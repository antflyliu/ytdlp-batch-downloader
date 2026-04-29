"""
monitor.fetcher — YouTube API 获取器
通过 ytb_api.YouTubeDataCollector 获取频道视频详情
"""
import os
import re
import sys
from collections.abc import Callable
from typing import Literal

from utils.paths import get_exe_dir

# Add project root to path for importing ytb_api
_project_root = get_exe_dir()
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import logging_config
import monitor.db as _db
from ytb_api import YouTubeDataCollector
from monitor import cache as channel_cache

_log = logging_config.get_logger("monitor.fetcher")

_YT_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)


def parse_youtube_duration(duration: str | None) -> int | None:
    """将 YouTube API 的 ISO 8601 时长转为秒。"""
    if not duration:
        return None

    match = _YT_DURATION_RE.fullmatch(duration)
    if not match:
        return None

    parts = {
        key: int(value) if value else 0
        for key, value in match.groupdict().items()
    }
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


class YouTubeFetcher:
    def __init__(
        self,
        api_key: str,
        fetch_mode: Literal["search", "playlist"] = "playlist",
        fetch_limit: int = 5,
        published_after_days: int | None = None,
        view_threshold: int = 0,
        proxy: str | None = None,
    ):
        self.api_key = api_key
        self.fetch_mode = fetch_mode
        self.fetch_limit = fetch_limit
        self.published_after_days = published_after_days
        self.view_threshold = view_threshold
        self.proxy = proxy

    def _make_youtube_collector(
        self,
        log_cb,
        should_cancel: Callable[[], bool] | None = None,
        **extra,
    ) -> YouTubeDataCollector:
        """构造与当前 Fetcher 参数一致的收集器；extra 可传 uploads_playlist_id 等。"""
        return YouTubeDataCollector(
            api_key=self.api_key,
            proxy=self.proxy,
            save_path=os.path.join(_project_root, "test_output"),
            logger_callback=log_cb,
            max_limit=self.fetch_limit,
            view_threshold=self.view_threshold,
            published_after_days=self.published_after_days,
            fetch_mode=self.fetch_mode,
            should_cancel=should_cancel,
            **extra,
        )

    @staticmethod
    def _channel_info_from_cache(cached: dict) -> dict:
        """从 channel_meta_cache 行构造与 get_channel_data 对齐的 channel_info 片段。"""
        return {
            "channel_id": cached["channel_id"],
            "channel_name": cached.get("channel_name"),
            "uploads_playlist_id": cached.get("uploads_playlist_id"),
            "subscriber_count": cached.get("subscriber_count"),
            "video_count": cached.get("video_count"),
            "description": cached.get("description"),
        }

    def _maybe_run_channel_meta_health_check(
        self,
        cfg: dict,
        cached: dict,
        channel_info: dict,
        channel_url: str,
        log_cb,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict:
        """
        P3-7：在配置允许且到达间隔时探针 uploads_playlist_id；不一致则刷新缓存并可告警。
        返回更新后的 channel_info（可能已重新 get_channel_data）。
        """
        if not cfg.get("channel_meta_health_check_enabled", True):
            return channel_info
        interval_h = float(cfg.get("channel_meta_health_check_interval_hours") or 24)
        if not channel_cache.should_run_uploads_health_check(cached, interval_h):
            return channel_info

        api = self._make_youtube_collector(log_cb, should_cancel=should_cancel)
        live_up = api.probe_uploads_playlist_id(channel_info["channel_id"])
        cached_up = channel_info.get("uploads_playlist_id")
        if live_up is not None and cached_up != live_up:
            _log.warning(
                f"缓存 uploads_playlist_id 与线上一致性校验失败: "
                f"缓存={cached_up!r} 线上={live_up!r}，重新拉取频道"
            )
            channel_info = api.get_channel_data(channel_url)
            if not channel_info:
                _log.error(f"健康检查失败后无法重新拉取频道信息: {channel_url}")
                return None
            channel_cache.save_channel_meta(
                handle=channel_url,
                channel_id=channel_info["channel_id"],
                channel_name=channel_info.get("channel_name"),
                uploads_playlist_id=channel_info.get("uploads_playlist_id"),
                subscriber_count=str(channel_info.get("subscriber_count", "")),
                video_count=str(channel_info.get("video_count", "")),
                description=channel_info.get("description"),
            )
            if cfg.get("notify_on_channel_meta_mismatch", True):
                try:
                    from monitor import quota as _quota

                    _quota.send_channel_meta_mismatch_alert(
                        channel_url=channel_url,
                        channel_id=channel_info["channel_id"],
                        cached_uploads_playlist_id=cached_up,
                        live_uploads_playlist_id=live_up,
                    )
                except Exception as notify_exc:
                    _log.warning(f"channel_meta 不一致告警发送失败: {notify_exc}")
            return channel_info

        if live_up is None:
            _log.warning(
                "频道元数据健康检查: channels.list 未返回 uploads，"
                "不更新 health_checked_at（下次扫描重试）"
            )
            return channel_info

        channel_cache.touch_channel_meta_health_checked(channel_url)
        return channel_info

    def fetch(
        self,
        channel_url: str,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[list[dict], dict | None]:
        """
        获取频道视频

        :param channel_url: 频道 URL (@xxx / UCxxxx / https://...)
        :param should_cancel: 可选；返回 True 时中止长时间 API 循环（如调度器已停止）。
        :return: (videos, channel_info)
                 videos: 视频列表，每条包含 video_id/title/url/published_at/view_count 等
                 channel_info: 频道元信息 dict
        """
        logs = []

        def log_cb(msg: str):
            logs.append(msg)

        try:
            cfg = _db.load_config()
            max_age = int(cfg.get("channel_meta_max_age_days") or 30)

            # ── 1. 尝试从缓存获取（未过期时）──────────────────
            cached = channel_cache.get_channel_meta(channel_url)
            if cached and not channel_cache.is_channel_meta_stale(cached, max_age):
                _log.info(f"缓存命中: {channel_url} → {cached['channel_id']}（0 API units）")
                channel_info = self._channel_info_from_cache(cached)
                channel_info = self._maybe_run_channel_meta_health_check(
                    cfg, cached, channel_info, channel_url, log_cb,
                    should_cancel=should_cancel,
                )
                if channel_info is None:
                    return [], None
            else:
                if cached and channel_cache.is_channel_meta_stale(cached, max_age):
                    _log.info(
                        f"频道元数据缓存已过期（>{max_age} 天），重新拉取: {channel_url}"
                    )
                # ── 2. 缓存未命中或已过期，调用 API ───────────────
                _log.info(f"拉取频道信息（API）: {channel_url}")
                channel_info = self._make_youtube_collector(
                    log_cb, should_cancel=should_cancel,
                ).get_channel_data(
                    channel_url
                )
                if not channel_info:
                    _log.error(f"无法获取频道信息: {channel_url}")
                    return [], None

                # 写入缓存
                channel_cache.save_channel_meta(
                    handle=channel_url,
                    channel_id=channel_info["channel_id"],
                    channel_name=channel_info.get("channel_name"),
                    uploads_playlist_id=channel_info.get("uploads_playlist_id"),
                    subscriber_count=str(channel_info.get("subscriber_count", "")),
                    video_count=str(channel_info.get("video_count", "")),
                    description=channel_info.get("description"),
                )

            # ── 3. 创建 collector 获取视频列表（带 uploads 绑定；与探针/元数据拉取分开以避免状态干扰）──
            collector = self._make_youtube_collector(
                log_cb,
                should_cancel=should_cancel,
                uploads_playlist_id=channel_info.get("uploads_playlist_id"),
                uploads_playlist_channel_id=channel_info["channel_id"],
            )

            # 获取视频列表
            raw_videos = collector.get_channel_videos(channel_info["channel_id"])

            # 标准化为统一格式
            videos = []
            for v in raw_videos:
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                content_details = v.get("contentDetails", {})
                videos.append({
                    "video_id": v.get("id", ""),
                    "channel_id": channel_info["channel_id"],
                    "channel_handle": channel_info.get("channel_name", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "url": f"https://www.youtube.com/watch?v={v.get('id', '')}",
                    "published_at": snippet.get("publishedAt", ""),
                    "upload_date": snippet.get("publishedAt", "")[:10] if snippet.get("publishedAt") else None,
                    "duration_sec": parse_youtube_duration(content_details.get("duration")),
                    "view_count": int(stats.get("viewCount", 0) or 0),
                    "like_count": int(stats.get("likeCount", 0) or 0),
                    "comment_count": int(stats.get("commentCount", 0) or 0),
                    "thumbnail_url": (
                        snippet.get("thumbnails", {})
                        .get("high", {})
                        .get("url")
                        or snippet.get("thumbnails", {})
                        .get("default", {})
                        .get("url", "")
                    ),
                    "fetched_at": snippet.get("publishedAt", ""),
                })

            _log.info(
                f"获取成功: 频道={channel_info['channel_name']} "
                f"视频数={len(videos)} 模式={self.fetch_mode}"
            )
            return videos, channel_info

        except Exception as e:
            _log.error(f"获取频道视频失败: {channel_url} — {e}")
            return [], None

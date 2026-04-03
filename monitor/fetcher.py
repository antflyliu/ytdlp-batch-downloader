"""
monitor.fetcher — YouTube API 获取器
通过 ytb_api.YouTubeDataCollector 获取频道视频详情
"""
import os
import sys
from typing import Literal

# 动态添加项目根目录到 path（确保能 import ytb_api）
# frozen 模式下 __file__ 在 _MEIPASS 内，需要从 exe_dir 向上找项目根
if getattr(sys, "frozen", False):
    # exe_dir/../ 向上找（dist/ -> 项目根）
    _monitor_dir = os.path.dirname(os.path.abspath(__file__))
    _meipass = sys._MEIPASS  # e.g. dist/YouTubeMonitor.exe/_MEIPASS/monitor/
    # 从 _MEIPASS/monitor 推出项目根
    _mon_offset = os.path.relpath(_monitor_dir, _meipass)  # 'monitor'
    _PROJECT_ROOT = _meipass.rsplit(_mon_offset, 1)[0].rstrip(os.sep)
    # 实际上是 exe 所在目录的父级
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(_monitor_dir))
else:
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logging_config
from ytb_api import YouTubeDataCollector
from monitor import cache as channel_cache

_log = logging_config.get_logger("monitor.fetcher")


class YouTubeFetcher:
    def __init__(
        self,
        api_key: str,
        fetch_mode: Literal["search", "playlist"] = "playlist",
        fetch_limit: int = 5,
        published_after_days: int | None = None,
        view_threshold: int = 0,
    ):
        self.api_key = api_key
        self.fetch_mode = fetch_mode
        self.fetch_limit = fetch_limit
        self.published_after_days = published_after_days
        self.view_threshold = view_threshold

    def fetch(self, channel_url: str) -> tuple[list[dict], dict | None]:
        """
        获取频道视频

        :param channel_url: 频道 URL (@xxx / UCxxxx / https://...)
        :return: (videos, channel_info)
                 videos: 视频列表，每条包含 video_id/title/url/published_at/view_count 等
                 channel_info: 频道元信息 dict
        """
        logs = []

        def log_cb(msg: str):
            logs.append(msg)

        try:
            # ── 1. 尝试从缓存获取 ──────────────────────────────
            cached = channel_cache.get_channel_meta(channel_url)
            if cached:
                _log.info(f"缓存命中: {channel_url} → {cached['channel_id']}（0 API units）")
                channel_info = {
                    "channel_id": cached["channel_id"],
                    "channel_name": cached.get("channel_name"),
                    "uploads_playlist_id": cached.get("uploads_playlist_id"),
                    "subscriber_count": cached.get("subscriber_count"),
                    "video_count": cached.get("video_count"),
                    "description": cached.get("description"),
                }
            else:
                # ── 2. 缓存未命中，调用 API ─────────────────────
                _log.info(f"缓存未命中，调用 API: {channel_url}")
                temp_collector = YouTubeDataCollector(
                    api_key=self.api_key,
                    save_path=os.path.join(_PROJECT_ROOT, "test_output"),
                    logger_callback=log_cb,
                    max_limit=self.fetch_limit,
                    view_threshold=self.view_threshold,
                    published_after_days=self.published_after_days,
                    fetch_mode=self.fetch_mode,
                )
                channel_info = temp_collector.get_channel_data(channel_url)
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

            # ── 3. 创建 collector 获取视频列表 ──────────────────
            collector = YouTubeDataCollector(
                api_key=self.api_key,
                save_path=os.path.join(_PROJECT_ROOT, "test_output"),
                logger_callback=log_cb,
                max_limit=self.fetch_limit,
                view_threshold=self.view_threshold,
                published_after_days=self.published_after_days,
                fetch_mode=self.fetch_mode,
                uploads_playlist_id=channel_info.get("uploads_playlist_id"),
            )

            # 获取视频列表
            raw_videos = collector.get_channel_videos(channel_info["channel_id"])

            # 标准化为统一格式
            videos = []
            for v in raw_videos:
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                videos.append({
                    "video_id": v.get("id", ""),
                    "channel_id": channel_info["channel_id"],
                    "channel_handle": channel_info.get("channel_name", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "url": f"https://www.youtube.com/watch?v={v.get('id', '')}",
                    "published_at": snippet.get("publishedAt", ""),
                    "upload_date": snippet.get("publishedAt", "")[:10] if snippet.get("publishedAt") else None,
                    "duration_sec": None,
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

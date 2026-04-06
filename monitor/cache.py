"""
monitor.cache — YouTube 频道元信息缓存
handle → channel_id + uploads_playlist_id 持久化缓存，减少 API 调用

内部使用 SQLAlchemy Core（通过 monitor.database 统一引擎）。
"""
import logging
import os
import sys
from datetime import datetime

from sqlalchemy import select

from monitor.database import (
    get_connection,
    create_all_tables,
    make_upsert,
    t_channel_meta_cache,
    t_monitor_videos,
)

_log = logging.getLogger("monitor.cache")


def _ensure_schema():
    """确保 channel_meta_cache 和 monitor_videos 下载状态列存在。

    由 create_all_tables() 处理全部表创建，此函数仅作为向后兼容
    入口，不再自行管理 sqlite3 连接。
    """
    create_all_tables()


def _normalize_handle(raw: str) -> str:
    """统一 handle 格式：去除前导 @、URL scheme、路径

    @MrBeast             → MrBeast
    https://.../@MrBeast → MrBeast
    UCxxxxx              → UCxxxxx（直接返回）
    """
    raw = raw.strip()
    if "://" in raw:
        raw = raw.split("/", 3)[-1]
    if "/" in raw:
        raw = raw.rstrip("/").rsplit("/", 1)[-1]
    return raw.lstrip("@")


def get_channel_meta(handle: str) -> dict | None:
    """根据 handle 查询缓存

    :param handle: 用户输入（@xxx / URL / UCxxxx）
    :return: 缓存记录 dict 或 None
    """
    normalized = _normalize_handle(handle)
    cmc = t_channel_meta_cache
    try:
        with get_connection() as conn:
            row = conn.execute(
                select(cmc).where(cmc.c.handle == normalized)
            ).mappings().fetchone()
            if row:
                return dict(row)
            if normalized.startswith("UC"):
                row = conn.execute(
                    select(cmc).where(cmc.c.channel_id == normalized)
                ).mappings().fetchone()
                if row:
                    return dict(row)
            return None
    except Exception as e:
        _log.warning("查询 channel_meta_cache 失败: %s", e)
        return None


def save_channel_meta(
    handle: str,
    channel_id: str,
    channel_name: str | None = None,
    uploads_playlist_id: str | None = None,
    subscriber_count: str | None = None,
    video_count: str | None = None,
    description: str | None = None,
) -> None:
    """写入/更新缓存"""
    normalized = _normalize_handle(handle)
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    stmt = make_upsert(
        t_channel_meta_cache,
        index_elements=["handle"],
        update_columns=[
            "channel_id",
            "channel_name",
            "uploads_playlist_id",
            "subscriber_count",
            "video_count",
            "description",
            "cached_at",
        ],
    )
    try:
        with get_connection() as conn:
            conn.execute(
                stmt,
                {
                    "handle": normalized,
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "uploads_playlist_id": uploads_playlist_id,
                    "subscriber_count": subscriber_count,
                    "video_count": video_count,
                    "description": description,
                    "cached_at": cached_at,
                },
            )
        _log.info("缓存已保存: %s → %s", normalized, channel_id)
    except Exception as e:
        _log.warning("保存 channel_meta_cache 失败: %s", e)


def delete_channel_meta(handle: str) -> bool:
    """删除指定缓存"""
    normalized = _normalize_handle(handle)
    cmc = t_channel_meta_cache
    try:
        with get_connection() as conn:
            result = conn.execute(
                cmc.delete().where(cmc.c.handle == normalized)
            )
        return result.rowcount > 0
    except Exception as e:
        _log.warning("删除 channel_meta_cache 失败: %s", e)
        return False


def delete_by_channel_id(channel_id: str) -> bool:
    """通过 channel_id 删除缓存"""
    cmc = t_channel_meta_cache
    try:
        with get_connection() as conn:
            result = conn.execute(
                cmc.delete().where(cmc.c.channel_id == channel_id)
            )
        return result.rowcount > 0
    except Exception as e:
        _log.warning("删除 channel_meta_cache 失败: %s", e)
        return False


def list_all_cache() -> list[dict]:
    """列出所有缓存"""
    cmc = t_channel_meta_cache
    try:
        with get_connection() as conn:
            rows = conn.execute(
                select(cmc).order_by(cmc.c.cached_at.desc())
            ).mappings().all()
            return [dict(row) for row in rows]
    except Exception as e:
        _log.warning("查询所有缓存失败: %s", e)
        return []


def clear_all_cache() -> int:
    """清空所有缓存，返回删除数量"""
    cmc = t_channel_meta_cache
    try:
        with get_connection() as conn:
            result = conn.execute(cmc.delete())
        _log.info("已清空所有缓存 (%d 条)", result.rowcount)
        return result.rowcount
    except Exception as e:
        _log.warning("清空缓存失败: %s", e)
        return 0


def refresh_from_api(handle: str, api_key: str, http_proxy: str | None = None) -> dict:
    """从 API 重新获取频道元信息并更新缓存

    :return: {"success": bool, "cached": dict, "error": str|None}
    """
    _normalize_handle(handle)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from ytb_api import YouTubeDataCollector

        collector = YouTubeDataCollector(
            api_key=api_key,
            save_path=os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "test_output",
            ),
            proxy=http_proxy,
        )

        channel_info = collector.get_channel_data(handle)
        if not channel_info:
            return {"success": False, "cached": None, "error": "无法获取频道信息"}

        save_channel_meta(
            handle=handle,
            channel_id=channel_info["channel_id"],
            channel_name=channel_info.get("channel_name"),
            uploads_playlist_id=channel_info.get("uploads_playlist_id"),
            subscriber_count=str(channel_info.get("subscriber_count", "")),
            video_count=str(channel_info.get("video_count", "")),
            description=channel_info.get("description"),
        )

        return {"success": True, "cached": get_channel_meta(handle), "error": None}

    except Exception as e:
        _log.error("刷新缓存失败: %s — %s", handle, e)
        return {"success": False, "cached": None, "error": str(e)}

"""
monitor.cache — YouTube 频道元信息缓存
handle → channel_id + uploads_playlist_id 持久化缓存，减少 API 调用
"""
import logging
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone

from utils.paths import get_data_dir, get_db_path

_DATA_DIR = get_data_dir()
_DB_PATH = get_db_path()
_log = logging.getLogger("monitor.cache")

# ── 确保数据库 schema 初始化（创建 channel_meta_cache 表）───────
def _ensure_schema():
    """创建 channel_meta_cache 表（如不存在）"""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_meta_cache (
                handle              TEXT PRIMARY KEY,
                channel_id          TEXT NOT NULL,
                channel_name        TEXT,
                uploads_playlist_id TEXT,
                subscriber_count    TEXT,
                video_count         TEXT,
                description         TEXT,
                cached_at           TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_channel_cache_channel_id
            ON channel_meta_cache(channel_id)
        """)

        _migrate_channel_meta_health_checked_at(conn)

        # ── Schema 迁移：为 monitor_videos 添加下载状态字段（如不存在）────
        _migrate_monitor_videos(conn)

        conn.commit()
    except Exception as e:
        _log.warning(f"_ensure_schema 失败: {e}")
    finally:
        conn.close()


def _migrate_channel_meta_health_checked_at(conn):
    """为 channel_meta_cache 增加 health_checked_at（uploads 健康检查时间）"""
    try:
        cur = conn.execute("PRAGMA table_info(channel_meta_cache)")
        cols = {row[1] for row in cur.fetchall()}
        if "health_checked_at" not in cols:
            conn.execute(
                "ALTER TABLE channel_meta_cache ADD COLUMN health_checked_at TEXT"
            )
            _log.info("Schema 迁移成功: channel_meta_cache.health_checked_at")
    except Exception as e:
        _log.warning(f"_migrate_channel_meta_health_checked_at 失败: {e}")


def _migrate_monitor_videos(conn):
    """检查并添加 monitor_videos 新字段"""
    try:
        # 检查列是否存在
        cur = conn.execute("PRAGMA table_info(monitor_videos)")
        existing_cols = {row[1] for row in cur.fetchall()}
        migrations = []
        if "download_status" not in existing_cols:
            migrations.append("ADD COLUMN download_status TEXT NOT NULL DEFAULT 'pending'")
        if "download_at" not in existing_cols:
            migrations.append("ADD COLUMN download_at TEXT")
        if "download_path" not in existing_cols:
            migrations.append("ADD COLUMN download_path TEXT")
        if "download_error" not in existing_cols:
            migrations.append("ADD COLUMN download_error TEXT")
        for mig in migrations:
            conn.execute(f"ALTER TABLE monitor_videos {mig}")
            _log.info(f"Schema 迁移成功: monitor_videos {mig}")
    except Exception as e:
        _log.warning(f"_migrate_monitor_videos 失败: {e}")

_ensure_schema()


def _get_conn():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_handle(raw: str) -> str:
    """
    统一 handle 格式：去除前导 @、URL scheme、路径
    @MrBeast       → MrBeast
    https://.../@MrBeast → MrBeast
    UCxxxxx        → UCxxxxx（直接返回）
    """
    raw = raw.strip()
    # 去除 URL scheme
    if "://" in raw:
        raw = raw.split("/", 3)[-1]
    # 去除路径
    if "/" in raw:
        raw = raw.rstrip("/").rsplit("/", 1)[-1]
    # 去除前导 @
    return raw.lstrip("@")


def is_channel_meta_stale(cached: dict | None, max_age_days: int) -> bool:
    """
    判断 channel_meta_cache 行是否超过 TTL，应重新拉取 channels 元数据。

    :param cached: get_channel_meta 返回的 dict，或 None
    :param max_age_days: 最大保留天数；<=0 表示不按 TTL 过期（始终视为未过期）
    """
    if not cached or max_age_days <= 0:
        return False
    raw = cached.get("cached_at")
    if not raw:
        return True
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(dt.tzinfo)
        return (now - dt) >= timedelta(days=max_age_days)
    except Exception:
        _log.warning("解析 cached_at 失败，将刷新频道元数据: %s", raw)
        return True


def should_run_uploads_health_check(cached: dict, interval_hours: float) -> bool:
    """
    是否应执行 uploads_playlist_id 与线上一致性检查。
    :param interval_hours: 两次检查最小间隔；<=0 时按 24 小时处理

    无 ``health_checked_at``（例如迁移旧库）时，用 ``cached_at`` 作为上次“元数据相关”时间，
    避免迁移后每次扫描都触发探针。
    """
    if interval_hours <= 0:
        interval_hours = 24.0
    raw = cached.get("health_checked_at") or cached.get("cached_at")
    if not raw:
        return True
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(dt.tzinfo)
        return (now - dt) >= timedelta(hours=interval_hours)
    except Exception:
        return True


def touch_channel_meta_health_checked(handle: str) -> None:
    """更新 health_checked_at 为当前时间（校验通过或跳过失败重试时使用）。"""
    normalized = _normalize_handle(handle)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute(
                "UPDATE channel_meta_cache SET health_checked_at=? WHERE handle=?",
                (now, normalized),
            )
    except Exception as e:
        _log.warning(f"touch_channel_meta_health_checked 失败: {e}")


def get_channel_meta(handle: str) -> dict | None:
    """
    根据 handle 查询缓存
    :param handle: 用户输入（@xxx / URL / UCxxxx）
    :return: 缓存记录 dict 或 None
    """
    normalized = _normalize_handle(handle)
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM channel_meta_cache WHERE handle=?",
                (normalized,),
            ).fetchone()
            if row:
                return dict(row)
            # 也尝试 channel_id 直接查询（用户可能输入的是 UCxxxx）
            if normalized.startswith("UC"):
                row = conn.execute(
                    "SELECT * FROM channel_meta_cache WHERE channel_id=?",
                    (normalized,),
                ).fetchone()
                if row:
                    return dict(row)
            return None
    except Exception as e:
        _log.warning(f"查询 channel_meta_cache 失败: {e}")
        return None


def save_channel_meta(
    handle: str,
    channel_id: str,
    channel_name: str | None = None,
    uploads_playlist_id: str | None = None,
    subscriber_count: str | None = None,
    video_count: str | None = None,
    description: str | None = None,
    health_checked_at: str | None = None,
) -> None:
    """
    写入/更新缓存
    """
    normalized = _normalize_handle(handle)
    from datetime import datetime
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    if health_checked_at is None:
        health_checked_at = cached_at
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO channel_meta_cache
                   (handle, channel_id, channel_name, uploads_playlist_id,
                    subscriber_count, video_count, description, cached_at, health_checked_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (normalized, channel_id, channel_name, uploads_playlist_id,
                 subscriber_count, video_count, description, cached_at, health_checked_at),
            )
        _log.info(f"缓存已保存: {normalized} → {channel_id}")
    except Exception as e:
        _log.warning(f"保存 channel_meta_cache 失败: {e}")


def delete_channel_meta(handle: str) -> bool:
    """删除指定缓存"""
    normalized = _normalize_handle(handle)
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM channel_meta_cache WHERE handle=?",
                (normalized,),
            )
        return cur.rowcount > 0
    except Exception as e:
        _log.warning(f"删除 channel_meta_cache 失败: {e}")
        return False


def delete_by_channel_id(channel_id: str) -> bool:
    """通过 channel_id 删除缓存"""
    try:
        with _get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM channel_meta_cache WHERE channel_id=?",
                (channel_id,),
            )
        return cur.rowcount > 0
    except Exception as e:
        _log.warning(f"删除 channel_meta_cache 失败: {e}")
        return False


def list_all_cache() -> list[dict]:
    """列出所有缓存"""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM channel_meta_cache ORDER BY cached_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        _log.warning(f"查询所有缓存失败: {e}")
        return []


def clear_all_cache() -> int:
    """清空所有缓存，返回删除数量"""
    try:
        with _get_conn() as conn:
            cur = conn.execute("DELETE FROM channel_meta_cache")
        _log.info(f"已清空所有缓存 ({cur.rowcount} 条)")
        return cur.rowcount
    except Exception as e:
        _log.warning(f"清空缓存失败: {e}")
        return 0


def refresh_from_api(handle: str, api_key: str, http_proxy: str | None = None) -> dict:
    """
    从 API 重新获取频道元信息并更新缓存
    :return: {"success": bool, "cached": dict, "error": str|None}
    """
    normalized = _normalize_handle(handle)

    # 动态 import 避免循环
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from ytb_api import YouTubeDataCollector

        collector = YouTubeDataCollector(
            api_key=api_key,
            save_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_output"),
            proxy=http_proxy,
        )

        # 先尝试用 handle 解析
        channel_info = collector.get_channel_data(handle)
        if not channel_info:
            return {"success": False, "cached": None, "error": "无法获取频道信息"}

        # 保存到缓存
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
        _log.error(f"刷新缓存失败: {handle} — {e}")
        return {"success": False, "cached": None, "error": str(e)}

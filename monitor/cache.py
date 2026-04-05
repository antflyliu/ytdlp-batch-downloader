"""
monitor.cache — YouTube 频道元信息缓存
handle → channel_id + uploads_playlist_id 持久化缓存，减少 API 调用
"""
import logging
import os
import sys

# 动态路径（与 monitor/db.py 保持一致）
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _PKG_DIR

_DATA_DIR = os.path.join(_EXE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

# 内部使用 sqlite，直接操作不通过 db.py（避免循环 import）
import sqlite3

# ★ _DB_PATH 和 _log 必须在模块加载早期定义（_ensure_schema 调用前就需要）
_DB_PATH = os.path.join(_DATA_DIR, "monitor.db")
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

        # ── Schema 迁移：为 monitor_videos 添加下载状态字段（如不存在）────
        _migrate_monitor_videos(conn)

        conn.commit()
    except Exception as e:
        _log.warning(f"_ensure_schema 失败: {e}")
    finally:
        conn.close()


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
) -> None:
    """
    写入/更新缓存
    """
    normalized = _normalize_handle(handle)
    from datetime import datetime
    cached_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO channel_meta_cache
                   (handle, channel_id, channel_name, uploads_playlist_id,
                    subscriber_count, video_count, description, cached_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (normalized, channel_id, channel_name, uploads_playlist_id,
                 subscriber_count, video_count, description, cached_at),
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

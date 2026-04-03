"""
monitor.db — Monitor 数据库初始化与访问助手
"""
import json
import os
import sys
import sqlite3
import threading
from datetime import datetime, timezone
from contextlib import contextmanager

# ── PyInstaller 兼容路径 ──────────────────────────────────────
# exe 内：sys._MEIPASS/...；源码：__file__/...
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")   # 打包资源目录
    _EXE_DIR = os.path.dirname(sys.executable)           # exe 所在目录（写用户数据）
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _PKG_DIR

_DATA_DIR = os.path.join(_EXE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

_DB_PATH = os.path.join(_DATA_DIR, "monitor.db")
_SCHEMA_PATH = os.path.join(_PKG_DIR, "schema.sql")
# config.json: 优先用户可写位置(exe_dir)，回退到只读资源(_PKG_DIR)
_CONFIG_PATH = os.path.join(_EXE_DIR, "config.json")


def _config_default() -> dict:
    """默认的全局配置"""
    return {
        "global_feishu_url": "",
        "global_dingtalk_url": "",
        "global_wecom_url": "",
        "default_fetch_mode": "playlist",
        "default_fetch_limit": 5,
        "default_scan_interval": 5,
        "quota_budget_per_day": 8000,
        "download_cookies_file": "",
        "download_output_path": "",
    }


def get_db_path() -> str:
    return _DB_PATH


def get_config_path() -> str:
    """返回 config.json 路径（优先 exe 同目录下，用户可写）"""
    return _CONFIG_PATH


def load_config() -> dict:
    """加载全局配置（支持 PyInstaller exe 和源码两种模式）"""
    # 优先读用户可写位置
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # 回退：读打包资源（PyInstaller exe 模式下为 _MEIPASS/monitor/config.json）
    pkg_cfg = os.path.join(_PKG_DIR, "config.json")
    if os.path.exists(pkg_cfg):
        with open(pkg_cfg, "r", encoding="utf-8") as f:
            return json.load(f)
    return _config_default()


def init_db() -> None:
    """初始化数据库，创建表（如不存在）"""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    with get_connection() as conn:
        conn.executescript(schema)
        _migrate_monitor_accounts(conn)


def _migrate_monitor_accounts(conn) -> None:
    """对老数据库迁移补列（PRAGMA table_info 方式，兼容已有数据）"""
    cur = conn.execute("PRAGMA table_info(monitor_accounts)")
    cols = {row[1] for row in cur.fetchall()}
    migrations = []
    if "feishu_message_mode" not in cols:
        migrations.append("ADD COLUMN feishu_message_mode TEXT NOT NULL DEFAULT 'card_json'")
    if "feishu_template_id" not in cols:
        migrations.append("ADD COLUMN feishu_template_id TEXT")
    if "feishu_scan_template_id" not in cols:
        migrations.append("ADD COLUMN feishu_scan_template_id TEXT")
    for mig in migrations:
        conn.execute(f"ALTER TABLE monitor_accounts {mig}")


@contextmanager
def get_connection():
    """线程安全的数据库连接上下文管理器"""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── monitor_accounts CRUD ─────────────────────────────────

def list_accounts(enabled_only: bool = False) -> list[dict]:
    with get_connection() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM monitor_accounts WHERE enabled=1 ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM monitor_accounts ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]


def get_account(account_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_accounts WHERE id=?", (account_id,)
        ).fetchone()
        return dict(row) if row else None


def add_account(
    name: str,
    channel_url: str,
    api_key_env: str,
    fetch_mode: str = "playlist",
    fetch_limit: int = 5,
    scan_interval: int = 5,
    notify_enabled: bool = True,
    notify_platform: str = "feishu",
    webhook_url: str | None = None,
    feishu_message_mode: str = "card_json",
    feishu_template_id: str | None = None,
    feishu_scan_template_id: str | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitor_accounts
               (name, channel_url, api_key_env, fetch_mode, fetch_limit,
                scan_interval, enabled, notify_enabled, notify_platform, webhook_url,
                feishu_message_mode, feishu_template_id, feishu_scan_template_id,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)""",
            (name, channel_url, api_key_env, fetch_mode, fetch_limit,
             scan_interval, int(notify_enabled), notify_platform, webhook_url,
             feishu_message_mode, feishu_template_id, feishu_scan_template_id,
             now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_account(
    account_id: int,
    name: str | None = None,
    channel_url: str | None = None,
    api_key_env: str | None = None,
    fetch_mode: str | None = None,
    fetch_limit: int | None = None,
    scan_interval: int | None = None,
    enabled: bool | None = None,
    notify_enabled: bool | None = None,
    notify_platform: str | None = None,
    webhook_url: str | None = None,
    feishu_message_mode: str | None = None,
    feishu_template_id: str | None = None,
    feishu_scan_template_id: str | None = None,
) -> None:
    fields, values = [], []
    if name             is not None: fields.append("name=?");             values.append(name)
    if channel_url      is not None: fields.append("channel_url=?");      values.append(channel_url)
    if api_key_env      is not None: fields.append("api_key_env=?");      values.append(api_key_env)
    if fetch_mode       is not None: fields.append("fetch_mode=?");       values.append(fetch_mode)
    if fetch_limit      is not None: fields.append("fetch_limit=?");      values.append(fetch_limit)
    if scan_interval    is not None: fields.append("scan_interval=?");    values.append(scan_interval)
    if enabled          is not None: fields.append("enabled=?");          values.append(int(enabled))
    if notify_enabled   is not None: fields.append("notify_enabled=?");   values.append(int(notify_enabled))
    if notify_platform  is not None: fields.append("notify_platform=?");  values.append(notify_platform)
    if webhook_url     is not None: fields.append("webhook_url=?");     values.append(webhook_url)
    if feishu_message_mode is not None: fields.append("feishu_message_mode=?"); values.append(feishu_message_mode)
    if feishu_template_id is not None: fields.append("feishu_template_id=?"); values.append(feishu_template_id)
    if feishu_scan_template_id is not None: fields.append("feishu_scan_template_id=?"); values.append(feishu_scan_template_id)
    fields.append("updated_at=?"); values.append(now_iso())
    values.append(account_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE monitor_accounts SET {','.join(fields)} WHERE id=?", values)


def delete_account(account_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM monitor_accounts WHERE id=?", (account_id,))


# ── monitor_events CRUD ───────────────────────────────────

def create_event(account_id: int, account_name: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitor_events
               (account_id, account_name, scan_started_at, status, total_videos, new_videos)
               VALUES (?,?,?,?,0,0)""",
            (account_id, account_name, now_iso(), "running"),
        )
        return cur.lastrowid


def finish_event(
    event_id: int,
    status: str,
    total_videos: int,
    new_videos: int,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_events SET
               scan_ended_at=?, status=?, total_videos=?, new_videos=?,
               error_message=?, duration_ms=?
               WHERE id=?""",
            (now_iso(), status, total_videos, new_videos, error_message, duration_ms, event_id),
        )


# ── monitor_videos CRUD ──────────────────────────────────

def insert_videos(
    videos: list[dict],
    account_id: int,
    event_id: int,
) -> int:
    """
    批量插入视频，返回实际插入数量（UNIQUE 冲突的会被忽略）
    """
    if not videos:
        return 0
    now = now_iso()
    with get_connection() as conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO monitor_videos
               (video_id, account_id, event_id, channel_id, channel_handle,
                title, description, url, published_at, upload_date, duration_sec,
                view_count, like_count, comment_count, thumbnail_url,
                fetched_at, notify_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    v["video_id"],
                    account_id,
                    event_id,
                    v.get("channel_id"),
                    v.get("channel_handle"),
                    v["title"],
                    v.get("description", ""),
                    v["url"],
                    v.get("published_at", ""),
                    v.get("upload_date"),
                    v.get("duration_sec"),
                    v.get("view_count"),
                    v.get("like_count"),
                    v.get("comment_count"),
                    v.get("thumbnail_url"),
                    v.get("fetched_at", now),
                    "pending",
                    now,
                )
                for v in videos
            ],
        )
        return cur.rowcount


def get_new_video_ids(new_videos: list[dict]) -> set[str]:
    """
    从新获取的视频列表中，找出不在 monitor_videos 表中的 video_id
    """
    if not new_videos:
        return set()
    vid_list = [v["video_id"] for v in new_videos]
    placeholders = ",".join("?" * len(vid_list))
    with get_connection() as conn:
        existing = {
            r[0] for r in conn.execute(
                f"SELECT video_id FROM monitor_videos WHERE video_id IN ({placeholders})",
                vid_list,
            ).fetchall()
        }
    return {vid for vid in vid_list if vid not in existing}


def mark_notify_sent(video_ids: list[str], sent_at: str | None = None) -> None:
    if not video_ids:
        return
    sent_at = sent_at or now_iso()
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monitor_videos SET notify_status='sent', notify_sent_at=? "
            f"WHERE video_id IN ({placeholders})",
            [sent_at] + video_ids,
        )


def mark_notify_failed(video_ids: list[str], error: str) -> None:
    if not video_ids:
        return
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monitor_videos SET notify_status='failed', notify_error=? "
            f"WHERE video_id IN ({placeholders})",
            [error] + video_ids,
        )


# ── 统计查询 ──────────────────────────────────────────────

def get_account_stats() -> list[dict]:
    """返回每个账户的统计：总扫描次数、新视频数、最后扫描时间"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                ma.id, ma.name, ma.channel_url, ma.enabled, ma.scan_interval,
                ma.fetch_limit, ma.fetch_mode, ma.notify_enabled,
                COUNT(me.id) AS total_scans,
                COALESCE(SUM(me.new_videos), 0) AS total_new_videos,
                MAX(me.scan_started_at) AS last_scan_at,
                MAX(CASE WHEN me.status='running' THEN 1 ELSE 0 END) AS is_running
               FROM monitor_accounts ma
               LEFT JOIN monitor_events me ON ma.id = me.account_id
               GROUP BY ma.id
               ORDER BY ma.id"""
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_events(limit: int = 50) -> list[dict]:
    """返回最近的扫描事件"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT me.*, ma.name AS account_name, ma.channel_url
               FROM monitor_events me
               JOIN monitor_accounts ma ON me.account_id = ma.id
               ORDER BY me.scan_started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_notify_videos(event_id: int) -> list[dict]:
    """获取某个事件中待通知的视频"""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM monitor_videos
               WHERE event_id=? AND notify_status='pending'
               ORDER BY published_at DESC""",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── 视频查询 ──────────────────────────────────────────────

def get_account_videos(
    account_id: int,
    title_kw: str | None = None,
    url_kw: str | None = None,
    sort_by: str = "published_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    分页查询账户视频列表，支持搜索和排序
    :return: (videos, total_count)
    """
    # 允许的排序字段（防注入）
    ALLOWED_SORT = {
        "published_at": "published_at",
        "view_count": "view_count",
        "like_count": "like_count",
        "comment_count": "comment_count",
    }
    order_col = ALLOWED_SORT.get(sort_by, "published_at")
    order_dir = "DESC" if sort_dir == "desc" else "ASC"

    where_clauses = ["account_id = ?"]
    params: list = [account_id]

    if title_kw:
        where_clauses.append("title LIKE ?")
        params.append(f"%{title_kw}%")
    if url_kw:
        where_clauses.append("url LIKE ?")
        params.append(f"%{url_kw}%")

    where_sql = " AND ".join(where_clauses)

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM monitor_videos WHERE {where_sql}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""SELECT
                id, video_id, title, description, url,
                published_at, upload_date, duration_sec,
                view_count, like_count, comment_count,
                notify_status, download_status, download_at, download_path,
                fetched_at
               FROM monitor_videos
               WHERE {where_sql}
               ORDER BY {order_col} {order_dir}
               LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total


def update_videos_download_status(
    video_ids: list[int],
    status: str,
    download_at: str | None = None,
    download_path: str | None = None,
    download_error: str | None = None,
) -> int:
    """批量更新视频下载状态"""
    if not video_ids:
        return 0
    placeholders = ",".join("?" * len(video_ids))
    fields = ["download_status = ?"]
    values: list = [status]
    if download_at:
        fields.append("download_at = ?")
        values.append(download_at)
    if download_path:
        fields.append("download_path = ?")
        values.append(download_path)
    if download_error:
        fields.append("download_error = ?")
        values.append(download_error)
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE monitor_videos SET {', '.join(fields)} WHERE id IN ({placeholders})",
            values + video_ids,
        )
        return cur.rowcount


def get_videos_by_ids(video_ids: list[int]) -> list[dict]:
    """根据 monitor_videos.id 列表查询视频记录（含 url, title 等）"""
    if not video_ids:
        return []
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT id, video_id, title, url, download_status
                FROM monitor_videos WHERE id IN ({placeholders})""",
            video_ids,
        ).fetchall()
        return [dict(r) for r in rows]


# ── 调度状态（存 DB，不用内存变量，避免进程重启丢失）─────

def get_scheduler_state() -> dict:
    """返回调度器的运行状态"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='scheduler_state'"
        ).fetchone()
        if row:
            import json
            return json.loads(row[0])
        return {"running": False, "started_at": None}


def set_scheduler_state(state: dict) -> None:
    import json
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO app_state (key, value) VALUES ('scheduler_state', ?)""",
            (json.dumps(state),),
        )


# 确保 app_state 表存在（懒创建）
def ensure_app_state_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )

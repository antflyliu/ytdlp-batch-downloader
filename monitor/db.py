"""
monitor.db — Monitor 数据库初始化与访问助手
"""
import json
import os
import sys
import sqlite3
from datetime import datetime
from contextlib import contextmanager

import logging_config
_log = logging_config.get_logger("monitor.db")

# 哨兵值：区分 update_account 中「参数未传入」和「显式传 None 清空字段」
_UNSET = type("_Unset", (), {"__repr__": lambda s: "<UNSET>", "__bool__": lambda s: False})()

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
        "default_sub_langs": "zh-Hans,en",
        "default_api_key_id": None,   # 系统默认 API Key（账户未指定时使用）
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
        _ensure_schema_migrations(conn)
        _migrate_monitor_accounts(conn)
    # 同步初始化 quota 表
    import monitor.quota as _quota
    _quota._ensure_schema()


def _ensure_schema_migrations(conn) -> None:
    """确保 schema_migrations 表存在"""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )"""
    )


def _migrate_monitor_accounts(conn) -> None:
    """对老数据库迁移补列（基于 schema_migrations 版本追踪，幂等）"""
    applied = set(
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    )
    today = _today_str()

    # v1: api_key_id 列
    if "v1_api_key_id" not in applied:
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "api_key_id" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN api_key_id INTEGER DEFAULT NULL"
            )
            _migrate_legacy_api_keys(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v1_api_key_id", today),
        )

    # v2: feishu 扩展列
    if "v2_feishu_ext" not in applied:
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        for col, ddl in [
            ("feishu_message_mode", "TEXT NOT NULL DEFAULT 'card_json'"),
            ("feishu_template_id", "TEXT"),
            ("feishu_scan_template_id", "TEXT"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE monitor_accounts ADD COLUMN {col} {ddl}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v2_feishu_ext", today),
        )

    # v3: api_quota_usage.api_key_env → api_key_value 列重命名
    if "v3_quota_col_rename" not in applied:
        cur = conn.execute("PRAGMA table_info(api_quota_usage)")
        cols = {row[1] for row in cur.fetchall()}
        if "api_key_env" in cols and "api_key_value" not in cols:
            conn.execute("ALTER TABLE api_quota_usage RENAME COLUMN api_key_env TO api_key_value")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v3_quota_col_rename", today),
        )

    # v4: webhook_url 加密（明文 → enc:... 格式）
    if "v4_webhook_encrypt" not in applied:
        rows = conn.execute(
            "SELECT id, webhook_url FROM monitor_accounts "
            "WHERE webhook_url IS NOT NULL AND webhook_url != '' AND webhook_url NOT LIKE 'enc:%'"
        ).fetchall()
        for row in rows:
            acct_id, url = row
            if url and not url.startswith("enc:"):
                encrypted = _encrypt_webhook(url)
                conn.execute(
                    "UPDATE monitor_accounts SET webhook_url=? WHERE id=?",
                    (encrypted, acct_id),
                )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v4_webhook_encrypt", today),
        )


def _migrate_legacy_api_keys(conn) -> None:
    """从已有的 monitor_accounts.api_key_env 环境变量名迁移 Key 到 api_keys 表"""
    rows = conn.execute(
        "SELECT DISTINCT api_key_env FROM monitor_accounts WHERE api_key_env IS NOT NULL"
    ).fetchall()
    for row in rows:
        env_name = row[0]
        key_value = os.environ.get(env_name, "")
        if key_value:
            # 写入 api_keys 表（忽略已存在）
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO api_keys
                       (key_value, name, daily_quota, quota_used, quota_reset_at,
                        is_active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (key_value, env_name, 10000, 0, _today_str(),
                     1, now_iso(), now_iso()),
                )
            except sqlite3.IntegrityError:
                pass  # Key 已存在，忽略
            except Exception:
                _log.warning(f"Migration: 迁移 api_key_env={env_name} 失败: {e}")


@contextmanager
def get_connection():
    """线程安全的数据库连接上下文管理器（启用 WAL 模式 + 外键约束）"""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
    """当前本地时间的 ISO 8601 字符串（含时区偏移，如 +08:00）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today_str() -> str:
    """当前本地日期字符串 (YYYY-MM-DD)。"""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


# ── api_keys CRUD ─────────────────────────────────────────

def list_api_keys() -> list[dict]:
    """列出所有 API Key（含今日配额使用情况）"""
    today = _today_str()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ak.*,
                      COALESCE(aqu.api_calls, 0) AS quota_used,
                      aqu.scans_done,
                      aqu.blocked_scans
               FROM api_keys ak
               LEFT JOIN api_quota_usage aqu
                 ON aqu.api_key_value = ak.key_value
                AND aqu.date_key = ?
               ORDER BY ak.id""",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_api_key(key_id: int) -> dict | None:
    """获取单个 API Key"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE id=?", (key_id,)
        ).fetchone()
        return dict(row) if row else None


def get_api_key_by_value(key_value: str) -> dict | None:
    """通过 Key 值查找"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_value=?", (key_value,)
        ).fetchone()
        return dict(row) if row else None


def add_api_key(
    key_value: str,
    name: str,
    daily_quota: int = 10000,
) -> int:
    """新增 API Key"""
    today = _today_str()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO api_keys
               (key_value, name, daily_quota, quota_used, quota_reset_at,
                is_active, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, 1, ?, ?)""",
            (key_value, name, daily_quota, today, now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_api_key(
    key_id: int,
    name: str | None = None,
    key_value: str | None = None,
    daily_quota: int | None = None,
    is_active: bool | None = None,
) -> None:
    """更新 API Key"""
    fields, values = [], []
    if name is not None:        fields.append("name=?");          values.append(name)
    # 空字符串表示"不修改"（前端留空时发送空字符串）
    if key_value:               fields.append("key_value=?");     values.append(key_value)
    if daily_quota is not None: fields.append("daily_quota=?"); values.append(daily_quota)
    if is_active is not None:  fields.append("is_active=?");    values.append(int(is_active))
    fields.append("updated_at=?"); values.append(now_iso())
    values.append(key_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE api_keys SET {','.join(fields)} WHERE id=?", values)


def delete_api_key(key_id: int) -> None:
    """删除 API Key（关联的账户 api_key_id 会被 SET NULL）"""
    with get_connection() as conn:
        conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))


def incr_api_key_quota(key_value: str, calls: int = 1, scans: int = 0) -> None:
    """增加 API Key 的配额使用"""
    import monitor.quota as _quota
    _quota.incr(key_value, calls=calls, scans=scans)


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
        return [_decrypt_account_webhook(dict(r)) for r in rows]


def _decrypt_account_webhook(account: dict) -> dict:
    """解密账户的 webhook_url"""
    if account and account.get("webhook_url"):
        account = dict(account)
        account["webhook_url"] = _decrypt_webhook(account["webhook_url"])
    return account


def get_account(account_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_accounts WHERE id=?", (account_id,)
        ).fetchone()
        return _decrypt_account_webhook(dict(row)) if row else None


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
    api_key_id: int | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitor_accounts
               (name, channel_url, api_key_env, fetch_mode, fetch_limit,
                scan_interval, enabled, notify_enabled, notify_platform, webhook_url,
                feishu_message_mode, feishu_template_id, feishu_scan_template_id,
                api_key_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)""",
            (name, channel_url, api_key_env, fetch_mode, fetch_limit,
             scan_interval, int(notify_enabled), notify_platform,
             _encrypt_webhook(webhook_url),
             feishu_message_mode, feishu_template_id, feishu_scan_template_id,
             api_key_id, now_iso(), now_iso()),
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
    webhook_url=_UNSET,
    feishu_message_mode: str | None = None,
    feishu_template_id=_UNSET,
    feishu_scan_template_id=_UNSET,
    api_key_id=_UNSET,
) -> None:
    """更新账户字段。

    对于可空字段（webhook_url / feishu_template_id / feishu_scan_template_id / api_key_id），
    使用 _UNSET 表示「不修改」，传 None 表示「清空为 NULL」。
    """
    fields, values = [], []
    if name             is not None: fields.append("name=?");             values.append(name)
    if channel_url      is not None: fields.append("channel_url=?");      values.append(channel_url)
    if api_key_env      is not None: fields.append("api_key_env=?");      values.append(api_key_env)
    if fetch_mode       is not None: fields.append("fetch_mode=?");       values.append(fetch_mode)
    if fetch_limit      is not None: fields.append("fetch_limit=?");      values.append(fetch_limit)
    if scan_interval    is not None: fields.append("scan_interval=?");   values.append(scan_interval)
    if enabled          is not None: fields.append("enabled=?");          values.append(int(enabled))
    if notify_enabled   is not None: fields.append("notify_enabled=?");   values.append(int(notify_enabled))
    if notify_platform  is not None: fields.append("notify_platform=?");  values.append(notify_platform)
    if webhook_url     is not _UNSET: fields.append("webhook_url=?");     values.append(_encrypt_webhook(webhook_url))
    if feishu_message_mode is not None: fields.append("feishu_message_mode=?"); values.append(feishu_message_mode)
    if feishu_template_id is not _UNSET: fields.append("feishu_template_id=?"); values.append(feishu_template_id)
    if feishu_scan_template_id is not _UNSET: fields.append("feishu_scan_template_id=?"); values.append(feishu_scan_template_id)
    if api_key_id is not _UNSET: fields.append("api_key_id=?");            values.append(api_key_id)
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

    def _escape_like(s: str) -> str:
        """转义 LIKE 通配符，防止 %/_ 产生意外宽匹配"""
        return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

    if title_kw:
        where_clauses.append("title LIKE ?")
        params.append(f"%{_escape_like(title_kw)}%")
    if url_kw:
        where_clauses.append("url LIKE ?")
        params.append(f"%{_escape_like(url_kw)}%")

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


# ── API Token 管理（REST API 认证）─────────────────────────────

def get_api_token() -> str:
    """
    获取 REST API 访问令牌。
    若 app_state 中无 token 则自动生成并保存。
    """
    ensure_app_state_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='api_token'"
        ).fetchone()
        if row:
            return row[0]
    # 无 token → 生成 40 字符十六进制随机串
    import secrets
    token = secrets.token_hex(20)
    set_api_token(token)
    return token


def set_api_token(token: str) -> None:
    """保存 REST API 访问令牌到 app_state"""
    ensure_app_state_table()
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO app_state (key, value) VALUES ('api_token', ?)""",
            (token,),
        )


# ── Webhook URL 加密（M-5）──────────────────────────────────────

def _get_webhook_enc_key() -> bytes:
    """
    获取 Webhook URL 加密密钥（从 app_state 读取，不存在则自动生成）。
    使用 Fernet.generate_key() 生成符合规范的 base64 编码密钥。
    """
    from cryptography.fernet import Fernet
    ensure_app_state_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='webhook_enc_key'"
        ).fetchone()
        if row:
            return row[0].encode("utf-8")
    key_str = Fernet.generate_key().decode("utf-8")
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO app_state (key, value) VALUES ('webhook_enc_key', ?)""",
            (key_str,),
        )
    return key_str.encode("utf-8")


def _encrypt_webhook(url: str | None) -> str | None:
    """加密 Webhook URL，明文为空或已加密则原样返回"""
    if not url:
        return None
    if url.startswith("enc:"):
        return url  # 已加密，跳过
    try:
        from cryptography.fernet import Fernet
        key = _get_webhook_enc_key()
        f = Fernet(key)
        encrypted = f.encrypt(url.encode("utf-8"))
        return "enc:" + encrypted.decode("utf-8")
    except Exception:
        return url  # 加密失败时降级为明文


def _decrypt_webhook(encrypted: str | None) -> str | None:
    """解密 Webhook URL，非加密值或解密失败则原样返回"""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted  # 明文原样返回
    try:
        from cryptography.fernet import Fernet
        key = _get_webhook_enc_key()
        f = Fernet(key)
        return f.decrypt(encrypted[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted  # 解密失败时返回原始值（可能已损坏）


# 确保 app_state 表存在（懒创建）
def ensure_app_state_table() -> None:
    """兼容旧代码：app_state 表已移入 schema.sql，此函数无操作"""


# ── 数据库备份（保留最近 7 份）────────────────────────────────

def backup_db() -> str | None:
    """
    备份 SQLite 数据库到 data/backup/ 目录，保留最近 7 份。
    返回备份文件路径，失败返回 None。
    """
    if not os.path.exists(_DB_PATH):
        return None
    backup_dir = os.path.join(_DATA_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"monitor_{ts}.db")

    try:
        import shutil
        # 备份时排除 api_keys 表以防明文 Key 泄露
        conn_backup = sqlite3.connect(backup_path)
        conn_src = sqlite3.connect(_DB_PATH)
        conn_backup.execute("PRAGMA journal_mode=WAL")
        for line in conn_src.iterdump():
            stripped = line.strip()
            if (stripped.startswith("CREATE TABLE api_keys")
                    or stripped.startswith("INSERT INTO api_keys")):
                continue
            try:
                conn_backup.execute(line)
            except Exception:
                pass
        conn_backup.commit()
        conn_backup.close()
        conn_src.close()

        # 清理超过 7 份的旧备份
        existing = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("monitor_") and f.endswith(".db")
        ])
        for old in existing[:-7]:
            os.remove(os.path.join(backup_dir, old))

        return backup_path
    except Exception:
        return None

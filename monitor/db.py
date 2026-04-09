"""
monitor.db — Monitor 数据库初始化与访问助手
"""
import json
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
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

_GLOBAL_WEBHOOK_KEYS = (
    "global_feishu_url",
    "global_dingtalk_url",
    "global_wecom_url",
)


def _write_config(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _encrypt_config_webhooks(cfg: dict) -> dict:
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _encrypt_webhook(cfg.get(key)) or ""
    return cfg


def _decrypt_config_webhooks(cfg: dict) -> dict:
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _decrypt_webhook(cfg.get(key)) or ""
    return cfg


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
        # ── 系统默认动态代理配置 ────────────────────────────────
        "system_dynamic_proxy_enabled": False,
        "apply_dynamic_proxy_to_new_accounts": True,
        "apply_dynamic_proxy_to_existing_accounts": False,
        "manual_download_route_policy": "balanced",
        "auto_download_route_policy": "strict",
        "allow_free_proxy": True,
        "allow_free_proxy_for_auto_download": False,
        "allow_free_proxy_with_cookies": False,
        "manual_direct_fallback": True,
        "auto_direct_fallback": False,
        "default_proxy_country_codes": [],
        "default_proxy_protocol_order": ["http", "https", "socks5"],
        "default_session_mode": "sticky",
        "default_sticky_minutes": 10,
        "candidate_prefetch_count": 5,
        "candidate_validate_count": 3,
        "validated_pool_ttl_seconds": 300,
        "provider_cooldown_seconds": 600,
        "proxy_probe_timeout_seconds": 8,
        "mask_proxy_in_logs": True,
    }


def get_db_path() -> str:
    return _DB_PATH


def get_config_path() -> str:
    """返回 config.json 路径（优先 exe 同目录下，用户可写）"""
    return _CONFIG_PATH


def load_config() -> dict:
    """加载全局配置（支持 PyInstaller exe 和源码两种模式）"""
    source_path = None
    raw_cfg = None
    if os.path.exists(_CONFIG_PATH):
        source_path = _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw_cfg = json.load(f)
    else:
        pkg_cfg = os.path.join(_PKG_DIR, "config.json")
        if os.path.exists(pkg_cfg):
            source_path = pkg_cfg
            with open(pkg_cfg, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
    if raw_cfg is None:
        return _config_default()

    raw_cfg = {**_config_default(), **raw_cfg}
    encrypted_cfg = _encrypt_config_webhooks(raw_cfg)
    if source_path and encrypted_cfg != raw_cfg:
        _write_config(source_path, encrypted_cfg)
    return _decrypt_config_webhooks(raw_cfg)


def save_config(cfg: dict) -> None:
    """保存全局配置，Webhook URL 落盘时加密。"""
    _write_config(_CONFIG_PATH, _encrypt_config_webhooks(cfg))


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

    if "v6_proxy_pool" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS proxy_pools (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                proxy_url   TEXT    NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_proxy_pools_enabled ON proxy_pools(enabled)"
        )
        # 为 monitor_accounts 添加 proxy_pool_id 和 proxy_enabled 列
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "proxy_pool_id" not in cols:
            conn.execute("ALTER TABLE monitor_accounts ADD COLUMN proxy_pool_id INTEGER DEFAULT NULL")
        if "proxy_enabled" not in cols:
            conn.execute("ALTER TABLE monitor_accounts ADD COLUMN proxy_enabled INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v6_proxy_pool", today),
        )

    # v5: 添加分页覆盖索引（account_id + published_at 排序优化）
    if "v5_video_pagination_index" not in applied:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_account_published "
            "ON monitor_videos(account_id, published_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v5_video_pagination_index", today),
        )

    # v7: 动态代理提供方 + 账户 download_proxy_mode + 下载决策日志
    if "v7_dynamic_proxy" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS dynamic_proxy_providers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL,
                enabled         INTEGER NOT NULL DEFAULT 1,
                billing_tier    TEXT    NOT NULL DEFAULT 'free',
                adapter_type    TEXT    NOT NULL DEFAULT 'public_feed',
                priority        INTEGER NOT NULL DEFAULT 100,
                supports_cookies         INTEGER NOT NULL DEFAULT 0,
                supports_auto_download   INTEGER NOT NULL DEFAULT 1,
                supports_country_filter INTEGER NOT NULL DEFAULT 0,
                supports_sticky_session INTEGER NOT NULL DEFAULT 0,
                risk_level      TEXT    NOT NULL DEFAULT 'medium',
                notes           TEXT    DEFAULT NULL,
                config_json     TEXT    NOT NULL DEFAULT '{}',
                last_health_status TEXT DEFAULT NULL,
                last_health_checked_at TEXT DEFAULT NULL,
                last_error_message     TEXT    DEFAULT NULL,
                cooldown_until  TEXT    DEFAULT NULL,
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dpp_enabled_priority "
            "ON dynamic_proxy_providers(enabled, priority)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dpp_health "
            "ON dynamic_proxy_providers(last_health_status, cooldown_until)"
        )
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "download_proxy_mode" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN download_proxy_mode TEXT NOT NULL DEFAULT 'auto'"
            )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS download_decision_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id      INTEGER,
                account_name    TEXT,
                video_count     INTEGER,
                is_auto_download INTEGER DEFAULT 0,
                cookies_present INTEGER DEFAULT 0,
                resolved_proxy_source TEXT,
                resolved_provider_name TEXT,
                resolved_provider_tier TEXT,
                resolved_country TEXT,
                resolved_session_mode TEXT,
                fallback_depth  INTEGER DEFAULT 0,
                masked_proxy_endpoint TEXT,
                decision_reason TEXT,
                warnings        TEXT,
                created_at      TEXT    NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ddl_account ON download_decision_logs(account_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ddl_created ON download_decision_logs(created_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v7_dynamic_proxy", today),
        )

    # v8: 动态代理候选节点表
    if "v8_dynamic_proxy_candidates" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS dynamic_proxy_candidates (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_key               TEXT    NOT NULL UNIQUE,
                provider_id                 INTEGER NOT NULL,
                protocol                    TEXT    NOT NULL,
                host                        TEXT    NOT NULL,
                port                        INTEGER NOT NULL,
                username                    TEXT    DEFAULT NULL,
                password_enc                TEXT    DEFAULT NULL,
                auth_type                   TEXT    NOT NULL DEFAULT 'none',
                masked_proxy_endpoint       TEXT    NOT NULL,
                country_code                TEXT    DEFAULT NULL,
                region                      TEXT    DEFAULT NULL,
                city                        TEXT    DEFAULT NULL,
                anonymity                   TEXT    DEFAULT NULL,
                risk_level                  TEXT    NOT NULL DEFAULT 'medium',
                supports_https              INTEGER NOT NULL DEFAULT 1,
                supports_cookies            INTEGER NOT NULL DEFAULT 0,
                supports_auto_download      INTEGER NOT NULL DEFAULT 1,
                supports_sticky_session     INTEGER NOT NULL DEFAULT 0,
                latency_ms                  INTEGER DEFAULT NULL,
                last_probe_status           TEXT    NOT NULL DEFAULT 'unknown',
                last_probe_at               TEXT    DEFAULT NULL,
                score                       REAL    NOT NULL DEFAULT 0.0,
                success_count               INTEGER NOT NULL DEFAULT 0,
                failure_count               INTEGER NOT NULL DEFAULT 0,
                consecutive_failures        INTEGER NOT NULL DEFAULT 0,
                last_success_at             TEXT    DEFAULT NULL,
                last_failure_at             TEXT    DEFAULT NULL,
                last_error_message          TEXT    DEFAULT NULL,
                failure_category            TEXT    DEFAULT NULL,
                provider_reference_id       TEXT    DEFAULT NULL,
                ttl_expires_at              TEXT    DEFAULT NULL,
                last_seen_at                TEXT    NOT NULL,
                created_at                  TEXT    NOT NULL,
                updated_at                  TEXT    NOT NULL,
                FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE CASCADE
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_provider_ttl "
            "ON dynamic_proxy_candidates(provider_id, ttl_expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_score "
            "ON dynamic_proxy_candidates(score DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_probe "
            "ON dynamic_proxy_candidates(last_probe_status, ttl_expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_ttl "
            "ON dynamic_proxy_candidates(ttl_expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_key "
            "ON dynamic_proxy_candidates(candidate_key)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v8_dynamic_proxy_candidates", today),
        )

    # v9: provider refresh_interval_minutes
    if "v9_provider_refresh_interval" not in applied:
        cur = conn.execute("PRAGMA table_info(dynamic_proxy_providers)")
        cols = {row[1] for row in cur.fetchall()}
        if "refresh_interval_minutes" not in cols:
            conn.execute(
                "ALTER TABLE dynamic_proxy_providers ADD COLUMN refresh_interval_minutes INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v9_provider_refresh_interval", today),
        )

    # v10: provider scheduler run logs
    if "v10_provider_scheduler_runs" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS provider_scheduler_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id INTEGER,
                provider_name TEXT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_count INTEGER DEFAULT 0,
                valid_count INTEGER DEFAULT 0,
                message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms INTEGER,
                FOREIGN KEY (provider_id) REFERENCES dynamic_proxy_providers(id) ON DELETE SET NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_provider_scheduler_runs_started_at ON provider_scheduler_runs(started_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_provider_scheduler_runs_provider_id ON provider_scheduler_runs(provider_id, started_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v10_provider_scheduler_runs", today),
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
    proxy_pool_id: int | None = None,
    proxy_enabled: bool = False,
    download_proxy_mode: str = "auto",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitor_accounts
               (name, channel_url, api_key_env, fetch_mode, fetch_limit,
                scan_interval, enabled, notify_enabled, notify_platform, webhook_url,
                feishu_message_mode, feishu_template_id, feishu_scan_template_id,
                api_key_id, proxy_pool_id, proxy_enabled, download_proxy_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, channel_url, api_key_env, fetch_mode, fetch_limit,
             scan_interval, int(notify_enabled), notify_platform,
             _encrypt_webhook(webhook_url),
             feishu_message_mode, feishu_template_id, feishu_scan_template_id,
             api_key_id, proxy_pool_id, int(proxy_enabled), download_proxy_mode,
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
    webhook_url=_UNSET,
    feishu_message_mode: str | None = None,
    feishu_template_id=_UNSET,
    feishu_scan_template_id=_UNSET,
    api_key_id=_UNSET,
    proxy_pool_id=_UNSET,
    proxy_enabled=None,
    download_proxy_mode=_UNSET,
) -> None:
    """更新账户字段。

    对于可空字段（webhook_url / feishu_template_id / feishu_scan_template_id / api_key_id / proxy_pool_id），
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
    if proxy_pool_id is not _UNSET: fields.append("proxy_pool_id=?");      values.append(proxy_pool_id)
    if proxy_enabled is not None: fields.append("proxy_enabled=?");        values.append(int(proxy_enabled))
    if download_proxy_mode is not _UNSET: fields.append("download_proxy_mode=?"); values.append(download_proxy_mode)
    fields.append("updated_at=?"); values.append(now_iso())
    values.append(account_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE monitor_accounts SET {','.join(fields)} WHERE id=?", values)


def delete_account(account_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM monitor_accounts WHERE id=?", (account_id,))


# ── proxy_pools CRUD ───────────────────────────────────────

def list_proxy_pools() -> list[dict]:
    """列出所有代理池（含启用状态）"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM proxy_pools ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_proxy_pool(pool_id: int) -> dict | None:
    """获取单个代理池"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM proxy_pools WHERE id=?", (pool_id,)
        ).fetchone()
        return dict(row) if row else None


def _validate_proxy_url(url: str) -> str:
    """
    验证代理 URL 格式。
    支持：http://, https://, socks5://, socks4://
    返回规范化后的 URL，失败抛出 ValueError。
    """
    from urllib.parse import urlparse
    if not url:
        raise ValueError("代理地址不能为空")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https", "socks5", "socks4", "socks"):
        raise ValueError(f"不支持的协议: {scheme}，支持 http/https/socks5")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    return url.strip()


def add_proxy_pool(name: str, proxy_url: str) -> int:
    """新增代理池（URL 格式已验证）"""
    proxy_url = _validate_proxy_url(proxy_url)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO proxy_pools (name, proxy_url, enabled, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?)""",
            (name, proxy_url, now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_proxy_pool(
    pool_id: int,
    name: str | None = None,
    proxy_url: str | None = None,
    enabled: bool | None = None,
) -> None:
    """更新代理池字段（URL 格式已验证）"""
    if proxy_url is not None:
        proxy_url = _validate_proxy_url(proxy_url)
    fields, values = [], []
    if name is not None:       fields.append("name=?");      values.append(name)
    if proxy_url is not None:  fields.append("proxy_url=?"); values.append(proxy_url)
    if enabled is not None:    fields.append("enabled=?");   values.append(int(enabled))
    if not fields:
        return  # 无实际变更，只更新 updated_at 无意义
    fields.append("updated_at=?"); values.append(now_iso())
    values.append(pool_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE proxy_pools SET {','.join(fields)} WHERE id=?", values)


def delete_proxy_pool(pool_id: int) -> None:
    """删除代理池（关联账户的 proxy_pool_id 会被清空，proxy_enabled 置为 0）"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE monitor_accounts SET proxy_pool_id=NULL, proxy_enabled=0 WHERE proxy_pool_id=?",
            (pool_id,),
        )
        conn.execute("DELETE FROM proxy_pools WHERE id=?", (pool_id,))


# ── dynamic_proxy_providers CRUD ─────────────────────────────

def list_dynamic_proxy_providers() -> list[dict]:
    """列出所有动态代理提供方"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM dynamic_proxy_providers ORDER BY priority ASC, id ASC"
        ).fetchall()
        return [_parse_provider_json(dict(r)) for r in rows]


def _parse_provider_json(provider: dict) -> dict:
    """解析 config_json 字段为 dict，并解密敏感字段"""
    if provider and provider.get("config_json"):
        try:
            import json
            provider = dict(provider)
            provider["config_json"] = _decrypt_config_secrets(json.loads(provider["config_json"]))
        except Exception:
            provider["config_json"] = {}
    return provider


def get_dynamic_proxy_provider(provider_id: int) -> dict | None:
    """获取单个动态代理提供方"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dynamic_proxy_providers WHERE id=?", (provider_id,)
        ).fetchone()
        return _parse_provider_json(dict(row)) if row else None


def add_dynamic_proxy_provider(
    name: str,
    billing_tier: str = "free",
    adapter_type: str = "public_feed",
    config_json: dict | None = None,
    enabled: bool = True,
    priority: int = 100,
    supports_cookies: bool = False,
    supports_auto_download: bool = True,
    supports_country_filter: bool = False,
    supports_sticky_session: bool = False,
    risk_level: str = "medium",
    notes: str | None = None,
    refresh_interval_minutes: int = 0,
) -> int:
    """新增动态代理提供方（config_json 敏感字段自动加密）"""
    import json
    cfg_encrypted = _encrypt_config_secrets(config_json or {})
    cfg_str = json.dumps(cfg_encrypted)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO dynamic_proxy_providers
               (name, enabled, billing_tier, adapter_type, priority,
                supports_cookies, supports_auto_download, supports_country_filter,
                supports_sticky_session, risk_level, notes, config_json,
                created_at, updated_at, refresh_interval_minutes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, int(enabled), billing_tier, adapter_type, priority,
             int(supports_cookies), int(supports_auto_download),
             int(supports_country_filter), int(supports_sticky_session),
             risk_level, notes, cfg_str, now_iso(), now_iso(),
             int(refresh_interval_minutes)),
        )
        return cur.lastrowid


def update_dynamic_proxy_provider(
    provider_id: int,
    name: str | None = None,
    enabled: bool | None = None,
    billing_tier: str | None = None,
    adapter_type: str | None = None,
    priority: int | None = None,
    supports_cookies: bool | None = None,
    supports_auto_download: bool | None = None,
    supports_country_filter: bool | None = None,
    supports_sticky_session: bool | None = None,
    risk_level: str | None = None,
    notes: str | None = None,
    config_json: dict | None = None,
    last_health_status: str | None = None,
    last_health_checked_at: str | None = None,
    last_error_message: str | None = _UNSET,
    cooldown_until: str | None = None,
    refresh_interval_minutes: int | None = None,
) -> None:
    """更新动态代理提供方"""
    import json
    fields, values = [], []
    if name is not None:          fields.append("name=?");              values.append(name)
    if enabled is not None:       fields.append("enabled=?");          values.append(int(enabled))
    if billing_tier is not None:  fields.append("billing_tier=?");     values.append(billing_tier)
    if adapter_type is not None:  fields.append("adapter_type=?");      values.append(adapter_type)
    if priority is not None:      fields.append("priority=?");         values.append(priority)
    if supports_cookies is not None:         fields.append("supports_cookies=?");          values.append(int(supports_cookies))
    if supports_auto_download is not None:   fields.append("supports_auto_download=?");    values.append(int(supports_auto_download))
    if supports_country_filter is not None: fields.append("supports_country_filter=?");  values.append(int(supports_country_filter))
    if supports_sticky_session is not None: fields.append("supports_sticky_session=?");  values.append(int(supports_sticky_session))
    if risk_level is not None:    fields.append("risk_level=?");       values.append(risk_level)
    if notes is not None:         fields.append("notes=?");             values.append(notes)
    if config_json is not None:   fields.append("config_json=?");       values.append(json.dumps(_encrypt_config_secrets(config_json)))
    if last_health_status is not None:      fields.append("last_health_status=?");     values.append(last_health_status)
    if last_health_checked_at is not None:  fields.append("last_health_checked_at=?");  values.append(last_health_checked_at)
    # None 表示显式清空 last_error_message；省略参数（_UNSET）表示不修改该列
    if last_error_message is not _UNSET:
        fields.append("last_error_message=?")
        values.append(last_error_message)
    if cooldown_until is not None: fields.append("cooldown_until=?");    values.append(cooldown_until)
    if refresh_interval_minutes is not None: fields.append("refresh_interval_minutes=?"); values.append(int(refresh_interval_minutes))
    if not fields:
        return
    fields.append("updated_at=?"); values.append(now_iso())
    values.append(provider_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE dynamic_proxy_providers SET {','.join(fields)} WHERE id=?",
            values,
        )


def delete_dynamic_proxy_provider(provider_id: int) -> None:
    """删除动态代理提供方"""
    with get_connection() as conn:
        conn.execute("DELETE FROM dynamic_proxy_providers WHERE id=?", (provider_id,))


def get_enabled_providers(billing_tier: str | None = None) -> list[dict]:
    """获取已启用的动态代理提供方（按优先级排序）"""
    with get_connection() as conn:
        if billing_tier is None:
            rows = conn.execute(
                "SELECT * FROM dynamic_proxy_providers WHERE enabled=1 ORDER BY priority ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dynamic_proxy_providers WHERE enabled=1 AND billing_tier=? ORDER BY priority ASC",
                (billing_tier,),
            ).fetchall()
        return [_parse_provider_json(dict(r)) for r in rows]


# ── dynamic_proxy_candidates helpers ───────────────────────────

def _encrypt_candidate_secret(value: str | None) -> str | None:
    """Fernet 加密候选密码，返回 'enc:<base64>' 格式。"""
    if not value:
        return None
    if value.startswith("enc:"):
        return value
    return _encrypt_config_value(value)


def _decrypt_candidate_secret(encrypted: str | None) -> str | None:
    """Fernet 解密候选密码，非加密值或解密失败原样返回。"""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted
    return _decrypt_config_value(encrypted)


def _build_runtime_proxy_url(
    protocol: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """按独立字段构造运行时可用的代理 URL。"""
    if username and password:
        from urllib.parse import quote
        user_part = f"{quote(username)}:{quote(password)}"
        return f"{protocol}://{user_part}@{host}:{port}"
    return f"{protocol}://{host}:{port}"


def _iso_future(seconds: int) -> str:
    """返回从现在起 N 秒后的 ISO 8601 时间字符串。"""
    from datetime import timedelta
    return (datetime.now() + timedelta(seconds=seconds)).astimezone().isoformat(timespec="seconds")


# ── dynamic_proxy_candidates CRUD ──────────────────────────────

def add_proxy_candidate(
    provider_id: int,
    protocol: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    auth_type: str = "none",
    country_code: str | None = None,
    region: str | None = None,
    city: str | None = None,
    anonymity: str | None = None,
    risk_level: str = "medium",
    supports_https: bool = True,
    supports_cookies: bool = False,
    supports_auto_download: bool = True,
    supports_sticky_session: bool = False,
    latency_ms: int | None = None,
    last_probe_status: str = "unknown",
    last_probe_at: str | None = None,
    score: float = 0.0,
    provider_reference_id: str | None = None,
    ttl_expires_at: str | None = None,
    masked_proxy_endpoint: str | None = None,
) -> int:
    """
    新增或刷新代理候选节点（幂等：按派生 candidate_key 去重）。
    返回候选节点 ID（新增或已存在）。
    """
    candidate_key = f"{provider_id}:{protocol}:{host}:{port}:{username or ''}"
    password_enc = _encrypt_candidate_secret(password)
    if masked_proxy_endpoint is None:
        masked_ep = f"{protocol}://***:****@{host}:{port}" if username or password else f"{protocol}://{host}:{port}"
    else:
        masked_ep = masked_proxy_endpoint

    now = now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM dynamic_proxy_candidates WHERE candidate_key=?",
            (candidate_key,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    provider_id=?, protocol=?, host=?, port=?,
                    username=?, password_enc=?, auth_type=?,
                    masked_proxy_endpoint=?, country_code=?, region=?, city=?,
                    anonymity=?, risk_level=?, supports_https=?,
                    supports_cookies=?, supports_auto_download=?,
                    supports_sticky_session=?, latency_ms=?,
                    last_probe_status=?, last_probe_at=?, score=?,
                    provider_reference_id=?, ttl_expires_at=?,
                    last_seen_at=?, updated_at=?
                   WHERE candidate_key=?""",
                (
                    provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_ep, country_code, region, city,
                    anonymity, risk_level, int(supports_https),
                    int(supports_cookies), int(supports_auto_download),
                    int(supports_sticky_session), latency_ms,
                    last_probe_status, last_probe_at or None, score,
                    provider_reference_id, ttl_expires_at,
                    now, now,
                    candidate_key,
                ),
            )
            return existing[0]
        else:
            cur = conn.execute(
                """INSERT INTO dynamic_proxy_candidates
                   (candidate_key, provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_proxy_endpoint, country_code, region, city,
                    anonymity, risk_level, supports_https,
                    supports_cookies, supports_auto_download, supports_sticky_session,
                    latency_ms, last_probe_status, last_probe_at,
                    score, provider_reference_id, ttl_expires_at,
                    last_seen_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_key, provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_ep, country_code, region, city,
                    anonymity, risk_level, int(supports_https),
                    int(supports_cookies), int(supports_auto_download), int(supports_sticky_session),
                    latency_ms, last_probe_status, last_probe_at,
                    score, provider_reference_id, ttl_expires_at,
                    now, now, now,
                ),
            )
            return cur.lastrowid


def get_proxy_candidate(candidate_id: int) -> dict | None:
    """获取单个代理候选节点"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dynamic_proxy_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
        return dict(row) if row else None


def get_proxy_candidate_by_provider(provider_id: int, valid_only: bool = True) -> list[dict]:
    """
    按 provider_id 获取候选节点列表。
    valid_only=True 时过滤 ttl_expires_at > now，按 score DESC 排序。
    """
    now = now_iso()
    with get_connection() as conn:
        if valid_only:
            rows = conn.execute(
                """SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=? AND (ttl_expires_at IS NULL OR ttl_expires_at > ?)
                   ORDER BY score DESC""",
                (provider_id, now),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=?
                   ORDER BY score DESC""",
                (provider_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def build_runtime_proxy_url(candidate: dict) -> str:
    """公开接口：从候选记录还原运行时可用的代理 URL（解密密码）。"""
    password_enc = candidate.get("password_enc")
    password = _decrypt_candidate_secret(password_enc) if password_enc else None
    return _build_runtime_proxy_url(
        candidate.get("protocol", "http"),
        candidate.get("host", ""),
        candidate.get("port", ""),
        candidate.get("username") or None,
        password,
    )


def delete_expired_candidates() -> int:
    """删除所有已过期的候选节点，返回删除数量。"""
    now = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM dynamic_proxy_candidates WHERE ttl_expires_at IS NOT NULL AND ttl_expires_at <= ?",
            (now,),
        )
        return cur.rowcount


def cleanup_stale_candidates(stale_days: int = 7) -> int:
    """删除长期处于 down 状态的候选节点（last_probe_status='down' 且超过 stale_days 未恢复），返回删除数量。"""
    cutoff = (datetime.now().astimezone() - timedelta(days=stale_days)).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """DELETE FROM dynamic_proxy_candidates
               WHERE last_probe_status = 'down'
                 AND last_probe_at IS NOT NULL
                 AND last_probe_at <= ?""",
            (cutoff,),
        )
        return cur.rowcount


def update_candidate_quality(
    candidate_id: int,
    success: bool,
    latency_ms: int | None = None,
    error_message: str | None = None,
    failure_category: str | None = None,
) -> None:
    """更新候选节点质量指标（成功/失败）。"""
    now = now_iso()
    with get_connection() as conn:
        if success:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    success_count = success_count + 1,
                    consecutive_failures = 0,
                    last_success_at = ?,
                    latency_ms = COALESCE(?, latency_ms),
                    last_error_message = NULL,
                    failure_category = NULL,
                    updated_at = ?
                   WHERE id=?""",
                (now, latency_ms, now, candidate_id),
            )
        else:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    failure_count = failure_count + 1,
                    consecutive_failures = consecutive_failures + 1,
                    last_failure_at = ?,
                    latency_ms = COALESCE(?, latency_ms),
                    last_error_message = ?,
                    failure_category = ?,
                    updated_at = ?
                   WHERE id=?""",
                (now, latency_ms, error_message, failure_category, now, candidate_id),
            )


# ── download_decision_logs CRUD ─────────────────────────────

def log_download_decision(
    account_id: int | None,
    account_name: str | None,
    video_count: int,
    is_auto_download: bool,
    cookies_present: bool,
    resolved_proxy_source: str,
    resolved_provider_name: str | None,
    resolved_provider_tier: str | None,
    resolved_country: str | None = None,
    resolved_session_mode: str | None = None,
    fallback_depth: int = 0,
    masked_proxy_endpoint: str | None = None,
    decision_reason: str = "",
    warnings: str | None = None,
) -> None:
    """记录一次下载的路由决策"""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO download_decision_logs
               (account_id, account_name, video_count, is_auto_download,
                cookies_present, resolved_proxy_source, resolved_provider_name,
                resolved_provider_tier, resolved_country, resolved_session_mode,
                fallback_depth, masked_proxy_endpoint, decision_reason, warnings, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, account_name, video_count, int(is_auto_download),
             int(cookies_present), resolved_proxy_source, resolved_provider_name,
             resolved_provider_tier, resolved_country, resolved_session_mode,
             fallback_depth, masked_proxy_endpoint, decision_reason, warnings,
             now_iso()),
        )


def get_download_decision_logs(account_id: int | None = None, limit: int = 100) -> list[dict]:
    """获取下载决策日志"""
    with get_connection() as conn:
        if account_id is not None:
            rows = conn.execute(
                "SELECT * FROM download_decision_logs WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM download_decision_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ── 工具函数 ─────────────────────────────────────────────────

def mask_proxy_url(url: str | None) -> str | None:
    """掩码代理 URL，返回安全可日志输出的格式。"""
    if not url:
        return None
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        # 掩码 user:pass@host:port 部分
        masked_netloc = f"***:****@***:****"
        masked = urlunparse((
            parsed.scheme,
            masked_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
        return masked
    except Exception:
        return "***:****@***:****"


def get_account_proxy(account: dict) -> str | None:
    """
    获取账户启用的代理 URL。
    仅当 account['proxy_enabled'] == 1 且 proxy_pool_id 存在且代理池 enabled==1 时返回。
    """
    if not account.get("proxy_enabled"):
        return None
    pool_id = account.get("proxy_pool_id")
    if not pool_id:
        return None
    pool = get_proxy_pool(pool_id)
    if pool and pool.get("enabled"):
        return pool.get("proxy_url")
    return None


# ── monitor_events CRUD ───────────────────────────────────

def add_provider_scheduler_run(
    provider_id: int | None,
    provider_name: str | None,
    job_type: str,
    status: str,
    raw_count: int = 0,
    valid_count: int = 0,
    message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_ms: int | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO provider_scheduler_runs
               (provider_id, provider_name, job_type, status, raw_count, valid_count, message, started_at, finished_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider_id, provider_name, job_type, status, raw_count, valid_count, message, started_at or now_iso(), finished_at, duration_ms),
        )
        return cur.lastrowid


def list_provider_scheduler_runs(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM provider_scheduler_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


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
    from cryptography.fernet import Fernet
    key = _get_webhook_enc_key()
    f = Fernet(key)
    encrypted = f.encrypt(url.encode("utf-8"))
    return "enc:" + encrypted.decode("utf-8")


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


# ── config_json 敏感字段加密 ─────────────────────────────────

# 已知敏感字段名列表（匹配测试期望）
_SECRET_FIELD_NAMES = frozenset(["password", "auth_secret", "api_key", "secret", "token"])


def _encrypt_config_value(value: str) -> str:
    """Fernet 加密单个字符串值，返回 'enc:<base64>' 格式。"""
    if not value:
        return value
    if value.startswith("enc:"):
        return value
    key = _get_webhook_enc_key()
    from cryptography.fernet import Fernet
    return "enc:" + Fernet(key).encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_config_value(value: str) -> str:
    """Fernet 解密单个字符串值，非加密值或解密失败原样返回。"""
    if not value:
        return value
    if not value.startswith("enc:"):
        return value
    try:
        key = _get_webhook_enc_key()
        from cryptography.fernet import Fernet
        return Fernet(key).decrypt(value[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return value


def _encrypt_config_secrets(cfg: dict) -> dict:
    """递归加密 config_json 中的敏感字符串字段（不修改非字符串值）。"""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and k.lower() in _SECRET_FIELD_NAMES:
            result[k] = _encrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = _encrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [
                _encrypt_config_value(item) if isinstance(item, str) and k.lower() in _SECRET_FIELD_NAMES else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _decrypt_config_secrets(cfg: dict) -> dict:
    """递归解密 config_json 中的敏感字符串字段。"""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and (v.startswith("enc:") or k.lower() in _SECRET_FIELD_NAMES):
            result[k] = _decrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = _decrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [_decrypt_config_value(item) if isinstance(item, str) else item for item in v]
        else:
            result[k] = v
    return result


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

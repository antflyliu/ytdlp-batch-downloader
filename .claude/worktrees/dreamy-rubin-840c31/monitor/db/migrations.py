"""
monitor.db.migrations — Database schema migrations.

All _migrate_* functions and _ensure_schema_migrations.
"""
import os

from monitor.db.connection import get_connection, _DATA_DIR
from monitor.db.db_core import now_iso, _today_str


def _ensure_schema_migrations(conn):
    """Ensure schema_migrations table exists."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )"""
    )


def _migrate_legacy_api_keys(conn):
    """Migrate api_key_env environment variable names to api_keys table."""
    import os as _os
    rows = conn.execute(
        "SELECT DISTINCT api_key_env FROM monitor_accounts WHERE api_key_env IS NOT NULL"
    ).fetchall()
    for row in rows:
        env_name = row[0]
        key_value = _os.environ.get(env_name, "")
        if key_value:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO api_keys
                       (key_value, name, daily_quota, quota_used, quota_reset_at,
                        is_active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (key_value, env_name, 10000, 0, _today_str(),
                     1, now_iso(), now_iso()),
                )
            except Exception:
                pass  # Key already exists


def run_all_migrations(conn):
    """Run all schema migrations idempotently."""
    _ensure_schema_migrations(conn)
    today = _today_str()

    # v1: api_key_id column
    if "v1_api_key_id" not in _get_applied_versions(conn):
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

    # v2: feishu extended columns
    if "v2_feishu_ext" not in _get_applied_versions(conn):
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

    # v3: api_quota_usage.api_key_env -> api_key_value rename
    if "v3_quota_col_rename" not in _get_applied_versions(conn):
        cur = conn.execute("PRAGMA table_info(api_quota_usage)")
        cols = {row[1] for row in cur.fetchall()}
        if "api_key_env" in cols and "api_key_value" not in cols:
            conn.execute(
                "ALTER TABLE api_quota_usage RENAME COLUMN api_key_env TO api_key_value"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v3_quota_col_rename", today),
        )

    # v4: webhook_url encryption
    if "v4_webhook_encrypt" not in _get_applied_versions(conn):
        from monitor.db.crypto import encrypt_webhook, decrypt_webhook
        rows = conn.execute(
            "SELECT id, webhook_url FROM monitor_accounts "
            "WHERE webhook_url IS NOT NULL AND webhook_url != '' AND webhook_url NOT LIKE 'enc:%'"
        ).fetchall()
        for row in rows:
            acct_id, url = row
            if url and not url.startswith("enc:"):
                encrypted = encrypt_webhook(url)
                conn.execute(
                    "UPDATE monitor_accounts SET webhook_url=? WHERE id=?",
                    (encrypted, acct_id),
                )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v4_webhook_encrypt", today),
        )

    # v5: video pagination index
    if "v5_video_pagination_index" not in _get_applied_versions(conn):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_account_published "
            "ON monitor_videos(account_id, published_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v5_video_pagination_index", today),
        )

    # v6: proxy pools
    if "v6_proxy_pool" not in _get_applied_versions(conn):
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
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "proxy_pool_id" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN proxy_pool_id INTEGER DEFAULT NULL"
            )
        if "proxy_enabled" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN proxy_enabled INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v6_proxy_pool", today),
        )

    # v7: dynamic proxy providers
    if "v7_dynamic_proxy" not in _get_applied_versions(conn):
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

    # v8: dynamic proxy candidates
    if "v8_dynamic_proxy_candidates" not in _get_applied_versions(conn):
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
    if "v9_provider_refresh_interval" not in _get_applied_versions(conn):
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
    if "v10_provider_scheduler_runs" not in _get_applied_versions(conn):
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

    # v11: persisted web batch tasks
    if "v11_web_batch_tasks" not in _get_applied_versions(conn):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS web_batch_tasks (
                task_id          TEXT PRIMARY KEY,
                task_kind        TEXT NOT NULL DEFAULT 'web_batch',
                source_name      TEXT,
                output_path      TEXT,
                status           TEXT NOT NULL,
                total            INTEGER NOT NULL DEFAULT 0,
                completed        INTEGER NOT NULL DEFAULT 0,
                success          INTEGER NOT NULL DEFAULT 0,
                failed           INTEGER NOT NULL DEFAULT 0,
                current_video    TEXT,
                error            TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                cancel_message   TEXT,
                results_json     TEXT NOT NULL DEFAULT '[]',
                urls             TEXT NOT NULL DEFAULT '[]',
                created_at       TEXT NOT NULL,
                finished_at      TEXT,
                updated_at       TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_batch_tasks_created_at ON web_batch_tasks(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_web_batch_tasks_status ON web_batch_tasks(status, created_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v11_web_batch_tasks", today),
        )

    # v12: monitor_accounts.dingtalk_sign_secret
    if "v12_monitor_accounts_dingtalk_sign_secret" not in _get_applied_versions(conn):
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "dingtalk_sign_secret" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN dingtalk_sign_secret TEXT DEFAULT NULL"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v12_monitor_accounts_dingtalk_sign_secret", today),
        )

    # v13: web_batch_tasks.urls for storing video URLs
    if "v13_web_batch_tasks_urls" not in _get_applied_versions(conn):
        cur = conn.execute("PRAGMA table_info(web_batch_tasks)")
        cols = {row[1] for row in cur.fetchall()}
        if "urls" not in cols:
            conn.execute("ALTER TABLE web_batch_tasks ADD COLUMN urls TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v13_web_batch_tasks_urls", today),
        )

    # v14: monitor_accounts.telegram_bot_token（与 webhook_url 解耦）
    if "v14_telegram_bot_token" not in _get_applied_versions(conn):
        cur = conn.execute("PRAGMA table_info(monitor_accounts)")
        cols = {row[1] for row in cur.fetchall()}
        if "telegram_bot_token" not in cols:
            conn.execute(
                "ALTER TABLE monitor_accounts ADD COLUMN telegram_bot_token TEXT DEFAULT NULL"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v14_telegram_bot_token", today),
        )

    # v15: clip_tasks 增强字段（封面图/字幕/长宽比）
    if "v15_clip_tasks_enhancements" not in _get_applied_versions(conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "clip_tasks" in tables:
            cur = conn.execute("PRAGMA table_info(clip_tasks)")
            cols = {row[1] for row in cur.fetchall()}
            for col, ddl in [
                ("thumbnail_path", "TEXT DEFAULT NULL"),
                ("subtitles_path", "TEXT DEFAULT NULL"),
                ("aspect_ratio", "TEXT DEFAULT NULL"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE clip_tasks ADD COLUMN {col} {ddl}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v15_clip_tasks_enhancements", today),
        )

    # v16: monitor_videos 失败重试字段
    if "v16_failed_retry_fields" not in _get_applied_versions(conn):
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "monitor_videos" in tables:
            cur = conn.execute("PRAGMA table_info(monitor_videos)")
            cols = {row[1] for row in cur.fetchall()}
            for col, ddl in [
                ("failed_reason", "TEXT"),
                ("failed_at", "TEXT"),
                ("failed_event_id", "INTEGER"),
                ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE monitor_videos ADD COLUMN {col} {ddl}")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v16_failed_retry_fields", today),
        )


def _get_applied_versions(conn) -> set:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

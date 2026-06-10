"""
monitor 数据库访问实现主体（磁盘路径：monitor/db.py）。

如何被加载：
  本文件不会作为「名为 monitor.db 的顶层模块文件」被直接解析；
  而是由 monitor/db/__init__.py 用 SourceFileLoader("monitor.db", <本文件路径>) 执行，
  因此运行时 __name__ 为 "monitor.db"，__file__ 指向本文件。

与 monitor/db/ 子目录的关系：
  大量逻辑在本文件；连接、db_core 由 __init__.py 在加载本文件之后显式注入顶层命名空间；
  queries/ 中的模块不注入本模块顶层，请使用 `import monitor.db.queries.<模块>`（__init__.py 为 monitor.db 设置了 __path__）。

说明：若仅阅读代码，请同时打开 monitor/db/__init__.py 理解完整导入链。
"""
import json
import importlib.util
import os
import sys
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

# Load db_core first to get shared sentinel _UNSET
_db_core_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
_db_core_path = os.path.join(_db_core_dir, "db_core.py")
_spec = importlib.util.spec_from_file_location("monitor.db.db_core", _db_core_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["monitor.db.db_core"] = _mod
_UNSET = _mod._UNSET

import logging_config
_log = logging_config.get_logger("monitor.db")

# ── Re-export config/ functions for backward compatibility ────────
# These were extracted to config/ package. Import from there.
from config.settings import (
    _config_default as _config_default,
    load_config as load_config,
    save_config as save_config,
    _write_config as _write_config,
)
from config.encryption import (
    _encrypt_webhook as _encrypt_webhook,
    _decrypt_webhook as _decrypt_webhook,
    _encrypt_config_secrets as _encrypt_config_secrets,
    _decrypt_config_secrets as _decrypt_config_secrets,
    _encrypt_config_value as _encrypt_config_value,
    _decrypt_config_value as _decrypt_config_value,
    _encrypt_candidate_secret as _encrypt_candidate_secret,
    _decrypt_candidate_secret as _decrypt_candidate_secret,
    _merge_masked_config_secrets as _merge_masked_config_secrets,
    _SECRET_FIELD_NAMES as _SECRET_FIELD_NAMES,
    _GLOBAL_WEBHOOK_KEYS as _GLOBAL_WEBHOOK_KEYS,
)
from config import DEFAULT_PROXY_PROTOCOL_ORDER

# ── PyInstaller 兼容路径 ──────────────────────────────────────
from utils.paths import get_pkg_dir, get_exe_dir, get_data_dir, get_db_path, get_schema_path, get_config_path

_PKG_DIR = get_pkg_dir()
_EXE_DIR = get_exe_dir()
_DATA_DIR = get_data_dir()
_DB_PATH = get_db_path()
_SCHEMA_PATH = get_schema_path()
_CONFIG_PATH = get_config_path()


ARTICLE_TASK_COLUMN_DDLS = [
    ("source_type", "TEXT NOT NULL DEFAULT 'video'"),
    ("monitor_video_id", "INTEGER"),
    ("video_id", "TEXT"),
    ("video_url", "TEXT"),
    ("video_title", "TEXT"),
    ("article_source_path", "TEXT"),
    ("article_text", "TEXT"),
    ("source_url", "TEXT"),
    ("source_title", "TEXT"),
    ("email_message_id", "INTEGER DEFAULT NULL"),
    ("rss_item_id", "INTEGER DEFAULT NULL"),
    ("status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("current_stage", "TEXT"),
    ("source_lang", "TEXT"),
    ("target_lang", "TEXT NOT NULL DEFAULT 'zh-Hans'"),
    ("auto_translate", "INTEGER NOT NULL DEFAULT 1"),
    ("output_dir", "TEXT"),
    ("draft_path", "TEXT"),
    ("transcript_path", "TEXT"),
    ("optimized_path", "TEXT"),
    ("summary_path", "TEXT"),
    ("translated_path", "TEXT"),
    ("stage_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("stages_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("result_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("error", "TEXT"),
    ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("cancel_message", "TEXT"),
    ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ("finished_at", "TEXT"),
]


# ── Backward-compatible public API re-exports ───────────────────
def get_db_path() -> str:
    """返回数据库路径（兼容旧接口）"""
    return _DB_PATH


def get_config_path() -> str:
    """返回 config.json 路径（兼容旧接口）"""
    return _CONFIG_PATH


def init_db() -> None:
    """初始化数据库，创建表（如不存在）"""
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    with get_connection() as conn:
        _prepare_legacy_schema_for_bootstrap(conn)
        conn.executescript(schema)
        _ensure_schema_migrations(conn)
        _migrate_monitor_accounts(conn)
    mark_incomplete_web_batch_tasks_interrupted()
    mark_incomplete_ai_content_tasks_interrupted()
    # 同步初始化 quota 表
    import monitor.quota as _quota
    _quota._ensure_schema()


def _prepare_legacy_schema_for_bootstrap(conn) -> None:
    """Patch old tables enough for schema.sql indexes to execute safely."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "monitor_videos" in tables:
        cur = conn.execute("PRAGMA table_info(monitor_videos)")
        cols = {row[1] for row in cur.fetchall()}
        for col, ddl in [
            ("channel_id", "TEXT DEFAULT NULL"),
            ("channel_handle", "TEXT DEFAULT NULL"),
            ("description", "TEXT DEFAULT NULL"),
            ("url", "TEXT NOT NULL DEFAULT ''"),
            ("upload_date", "TEXT DEFAULT NULL"),
            ("duration_sec", "INTEGER DEFAULT NULL"),
            ("view_count", "INTEGER DEFAULT NULL"),
            ("like_count", "INTEGER DEFAULT NULL"),
            ("comment_count", "INTEGER DEFAULT NULL"),
            ("thumbnail_url", "TEXT DEFAULT NULL"),
            ("fetched_at", "TEXT NOT NULL DEFAULT ''"),
            ("notify_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("notify_sent_at", "TEXT DEFAULT NULL"),
            ("notify_error", "TEXT DEFAULT NULL"),
            ("download_at", "TEXT DEFAULT NULL"),
            ("download_path", "TEXT DEFAULT NULL"),
            ("download_error", "TEXT DEFAULT NULL"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE monitor_videos ADD COLUMN {col} {ddl}")
    _ensure_article_task_columns(conn)
    _dedupe_content_variants_identity_for_bootstrap(conn)


def _dedupe_content_variants_identity_for_bootstrap(conn) -> None:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "content_variants" not in tables:
        return
    groups = conn.execute(
        """SELECT source_type, source_id, platform, COUNT(*) AS row_count
           FROM content_variants
           GROUP BY source_type, source_id, platform
           HAVING row_count > 1"""
    ).fetchall()
    publication_table_exists = "content_publication_tasks" in tables
    for group in groups:
        rows = conn.execute(
            """SELECT id FROM content_variants
               WHERE source_type=? AND source_id=? AND platform=?
               ORDER BY updated_at DESC, created_at DESC, id DESC""",
            (group[0], group[1], group[2]),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep_id = int(rows[0][0])
        stale_ids = [int(row[0]) for row in rows[1:]]
        placeholders = ",".join("?" for _ in stale_ids)
        if publication_table_exists:
            conn.execute(
                f"UPDATE content_publication_tasks SET variant_id=? WHERE variant_id IN ({placeholders})",
                [keep_id, *stale_ids],
            )
        conn.execute(f"DELETE FROM content_variants WHERE id IN ({placeholders})", stale_ids)


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

    # v11: persisted Web batch download tasks
    if "v11_web_batch_tasks" not in applied:
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
    if "v12_monitor_accounts_dingtalk_sign_secret" not in applied:
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

    # v13: web_batch_tasks 新增 task_kind + urls 列（支持任务来源分类 + 重启功能）
    if "v13_web_batch_tasks_urls" not in applied:
        cur = conn.execute("PRAGMA table_info(web_batch_tasks)")
        cols = {row[1] for row in cur.fetchall()}
        if "task_kind" not in cols:
            conn.execute(
                "ALTER TABLE web_batch_tasks ADD COLUMN task_kind TEXT NOT NULL DEFAULT 'web_batch'"
            )
        if "urls" not in cols:
            conn.execute(
                "ALTER TABLE web_batch_tasks ADD COLUMN urls TEXT NOT NULL DEFAULT '[]'"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v13_web_batch_tasks_urls", today),
        )

    # v14: monitor_accounts.telegram_bot_token（与 webhook_url 解耦）
    if "v14_telegram_bot_token" not in applied:
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

    # v15: AI 视频切片任务表
    if "v15_clip_tasks" not in applied:
        conn.execute("""CREATE TABLE IF NOT EXISTS clip_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            monitor_video_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            account_name TEXT NOT NULL,
            video_title TEXT NOT NULL,
            video_path TEXT NOT NULL,
            srt_path TEXT NOT NULL,
            output_dir TEXT NOT NULL,
            llm_provider TEXT NOT NULL DEFAULT 'qwen',
            llm_model TEXT,
            min_score REAL NOT NULL DEFAULT 7.0,
            category TEXT NOT NULL DEFAULT 'knowledge',
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            clip_count INTEGER DEFAULT 0,
            collection_count INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clip_tasks_account ON clip_tasks(account_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clip_tasks_video ON clip_tasks(monitor_video_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clip_tasks_status ON clip_tasks(status, created_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v15_clip_tasks_enhancements", today),
        )

    # v16: monitor_videos 失败重试字段
    if "v16_failed_retry_fields" not in applied:
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

    # v17: AI article + video generation task workflows
    if "v17_ai_content_workflows" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS article_tasks (
                task_id           TEXT PRIMARY KEY,
                source_type       TEXT    NOT NULL DEFAULT 'video',
                monitor_video_id  INTEGER,
                video_id          TEXT,
                video_url         TEXT,
                video_title       TEXT,
                article_source_path TEXT,
                article_text      TEXT,
                source_url        TEXT,
                source_title      TEXT,
                status            TEXT NOT NULL DEFAULT 'pending',
                current_stage     TEXT,
                source_lang       TEXT,
                target_lang       TEXT NOT NULL DEFAULT 'zh-Hans',
                auto_translate    INTEGER NOT NULL DEFAULT 1,
                output_dir        TEXT,
                draft_path        TEXT,
                transcript_path   TEXT,
                optimized_path    TEXT,
                summary_path      TEXT,
                translated_path   TEXT,
                stage_json        TEXT NOT NULL DEFAULT '{}',
                stages_json       TEXT NOT NULL DEFAULT '{}',
                result_json       TEXT NOT NULL DEFAULT '{}',
                error             TEXT,
                cancel_requested  INTEGER NOT NULL DEFAULT 0,
                cancel_message    TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                finished_at       TEXT,
                FOREIGN KEY (monitor_video_id) REFERENCES monitor_videos(id) ON DELETE SET NULL
            )"""
        )
        _ensure_article_task_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_article_tasks_created_at ON article_tasks(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_article_tasks_status ON article_tasks(status, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_article_tasks_video ON article_tasks(monitor_video_id, created_at DESC)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS video_gen_tasks (
                task_id           TEXT PRIMARY KEY,
                mode              TEXT NOT NULL DEFAULT 'generate',
                topic             TEXT,
                script_text       TEXT,
                template_name     TEXT,
                template_key      TEXT,
                prompt_prefix     TEXT,
                image_workflow    TEXT,
                tts_workflow      TEXT,
                bgm_volume        REAL,
                scene_count       INTEGER NOT NULL DEFAULT 5,
                status            TEXT NOT NULL DEFAULT 'pending',
                current_stage     TEXT,
                output_dir        TEXT,
                output_path       TEXT,
                storyboard_path   TEXT,
                video_path        TEXT,
                duration_sec      REAL,
                file_size         INTEGER,
                stage_json        TEXT NOT NULL DEFAULT '{}',
                stages_json       TEXT NOT NULL DEFAULT '{}',
                result_json       TEXT NOT NULL DEFAULT '{}',
                error             TEXT,
                cancel_requested  INTEGER NOT NULL DEFAULT 0,
                cancel_message    TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                finished_at       TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_video_gen_tasks_created_at ON video_gen_tasks(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_video_gen_tasks_status ON video_gen_tasks(status, created_at DESC)"
        )
        _ensure_voice_tasks_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v17_ai_content_workflows", today),
        )

    # v17b: keep the early frontend/API contract aliases available without
    # changing the internal task field names used by the pipelines.
    if "v17_ai_content_contract_aliases" not in applied:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "article_tasks" in tables:
            cur = conn.execute("PRAGMA table_info(article_tasks)")
            cols = {row[1] for row in cur.fetchall()}
            if "stage_json" not in cols:
                conn.execute("ALTER TABLE article_tasks ADD COLUMN stage_json TEXT NOT NULL DEFAULT '{}'")
        if "video_gen_tasks" in tables:
            cur = conn.execute("PRAGMA table_info(video_gen_tasks)")
            cols = {row[1] for row in cur.fetchall()}
            for col, ddl in [
                ("template_name", "TEXT"),
                ("stage_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("output_path", "TEXT"),
                ("prompt_prefix", "TEXT"),
                ("image_workflow", "TEXT"),
                ("tts_workflow", "TEXT"),
                ("bgm_volume", "REAL"),
            ]:
                if col not in cols:
                    conn.execute(f"ALTER TABLE video_gen_tasks ADD COLUMN {col} {ddl}")
        _ensure_voice_tasks_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v17_ai_content_contract_aliases", today),
        )

    if "v18_voice_tasks" not in applied:
        _ensure_voice_tasks_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v18_voice_tasks", today),
        )

    # v18: WeChat Official Account publish tasks
    if "v18_wechat_publish_tasks" not in applied:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wechat_publish_tasks (
                task_id           TEXT PRIMARY KEY,
                article_task_id   TEXT,
                draft_path        TEXT,
                title             TEXT,
                author            TEXT,
                theme             TEXT NOT NULL DEFAULT 'default',
                color             TEXT NOT NULL DEFAULT 'blue',
                need_open_comment INTEGER NOT NULL DEFAULT 1,
                only_fans_can_comment INTEGER NOT NULL DEFAULT 0,
                cover_image       TEXT,
                html_content      TEXT,
                publish_mode      TEXT NOT NULL DEFAULT 'draft',
                status            TEXT NOT NULL DEFAULT 'pending',
                wx_article_id     TEXT,
                wx_url            TEXT,
                error             TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                finished_at       TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_created_at ON wechat_publish_tasks(created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_status ON wechat_publish_tasks(status, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wechat_tasks_article ON wechat_publish_tasks(article_task_id, created_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v18_wechat_publish_tasks", today),
        )

    # v19: Native WeChat Official Account collection tables.
    if "v19_wechat_native_collect" not in applied:
        _ensure_wechat_native_collect_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v19_wechat_native_collect", today),
        )

    # v20: Article generation can consume local WeChat article exports directly.
    if "v20_article_wechat_sources" not in applied:
        _ensure_article_task_columns(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v20_article_wechat_sources", today),
        )

    # v21: Email collection and platform content variants.
    if "v21_email_collect_content_sources" not in applied:
        _ensure_email_collect_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v21_email_collect_content_sources", today),
        )

    # v22: outlookEmail external mailbox source fields.
    if "v22_email_collect_outlook_email_source" not in applied:
        _ensure_email_collect_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v22_email_collect_outlook_email_source", today),
        )

    if "v23_rss_collect_sources" not in applied:
        _ensure_rss_collect_schema(conn)
        _ensure_article_task_columns(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_article_tasks_rss_item "
            "ON article_tasks(rss_item_id, created_at DESC)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v23_rss_collect_sources", today),
        )

    if "v24_weread_exporter_tasks" not in applied:
        _ensure_weread_exporter_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v24_weread_exporter_tasks", today),
        )

    if "v25_rss_catalog_sources" not in applied:
        _ensure_rss_collect_schema(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            ("v25_rss_catalog_sources", today),
        )


def _ensure_email_collect_schema(conn) -> None:
    from monitor.db.queries import email_collect as _email_collect_queries

    _email_collect_queries.ensure_schema(conn)


def _ensure_rss_collect_schema(conn) -> None:
    from monitor.db.queries import rss_collect as _rss_collect_queries

    _rss_collect_queries.ensure_schema(conn)
    _ensure_article_task_columns(conn)


def _ensure_weread_exporter_schema(conn) -> None:
    from monitor.db.queries import weread_exporter as _weread_exporter_queries

    _weread_exporter_queries.ensure_schema(conn)


def _ensure_article_task_columns(conn) -> None:
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "article_tasks" not in tables:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(article_tasks)").fetchall()}
    for col, ddl in ARTICLE_TASK_COLUMN_DDLS:
        if col not in cols:
            conn.execute(f"ALTER TABLE article_tasks ADD COLUMN {col} {ddl}")


def _ensure_voice_tasks_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS voice_tasks (
            task_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            capability TEXT NOT NULL,
            mode TEXT,
            source TEXT,
            source_task_id TEXT,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            stage TEXT,
            message TEXT,
            input_text_hash TEXT,
            input_path TEXT,
            output_audio_path TEXT,
            output_text_path TEXT,
            output_srt_path TEXT,
            metadata_path TEXT,
            options_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            cancel_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_tasks_created_at ON voice_tasks(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_tasks_status ON voice_tasks(status, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_tasks_kind ON voice_tasks(kind, created_at DESC)")


def _ensure_article_wechat_source_columns(conn) -> None:
    _ensure_article_task_columns(conn)


def _ensure_wechat_native_collect_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wechat_collect_sessions (
            session_id      TEXT PRIMARY KEY,
            token_enc       TEXT NOT NULL,
            cookie_json_enc TEXT NOT NULL,
            nickname        TEXT,
            avatar          TEXT,
            status          TEXT NOT NULL DEFAULT 'active',
            expires_at      TEXT NOT NULL,
            last_checked_at TEXT,
            last_error      TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_collect_sessions_status "
        "ON wechat_collect_sessions(status, expires_at)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wechat_collect_accounts (
            fakeid         TEXT PRIMARY KEY,
            nickname       TEXT,
            alias          TEXT,
            round_head_img TEXT,
            service_type   INTEGER,
            signature      TEXT,
            verify_status  INTEGER,
            raw_json       TEXT NOT NULL DEFAULT '{}',
            last_synced_at TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wechat_collect_articles (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            fakeid        TEXT NOT NULL,
            aid           TEXT,
            title         TEXT,
            link          TEXT NOT NULL UNIQUE,
            digest        TEXT,
            cover         TEXT,
            author_name   TEXT,
            update_time   INTEGER,
            create_time   INTEGER,
            raw_json      TEXT NOT NULL DEFAULT '{}',
            local_path    TEXT,
            export_format TEXT,
            status        TEXT NOT NULL DEFAULT 'listed',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            FOREIGN KEY (fakeid) REFERENCES wechat_collect_accounts(fakeid) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_collect_articles_fakeid_update "
        "ON wechat_collect_articles(fakeid, update_time DESC)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wechat_collect_tasks (
            task_id          TEXT PRIMARY KEY,
            provider         TEXT NOT NULL DEFAULT 'native',
            session_id       TEXT,
            source_mode      TEXT NOT NULL,
            fakeid           TEXT,
            article_url      TEXT,
            account_name     TEXT,
            urls_json        TEXT NOT NULL DEFAULT '[]',
            keyword          TEXT,
            export_format    TEXT NOT NULL DEFAULT 'markdown',
            output_dir       TEXT,
            max_articles     INTEGER NOT NULL DEFAULT 50,
            page_size        INTEGER NOT NULL DEFAULT 20,
            delay_seconds    REAL NOT NULL DEFAULT 1.0,
            status           TEXT NOT NULL DEFAULT 'pending',
            total            INTEGER NOT NULL DEFAULT 0,
            completed        INTEGER NOT NULL DEFAULT 0,
            success          INTEGER NOT NULL DEFAULT 0,
            failed           INTEGER NOT NULL DEFAULT 0,
            current          TEXT,
            result_json      TEXT NOT NULL DEFAULT '[]',
            error            TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            finished_at      TEXT
        )"""
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(wechat_collect_tasks)").fetchall()}
    for col, ddl in [
        ("max_articles", "INTEGER NOT NULL DEFAULT 50"),
        ("page_size", "INTEGER NOT NULL DEFAULT 20"),
        ("delay_seconds", "REAL NOT NULL DEFAULT 1.0"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE wechat_collect_tasks ADD COLUMN {col} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_created_at "
        "ON wechat_collect_tasks(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_status "
        "ON wechat_collect_tasks(status, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_provider "
        "ON wechat_collect_tasks(provider, created_at DESC)"
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
            except Exception as e:
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
    from monitor import quota as _quota
    today = _quota.get_quota_date_key()
    with get_connection() as conn:
        # 禁止 SELECT ak.*：api_keys 表含遗留列 quota_used，与下方别名 quota_used 重名时，
        # sqlite3.Row 按列名取值为「第一列」，导致 UI 永远显示表内冻结的 0 而非 api_quota_usage.api_calls。
        rows = conn.execute(
            """SELECT ak.id,
                      ak.key_value,
                      ak.name,
                      ak.daily_quota,
                      ak.quota_reset_at,
                      ak.is_active,
                      ak.created_at,
                      ak.updated_at,
                      COALESCE(aqu.api_calls, 0) AS quota_used,
                      COALESCE(aqu.scans_done, 0) AS scans_done,
                      COALESCE(aqu.blocked_scans, 0) AS blocked_scans
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
    if name is not None:
        fields.append("name=?")
        values.append(name)
    # 空字符串表示"不修改"（前端留空时发送空字符串）
    if key_value:
        fields.append("key_value=?")
        values.append(key_value)
    if daily_quota is not None:
        fields.append("daily_quota=?")
        values.append(daily_quota)
    if is_active is not None:
        fields.append("is_active=?")
        values.append(int(is_active))
    fields.append("updated_at=?")
    values.append(now_iso())
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
    """解密账户的 webhook_url 和 telegram_bot_token；dingtalk_sign_secret 为明文存储，无需解密"""
    if not account:
        return account
    account = dict(account)
    if account.get("webhook_url"):
        account["webhook_url"] = _decrypt_webhook(account["webhook_url"])
    if account.get("telegram_bot_token"):
        account["telegram_bot_token"] = _decrypt_webhook(account["telegram_bot_token"])
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
    telegram_bot_token: str | None = None,
    dingtalk_sign_secret: str | None = None,
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
                telegram_bot_token, dingtalk_sign_secret,
                feishu_message_mode, feishu_template_id, feishu_scan_template_id,
                api_key_id, proxy_pool_id, proxy_enabled, download_proxy_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, channel_url, api_key_env, fetch_mode, fetch_limit,
             scan_interval, int(notify_enabled), notify_platform,
             _encrypt_webhook(webhook_url),
             _encrypt_webhook(telegram_bot_token) if telegram_bot_token else None,
             dingtalk_sign_secret,
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
    telegram_bot_token=_UNSET,
    dingtalk_sign_secret=_UNSET,
    feishu_message_mode: str | None = None,
    feishu_template_id=_UNSET,
    feishu_scan_template_id=_UNSET,
    api_key_id=_UNSET,
    proxy_pool_id=_UNSET,
    proxy_enabled=None,
    download_proxy_mode=_UNSET,
) -> None:
    """更新账户字段。

    对于可空字段（webhook_url / telegram_bot_token / feishu_template_id / feishu_scan_template_id / api_key_id / proxy_pool_id），
    使用 _UNSET 表示「不修改」，传 None 表示「清空为 NULL」。
    """
    fields, values = [], []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if channel_url is not None:
        fields.append("channel_url=?")
        values.append(channel_url)
    if api_key_env is not None:
        fields.append("api_key_env=?")
        values.append(api_key_env)
    if fetch_mode is not None:
        fields.append("fetch_mode=?")
        values.append(fetch_mode)
    if fetch_limit is not None:
        fields.append("fetch_limit=?")
        values.append(fetch_limit)
    if scan_interval is not None:
        fields.append("scan_interval=?")
        values.append(scan_interval)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if notify_enabled is not None:
        fields.append("notify_enabled=?")
        values.append(int(notify_enabled))
    if notify_platform is not None:
        fields.append("notify_platform=?")
        values.append(notify_platform)
    if webhook_url is not _UNSET:
        fields.append("webhook_url=?")
        values.append(_encrypt_webhook(webhook_url))
    if telegram_bot_token is not _UNSET:
        fields.append("telegram_bot_token=?")
        values.append(_encrypt_webhook(telegram_bot_token) if telegram_bot_token else None)
    if dingtalk_sign_secret is not _UNSET:
        fields.append("dingtalk_sign_secret=?")
        values.append(dingtalk_sign_secret)
    if feishu_message_mode is not None:
        fields.append("feishu_message_mode=?")
        values.append(feishu_message_mode)
    if feishu_template_id is not _UNSET:
        fields.append("feishu_template_id=?")
        values.append(feishu_template_id)
    if feishu_scan_template_id is not _UNSET:
        fields.append("feishu_scan_template_id=?")
        values.append(feishu_scan_template_id)
    if api_key_id is not _UNSET:
        fields.append("api_key_id=?")
        values.append(api_key_id)
    if proxy_pool_id is not _UNSET:
        fields.append("proxy_pool_id=?")
        values.append(proxy_pool_id)
    if proxy_enabled is not None:
        fields.append("proxy_enabled=?")
        values.append(int(proxy_enabled))
    if download_proxy_mode is not _UNSET:
        fields.append("download_proxy_mode=?")
        values.append(download_proxy_mode)
    fields.append("updated_at=?")
    values.append(now_iso())
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
        raise ValueError(f"不支持的协议: {scheme}，支持 http/https/socks5/socks4")
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
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if proxy_url is not None:
        fields.append("proxy_url=?")
        values.append(proxy_url)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if not fields:
        return  # 无实际变更，只更新 updated_at 无意义
    fields.append("updated_at=?")
    values.append(now_iso())
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
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if billing_tier is not None:
        fields.append("billing_tier=?")
        values.append(billing_tier)
    if adapter_type is not None:
        fields.append("adapter_type=?")
        values.append(adapter_type)
    if priority is not None:
        fields.append("priority=?")
        values.append(priority)
    if supports_cookies is not None:
        fields.append("supports_cookies=?")
        values.append(int(supports_cookies))
    if supports_auto_download is not None:
        fields.append("supports_auto_download=?")
        values.append(int(supports_auto_download))
    if supports_country_filter is not None:
        fields.append("supports_country_filter=?")
        values.append(int(supports_country_filter))
    if supports_sticky_session is not None:
        fields.append("supports_sticky_session=?")
        values.append(int(supports_sticky_session))
    if risk_level is not None:
        fields.append("risk_level=?")
        values.append(risk_level)
    if notes is not None:
        fields.append("notes=?")
        values.append(notes)
    if config_json is not None:
        existing = get_dynamic_proxy_provider(provider_id) or {}
        merged_config = _merge_masked_config_secrets(
            config_json,
            existing.get("config_json") or {},
        )
        fields.append("config_json=?")
        values.append(json.dumps(_encrypt_config_secrets(merged_config)))
    if last_health_status is not None:
        fields.append("last_health_status=?")
        values.append(last_health_status)
    if last_health_checked_at is not None:
        fields.append("last_health_checked_at=?")
        values.append(last_health_checked_at)
    # None 表示显式清空 last_error_message；省略参数（_UNSET）表示不修改该列
    if last_error_message is not _UNSET:
        fields.append("last_error_message=?")
        values.append(last_error_message)
    if cooldown_until is not None:
        fields.append("cooldown_until=?")
        values.append(cooldown_until)
    if refresh_interval_minutes is not None:
        fields.append("refresh_interval_minutes=?")
        values.append(int(refresh_interval_minutes))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
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


def get_proxy_candidate_by_provider(
    provider_id: int, valid_only: bool = True, order_by_score_desc: bool = True
) -> list[dict]:
    """
    按 provider_id 获取候选节点列表。
    valid_only=True 时过滤 ttl_expires_at > now。
    order_by_score_desc=True（默认）：按 score DESC（展示、兼容旧逻辑）。
    order_by_score_desc=False：按 id ASC，供下载选路拉全量后再做与预览一致的排序，避免高分非 healthy 占满截取窗口。
    """
    now = now_iso()
    order_clause = "ORDER BY score DESC" if order_by_score_desc else "ORDER BY id ASC"
    with get_connection() as conn:
        if valid_only:
            rows = conn.execute(
                f"""SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=? AND (ttl_expires_at IS NULL OR ttl_expires_at > ?)
                   {order_clause}""",
                (provider_id, now),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=?
                   {order_clause}""",
                (provider_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _healthy_preview_sort_key_row(r: dict) -> tuple[int, int, float]:
    """与候选预览「当前最优」一致：有效 latency 优先，升序；再按 score 降序。"""
    lm = r.get("latency_ms")
    if isinstance(lm, int) and lm >= 0:
        tier = 0
        lat = lm
    else:
        tier = 1
        lat = 0
    sc = r.get("score", 0.0)
    score_f = float(sc) if isinstance(sc, (int, float)) else 0.0
    return (tier, lat, -score_f)


def rank_healthy_candidates_preview_aligned(rows: list[dict]) -> list[dict]:
    """
    仅 last_probe_status == healthy 的条目，按预览同款规则排序（latency → score）。
    供下载选路与预览共用，保证「当前最优」与首轮代理一致。
    """
    healthy = [
        r
        for r in rows
        if str(r.get("last_probe_status") or "").strip().lower() == "healthy"
    ]
    if not healthy:
        return []
    return sorted(healthy, key=_healthy_preview_sort_key_row)


def pick_healthy_fastest_top_candidate(rows: list[dict]) -> dict | None:
    """
    预览/摘要用「当前最优」：last_probe_status == healthy，
    再按 latency_ms 升序（正序）排序，取延迟最小的一条；并列时 score 高者优先。
    无 healthy 时返回 None。无有效 latency 的 healthy 排在有数值者之后。
    """
    ranked = rank_healthy_candidates_preview_aligned(rows)
    if not ranked:
        return None
    best = ranked[0]
    sc = best.get("score", 0.0)
    score_f = float(sc) if isinstance(sc, (int, float)) else 0.0
    return {
        "masked_proxy_endpoint": best.get("masked_proxy_endpoint"),
        "last_probe_status": best.get("last_probe_status"),
        "latency_ms": best.get("latency_ms"),
        "score": score_f,
    }


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


# ── web_batch_tasks CRUD ────────────────────────────────────

def _normalize_web_batch_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    try:
        item["results"] = json.loads(item.get("results_json") or "[]")
    except Exception:
        item["results"] = []
    try:
        item["urls"] = json.loads(item.get("urls") or "[]")
    except Exception:
        item["urls"] = []
    item.pop("results_json", None)
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    return item


def save_web_batch_task(task: dict) -> None:
    """Insert or update a persisted Web batch task snapshot."""
    payload = {
        "task_id": task.get("task_id"),
        "task_kind": task.get("task_kind", "web_batch"),
        "source_name": task.get("source_name"),
        "output_path": task.get("output_path"),
        "status": task.get("status", "running"),
        "total": int(task.get("total", 0)),
        "completed": int(task.get("completed", 0)),
        "success": int(task.get("success", 0)),
        "failed": int(task.get("failed", 0)),
        "current_video": task.get("current_video") or "",
        "error": task.get("error"),
        "cancel_requested": int(bool(task.get("cancel_requested"))),
        "cancel_message": task.get("cancel_message"),
        "urls": json.dumps(task.get("urls", []) or [], ensure_ascii=False),
        "results_json": json.dumps(task.get("results", []) or [], ensure_ascii=False),
        "created_at": task.get("created_at") or now_iso(),
        "finished_at": task.get("finished_at"),
        "updated_at": now_iso(),
    }
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO web_batch_tasks
               (task_id, task_kind, source_name, output_path, status, total, completed, success, failed,
                current_video, error, cancel_requested, cancel_message, urls, results_json,
                created_at, finished_at, updated_at)
               VALUES (:task_id, :task_kind, :source_name, :output_path, :status, :total, :completed,
                       :success, :failed, :current_video, :error, :cancel_requested, :cancel_message,
                       :urls, :results_json, :created_at, :finished_at, :updated_at)
               ON CONFLICT(task_id) DO UPDATE SET
                 task_kind=excluded.task_kind,
                 source_name=excluded.source_name,
                 output_path=excluded.output_path,
                 status=excluded.status,
                 total=excluded.total,
                 completed=excluded.completed,
                 success=excluded.success,
                 failed=excluded.failed,
                 current_video=excluded.current_video,
                 error=excluded.error,
                 cancel_requested=excluded.cancel_requested,
                 cancel_message=excluded.cancel_message,
                 urls=excluded.urls,
                 results_json=excluded.results_json,
                 created_at=excluded.created_at,
                 finished_at=excluded.finished_at,
                 updated_at=excluded.updated_at""",
            payload,
        )


def get_web_batch_task(task_id: str) -> dict | None:
    """Load a persisted Web batch task by task_id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM web_batch_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return _normalize_web_batch_task_row(row)


def list_web_batch_tasks(limit: int = 50) -> list[dict]:
    """List persisted Web batch tasks ordered by newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM web_batch_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_normalize_web_batch_task_row(row) for row in rows]


def mark_incomplete_web_batch_tasks_interrupted() -> None:
    """Convert stale running/cancelling persisted tasks to interrupted errors on startup."""
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE web_batch_tasks
               SET status='error',
                   error=COALESCE(error, '服务重启导致任务中断'),
                   current_video='服务重启导致任务中断',
                   finished_at=COALESCE(finished_at, ?),
                   updated_at=?,
                   cancel_requested=0
               WHERE status IN ('running', 'cancelling')""",
            (now, now),
        )


# ── AI 内容工作流任务 CRUD ────────────────────────────────

_AI_TASK_TERMINAL_STATUSES = {"done", "error", "cancelled", "interrupted"}
_AI_TASK_FAILED_TERMINAL_STATUSES = {"error", "cancelled", "interrupted"}
_AI_TASK_ACTIVE_STAGE_STATUSES = {"pending", "running", "cancelling"}
_AI_TASK_TERMINAL_STAGE_MESSAGES = {
    "error": "任务失败",
    "cancelled": "任务已取消",
    "interrupted": "服务重启导致任务中断",
}


def _json_loads_or(raw, default):
    try:
        return json.loads(raw) if raw not in (None, "") else default
    except Exception:
        return default


def _normalize_ai_task_stages_for_status(
    status: str | None,
    current_stage: str | None,
    stages,
):
    if status not in _AI_TASK_FAILED_TERMINAL_STATUSES or not isinstance(stages, dict):
        return stages

    normalized = dict(stages)
    preferred_keys = [str(current_stage)] if current_stage and str(current_stage) in normalized else []
    active_keys = [
        key
        for key, stage in normalized.items()
        if isinstance(stage, dict)
        and str(stage.get("status") or "").lower() in _AI_TASK_ACTIVE_STAGE_STATUSES
        and key not in preferred_keys
    ]
    for key in preferred_keys + active_keys:
        stage = normalized.get(key)
        if not isinstance(stage, dict):
            continue
        if str(stage.get("status") or "").lower() not in _AI_TASK_ACTIVE_STAGE_STATUSES:
            continue
        next_stage = dict(stage)
        terminal_message = _AI_TASK_TERMINAL_STAGE_MESSAGES.get(status, status)
        current_message = str(next_stage.get("message") or "").strip()
        next_stage["status"] = status
        if current_message and terminal_message not in current_message:
            next_stage["message"] = f"{current_message}；{terminal_message}"
        else:
            next_stage["message"] = current_message or terminal_message
        normalized[key] = next_stage
    return normalized


def _build_ai_task_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _normalize_article_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["auto_translate"] = bool(item.get("auto_translate"))
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    stages_json = item.pop("stages_json", None) or item.get("stage_json")
    item["stages"] = _normalize_ai_task_stages_for_status(
        item.get("status"),
        item.get("current_stage"),
        _json_loads_or(stages_json, {}),
    )
    item["result"] = _json_loads_or(item.pop("result_json", "{}"), {})
    return item


def _normalize_video_gen_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    stages_json = item.pop("stages_json", None) or item.get("stage_json")
    item["stages"] = _normalize_ai_task_stages_for_status(
        item.get("status"),
        item.get("current_stage"),
        _json_loads_or(stages_json, {}),
    )
    item["result"] = _json_loads_or(item.pop("result_json", "{}"), {})
    item["template_name"] = item.get("template_name") or item.get("template_key")
    item["output_path"] = item.get("output_path") or item.get("video_path")
    return item


def _normalize_voice_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    item["progress"] = int(item.get("progress") or 0)
    item["options"] = _json_loads_or(item.pop("options_json", "{}"), {})
    item["result"] = _json_loads_or(item.pop("result_json", "{}"), {})
    return item


def create_voice_task(
    *,
    kind: str,
    provider: str,
    capability: str,
    mode: str | None = None,
    source: str | None = None,
    source_task_id: str | None = None,
    input_text_hash: str | None = None,
    input_path: str | None = None,
    options: dict | None = None,
    task_id: str | None = None,
) -> str:
    task_id = task_id or _build_ai_task_id("voice")
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO voice_tasks
               (task_id, kind, provider, capability, mode, source, source_task_id,
                status, progress, input_text_hash, input_path, options_json, result_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, '{}', ?, ?)""",
            (
                task_id,
                kind,
                provider,
                capability,
                mode,
                source,
                source_task_id,
                input_text_hash,
                input_path,
                json.dumps(options or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
    return task_id


def update_voice_task(
    task_id: str,
    *,
    provider=_UNSET,
    status=_UNSET,
    progress=_UNSET,
    stage=_UNSET,
    message=_UNSET,
    input_path=_UNSET,
    output_audio_path=_UNSET,
    output_text_path=_UNSET,
    output_srt_path=_UNSET,
    metadata_path=_UNSET,
    result=_UNSET,
    error=_UNSET,
    cancel_requested=_UNSET,
    cancel_message=_UNSET,
    finished_at=_UNSET,
) -> None:
    fields = []
    values = []
    mapping = [
        ("provider", provider),
        ("status", status),
        ("progress", progress),
        ("stage", stage),
        ("message", message),
        ("input_path", input_path),
        ("output_audio_path", output_audio_path),
        ("output_text_path", output_text_path),
        ("output_srt_path", output_srt_path),
        ("metadata_path", metadata_path),
        ("error", error),
        ("cancel_message", cancel_message),
        ("finished_at", finished_at),
    ]
    for field, value in mapping:
        if value is not _UNSET:
            fields.append(f"{field}=?")
            values.append(value)
    if result is not _UNSET:
        fields.append("result_json=?")
        values.append(json.dumps(result or {}, ensure_ascii=False))
    if cancel_requested is not _UNSET:
        fields.append("cancel_requested=?")
        values.append(int(bool(cancel_requested)))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE voice_tasks SET {', '.join(fields)} WHERE task_id = ?", values)


def get_voice_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM voice_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return _normalize_voice_task_row(row)


def list_voice_tasks(
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where = []
    params = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM voice_tasks WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM voice_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return ([_normalize_voice_task_row(row) for row in rows], total)


def request_cancel_voice_task(task_id: str, message: str | None = None) -> dict | None:
    task = get_voice_task(task_id)
    if not task:
        return None
    if task.get("status") not in _AI_TASK_TERMINAL_STATUSES:
        next_status = "cancelling" if task.get("status") != "pending" else "cancelled"
        finished_at = now_iso() if next_status == "cancelled" else _UNSET
        update_voice_task(
            task_id,
            status=next_status,
            cancel_requested=True,
            cancel_message=message or "正在取消语音任务…",
            finished_at=finished_at,
        )
    return get_voice_task(task_id)


def create_article_task(
    monitor_video_id: int | None,
    video_id: str | None,
    video_url: str | None,
    video_title: str | None,
    *,
    source_type: str = "video",
    article_source_path: str | None = None,
    article_text: str | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
    email_message_id: int | None = None,
    rss_item_id: int | None = None,
    target_lang: str = "zh-Hans",
    auto_translate: bool = True,
    output_dir: str | None = None,
    task_id: str | None = None,
) -> str:
    task_id = task_id or _build_ai_task_id("article")
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO article_tasks
               (task_id, source_type, monitor_video_id, video_id, video_url, video_title,
                article_source_path, article_text, source_url, source_title,
                email_message_id, rss_item_id,
                status, target_lang, auto_translate, output_dir,
                stages_json, result_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, '{}', '{}', ?, ?)""",
            (
                task_id,
                source_type or "video",
                monitor_video_id,
                video_id,
                video_url,
                video_title,
                article_source_path,
                article_text,
                source_url,
                source_title,
                email_message_id,
                rss_item_id,
                target_lang,
                int(bool(auto_translate)),
                output_dir,
                now,
                now,
            ),
        )
    return task_id


def update_article_task(
    task_id: str,
    *,
    status=_UNSET,
    current_stage=_UNSET,
    source_lang=_UNSET,
    target_lang=_UNSET,
    output_dir=_UNSET,
    draft_path=_UNSET,
    transcript_path=_UNSET,
    optimized_path=_UNSET,
    summary_path=_UNSET,
    translated_path=_UNSET,
    stages=_UNSET,
    result=_UNSET,
    error=_UNSET,
    cancel_requested=_UNSET,
    cancel_message=_UNSET,
    finished_at=_UNSET,
) -> None:
    fields = []
    values = []
    mapping = [
        ("status", status),
        ("current_stage", current_stage),
        ("source_lang", source_lang),
        ("target_lang", target_lang),
        ("output_dir", output_dir),
        ("draft_path", draft_path),
        ("transcript_path", transcript_path),
        ("optimized_path", optimized_path),
        ("summary_path", summary_path),
        ("translated_path", translated_path),
        ("error", error),
        ("cancel_message", cancel_message),
        ("finished_at", finished_at),
    ]
    for field, value in mapping:
        if value is not _UNSET:
            fields.append(f"{field}=?")
            values.append(value)
    if stages is not _UNSET:
        stages_payload = json.dumps(stages or {}, ensure_ascii=False)
        fields.append("stages_json=?")
        values.append(stages_payload)
        fields.append("stage_json=?")
        values.append(stages_payload)
    if result is not _UNSET:
        fields.append("result_json=?")
        values.append(json.dumps(result or {}, ensure_ascii=False))
    if cancel_requested is not _UNSET:
        fields.append("cancel_requested=?")
        values.append(int(bool(cancel_requested)))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE article_tasks SET {', '.join(fields)} WHERE task_id = ?", values)


def get_article_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM article_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return _normalize_article_task_row(row)


def list_article_tasks(
    *,
    status: str | None = None,
    monitor_video_id: int | None = None,
    source_type: str | None = None,
    email_message_id: int | None = None,
    rss_item_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if monitor_video_id is not None:
        where.append("monitor_video_id = ?")
        params.append(monitor_video_id)
    if source_type:
        where.append("source_type = ?")
        params.append(source_type)
    if email_message_id is not None:
        where.append("email_message_id = ?")
        params.append(email_message_id)
    if rss_item_id is not None:
        where.append("rss_item_id = ?")
        params.append(rss_item_id)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM article_tasks WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM article_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return ([_normalize_article_task_row(row) for row in rows], total)


def request_cancel_article_task(task_id: str, message: str | None = None) -> dict | None:
    task = get_article_task(task_id)
    if not task:
        return None
    if task.get("status") not in _AI_TASK_TERMINAL_STATUSES:
        next_status = "cancelling" if task.get("status") != "pending" else "cancelled"
        finished_at = now_iso() if next_status == "cancelled" else _UNSET
        update_article_task(
            task_id,
            status=next_status,
            cancel_requested=True,
            cancel_message=message or "正在取消文章任务…",
            finished_at=finished_at,
        )
    return get_article_task(task_id)


def create_video_gen_task(
    *,
    mode: str,
    topic: str | None,
    script_text: str | None,
    template_key: str,
    scene_count: int,
    prompt_prefix: str | None = None,
    image_workflow: str | None = None,
    tts_workflow: str | None = None,
    bgm_volume: float | None = None,
    output_dir: str | None = None,
    task_id: str | None = None,
) -> str:
    task_id = task_id or _build_ai_task_id("video_gen")
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO video_gen_tasks
               (task_id, mode, topic, script_text, template_key, template_name, scene_count,
                prompt_prefix, image_workflow, tts_workflow, bgm_volume,
                status, output_dir, stages_json, result_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, '{}', '{}', ?, ?)""",
            (
                task_id,
                mode,
                topic,
                script_text,
                template_key,
                template_key,
                scene_count,
                prompt_prefix,
                image_workflow,
                tts_workflow,
                bgm_volume,
                output_dir,
                now,
                now,
            ),
        )
    return task_id


def update_video_gen_task(
    task_id: str,
    *,
    mode=_UNSET,
    topic=_UNSET,
    script_text=_UNSET,
    template_key=_UNSET,
    prompt_prefix=_UNSET,
    image_workflow=_UNSET,
    tts_workflow=_UNSET,
    bgm_volume=_UNSET,
    scene_count=_UNSET,
    status=_UNSET,
    current_stage=_UNSET,
    output_dir=_UNSET,
    storyboard_path=_UNSET,
    video_path=_UNSET,
    duration_sec=_UNSET,
    file_size=_UNSET,
    stages=_UNSET,
    result=_UNSET,
    error=_UNSET,
    cancel_requested=_UNSET,
    cancel_message=_UNSET,
    finished_at=_UNSET,
) -> None:
    fields = []
    values = []
    mapping = [
        ("mode", mode),
        ("topic", topic),
        ("script_text", script_text),
        ("prompt_prefix", prompt_prefix),
        ("image_workflow", image_workflow),
        ("tts_workflow", tts_workflow),
        ("bgm_volume", bgm_volume),
        ("scene_count", scene_count),
        ("status", status),
        ("current_stage", current_stage),
        ("output_dir", output_dir),
        ("storyboard_path", storyboard_path),
        ("duration_sec", duration_sec),
        ("file_size", file_size),
        ("error", error),
        ("cancel_message", cancel_message),
        ("finished_at", finished_at),
    ]
    for field, value in mapping:
        if value is not _UNSET:
            fields.append(f"{field}=?")
            values.append(value)
    if template_key is not _UNSET:
        fields.append("template_key=?")
        values.append(template_key)
        fields.append("template_name=?")
        values.append(template_key)
    if video_path is not _UNSET:
        fields.append("video_path=?")
        values.append(video_path)
        fields.append("output_path=?")
        values.append(video_path)
    if stages is not _UNSET:
        stages_payload = json.dumps(stages or {}, ensure_ascii=False)
        fields.append("stages_json=?")
        values.append(stages_payload)
        fields.append("stage_json=?")
        values.append(stages_payload)
    if result is not _UNSET:
        fields.append("result_json=?")
        values.append(json.dumps(result or {}, ensure_ascii=False))
    if cancel_requested is not _UNSET:
        fields.append("cancel_requested=?")
        values.append(int(bool(cancel_requested)))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE video_gen_tasks SET {', '.join(fields)} WHERE task_id = ?", values)


def get_video_gen_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM video_gen_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return _normalize_video_gen_task_row(row)


def list_video_gen_tasks(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM video_gen_tasks WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM video_gen_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return ([_normalize_video_gen_task_row(row) for row in rows], total)


def request_cancel_video_gen_task(task_id: str, message: str | None = None) -> dict | None:
    task = get_video_gen_task(task_id)
    if not task:
        return None
    if task.get("status") not in _AI_TASK_TERMINAL_STATUSES:
        next_status = "cancelling" if task.get("status") != "pending" else "cancelled"
        finished_at = now_iso() if next_status == "cancelled" else _UNSET
        update_video_gen_task(
            task_id,
            status=next_status,
            cancel_requested=True,
            cancel_message=message or "正在取消视频生成任务…",
            finished_at=finished_at,
        )
    return get_video_gen_task(task_id)


def mark_incomplete_ai_content_tasks_interrupted() -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE article_tasks
               SET status='interrupted',
                   error=CASE WHEN error IS NULL OR error = '' THEN '服务重启导致任务中断' ELSE error END,
                   finished_at=COALESCE(finished_at, ?),
                   updated_at=?,
                   cancel_requested=0
               WHERE status IN ('pending', 'running', 'cancelling')""",
            (now, now),
        )
        conn.execute(
            """UPDATE video_gen_tasks
               SET status='interrupted',
                   error=CASE WHEN error IS NULL OR error = '' THEN '服务重启导致任务中断' ELSE error END,
                   finished_at=COALESCE(finished_at, ?),
                   updated_at=?,
                   cancel_requested=0
               WHERE status IN ('pending', 'running', 'cancelling')""",
            (now, now),
        )
        conn.execute(
            """UPDATE wechat_publish_tasks
               SET status='interrupted',
                   error=CASE WHEN error IS NULL OR error = '' THEN '服务重启导致任务中断' ELSE error END,
                   finished_at=COALESCE(finished_at, ?),
                   updated_at=?
               WHERE status IN ('pending', 'running', 'cancelling')""",
            (now, now),
        )


# ── wechat_publish_tasks CRUD ─────────────────────────────────

def _normalize_wechat_publish_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["need_open_comment"] = bool(item.get("need_open_comment"))
    item["only_fans_can_comment"] = bool(item.get("only_fans_can_comment"))
    return item


def create_wechat_publish_task(
    draft_path: str,
    title: str | None,
    *,
    article_task_id: str | None = None,
    author: str | None = None,
    theme: str = "default",
    color: str = "blue",
    need_open_comment: bool = True,
    only_fans_can_comment: bool = False,
    cover_image: str | None = None,
    html_content: str | None = None,
    publish_mode: str = "draft",
) -> str:
    """Create a WeChat publish task and return task_id."""
    task_id = f"wechat_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_publish_tasks
               (task_id, article_task_id, draft_path, title, author,
                theme, color, need_open_comment, only_fans_can_comment,
                cover_image, html_content, publish_mode, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                task_id,
                article_task_id,
                draft_path,
                title,
                author,
                theme,
                color,
                int(bool(need_open_comment)),
                int(bool(only_fans_can_comment)),
                cover_image,
                html_content,
                publish_mode,
                now,
                now,
            ),
        )
    return task_id


def update_wechat_publish_task(
    task_id: str,
    *,
    status=_UNSET,
    wx_article_id=_UNSET,
    wx_url=_UNSET,
    error=_UNSET,
    finished_at=_UNSET,
    html_content=_UNSET,
) -> None:
    """Update a WeChat publish task."""
    fields = []
    values = []
    mapping = [
        ("status", status),
        ("wx_article_id", wx_article_id),
        ("wx_url", wx_url),
        ("error", error),
        ("finished_at", finished_at),
        ("html_content", html_content),
    ]
    for field, value in mapping:
        if value is not _UNSET:
            fields.append(f"{field}=?")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE wechat_publish_tasks SET {', '.join(fields)} WHERE task_id = ?",
            values,
        )


def get_wechat_publish_task(task_id: str) -> dict | None:
    """Get one WeChat publish task."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_publish_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return _normalize_wechat_publish_task_row(row)


def list_wechat_publish_tasks(
    *,
    status: str | None = None,
    article_task_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List WeChat publish tasks with pagination."""
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if article_task_id:
        where.append("article_task_id = ?")
        params.append(article_task_id)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM wechat_publish_tasks WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM wechat_publish_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return ([_normalize_wechat_publish_task_row(row) for row in rows], total)


def get_wechat_publish_monthly_usage(month_key: str | None = None) -> dict:
    """Return local monthly WeChat freepublish usage tracked by this service."""
    month = (month_key or now_iso()[:7]).strip()[:7]
    with get_connection() as conn:
        used = conn.execute(
            """SELECT COUNT(*) FROM wechat_publish_tasks
               WHERE publish_mode = 'publish'
                 AND status = 'done'
                 AND substr(COALESCE(finished_at, updated_at, created_at), 1, 7) = ?""",
            (month,),
        ).fetchone()[0]
        active = conn.execute(
            """SELECT COUNT(*) FROM wechat_publish_tasks
               WHERE publish_mode = 'publish'
                 AND status IN ('pending', 'running')
                 AND substr(created_at, 1, 7) = ?""",
            (month,),
        ).fetchone()[0]
    return {"month": month, "used": int(used or 0), "active": int(active or 0)}


# ── 工具函数 ─────────────────────────────────────────────────

def mask_proxy_url(url: str | None) -> str | None:
    """掩码代理 URL，返回安全可日志输出的格式。"""
    if not url:
        return None
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        # 掩码 user:pass@host:port 部分
        masked_netloc = "***:****@***:****"
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


def get_account_videos_filtered(
    account_id: int,
    status: str | None = None,
) -> list[dict]:
    """查询账户视频列表，可按下载状态过滤；用于详情页状态筛选。"""
    where_clauses = ["account_id = ?"]
    params: list = [account_id]
    if status:
        where_clauses.append("download_status = ?")
        params.append(status)

    where_sql = " AND ".join(where_clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT
                id, video_id, title, description, url,
                published_at, upload_date, duration_sec,
                view_count, like_count, comment_count,
                notify_status, download_status, download_at, download_path,
                fetched_at, retry_count, failed_reason, failed_at
               FROM monitor_videos
               WHERE {where_sql}
               ORDER BY published_at DESC, id DESC
               LIMIT 100""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def update_videos_download_status(
    video_ids: list[int],
    status: str | None = None,
    download_at: str | None = None,
    download_path: str | None = None,
    download_error: str | None = None,
    retry_count: int | None = None,
    failed_reason: str | None = None,
    failed_at: str | None = None,
) -> int:
    """批量更新视频下载状态及重试字段"""
    if not video_ids:
        return 0
    fields = []
    values: list = []
    if status:
        fields.append("download_status = ?")
        values.append(status)
    if download_at:
        fields.append("downloaded_at = ?")
        values.append(download_at)
    if download_path:
        fields.append("downloaded_path = ?")
        values.append(download_path)
    if download_error:
        fields.append("download_error = ?")
        values.append(download_error)
    if retry_count is not None:
        fields.append("retry_count = ?")
        values.append(retry_count)
    if failed_reason is not None:
        fields.append("failed_reason = ?")
        values.append(failed_reason)
    if failed_at is not None:
        fields.append("failed_at = ?")
        values.append(failed_at)
    if not fields:
        return 0
    placeholders = ",".join("?" * len(video_ids))
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
            f"""SELECT id, video_id, title, url, download_status, account_id,
                       retry_count, failed_reason, failed_at
                FROM monitor_videos WHERE id IN ({placeholders})""",
            video_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def reset_videos_for_retry(video_ids: list[int], account_id: int) -> None:
    """
    Reset failed videos to pending for retry.
    Uses parameterized queries to prevent SQL injection.
    """
    if not video_ids:
        return
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"""UPDATE monitor_videos
               SET download_status = 'pending',
                   retry_count = 0,
                   failed_reason = NULL,
                   failed_at = NULL,
                   failed_event_id = NULL
               WHERE id IN ({placeholders})
               AND download_status = 'failed'""",
            video_ids,
        )


def mark_stale_running_videos_interrupted() -> None:
    """
    Mark running videos as failed on process restart.
    Prevents zombie tasks where download_status='running' never ends.
    """
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_videos
               SET download_status = 'failed',
                   failed_reason = '服务重启导致任务中断',
                   failed_at = ?,
                   retry_count = 0
               WHERE download_status = 'running'""",
            (now,),
        )


def get_scheduler_state() -> dict:
    """返回调度器的运行状态"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='scheduler_state'"
        ).fetchone()
        if row:
            return json.loads(row[0])
        return {"running": False, "started_at": None}


def set_scheduler_state(state: dict) -> None:
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
        # 排除敏感数据：api_keys 表 + app_state 中的密钥/token
        _EXCLUDED_APP_STATE_KEYS = ("webhook_enc_key", "api_token")
        conn_backup = sqlite3.connect(backup_path)
        conn_src = sqlite3.connect(_DB_PATH)
        conn_backup.execute("PRAGMA journal_mode=WAL")
        for line in conn_src.iterdump():
            stripped = line.strip()
            if (stripped.startswith("CREATE TABLE api_keys")
                    or stripped.startswith("INSERT INTO api_keys")):
                continue
            if stripped.startswith("INSERT INTO app_state"):
                import re
                match = re.search(r"VALUES\s*\(\s*'([^']+)'", stripped)
                if match and match.group(1) in _EXCLUDED_APP_STATE_KEYS:
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


# ── AI 视频切片任务 ───────────────────────────────────────────

def get_monitor_video(video_id: int) -> dict | None:
    """根据 monitor_videos.id 获取单条视频记录"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_videos WHERE id = ?", (video_id,),
        ).fetchone()
        return dict(row) if row else None


def create_clip_task(
    video_id: int,
    monitor_video_id: int,
    account_id: int,
    account_name: str,
    video_title: str,
    video_path: str,
    srt_path: str,
    output_dir: str,
    llm_provider: str = "qwen",
    llm_model: str | None = None,
    min_score: float = 7.0,
    category: str = "knowledge",
) -> int:
    """创建一条切片任务记录，返回新任务的 id"""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO clip_tasks
            (video_id, monitor_video_id, account_id, account_name, video_title,
             video_path, srt_path, output_dir, llm_provider, llm_model,
             min_score, category, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending',
                    ?)""",
            (
                video_id, monitor_video_id, account_id, account_name, video_title,
                video_path, srt_path, output_dir, llm_provider, llm_model,
                min_score, category,
                datetime.now().isoformat(),
            ),
        )
        return cursor.lastrowid or 0


def update_clip_task(
    task_id: int,
    status: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    clip_count: int | None = None,
    collection_count: int | None = None,
    error: str | None = None,
) -> None:
    """更新切片任务状态和结果"""
    fields, values = [], []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if started_at is not None:
        fields.append("started_at = ?")
        values.append(started_at)
    if finished_at is not None:
        fields.append("finished_at = ?")
        values.append(finished_at)
    if clip_count is not None:
        fields.append("clip_count = ?")
        values.append(clip_count)
    if collection_count is not None:
        fields.append("collection_count = ?")
        values.append(collection_count)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if not fields:
        return
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE clip_tasks SET {', '.join(fields)} WHERE id = ?", values)


def get_clip_task(task_id: int) -> dict | None:
    """获取单个切片任务详情（包含 clips + collections 列表）"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM clip_tasks WHERE id = ?", (task_id,),
        ).fetchone()
        if not row:
            return None
        task = dict(row)

    # 尝试读取 clips_metadata.json + step6_clips_result.json，补充 clips 和 collections
    output_dir = task.get("output_dir")
    if output_dir:
        meta_path = Path(output_dir) / "clips_metadata.json"
        step6_path = Path(output_dir) / "step6_clips_result.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                step6_clips = []
                if step6_path.exists():
                    step6_clips = json.loads(step6_path.read_text(encoding="utf-8"))
                # 合并：step6 有 clip_path，meta 有 title/score/start_time
                clips_with_titles = meta.get("clips_with_titles", [])
                id_to_path = {c.get("id"): c.get("clip_path") for c in step6_clips}
                task["clips"] = [
                    {**ct, "clip_path": id_to_path.get(ct.get("id"), "")}
                    for ct in clips_with_titles
                ]
                task["collections"] = meta.get("collections", [])
                task["clip_count"] = len(task["clips"])
                task["collection_count"] = len(task["collections"])
            except Exception:
                task["clips"] = []
                task["collections"] = []
        else:
            task["clips"] = []
            task["collections"] = []
    else:
        task["clips"] = []
        task["collections"] = []

    return task


def list_clip_tasks(
    account_id: int | None = None,
    monitor_video_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    分页查询切片任务列表。
    :return: (tasks, total_count)
    """
    where_clauses = []
    params: list = []
    if account_id is not None:
        where_clauses.append("account_id = ?")
        params.append(account_id)
    if monitor_video_id is not None:
        where_clauses.append("monitor_video_id = ?")
        params.append(monitor_video_id)
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM clip_tasks WHERE {where_sql}", params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, monitor_video_id, account_id, account_name, video_title,
                       video_path, srt_path, output_dir,
                       llm_provider, llm_model, min_score, category,
                       status, started_at, finished_at,
                       clip_count, collection_count, error, created_at
                FROM clip_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

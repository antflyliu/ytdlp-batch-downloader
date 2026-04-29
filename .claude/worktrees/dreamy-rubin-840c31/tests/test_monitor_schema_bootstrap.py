"""Regression tests for monitor schema bootstrap and legacy upgrades."""
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db  # noqa: E402


@pytest.fixture()
def db_module(tmp_path, monkeypatch):
    db = monitor_db
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))
    return db


def _table_columns(db_module, table_name: str) -> set[str]:
    with db_module.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def test_init_db_bootstraps_runtime_schema_objects_on_fresh_database(db_module):
    db_module.init_db()

    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }

    assert {
        "api_quota_usage",
        "channel_meta_cache",
        "schema_migrations",
        "dynamic_proxy_providers",
        "download_decision_logs",
        "provider_scheduler_runs",
        "web_batch_tasks",
    } <= tables
    assert {"download_proxy_mode", "dingtalk_sign_secret"} <= _table_columns(
        db_module, "monitor_accounts"
    )
    assert {"api_key_value", "date_key", "updated_at"} <= _table_columns(
        db_module, "api_quota_usage"
    )
    assert "refresh_interval_minutes" in _table_columns(
        db_module, "dynamic_proxy_providers"
    )
    assert {"results_json", "cancel_requested", "cancel_message"} <= _table_columns(
        db_module, "web_batch_tasks"
    )
    assert {
        "idx_web_batch_tasks_created_at",
        "idx_web_batch_tasks_status",
        "idx_provider_scheduler_runs_started_at",
        "idx_provider_scheduler_runs_provider_id",
        "idx_download_decision_account",
    } <= indexes


def test_init_db_upgrades_legacy_database_columns_and_tables(db_module):
    legacy_db_path = Path(db_module._DB_PATH)
    with sqlite3.connect(legacy_db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE monitor_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                channel_url TEXT NOT NULL,
                api_key_env TEXT NOT NULL,
                fetch_mode TEXT NOT NULL DEFAULT 'playlist',
                fetch_limit INTEGER NOT NULL DEFAULT 5,
                scan_interval INTEGER NOT NULL DEFAULT 5,
                enabled INTEGER NOT NULL DEFAULT 1,
                notify_enabled INTEGER NOT NULL DEFAULT 1,
                notify_platform TEXT NOT NULL DEFAULT 'feishu',
                webhook_url TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE api_quota_usage (
                api_key_env TEXT NOT NULL,
                date_key TEXT NOT NULL,
                api_calls INTEGER DEFAULT 0,
                scans_done INTEGER DEFAULT 0,
                blocked_scans INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (api_key_env, date_key)
            );

            CREATE TABLE dynamic_proxy_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                billing_tier TEXT NOT NULL DEFAULT 'free',
                adapter_type TEXT NOT NULL DEFAULT 'public_feed',
                priority INTEGER NOT NULL DEFAULT 100,
                supports_cookies INTEGER NOT NULL DEFAULT 0,
                supports_auto_download INTEGER NOT NULL DEFAULT 1,
                supports_country_filter INTEGER NOT NULL DEFAULT 0,
                supports_sticky_session INTEGER NOT NULL DEFAULT 0,
                risk_level TEXT NOT NULL DEFAULT 'medium',
                notes TEXT DEFAULT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                last_health_status TEXT DEFAULT NULL,
                last_health_checked_at TEXT DEFAULT NULL,
                last_error_message TEXT DEFAULT NULL,
                cooldown_until TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO monitor_accounts
                (name, channel_url, api_key_env, created_at, updated_at)
            VALUES
                ('Legacy account', '@legacy_channel', 'YOUTUBE_DATA_API_V3',
                 '2026-04-10T10:00:00+08:00', '2026-04-10T10:00:00+08:00')
            """
        )

    db_module.init_db()

    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        applied = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

    monitor_account_columns = _table_columns(db_module, "monitor_accounts")
    quota_columns = _table_columns(db_module, "api_quota_usage")
    provider_columns = _table_columns(db_module, "dynamic_proxy_providers")

    assert "download_proxy_mode" in monitor_account_columns
    assert "dingtalk_sign_secret" in monitor_account_columns
    assert "api_key_value" in quota_columns
    assert "api_key_env" not in quota_columns
    assert "refresh_interval_minutes" in provider_columns
    assert "web_batch_tasks" in tables
    assert {
        "v7_dynamic_proxy",
        "v8_dynamic_proxy_candidates",
        "v9_provider_refresh_interval",
        "v10_provider_scheduler_runs",
        "v11_web_batch_tasks",
        "v12_monitor_accounts_dingtalk_sign_secret",
        "v15_clip_tasks_enhancements",
        "v16_failed_retry_fields",
    } <= applied

    # v16: verify monitor_videos has retry fields
    video_columns = _table_columns(db_module, "monitor_videos")
    assert {"failed_reason", "failed_at", "failed_event_id", "retry_count"} <= video_columns

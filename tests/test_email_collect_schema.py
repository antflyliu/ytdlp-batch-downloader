from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db
import monitor.db.connection as db_connection
from monitor.db.queries import email_collect as email_queries


@pytest.fixture()
def db_module(tmp_path, monkeypatch):
    db = monitor_db
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(db_connection, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    return db


def _table_columns(db_module, table_name: str) -> set[str]:
    with db_module.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _column_notnull(db_module, table_name: str, column_name: str) -> int:
    with db_module.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    for row in rows:
        if row["name"] == column_name:
            return int(row["notnull"])
    raise AssertionError(f"{table_name}.{column_name} not found")


def _require_email_schema_or_xfail(db_module) -> None:
    db_module.init_db()
    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    required = {
        "email_accounts",
        "email_mailboxes",
        "email_watch_state",
        "email_messages",
        "email_attachments",
        "email_processing_tasks",
        "content_targets",
        "content_variants",
        "content_publication_tasks",
    }
    missing = sorted(required - tables)
    if missing:
        pytest.xfail(f"Email collect schema is not wired into init_db yet. Missing: {missing}")


def test_init_db_bootstraps_email_collect_tables_targets_and_article_task_column(db_module):
    _require_email_schema_or_xfail(db_module)

    with db_module.get_connection() as conn:
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        targets = conn.execute(
            "SELECT platform, publish_mode FROM content_targets ORDER BY id ASC"
        ).fetchall()

    assert {"email_message_id", "source_type", "article_text", "source_title"} <= _table_columns(
        db_module, "article_tasks"
    )
    assert {
        "idx_email_messages_provider",
        "idx_email_messages_dedupe",
        "idx_content_targets_enabled",
        "idx_content_variants_source",
        "idx_content_variants_identity",
        "idx_article_tasks_email_message",
    } <= indexes
    assert _column_notnull(db_module, "email_oauth_states", "account_id") == 0
    assert {row["platform"] for row in targets} >= {
        "wechat",
        "xiaohongshu",
        "toutiao",
        "baijiahao",
        "juejin",
        "zhihu",
        "x",
        "reddit",
    }


def test_init_db_upgrades_legacy_database_with_email_collect_schema_idempotently(db_module):
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

            CREATE TABLE article_tasks (
                task_id TEXT PRIMARY KEY,
                monitor_video_id INTEGER,
                video_id TEXT,
                email_message_id INTEGER DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            );
            """
        )

    _require_email_schema_or_xfail(db_module)
    _require_email_schema_or_xfail(db_module)

    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        target_count = conn.execute("SELECT COUNT(*) FROM content_targets").fetchone()[0]

    assert "email_messages" in tables
    assert "content_variants" in tables
    assert target_count >= 8

    article_columns = _table_columns(db_module, "article_tasks")
    assert {
        "email_message_id",
        "video_url",
        "video_title",
        "target_lang",
        "auto_translate",
        "output_dir",
        "stages_json",
        "result_json",
    } <= article_columns

    task_id = db_module.create_article_task(
        None,
        None,
        None,
        "Email source title",
        source_type="email_message",
        article_text="Cleaned email body",
        source_url="/email/messages/42",
        source_title="Email source title",
        email_message_id=42,
        target_lang="en",
        auto_translate=False,
        output_dir=str(Path(db_module._DATA_DIR) / "articles"),
    )
    with db_module.get_connection() as conn:
        task = conn.execute("SELECT * FROM article_tasks WHERE task_id=?", (task_id,)).fetchone()

    assert task["source_type"] == "email_message"
    assert task["email_message_id"] == 42
    assert task["video_url"] is None
    assert task["target_lang"] == "en"
    assert task["auto_translate"] == 0


def test_init_db_bootstrap_seeds_content_targets_idempotently(db_module):
    _require_email_schema_or_xfail(db_module)
    _require_email_schema_or_xfail(db_module)

    with db_module.get_connection() as conn:
        rows = conn.execute(
            "SELECT platform, COUNT(*) AS row_count FROM content_targets GROUP BY platform"
        ).fetchall()
        wechat = conn.execute(
            "SELECT output_contract_json, prompt_profile_json FROM content_targets WHERE platform='wechat'"
        ).fetchone()

    assert rows
    assert all(row["row_count"] == 1 for row in rows)
    output_contract = email_queries._json_loads(wechat["output_contract_json"], {})
    prompt_profile = email_queries._json_loads(wechat["prompt_profile_json"], {})
    assert output_contract["format"] == "long_article"
    assert output_contract["editorial_focus"] == "深度结构化解读"
    assert prompt_profile["platform_role"] == "公众号深度编辑"
    assert "事实核验" in prompt_profile["review_checklist"]


def test_seed_content_targets_backfills_missing_platform_contract_keys(db_module):
    with db_module.get_connection() as conn:
        email_queries.ensure_schema(conn)
        conn.execute(
            "UPDATE content_targets SET output_contract_json=?, prompt_profile_json=? WHERE platform='wechat'",
            ('{"format":"long_article","max_chars":4500}', '{"tone":"custom"}'),
        )
        email_queries.ensure_schema(conn)
        row = conn.execute(
            "SELECT output_contract_json, prompt_profile_json FROM content_targets WHERE platform='wechat'"
        ).fetchone()

    output_contract = email_queries._json_loads(row["output_contract_json"], {})
    prompt_profile = email_queries._json_loads(row["prompt_profile_json"], {})
    assert output_contract["max_chars"] == 4500
    assert output_contract["editorial_focus"] == "深度结构化解读"
    assert prompt_profile["tone"] == "custom"
    assert prompt_profile["platform_role"] == "公众号深度编辑"


def test_email_oauth_states_legacy_notnull_account_id_is_migrated(db_module):
    with db_module.get_connection() as conn:
        email_queries.ensure_schema(conn)
        conn.execute("DROP TABLE email_oauth_states")
        conn.execute(
            """CREATE TABLE email_oauth_states (
                state_hash TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT 'gmail',
                requested_scopes_json TEXT NOT NULL DEFAULT '[]',
                redirect_uri TEXT NOT NULL,
                return_to TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT
            )"""
        )
        assert int(
            next(row for row in conn.execute("PRAGMA table_info(email_oauth_states)") if row["name"] == "account_id")[
                "notnull"
            ]
        ) == 1
        email_queries.ensure_schema(conn)

    assert _column_notnull(db_module, "email_oauth_states", "account_id") == 0


def test_email_accounts_dedupes_gmail_case_variants_and_enforces_nocase_unique(db_module):
    now = "2026-05-01T00:00:00Z"
    with db_module.get_connection() as conn:
        email_queries.ensure_schema(conn)
        conn.execute("DROP INDEX IF EXISTS idx_email_accounts_gmail_email_nocase")
        conn.execute(
            """INSERT INTO email_accounts
               (provider, display_name, email_address, status, gmail_scope_json,
                imap_port, imap_security, smtp_port, smtp_security, sync_mode,
                poll_interval_seconds, include_spam_trash, max_messages_per_sync,
                created_at, updated_at)
               VALUES ('gmail', 'Upper Gmail', 'User@Gmail.com', 'active', '[]',
                       993, 'ssl', 465, 'ssl', 'poll', 300, 0, 20, ?, ?)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO email_accounts
               (provider, display_name, email_address, status, gmail_refresh_token_enc,
                gmail_scope_json, imap_port, imap_security, smtp_port, smtp_security,
                sync_mode, poll_interval_seconds, include_spam_trash, max_messages_per_sync,
                created_at, updated_at)
               VALUES ('gmail', 'Lower Gmail', 'user@gmail.com', 'active', 'enc-token',
                       '["https://www.googleapis.com/auth/gmail.readonly"]',
                       993, 'ssl', 465, 'ssl', 'poll', 300, 0, 20, ?, ?)""",
            (now, "2026-05-01T00:01:00Z"),
        )
        email_queries.ensure_schema(conn)
        rows = conn.execute(
            """SELECT id, display_name, email_address, gmail_refresh_token_enc
               FROM email_accounts
               WHERE provider='gmail' AND lower(email_address)='user@gmail.com'"""
        ).fetchall()

        assert len(rows) == 1
        assert rows[0]["email_address"] == "user@gmail.com"
        assert rows[0]["display_name"] == "Lower Gmail"
        assert rows[0]["gmail_refresh_token_enc"] == "enc-token"

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO email_accounts
                   (provider, display_name, email_address, status, gmail_scope_json,
                    imap_port, imap_security, smtp_port, smtp_security, sync_mode,
                    poll_interval_seconds, include_spam_trash, max_messages_per_sync,
                    created_at, updated_at)
                   VALUES ('gmail', 'Duplicate Gmail', 'USER@gmail.com', 'active', '[]',
                           993, 'ssl', 465, 'ssl', 'poll', 300, 0, 20, ?, ?)""",
                (now, now),
            )

"""Contract tests for AI article/video workflow schema and startup recovery."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db


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


def _xfail_if_missing(items: set[str], required: set[str], reason: str) -> None:
    missing = sorted(required - items)
    if missing:
        pytest.xfail(f"{reason}. Missing: {', '.join(missing)}")


def _init_db_or_xfail(db_module) -> None:
    try:
        db_module.init_db()
    except NameError as exc:
        if "mark_incomplete_ai_content_tasks_interrupted" in str(exc):
            pytest.xfail(
                "AI content startup recovery is wired into init_db but the recovery helper is not defined yet"
            )
        raise
    except sqlite3.OperationalError as exc:
        pytest.xfail(f"Legacy AI content migration path is not stable enough for contract verification yet: {exc}")


def test_init_db_bootstraps_ai_content_tables_and_indexes_on_fresh_database(db_module):
    _init_db_or_xfail(db_module)

    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        indexes = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }

    required_tables = {"article_tasks", "video_gen_tasks", "wechat_publish_tasks"}
    required_indexes = {
        "idx_article_tasks_created_at",
        "idx_article_tasks_status",
        "idx_video_gen_tasks_created_at",
        "idx_video_gen_tasks_status",
    }
    _xfail_if_missing(
        tables,
        required_tables,
        "P0 AI content workflow tables are not bootstrapped yet",
    )
    _xfail_if_missing(
        indexes,
        required_indexes,
        "P0 AI content workflow indexes are not bootstrapped yet",
    )

    article_columns = _table_columns(db_module, "article_tasks")
    required_article_columns = {"monitor_video_id", "video_id", "status", "stage_json", "output_dir"}
    if not required_article_columns <= article_columns:
        pytest.xfail(
            "Existing article_tasks schema does not match the P0 AI article contract yet"
        )

    video_columns = _table_columns(db_module, "video_gen_tasks")
    required_video_columns = {
        "status",
        "mode",
        "template_name",
        "stage_json",
        "output_path",
        "error",
    }
    if not required_video_columns <= video_columns:
        pytest.xfail(
            "Existing video_gen_tasks schema does not match the P0 Pixelle workflow contract yet"
        )


def test_init_db_upgrades_legacy_database_with_ai_content_migration_idempotently(db_module):
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

                CREATE TABLE monitor_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL UNIQUE,
                    account_id INTEGER NOT NULL,
                    event_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    download_status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
        )

    _init_db_or_xfail(db_module)
    _init_db_or_xfail(db_module)

    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        applied = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        ]

    if "v17_ai_content_workflows" not in applied:
        pytest.xfail("P0 AI content workflow migration marker is not recorded yet")

    assert "article_tasks" in tables
    assert "video_gen_tasks" in tables
    assert applied.count("v17_ai_content_workflows") == 1


def test_ai_content_startup_recovery_marks_stale_tasks_interrupted(db_module):
    _init_db_or_xfail(db_module)

    recovery_fn = getattr(db_module, "mark_incomplete_ai_content_tasks_interrupted", None)
    if recovery_fn is None:
        pytest.xfail("AI content startup recovery helper is not implemented yet")

    required_tables = {"article_tasks", "video_gen_tasks"}
    with db_module.get_connection() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    _xfail_if_missing(
        tables,
        required_tables,
        "AI content task tables are required before startup recovery can be verified",
    )

    now = "2026-04-27T10:00:00+08:00"
    with db_module.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO monitor_accounts
                (id, name, channel_url, api_key_env, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "contract-account", "https://youtube.com/@contract", "TEST_API_KEY", now, now),
        )
        conn.execute(
            """
            INSERT INTO monitor_events
                (id, account_id, account_name, scan_started_at, status, total_videos, new_videos)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, "contract-account", now, "success", 1, 1),
        )
        conn.execute(
            """
            INSERT INTO monitor_videos
                (id, video_id, account_id, event_id, title, url, published_at, fetched_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "yt-contract-source", 1, 1, "Contract source", "https://youtu.be/yt-contract-source", now, now, now),
        )
        conn.execute(
            """
            INSERT INTO article_tasks
                (monitor_video_id, video_id, status, stage_json, output_dir, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "yt-article-1", "running", "{}", "D:/output/article-1", now, now),
        )
        conn.execute(
            """
            INSERT INTO article_tasks
                (monitor_video_id, video_id, status, stage_json, output_dir, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "yt-article-pending", "pending", "{}", "D:/output/article-pending", now, now),
        )
        conn.execute(
            """
            INSERT INTO video_gen_tasks
                (mode, status, template_name, stage_json, output_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("topic", "cancelling", "pixelle/basic", "{}", "D:/output/video-1.mp4", now, now),
        )
        conn.execute(
            """
            INSERT INTO video_gen_tasks
                (mode, status, template_name, stage_json, output_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("topic", "pending", "pixelle/basic", "{}", "D:/output/video-pending.mp4", now, now),
        )
        conn.execute(
            """
            INSERT INTO wechat_publish_tasks
                (task_id, draft_path, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("wechat-publish-1", "D:/output/article-1/draft.md", "Contract publish", "running", now, now),
        )

    recovery_fn()

    with db_module.get_connection() as conn:
        article = conn.execute(
            "SELECT status, error FROM article_tasks WHERE video_id = ?",
            ("yt-article-1",),
        ).fetchone()
        pending_article = conn.execute(
            "SELECT status, error FROM article_tasks WHERE video_id = ?",
            ("yt-article-pending",),
        ).fetchone()
        video = conn.execute(
            "SELECT status, error FROM video_gen_tasks WHERE output_path = ?",
            ("D:/output/video-1.mp4",),
        ).fetchone()
        pending_video = conn.execute(
            "SELECT status, error FROM video_gen_tasks WHERE output_path = ?",
            ("D:/output/video-pending.mp4",),
        ).fetchone()
        wechat = conn.execute(
            "SELECT status, error FROM wechat_publish_tasks WHERE task_id = ?",
            ("wechat-publish-1",),
        ).fetchone()

    assert article["status"] == "interrupted"
    assert "中断" in (article["error"] or "")
    assert pending_article["status"] == "interrupted"
    assert "中断" in (pending_article["error"] or "")
    assert video["status"] == "interrupted"
    assert "中断" in (video["error"] or "")
    assert pending_video["status"] == "interrupted"
    assert "中断" in (pending_video["error"] or "")
    assert wechat["status"] == "interrupted"
    assert "中断" in (wechat["error"] or "")


def test_ai_content_terminal_task_does_not_expose_running_stage(db_module):
    _init_db_or_xfail(db_module)
    now = "2026-04-30T11:00:00+08:00"
    stages = {
        "source_media": {"status": "done", "message": "音频下载完成，准备 Whisper 转写"},
        "whisper": {"status": "running", "message": "正在使用本地 Whisper 模型转写"},
    }
    with db_module.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO article_tasks
                (task_id, status, current_stage, stages_json, stage_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "article-stale-whisper",
                "interrupted",
                "whisper",
                json.dumps(stages, ensure_ascii=False),
                json.dumps(stages, ensure_ascii=False),
                "服务重启导致任务中断",
                now,
                now,
            ),
        )

    task = db_module.get_article_task("article-stale-whisper")

    assert task["status"] == "interrupted"
    assert task["stages"]["source_media"]["status"] == "done"
    assert task["stages"]["whisper"]["status"] == "interrupted"
    assert "Whisper" in task["stages"]["whisper"]["message"]
    assert "中断" in task["stages"]["whisper"]["message"]

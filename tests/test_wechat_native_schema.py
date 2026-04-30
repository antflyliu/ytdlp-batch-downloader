from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def _patch_monitor_db_paths(monkeypatch, db_path: Path, data_dir: Path, schema_path: Path) -> None:
    import monitor.db as db
    import monitor.db.connection as db_connection

    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def test_wechat_native_tables_exist_after_init(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"

    _patch_monitor_db_paths(monkeypatch, db_path, data_dir, schema_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    try:
        tables = _tables(conn)
        assert "wechat_collect_sessions" in tables
        assert "wechat_collect_accounts" in tables
        assert "wechat_collect_articles" in tables
        assert "wechat_collect_tasks" in tables
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "idx_wechat_collect_tasks_created_at" in indexes
        assert "idx_wechat_collect_articles_fakeid_update" in indexes
    finally:
        conn.close()


def test_wechat_collect_query_module_round_trips_session(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"

    _patch_monitor_db_paths(monkeypatch, db_path, data_dir, schema_path)
    db.init_db()

    queries = importlib.import_module("monitor.db.queries.wechat_collect")
    queries.upsert_session(
        session_id="sess-1",
        token_enc="enc-token",
        cookie_json_enc="enc-cookie",
        nickname="测试号",
        avatar="https://example.test/a.png",
        expires_at="2030-01-01T00:00:00+08:00",
        status="active",
    )

    session = queries.get_session("sess-1")
    assert session is not None
    assert session["session_id"] == "sess-1"
    assert session["nickname"] == "测试号"
    assert session["status"] == "active"

"""tests/test_monitor_retry_sql_injection.py — SQL injection protection for reset_videos_for_retry."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_sql_injection_blocked(tmp_path, monkeypatch):
    """
    SQL injection payload should be safely handled via parameterized queries.
    Normal records must be reset; injection attempts must not corrupt query.
    """
    import monitor.db as monitor_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(monitor_db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(monitor_db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(monitor_db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(monitor_db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))

    monitor_db.init_db()

    now = monitor_db.now_iso()
    with monitor_db.get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO monitor_accounts (id, name, channel_url, api_key_env, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, "Test", "@test", "KEY", now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO monitor_events (id, account_id, account_name, scan_started_at, status, total_videos, new_videos) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "Test", now, "done", 1, 1),
        )
        vid_normal = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid_normal", "Normal", "https://yt.be/normal", "failed", now, now, now, "pending", 1, 1),
        ).lastrowid
        vid_injection = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid_inj", "Injected", "https://yt.be/inj", "failed", now, now, now, "pending", 1, 1),
        ).lastrowid

    # Injection payload: close string then append DROP TABLE
    injection_ids = [vid_normal, vid_injection, 9999]  # 9999 does not exist
    try:
        monitor_db.reset_videos_for_retry(injection_ids, account_id=1)
    except Exception as exc:
        pytest.fail(f"SQL injection payload caused exception (parameterized query may have failed): {exc}")

    # Normal record should be reset
    with monitor_db.get_connection() as conn:
        status = conn.execute(
            "SELECT download_status FROM monitor_videos WHERE id=?", (vid_normal,),
        ).fetchone()[0]
    assert status == "pending", "Normal record should be reset to pending"

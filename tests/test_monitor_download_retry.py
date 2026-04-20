"""tests/test_monitor_download_retry.py — Test update_videos_download_status retry fields."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _setup_test_db(tmp_path, monkeypatch):
    """Create a fresh test DB with parent records for FK constraints."""
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

    return monitor_db, now


def test_update_retry_count_persists(tmp_path, monkeypatch):
    """update_videos_download_status should persist retry_count field."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid1", "Test", "https://yt.be/1", "pending", now, now, now, "pending", 1, 1),
        ).lastrowid

    monitor_db.update_videos_download_status([vid], retry_count=2)

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT retry_count FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()
    assert row[0] == 2


def test_update_failed_reason_and_at(tmp_path, monkeypatch):
    """update_videos_download_status should persist failed_reason and failed_at."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid2", "Test2", "https://yt.be/2", "pending", now, now, now, "pending", 1, 1),
        ).lastrowid

    monitor_db.update_videos_download_status(
        [vid],
        status="failed",
        download_error="429 rate limit",
        retry_count=0,
        failed_reason="batch_download_error",
        failed_at=now,
    )

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status, download_error, retry_count, failed_reason, failed_at FROM monitor_videos WHERE id=?",
            (vid,),
        ).fetchone()
    assert row[0] == "failed"
    assert row[1] == "429 rate limit"
    assert row[2] == 0
    assert row[3] == "batch_download_error"
    assert row[4] == now


def test_update_status_without_retry_fields(tmp_path, monkeypatch):
    """update_videos_download_status should work without retry fields (backward compat)."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid3", "Test3", "https://yt.be/3", "pending", now, now, now, "pending", 1, 1),
        ).lastrowid

    # Old-style call: status only
    monitor_db.update_videos_download_status([vid], "downloading")

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()
    assert row[0] == "downloading"


def test_get_videos_by_ids_includes_retry_fields(tmp_path, monkeypatch):
    """get_videos_by_ids should return retry_count, failed_reason, failed_at, account_id."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id, retry_count, failed_reason, failed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid4", "Test4", "https://yt.be/4", "failed", now, now, now, "pending", 1, 1, 3, "batch_download_error", now),
        ).lastrowid

    results = monitor_db.get_videos_by_ids([vid])
    assert len(results) == 1
    r = results[0]
    assert r["retry_count"] == 3
    assert r["failed_reason"] == "batch_download_error"
    assert r["failed_at"] == now
    assert r["account_id"] == 1  # account_id returned from DB (FK constraint requires account 1)


def test_reset_videos_for_retry(tmp_path, monkeypatch):
    """reset_videos_for_retry should reset failed videos to pending."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id, retry_count, failed_reason, failed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid5", "Test5", "https://yt.be/5", "failed", now, now, now, "pending", 1, 1, 3, "test", now),
        ).lastrowid

    monitor_db.reset_videos_for_retry([vid], account_id=1)

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status, retry_count, failed_reason, failed_at FROM monitor_videos WHERE id=?",
            (vid,),
        ).fetchone()
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None
    assert row[3] is None


def test_reset_videos_for_retry_non_failed_unchanged(tmp_path, monkeypatch):
    """reset_videos_for_retry should NOT change non-failed videos."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id, retry_count, failed_reason, failed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid6", "Test6", "https://yt.be/6", "downloaded", now, now, now, "pending", 1, 1, 0, None, None),
        ).lastrowid

    monitor_db.reset_videos_for_retry([vid], account_id=1)

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()
    assert row[0] == "downloaded"


def test_mark_stale_running_videos_interrupted(tmp_path, monkeypatch):
    """mark_stale_running_videos_interrupted should mark running as failed."""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid7", "Test7", "https://yt.be/7", "running", now, now, now, "pending", 1, 1),
        ).lastrowid

    monitor_db.mark_stale_running_videos_interrupted()

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status, failed_reason FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()
    assert row[0] == "failed"
    assert row[1] == "服务重启导致任务中断"

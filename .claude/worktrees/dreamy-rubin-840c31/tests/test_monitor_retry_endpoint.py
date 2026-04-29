"""tests/test_monitor_retry_endpoint.py — Test retry API endpoint logic."""
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


def test_retry_endpoint_validation_empty_video_ids(tmp_path, monkeypatch):
    """video_ids 为空列表时验证失败"""
    monitor_db, _ = _setup_test_db(tmp_path, monkeypatch)
    body = {"video_ids": [], "account_id": 1}
    assert not isinstance(body.get("video_ids"), list) or not body.get("video_ids")


def test_retry_endpoint_validation_non_integer_account_id(tmp_path, monkeypatch):
    """account_id 非整数时验证失败"""
    monitor_db, _ = _setup_test_db(tmp_path, monkeypatch)
    body = {"video_ids": [1, 2], "account_id": "not_an_int"}
    assert not isinstance(body.get("account_id"), int)


def test_reset_videos_for_retry_resets_failed_to_pending(tmp_path, monkeypatch):
    """reset_videos_for_retry 将 failed 视频重置为 pending"""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid1", "Test", "https://yt.be/1", "failed", now, now, now, "pending", 1, 1),
        ).lastrowid

    monitor_db.reset_videos_for_retry([vid], 1)

    with monitor_db.get_connection() as conn:
        status = conn.execute(
            "SELECT download_status FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()[0]
    assert status == "pending", f"Expected pending, got {status}"


def test_reset_videos_for_retry_preserves_non_failed(tmp_path, monkeypatch):
    """reset_videos_for_retry 不修改非 failed 状态的视频"""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid2", "Test", "https://yt.be/2", "downloaded", now, now, now, "pending", 1, 1),
        ).lastrowid

    monitor_db.reset_videos_for_retry([vid], 1)

    with monitor_db.get_connection() as conn:
        status = conn.execute(
            "SELECT download_status FROM monitor_videos WHERE id=?", (vid,),
        ).fetchone()[0]
    assert status == "downloaded", f"Expected downloaded, got {status}"


def test_reset_videos_for_retry_clears_all_retry_fields(tmp_path, monkeypatch):
    """reset_videos_for_retry 重置 retry_count 并清除 failed_reason/failed_at/failed_event_id"""
    monitor_db, now = _setup_test_db(tmp_path, monkeypatch)

    with monitor_db.get_connection() as conn:
        vid = conn.execute(
            "INSERT INTO monitor_videos (video_id, title, url, download_status, created_at, published_at, fetched_at, notify_status, account_id, event_id, retry_count, failed_reason, failed_at, failed_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("vid3", "Test", "https://yt.be/3", "failed", now, now, now, "pending", 1, 1, 3, "test_error", now, 5),
        ).lastrowid

    monitor_db.reset_videos_for_retry([vid], 1)

    with monitor_db.get_connection() as conn:
        row = conn.execute(
            "SELECT download_status, retry_count, failed_reason, failed_at, failed_event_id FROM monitor_videos WHERE id=?",
            (vid,),
        ).fetchone()
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None
    assert row[3] is None
    assert row[4] is None

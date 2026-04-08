"""tests/test_scheduler_cleanup.py — Step 3: stale candidate cleanup job"""
import sys
from pathlib import Path
from unittest import mock
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as _db


class FakeScheduler:
    def __init__(self):
        self.jobs = {}
        self.running = False

    def add_job(self, func, trigger=None, args=None, id=None, name=None, replace_existing=False):
        self.jobs[id] = {"func": func, "trigger": trigger, "args": args or [], "name": name}
        return id

    def get_jobs(self):
        return [type("Job", (), {"id": k, "name": (v or {}).get("name", ""), "next_run_time": None}) for k, v in self.jobs.items() if k is not None]

    def start(self):
        self.running = True


def test_cleanup_stale_candidates_removes_down_probes_older_than_7_days():
    """cleanup_stale_candidates() removes candidates that have been 'down' for more than 7 days."""
    import sqlite3
    import tempfile
    import os

    orig = _db.get_connection
    path = tempfile.mktemp(suffix=".db")

    def factory():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    _db.get_connection = factory
    _db.init_db()

    try:
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=8)).isoformat()
        recent_date = (now - timedelta(days=3)).isoformat()

        with _db.get_connection() as conn:
            # Provider 1
            conn.execute(
                "INSERT INTO dynamic_proxy_providers (name,billing_tier,adapter_type,refresh_interval_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("P1","free","list_api",0,now.isoformat(),now.isoformat())
            )
            # Candidate with down status > 7 days old → should be deleted
            conn.execute(
                """INSERT INTO dynamic_proxy_candidates
                   (candidate_key,provider_id,protocol,host,port,masked_proxy_endpoint,
                    last_probe_status,last_probe_at,last_seen_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("key_down_stale", 1, "http", "1.2.3.4", 8080, "http://***",
                 "down", old_date, old_date, now.isoformat(), now.isoformat())
            )
            # Candidate with down status but recent → should be kept
            conn.execute(
                """INSERT INTO dynamic_proxy_candidates
                   (candidate_key,provider_id,protocol,host,port,masked_proxy_endpoint,
                    last_probe_status,last_probe_at,last_seen_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("key_down_recent", 1, "http", "5.6.7.8", 8080, "http://***",
                 "down", recent_date, recent_date, now.isoformat(), now.isoformat())
            )
            # Candidate with healthy status → should be kept
            conn.execute(
                """INSERT INTO dynamic_proxy_candidates
                   (candidate_key,provider_id,protocol,host,port,masked_proxy_endpoint,
                    last_probe_status,last_probe_at,last_seen_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("key_healthy", 1, "http", "9.9.9.9", 8080, "http://***",
                 "healthy", recent_date, recent_date, now.isoformat(), now.isoformat())
            )

        deleted = _db.cleanup_stale_candidates(stale_days=7)

        assert deleted == 1, f"Expected 1 stale candidate removed, got {deleted}"

        with _db.get_connection() as conn:
            remaining = conn.execute(
                "SELECT candidate_key FROM dynamic_proxy_candidates ORDER BY candidate_key"
            ).fetchall()
            remaining_keys = [r[0] for r in remaining]

        assert "key_down_stale" not in remaining_keys, "Down + stale should be deleted"
        assert "key_down_recent" in remaining_keys, "Down + recent should be kept"
        assert "key_healthy" in remaining_keys, "Healthy should be kept"
    finally:
        _db.get_connection = orig
        try:
            os.unlink(path)
        except PermissionError:
            pass


def test_scheduler_start_registers_cleanup_job():
    """start() registers a daily cleanup job on startup."""
    import monitor.scheduler as _scheduler

    try:
        with mock.patch.object(_scheduler, "_db") as mock_db:
            with mock.patch.object(_scheduler, "apscheduler") as mock_aps:
                fake_scheduler = FakeScheduler()
                mock_aps.schedulers.background.BackgroundScheduler.return_value = fake_scheduler

                mock_db.list_accounts.return_value = []
                mock_db.list_dynamic_proxy_providers.return_value = []
                mock_db.get_config_path.return_value = ""

                with mock.patch.object(_db, "_ensure_schema_migrations"):
                    _scheduler.start()

            cleanup_job_ids = [jid for jid in fake_scheduler.jobs if jid and jid.startswith("cleanup_")]
            assert len(cleanup_job_ids) == 1, f"Expected 1 cleanup job, got {cleanup_job_ids}: {list(fake_scheduler.jobs.keys())}"
            assert "cleanup_stale_candidates" in cleanup_job_ids
    finally:
        _scheduler._scheduler = None


def test_cleanup_job_calls_cleanup_stale_candidates():
    """The registered cleanup job calls db.cleanup_stale_candidates() and db.delete_expired_candidates()."""
    import monitor.scheduler as _scheduler

    calls_expired = []
    calls_stale = []

    def fake_delete_expired():
        calls_expired.append(1)
        return 0

    def fake_cleanup_stale(stale_days=7):
        calls_stale.append(stale_days)
        return 0

    original_delete = _db.delete_expired_candidates
    original_cleanup = _db.cleanup_stale_candidates
    _db.delete_expired_candidates = fake_delete_expired
    _db.cleanup_stale_candidates = fake_cleanup_stale

    try:
        _scheduler._cleanup_stale_and_expired_candidates()

        assert len(calls_expired) == 1, f"Expected delete_expired_candidates called once, got {calls_expired}"
        assert len(calls_stale) == 1, f"Expected cleanup_stale_candidates called once, got {calls_stale}"
        assert calls_stale[0] == 7, f"Expected stale_days=7, got {calls_stale[0]}"
    finally:
        _db.delete_expired_candidates = original_delete
        _db.cleanup_stale_candidates = original_cleanup

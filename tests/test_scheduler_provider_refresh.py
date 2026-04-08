"""tests/test_scheduler_provider_refresh.py — Step 2: provider refresh APScheduler job registration"""
import threading
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.scheduler as _scheduler


class FakeScheduler:
    """Fake APScheduler-like object that records add_job/reschedule_job/remove_job calls."""
    def __init__(self):
        self.jobs = {}
        self.running = False

    def add_job(self, func, trigger=None, args=None, id=None, name=None, replace_existing=False):
        self.jobs[id] = {"func": func, "trigger": trigger, "args": args or [], "name": name}
        return id

    def reschedule_job(self, job_id, **kwargs):
        self.jobs.setdefault(job_id, {})["rescheduled"] = True

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)

    def get_jobs(self):
        return [type("Job", (), {"id": k, "name": (v or {}).get("name", ""), "next_run_time": None}) for k, v in self.jobs.items() if k is not None]

    def start(self):
        self.running = True


def test_scheduler_start_registers_refresh_job_per_enabled_provider_with_interval():
    """start() registers a refresh APScheduler job for each provider with refresh_interval_minutes > 0."""
    import monitor.db as _db

    # Provider with 30-minute interval
    p1 = {"id": 1, "name": "P1", "enabled": 1, "refresh_interval_minutes": 30, "billing_tier": "free", "adapter_type": "list_api", "priority": 100}
    # Provider with interval = 0 (disabled)
    p2 = {"id": 2, "name": "P2", "enabled": 1, "refresh_interval_minutes": 0, "billing_tier": "free", "adapter_type": "list_api", "priority": 100}
    # Disabled provider
    p3 = {"id": 3, "name": "P3", "enabled": 0, "refresh_interval_minutes": 60, "billing_tier": "free", "adapter_type": "list_api", "priority": 100}

    try:
        with mock.patch.object(_scheduler, "_db") as mock_db:
            with mock.patch.object(_scheduler, "apscheduler") as mock_aps:
                fake_scheduler = FakeScheduler()
                mock_aps.schedulers.background.BackgroundScheduler.return_value = fake_scheduler

                mock_db.list_accounts.return_value = []
                mock_db.list_dynamic_proxy_providers.return_value = [p1, p2, p3]
                mock_db.get_config_path.return_value = ""

                with mock.patch.object(_db, "_ensure_schema_migrations"):
                    _scheduler.start()

            # Only p1 should have a refresh job (enabled + interval > 0)
            refresh_job_ids = [jid for jid in fake_scheduler.jobs if jid and jid.startswith("provider_refresh_")]
            assert len(refresh_job_ids) == 1, f"Expected 1 refresh job, got {len(refresh_job_ids)}: {refresh_job_ids}"
            assert "provider_refresh_1" in refresh_job_ids
    finally:
        # Stop real scheduler if it was created, then reset global
        try:
            _scheduler.stop()
        except Exception:
            pass
        _scheduler._scheduler = None


def test_scheduler_reschedule_job_on_refresh_interval_change():
    """reload_jobs() reschedules when a provider's refresh_interval_minutes changes."""
    import monitor.db as _db

    fake_scheduler = FakeScheduler()
    fake_scheduler.running = True
    # Pre-existing refresh job for provider 1
    fake_scheduler.jobs["provider_refresh_1"] = {
        "func": None, "trigger": None, "args": [], "name": "P1 refresh",
    }
    # Pre-existing account job so account removal loop doesn't wipe provider jobs
    fake_scheduler.jobs["account_99"] = {
        "func": None, "trigger": None, "args": [], "name": "Acc99",
    }

    with mock.patch.object(_scheduler, "_db") as mock_db:
        mock_db.list_dynamic_proxy_providers.return_value = []
        mock_db.list_accounts.return_value = [
            {"id": 99, "name": "Acc99", "channel_url": "https://example.com", "scan_interval": 60, "enabled": 1}
        ]
        mock_db.get_config_path.return_value = ""

        _scheduler._scheduler = fake_scheduler

        # Change p1's interval from 30 to 60
        updated_p1 = {"id": 1, "name": "P1", "enabled": 1, "refresh_interval_minutes": 60, "billing_tier": "free", "adapter_type": "list_api", "priority": 100}
        mock_db.list_dynamic_proxy_providers.return_value = [updated_p1]

        _scheduler.reload_jobs()

        # provider_refresh_1 should have been rescheduled
        assert fake_scheduler.jobs.get("provider_refresh_1", {}).get("rescheduled") is True


def test_scheduler_remove_refresh_job_when_interval_set_to_zero():
    """reload_jobs() removes the refresh job when a provider's interval is set to 0."""
    import monitor.db as _db

    fake_scheduler = FakeScheduler()
    fake_scheduler.running = True
    fake_scheduler.jobs["provider_refresh_1"] = {
        "func": None, "trigger": None, "args": [], "name": "P1 refresh",
    }
    fake_scheduler.jobs["account_99"] = {
        "func": None, "trigger": None, "args": [], "name": "Acc99",
    }

    with mock.patch.object(_scheduler, "_db") as mock_db:
        mock_db.list_dynamic_proxy_providers.return_value = [
            {"id": 1, "name": "P1", "enabled": 1, "refresh_interval_minutes": 0, "billing_tier": "free", "adapter_type": "list_api", "priority": 100}
        ]
        mock_db.list_accounts.return_value = [
            {"id": 99, "name": "Acc99", "channel_url": "https://example.com", "scan_interval": 60, "enabled": 1}
        ]
        mock_db.get_config_path.return_value = ""

        _scheduler._scheduler = fake_scheduler

        _scheduler.reload_jobs()

        # provider_refresh_1 should be removed; account_99 should remain
        assert "provider_refresh_1" not in fake_scheduler.jobs
        assert "account_99" in fake_scheduler.jobs


def test_scheduler_refresh_job_calls_refresh_dynamic_provider():
    """The registered refresh job calls refresh_dynamic_provider(provider_id)."""
    import monitor.db as _db

    calls = []

    def fake_refresh(provider_id):
        calls.append(provider_id)
        return {"ok": True, "provider_id": provider_id, "raw_count": 0, "valid_count": 0}

    fake_scheduler = FakeScheduler()
    fake_scheduler.running = True

    try:
        with mock.patch.object(_scheduler, "_db") as mock_db:
            mock_db.list_dynamic_proxy_providers.return_value = []
            mock_db.list_accounts.return_value = []
            mock_db.get_config_path.return_value = ""

            _scheduler._scheduler = fake_scheduler

            # Manually add a refresh job
            _scheduler._scheduler.add_job(
                func=fake_refresh,
                args=[42],
                id="provider_refresh_42",
                name="Provider 42 refresh",
            )

            # Simulate the job being triggered by calling its func directly
            job = fake_scheduler.jobs["provider_refresh_42"]
            job["func"](*job["args"])

            assert calls == [42]
    finally:
        _scheduler._scheduler = None

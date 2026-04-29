"""tests/test_provider_scheduler_logs.py — provider scheduler run log behavior"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.provider_scheduler as provider_scheduler


def test_provider_scheduler_run_once_writes_refresh_logs():
    providers = [
        {"id": 2, "name": "geonode-proxylist", "enabled": 1, "adapter_type": "list_api", "refresh_interval_minutes": 1},
        {"id": 3, "name": "another-provider", "enabled": 1, "adapter_type": "public_feed", "refresh_interval_minutes": 5},
    ]
    results = {
        2: {"ok": True, "provider_id": 2, "raw_count": 50, "valid_count": 50},
        3: {"ok": True, "provider_id": 3, "raw_count": 20, "valid_count": 18},
    }

    with mock.patch.object(provider_scheduler, "_db") as mock_db:
        with mock.patch.object(provider_scheduler, "refresh_dynamic_provider", side_effect=lambda pid: results[pid]):
            mock_db.list_dynamic_proxy_providers.return_value = providers
            provider_scheduler.run_once()

    assert mock_db.add_provider_scheduler_run.call_count == 2
    first = mock_db.add_provider_scheduler_run.call_args_list[0].kwargs
    assert first["provider_id"] == 2
    assert first["provider_name"] == "geonode-proxylist"
    assert first["job_type"] == "refresh"
    assert first["status"] == "success"
    assert first["raw_count"] == 50
    assert first["valid_count"] == 50


def test_provider_scheduler_run_once_continues_after_provider_exception():
    providers = [
        {"id": 2, "name": "bad-provider", "enabled": 1, "adapter_type": "list_api", "refresh_interval_minutes": 1},
        {"id": 3, "name": "good-provider", "enabled": 1, "adapter_type": "public_feed", "refresh_interval_minutes": 5},
    ]

    def fake_refresh(pid):
        if pid == 2:
            raise RuntimeError("network exploded")
        return {"ok": True, "provider_id": 3, "raw_count": 20, "valid_count": 18}

    with mock.patch.object(provider_scheduler, "_db") as mock_db:
        with mock.patch.object(provider_scheduler, "refresh_dynamic_provider", side_effect=fake_refresh):
            mock_db.list_dynamic_proxy_providers.return_value = providers
            result = provider_scheduler.run_once()

    assert result["provider_count"] == 2
    assert len(result["results"]) == 2
    assert result["results"][0]["ok"] is False
    assert result["results"][0]["provider_id"] == 2
    assert result["results"][0]["error"] == "network exploded"
    assert result["results"][1]["ok"] is True
    assert mock_db.add_provider_scheduler_run.call_count == 2
    first = mock_db.add_provider_scheduler_run.call_args_list[0].kwargs
    second = mock_db.add_provider_scheduler_run.call_args_list[1].kwargs
    assert first["provider_id"] == 2
    assert first["status"] == "error"
    assert first["message"] == "network exploded"
    assert second["provider_id"] == 3
    assert second["status"] == "success"


def test_provider_scheduler_scheduled_refresh_writes_refresh_log():
    prov = {"id": 7, "name": "geonode-proxylist"}
    result = {"ok": True, "provider_id": 7, "raw_count": 3, "valid_count": 2}

    with mock.patch.object(provider_scheduler, "_db") as mock_db:
        with mock.patch.object(
            provider_scheduler, "refresh_dynamic_provider", return_value=result
        ):
            mock_db.get_dynamic_proxy_provider.return_value = prov
            provider_scheduler._run_scheduled_refresh(7)

    mock_db.add_provider_scheduler_run.assert_called_once()
    call = mock_db.add_provider_scheduler_run.call_args.kwargs
    assert call["provider_id"] == 7
    assert call["provider_name"] == "geonode-proxylist"
    assert call["job_type"] == "refresh"
    assert call["status"] == "success"
    assert call["raw_count"] == 3
    assert call["valid_count"] == 2


def test_provider_scheduler_scheduled_refresh_records_error_on_exception():
    prov = {"id": 8, "name": "bad"}

    with mock.patch.object(provider_scheduler, "_db") as mock_db:
        with mock.patch.object(
            provider_scheduler,
            "refresh_dynamic_provider",
            side_effect=RuntimeError("boom"),
        ):
            mock_db.get_dynamic_proxy_provider.return_value = prov
            try:
                provider_scheduler._run_scheduled_refresh(8)
            except RuntimeError:
                pass

    mock_db.add_provider_scheduler_run.assert_called_once()
    call = mock_db.add_provider_scheduler_run.call_args.kwargs
    assert call["status"] == "error"
    assert call["message"] == "boom"


def test_provider_scheduler_cleanup_job_writes_cleanup_log():
    with mock.patch.object(provider_scheduler, "_db") as mock_db:
        with mock.patch.object(provider_scheduler, "_cleanup_stale_and_expired_candidates") as mock_cleanup:
            mock_cleanup.return_value = None
            provider_scheduler._run_cleanup_job()

    mock_db.add_provider_scheduler_run.assert_called_once()
    call = mock_db.add_provider_scheduler_run.call_args.kwargs
    assert call["provider_id"] is None
    assert call["job_type"] == "cleanup"
    assert call["status"] == "success"

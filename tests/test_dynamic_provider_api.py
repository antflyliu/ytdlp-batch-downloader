"""tests/test_dynamic_provider_api.py — Dynamic provider API regression tests"""
import json
import sys
import threading
import unittest
from datetime import datetime, timedelta
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor.db as monitor_db
import monitor_server
import server.__main__ as _server_main  # noqa: E402


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TestDynamicProviderApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        monitor_server.MonitorHandler._api_token = "test-token"
        cls.server = _ThreadedHTTPServer(("127.0.0.1", 0), monitor_server.MonitorHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        if hasattr(monitor_server.MonitorHandler, "_api_token"):
            delattr(monitor_server.MonitorHandler, "_api_token")

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        body_bytes = resp.read()
        conn.close()
        return resp.status, body_bytes, dict(resp.getheaders())



    def test_provider_scheduler_logs_endpoint(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.list_provider_scheduler_runs.return_value = [
                {
                    "id": 1,
                    "provider_id": 2,
                    "provider_name": "geonode-proxylist",
                    "job_type": "refresh",
                    "status": "success",
                    "raw_count": 50,
                    "valid_count": 50,
                    "message": "ok",
                    "started_at": "2026-04-08T17:00:00+08:00",
                    "finished_at": "2026-04-08T17:00:02+08:00",
                    "duration_ms": 2000,
                }
            ]
            status, resp_body, _ = self._request(
                "GET",
                "/api/provider-scheduler/logs",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["provider_name"], "geonode-proxylist")
        self.assertEqual(data[0]["job_type"], "refresh")
        self.assertEqual(data[0]["raw_count"], 50)


    def test_provider_scheduler_status_endpoint(self):
        with mock.patch.object(_server_main, "_provider_scheduler") as mock_provider_scheduler:
            mock_provider_scheduler.is_running.return_value = True
            mock_provider_scheduler.get_next_run_times.return_value = [{"id": "provider_refresh_2", "name": "ProviderRefresh geonode", "next_run": "2026-04-08 17:00:00"}]
            status, resp_body, headers = self._request(
                "GET",
                "/api/provider-scheduler/status",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertTrue(data["running"])
        self.assertEqual(len(data["next_runs"]), 1)


    def test_provider_scheduler_start_endpoint(self):
        with mock.patch.object(_server_main, "_provider_scheduler") as mock_provider_scheduler:
            mock_provider_scheduler.start.return_value = True
            status, resp_body, _ = self._request(
                "POST",
                "/api/provider-scheduler/start",
                body=b"{}",
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertTrue(data["ok"])
        mock_provider_scheduler.start.assert_called_once_with()


    def test_provider_scheduler_stop_endpoint(self):
        with mock.patch.object(_server_main, "_provider_scheduler") as mock_provider_scheduler:
            mock_provider_scheduler.stop.return_value = True
            status, resp_body, _ = self._request(
                "POST",
                "/api/provider-scheduler/stop",
                body=b"{}",
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertTrue(data["ok"])
        mock_provider_scheduler.stop.assert_called_once_with()

    def test_provider_scheduler_run_once_endpoint(self):
        with mock.patch.object(_server_main, "_provider_scheduler") as mock_provider_scheduler:
            mock_provider_scheduler.run_once.return_value = {
                "ok": True,
                "provider_count": 2,
                "results": [
                    {"provider_id": 2, "raw_count": 50, "valid_count": 50},
                    {"provider_id": 3, "raw_count": 20, "valid_count": 18},
                ],
            }
            status, resp_body, _ = self._request(
                "POST",
                "/api/provider-scheduler/run-once",
                body=b"{}",
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(data["provider_count"], 2)
        self.assertEqual(len(data["results"]), 2)

    def test_dynamic_provider_list_expired_cooldown_reports_false(self):
        past = (datetime.now() - timedelta(minutes=10)).isoformat()
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.list_dynamic_proxy_providers.return_value = [{
                "id": 1,
                "name": "Expired Cooldown",
                "enabled": 1,
                "billing_tier": "paid",
                "adapter_type": "local_gateway",
                "priority": 10,
                "supports_cookies": 1,
                "supports_auto_download": 1,
                "supports_country_filter": 0,
                "supports_sticky_session": 0,
                "risk_level": "low",
                "notes": "",
                "config_json": {"local_proxy_url": "http://127.0.0.1:7890"},
                "last_health_status": "healthy",
                "last_health_checked_at": "",
                "last_error_message": "",
                "cooldown_until": past,
                "created_at": "",
                "updated_at": "",
            }]
            mock_db.mask_proxy_url.return_value = "http://***:****@***:****"

            status, body, _ = self._request(
                "GET",
                "/api/dynamic-providers",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertFalse(data[0]["is_in_cooldown"])

    def test_routing_preview_returns_route_without_triggering_download(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            with mock.patch("monitor.dynamic_provider_resolver.resolve_for_manual_download") as mock_resolve:
                mock_db.get_account.return_value = {"id": 7, "name": "Account-7", "download_proxy_mode": "auto"}
                mock_resolve.return_value = mock.Mock(
                    resolved_mode="system_paid",
                    resolved_proxy_source="system_paid",
                    provider_name="Webshare Gateway",
                    provider_tier="paid",
                    masked_proxy_endpoint="http://***:****@***:****",
                    session_mode="sticky",
                    fallback_depth=1,
                    reason="命中系统付费动态代理",
                    warnings=["ok"],
                )

                status, body, headers = self._request(
                    "GET",
                    "/api/routing-preview?account_id=7&auto=0&cookies=1&direct=0",
                    headers={"Authorization": "Bearer test-token"},
                )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["account_id"], 7)
        self.assertEqual(data["routing"]["resolved_proxy_source"], "system_paid")
        self.assertEqual(data["routing"]["provider_name"], "Webshare Gateway")

    def test_routing_preview_requires_account_id(self):
        """Missing account_id returns 400."""
        status, body, _ = self._request(
            "GET",
            "/api/routing-preview",
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_routing_preview_account_not_found(self):
        """Invalid account_id returns 404."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_account.return_value = None
            status, body, _ = self._request(
                "GET",
                "/api/routing-preview?account_id=9999",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(status, 404)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_routing_preview_user_forced_direct(self):
        """direct=1 forces direct mode regardless of account settings."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_account.return_value = {"id": 7, "name": "Account-7", "download_proxy_mode": "auto"}
            status, body, headers = self._request(
                "GET",
                "/api/routing-preview?account_id=7&direct=1",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["routing"]["resolved_proxy_source"], "direct")
        self.assertEqual(data["routing"]["reason"], "用户显式指定直连")

    def test_routing_preview_auto_download_mode(self):
        """auto=1 resolves for auto download context."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            with mock.patch("monitor.dynamic_provider_resolver.resolve_for_auto_download") as mock_resolve:
                mock_db.get_account.return_value = {"id": 7, "name": "Account-7", "download_proxy_mode": "auto"}
                mock_resolve.return_value = mock.Mock(
                    resolved_mode="system_paid", resolved_proxy_source="system_paid",
                    provider_name="Paid Proxy", provider_tier="paid",
                    masked_proxy_endpoint=None, session_mode="sticky",
                    fallback_depth=1, reason="ok", warnings=[],
                )
                status, body, _ = self._request(
                    "GET",
                    "/api/routing-preview?account_id=7&auto=1",
                    headers={"Authorization": "Bearer test-token"},
                )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["is_auto_download"])

    def test_dynamic_provider_add_success(self):
        """POST /api/dynamic-providers creates a new provider."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.add_dynamic_proxy_provider.return_value = 42
            body = json.dumps({
                "name": "New Provider",
                "billing_tier": "paid",
                "adapter_type": "rotating_gateway",
                "config_json": {"gateway_host": "gw.example.com", "gateway_port": 8080},
            }).encode("utf-8")
            status, resp_body, _ = self._request(
                "POST",
                "/api/dynamic-providers",
                body=body,
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(data["id"], 42)
        mock_db.add_dynamic_proxy_provider.assert_called_once()

    def test_dynamic_provider_add_requires_name(self):
        """POST /api/dynamic-providers with empty name returns 400."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            body = json.dumps({"name": ""}).encode("utf-8")
            status, resp_body, _ = self._request(
                "POST",
                "/api/dynamic-providers",
                body=body,
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 400)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertIn("error", data)

    def test_dynamic_provider_update_success(self):
        """POST /api/dynamic-providers/{id}/update updates provider fields."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {"id": 5, "name": "Old Name"}
            body = json.dumps({"name": "Updated Name", "enabled": True}).encode("utf-8")
            status, resp_body, _ = self._request(
                "POST",
                "/api/dynamic-providers/5/update",
                body=body,
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        mock_db.update_dynamic_proxy_provider.assert_called_once()

    def test_dynamic_provider_update_not_found(self):
        """POST /api/dynamic-providers/{id}/update with unknown id returns 404."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = None
            body = json.dumps({"name": "Whatever"}).encode("utf-8")
            status, resp_body, _ = self._request(
                "POST",
                "/api/dynamic-providers/9999/update",
                body=body,
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 404)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertIn("error", data)

    def test_dynamic_provider_delete_success(self):
        """DELETE /api/dynamic-providers/{id} deletes provider."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {"id": 3, "name": "ToDelete"}
            status, resp_body, _ = self._request(
                "DELETE",
                "/api/dynamic-providers/3",
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(status, 200)
        mock_db.delete_dynamic_proxy_provider.assert_called_once_with(3)

    def test_dynamic_provider_cooldown_clear(self):
        """POST /api/dynamic-providers/{id}/cooldown/clear clears cooldown."""
        with mock.patch.object(_server_main, "_db") as mock_db:
            status, resp_body, _ = self._request(
                "POST",
                "/api/dynamic-providers/7/cooldown/clear",
                body=b"{}",
                headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        mock_db.update_dynamic_proxy_provider.assert_called_once()
        call_kwargs = mock_db.update_dynamic_proxy_provider.call_args[1]
        self.assertIsNone(call_kwargs["cooldown_until"])
        self.assertEqual(call_kwargs["last_health_status"], "healthy")


    def test_dynamic_provider_add_reload_jobs_when_scheduler_running(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.add_dynamic_proxy_provider.return_value = 42
            with mock.patch.object(_server_main._scheduler, "is_running", return_value=True):
                with mock.patch.object(_server_main._scheduler, "reload_jobs") as mock_reload:
                    body = json.dumps({
                        "name": "New Provider",
                        "billing_tier": "paid",
                        "adapter_type": "rotating_gateway",
                        "config_json": {"gateway_host": "gw.example.com", "gateway_port": 8080},
                    }).encode("utf-8")
                    status, _, _ = self._request(
                        "POST",
                        "/api/dynamic-providers",
                        body=body,
                        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
                    )
        self.assertEqual(status, 200)
        mock_reload.assert_called_once()

    def test_dynamic_provider_update_reload_jobs_when_scheduler_running(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {"id": 5, "name": "Old Name"}
            with mock.patch.object(_server_main._scheduler, "is_running", return_value=True):
                with mock.patch.object(_server_main._scheduler, "reload_jobs") as mock_reload:
                    body = json.dumps({"name": "Updated Name", "enabled": True}).encode("utf-8")
                    status, _, _ = self._request(
                        "POST",
                        "/api/dynamic-providers/5/update",
                        body=body,
                        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
                    )
        self.assertEqual(status, 200)
        mock_reload.assert_called_once()

    def test_dynamic_provider_delete_reload_jobs_when_scheduler_running(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {"id": 3, "name": "ToDelete"}
            with mock.patch.object(_server_main._scheduler, "is_running", return_value=True):
                with mock.patch.object(_server_main._scheduler, "reload_jobs") as mock_reload:
                    status, _, _ = self._request(
                        "DELETE",
                        "/api/dynamic-providers/3",
                        headers={"Authorization": "Bearer test-token"},
                    )
        self.assertEqual(status, 200)
        mock_reload.assert_called_once()

    def test_dynamic_provider_manual_refresh_endpoint_returns_preview_aligned_summary(self):
        with mock.patch.object(_server_main, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {"id": 5, "name": "Refresh Provider"}
            with mock.patch.object(_server_main._scheduler, "refresh_dynamic_provider", return_value={
                "ok": True,
                "provider_id": 5,
                "raw_count": 12,
                "valid_count": 7,
                "status_counts": {"healthy": 5, "down": 2},
                "latency_summary": {"count": 5, "min_ms": 90, "max_ms": 240},
                "score_summary": {"count": 7, "min_score": 2.0, "max_score": 18.0},
                "top_candidate": {
                    "masked_proxy_endpoint": "http://***:****@8.8.8.8:8080",
                    "last_probe_status": "healthy",
                    "latency_ms": 90,
                    "score": 18.0,
                },
            }) as mock_refresh:
                status, resp_body, _ = self._request(
                    "POST",
                    "/api/dynamic-providers/5/refresh",
                    body=b"{}",
                    headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
                )

        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(data["provider_id"], 5)
        self.assertEqual(data["valid_count"], 7)
        self.assertEqual(data["status_counts"], {"healthy": 5, "down": 2})
        self.assertEqual(data["latency_summary"], {"count": 5, "min_ms": 90, "max_ms": 240})
        self.assertEqual(data["score_summary"], {"count": 7, "min_score": 2.0, "max_score": 18.0})
        self.assertEqual(data["top_candidate"]["score"], 18.0)
        mock_refresh.assert_called_once_with(5)

    def test_scheduler_refresh_dynamic_provider_singleflights_concurrent_calls(self):
        provider = {
            "id": 5,
            "name": "Refresh Provider",
            "adapter_type": "list_api",
            "config_json": {
                "response": {
                    "items_path": "data",
                    "field_mapping": {
                        "host": ["ip"],
                        "port": ["port"],
                        "protocol": ["protocol"],
                    },
                },
            },
        }
        with mock.patch.object(_server_main._scheduler, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = provider
            entered = threading.Event()
            release = threading.Event()
            call_counter = {"count": 0}

            def fake_fetch(provider_arg, scenario_arg):
                call_counter["count"] += 1
                entered.set()
                release.wait(timeout=1)
                return [mock.Mock(host="8.8.8.8", port=8080, protocol="http", score=0.0)]

            with mock.patch("monitor.provider_templates.fetch_provider_candidates", side_effect=fake_fetch):
                with mock.patch.object(mock_db, "add_proxy_candidate", return_value=101) as mock_add:
                    results: list[dict] = []

                    def _run_refresh():
                        results.append(_server_main._scheduler.refresh_dynamic_provider(5))

                    t1 = threading.Thread(target=_run_refresh)
                    t1.start()
                    entered.wait(timeout=1)

                    t2 = threading.Thread(target=_run_refresh)
                    t2.start()

                    release.set()
                    t1.join(timeout=2)
                    t2.join(timeout=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(call_counter["count"], 1)
        self.assertEqual(mock_add.call_count, 1)
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_scheduler_refresh_dynamic_provider_returns_preview_aligned_summary(self):
        provider = {
            "id": 7,
            "name": "Summary Provider",
            "adapter_type": "list_api",
            "config_json": {
                "response": {
                    "items_path": "data",
                    "field_mapping": {
                        "host": ["ip"],
                        "port": ["port"],
                        "protocol": ["protocol"],
                    },
                },
            },
        }
        candidate_a = mock.Mock(
            host="8.8.8.8", port=8080, protocol="http", username=None, auth_type="none",
            country_code=None, region=None, city=None, anonymity=None, risk_level="medium",
            supports_https=True, supports_cookies=False, supports_auto_download=True,
            supports_sticky_session=False, score=12.5, provider_reference_id=None, ttl_expires_at=None,
            masked_proxy_endpoint="http://***:****@8.8.8.8:8080",
        )
        candidate_b = mock.Mock(
            host="9.9.9.9", port=8081, protocol="http", username=None, auth_type="none",
            country_code=None, region=None, city=None, anonymity=None, risk_level="medium",
            supports_https=True, supports_cookies=False, supports_auto_download=True,
            supports_sticky_session=False, score=3.0, provider_reference_id=None, ttl_expires_at=None,
            masked_proxy_endpoint="http://9.9.9.9:8081",
        )
        probe_results = [
            mock.Mock(status="healthy", latency_ms=120, error_message=None),
            mock.Mock(status="down", latency_ms=None, error_message="connect failed"),
        ]
        with mock.patch.object(_server_main._scheduler, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = provider
            with mock.patch("monitor.provider_templates.fetch_provider_candidates", return_value=[candidate_a, candidate_b]):
                with mock.patch("monitor.proxy_validator.CandidateProbeValidator") as mock_validator_cls:
                    mock_validator = mock_validator_cls.return_value

                    async def fake_probe(candidate_arg, timeout=8):
                        return probe_results.pop(0)

                    mock_validator.probe_lightweight.side_effect = fake_probe
                    with mock.patch.object(mock_db, "add_proxy_candidate", return_value=101):
                        result = _server_main._scheduler.refresh_dynamic_provider(7)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_counts"], {"healthy": 1, "down": 1})
        self.assertEqual(result["latency_summary"], {"count": 1, "min_ms": 120, "max_ms": 120})
        self.assertEqual(result["score_summary"], {"count": 2, "min_score": 3.0, "max_score": 12.5})
        self.assertEqual(result["top_candidate"], {
            "masked_proxy_endpoint": "http://***:****@8.8.8.8:8080",
            "last_probe_status": "healthy",
            "latency_ms": 120,
            "score": 12.5,
        })

    def test_scheduler_refresh_top_candidate_skips_down_picks_fastest_healthy(self):
        """首个候选为 down 时，当前最优应为后续 healthy 中延迟最低者。"""
        provider = {
            "id": 8,
            "name": "Order Provider",
            "adapter_type": "list_api",
            "config_json": {
                "response": {
                    "items_path": "data",
                    "field_mapping": {
                        "host": ["ip"],
                        "port": ["port"],
                        "protocol": ["protocol"],
                    },
                },
            },
        }
        candidate_down = mock.Mock(
            host="1.1.1.1", port=80, protocol="http", username=None, auth_type="none",
            country_code=None, region=None, city=None, anonymity=None, risk_level="medium",
            supports_https=True, supports_cookies=False, supports_auto_download=True,
            supports_sticky_session=False, score=99.0, provider_reference_id=None, ttl_expires_at=None,
            masked_proxy_endpoint="http://1.1.1.1:80",
        )
        candidate_slow = mock.Mock(
            host="8.8.8.8", port=8080, protocol="http", username=None, auth_type="none",
            country_code=None, region=None, city=None, anonymity=None, risk_level="medium",
            supports_https=True, supports_cookies=False, supports_auto_download=True,
            supports_sticky_session=False, score=10.0, provider_reference_id=None, ttl_expires_at=None,
            masked_proxy_endpoint="http://8.8.8.8:8080",
        )
        candidate_fast = mock.Mock(
            host="9.9.9.9", port=8081, protocol="http", username=None, auth_type="none",
            country_code=None, region=None, city=None, anonymity=None, risk_level="medium",
            supports_https=True, supports_cookies=False, supports_auto_download=True,
            supports_sticky_session=False, score=1.0, provider_reference_id=None, ttl_expires_at=None,
            masked_proxy_endpoint="http://9.9.9.9:8081",
        )
        probe_results = [
            mock.Mock(status="down", latency_ms=None, error_message="x"),
            mock.Mock(status="healthy", latency_ms=500, error_message=None),
            mock.Mock(status="healthy", latency_ms=80, error_message=None),
        ]
        with mock.patch.object(_server_main._scheduler, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = provider
            with mock.patch(
                "monitor.provider_templates.fetch_provider_candidates",
                return_value=[candidate_down, candidate_slow, candidate_fast],
            ):
                with mock.patch("monitor.proxy_validator.CandidateProbeValidator") as mock_validator_cls:
                    mock_validator = mock_validator_cls.return_value

                    async def fake_probe(candidate_arg, timeout=8):
                        return probe_results.pop(0)

                    mock_validator.probe_lightweight.side_effect = fake_probe
                    with mock.patch.object(mock_db, "add_proxy_candidate", return_value=101):
                        result = _server_main._scheduler.refresh_dynamic_provider(8)

        self.assertTrue(result["ok"])
        self.assertEqual(result["top_candidate"]["masked_proxy_endpoint"], "http://9.9.9.9:8081")
        self.assertEqual(result["top_candidate"]["last_probe_status"], "healthy")
        self.assertEqual(result["top_candidate"]["latency_ms"], 80)

    def test_pick_healthy_fastest_top_candidate_prefers_lowest_latency(self):
        rows = [
            {
                "last_probe_status": "down",
                "latency_ms": 10,
                "masked_proxy_endpoint": "socks4://bad:1",
                "score": 100.0,
            },
            {
                "last_probe_status": "healthy",
                "latency_ms": 200,
                "masked_proxy_endpoint": "http://slow:2",
                "score": 5.0,
            },
            {
                "last_probe_status": "healthy",
                "latency_ms": 50,
                "masked_proxy_endpoint": "http://fast:3",
                "score": 1.0,
            },
        ]
        top = monitor_db.pick_healthy_fastest_top_candidate(rows)
        self.assertIsNotNone(top)
        self.assertEqual(top["masked_proxy_endpoint"], "http://fast:3")
        self.assertEqual(top["latency_ms"], 50)
        self.assertEqual(top["last_probe_status"], "healthy")

    def test_pick_healthy_fastest_top_candidate_same_latency_prefers_higher_score(self):
        rows = [
            {
                "last_probe_status": "healthy",
                "latency_ms": 100,
                "masked_proxy_endpoint": "http://a",
                "score": 1.0,
            },
            {
                "last_probe_status": "healthy",
                "latency_ms": 100,
                "masked_proxy_endpoint": "http://b",
                "score": 9.0,
            },
        ]
        top = monitor_db.pick_healthy_fastest_top_candidate(rows)
        self.assertEqual(top["masked_proxy_endpoint"], "http://b")
        self.assertEqual(top["score"], 9.0)

    def test_pick_healthy_fastest_top_candidate_none_when_all_down(self):
        rows = [
            {"last_probe_status": "down", "latency_ms": 10, "masked_proxy_endpoint": "x", "score": 1},
        ]
        self.assertIsNone(monitor_db.pick_healthy_fastest_top_candidate(rows))


if __name__ == "__main__":
    unittest.main()

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

import monitor_server


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

    def test_dynamic_provider_list_returns_metadata_fields(self):
        future = (datetime.now() + timedelta(minutes=10)).isoformat()
        with mock.patch.object(monitor_server, "_db") as mock_db:
            mock_db.list_dynamic_proxy_providers.return_value = [{
                "id": 1,
                "name": "Webshare Gateway",
                "enabled": 1,
                "billing_tier": "paid",
                "adapter_type": "rotating_gateway",
                "priority": 10,
                "supports_cookies": 1,
                "supports_auto_download": 1,
                "supports_country_filter": 1,
                "supports_sticky_session": 1,
                "risk_level": "low",
                "notes": "primary",
                "config_json": {
                    "protocol": "http",
                    "gateway_host": "gw.example.com",
                    "gateway_port": 8080,
                    "username": "user1",
                    "password": "secret-pass",
                },
                "last_health_status": "healthy",
                "last_health_checked_at": "2026-04-07T12:00:00+08:00",
                "last_error_message": "",
                "cooldown_until": future,
                "created_at": "2026-04-07T12:00:00+08:00",
                "updated_at": "2026-04-07T12:00:00+08:00",
            }]
            mock_db.mask_proxy_url.return_value = "http://***:****@***:****"

            status, body, headers = self._request(
                "GET",
                "/api/dynamic-providers",
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(len(data), 1)
        row = data[0]
        self.assertIn("masked_preview", row)
        self.assertIn("status_text", row)
        self.assertIn("capabilities", row)
        self.assertIn("config_json", row)
        self.assertTrue(row["is_in_cooldown"])
        self.assertEqual(row["masked_preview"], "http://***:****@***:****")
        self.assertIn("Cookie", " ".join(row["capabilities"]))

    def test_dynamic_provider_list_expired_cooldown_reports_false(self):
        past = (datetime.now() - timedelta(minutes=10)).isoformat()
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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
        with mock.patch.object(monitor_server, "_db") as mock_db:
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

    def test_health_check_local_gateway_success_updates_status(self):
        from monitor.provider_health import ProbeResult
        provider = {
            "id": 1,
            "name": "Local Gateway",
            "adapter_type": "local_gateway",
            "config_json": {"local_proxy_url": "http://127.0.0.1:7890", "healthcheck_url": "http://127.0.0.1:7890/health"},
        }
        with mock.patch.object(monitor_server, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = provider
            mock_db.load_config.return_value = {"provider_cooldown_seconds": 600}
            body = b"{}"
            with mock.patch("monitor.provider_health.check_provider_health", return_value=ProbeResult(
                status="healthy", latency_ms=120, error_message=None, response_code=200,
            )):
                status, resp_body, _ = self._request(
                    "POST",
                    "/api/dynamic-providers/1/health-check",
                    body=body,
                    headers={
                        "Authorization": "Bearer test-token",
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                    },
                )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(data["status"], "healthy")
        mock_db.update_dynamic_proxy_provider.assert_called()

    def test_health_check_local_gateway_failure_sets_down(self):
        from monitor.provider_health import ProbeResult
        provider = {
            "id": 1,
            "name": "Local Gateway",
            "adapter_type": "local_gateway",
            "config_json": {"local_proxy_url": "http://127.0.0.1:7890", "healthcheck_url": "http://127.0.0.1:7890/health"},
        }
        with mock.patch.object(monitor_server, "_db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = provider
            mock_db.load_config.return_value = {"provider_cooldown_seconds": 600}
            body = b"{}"
            with mock.patch("monitor.provider_health.check_provider_health", return_value=ProbeResult(
                status="down", latency_ms=-1, error_message="connection refused", response_code=None,
            )):
                status, resp_body, _ = self._request(
                    "POST",
                    "/api/dynamic-providers/1/health-check",
                    body=body,
                    headers={
                        "Authorization": "Bearer test-token",
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                    },
                )
        self.assertEqual(status, 200)
        data = json.loads(resp_body.decode("utf-8"))
        self.assertEqual(data["status"], "down")
        self.assertIn("cooldown_until", data)
        mock_db.update_dynamic_proxy_provider.assert_called()


if __name__ == "__main__":
    unittest.main()

"""tests/test_provider_health.py — Dynamic provider health-check unit tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class TestProviderHealthCore(unittest.TestCase):
    """Test the core health check logic via provider_health module."""

    def test_disabled_provider_returns_not_started(self):
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "Disabled Provider",
                "enabled": False,
                "adapter_type": "rotating_gateway",
                "config_json": {},
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "not_started")
        self.assertEqual(result.error_message, "提供方已禁用")

    def test_missing_provider_returns_down(self):
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = None
            result = check_provider_health(999)
        self.assertEqual(result.status, "down")
        self.assertEqual(result.error_message, "提供方不存在")

    def test_unknown_adapter_type_returns_down(self):
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "Unknown Adapter",
                "enabled": True,
                "adapter_type": "unknown_adapter",
                "config_json": {},
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "down")
        self.assertIn("未知适配器类型", result.error_message)

    def test_public_feed_returns_healthy_immediately(self):
        """public_feed has no gateway to probe — should return healthy without HTTP call."""
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "Public Feed Provider",
                "enabled": True,
                "adapter_type": "public_feed",
                "config_json": {},
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.latency_ms, 0)
        self.assertIsNone(result.error_message)

    def test_list_api_returns_healthy_immediately(self):
        """list_api has no gateway to probe — should return healthy without HTTP call."""
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "List API Provider",
                "enabled": True,
                "adapter_type": "list_api",
                "config_json": {},
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.latency_ms, 0)

    def test_rotating_gateway_missing_host_returns_down(self):
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "Incomplete Gateway",
                "enabled": True,
                "adapter_type": "rotating_gateway",
                "config_json": {"gateway_port": 8080},  # missing host
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "down")
        self.assertIn("gateway_host", result.error_message)

    def test_local_gateway_missing_url_returns_down(self):
        from monitor.provider_health import check_provider_health
        with mock.patch("monitor.provider_health._db") as mock_db:
            mock_db.get_dynamic_proxy_provider.return_value = {
                "id": 1,
                "name": "Incomplete Local",
                "enabled": True,
                "adapter_type": "local_gateway",
                "config_json": {},  # missing local_proxy_url
            }
            result = check_provider_health(1)
        self.assertEqual(result.status, "down")
        self.assertIn("local_proxy_url", result.error_message)

    def test_build_gateway_proxy_url_constructs_correct_format(self):
        from monitor.provider_health import _build_gateway_proxy_url
        url = _build_gateway_proxy_url("http", "user", "pass", "proxy.example.com", 8080)
        self.assertEqual(url, "http://user:pass@proxy.example.com:8080")

    def test_build_gateway_proxy_url_without_auth(self):
        from monitor.provider_health import _build_gateway_proxy_url
        url = _build_gateway_proxy_url("http", "", "", "proxy.example.com", 8080)
        self.assertEqual(url, "http://proxy.example.com:8080")

    def test_build_gateway_proxy_url_socks5(self):
        from monitor.provider_health import _build_gateway_proxy_url
        url = _build_gateway_proxy_url("socks5", "user", "pass", "proxy.example.com", 1080)
        self.assertEqual(url, "socks5://user:pass@proxy.example.com:1080")

    def test_build_gateway_proxy_url_socks4(self):
        from monitor.provider_health import _build_gateway_proxy_url
        url = _build_gateway_proxy_url("socks4", "", "", "proxy.example.com", 1080)
        self.assertEqual(url, "socks4://proxy.example.com:1080")


class TestProviderHealthHttpProbe(unittest.TestCase):
    """Test HTTP probe behavior via mocking."""

    def test_healthy_response_returns_healthy(self):
        from monitor.provider_health import _http_probe
        import urllib.request
        from unittest.mock import patch, MagicMock

        mock_response = MagicMock()
        mock_response.code = 204
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = _http_probe("http://user:pass@proxy.example.com:8080", "http")

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.response_code, 204)
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertIsNone(result.error_message)

    def test_401_auth_error_returns_auth_error(self):
        from monitor.provider_health import _http_probe
        import urllib.request
        from urllib.error import HTTPError
        from unittest.mock import patch, MagicMock

        mock_opener = MagicMock()
        mock_opener.open.side_effect = HTTPError(
            url="https://www.google.com/generate_204",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = _http_probe("http://user:bad@proxy.example.com:8080", "http")

        self.assertEqual(result.status, "auth_error")
        self.assertEqual(result.response_code, 401)

    def test_407_proxy_auth_returns_auth_error(self):
        from monitor.provider_health import _http_probe
        import urllib.request
        from urllib.error import URLError
        from unittest.mock import patch, MagicMock

        mock_opener = MagicMock()
        mock_opener.open.side_effect = URLError("Proxy Authentication Required")

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = _http_probe("http://user:bad@proxy.example.com:8080", "http")

        self.assertEqual(result.status, "auth_error")
        self.assertIn("认证", result.error_message)

    def test_connection_refused_returns_down(self):
        from monitor.provider_health import _http_probe
        from unittest.mock import patch, MagicMock

        mock_opener = MagicMock()
        mock_opener.open.side_effect = ConnectionRefusedError()

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = _http_probe("http://proxy.example.com:8080", "http")

        self.assertEqual(result.status, "down")
        self.assertEqual(result.latency_ms, -1)
        self.assertIn("拒绝", result.error_message)

    def test_timeout_returns_down(self):
        from monitor.provider_health import _http_probe
        import socket
        from unittest.mock import patch, MagicMock

        mock_opener = MagicMock()
        mock_opener.open.side_effect = socket.timeout("timed out")

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = _http_probe("http://proxy.example.com:8080", "http")

        self.assertEqual(result.status, "down")
        self.assertIn("超时", result.error_message)

    def test_slow_response_returns_degraded(self):
        from monitor.provider_health import _http_probe
        import urllib.request
        from unittest.mock import patch, MagicMock
        import time

        mock_response = MagicMock()
        mock_response.code = 204
        mock_opener = MagicMock()
        # Simulate slow response (> degraded threshold)
        def slow_open(*args, **kwargs):
            time.sleep(0.05)  # 50ms simulated
            return mock_response
        mock_opener.open.side_effect = slow_open

        with patch("monitor.provider_health._db") as mock_db:
            mock_db.load_config.return_value = {"proxy_probe_timeout_seconds": 5}
            with patch("urllib.request.build_opener", return_value=mock_opener):
                # Patch the degraded threshold to a small value so 50ms triggers it
                with patch("monitor.provider_health._DEGRADED_THRESHOLD_MS", 10):
                    result = _http_probe("http://proxy.example.com:8080", "http")

        self.assertEqual(result.status, "degraded")
        self.assertGreater(result.latency_ms, 10)  # patched threshold
        self.assertIn("过慢", result.error_message)


class TestHealthCheckApiIntegration(unittest.TestCase):
    """Integration test: health check API endpoint wires through to DB correctly."""

    def test_health_check_calls_provider_health_module(self):
        """The API endpoint should call check_provider_health and persist results."""
        import monitor_server
        import monitor.db as _db

        # Set up the handler with a test token
        monitor_server.MonitorHandler._api_token = "test-token"

        from monitor.provider_health import ProbeResult

        mock_result = ProbeResult(
            status="healthy",
            latency_ms=150,
            error_message=None,
            response_code=204,
        )

        with mock.patch.object(_db, "get_dynamic_proxy_provider") as mock_get:
            mock_get.return_value = {
                "id": 5,
                "name": "Test Provider",
                "enabled": True,
                "adapter_type": "rotating_gateway",
                "config_json": {"gateway_host": "gw.test.com", "gateway_port": 8080},
            }
            with mock.patch("monitor.provider_health.check_provider_health", return_value=mock_result) as mock_health:
                with mock.patch.object(_db, "update_dynamic_proxy_provider") as mock_update:
                    with mock.patch.object(_db, "load_config") as mock_cfg:
                        mock_cfg.return_value = {"provider_cooldown_seconds": 600}
                        with mock.patch.object(monitor_server.MonitorHandler, "_send_json") as mock_send:
                            handler = monitor_server.MonitorHandler
                            instance = object.__new__(handler)
                            instance._send_json = mock_send
                            instance._api_dynamic_provider_health_check(5)

        # Verify health check was called
        mock_health.assert_called_once_with(5)

        # Verify DB was updated with the result
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs["last_health_status"], "healthy")
        self.assertEqual(call_kwargs["last_error_message"], None)
        self.assertIsNone(call_kwargs["cooldown_until"])

        # Verify API response
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertEqual(args[0]["ok"], True)
        self.assertEqual(args[0]["status"], "healthy")
        self.assertEqual(args[0]["latency_ms"], 150)
        self.assertEqual(args[0]["response_code"], 204)

    def test_health_check_down_sets_cooldown(self):
        """Down status should set cooldown_until from config."""
        import monitor_server
        import monitor.db as _db

        from monitor.provider_health import ProbeResult

        mock_result = ProbeResult(
            status="down",
            latency_ms=-1,
            error_message="连接超时",
            response_code=None,
        )

        with mock.patch.object(_db, "get_dynamic_proxy_provider") as mock_get:
            mock_get.return_value = {
                "id": 3,
                "name": "Down Provider",
                "enabled": True,
                "adapter_type": "rotating_gateway",
                "config_json": {"gateway_host": "down.test.com", "gateway_port": 8080},
            }
            with mock.patch("monitor.provider_health.check_provider_health", return_value=mock_result):
                with mock.patch.object(_db, "update_dynamic_proxy_provider") as mock_update:
                    with mock.patch.object(_db, "load_config") as mock_cfg:
                        mock_cfg.return_value = {"provider_cooldown_seconds": 300}
                        with mock.patch.object(monitor_server.MonitorHandler, "_send_json") as mock_send:
                            handler = monitor_server.MonitorHandler
                            instance = object.__new__(handler)
                            instance._send_json = mock_send
                            instance._api_dynamic_provider_health_check(3)

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs["last_health_status"], "down")
        self.assertEqual(call_kwargs["last_error_message"], "连接超时")
        self.assertIsNotNone(call_kwargs["cooldown_until"])  # cooldown should be set

        # API response
        args, _ = mock_send.call_args
        self.assertEqual(args[0]["ok"], True)
        self.assertEqual(args[0]["status"], "down")
        self.assertIsNotNone(args[0]["cooldown_until"])

    def test_health_check_auth_error_no_cooldown(self):
        """Auth error should NOT set cooldown (config problem, fix manually)."""
        import monitor_server
        import monitor.db as _db

        from monitor.provider_health import ProbeResult

        mock_result = ProbeResult(
            status="auth_error",
            latency_ms=50,
            error_message="认证失败 (407)",
            response_code=407,
        )

        with mock.patch.object(_db, "get_dynamic_proxy_provider") as mock_get:
            mock_get.return_value = {
                "id": 4,
                "name": "Auth Failed",
                "enabled": True,
                "adapter_type": "rotating_gateway",
                "config_json": {"gateway_host": "auth.test.com", "gateway_port": 8080},
            }
            with mock.patch("monitor.provider_health.check_provider_health", return_value=mock_result):
                with mock.patch.object(_db, "update_dynamic_proxy_provider") as mock_update:
                    with mock.patch.object(_db, "load_config") as mock_cfg:
                        mock_cfg.return_value = {"provider_cooldown_seconds": 600}
                        with mock.patch.object(monitor_server.MonitorHandler, "_send_json") as mock_send:
                            handler = monitor_server.MonitorHandler
                            instance = object.__new__(handler)
                            instance._send_json = mock_send
                            instance._api_dynamic_provider_health_check(4)

        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args[1]
        self.assertEqual(call_kwargs["last_health_status"], "auth_error")
        self.assertIsNone(call_kwargs["cooldown_until"])  # NO cooldown for auth errors


if __name__ == "__main__":
    unittest.main()

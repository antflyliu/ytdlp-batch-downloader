"""候选代理探测 transport：与 provider_health 探针衔接。"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class _Cand:
    def __init__(self):
        self.protocol = "http"
        self.host = "1.2.3.4"
        self.port = 8080
        self.proxy_url = "http://1.2.3.4:8080"


class TestUrllibCandidateTransport(unittest.TestCase):
    def test_rejected_level0_returns_down_without_network(self):
        from monitor.candidate_probe_transport import UrllibCandidateTransport
        from monitor.proxy_router import CanonicalProxyCandidate

        c = CanonicalProxyCandidate(
            candidate_key="x",
            provider_id=1,
            provider_name="n",
            protocol="http",
            host="10.0.0.1",
            port=80,
            proxy_url="http://10.0.0.1:80",
        )
        t = UrllibCandidateTransport()
        r = asyncio.run(t.probe_lightweight(c, timeout=3))
        self.assertEqual(r.status, "down")
        self.assertIn("私网", r.error_message or "")

    def test_probe_delegates_to_probe_proxy_url(self):
        from monitor.candidate_probe_transport import UrllibCandidateTransport
        from monitor.provider_health import ProbeResult as PR

        fake = PR(status="healthy", latency_ms=42, error_message=None, response_code=204)

        with mock.patch(
            "monitor.candidate_probe_transport.probe_proxy_url",
            return_value=fake,
        ) as m_probe:
            t = UrllibCandidateTransport()
            r = asyncio.run(t.probe_lightweight(_Cand(), timeout=5))

        m_probe.assert_called_once()
        self.assertEqual(m_probe.call_args[0][0], "http://1.2.3.4:8080")
        self.assertEqual(m_probe.call_args[0][1], "http")
        self.assertEqual(m_probe.call_args[0][2], 5.0)
        self.assertEqual(r.status, "healthy")
        self.assertEqual(r.latency_ms, 42)


class TestProbeProxyUrlTimeout(unittest.TestCase):
    def test_explicit_timeout_skips_load_config(self):
        from monitor.provider_health import probe_proxy_url
        import urllib.request
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.code = 204
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response

        with patch("monitor.provider_health._db") as mock_db:
            with patch("urllib.request.build_opener", return_value=mock_opener):
                result = probe_proxy_url("http://proxy.example.com:8080", "http", timeout_seconds=2.5)

        mock_db.load_config.assert_not_called()
        self.assertEqual(result.status, "healthy")
        mock_opener.open.assert_called()
        self.assertEqual(mock_opener.open.call_args[1]["timeout"], 2.5)

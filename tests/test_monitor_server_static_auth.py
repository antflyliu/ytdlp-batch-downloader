"""tests/test_monitor_server_static_auth.py — monitor_server 静态资源鉴权边界回归测试"""
import os
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from socketserver import ThreadingMixIn
from http.server import HTTPServer

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor_server


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TestStaticFileAuthBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 避免测试触发真实数据库 token 生成逻辑
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

    def _request(self, method: str, path: str, headers: dict | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body, dict(resp.getheaders())

    def test_get_embedded_presentation_is_anonymous(self):
        status, body, headers = self._request("GET", "/proxy-pool-feature.html")
        self.assertEqual(status, 200)
        self.assertIn(b"IP ", body)
        self.assertEqual(headers.get("Content-type", "").split(";")[0], "text/html")

    def test_head_embedded_presentation_is_anonymous(self):
        status, body, headers = self._request("HEAD", "/proxy-pool-feature.html")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("Content-type", "").split(";")[0], "text/html")

    def test_missing_static_file_returns_404_not_401(self):
        status, body, _ = self._request("GET", "/missing-static-file.js")
        self.assertEqual(status, 404)
        self.assertNotIn("401".encode(), body)

    def test_api_still_requires_bearer_token(self):
        status, body, headers = self._request("GET", "/api/accounts")
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        self.assertIn("未授权".encode("utf-8"), body)

    def test_shutdown_api_requires_bearer_token(self):
        status, body, headers = self._request("POST", "/api/system/shutdown")
        self.assertEqual(status, 401)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")


if __name__ == "__main__":
    unittest.main()

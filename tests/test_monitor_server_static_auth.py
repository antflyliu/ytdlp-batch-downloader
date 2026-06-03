"""tests/test_monitor_server_static_auth.py — monitor_server 静态资源鉴权边界回归测试"""
import json
import sys
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from socketserver import ThreadingMixIn
from http.server import HTTPServer
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor_server
import server.__main__ as _server_main  # noqa: E402 — 实际实现位置


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TestStaticFileAuthBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _ThreadedHTTPServer(("127.0.0.1", 0), monitor_server.MonitorHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        body_bytes = resp.read()
        conn.close()
        return resp.status, body_bytes, dict(resp.getheaders())

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

    def test_api_accounts_allowed_without_monitor_token(self):
        status, body, headers = self._request("GET", "/api/accounts")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")

    def test_shutdown_api_allows_without_auth_when_open(self):
        with mock.patch.object(TestStaticFileAuthBoundary.server, "shutdown"):
            status, body, headers = self._request("POST", "/api/system/shutdown")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        self.assertIn(b'"ok"', body)

    def test_account_api_accepts_handle_channel_url(self):
        with mock.patch.object(_server_main, "_db") as mock_db, mock.patch.object(monitor_server, "_scheduler") as mock_scheduler:
            mock_db.add_account.return_value = 123
            mock_scheduler.is_running.return_value = False
            body = json.dumps({
                "name": "Handle Account",
                "channel_url": "@GoogleDevelopers",
                "api_key_env": "YOUTUBE_Data_API_V3",
            }).encode("utf-8")
            status, resp_body, headers = self._request(
                "POST",
                "/api/accounts",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        self.assertIn(b'"ok": true', resp_body)
        mock_db.add_account.assert_called_once()
        self.assertEqual(mock_db.add_account.call_args.kwargs["channel_url"], "@GoogleDevelopers")

    def test_account_api_accepts_uc_channel_id(self):
        with mock.patch.object(_server_main, "_db") as mock_db, mock.patch.object(monitor_server, "_scheduler") as mock_scheduler:
            mock_db.add_account.return_value = 124
            mock_scheduler.is_running.return_value = False
            body = json.dumps({
                "name": "UC Account",
                "channel_url": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                "api_key_env": "YOUTUBE_Data_API_V3",
            }).encode("utf-8")
            status, resp_body, headers = self._request(
                "POST",
                "/api/accounts",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type", "").split(";")[0], "application/json")
        self.assertIn(b'"ok": true', resp_body)
        mock_db.add_account.assert_called_once()
        self.assertEqual(mock_db.add_account.call_args.kwargs["channel_url"], "UC_x5XG1OV2P6uZZ5FSM9Ttw")

    def test_static_get_ignores_client_aborted_connection(self):
        handler = monitor_server.MonitorHandler.__new__(monitor_server.MonitorHandler)
        handler.path = "/__nonexistent_unit_test__.html"
        handler.requestline = "GET /__nonexistent_unit_test__.html HTTP/1.0"
        with mock.patch.object(_server_main.SimpleHTTPRequestHandler, "do_GET", side_effect=ConnectionAbortedError(10053, "aborted")):
            with mock.patch.object(_server_main, "_log") as mock_log:
                # should not re-raise when browser aborts static response mid-stream
                handler.do_GET()
        mock_log.warning.assert_called_once()

    def test_static_get_ignores_broken_pipe(self):
        handler = monitor_server.MonitorHandler.__new__(monitor_server.MonitorHandler)
        handler.path = "/__nonexistent_unit_test__.html"
        handler.requestline = "GET /__nonexistent_unit_test__.html HTTP/1.0"
        with mock.patch.object(_server_main.SimpleHTTPRequestHandler, "do_GET", side_effect=BrokenPipeError("pipe closed")):
            with mock.patch.object(_server_main, "_log") as mock_log:
                handler.do_GET()
        mock_log.warning.assert_called_once()

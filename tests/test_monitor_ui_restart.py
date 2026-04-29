"""tests/test_monitor_ui_restart.py — Web UI 强制重启入口测试"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor_ui


class TestForceRestartWebUI(unittest.TestCase):
    @patch("monitor_ui.time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    @patch("monitor_ui._db.get_api_token", return_value="test-token")
    def test_shutdown_existing_web_ui_success(self, mock_token, mock_urlopen, _mock_sleep):
        shutdown_resp = MagicMock()
        shutdown_resp.status = 200
        # 第一次请求 shutdown 成功，第二次 status 探测失败表示服务已停
        mock_urlopen.side_effect = [shutdown_resp, URLError("connection refused")]

        ok = monitor_ui._shutdown_existing_web_ui(18999)

        self.assertTrue(ok)
        self.assertGreaterEqual(mock_urlopen.call_count, 2)
        req = mock_urlopen.call_args_list[0].args[0]
        self.assertIn("/api/system/shutdown", req.full_url)
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token")

    @patch("urllib.request.urlopen")
    @patch("monitor_ui._db.get_api_token", return_value="test-token")
    def test_shutdown_existing_web_ui_returns_false_on_request_error(self, mock_token, mock_urlopen):
        mock_urlopen.side_effect = URLError("boom")

        ok = monitor_ui._shutdown_existing_web_ui(18999)

        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

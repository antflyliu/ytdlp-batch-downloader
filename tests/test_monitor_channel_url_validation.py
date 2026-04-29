"""tests/test_monitor_channel_url_validation.py — monitor_server 频道 URL 校验回归测试"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import monitor_server


class TestMonitorChannelUrlValidation(unittest.TestCase):
    def test_accepts_youtube_full_url(self):
        self.assertTrue(monitor_server._is_valid_youtube_url("https://www.youtube.com/@wenzhaoofficial"))

    def test_accepts_handle(self):
        self.assertTrue(monitor_server._is_valid_youtube_url("@wenzhaoofficial"))

    def test_accepts_uc_channel_id(self):
        self.assertTrue(monitor_server._is_valid_youtube_url("UC1234567890abcdefghijkl"))

    def test_rejects_non_youtube_http_url(self):
        self.assertFalse(monitor_server._is_valid_youtube_url("https://example.com/foo"))

    def test_rejects_javascript_scheme(self):
        self.assertFalse(monitor_server._is_valid_youtube_url("javascript:alert(1)"))


if __name__ == "__main__":
    unittest.main()

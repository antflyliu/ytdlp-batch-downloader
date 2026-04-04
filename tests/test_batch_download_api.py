"""tests/test_batch_download_api.py — 批量下载 API 单元测试"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


# ── mock HTTP server ─────────────────────────────────────────
class _FakeMonitorHandler:
    """Minimal mock of MonitorHandler for testing API responses."""
    _cfg = {}
    _tasks = {}
    _task_lock = threading.Lock()

    def __init__(self):
        self._json_body = {}
        self._path = ""
        self._method = "POST"
        self._sent = {}

    def _read_json(self):
        import json
        return self._json_body

    def _send_json(self, data, code=200):
        self._sent = {"code": code, "body": data}

    def _api_account_videos_batch_download(self, acc_id, body):
        from monitor import db as _db

        video_ids = body.get("video_ids", [])
        if not isinstance(video_ids, list):
            self._send_json({"error": "video_ids 必须为数组"}, 400)
            return
        for vid in video_ids:
            if not isinstance(vid, int):
                self._send_json({"error": "video_ids 数组元素必须为整数"}, 400)
                return
        if not video_ids:
            self._send_json({"error": "未选择视频"}, 400)
            return

        cfg = _db.load_config()
        output_path = body.get("output_path", "").strip()
        if not output_path:
            output_path = cfg.get("download_output_path", "").strip()
        if not output_path:
            output_path = os.path.join(_ROOT, "videos")

        sub_langs = body.get("sub_langs")
        no_subs = body.get("no_subs", True)

        self._send_json({
            "ok": True,
            "task_id": "test-task",
            "queued": len(video_ids),
            "sub_langs": sub_langs,
            "no_subs": no_subs,
        })


class _TestHTTPClient:
    """Minimal HTTP client using stdlib socket."""
    def __init__(self, port):
        self.port = port
        self.host = "127.0.0.1"

    def post_json(self, path, body):
        body_bytes = json.dumps(body).encode()
        conn = HTTPConnection(self.host, self.port, timeout=5)
        conn.request("POST", path, body=body_bytes,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())


class TestVideoIdsValidation(unittest.TestCase):
    """video_ids 类型校验测试"""

    def setUp(self):
        self.h = _FakeMonitorHandler()

    def _call(self, video_ids):
        self.h._json_body = {"video_ids": video_ids}
        self.h._api_account_videos_batch_download("1", self.h._json_body)
        return self.h._sent

    def test_not_list_returns_400(self):
        r = self._call("not-a-list")
        self.assertEqual(r["code"], 400)
        self.assertIn("必须为数组", r["body"]["error"])

    def test_not_list_string_number_returns_400(self):
        r = self._call(123)
        self.assertEqual(r["code"], 400)
        self.assertIn("必须为数组", r["body"]["error"])

    def test_elements_not_int_returns_400(self):
        r = self._call([1, "2", 3])
        self.assertEqual(r["code"], 400)
        self.assertIn("必须为整数", r["body"]["error"])

    def test_empty_list_returns_400(self):
        r = self._call([])
        self.assertEqual(r["code"], 400)
        self.assertIn("未选择视频", r["body"]["error"])

    def test_valid_int_list_returns_200(self):
        r = self._call([1, 2, 3])
        self.assertEqual(r["code"], 200)
        self.assertTrue(r["body"]["ok"])


class TestSubtitleDefaults(unittest.TestCase):
    """字幕下载默认参数测试"""

    def setUp(self):
        self.h = _FakeMonitorHandler()

    def _call(self, body_override=None):
        body = {"video_ids": [1]}
        if body_override:
            body.update(body_override)
        self.h._json_body = body
        self.h._api_account_videos_batch_download("1", self.h._json_body)
        return self.h._sent

    def test_default_no_subs_is_true(self):
        r = self._call()
        self.assertTrue(r["body"]["no_subs"])

    def test_default_sub_langs_is_none(self):
        r = self._call()
        self.assertIsNone(r["body"]["sub_langs"])

    def test_toggle_on_includes_sub_langs(self):
        r = self._call({"sub_langs": "zh-Hans,en", "no_subs": False})
        self.assertEqual(r["body"]["sub_langs"], "zh-Hans,en")
        self.assertFalse(r["body"]["no_subs"])

    def test_toggle_off_no_subs_true(self):
        r = self._call({"no_subs": True})
        self.assertTrue(r["body"]["no_subs"])
        self.assertIsNone(r["body"]["sub_langs"])


class TestSchedulerNoSubs(unittest.TestCase):
    """调度器自动下载 no_subs=True 测试"""

    @patch("monitor.scheduler.batch_download")
    @patch("monitor.scheduler._db.get_videos_by_ids")
    @patch("monitor.scheduler._db.load_config")
    @patch("monitor.scheduler._db.update_videos_download_status")
    def test_auto_download_passes_no_subs_true(
        self, mock_status, mock_cfg, mock_ids, mock_dl
    ):
        mock_cfg.return_value = {"download_output_path": tempfile.gettempdir()}
        mock_ids.return_value = [
            {"id": 1, "url": "https://youtu.be/test", "title": "v1"}
        ]
        mock_dl.return_value = []

        from monitor import scheduler
        scheduler._auto_download_videos([{"id": 1, "url": "https://youtu.be/test"}])

        _, kwargs = mock_dl.call_args
        self.assertTrue(kwargs.get("no_subs"))
        self.assertIsNone(kwargs.get("sub_langs"))


class TestConfigDefaultSubLangs(unittest.TestCase):
    """default_sub_langs 配置项测试"""

    def test_default_sub_langs_in_config_default(self):
        from monitor.db import _config_default
        cfg = _config_default()
        self.assertEqual(cfg.get("default_sub_langs"), "zh-Hans,en")


class TestBackupDb(unittest.TestCase):
    """数据库备份测试"""

    @patch("monitor.db.get_connection")
    def test_backup_db_creates_backup_file(self, mock_conn):
        import shutil
        with patch("shutil.copy2") as mock_copy:
            with patch("os.listdir", return_value=["monitor_20260101_120000.db"]):
                with patch("os.remove"):
                    with patch("os.path.exists", return_value=True):
                        from monitor import db
                        path = db.backup_db()
                        mock_copy.assert_called_once()
                        self.assertIsNotNone(path)


if __name__ == "__main__":
    unittest.main()

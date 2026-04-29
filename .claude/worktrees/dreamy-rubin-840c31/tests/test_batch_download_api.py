"""tests/test_batch_download_api.py — 批量下载 API 单元测试"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
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
    """数据库备份测试：验证 iterdump 方式排除 api_keys 表"""

    def setUp(self):
        import tempfile, shutil, sqlite3
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "monitor.db")
        self._data_dir = self._tmpdir
        # 创建源 DB：包含 api_keys 和另一个表
        conn = sqlite3.connect(self._db_path)
        conn.execute("CREATE TABLE api_keys (id INTEGER PRIMARY KEY, key_value TEXT, name TEXT)")
        conn.execute("INSERT INTO api_keys (key_value, name) VALUES ('AIzaSySECRET123', 'TestKey')")
        conn.execute("CREATE TABLE monitor_accounts (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO monitor_accounts (name) VALUES ('TestAccount')")
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _ctx(self):
        """patch db 和 db.connection 模块的路径变量到临时目录"""
        import monitor.db as _db
        from contextlib import ExitStack
        _conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack = ExitStack()
        stack.enter_context(patch.object(_db, "_DB_PATH", self._db_path))
        stack.enter_context(patch.object(_db, "_DATA_DIR", self._data_dir))
        stack.enter_context(patch.object(_conn, "_DB_PATH", self._db_path))
        stack.enter_context(patch.object(_conn, "_DATA_DIR", self._data_dir))
        return stack

    def test_backup_db_creates_backup_file(self):
        """验证备份文件被创建"""
        import monitor.db as _db
        with self._ctx():
            path = _db.backup_db()
            self.assertIsNotNone(path)
            self.assertTrue(os.path.exists(path))

    def test_backup_db_excludes_api_keys_table(self):
        """验证备份内容排除 api_keys 表（防止明文 Key 泄露）"""
        import monitor.db as _db
        import sqlite3
        with self._ctx():
            path = _db.backup_db()
            self.assertIsNotNone(path)
            # 读取备份文件，检查表和内容
            bk = sqlite3.connect(path)
            tables = [r[0] for r in bk.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            # api_keys 不应出现在备份中
            self.assertNotIn("api_keys", tables)
            # 其他表应保留
            self.assertIn("monitor_accounts", tables)
            # 确认其他表数据完整
            acc_count = bk.execute("SELECT COUNT(*) FROM monitor_accounts").fetchone()[0]
            self.assertEqual(acc_count, 1)
            bk.close()


class _WebhookConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "monitor.db")
        self._data_dir = os.path.join(self._tmpdir, "data")
        self._config_path = os.path.join(self._tmpdir, "config.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _ctx(self):
        import monitor.db as _db
        import utils.paths as up
        import config.settings as cs
        from contextlib import ExitStack
        _conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack = ExitStack()
        stack.enter_context(patch.object(up, "get_config_path", lambda: self._config_path))
        stack.enter_context(patch.object(up, "get_db_path", lambda: self._db_path))
        stack.enter_context(patch.object(up, "get_data_dir", lambda: self._data_dir))
        stack.enter_context(patch.object(cs, "get_config_path", lambda: self._config_path))
        stack.enter_context(patch.object(cs, "get_data_dir", lambda: self._data_dir))
        stack.enter_context(patch.object(cs, "get_pkg_dir", lambda: self._tmpdir))
        stack.enter_context(patch.object(_db, "_DB_PATH", self._db_path))
        stack.enter_context(patch.object(_db, "_DATA_DIR", self._data_dir))
        stack.enter_context(patch.object(_db, "_CONFIG_PATH", self._config_path))
        stack.enter_context(patch.object(_db, "_PKG_DIR", self._tmpdir))
        stack.enter_context(patch.object(_conn, "_DB_PATH", self._db_path))
        stack.enter_context(patch.object(_conn, "_DATA_DIR", self._data_dir))
        stack.enter_context(patch.object(_conn, "_CONFIG_PATH", self._config_path))
        stack.enter_context(patch.object(_conn, "_PKG_DIR", self._tmpdir))
        return stack

    def _read_raw_config(self):
        with open(self._config_path, "r", encoding="utf-8") as f:
            return json.load(f)


class TestGlobalWebhookConfigEncryption(_WebhookConfigTestCase):
    def test_save_config_encrypts_global_webhooks(self):
        import monitor.db as _db

        plaintext = "https://open.feishu.cn/open-apis/bot/v2/hook/secret-token"
        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["global_feishu_url"] = plaintext

            _db.save_config(cfg)

            raw_cfg = self._read_raw_config()
            self.assertNotEqual(raw_cfg["global_feishu_url"], plaintext)
            self.assertTrue(raw_cfg["global_feishu_url"].startswith("enc:"))

            loaded_cfg = _db.load_config()
            self.assertEqual(loaded_cfg["global_feishu_url"], plaintext)

    def test_save_config_encrypts_global_dingtalk_sign_secret(self):
        import monitor.db as _db

        plaintext = "SECxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["global_dingtalk_sign_secret"] = plaintext

            _db.save_config(cfg)

            raw_cfg = self._read_raw_config()
            self.assertNotEqual(raw_cfg["global_dingtalk_sign_secret"], plaintext)
            self.assertTrue(raw_cfg["global_dingtalk_sign_secret"].startswith("enc:"))

            loaded_cfg = _db.load_config()
            self.assertEqual(loaded_cfg["global_dingtalk_sign_secret"], plaintext)

    def test_load_config_migrates_plaintext_global_webhooks(self):
        import monitor.db as _db

        plaintext = "https://open.feishu.cn/open-apis/bot/v2/hook/plaintext-token"
        with self._ctx():
            _db.init_db()
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump({
                    **_db._config_default(),
                    "global_feishu_url": plaintext,
                }, f, ensure_ascii=False, indent=2)

            loaded_cfg = _db.load_config()

            self.assertEqual(loaded_cfg["global_feishu_url"], plaintext)
            raw_cfg = self._read_raw_config()
            self.assertNotEqual(raw_cfg["global_feishu_url"], plaintext)
            self.assertTrue(raw_cfg["global_feishu_url"].startswith("enc:"))

    def test_load_config_preserves_encrypted_default_api_key_id_at_rest(self):
        import monitor.db as _db

        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["default_api_key_id"] = "7"
            _db.save_config(cfg)
            raw_before = self._read_raw_config()
            self.assertTrue(raw_before["default_api_key_id"].startswith("enc:"))

            loaded_cfg = _db.load_config()

            self.assertEqual(loaded_cfg["default_api_key_id"], "7")
            raw_after = self._read_raw_config()
            self.assertEqual(raw_after["default_api_key_id"], raw_before["default_api_key_id"])

    def test_load_config_migrates_plaintext_default_api_key_id(self):
        import monitor.db as _db

        with self._ctx():
            _db.init_db()
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump({
                    **_db._config_default(),
                    "default_api_key_id": "7",
                }, f, ensure_ascii=False, indent=2)

            loaded_cfg = _db.load_config()

            self.assertEqual(loaded_cfg["default_api_key_id"], "7")
            raw_cfg = self._read_raw_config()
            self.assertNotEqual(raw_cfg["default_api_key_id"], "7")
            self.assertTrue(raw_cfg["default_api_key_id"].startswith("enc:"))


class TestSchedulerGlobalWebhookLoading(_WebhookConfigTestCase):
    def test_ensure_global_webhooks_uses_decrypted_values(self):
        import monitor.db as _db
        from monitor import scheduler

        plaintext = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-key"
        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["global_wecom_url"] = plaintext
            _db.save_config(cfg)

            scheduler._GLOBAL_WEBHOOKS = {}
            scheduler._GLOBAL_WEBHOOKS_LOADED = False
            scheduler._invalidate_config_cache()

            scheduler._ensure_global_webhooks()

            self.assertEqual(scheduler._GLOBAL_WEBHOOKS["wecom"], plaintext)
            raw_cfg = self._read_raw_config()
            self.assertTrue(raw_cfg["global_wecom_url"].startswith("enc:"))

    def test_ensure_global_webhooks_loads_dingtalk_sign_secret(self):
        import monitor.db as _db
        from monitor import scheduler

        sec = "SECbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["global_dingtalk_sign_secret"] = sec
            _db.save_config(cfg)

            scheduler._GLOBAL_WEBHOOKS = {}
            scheduler._GLOBAL_WEBHOOKS_LOADED = False
            scheduler._GLOBAL_DINGTALK_SIGN_SECRET = None
            scheduler._invalidate_config_cache()

            scheduler._ensure_global_webhooks()

            self.assertEqual(scheduler._GLOBAL_DINGTALK_SIGN_SECRET, sec)
            raw_cfg = self._read_raw_config()
            self.assertTrue(raw_cfg["global_dingtalk_sign_secret"].startswith("enc:"))


class TestNotifyLogWebhookRedaction(_WebhookConfigTestCase):
    def test_log_result_does_not_store_raw_webhook(self):
        import monitor.db as _db
        from monitor import notifier

        plaintext = "https://open.feishu.cn/open-apis/bot/v2/hook/super-secret-token"
        with self._ctx():
            _db.init_db()
            account_id = _db.add_account(
                name="TestAccount",
                channel_url="https://www.youtube.com/@test",
                api_key_env="YOUTUBE_Data_API_V3",
            )
            with _db.get_connection() as conn:
                cur = conn.execute(
                    """INSERT INTO monitor_events
                       (account_id, account_name, scan_started_at, status, total_videos, new_videos)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (account_id, "TestAccount", _db.now_iso(), "success", 1, 1),
                )
                event_id = cur.lastrowid

            notifier._log_result(
                platform="feishu",
                account_name="TestAccount",
                video_count=1,
                success=True,
                response="{\"code\":0}",
                event_id=event_id,
                account_id=account_id,
                now_str=_db.now_iso(),
                webhook_url=plaintext,
            )

            with _db.get_connection() as conn:
                row = conn.execute(
                    "SELECT webhook_url FROM monitor_notify_logs WHERE event_id=?",
                    (event_id,),
                ).fetchone()

            self.assertIsNotNone(row)
            self.assertNotEqual(row[0], plaintext)
            self.assertNotIn("super-secret-token", row[0])

    def test_notify_log_does_not_expose_webhook_token(self):
        from monitor import notifier

        plaintext = "https://open.feishu.cn/open-apis/bot/v2/hook/super-secret-token"
        videos = [{"video_id": 1, "title": "Video 1", "url": "https://youtu.be/test"}]

        with patch.object(notifier._log, "info") as mock_info, \
             patch.object(notifier, "_send_webhook", return_value=(True, '{"code":0}')), \
             patch.object(notifier, "_log_result"), \
             patch.object(notifier._db, "mark_notify_sent"):
            notifier.notify(
                event_id=1,
                account_id=1,
                account_name="TestAccount",
                channel_url="https://www.youtube.com/@test",
                videos=videos,
                platform="feishu",
                webhook_url=plaintext,
                duration_ms=123,
            )

        joined_messages = "\n".join(
            str(call.args[0]) for call in mock_info.call_args_list if call.args
        )
        self.assertNotIn("super-secret-token", joined_messages)
        self.assertIn("https://open.feishu.cn/[redacted]", joined_messages)


class TestDynamicProxyConfigPersistence(_WebhookConfigTestCase):
    """Verify dynamic proxy config fields are saved and loaded correctly."""

    def test_save_config_persists_dynamic_proxy_flags(self):
        import monitor.db as _db

        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            # Set non-default values for dynamic proxy fields
            cfg["system_dynamic_proxy_enabled"] = True
            cfg["allow_free_proxy"] = False
            cfg["allow_free_proxy_for_auto_download"] = True
            cfg["allow_free_proxy_with_cookies"] = True
            cfg["manual_direct_fallback"] = False
            cfg["auto_direct_fallback"] = True
            cfg["default_proxy_protocol_order"] = ["socks5", "http"]
            cfg["default_session_mode"] = "rotate"
            cfg["default_sticky_minutes"] = 30

            _db.save_config(cfg)
            loaded = _db.load_config()

            self.assertTrue(loaded["system_dynamic_proxy_enabled"])
            self.assertFalse(loaded["allow_free_proxy"])
            self.assertTrue(loaded["allow_free_proxy_for_auto_download"])
            self.assertTrue(loaded["allow_free_proxy_with_cookies"])
            self.assertFalse(loaded["manual_direct_fallback"])
            self.assertTrue(loaded["auto_direct_fallback"])
            self.assertEqual(loaded["default_proxy_protocol_order"], ["socks5", "http"])
            self.assertEqual(loaded["default_session_mode"], "rotate")
            self.assertEqual(loaded["default_sticky_minutes"], 30)

    def test_config_preserves_apply_dynamic_proxy_switches(self):
        import monitor.db as _db

        with self._ctx():
            _db.init_db()
            cfg = _db._config_default()
            cfg["apply_dynamic_proxy_to_new_accounts"] = False
            cfg["apply_dynamic_proxy_to_existing_accounts"] = True

            _db.save_config(cfg)
            loaded = _db.load_config()

            self.assertFalse(loaded["apply_dynamic_proxy_to_new_accounts"])
            self.assertTrue(loaded["apply_dynamic_proxy_to_existing_accounts"])

    def test_load_config_merges_old_config_with_dynamic_defaults(self):
        """Old config without dynamic proxy fields should get defaults on load."""
        import monitor.db as _db

        with self._ctx():
            _db.init_db()
            old_cfg = {"download_output_path": "/old/path"}
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(old_cfg, f)

            loaded = _db.load_config()

            # New fields should have defaults
            self.assertFalse(loaded["system_dynamic_proxy_enabled"])
            self.assertTrue(loaded["allow_free_proxy"])
            self.assertFalse(loaded["allow_free_proxy_for_auto_download"])
            self.assertFalse(loaded["allow_free_proxy_with_cookies"])
            self.assertTrue(loaded["manual_direct_fallback"])
            self.assertFalse(loaded["auto_direct_fallback"])
            # Old field preserved
            self.assertEqual(loaded["download_output_path"], "/old/path")


class TestDownloadProxyModeAccountRoundtrip(unittest.TestCase):
    """Verify download_proxy_mode is correctly returned and saved via account API."""

    def test_account_response_includes_download_proxy_mode(self):
        import monitor.db as _db
        import tempfile, shutil

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        cfg_path = os.path.join(tmpdir, "cfg.json")
        pkg_dir = tmpdir

        orig_db = _db._DB_PATH
        orig_cfg = _db._CONFIG_PATH
        orig_pkg = _db._PKG_DIR

        try:
            _db._DB_PATH = db_path
            _db._CONFIG_PATH = cfg_path
            _db._PKG_DIR = pkg_dir
            _db.init_db()

            aid = _db.add_account(
                name="Test Account",
                channel_url="https://www.youtube.com/@test",
                api_key_env="TEST_KEY",
                download_proxy_mode="system_only",
            )
            account = _db.get_account(aid)

            self.assertEqual(account["download_proxy_mode"], "system_only")
        finally:
            _db._DB_PATH = orig_db
            _db._CONFIG_PATH = orig_cfg
            _db._PKG_DIR = orig_pkg
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_update_account_changes_download_proxy_mode(self):
        import monitor.db as _db
        import tempfile, shutil

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        cfg_path = os.path.join(tmpdir, "cfg.json")

        orig_db = _db._DB_PATH
        orig_cfg = _db._CONFIG_PATH
        orig_pkg = _db._PKG_DIR

        try:
            _db._DB_PATH = db_path
            _db._CONFIG_PATH = cfg_path
            _db._PKG_DIR = tmpdir
            _db.init_db()

            aid = _db.add_account(
                name="Test Account",
                channel_url="https://www.youtube.com/@test",
                api_key_env="TEST_KEY",
                download_proxy_mode="auto",
            )

            # Update mode to account_only
            _db.update_account(aid, download_proxy_mode="account_only")
            account = _db.get_account(aid)
            self.assertEqual(account["download_proxy_mode"], "account_only")

            # Update mode to direct_only
            _db.update_account(aid, download_proxy_mode="direct_only")
            account = _db.get_account(aid)
            self.assertEqual(account["download_proxy_mode"], "direct_only")
        finally:
            _db._DB_PATH = orig_db
            _db._CONFIG_PATH = orig_cfg
            _db._PKG_DIR = orig_pkg
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

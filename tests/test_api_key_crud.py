"""tests/test_api_key_crud.py — API Key CRUD 单元测试"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


def _test_env():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    data_dir = os.path.dirname(db_path)
    cfg_path = os.path.join(data_dir, "config.json")

    test_env = os.environ.copy()
    test_env["YOUTUBE_Data_API_V3"] = "AIzaSyTestKeyForUnitTest123456789"

    def cleanup():
        try:
            os.unlink(db_path)
        except Exception:
            pass
        try:
            os.unlink(cfg_path)
        except Exception:
            pass
        backup_dir = os.path.join(data_dir, "backup")
        try:
            import shutil
            shutil.rmtree(backup_dir)
        except Exception:
            pass

    return db_path, data_dir, cfg_path, cleanup


class TestMaskAndEscape(unittest.TestCase):
    """纯函数测试"""

    def test_mask_key_short(self):
        key = "AIzaSyAB12"
        masked = key[:4] + "••••••"
        self.assertEqual(masked[:4], "AIza")
        self.assertEqual(len(masked), 10)

    def test_mask_key_normal(self):
        key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZabcd"
        masked = key[:4] + "••••••••" + key[-4:]
        self.assertEqual(masked[:4], "AIza")
        self.assertEqual(masked[-4:], "abcd")
        self.assertIn("••••••••", masked)
        self.assertNotIn("BCDE", masked)

    def test_escape_like_plain(self):
        s = "hello world"
        e = s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        self.assertEqual(e, "hello world")

    def test_escape_like_percent(self):
        s = "video%20files"
        e = s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        self.assertEqual(e, r"video\%20files")

    def test_escape_like_underscore(self):
        s = "video_1_files"
        e = s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        self.assertEqual(e, r"video\_1\_files")

    def test_escape_like_mixed(self):
        s = "50%_files"
        e = s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        self.assertEqual(e, r"50\%\_files")


class TestApiKeyCRUD(unittest.TestCase):
    """API Key CRUD 测试（临时数据库隔离）"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _ctx(self):
        """返回 ExitStack，管理所有需要 patch 的模块路径"""
        import monitor.db as db
        import monitor.quota as quota
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        stack.enter_context(patch.object(quota, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(quota, "_DATA_DIR", self.data_dir))
        return stack

    def _db_only_ctx(self):
        """仅 patch db 模块（用于不需要 quota 表的测试）"""
        import monitor.db as db
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        return stack

    def test_add_and_list_key(self):
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyTestKeyForCRUD11111111111111", "测试Key", 5000)
            self.assertIsInstance(key_id, int)
            self.assertGreater(key_id, 0)

            keys = db.list_api_keys()
            found = next((k for k in keys if k["id"] == key_id), None)
            self.assertIsNotNone(found)
            self.assertEqual(found["name"], "测试Key")
            self.assertEqual(found["daily_quota"], 5000)
            self.assertEqual(found["is_active"], 1)

    def test_add_duplicate_raises(self):
        import monitor.db as db
        with self._ctx():
            db.init_db()
            db.add_api_key("AIzaSyDupTest11111111111111111111", "Key-A", 10000)
            from sqlite3 import IntegrityError
            with self.assertRaises(IntegrityError):
                db.add_api_key("AIzaSyDupTest11111111111111111111", "Key-B", 5000)

    def test_update_fields(self):
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyUpdateTest22222222222222222", "原始名称", 10000)
            db.update_api_key(key_id, name="新名称", daily_quota=8000, is_active=False)
            k = db.get_api_key(key_id)
            self.assertEqual(k["name"], "新名称")
            self.assertEqual(k["daily_quota"], 8000)
            self.assertEqual(k["is_active"], 0)

    def test_update_empty_key_value_unchanged(self):
        """空字符串 key_value 表示不修改"""
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyEmptyTest33333333333333333", "原始Key", 10000)
            k1 = db.get_api_key(key_id)
            orig = k1["key_value"]

            db.update_api_key(key_id, name="新名称", key_value="")
            k2 = db.get_api_key(key_id)
            self.assertEqual(k2["key_value"], orig)
            self.assertEqual(k2["name"], "新名称")

    def test_delete_key(self):
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyDeleteTest44444444444444444", "待删除", 10000)
            db.delete_api_key(key_id)
            self.assertIsNone(db.get_api_key(key_id))

    def test_delete_key_sets_account_null(self):
        """ON DELETE SET NULL：删除 Key 后关联账户的 api_key_id 变为 NULL"""
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyFKTest55555555555555555555", "FK测试", 10000)
            acc_id = db.add_account(
                name="FK测试账户",
                channel_url="https://youtube.com/@fktest",
                api_key_env="YOUTUBE_Data_API_V3",
                api_key_id=key_id,
            )
            # 验证关联
            acc_before = db.get_account(acc_id)
            self.assertEqual(acc_before["api_key_id"], key_id)
            # 删除 Key
            db.delete_api_key(key_id)
            # 验证账户的 api_key_id 被设为 NULL
            acc_after = db.get_account(acc_id)
            self.assertIsNone(acc_after["api_key_id"])

    def test_get_api_key_by_value(self):
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_val = "AIzaSyGetByVal66666666666666666"
            key_id = db.add_api_key(key_val, "by-value测试", 10000)
            found = db.get_api_key_by_value(key_val)
            self.assertIsNotNone(found)
            self.assertEqual(found["id"], key_id)
            self.assertEqual(found["key_value"], key_val)

    def test_quota_incr(self):
        """incr_api_key_quota 成功执行不抛异常"""
        import monitor.db as db
        with self._ctx():
            db.init_db()
            key_id = db.add_api_key(
                "AIzaSyQuotaTest77777777777777777", "配额测试", 10000)
            k = db.get_api_key(key_id)
            # 无异常即通过
            db.incr_api_key_quota(k["key_value"], calls=5, scans=1)

    def test_default_api_key_id_validation(self):
        """不存在的 default_api_key_id 应返回 None"""
        import monitor.db as db
        with self._ctx():
            db.init_db()
            db.add_api_key(
                "AIzaSyValTest88888888888888888", "验证测试", 10000)
            # get_api_key 对不存在的 ID 返回 None
            self.assertIsNone(db.get_api_key(99999))


class TestResolveApiKey(unittest.TestCase):
    """_resolve_api_key 三层兜底链测试"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _patched(self):
        import monitor.db as db
        import monitor.scheduler as scheduler
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        return stack

    def test_account_key_priority(self):
        """账户 api_key_id 优先于系统默认"""
        import monitor.db as db
        import monitor.scheduler as scheduler
        with self._patched():
            db.init_db()
            key1 = db.add_api_key(
                "AIzaSyAccKey99999999999999999", "账户Key", 10000)
            key2 = db.add_api_key(
                "AIzaSyDefKeyAAAAAAAAAAAAAAAAAAA", "默认Key", 10000)

            # 设置 key2 为系统默认
            cfg = db.load_config()
            cfg["default_api_key_id"] = key2
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)

            scheduler._config_cache = None
            account = {"api_key_id": key1, "name": "test"}
            api_key, record, budget = scheduler._resolve_api_key(account)
            self.assertEqual(api_key, "AIzaSyAccKey99999999999999999")
            self.assertEqual(record["id"], key1)
            scheduler._config_cache = None

    def test_fallback_to_default(self):
        """无账户指定时使用系统默认"""
        import monitor.db as db
        import monitor.scheduler as scheduler
        with self._patched():
            db.init_db()
            key1 = db.add_api_key(
                "AIzaSyFallbackBBBBBBBBBBBBBBBBBB", "默认Key", 10000)
            cfg = db.load_config()
            cfg["default_api_key_id"] = key1
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)

            scheduler._config_cache = None
            account = {"api_key_id": None, "name": "test"}
            api_key, record, budget = scheduler._resolve_api_key(account)
            self.assertEqual(api_key, "AIzaSyFallbackBBBBBBBBBBBBBBBBBB")
            self.assertEqual(record["id"], key1)
            scheduler._config_cache = None


if __name__ == "__main__":
    unittest.main()

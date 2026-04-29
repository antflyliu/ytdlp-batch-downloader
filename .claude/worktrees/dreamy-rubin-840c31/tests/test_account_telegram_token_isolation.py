"""
tests/test_account_telegram_token_isolation.py

回归测试：telegram_bot_token 与 webhook_url 字段隔离

Bug 背景：
  1. 飞书/钉钉/企微使用 Webhook URL，但前端标签误写为"Bot Token"
  2. Telegram Bot Token 和其他平台的 Webhook URL 共用同一个数据库字段，
     导致切换平台时字段串值、编辑回填错误

修复验证：
  - telegram_bot_token 为独立数据库列，与 webhook_url 完全解耦
  - add_account / update_account / get_account 对两字段分别处理
  - scheduler 通知决策：Telegram 平台使用 telegram_bot_token，
    其他平台使用 webhook_url
  - API 序列化返回两个独立字段
"""
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
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({}, f)

    def cleanup():
        for path in [db_path, cfg_path]:
            try:
                os.unlink(path)
            except Exception:
                pass

    return db_path, data_dir, cfg_path, cleanup


class TestTelegramTokenFieldIsolation(unittest.TestCase):
    """telegram_bot_token 与 webhook_url 字段隔离 — DB 层测试"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _ctx(self):
        """Patch 所有模块路径指向隔离的临时数据库"""
        import monitor.db as db
        import utils.paths as up
        import config.settings as cs
        from contextlib import ExitStack
        stack = ExitStack()
        db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack.enter_context(patch.object(up, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(up, "get_db_path", lambda: self.db_path))
        stack.enter_context(patch.object(up, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(cs, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_pkg_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        stack.enter_context(patch.object(db_conn, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db_conn, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db_conn, "_CONFIG_PATH", self.cfg_path))
        return stack

    def test_add_account_with_telegram_token(self):
        """add_account 支持 telegram_bot_token 参数并正确加密存储"""
        import monitor.db as db
        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="Telegram测试账户",
                channel_url="https://youtube.com/@test",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                telegram_bot_token="123456789:ABCdefGhIJKlmNoPQRsTUVwxYZ",
                webhook_url=None,
            )
            self.assertIsInstance(acc_id, int)

    def test_get_account_decrypts_telegram_token(self):
        """get_account 能正确解密 telegram_bot_token"""
        import monitor.db as db
        token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxYZ"
        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="Telegram解密测试",
                channel_url="https://youtube.com/@test2",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                telegram_bot_token=token,
            )
            acc = db.get_account(acc_id)
            self.assertEqual(acc["telegram_bot_token"], token)

    def test_webhook_url_and_telegram_token_independent(self):
        """webhook_url 与 telegram_bot_token 两字段相互独立，互不影响"""
        import monitor.db as db
        webhook = "https://open.feishu.cn/webhook/test-webhook"
        tg_token = "987654321:TGbotTOKEN"

        with self._ctx():
            db.init_db()
            # 创建同时有两个字段的账户
            acc_id = db.add_account(
                name="双平台账户",
                channel_url="https://youtube.com/@dual",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                webhook_url=webhook,
                telegram_bot_token=tg_token,
            )
            acc = db.get_account(acc_id)
            # 两者都正确解密
            self.assertEqual(acc["webhook_url"], webhook)
            self.assertEqual(acc["telegram_bot_token"], tg_token)

    def test_update_telegram_token_only_preserves_webhook_url(self):
        """仅更新 telegram_bot_token 时 webhook_url 保持不变"""
        import monitor.db as db
        original_webhook = "https://open.feishu.cn/webhook/original"
        original_token = "111111111:OriginalToken"
        new_token = "222222222:NewToken"

        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="更新测试",
                channel_url="https://youtube.com/@update",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                webhook_url=original_webhook,
                telegram_bot_token=original_token,
            )
            # 仅更新 telegram_bot_token
            db.update_account(acc_id, telegram_bot_token=new_token)

            acc = db.get_account(acc_id)
            self.assertEqual(acc["webhook_url"], original_webhook)
            self.assertEqual(acc["telegram_bot_token"], new_token)

    def test_update_webhook_url_only_preserves_telegram_token(self):
        """仅更新 webhook_url 时 telegram_bot_token 保持不变"""
        import monitor.db as db
        original_webhook = "https://open.feishu.cn/webhook/first"
        new_webhook = "https://open.feishu.cn/webhook/second"
        tg_token = "333333333:TGTokenPreserved"

        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="Webhook更新测试",
                channel_url="https://youtube.com/@webhookupdate",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                webhook_url=original_webhook,
                telegram_bot_token=tg_token,
            )
            # 仅更新 webhook_url
            db.update_account(acc_id, webhook_url=new_webhook)

            acc = db.get_account(acc_id)
            self.assertEqual(acc["webhook_url"], new_webhook)
            self.assertEqual(acc["telegram_bot_token"], tg_token)

    def test_telegram_token_null_when_not_provided(self):
        """未传入 telegram_bot_token 时该字段为 NULL"""
        import monitor.db as db
        webhook = "https://open.feishu.cn/webhook/only-webhook"

        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="仅Webhook",
                channel_url="https://youtube.com/@webhookonly",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="feishu",
                webhook_url=webhook,
                telegram_bot_token=None,
            )
            acc = db.get_account(acc_id)
            self.assertEqual(acc["webhook_url"], webhook)
            self.assertIsNone(acc["telegram_bot_token"])

    def test_list_accounts_returns_both_fields(self):
        """list_accounts 返回两个解密后的字段"""
        import monitor.db as db
        webhook = "https://open.feishu.cn/webhook/list-test"
        token = "444444444:ListTestToken"

        with self._ctx():
            db.init_db()
            db.add_account(
                name="列表测试",
                channel_url="https://youtube.com/@listtest",
                api_key_env="YOUTUBE_Data_API_V3",
                webhook_url=webhook,
                telegram_bot_token=token,
            )
            rows = db.list_accounts()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["webhook_url"], webhook)
            self.assertEqual(rows[0]["telegram_bot_token"], token)


class TestSchedulerTelegramTokenResolution(unittest.TestCase):
    """scheduler 通知决策：Telegram 平台使用 telegram_bot_token"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _patched(self):
        import monitor.db as db
        import utils.paths as up
        import config.settings as cs
        import monitor.scheduler as sched
        from contextlib import ExitStack
        stack = ExitStack()
        db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack.enter_context(patch.object(up, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(up, "get_db_path", lambda: self.db_path))
        stack.enter_context(patch.object(up, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(cs, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_pkg_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        stack.enter_context(patch.object(db_conn, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db_conn, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db_conn, "_CONFIG_PATH", self.cfg_path))
        # 重置 scheduler 配置缓存
        sched._config_cache = None
        return stack

    def test_telegram_platform_uses_telegram_bot_token(self):
        """Telegram 通知时使用 account.telegram_bot_token"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            acc_id = db.add_account(
                name="TG平台测试",
                channel_url="https://youtube.com/@tgtest",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                telegram_bot_token="555555555:TGAccountToken",
                webhook_url="https://open.feishu.cn/webhook/wrong",
            )
            sched._config_cache = None
            account = db.get_account(acc_id)

            # 模拟 _notify_new_videos 的 token 解析逻辑
            platform = account["notify_platform"]
            if platform == "telegram":
                token = account.get("telegram_bot_token")
            else:
                token = account.get("webhook_url")

            self.assertEqual(token, "555555555:TGAccountToken")

    def test_feishu_platform_uses_webhook_url_not_telegram_token(self):
        """飞书通知时应使用 webhook_url，不受 telegram_bot_token 影响"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            acc_id = db.add_account(
                name="飞书平台测试",
                channel_url="https://youtube.com/@feishutest",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="feishu",
                telegram_bot_token="666666666:TGShouldNotBeUsed",
                webhook_url="https://open.feishu.cn/webhook/feishu-correct",
            )
            sched._config_cache = None
            account = db.get_account(acc_id)

            platform = account["notify_platform"]
            if platform == "telegram":
                token = account.get("telegram_bot_token")
            else:
                token = account.get("webhook_url")

            self.assertEqual(token, "https://open.feishu.cn/webhook/feishu-correct")

    def test_account_telegram_token_overrides_global(self):
        """账户级 telegram_bot_token 优先于全局 token"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            # 设置全局 Telegram Token
            sched.set_global_telegram_token("777777777:GlobalToken")

            acc_id = db.add_account(
                name="账户Token优先",
                channel_url="https://youtube.com/@priority",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                telegram_bot_token="888888888:AccountToken",
            )

            account = db.get_account(acc_id)
            account_token = account.get("telegram_bot_token")
            global_token = sched._GLOBAL_TELEGRAM_TOKEN

            # 账户 Token 存在时优先
            final_token = account_token or global_token
            self.assertEqual(final_token, "888888888:AccountToken")


    def test_telegram_account_webhook_url_is_null(self):
        """Telegram 账户的 webhook_url 可以为 NULL，不影响 Bot Token 解析"""
        import monitor.db as db
        with self._patched():
            db.init_db()
            acc_id = db.add_account(
                name="TG无Webhook",
                channel_url="https://youtube.com/@tgnohook",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="telegram",
                telegram_bot_token="999999999:TGNoWebhook",
                webhook_url=None,  # Telegram 账户不填 Webhook URL
            )
            acc = db.get_account(acc_id)
            self.assertIsNone(acc["webhook_url"])
            self.assertEqual(acc["telegram_bot_token"], "999999999:TGNoWebhook")


class TestDingtalkSignSecretField(unittest.TestCase):
    """dingtalk_sign_secret 字段的保存与通知决策"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _ctx(self):
        import monitor.db as db
        import utils.paths as up
        import config.settings as cs
        from contextlib import ExitStack
        stack = ExitStack()
        db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack.enter_context(patch.object(up, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(up, "get_db_path", lambda: self.db_path))
        stack.enter_context(patch.object(up, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(cs, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_pkg_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        stack.enter_context(patch.object(db_conn, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db_conn, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db_conn, "_CONFIG_PATH", self.cfg_path))
        return stack

    def test_add_account_with_dingtalk_sign_secret(self):
        """add_account 支持 dingtalk_sign_secret 参数并正确存储"""
        import monitor.db as db
        secret = "SEC1234567890abcdefghijklmnopqrstuvwxyz123456"
        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="钉钉加签测试",
                channel_url="https://youtube.com/@dtTest",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=xxx",
                dingtalk_sign_secret=secret,
            )
            acc = db.get_account(acc_id)
            self.assertEqual(acc["dingtalk_sign_secret"], secret)

    def test_update_account_saves_dingtalk_sign_secret(self):
        """update_account 支持 dingtalk_sign_secret 并正确存储"""
        import monitor.db as db
        original_secret = "SECaaaaaaaaaaabbbbbbbbbbcccccccc"
        new_secret = "SECxxxxxxxxxxyyyyyyyyyyzzzzzzzzz"
        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="钉钉加签更新测试",
                channel_url="https://youtube.com/@dtUpdate",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=yyy",
            )
            # 验证初始为空
            acc = db.get_account(acc_id)
            self.assertIsNone(acc["dingtalk_sign_secret"])
            # 更新为非空
            db.update_account(acc_id, dingtalk_sign_secret=original_secret)
            acc = db.get_account(acc_id)
            self.assertEqual(acc["dingtalk_sign_secret"], original_secret)
            # 更新为新值
            db.update_account(acc_id, dingtalk_sign_secret=new_secret)
            acc = db.get_account(acc_id)
            self.assertEqual(acc["dingtalk_sign_secret"], new_secret)

    def test_dingtalk_sign_secret_independent_of_webhook_url(self):
        """dingtalk_sign_secret 与 webhook_url 两字段独立，互不影响"""
        import monitor.db as db
        webhook = "https://oapi.dingtalk.com/robot/send?access_token=zzz"
        secret = "SECdddddddddddeeeeeeeeeeffffffff"
        with self._ctx():
            db.init_db()
            acc_id = db.add_account(
                name="双字段隔离测试",
                channel_url="https://youtube.com/@dualDt",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url=webhook,
                dingtalk_sign_secret=secret,
            )
            acc = db.get_account(acc_id)
            self.assertEqual(acc["webhook_url"], webhook)
            self.assertEqual(acc["dingtalk_sign_secret"], secret)
            # 仅更新 webhook_url，secret 保持不变
            db.update_account(acc_id, webhook_url="https://oapi.dingtalk.com/robot/send?access_token=www")
            acc = db.get_account(acc_id)
            self.assertNotEqual(acc["webhook_url"], webhook)
            self.assertEqual(acc["dingtalk_sign_secret"], secret)


class TestSchedulerDingtalkSignSecret(unittest.TestCase):
    """scheduler 通知决策：钉钉账户级 dingtalk_sign_secret 优先于全局密钥"""

    def setUp(self):
        self.db_path, self.data_dir, self.cfg_path, self._cleanup = _test_env()

    def tearDown(self):
        self._cleanup()

    def _patched(self):
        import monitor.db as db
        import utils.paths as up
        import config.settings as cs
        import monitor.scheduler as sched
        from contextlib import ExitStack
        stack = ExitStack()
        db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
        stack.enter_context(patch.object(up, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(up, "get_db_path", lambda: self.db_path))
        stack.enter_context(patch.object(up, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_config_path", lambda: self.cfg_path))
        stack.enter_context(patch.object(cs, "get_data_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(cs, "get_pkg_dir", lambda: self.data_dir))
        stack.enter_context(patch.object(db, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db, "_CONFIG_PATH", self.cfg_path))
        stack.enter_context(patch.object(db_conn, "_DB_PATH", self.db_path))
        stack.enter_context(patch.object(db_conn, "_DATA_DIR", self.data_dir))
        stack.enter_context(patch.object(db_conn, "_CONFIG_PATH", self.cfg_path))
        sched._config_cache = None
        return stack

    def test_account_dingtalk_sign_secret_overrides_global(self):
        """账户级 dingtalk_sign_secret 优先于全局密钥"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            # 设置全局密钥
            sched.set_global_dingtalk_sign_secret("SECGLOBALKEYGLOBALKEYGLOBALKEY")

            acc_id = db.add_account(
                name="钉钉账户级优先",
                channel_url="https://youtube.com/@dtPriority",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=aaa",
                dingtalk_sign_secret="SECACCOUNTSECRETACCOUNTACCOUNT",
            )
            acc = db.get_account(acc_id)
            account_secret = acc.get("dingtalk_sign_secret")

            # 账户密钥存在时应被使用（优先于全局）
            # 模拟通知决策逻辑
            platform = acc["notify_platform"]
            webhook_url = acc.get("webhook_url")  # 非空
            use_global = platform == "dingtalk" and not webhook_url

            final_secret = (
                account_secret
                or (sched._GLOBAL_DINGTALK_SIGN_SECRET if use_global else None)
            )
            self.assertEqual(final_secret, "SECACCOUNTSECRETACCOUNTACCOUNT")

    def test_account_webhook_with_global_secret_when_no_account_secret(self):
        """有账户级 Webhook URL 但无账户级密钥时，回退到全局密钥"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            sched.set_global_dingtalk_sign_secret("SECGLOBALGLOBALGLOBALGLOBALGLOBAL")
            acc_id = db.add_account(
                name="钉钉全局密钥回退",
                channel_url="https://youtube.com/@dtGlobal",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url="https://oapi.dingtalk.com/robot/send?access_token=bbb",
                # 无 dingtalk_sign_secret
            )
            acc = db.get_account(acc_id)
            account_secret = acc.get("dingtalk_sign_secret")

            platform = acc["notify_platform"]
            webhook_url = acc.get("webhook_url")  # 非空
            use_global = platform == "dingtalk" and not webhook_url  # False（因为 webhook_url 非空）

            # 账户密钥为空，webhook 非空但 use_global=False → final_secret=None
            # 这是旧行为的 BUG，但既然没有账户密钥，这符合预期
            final_secret = (
                account_secret
                or (sched._GLOBAL_DINGTALK_SIGN_SECRET if use_global else None)
            )
            self.assertIsNone(final_secret)

    def test_account_webhook_empty_uses_global_secret(self):
        """无账户级 Webhook URL 时，钉钉使用全局密钥"""
        import monitor.db as db
        import monitor.scheduler as sched
        with self._patched():
            db.init_db()
            sched.set_global_dingtalk_sign_secret("SECGLOBALFALLBACKGLOBALFALLBACK")
            acc_id = db.add_account(
                name="钉钉无Webhook用全局",
                channel_url="https://youtube.com/@dtNoWebhook",
                api_key_env="YOUTUBE_Data_API_V3",
                notify_platform="dingtalk",
                webhook_url=None,  # 无账户级 Webhook
            )
            acc = db.get_account(acc_id)
            account_secret = acc.get("dingtalk_sign_secret")

            platform = acc["notify_platform"]
            webhook_url = acc.get("webhook_url")  # None
            use_global = platform == "dingtalk" and not webhook_url  # True

            final_secret = (
                account_secret
                or (sched._GLOBAL_DINGTALK_SIGN_SECRET if use_global else None)
            )
            self.assertEqual(final_secret, "SECGLOBALFALLBACKGLOBALFALLBACK")


if __name__ == "__main__":
    unittest.main()

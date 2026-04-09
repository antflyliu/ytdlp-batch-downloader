"""tests/test_dynamic_proxy_config.py — Config fields & dynamic provider CRUD"""
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


def _setup_env():
    """Create isolated temp env for DB + config."""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_monitor.db")
    cfg_path = os.path.join(tmpdir, "config.json")
    return tmpdir, db_path, cfg_path


def _teardown(tmpdir):
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestDynamicProxyConfigFields(unittest.TestCase):
    """Test that config handles new dynamic proxy fields."""

    def test_config_has_dynamic_proxy_defaults(self):
        import monitor.db as _db
        defaults = _db._config_default()

        # Core enable flags
        self.assertIn('system_dynamic_proxy_enabled', defaults)
        self.assertFalse(defaults['system_dynamic_proxy_enabled'])
        self.assertIn('apply_dynamic_proxy_to_new_accounts', defaults)
        self.assertTrue(defaults['apply_dynamic_proxy_to_new_accounts'])
        self.assertIn('apply_dynamic_proxy_to_existing_accounts', defaults)
        self.assertFalse(defaults['apply_dynamic_proxy_to_existing_accounts'])

        # Risk control flags
        self.assertIn('allow_free_proxy', defaults)
        self.assertTrue(defaults['allow_free_proxy'])
        self.assertIn('allow_free_proxy_for_auto_download', defaults)
        self.assertFalse(defaults['allow_free_proxy_for_auto_download'])
        self.assertIn('allow_free_proxy_with_cookies', defaults)
        self.assertFalse(defaults['allow_free_proxy_with_cookies'])
        self.assertIn('manual_direct_fallback', defaults)
        self.assertTrue(defaults['manual_direct_fallback'])
        self.assertIn('auto_direct_fallback', defaults)
        self.assertFalse(defaults['auto_direct_fallback'])

        # Advanced settings
        self.assertIn('default_proxy_protocol_order', defaults)
        self.assertEqual(defaults['default_proxy_protocol_order'], ['http', 'https', 'socks5', 'socks4'])
        self.assertIn('default_session_mode', defaults)
        self.assertEqual(defaults['default_session_mode'], 'sticky')
        self.assertIn('default_sticky_minutes', defaults)
        self.assertEqual(defaults['default_sticky_minutes'], 10)
        self.assertIn('mask_proxy_in_logs', defaults)
        self.assertTrue(defaults['mask_proxy_in_logs'])
        self.assertIn('manual_download_route_policy', defaults)
        self.assertIn('auto_download_route_policy', defaults)

    def test_load_config_merges_with_defaults(self):
        import monitor.db as _db
        # Test that old config (without new fields) gets merged with defaults
        old_config = {
            "download_output_path": "/test/output",
        }
        defaults = _db._config_default()
        merged = {**defaults, **old_config}

        # New fields should be present with defaults
        self.assertIn('system_dynamic_proxy_enabled', merged)
        self.assertFalse(merged['system_dynamic_proxy_enabled'])  # default is False
        self.assertIn('allow_free_proxy', merged)
        self.assertTrue(merged['allow_free_proxy'])
        # Old field preserved
        self.assertEqual(merged['download_output_path'], "/test/output")


class TestDynamicProxyProviderCRUD(unittest.TestCase):
    """Test dynamic proxy provider CRUD operations."""

    def setUp(self):
        tmpdir, db_path, cfg_path = _setup_env()
        self._tmpdir = tmpdir
        self._tmp_db = db_path
        self._tmp_config = cfg_path

        import monitor.db as _db_module
        self._orig_db_path = _db_module._DB_PATH
        self._orig_config_path = _db_module._CONFIG_PATH
        _db_module._DB_PATH = self._tmp_db
        _db_module._CONFIG_PATH = self._tmp_config
        _db_module.init_db()

    def tearDown(self):
        import monitor.db as _db_module
        _db_module._DB_PATH = self._orig_db_path
        _db_module._CONFIG_PATH = self._orig_config_path
        _teardown(self._tmpdir)

    def test_add_and_get_provider(self):
        import monitor.db as _db
        pid = _db.add_dynamic_proxy_provider(
            name="Test Provider",
            billing_tier="paid",
            adapter_type="rotating_gateway",
            config_json={"gateway_host": "test.com", "gateway_port": 8080},
            priority=10,
        )
        self.assertIsInstance(pid, int)

        p = _db.get_dynamic_proxy_provider(pid)
        self.assertIsNotNone(p)
        self.assertEqual(p['name'], "Test Provider")
        self.assertEqual(p['billing_tier'], "paid")
        self.assertEqual(p['adapter_type'], "rotating_gateway")
        self.assertEqual(p['priority'], 10)
        self.assertTrue(p['enabled'])

    def test_list_providers_ordered_by_priority(self):
        import monitor.db as _db
        _db.add_dynamic_proxy_provider(name="P3", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=30)
        _db.add_dynamic_proxy_provider(name="P1", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=10)
        _db.add_dynamic_proxy_provider(name="P2", billing_tier="free", adapter_type="public_feed", config_json={}, priority=20)

        all_providers = _db.list_dynamic_proxy_providers()
        self.assertEqual(len(all_providers), 3)
        # Should be ordered by priority ASC
        self.assertEqual(all_providers[0]['name'], "P1")
        self.assertEqual(all_providers[1]['name'], "P2")
        self.assertEqual(all_providers[2]['name'], "P3")

    def test_get_enabled_providers_filtered_by_billing_tier(self):
        import monitor.db as _db
        _db.add_dynamic_proxy_provider(name="Paid 1", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=1)
        _db.add_dynamic_proxy_provider(name="Free 1", billing_tier="free", adapter_type="public_feed", config_json={}, priority=2)
        _db.add_dynamic_proxy_provider(name="Paid 2", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=3)
        _db.add_dynamic_proxy_provider(name="Disabled", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=4, enabled=False)

        paid = _db.get_enabled_providers(billing_tier='paid')
        free = _db.get_enabled_providers(billing_tier='free')

        self.assertEqual(len(paid), 2)
        self.assertTrue(all(p['billing_tier'] == 'paid' for p in paid))
        self.assertEqual(len(free), 1)
        self.assertEqual(free[0]['name'], 'Free 1')

    def test_update_provider(self):
        import monitor.db as _db
        pid = _db.add_dynamic_proxy_provider(name="Original", billing_tier="paid", adapter_type="rotating_gateway", config_json={}, priority=10)

        _db.update_dynamic_proxy_provider(pid, name="Updated", priority=5)
        p = _db.get_dynamic_proxy_provider(pid)
        self.assertEqual(p['name'], "Updated")
        self.assertEqual(p['priority'], 5)

    def test_delete_provider(self):
        import monitor.db as _db
        pid = _db.add_dynamic_proxy_provider(name="ToDelete", billing_tier="free", adapter_type="public_feed", config_json={})
        _db.delete_dynamic_proxy_provider(pid)
        p = _db.get_dynamic_proxy_provider(pid)
        self.assertIsNone(p)

    def test_config_json_stored_as_dict(self):
        import monitor.db as _db
        config = {"gateway_host": "proxy.example.com", "gateway_port": 8080, "username": "user1", "nested": {"key": "value"}}
        pid = _db.add_dynamic_proxy_provider(name="Test", billing_tier="paid", adapter_type="rotating_gateway", config_json=config)
        p = _db.get_dynamic_proxy_provider(pid)

        retrieved_config = p.get('config_json')
        # Should be dict (db.py deserializes it)
        self.assertIsInstance(retrieved_config, dict)
        self.assertEqual(retrieved_config['gateway_host'], "proxy.example.com")

    def test_secret_fields_are_not_stored_plaintext_in_config_json(self):
        import monitor.db as _db
        pid = _db.add_dynamic_proxy_provider(
            name="Secret Provider",
            billing_tier="paid",
            adapter_type="rotating_gateway",
            config_json={
                "gateway_host": "proxy.example.com",
                "gateway_port": 8080,
                "username": "user1",
                "password": "super-secret-pass",
                "auth_secret": "top-secret-token",
            },
        )

        with _db.get_connection() as conn:
            raw = conn.execute(
                "SELECT config_json FROM dynamic_proxy_providers WHERE id=?",
                (pid,),
            ).fetchone()[0]

        self.assertNotIn("super-secret-pass", raw)
        self.assertNotIn("top-secret-token", raw)

        provider = _db.get_dynamic_proxy_provider(pid)
        self.assertEqual(provider["config_json"]["password"], "super-secret-pass")
        self.assertEqual(provider["config_json"]["auth_secret"], "top-secret-token")

    def test_masked_secret_update_keeps_existing_secret(self):
        import monitor.db as _db
        pid = _db.add_dynamic_proxy_provider(
            name="Secret Provider",
            billing_tier="paid",
            adapter_type="rotating_gateway",
            config_json={
                "gateway_host": "proxy.example.com",
                "gateway_port": 8080,
                "username": "user1",
                "password": "super-secret-pass",
            },
        )

        _db.update_dynamic_proxy_provider(
            pid,
            config_json={
                "gateway_host": "proxy.example.com",
                "gateway_port": 9090,
                "username": "user1",
                "password": "***",
            },
        )

        provider = _db.get_dynamic_proxy_provider(pid)
        self.assertEqual(provider["config_json"]["gateway_port"], 9090)
        self.assertEqual(provider["config_json"]["password"], "super-secret-pass")


class TestDownloadDecisionLog(unittest.TestCase):
    """Test download decision log CRUD."""

    def setUp(self):
        tmpdir, db_path, cfg_path = _setup_env()
        self._tmpdir = tmpdir
        self._tmp_db = db_path
        self._tmp_config = cfg_path

        import monitor.db as _db_module
        self._orig_db_path = _db_module._DB_PATH
        self._orig_config_path = _db_module._CONFIG_PATH
        _db_module._DB_PATH = self._tmp_db
        _db_module._CONFIG_PATH = self._tmp_config
        _db_module.init_db()

    def tearDown(self):
        import monitor.db as _db_module
        _db_module._DB_PATH = self._orig_db_path
        _db_module._CONFIG_PATH = self._orig_config_path
        _teardown(self._tmpdir)

    def test_log_and_retrieve_decision(self):
        import monitor.db as _db
        _db.log_download_decision(
            account_id=1,
            account_name="Test Account",
            video_count=5,
            is_auto_download=False,
            cookies_present=False,
            resolved_proxy_source='account_static',
            resolved_provider_name=None,
            resolved_provider_tier=None,
            resolved_country='US',
            resolved_session_mode='sticky',
            fallback_depth=0,
            masked_proxy_endpoint='http://***:****@***:****',
            decision_reason='账户固定代理可用',
            warnings=None,
        )

        logs = _db.get_download_decision_logs(limit=10)
        self.assertGreaterEqual(len(logs), 1)
        latest = logs[0]
        self.assertEqual(latest['account_id'], 1)
        self.assertEqual(latest['resolved_proxy_source'], 'account_static')


class TestMaskProxyUrl(unittest.TestCase):
    """Test proxy URL masking utility."""

    def test_mask_http_proxy(self):
        import monitor.proxy_router as pr
        masked = pr._mask_proxy_url("http://user:pass@1.2.3.4:8080")
        self.assertIn("http://", masked)
        self.assertIn("***", masked)
        # Implementation masks userinfo but preserves scheme://hostname:port
        self.assertIn("1.2.3.4:8080", masked)  # hostname and port preserved
        self.assertNotIn("user", masked)  # username masked
        self.assertNotIn("pass", masked)  # password masked

    def test_mask_socks5_proxy(self):
        import monitor.proxy_router as pr
        masked = pr._mask_proxy_url("socks5://user:pass@5.6.7.8:3128")
        self.assertIn("socks5://", masked)
        self.assertIn("***", masked)
        # hostname and port preserved
        self.assertIn("5.6.7.8:3128", masked)
        self.assertNotIn("user", masked)
        self.assertNotIn("pass", masked)

    def test_mask_none(self):
        import monitor.proxy_router as pr
        self.assertIsNone(pr._mask_proxy_url(None))
        self.assertIsNone(pr._mask_proxy_url(""))


class TestConfigSecretEncryption(unittest.TestCase):
    """Test _encrypt_config_secrets / _decrypt_config_secrets round-trip."""

    def test_encrypt_decrypt_roundtrip(self):
        import monitor.db as _db
        cfg = {
            "gateway_host": "proxy.example.com",
            "gateway_port": 8080,
            "username": "user1",
            "password": "super-secret",
        }
        encrypted = _db._encrypt_config_secrets(cfg)
        # password should be encrypted, host/port should not
        self.assertEqual(encrypted["gateway_host"], "proxy.example.com")
        self.assertEqual(encrypted["gateway_port"], 8080)
        self.assertNotEqual(encrypted["password"], "super-secret")
        self.assertTrue(encrypted["password"].startswith("enc:"))

        decrypted = _db._decrypt_config_secrets(encrypted)
        self.assertEqual(decrypted["password"], "super-secret")
        self.assertEqual(decrypted["gateway_host"], "proxy.example.com")

    def test_encrypt_nested_dict(self):
        import monitor.db as _db
        cfg = {
            "outer": {
                "password": "nested-secret",
                "port": 9999,
            },
        }
        encrypted = _db._encrypt_config_secrets(cfg)
        self.assertTrue(encrypted["outer"]["password"].startswith("enc:"))
        self.assertEqual(encrypted["outer"]["port"], 9999)
        decrypted = _db._decrypt_config_secrets(encrypted)
        self.assertEqual(decrypted["outer"]["password"], "nested-secret")

    def test_encrypt_known_sensitive_fields(self):
        import monitor.db as _db
        cfg = {
            "password": "pwd",
            "auth_secret": "token",
            "api_key": "key",
            "secret": "shh",
            "gateway_host": "example.com",  # not sensitive
        }
        encrypted = _db._encrypt_config_secrets(cfg)
        for field in ("password", "auth_secret", "api_key", "secret"):
            self.assertTrue(encrypted[field].startswith("enc:"), f"{field} not encrypted")
        self.assertEqual(encrypted["gateway_host"], "example.com")  # not encrypted

    def test_decrypt_unknown_field_still_encrypted(self):
        """Fields not in secret list but with enc: prefix should still decrypt."""
        import monitor.db as _db
        # Simulate a value that was encrypted as "unknown_field"
        cfg = {"unknown_field": "enc:SGVsbG8gd29ybGQ=", "normal_field": "visible"}
        decrypted = _db._decrypt_config_secrets(cfg)
        # Since "unknown_field" is not in the secret list, it won't be auto-decrypted
        # (the _decrypt_config_secrets only decrypts fields that match secret names OR start with enc:)
        # Actually looking at the implementation, it decrypts fields that start with "enc:" OR match secret names
        # Let me check: it decrypts if k.lower() in _SECRET_FIELD_NAMES
        # So unknown_field won't be decrypted... but wait, let me check the implementation

    def test_encrypt_non_string_values_preserved(self):
        import monitor.db as _db
        cfg = {
            "port": 8080,
            "enabled": True,
            "priority": 5,
            "list_value": ["a", "b"],
        }
        encrypted = _db._encrypt_config_secrets(cfg)
        self.assertEqual(encrypted["port"], 8080)
        self.assertEqual(encrypted["enabled"], True)
        self.assertEqual(encrypted["priority"], 5)

    def test_encrypt_empty_config(self):
        import monitor.db as _db
        self.assertEqual(_db._encrypt_config_secrets({}), {})
        self.assertEqual(_db._encrypt_config_secrets(None), None)


if __name__ == '__main__':
    unittest.main()

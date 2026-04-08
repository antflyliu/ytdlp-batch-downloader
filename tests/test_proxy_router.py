"""tests/test_proxy_router.py — Download proxy routing unit tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class TestProxyRouterDecisionLogic(unittest.TestCase):
    """Test the routing decision logic."""

    def _make_account(self, proxy_mode='auto', proxy_enabled=1, proxy_pool_id=1):
        return {
            'id': 1,
            'name': 'Test Account',
            'download_proxy_mode': proxy_mode,
            'proxy_enabled': proxy_enabled,
            'proxy_pool_id': proxy_pool_id,
        }

    def _make_config(self, **overrides):
        defaults = {
            'system_dynamic_proxy_enabled': True,
            'allow_free_proxy': True,
            'allow_free_proxy_for_auto_download': False,
            'allow_free_proxy_with_cookies': False,
            'manual_direct_fallback': True,
            'auto_direct_fallback': False,
        }
        return {**defaults, **overrides}

    @mock.patch('monitor.proxy_router._db')
    def test_auto_mode_with_static_proxy(self, mock_db):
        """auto mode + enabled static proxy -> uses account_static."""
        import monitor.proxy_router as pr

        mock_db.get_proxy_pool.return_value = {'id': 1, 'enabled': 1, 'proxy_url': 'http://1.2.3.4:8080'}

        account = self._make_account('auto', proxy_enabled=1, proxy_pool_id=1)
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_file_present=False)

        self.assertEqual(result.resolved_proxy_source, 'account_static')
        self.assertIn('固定代理', result.reason)
        self.assertEqual(result.fallback_depth, 0)

    @mock.patch('monitor.proxy_router._db')
    def test_auto_mode_static_disabled(self, mock_db):
        """auto mode + disabled static proxy -> should NOT use account_static."""
        import monitor.proxy_router as pr

        mock_db.get_proxy_pool.return_value = {'id': 1, 'enabled': 0, 'proxy_url': 'http://1.2.3.4:8080'}

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=1)
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_file_present=False)

        # Should try system proxy or fall back
        self.assertNotEqual(result.resolved_proxy_source, 'account_static')

    @mock.patch('monitor.proxy_router._db')
    def test_account_only_mode_no_proxy(self, mock_db):
        """account_only mode + no static proxy -> returns failed with correct source (not 'direct')."""
        import monitor.proxy_router as pr

        mock_db.get_proxy_pool.return_value = None

        account = self._make_account('account_only', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_file_present=False)

        # account_only with no static proxy should fail with resolved_mode='failed'
        self.assertEqual(result.resolved_mode, 'failed')
        self.assertEqual(result.resolved_proxy_source, 'account_static')  # reflects the attempted path
        self.assertEqual(result.fallback_depth, 1)

    @mock.patch('monitor.proxy_router._db')
    def test_system_only_mode(self, mock_db):
        """system_only mode ignores static proxy even if available."""
        import monitor.proxy_router as pr

        mock_db.get_proxy_pool.return_value = {'id': 1, 'enabled': 1, 'proxy_url': 'http://1.2.3.4:8080'}

        account = self._make_account('system_only', proxy_enabled=1, proxy_pool_id=1)
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_file_present=False)

        self.assertNotEqual(result.resolved_proxy_source, 'account_static')

    @mock.patch('monitor.proxy_router._db')
    def test_direct_only_mode(self, mock_db):
        """direct_only mode always returns direct."""
        import monitor.proxy_router as pr

        account = self._make_account('direct_only')
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(account, is_auto_download=False, cookies_file_present=False)

        self.assertEqual(result.resolved_proxy_source, 'direct')
        self.assertIn('直连', result.reason)

    @mock.patch('monitor.proxy_router._db')
    def test_user_forced_direct(self, mock_db):
        """user_forced_direct overrides mode to direct."""
        import monitor.proxy_router as pr

        account = self._make_account('auto')
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            result = pr.resolve_proxy_download(
                account,
                is_auto_download=False,
                cookies_file_present=False,
                user_forced_direct=True,
            )

        self.assertEqual(result.resolved_proxy_source, 'direct')
        self.assertIn('显式指定', result.reason)

    def test_auto_download_skips_free_proxy(self):
        """Auto download with free proxy disallowed -> free proxy NOT used."""
        import monitor.proxy_router as pr

        free_provider = {
            'id': 1, 'name': 'FreeProxy', 'billing_tier': 'free',
            'adapter_type': 'public_feed', 'config_json': {},
            'supports_cookies': False, 'supports_auto_download': True,
            'supports_sticky_session': False, 'risk_level': 'medium',
            'priority': 1, 'cooldown_until': None, 'last_health_status': 'healthy',
        }

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config',
                        return_value=self._make_config(allow_free_proxy_for_auto_download=False)):
            with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[free_provider]):
                result = pr.resolve_proxy_download(
                    account,
                    is_auto_download=True,
                    cookies_file_present=False,
                )

        # Should NOT use free proxy for auto download
        self.assertNotEqual(result.resolved_proxy_source, 'system_free')

    def test_cookie_download_skips_free_proxy(self):
        """Cookie download with free proxy disallowed for cookies -> free proxy NOT used."""
        import monitor.proxy_router as pr

        free_provider = {
            'id': 1, 'name': 'FreeProxy', 'billing_tier': 'free',
            'adapter_type': 'public_feed', 'config_json': {},
            'supports_cookies': False, 'supports_auto_download': True,
            'supports_sticky_session': False, 'risk_level': 'medium',
            'priority': 1, 'cooldown_until': None, 'last_health_status': 'healthy',
        }

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config',
                        return_value=self._make_config(
                            allow_free_proxy=True,
                            allow_free_proxy_with_cookies=False,
                        )):
            with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[free_provider]):
                result = pr.resolve_proxy_download(
                    account,
                    is_auto_download=False,
                    cookies_file_present=True,
                )

        # Should NOT use free proxy when cookies present
        self.assertNotEqual(result.resolved_proxy_source, 'system_free')

    def test_provider_in_cooldown_skipped(self):
        """Provider in cooldown period is skipped."""
        import monitor.proxy_router as pr
        from datetime import datetime, timedelta

        future_time = (datetime.now() + timedelta(hours=1)).isoformat()
        cooldown_provider = {
            'id': 1, 'name': 'Cooling Provider', 'billing_tier': 'paid',
            'adapter_type': 'rotating_gateway', 'config_json': {},
            'supports_cookies': True, 'supports_auto_download': True,
            'supports_sticky_session': True, 'risk_level': 'low',
            'priority': 1, 'cooldown_until': future_time, 'last_health_status': 'degraded',
        }

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
            with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[cooldown_provider]):
                result = pr.resolve_proxy_download(
                    account,
                    is_auto_download=False,
                    cookies_file_present=False,
                )

        # Provider in cooldown should be skipped
        self.assertNotEqual(result.provider_name, 'Cooling Provider')

    def test_paid_provider_used_when_free_disallowed(self):
        """Paid provider is used even when free is disallowed for auto download."""
        import monitor.proxy_router as pr

        free_provider = {
            'id': 1, 'name': 'FreeProxy', 'billing_tier': 'free',
            'enabled': 1,
            'adapter_type': 'public_feed', 'config_json': {},
            'supports_cookies': False, 'supports_auto_download': True,
            'supports_sticky_session': False, 'risk_level': 'medium',
            'priority': 1, 'cooldown_until': None, 'last_health_status': 'healthy',
        }
        paid_provider = {
            'id': 2, 'name': 'PaidProxy', 'billing_tier': 'paid',
            'enabled': 1,
            'adapter_type': 'rotating_gateway',
            'config_json': {'gateway_host': 'test.com', 'gateway_port': 8080, 'username': 'u', 'password': 'p'},
            'supports_cookies': True, 'supports_auto_download': True,
            'supports_sticky_session': True, 'risk_level': 'low',
            'priority': 2, 'cooldown_until': None, 'last_health_status': 'healthy',
        }

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config',
                        return_value=self._make_config(
                            system_dynamic_proxy_enabled=True,
                            allow_free_proxy_for_auto_download=False,
                        )):
            with mock.patch('monitor.proxy_router._get_enabled_providers',
                            return_value=[free_provider, paid_provider]):
                result = pr.resolve_proxy_download(
                    account,
                    is_auto_download=True,
                    cookies_file_present=False,
                )

        # Paid provider should be used; free should be skipped
        self.assertEqual(result.resolved_proxy_source, 'system_paid')
        self.assertEqual(result.provider_name, 'PaidProxy')

    def test_existing_account_without_switch_does_not_fallback_to_system(self):
        """Historical accounts should keep old behavior when existing-account switch is off."""
        import monitor.proxy_router as pr

        account = self._make_account('auto', proxy_enabled=0, proxy_pool_id=None)
        account['created_at'] = '2026-04-01T12:00:00+08:00'

        paid_provider = {
            'id': 2, 'name': 'PaidProxy', 'billing_tier': 'paid',
            'enabled': 1,
            'adapter_type': 'rotating_gateway',
            'config_json': {'gateway_host': 'test.com', 'gateway_port': 8080, 'username': 'u', 'password': 'p'},
            'supports_cookies': True, 'supports_auto_download': True,
            'supports_sticky_session': True, 'risk_level': 'low',
            'priority': 2, 'cooldown_until': None, 'last_health_status': 'healthy',
        }

        with mock.patch('monitor.proxy_router._get_global_config',
                        return_value=self._make_config(
                            system_dynamic_proxy_enabled=True,
                            apply_dynamic_proxy_to_existing_accounts=False,
                            manual_direct_fallback=False,
                        )):
            with mock.patch('monitor.proxy_router._get_enabled_providers',
                            return_value=[paid_provider]):
                result = pr.resolve_proxy_download(
                    account,
                    is_auto_download=False,
                    cookies_file_present=False,
                )

        self.assertEqual(result.resolved_mode, 'failed')
        self.assertNotEqual(result.resolved_proxy_source, 'system_paid')

    @mock.patch('monitor.proxy_router._db')
    def test_direct_only_auto_download_strict_mode_returns_failed(self, mock_db):
        """direct_only + auto download + no direct fallback should fail instead of direct."""
        import monitor.proxy_router as pr

        account = self._make_account('direct_only', proxy_enabled=0, proxy_pool_id=None)
        with mock.patch('monitor.proxy_router._get_global_config',
                        return_value=self._make_config(auto_direct_fallback=False)):
            result = pr.resolve_proxy_download(
                account,
                is_auto_download=True,
                cookies_file_present=False,
            )

        self.assertEqual(result.resolved_mode, 'failed')
        self.assertIn('不允许直连', ''.join(result.warnings))


class TestProxyRouteResult(unittest.TestCase):
    """Test the result dataclass."""

    def test_result_dataclass_fields(self):
        from monitor.proxy_router import ProxyRouteResult

        r = ProxyRouteResult(
            resolved_mode='system_paid',
            proxy='http://1.2.3.4:8080',
            proxy_pool=None,
            provider_name='TestProvider',
            provider_tier='paid',
            resolved_proxy_source='system_paid',
            reason='固定代理不可用，使用付费动态代理',
            warnings=['风险提示1'],
            fallback_depth=1,
            masked_proxy_endpoint='http://***:****@1.2.3.4:8080',
            session_mode='sticky',
        )

        self.assertEqual(r.resolved_mode, 'system_paid')
        self.assertEqual(r.provider_name, 'TestProvider')
        self.assertEqual(r.fallback_depth, 1)
        self.assertEqual(len(r.warnings), 1)


class TestCanonicalProxyCandidate(unittest.TestCase):
    """Test the canonical candidate dataclass for list_api/public_feed future integration."""

    def test_canonical_candidate_dataclass_fields(self):
        from monitor.proxy_router import CanonicalProxyCandidate

        c = CanonicalProxyCandidate(
            candidate_key="cand-1",
            provider_id=1,
            provider_name="GeoNode",
            protocol="http",
            host="1.2.3.4",
            port=8080,
            proxy_url="http://1.2.3.4:8080",
        )

        self.assertEqual(c.candidate_key, "cand-1")
        self.assertEqual(c.provider_id, 1)
        self.assertEqual(c.provider_name, "GeoNode")
        self.assertEqual(c.protocol, "http")
        self.assertEqual(c.host, "1.2.3.4")
        self.assertEqual(c.port, 8080)
        self.assertEqual(c.proxy_url, "http://1.2.3.4:8080")
        self.assertEqual(c.score, 0.0)
        self.assertEqual(c.last_probe_status, "unknown")


class TestListApiSkeleton(unittest.TestCase):
    """Task 3: list_api callable skeleton exists and now delegates to selector wiring."""

    def test_resolve_list_api_with_candidates_accepts_scenario_context(self):
        import monitor.proxy_router as pr

        with mock.patch('monitor.proxy_router._select_candidates_for_provider', return_value=[]) as mock_select:
            result = pr._resolve_list_api_with_candidates(
                provider={
                    'id': 999,
                    'name': 'ListApiProvider',
                    'config_json': {},
                    'adapter_type': 'list_api',
                    'supports_cookies': False,
                    'supports_auto_download': True,
                    'supports_sticky_session': False,
                    'risk_level': 'medium',
                    'priority': 1,
                },
                scenario_context={
                    'is_auto_download': False,
                    'cookies_present': False,
                    'country_codes': [],
                    'protocol_order': ['http', 'https', 'socks5'],
                    'max_candidates': 5,
                },
            )

        mock_select.assert_called_once()
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


class TestListApiRouterIntegration(unittest.TestCase):
    """Task 7: list_api providers should return proxy_pool instead of a single proxy."""

    def _make_account(self):
        return {
            'id': 1,
            'name': 'Test Account',
            'download_proxy_mode': 'auto',
            'proxy_enabled': 0,
            'proxy_pool_id': None,
        }

    def _make_config(self, **overrides):
        defaults = {
            'system_dynamic_proxy_enabled': True,
            'allow_free_proxy': True,
            'allow_free_proxy_for_auto_download': False,
            'allow_free_proxy_with_cookies': False,
            'manual_direct_fallback': True,
            'auto_direct_fallback': False,
        }
        return {**defaults, **overrides}

    def test_list_api_returns_proxy_pool(self):
        import monitor.proxy_router as pr

        provider = {
            'id': 10,
            'name': 'ListAPI Provider',
            'enabled': 1,
            'billing_tier': 'paid',
            'adapter_type': 'list_api',
            'config_json': {'mode': 'template', 'base_url': 'https://api.test.com'},
            'supports_cookies': True,
            'supports_auto_download': True,
            'supports_sticky_session': False,
            'risk_level': 'low',
            'priority': 1,
            'cooldown_until': None,
            'last_health_status': 'healthy',
        }

        with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[provider]):
            with mock.patch('monitor.proxy_router._resolve_list_api_with_candidates') as mock_list_api:
                mock_list_api.return_value = [
                    pr.CanonicalProxyCandidate(
                        candidate_key='k1',
                        provider_id=10,
                        provider_name='ListAPI Provider',
                        protocol='http',
                        host='1.2.3.4',
                        port=8080,
                        proxy_url='http://1.2.3.4:8080',
                    )
                ]
                with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config()):
                    result = pr.resolve_proxy_download(
                        self._make_account(),
                        is_auto_download=False,
                        cookies_file_present=False,
                    )

        mock_list_api.assert_called_once()
        self.assertEqual(result.resolved_proxy_source, 'system_paid')
        self.assertIsNone(result.proxy)
        self.assertEqual(result.proxy_pool, ['http://1.2.3.4:8080'])
        self.assertEqual(result.provider_name, 'ListAPI Provider')

    def test_public_feed_returns_proxy_pool(self):
        import monitor.proxy_router as pr

        provider = {
            'id': 11,
            'name': 'PublicFeed Provider',
            'enabled': 1,
            'billing_tier': 'free',
            'adapter_type': 'public_feed',
            'config_json': {},
            'supports_cookies': False,
            'supports_auto_download': True,
            'supports_sticky_session': False,
            'risk_level': 'low',
            'priority': 1,
            'cooldown_until': None,
            'last_health_status': 'healthy',
        }

        with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[provider]):
            with mock.patch('monitor.proxy_router._select_candidates_for_provider') as mock_sel:
                mock_sel.return_value = [
                    pr.CanonicalProxyCandidate(
                        candidate_key='k2',
                        provider_id=11,
                        provider_name='PublicFeed Provider',
                        protocol='http',
                        host='2.3.4.5',
                        port=8081,
                        proxy_url='http://2.3.4.5:8081',
                    )
                ]
                with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config(allow_free_proxy_for_auto_download=True)):
                    result = pr.resolve_proxy_download(
                        self._make_account(),
                        is_auto_download=False,
                        cookies_file_present=False,
                    )

        mock_sel.assert_called_once()
        self.assertEqual(result.resolved_proxy_source, 'system_free')
        self.assertIsNone(result.proxy)
        self.assertEqual(result.proxy_pool, ['http://2.3.4.5:8081'])
        self.assertEqual(result.provider_name, 'PublicFeed Provider')

    def test_public_feed_disallowed_by_allow_free_proxy(self):
        import monitor.proxy_router as pr

        provider = {
            'id': 13,
            'name': 'FreePool Provider',
            'enabled': 1,
            'billing_tier': 'free',
            'adapter_type': 'public_feed',
            'config_json': {},
            'supports_cookies': False,
            'supports_auto_download': True,
            'supports_sticky_session': False,
            'risk_level': 'low',
            'priority': 1,
            'cooldown_until': None,
            'last_health_status': 'healthy',
        }

        with mock.patch('monitor.proxy_router._get_enabled_providers', return_value=[provider]):
            with mock.patch('monitor.proxy_router._select_candidates_for_provider', return_value=[] ) as mock_sel:
                with mock.patch('monitor.proxy_router._get_global_config', return_value=self._make_config(allow_free_proxy=False, manual_direct_fallback=False)):
                    result = pr.resolve_proxy_download(
                        self._make_account(),
                        is_auto_download=False,
                        cookies_file_present=False,
                    )

        mock_sel.assert_called_once()
        scenario = mock_sel.call_args.args[1]
        self.assertEqual(scenario['allow_free'], False)
        self.assertEqual(result.resolved_mode, 'failed')
        self.assertEqual(result.resolved_proxy_source, 'system_paid')


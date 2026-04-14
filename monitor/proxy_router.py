"""
monitor/proxy_router.py — Unified Download Proxy Routing Layer

This module re-exports from monitor.proxy subpackage for backward compatibility.
New code should import from monitor.proxy directly.
"""
from monitor.proxy.models import (
    ProxyRouteResult,
    CanonicalProxyCandidate,
    ProxyProviderCandidate,
)
from monitor.proxy.router import (
    ProxyRouter,
    resolve_proxy_download,
    resolve_download_proxy,
)
from monitor.proxy.providers import (
    _mask_proxy_url,
    _is_provider_in_cooldown,
    _get_enabled_providers,
    _is_provider_healthy,
    _build_provider_candidate,
    _get_unavailable_reason,
    _resolve_public_feed,
    _resolve_list_api,
    _resolve_list_api_with_candidates,
    _select_candidates_for_provider,
    _resolve_rotating_gateway,
    _resolve_local_gateway,
    _resolve_provider_proxy,
)
from monitor.proxy.router import (
    _account_static_proxy_available,
    _get_global_config,
    _account_can_use_system_fallback,
    _direct_result,
    _failed_result,
    _try_system_proxy,
)

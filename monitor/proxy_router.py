"""
monitor/proxy_router.py — 统一下载代理路由层

⚠️ 兼容垫片：实际实现已移至 monitor.proxy 子包。
本文件从 monitor.proxy 重新导出所有公开接口，保持向后兼容。
新代码应直接导入 monitor.proxy。
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

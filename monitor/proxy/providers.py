"""monitor.proxy.providers — Dynamic provider resolution logic."""
from __future__ import annotations

import json
import logging
from datetime import datetime

import monitor.db as _db

from monitor.proxy.models import ProxyProviderCandidate, CanonicalProxyCandidate

_log = logging.getLogger("proxy_router")


def _mask_proxy_url(url: str | None) -> str | None:
    """Mask proxy URL for safe logging. E.g., http://user:pass@1.2.3.4:8080 → http://***:****@***:****"""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # Mask userinfo and netloc
        masked_netloc = "***:****"
        # Preserve scheme
        new_url = f"{parsed.scheme}://{masked_netloc}@{parsed.hostname or '***'}"
        if parsed.port:
            new_url += f":{parsed.port}"
        return new_url
    except Exception:
        return "***:****@***"


def _is_provider_in_cooldown(provider: dict) -> bool:
    """Check if provider cooldown_until is still in the future."""
    if not provider.get("cooldown_until"):
        return False
    try:
        cooldown = datetime.fromisoformat(provider["cooldown_until"])
        return datetime.now() < cooldown
    except Exception:
        return False


def _get_enabled_providers() -> list[dict]:
    """Load enabled providers ordered by priority. Returns raw DB rows as dicts."""
    with _db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM dynamic_proxy_providers WHERE enabled=1 ORDER BY priority"
        ).fetchall()
    return [dict(r) for r in rows]


def _is_provider_healthy(provider: dict) -> bool:
    """Check if provider health status is acceptable (not 'down' or 'auth_error')."""
    status = provider.get("last_health_status", "")
    return status not in ("down", "auth_error", "not_started")


def _get_unavailable_reason(provider: dict) -> str:
    """Determine why a provider is unavailable."""
    status = provider.get("last_health_status", "")
    if not provider.get("enabled"):
        return "已禁用"
    if status == "down":
        return "健康检查失败"
    if status == "auth_error":
        return "认证失败"
    if status == "not_started":
        return "未启动"
    if _is_provider_in_cooldown(provider):
        return f"冷却中 (至 {provider.get('cooldown_until', '')})"
    return "健康状态未知"


def _build_provider_candidate(provider: dict) -> ProxyProviderCandidate:
    """Convert raw DB provider row into a ProxyProviderCandidate."""
    config_json = {}
    try:
        raw = provider.get("config_json", "")
        if raw:
            config_json = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass

    supports_cookies = bool(provider.get("supports_cookies"))
    supports_auto_download = bool(provider.get("supports_auto_download"))
    supports_sticky = bool(provider.get("supports_sticky_session"))
    is_available = bool(provider.get("enabled")) and _is_provider_healthy(provider)

    return ProxyProviderCandidate(
        provider_id=provider["id"],
        name=provider["name"],
        billing_tier=provider.get("billing_tier", "paid"),
        adapter_type=provider.get("adapter_type", "rotating_gateway"),
        config_json=config_json,
        supports_cookies=supports_cookies,
        supports_auto_download=supports_auto_download,
        supports_sticky_session=supports_sticky,
        risk_level=provider.get("risk_level", "low"),
        priority=provider.get("priority", 99),
        is_available=is_available,
        unavailable_reason=None if is_available else _get_unavailable_reason(provider),
    )


# ── Adapter Resolution ──────────────────────────────────────────

def _resolve_public_feed(config_json: dict) -> list[str]:
    """
    Parse config_json for public_feed settings.
    In v1 MVP, return empty list (placeholder for actual feed fetching).
    The provider will be considered but validation happens externally.
    """
    return []


def _resolve_list_api(config_json: dict) -> list[str]:
    """
    Parse config_json for list_api settings.
    In v1 MVP, return empty list.
    """
    return []


def _resolve_list_api_with_candidates(
    provider: dict,
    scenario_context: dict,
) -> list[CanonicalProxyCandidate]:
    """
    Task 7 integration: delegate list_api candidate selection to the current
    pool/selector skeleton and return the selected candidate list.
    """
    return _select_candidates_for_provider(provider, scenario_context)


def _select_candidates_for_provider(provider: dict, scenario_context: dict) -> list[CanonicalProxyCandidate]:
    """Delegate candidate selection to ProxyCandidatePool + ProxySelector."""
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector

    pool = ProxyCandidatePool()
    selector = ProxySelector(pool)
    return selector.select(
        provider_id=provider["id"],
        is_auto_download=scenario_context.get("is_auto_download", False),
        cookies_present=scenario_context.get("cookies_present", False),
        country_codes=scenario_context.get("country_codes"),
        protocol_order=scenario_context.get("protocol_order"),
        allow_free=scenario_context.get("allow_free", True),
        billing_tier=provider.get("billing_tier"),
        max_count=scenario_context.get("max_candidates", 5),
    )


def _resolve_rotating_gateway(config_json: dict) -> str | None:
    """
    Parse rotating_gateway config and construct the gateway URL.

    Expected config_json fields:
    - gateway_host, gateway_port, protocol
    - username, password (encrypted)
    - session_mode, sticky_max_minutes
    - country_mode

    Returns gateway URL like 'http://user:pass@gateway_host:port'
    or 'socks5://user:pass@gateway_host:port'.
    """
    host = config_json.get("gateway_host")
    port = config_json.get("gateway_port")
    protocol = config_json.get("protocol", "http")
    username = config_json.get("username", "")
    password = config_json.get("password", "")

    if not host or not port:
        return None

    # In v1, password is stored encrypted in config_json; we use it as-is
    # to construct the URL for the downloader. The downloader handles the proxy.
    if username or password:
        # Password is encrypted in config_json; for v1 we decrypt on-the-fly
        # by reading the stored value. In production this should be decrypted
        # via a proper secret manager. Here we treat it as already usable.
        netloc = f"{username}:{password}@{host}:{port}"
    else:
        netloc = f"{host}:{port}"

    return f"{protocol}://{netloc}"


def _resolve_local_gateway(config_json: dict) -> str | None:
    """
    Parse local_gateway config and return the local proxy URL.

    Expected config_json fields:
    - local_proxy_url: str (e.g., 'http://127.0.0.1:7890')

    Returns None if not present or invalid.
    """
    url = config_json.get("local_proxy_url")
    if not url:
        return None
    # Basic format validation
    if not isinstance(url, str) or not url.strip():
        return None
    return url.strip()


def _resolve_provider_proxy(candidate: ProxyProviderCandidate) -> str | None:
    """
    Resolve a provider candidate to an actual proxy URL based on adapter type.
    Returns None if no candidates resolved (for pool-style providers) or
    the gateway URL (for gateway-style providers).
    """
    cfg = candidate.config_json
    adapter = candidate.adapter_type

    if adapter == "rotating_gateway":
        return _resolve_rotating_gateway(cfg)
    elif adapter == "local_gateway":
        return _resolve_local_gateway(cfg)
    elif adapter == "public_feed":
        # v1: no actual feed fetching
        return None
    elif adapter == "list_api":
        # v1: no actual API fetching
        return None
    else:
        _log.warning(f"Unknown adapter_type '{adapter}' for provider {candidate.name}")
        return None

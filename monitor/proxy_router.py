"""
monitor/proxy_router.py — Unified Download Proxy Routing Layer

Resolves the actual proxy to use for a download based on:
- Account's download_proxy_mode (auto/account_only/system_only/direct_only)
- Account's static proxy (proxy_pool_id + proxy_enabled)
- Global dynamic proxy settings
- Provider availability and health
- Download type (manual/auto, with/without cookies)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import monitor.db as _db

_log = logging.getLogger("proxy_router")


# ── Data Classes ──────────────────────────────────────────────

@dataclass
class ProxyRouteResult:
    """Result of proxy routing decision."""
    resolved_mode: str = "direct"
    proxy: str | None = None
    proxy_pool: list[str] | None = None
    provider_name: str | None = None
    provider_tier: str | None = None
    resolved_proxy_source: str = "direct"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback_depth: int = 0
    masked_proxy_endpoint: str | None = None
    session_mode: str | None = None
    cookies_file_present: bool = False  # track whether cookies are used in this request


@dataclass
class CanonicalProxyCandidate:
    """Canonical proxy candidate model for future list_api/public_feed normalization."""
    candidate_key: str
    provider_id: int
    provider_name: str
    protocol: str
    host: str
    port: int
    proxy_url: str
    provider_adapter: str = "list_api"
    username: str | None = None
    password_enc: str | None = None
    auth_type: str = "none"
    country_code: str | None = None
    region: str | None = None
    city: str | None = None
    anonymity: str | None = None
    risk_level: str = "medium"
    supports_https: bool = True
    supports_cookies: bool = False
    supports_auto_download: bool = True
    supports_sticky_session: bool = False
    latency_ms: int | None = None
    last_probe_status: str = "unknown"
    last_probe_at: str | None = None
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    score: float = 0.0
    provider_reference_id: str | None = None
    ttl_expires_at: str | None = None
    last_seen_at: str | None = None


@dataclass
class ProxyProviderCandidate:
    """A dynamic proxy provider that is a candidate for routing."""
    provider_id: int
    name: str
    billing_tier: str            # 'free' | 'paid'
    adapter_type: str            # 'public_feed' | 'list_api' | 'rotating_gateway' | 'local_gateway'
    config_json: dict
    supports_cookies: bool
    supports_auto_download: bool
    supports_sticky_session: bool
    risk_level: str              # 'low' | 'medium' | 'high'
    priority: int
    is_available: bool
    unavailable_reason: str | None = None


# ── Helpers ─────────────────────────────────────────────────────

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


# ── Account Static Proxy ─────────────────────────────────────────

def _account_static_proxy_available(account: dict) -> tuple[bool, str | None]:
    """
    Check if the account has an available static proxy.
    Returns (available, proxy_url or None).
    """
    if not account.get("proxy_enabled"):
        return False, None
    pool_id = account.get("proxy_pool_id")
    if not pool_id:
        return False, None
    proxy = _db.get_account_proxy(account)
    if proxy:
        return True, proxy
    return False, None


# ── Core Routing Logic ──────────────────────────────────────────

def _get_global_config() -> dict:
    """Load global config with defaults for dynamic proxy fields."""
    cfg = _db.load_config()
    return {
        "system_dynamic_proxy_enabled": cfg.get("system_dynamic_proxy_enabled", False),
        "apply_dynamic_proxy_to_new_accounts": cfg.get("apply_dynamic_proxy_to_new_accounts", True),
        "apply_dynamic_proxy_to_existing_accounts": cfg.get("apply_dynamic_proxy_to_existing_accounts", False),
        "allow_free_proxy": cfg.get("allow_free_proxy", True),
        "allow_free_proxy_for_auto_download": cfg.get("allow_free_proxy_for_auto_download", False),
        "allow_free_proxy_with_cookies": cfg.get("allow_free_proxy_with_cookies", False),
        "manual_direct_fallback": cfg.get("manual_direct_fallback", True),
        "auto_direct_fallback": cfg.get("auto_direct_fallback", False),
    }


def _account_can_use_system_fallback(account: dict, global_config: dict) -> bool:
    """Decide whether this account is allowed to use system dynamic proxy fallback."""
    if not global_config.get("system_dynamic_proxy_enabled", False):
        return False

    created_at = account.get("created_at")
    # No created_at on new/unsaved accounts in tests/UI flow: treat as new account
    if not created_at:
        return bool(global_config.get("apply_dynamic_proxy_to_new_accounts", True))

    return bool(global_config.get("apply_dynamic_proxy_to_existing_accounts", False))


def _direct_result(
    reason: str,
    fallback_depth: int = 0,
    warnings: list[str] | None = None,
    cookies_file_present: bool = False,
) -> ProxyRouteResult:
    """Build a direct (no proxy) result."""
    return ProxyRouteResult(
        resolved_mode="direct",
        proxy=None,
        proxy_pool=None,
        provider_name=None,
        provider_tier=None,
        resolved_proxy_source="direct",
        reason=reason,
        warnings=warnings or [],
        fallback_depth=fallback_depth,
        masked_proxy_endpoint=None,
        session_mode=None,
        cookies_file_present=cookies_file_present,
    )


def _failed_result(reason: str, fallback_depth: int = 0, cookies_file_present: bool = False, resolved_source: str = "failed", warnings: list[str] | None = None) -> ProxyRouteResult:
    """Build a failed routing result."""
    return ProxyRouteResult(
        resolved_mode="failed",
        proxy=None,
        proxy_pool=None,
        provider_name=None,
        provider_tier=None,
        resolved_proxy_source=resolved_source,
        reason=reason,
        warnings=warnings or [],
        fallback_depth=fallback_depth,
        masked_proxy_endpoint=None,
        session_mode=None,
        cookies_file_present=cookies_file_present,
    )


def _try_system_proxy(
    account: dict,
    is_auto_download: bool,
    cookies_file_present: bool,
    global_config: dict,
) -> ProxyRouteResult:
    """
    Try to resolve a system dynamic proxy based on global config and constraints.
    Returns the best available provider's proxy, or a direct/failed fallback.
    """
    try:
        providers_raw = _get_enabled_providers()
    except Exception as e:
        _log.warning(f"Failed to load providers: {e}")
        providers_raw = []

    if not providers_raw:
        _log.debug("No enabled providers found")
        allow_direct = global_config["auto_direct_fallback"] if is_auto_download else global_config["manual_direct_fallback"]
        if allow_direct:
            return _direct_result(
                reason="无可用动态代理提供方，已启用直连兜底",
                fallback_depth=1,
                warnings=["无可用动态代理提供方"],
                cookies_file_present=cookies_file_present,
            )
        return _failed_result("无可用动态代理提供方且不允许直连", fallback_depth=1, cookies_file_present=cookies_file_present, resolved_source="system_paid")

    candidates: list[ProxyProviderCandidate] = []
    for prov in providers_raw:
        cand = _build_provider_candidate(prov)
        candidates.append(cand)

    # Build ordered list: paid first, then free (if allowed)
    paid_candidates = [c for c in candidates if c.billing_tier == "paid"]
    free_candidates = [c for c in candidates if c.billing_tier == "free"]

    # Filter free candidates based on constraints
    if is_auto_download and not global_config["allow_free_proxy_for_auto_download"]:
        free_candidates = []
        _log.debug("Auto download: free proxy disallowed by config")

    if cookies_file_present and not global_config["allow_free_proxy_with_cookies"]:
        # Also skip high-risk paid providers with cookies
        paid_candidates = [
            c for c in paid_candidates
            if c.risk_level != "high"
        ]
        free_candidates = []
        _log.debug("Cookie download: free proxy disallowed, high-risk paid skipped")

    # Cookie check: skip high-risk providers regardless of tier
    paid_candidates = [c for c in paid_candidates if c.risk_level != "high"]

    ordered_candidates = paid_candidates + free_candidates

    warnings: list[str] = []
    for cand in ordered_candidates:
        # Check cooldown
        # We need to check cooldown on the raw provider dict
        raw = next((p for p in providers_raw if p["id"] == cand.provider_id), {})
        if _is_provider_in_cooldown(raw):
            _log.debug(f"Provider {cand.name} skipped: in cooldown")
            warnings.append(f"提供方 {cand.name} 冷却中，跳过")
            continue

        # Check unavailable
        if not cand.is_available:
            reason = cand.unavailable_reason or "不可用"
            _log.debug(f"Provider {cand.name} skipped: {reason}")
            warnings.append(f"提供方 {cand.name} 不可用 ({reason})，跳过")
            continue

        # Check supports_auto_download
        if is_auto_download and not cand.supports_auto_download:
            _log.debug(f"Provider {cand.name} skipped: does not support auto download")
            warnings.append(f"提供方 {cand.name} 不支持自动下载，跳过")
            continue

        # Check supports_cookies
        if cookies_file_present and not cand.supports_cookies:
            _log.debug(f"Provider {cand.name} skipped: does not support cookies")
            warnings.append(f"提供方 {cand.name} 不支持 Cookie，跳过")
            continue

        # Resolve the actual proxy
        proxy = _resolve_provider_proxy(cand)

        # For gateway types (rotating/local): proxy must be a non-empty string.
        # For pool-style types (public_feed/list_api): use selected candidate pool.
        is_pool_adapter = cand.adapter_type in ("public_feed", "list_api")
        if is_pool_adapter:
            po = global_config.get("default_proxy_protocol_order")
            if not isinstance(po, list) or not po:
                po = list(_db.DEFAULT_PROXY_PROTOCOL_ORDER)
            scenario = {
                "is_auto_download": is_auto_download,
                "cookies_present": cookies_file_present,
                "country_codes": [],
                "protocol_order": po,
                "allow_free": global_config.get("allow_free_proxy", True),
                "max_candidates": 5,
            }
            if cand.adapter_type == "list_api":
                selected_candidates = _resolve_list_api_with_candidates(raw, scenario)
            else:
                selected_candidates = _select_candidates_for_provider(raw, scenario)
            if not selected_candidates:
                _log.debug(f"Provider {cand.name} ({cand.adapter_type}): no selected candidates")
                warnings.append(f"提供方 {cand.name} 候选池为空，跳过")
                continue

            proxy_pool = [candidate.proxy_url for candidate in selected_candidates]
            masked = _mask_proxy_url(proxy_pool[0])
            tier_label = "系统付费动态代理" if cand.billing_tier == "paid" else "系统免费动态代理"
            _log.info(
                f"路由命中: {tier_label} provider={cand.name} "
                f"adapter={cand.adapter_type} tier={cand.billing_tier} "
                f"pool_size={len(proxy_pool)} first={masked}"
            )

            result_warnings = list(warnings)
            if cand.billing_tier == "free":
                result_warnings.append(f"使用免费动态代理提供方 {cand.name}，稳定性可能不如付费代理")

            return ProxyRouteResult(
                resolved_mode=cand.billing_tier + "_system",
                proxy=None,
                proxy_pool=proxy_pool,
                provider_name=cand.name,
                provider_tier=cand.billing_tier,
                resolved_proxy_source="system_" + cand.billing_tier,
                reason=f"命中系统动态代理提供方: {cand.name} ({cand.adapter_type})，返回 {len(proxy_pool)} 个候选",
                warnings=result_warnings,
                fallback_depth=1,
                masked_proxy_endpoint=masked,
                session_mode="rotating",
                cookies_file_present=cookies_file_present,
            )

        if proxy is None:
            _log.debug(f"Provider {cand.name} ({cand.adapter_type}): no proxy resolved")
            warnings.append(f"提供方 {cand.name} 未返回可用代理，跳过")
            continue

        # Build result
        session_mode = cand.config_json.get("session_mode", "sticky")
        masked = _mask_proxy_url(proxy)

        tier_label = "系统付费动态代理" if cand.billing_tier == "paid" else "系统免费动态代理"
        _log.info(
            f"路由命中: {tier_label} provider={cand.name} "
            f"adapter={cand.adapter_type} tier={cand.billing_tier} "
            f"proxy={masked} session={session_mode}"
        )

        result_warnings = list(warnings)
        if cand.billing_tier == "free":
            result_warnings.append(f"使用免费动态代理提供方 {cand.name}，稳定性可能不如付费代理")

        return ProxyRouteResult(
            resolved_mode=cand.billing_tier + "_system",
            proxy=proxy,
            proxy_pool=None,
            provider_name=cand.name,
            provider_tier=cand.billing_tier,
            resolved_proxy_source="system_" + cand.billing_tier,
            reason=f"命中系统动态代理提供方: {cand.name} ({cand.adapter_type})",
            warnings=result_warnings,
            fallback_depth=1,
            masked_proxy_endpoint=masked,
            session_mode=session_mode,
        )

    # All providers exhausted
    warnings.append("所有动态代理提供方均不可用")
    allow_direct = global_config["auto_direct_fallback"] if is_auto_download else global_config["manual_direct_fallback"]
    if allow_direct:
        _log.info("所有动态代理提供方不可用，启用直连兜底")
        return _direct_result(
            reason="无可用动态代理，启用直连兜底",
            fallback_depth=2,
            warnings=list(warnings),
            cookies_file_present=cookies_file_present,
        )
    return _failed_result(
        reason="无可用动态代理且不允许直连",
        fallback_depth=2,
        cookies_file_present=cookies_file_present,
        resolved_source="system_paid",
    )


def resolve_proxy_download(
    account: dict,
    is_auto_download: bool = False,
    cookies_file_present: bool = False,
    user_forced_direct: bool = False,
) -> ProxyRouteResult:
    """
    Resolve the proxy to use for a download.

    Args:
        account: Account dict from db (may have download_proxy_mode field)
        is_auto_download: Whether this is an auto download (vs manual)
        cookies_file_present: Whether a cookies file is present for this download
        user_forced_direct: Whether the user explicitly chose direct

    Returns:
        ProxyRouteResult with resolved proxy info
    """
    mode = account.get("download_proxy_mode", "auto")
    global_config = _get_global_config()

    # Step 1: User forced direct
    if user_forced_direct:
        _log.info(f"路由决策: 用户显式指定直连 mode={mode}")
        return _direct_result(
            reason="用户显式指定直连",
            fallback_depth=0,
            warnings=[],
            cookies_file_present=cookies_file_present,
        )

    # Step 2: Route by download_proxy_mode
    if mode == "direct_only":
        _log.info("路由决策: 账户设置为始终直连 mode=direct_only")
        if is_auto_download and not global_config["auto_direct_fallback"]:
            return _failed_result(
                reason="账户设置为始终直连，但自动下载不允许直连",
                fallback_depth=0,
                cookies_file_present=cookies_file_present,
                resolved_source="direct",
                warnings=["不允许直连"],
            )
        return _direct_result(
            reason="账户设置为始终直连",
            fallback_depth=0,
            cookies_file_present=cookies_file_present,
        )

    if mode == "account_only":
        _log.info("路由决策: 账户仅使用固定代理 mode=account_only")
        available, proxy = _account_static_proxy_available(account)
        if available and proxy:
            masked = _mask_proxy_url(proxy)
            _log.info(f"路由命中: 账户固定代理 proxy={masked}")
            return ProxyRouteResult(
                resolved_mode="account_static",
                proxy=proxy,
                proxy_pool=None,
                provider_name=None,
                provider_tier=None,
                resolved_proxy_source="account_static",
                reason="账户固定代理可用",
                warnings=[],
                fallback_depth=0,
                masked_proxy_endpoint=masked,
                session_mode=None,
            )
        _log.warning("路由失败: 账户仅允许固定代理但固定代理不可用")
        return _failed_result(
            reason="账户仅允许固定代理但固定代理不可用",
            fallback_depth=1,
            cookies_file_present=cookies_file_present,
            resolved_source="account_static",
        )

    if mode == "system_only":
        _log.info("路由决策: 账户仅使用系统动态代理 mode=system_only")
        if not _account_can_use_system_fallback(account, global_config):
            return _failed_result(
                reason="当前账户未启用系统动态代理回退",
                fallback_depth=0,
                cookies_file_present=cookies_file_present,
                resolved_source="system_paid",
            )
        if not global_config["system_dynamic_proxy_enabled"]:
            _log.warning("系统动态代理未启用")
            return _direct_result(
                reason="系统动态代理未启用，退回直连",
                fallback_depth=0,
                warnings=["系统动态代理未启用"],
                cookies_file_present=cookies_file_present,
            )
        return _try_system_proxy(
            account, is_auto_download, cookies_file_present, global_config
        )

    # mode == "auto" (default)
    _log.info(f"路由决策: 自动模式 mode=auto is_auto={is_auto_download} cookies={cookies_file_present}")

    # Try account static proxy first
    available, proxy = _account_static_proxy_available(account)
    if available and proxy:
        masked = _mask_proxy_url(proxy)
        _log.info(f"路由命中: 账户固定代理可用 proxy={masked}")
        return ProxyRouteResult(
            resolved_mode="account_static",
            proxy=proxy,
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="account_static",
            reason="账户固定代理可用",
            warnings=[],
            fallback_depth=0,
            masked_proxy_endpoint=masked,
            session_mode=None,
        )

    # Account static proxy not available — try system dynamic proxy
    if not _account_can_use_system_fallback(account, global_config):
        _log.warning("账户固定代理不可用且系统动态代理未对该账户启用")
        allow_direct = (
            global_config["manual_direct_fallback"]
            if not is_auto_download
            else global_config["auto_direct_fallback"]
        )
        if allow_direct:
            return _direct_result(
                reason="账户固定代理不可用且系统动态代理未对该账户启用，启用直连兜底",
                fallback_depth=1,
                warnings=["系统动态代理未对该账户启用"],
                cookies_file_present=cookies_file_present,
            )
        return _failed_result(
            reason="账户固定代理不可用且系统动态代理未对该账户启用且不允许直连",
            fallback_depth=1,
            cookies_file_present=cookies_file_present,
            resolved_source="failed",
        )

    # Fall back to system dynamic proxy
    _log.info("账户固定代理不可用，尝试系统动态代理")
    return _try_system_proxy(
        account, is_auto_download, cookies_file_present, global_config
    )


def resolve_download_proxy(
    account_id: int,
    is_auto_download: bool = False,
    cookies_file_present: bool = False,
    user_forced_direct: bool = False,
) -> ProxyRouteResult:
    """
    Public entry point — loads account from DB and delegates to core function.

    Args:
        account_id: The monitor account ID
        is_auto_download: Whether this is an auto download
        cookies_file_present: Whether a cookies file is present
        user_forced_direct: Whether user explicitly chose direct

    Returns:
        ProxyRouteResult with resolved proxy info
    """
    account = _db.get_account(account_id)
    if not account:
        _log.error(f"路由失败: 账户不存在 (id={account_id})")
        return ProxyRouteResult(
            resolved_mode="failed",
            proxy=None,
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="direct",
            reason=f"账户不存在 (id={account_id})",
            warnings=[],
            fallback_depth=0,
            masked_proxy_endpoint=None,
            session_mode=None,
        )
    return resolve_proxy_download(
        account,
        is_auto_download=is_auto_download,
        cookies_file_present=cookies_file_present,
        user_forced_direct=user_forced_direct,
    )

"""monitor.proxy.router — Main proxy routing logic."""
from __future__ import annotations

import logging

import monitor.db as _db
from monitor.proxy.models import ProxyRouteResult, ProxyProviderCandidate, CanonicalProxyCandidate
from monitor.proxy.providers import (
    _get_enabled_providers,
    _build_provider_candidate,
    _is_provider_in_cooldown,
    _resolve_provider_proxy,
    _select_candidates_for_provider,
    _mask_proxy_url,
)

_log = logging.getLogger("proxy_router")


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


def _failed_result(
    reason: str,
    fallback_depth: int = 0,
    cookies_file_present: bool = False,
    resolved_source: str = "failed",
    warnings: list[str] | None = None,
) -> ProxyRouteResult:
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
                from monitor.proxy.providers import _resolve_list_api_with_candidates
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


class ProxyRouter:
    """Proxy routing namespace — mirrors the proxy_router module API."""

    @staticmethod
    def resolve(account: dict, is_auto_download: bool = False, cookies_file_present: bool = False, user_forced_direct: bool = False):
        return resolve_proxy_download(account, is_auto_download, cookies_file_present, user_forced_direct)

    @staticmethod
    def resolve_by_id(account_id: int, is_auto_download: bool = False, cookies_file_present: bool = False, user_forced_direct: bool = False):
        return resolve_download_proxy(account_id, is_auto_download, cookies_file_present, user_forced_direct)


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

from __future__ import annotations

from dataclasses import dataclass, field

import monitor.proxy.router as proxy_router


@dataclass
class NativeProxyPlan:
    proxies: list[str] = field(default_factory=list)
    source: str = "direct"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    session_mode: str = ""

    @property
    def requests_proxies(self) -> dict[str, str] | None:
        if not self.proxies:
            return None
        proxy = self.proxies[0]
        return {"http": proxy, "https": proxy}


def resolve_native_proxy_plan(account: dict | None = None, *, cookies_present: bool = False) -> NativeProxyPlan:
    account = dict(account or {})
    account.setdefault("download_proxy_mode", "auto")
    route = proxy_router.resolve_proxy_download(
        account,
        is_auto_download=False,
        cookies_file_present=cookies_present,
        user_forced_direct=False,
    )
    tier = getattr(route, "provider_tier", "") or ""
    source = getattr(route, "resolved_proxy_source", "") or "direct"
    session_mode = getattr(route, "session_mode", "") or ""
    if cookies_present and tier == "free":
        return NativeProxyPlan(
            proxies=[],
            source="direct",
            reason="Cookie 请求禁止使用免费代理，退回直连",
            warnings=["Cookie 请求禁止使用免费动态代理"],
        )
    proxies = list(getattr(route, "proxy_pool", None) or [])
    proxy = getattr(route, "proxy", None)
    if proxy:
        proxies.insert(0, proxy)
    if cookies_present and proxies and session_mode and session_mode != "sticky":
        return NativeProxyPlan(
            proxies=[],
            source="direct",
            reason="Cookie 请求需要粘性会话代理，非 sticky 代理已退回直连",
            warnings=list(getattr(route, "warnings", []) or []) + ["Cookie 请求需要 Sticky Session 代理"],
            session_mode=session_mode,
        )
    return NativeProxyPlan(
        proxies=[item for item in proxies if item],
        source=source if proxies else "direct",
        reason=getattr(route, "reason", "") or "",
        warnings=list(getattr(route, "warnings", []) or []),
        session_mode=session_mode,
    )

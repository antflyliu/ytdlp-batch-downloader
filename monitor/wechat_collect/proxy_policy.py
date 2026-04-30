from __future__ import annotations

from dataclasses import dataclass, field

import monitor.proxy.router as proxy_router


@dataclass
class NativeProxyPlan:
    proxies: list[str] = field(default_factory=list)
    source: str = "direct"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

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
    return NativeProxyPlan(
        proxies=[item for item in proxies if item],
        source=source if proxies else "direct",
        reason=getattr(route, "reason", "") or "",
        warnings=list(getattr(route, "warnings", []) or []),
    )

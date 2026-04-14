"""monitor.proxy.models — Data classes for proxy routing."""
from __future__ import annotations

from dataclasses import dataclass, field


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

"""
monitor/provider_health.py — Dynamic Proxy Provider Health Check

Probes rotating_gateway and local_gateway providers via HTTP to determine
their actual health status.
"""
from __future__ import annotations

import logging
import socket
import ssl
from dataclasses import dataclass

import monitor.db as _db

_log = logging.getLogger("provider_health")


# ── Result Dataclass ──────────────────────────────────────────────

@dataclass
class ProbeResult:
    """Result of a provider health probe."""
    status: str          # 'healthy' | 'degraded' | 'auth_error' | 'down' | 'not_started'
    latency_ms: int       # Round-trip latency in milliseconds, -1 if unreachable
    error_message: str | None  # Human-readable error if status != healthy
    response_code: int | None  # HTTP status code if a response was received, else None


# ── Health Probe ──────────────────────────────────────────────────

def check_provider_health(provider_id: int) -> ProbeResult:
    """
    Probe a dynamic proxy provider and return its health status.

    Probes are performed by sending an HTTP HEAD request through the proxy
    to a reliable test URL (https://www.google.com/generate_204).

    Returns a ProbeResult with status, latency, and error details.
    """
    provider = _db.get_dynamic_proxy_provider(provider_id)
    if not provider:
        return ProbeResult(status="down", latency_ms=-1, error_message="提供方不存在", response_code=None)

    if not provider.get("enabled"):
        return ProbeResult(status="not_started", latency_ms=-1, error_message="提供方已禁用", response_code=None)

    adapter = provider.get("adapter_type", "")
    cfg = provider.get("config_json") or {}

    if adapter == "rotating_gateway":
        return _probe_rotating_gateway(cfg)
    elif adapter == "local_gateway":
        return _probe_local_gateway(cfg)
    elif adapter == "public_feed":
        # v1: public_feed has no gateway to probe
        return ProbeResult(status="healthy", latency_ms=0, error_message=None, response_code=None)
    elif adapter == "list_api":
        # v1: list_api has no gateway to probe
        return ProbeResult(status="healthy", latency_ms=0, error_message=None, response_code=None)
    else:
        return ProbeResult(status="down", latency_ms=-1, error_message=f"未知适配器类型: {adapter}", response_code=None)


def _probe_rotating_gateway(cfg: dict) -> ProbeResult:
    """
    Probe a rotating_gateway provider by sending HTTP HEAD through the proxy.
    """
    host = cfg.get("gateway_host")
    port = cfg.get("gateway_port")
    protocol = cfg.get("protocol", "http")
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not host or not port:
        return ProbeResult(
            status="down",
            latency_ms=-1,
            error_message="配置缺少 gateway_host 或 gateway_port",
            response_code=None,
        )

    proxy_url = _build_gateway_proxy_url(protocol, username, password, host, port)
    return _http_probe(proxy_url, protocol)


def _probe_local_gateway(cfg: dict) -> ProbeResult:
    """
    Probe a local_gateway provider by sending HTTP HEAD through the local proxy.
    """
    local_url = cfg.get("local_proxy_url")
    if not local_url:
        return ProbeResult(
            status="down",
            latency_ms=-1,
            error_message="配置缺少 local_proxy_url",
            response_code=None,
        )

    # Determine scheme for the proxy URL
    scheme = "http"
    if local_url.startswith("socks5://"):
        scheme = "socks5"
    elif local_url.startswith("socks4://"):
        scheme = "socks4"
    elif local_url.startswith("https://"):
        scheme = "https"

    return _http_probe(local_url, scheme)


def _build_gateway_proxy_url(protocol: str, username: str, password: str, host: str, port: int) -> str:
    """Build a proxy URL for the rotating gateway."""
    # Normalize protocol for urllib
    proxy_scheme = "http" if protocol.lower() in ("http", "https") else protocol.lower()
    if username or password:
        netloc = f"{username}:{password}@{host}:{port}"
    else:
        netloc = f"{host}:{port}"
    return f"{proxy_scheme}://{netloc}"


# ── HTTP Probe ───────────────────────────────────────────────────

# Test URLs (tried in order — use the first reachable one)
_PROBE_URLS = [
    "https://www.google.com/generate_204",
    "https://clients3.google.com/generate_204",
    "https://www.gstatic.com/generate_204",
    "http://connectivitycheck.gstatic.com/generate_204",
]
# Fallback HTTP URL (no TLS) if all HTTPS fail
_PROBE_HTTP_URL = "http://httpbin.org/get"

# Degraded threshold: probes returning >3s latency are marked degraded
_DEGRADED_THRESHOLD_MS = 3000


def probe_proxy_url(
    proxy_url: str,
    proxy_scheme: str,
    timeout_seconds: float | None = None,
) -> ProbeResult:
    """
    经代理发起 HEAD 出网探测（与网关类提供方健康检查相同逻辑）。

    Args:
        proxy_url: 完整代理 URL（如 http://user:pass@host:port）
        proxy_scheme: http / https / socks4 / socks5
        timeout_seconds: 超时秒数；省略时使用配置项 proxy_probe_timeout_seconds
    """
    return _http_probe(proxy_url, proxy_scheme, timeout_seconds=timeout_seconds)


def _http_probe(
    proxy_url: str,
    proxy_scheme: str,
    timeout_seconds: float | None = None,
) -> ProbeResult:
    """
    Send an HTTP HEAD request through the given proxy and return the result.

    Args:
        proxy_url:    Full proxy URL (e.g. http://user:pass@host:port)
        proxy_scheme: 'http', 'https', or 'socks5'

    Returns:
        ProbeResult with status, latency, and error details.
    """
    import urllib.request
    import urllib.error

    if timeout_seconds is not None:
        timeout_sec = float(timeout_seconds)
    else:
        cfg = _db.load_config()
        timeout_sec = float(cfg.get("proxy_probe_timeout_seconds", 8))

    # HTTP proxies → try HTTPS URLs through the proxy (tests proxy forwarding to internet)
    # SOCKS proxies → use HTTP test URL (simpler compatibility)
    proxy_type = proxy_scheme.lower()
    use_tls_probe = proxy_type not in ("socks5", "socks4", "http")
    test_urls = [u for u in _PROBE_URLS if u.startswith("https://")] if use_tls_probe else [_PROBE_HTTP_URL]
    if not test_urls:
        test_urls = _PROBE_URLS  # fallback to HTTPS list

    last_error: str | None = None

    for test_url in test_urls:
        try:
            start_ms = _current_time_ms()

            # Build proxy handler
            proxy_type = proxy_scheme.lower()
            if proxy_type == "https":
                proxy_type = "http"  # urllib.request doesn't support https proxy directly
            elif proxy_type not in ("http", "socks5", "socks4"):
                proxy_type = "http"

            proxy = urllib.request.ProxyHandler({proxy_type: proxy_url})
            # Build SSL context that skips certificate verification for proxies
            # (proxy TLS certs are typically self-signed or untrusted)
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            opener = urllib.request.build_opener(proxy, urllib.request.HTTPSHandler(context=ssl_ctx))
            request = urllib.request.Request(test_url, method="HEAD")
            # Set a short user-agent to avoid heavy responses
            request.add_header("User-Agent", "Mozilla/5.0 (compatible; health-probe/1.0)")

            try:
                response = opener.open(request, timeout=timeout_sec)
                status_code = response.code
                elapsed_ms = _current_time_ms() - start_ms
                response.close()
            except urllib.error.HTTPError as e:
                status_code = e.code
                elapsed_ms = _current_time_ms() - start_ms
                # 401/407 = auth failure
                if status_code in (401, 407):
                    return ProbeResult(
                        status="auth_error",
                        latency_ms=elapsed_ms,
                        error_message=f"认证失败 (HTTP {status_code})",
                        response_code=status_code,
                    )
                # Treat 4xx/5xx as degraded/down depending on code
                if 400 <= status_code < 500:
                    return ProbeResult(
                        status="degraded",
                        latency_ms=elapsed_ms,
                        error_message=f"代理响应异常 (HTTP {status_code})",
                        response_code=status_code,
                    )
                else:
                    return ProbeResult(
                        status="down",
                        latency_ms=elapsed_ms,
                        error_message=f"代理服务器错误 (HTTP {status_code})",
                        response_code=status_code,
                    )
            except urllib.error.URLError as e:
                elapsed_ms = _current_time_ms() - start_ms
                err_str = str(e.reason)
                # Socket-level auth errors
                if isinstance(e.reason, socket.timeout) or "timed out" in err_str.lower():
                    return ProbeResult(
                        status="down",
                        latency_ms=elapsed_ms,
                        error_message="连接超时",
                        response_code=None,
                    )
                if "407" in err_str or "Proxy Authentication Required" in err_str:
                    return ProbeResult(
                        status="auth_error",
                        latency_ms=elapsed_ms,
                        error_message="代理认证失败 (407)",
                        response_code=407,
                    )
                if "401" in err_str or "Unauthorized" in err_str:
                    return ProbeResult(
                        status="auth_error",
                        latency_ms=elapsed_ms,
                        error_message="认证失败 (401)",
                        response_code=401,
                    )
                return ProbeResult(
                    status="down",
                    latency_ms=elapsed_ms,
                    error_message=f"连接失败: {err_str}",
                    response_code=None,
                )

            # Success: 2xx/3xx
            if 200 <= status_code < 400:
                if elapsed_ms > _DEGRADED_THRESHOLD_MS:
                    return ProbeResult(
                        status="degraded",
                        latency_ms=elapsed_ms,
                        error_message=f"代理响应过慢 ({elapsed_ms}ms)",
                        response_code=status_code,
                    )
                return ProbeResult(
                    status="healthy",
                    latency_ms=elapsed_ms,
                    error_message=None,
                    response_code=status_code,
                )

            # Other status codes
            return ProbeResult(
                status="down",
                latency_ms=elapsed_ms,
                error_message=f"异常响应 (HTTP {status_code})",
                response_code=status_code,
            )

        except socket.timeout:
            elapsed_ms = _current_time_ms() - start_ms
            last_error = "连接超时"
            _log.debug(f"Health probe timeout on {test_url}")
            continue
        except ConnectionRefusedError:
            elapsed_ms = _current_time_ms() - start_ms
            last_error = "连接被拒绝"
            _log.debug(f"Health probe connection refused on {test_url}")
            continue
        except Exception as e:
            last_error = str(e)
            _log.debug(f"Health probe error on {test_url}: {e}")
            continue

    # All URLs failed
    return ProbeResult(
        status="down",
        latency_ms=-1,
        error_message=last_error or "所有探测地址均失败",
        response_code=None,
    )


def _current_time_ms() -> int:
    """Return current time in milliseconds."""
    import time
    return int(time.time() * 1000)

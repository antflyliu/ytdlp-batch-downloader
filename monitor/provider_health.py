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


@dataclass
class ProbeResult:
    """Result of a provider health probe."""
    status: str
    latency_ms: int
    error_message: str | None
    response_code: int | None


def check_provider_health(provider_id: int) -> ProbeResult:
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
        return ProbeResult(status="healthy", latency_ms=0, error_message=None, response_code=None)
    elif adapter == "list_api":
        return ProbeResult(status="healthy", latency_ms=0, error_message=None, response_code=None)
    else:
        return ProbeResult(status="down", latency_ms=-1, error_message=f"未知适配器类型: {adapter}", response_code=None)


def _probe_rotating_gateway(cfg: dict) -> ProbeResult:
    host = cfg.get("gateway_host")
    port = cfg.get("gateway_port")
    protocol = cfg.get("protocol", "http")
    username = cfg.get("username", "")
    password = cfg.get("password", "")

    if not host or not port:
        return ProbeResult(status="down", latency_ms=-1, error_message="配置缺少 gateway_host 或 gateway_port", response_code=None)

    proxy_url = _build_gateway_proxy_url(protocol, username, password, host, port)
    return _http_probe(proxy_url, protocol)


def _probe_local_gateway(cfg: dict) -> ProbeResult:
    local_url = cfg.get("local_proxy_url")
    if not local_url:
        return ProbeResult(status="down", latency_ms=-1, error_message="配置缺少 local_proxy_url", response_code=None)

    scheme = "http"
    if local_url.startswith("socks5://"):
        scheme = "socks5"
    elif local_url.startswith("socks4://"):
        scheme = "socks4"
    elif local_url.startswith("https://"):
        scheme = "https"

    return _http_probe(local_url, scheme)


def _build_gateway_proxy_url(protocol: str, username: str, password: str, host: str, port: int) -> str:
    proxy_scheme = "http" if protocol.lower() in ("http", "https") else protocol.lower()
    if username or password:
        netloc = f"{username}:{password}@{host}:{port}"
    else:
        netloc = f"{host}:{port}"
    return f"{proxy_scheme}://{netloc}"


_PROBE_URLS = [
    "https://www.google.com/generate_204",
    "https://clients3.google.com/generate_204",
    "https://www.gstatic.com/generate_204",
    "http://connectivitycheck.gstatic.com/generate_204",
]
_PROBE_HTTP_URL = "http://httpbin.org/get"
_DEGRADED_THRESHOLD_MS = 3000


def _http_probe(proxy_url: str, proxy_scheme: str) -> ProbeResult:
    import urllib.request
    import urllib.error
    import time

    cfg = _db.load_config()
    timeout_sec = cfg.get("proxy_probe_timeout_seconds", 8)

    proxy_type = proxy_scheme.lower()
    use_tls_probe = proxy_type not in ("socks5", "socks4", "http")
    test_urls = [u for u in _PROBE_URLS if u.startswith("https://")] if use_tls_probe else [_PROBE_HTTP_URL]
    if not test_urls:
        test_urls = _PROBE_URLS

    for test_url in test_urls:
        try:
            start_ms = _current_time_ms()
            proxy_type = proxy_scheme.lower()
            if proxy_type == "https":
                proxy_type = "http"
            elif proxy_type not in ("http", "socks5", "socks4"):
                proxy_type = "http"

            proxy = urllib.request.ProxyHandler({proxy_type: proxy_url})
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            opener = urllib.request.build_opener(proxy, urllib.request.HTTPSHandler(context=ssl_ctx))
            request = urllib.request.Request(test_url, method="HEAD")
            request.add_header("User-Agent", "Mozilla/5.0 (compatible; health-probe/1.0)")

            try:
                response = opener.open(request, timeout=timeout_sec)
                status_code = response.code
                elapsed_ms = _current_time_ms() - start_ms
                response.close()
            except urllib.error.HTTPError as e:
                status_code = e.code
                elapsed_ms = _current_time_ms() - start_ms
                if status_code in (401, 407):
                    return ProbeResult(status="auth_error", latency_ms=elapsed_ms, error_message=f"认证失败 (HTTP {status_code})", response_code=status_code)
                if 400 <= status_code < 500:
                    return ProbeResult(status="degraded", latency_ms=elapsed_ms, error_message=f"代理响应异常 (HTTP {status_code})", response_code=status_code)
                return ProbeResult(status="down", latency_ms=elapsed_ms, error_message=f"代理服务器错误 (HTTP {status_code})", response_code=status_code)
            except urllib.error.URLError as e:
                elapsed_ms = _current_time_ms() - start_ms
                err_str = str(e.reason)
                if isinstance(e.reason, socket.timeout) or "timed out" in err_str.lower():
                    return ProbeResult(status="down", latency_ms=elapsed_ms, error_message="连接超时", response_code=None)
                if "407" in err_str or "Proxy Authentication Required" in err_str:
                    return ProbeResult(status="auth_error", latency_ms=elapsed_ms, error_message="代理认证失败 (407)", response_code=407)
                if "401" in err_str or "Unauthorized" in err_str:
                    return ProbeResult(status="auth_error", latency_ms=elapsed_ms, error_message="认证失败 (401)", response_code=401)
                return ProbeResult(status="down", latency_ms=elapsed_ms, error_message=f"连接失败: {err_str}", response_code=None)

            if 200 <= status_code < 400:
                if elapsed_ms > _DEGRADED_THRESHOLD_MS:
                    return ProbeResult(status="degraded", latency_ms=elapsed_ms, error_message=f"代理响应过慢 ({elapsed_ms}ms)", response_code=status_code)
                return ProbeResult(status="healthy", latency_ms=elapsed_ms, error_message=None, response_code=status_code)
        except Exception as e:
            _log.debug("provider health probe fallback failed: %s", e)
            continue

    return ProbeResult(status="down", latency_ms=-1, error_message="探测失败", response_code=None)


def _current_time_ms() -> int:
    import time
    return int(time.time() * 1000)

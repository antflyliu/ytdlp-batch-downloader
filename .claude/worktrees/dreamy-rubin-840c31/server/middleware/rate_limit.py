"""
server/middleware/rate_limit.py — Rate limiting middleware.

Extracted from monitor_server.py:
  - _rate_limiter dict, _rate_limiter_lock
  - _rate_limit_client_ip (as standalone get_client_ip_from_headers)
  - _rate_limit_exempt_loopback (as standalone is_loopback_ip)
  - _check_rate_limit (as standalone check_rate_limit)
  - _path_skips_rate_limit (as standalone path_skips_rate_limit)
  - Constants: _RATE_LIMIT_WINDOW, _RATE_LIMIT_MAX
"""
from __future__ import annotations

import collections
import threading
import time


# ── Rate limiter state ──────────────────────────────────────────
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 600    # max requests per window per IP

_rate_limiter: dict[str, collections.deque[float]] = {}
_rate_limiter_lock = threading.Lock()


def is_loopback_ip(ip: str) -> bool:
    """Return True if the IP is loopback (127.x.x.x, ::1, ::ffff:127.x.x.x)."""
    if not ip:
        return False
    ip = ip.strip()
    if ip in ("127.0.0.1", "::1"):
        return True
    if ip.startswith("127."):
        return True
    if ip.startswith("::ffff:127."):
        return True
    return False


def get_client_ip_from_headers(headers, client_address: tuple) -> str:
    """Extract client IP from the socket address (local desktop app, no reverse proxy)."""
    return client_address[0] or ""


def path_skips_rate_limit(path: str) -> bool:
    """Return True for paths that should skip global rate limiting (high-frequency polling)."""
    if path.startswith("/api/download-tasks/"):
        return True
    if path in ("/api/provider-scheduler/logs", "/api/provider-scheduler/status"):
        return True
    return False


def check_rate_limit(
    ip: str,
    *,
    window: int = RATE_LIMIT_WINDOW,
    max_requests: int = RATE_LIMIT_MAX,
    rate_limiter: dict[str, collections.deque[float]] | None = None,
    rate_limiter_lock: threading.Lock | None = None,
) -> tuple[bool, int | None]:
    """
    Check if a client IP has exceeded the rate limit.

    Returns:
        (is_allowed, retry_after) — is_allowed=True means passed; False means limited.
        retry_after is the number of seconds until the window clears (only set when limited).

    Callers that need to send a 429 response can use the returned retry_after value.
    """
    if is_loopback_ip(ip):
        return True, None

    if rate_limiter is None:
        rate_limiter = _rate_limiter
    if rate_limiter_lock is None:
        rate_limiter_lock = _rate_limiter_lock

    now = time.time()
    with rate_limiter_lock:
        if ip not in rate_limiter:
            rate_limiter[ip] = collections.deque(maxlen=max_requests)
        times = rate_limiter[ip]

        cutoff = now - window
        while times and times[0] < cutoff:
            times.popleft()

        if len(times) >= max_requests:
            retry_after = int(window - (now - times[0])) + 1
            return False, retry_after

        times.append(now)
    return True, None

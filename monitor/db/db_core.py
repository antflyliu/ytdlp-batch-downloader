"""
monitor.db.core — Shared constants and helpers for the db subpackage.

Imported by all other db submodules. Contains:
- Sentinel values
- Default constants
- Time helpers (now_iso, _today_str)
"""
from contextlib import contextmanager
from datetime import datetime, timedelta

# Sentinel value: distinguish "parameter not passed" from "explicitly passed None"
_UNSET = type("_Unset", (), {"__repr__": lambda s: "<UNSET>", "__bool__": lambda s: False})()

# Dynamic proxy protocol order (shared default)
DEFAULT_PROXY_PROTOCOL_ORDER = ("http", "https", "socks5", "socks4")

# Webhook config keys
_GLOBAL_WEBHOOK_KEYS = (
    "global_feishu_url",
    "global_dingtalk_url",
    "global_dingtalk_sign_secret",
    "global_wecom_url",
    "global_telegram_token",
)

# Sensitive field names for config encryption
_SECRET_FIELD_NAMES = frozenset(
    ["password", "auth_secret", "api_key", "secret", "token"]
)


def now_iso() -> str:
    """Current local time as ISO 8601 string with timezone offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today_str() -> str:
    """Current local date as YYYY-MM-DD string."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _iso_future(seconds: int) -> str:
    """Return ISO 8601 string N seconds from now."""
    return (
        datetime.now() + timedelta(seconds=seconds)
    ).astimezone().isoformat(timespec="seconds")


def _escape_like(s: str) -> str:
    """Escape LIKE wildcards to prevent over-matching."""
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

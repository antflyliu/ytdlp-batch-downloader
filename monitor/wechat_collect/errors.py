from __future__ import annotations

import re


_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)([?&](?:api_token|auth_key|token|key|secret)=)([^&#\s]+)"), r"\1***"),
    (re.compile(r"(?i)\b((?:api_token|auth_key|token|key|secret)\s*[:=]\s*)([^,&\s;]+)"), r"\1***"),
    (re.compile(r"(?i)\b(Cookie\s*[:=]\s*)([^\r\n]+)"), r"\1***"),
    (re.compile(r"(?i)\b(Set-Cookie\s*[:=]\s*)([^\r\n]+)"), r"\1***"),
)


def redact_sensitive_text(value: object) -> str:
    """Remove credential-like values from messages that can reach API responses or logs."""
    text = str(value or "")
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def safe_error_message(exc: BaseException | object) -> str:
    return redact_sensitive_text(exc)


class WechatNativeError(RuntimeError):
    """Base class for native WeChat collector failures."""


class WechatLoginError(WechatNativeError):
    """Raised when QR login cannot start, poll, or finalize."""


class WechatSessionError(WechatNativeError):
    """Raised when a persisted native session is missing or expired."""


class WechatUpstreamError(WechatNativeError):
    """Raised when mp.weixin.qq.com returns a non-success response."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        operation: str = "",
        session_expired: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.session_expired = session_expired


class WechatArticleError(WechatNativeError):
    """Raised when article HTML cannot be fetched, parsed, or exported."""


class WechatTaskError(WechatNativeError):
    """Raised when a collection task cannot be created or completed."""

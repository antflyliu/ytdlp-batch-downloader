from __future__ import annotations


class EmailCollectError(RuntimeError):
    """Base error for email collection operations."""


class EmailAccountValidationError(EmailCollectError):
    """Raised when an email account payload is invalid."""


class EmailProviderError(EmailCollectError):
    """Raised when an email provider cannot fetch or test messages."""

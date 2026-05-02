from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EMAIL_PROVIDER_GMAIL = "gmail"
EMAIL_PROVIDER_IMAP = "imap"
EMAIL_PROVIDERS = {EMAIL_PROVIDER_GMAIL, EMAIL_PROVIDER_IMAP}

EMAIL_SECRET_FIELDS = {
    "gmail_client_secret",
    "gmail_refresh_token",
    "imap_password",
    "smtp_password",
}

DEFAULT_CONTENT_PLATFORMS = (
    "wechat",
    "xiaohongshu",
    "toutiao",
    "baijiahao",
    "juejin",
    "zhihu",
    "x",
    "reddit",
)


@dataclass(slots=True)
class AttachmentMeta:
    filename: str = ""
    content_type: str = ""
    size: int = 0
    content_id: str = ""
    disposition: str = ""


@dataclass(slots=True)
class ParsedEmailMessage:
    provider: str
    provider_message_id: str
    provider_thread_id: str = ""
    rfc_message_id: str = ""
    subject: str = ""
    from_addr: str = ""
    to_addr: str = ""
    cc_addr: str = ""
    received_at: str = ""
    sent_at: str = ""
    snippet: str = ""
    body_text: str = ""
    html_body: str = ""
    raw_mime: bytes | None = None
    attachments: list[AttachmentMeta] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CleanEmailMessage:
    body_text: str
    snippet: str
    body_hash: str
    report: dict[str, Any]


@dataclass(slots=True)
class EmailClassification:
    primary_type: str
    secondary_types: list[str]
    language: str
    value_score: int
    action: str
    recommended_targets: list[str]
    risk_flags: list[str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_type": self.primary_type,
            "secondary_types": self.secondary_types,
            "language": self.language,
            "value_score": self.value_score,
            "action": self.action,
            "recommended_targets": self.recommended_targets,
            "risk_flags": self.risk_flags,
            "reason": self.reason,
        }

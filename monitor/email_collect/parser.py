from __future__ import annotations

import base64
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Any

from .cleaner import html_to_text
from .models import AttachmentMeta, ParsedEmailMessage


def _header_value(message, name: str) -> str:
    value = message.get(name)
    return str(value or "").strip()


def _date_header(message) -> str:
    raw = _header_value(message, "Date")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).astimezone().isoformat(timespec="seconds")
    except Exception:
        return raw


def _body_payload(part) -> str:
    try:
        payload = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        if isinstance(payload, bytes):
            return payload.decode(charset, errors="replace")
    return str(payload or "")


def _extract_body(message) -> tuple[str, str]:
    plain = ""
    html_body = ""
    plain_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    if plain_part is not None:
        plain = _body_payload(plain_part).strip()
    if html_part is not None:
        html_body = _body_payload(html_part).strip()
    if not plain and html_body:
        plain = html_to_text(html_body)
    return plain, html_body


def _extract_attachments(message) -> list[AttachmentMeta]:
    attachments: list[AttachmentMeta] = []
    for part in message.iter_attachments():
        filename = str(part.get_filename() or "")
        content_type = str(part.get_content_type() or "")
        content_id = str(part.get("Content-ID") or "").strip("<>")
        disposition = str(part.get_content_disposition() or "")
        size = 0
        try:
            payload = part.get_payload(decode=True) or b""
            size = len(payload)
        except Exception:
            size = 0
        attachments.append(
            AttachmentMeta(
                filename=filename,
                content_type=content_type,
                size=size,
                content_id=content_id,
                disposition=disposition,
            )
        )
    return attachments


def parse_rfc822(
    raw: bytes | str,
    *,
    provider: str,
    provider_message_id: str,
    provider_thread_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> ParsedEmailMessage:
    raw_bytes = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else raw
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes or b"")
    body_text, html_body = _extract_body(message)
    snippet = " ".join(body_text.split())[:240]
    sent_at = _date_header(message)
    return ParsedEmailMessage(
        provider=provider,
        provider_message_id=str(provider_message_id or ""),
        provider_thread_id=str(provider_thread_id or ""),
        rfc_message_id=_header_value(message, "Message-ID"),
        subject=_header_value(message, "Subject"),
        from_addr=_header_value(message, "From"),
        to_addr=_header_value(message, "To"),
        cc_addr=_header_value(message, "Cc"),
        received_at=sent_at,
        sent_at=sent_at,
        snippet=snippet,
        body_text=body_text,
        html_body=html_body,
        raw_mime=raw_bytes,
        attachments=_extract_attachments(message),
        raw_payload=raw_payload or {},
    )


def parse_gmail_raw_message(payload: dict[str, Any]) -> ParsedEmailMessage:
    raw_value = str(payload.get("raw") or "")
    if not raw_value:
        raise ValueError("Gmail message payload does not include raw content")
    padded = raw_value + "=" * (-len(raw_value) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    return parse_rfc822(
        raw_bytes,
        provider="gmail",
        provider_message_id=str(payload.get("id") or ""),
        provider_thread_id=str(payload.get("threadId") or ""),
        raw_payload=payload,
    )

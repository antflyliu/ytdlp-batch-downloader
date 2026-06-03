from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.email_collect.parser import parse_gmail_raw_message, parse_rfc822


def test_parse_rfc822_prefers_plain_body_and_extracts_attachment_metadata():
    raw = (
        "From: Alice <alice@example.com>\n"
        "To: Bob <bob@example.com>\n"
        "Cc: Carol <carol@example.com>\n"
        "Subject: Release Update\n"
        "Date: Tue, 30 Apr 2026 11:22:33 +0800\n"
        "Message-ID: <msg-1@example.com>\n"
        "MIME-Version: 1.0\n"
        "Content-Type: multipart/mixed; boundary=\"mix\"\n"
        "\n"
        "--mix\n"
        "Content-Type: multipart/alternative; boundary=\"alt\"\n"
        "\n"
        "--alt\n"
        "Content-Type: text/plain; charset=\"utf-8\"\n"
        "\n"
        "Plain body line 1.\n"
        "Plain body line 2.\n"
        "--alt\n"
        "Content-Type: text/html; charset=\"utf-8\"\n"
        "\n"
        "<p>HTML body</p>\n"
        "--alt--\n"
        "--mix\n"
        "Content-Type: text/plain; name=\"notes.txt\"\n"
        "Content-Disposition: attachment; filename=\"notes.txt\"\n"
        "Content-ID: <cid-note>\n"
        "\n"
        "attachment payload\n"
        "--mix--\n"
    )

    parsed = parse_rfc822(
        raw,
        provider="imap",
        provider_message_id="provider-msg-1",
        provider_thread_id="thread-1",
    )

    assert parsed.provider == "imap"
    assert parsed.provider_message_id == "provider-msg-1"
    assert parsed.provider_thread_id == "thread-1"
    assert parsed.rfc_message_id == "<msg-1@example.com>"
    assert parsed.subject == "Release Update"
    assert parsed.from_addr == "Alice <alice@example.com>"
    assert parsed.to_addr == "Bob <bob@example.com>"
    assert parsed.cc_addr == "Carol <carol@example.com>"
    assert parsed.body_text == "Plain body line 1.\nPlain body line 2."
    assert parsed.html_body == "<p>HTML body</p>"
    assert parsed.snippet == "Plain body line 1. Plain body line 2."
    assert parsed.sent_at.endswith("+08:00")
    assert parsed.received_at == parsed.sent_at
    assert parsed.raw_mime == raw.encode("utf-8")
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "notes.txt"
    assert parsed.attachments[0].content_type == "text/plain"
    assert parsed.attachments[0].content_id == "cid-note"
    assert parsed.attachments[0].disposition == "attachment"
    assert parsed.attachments[0].size == len(b"attachment payload")


def test_parse_rfc822_falls_back_to_html_text_when_plain_part_missing():
    raw = (
        "From: Sender <sender@example.com>\n"
        "To: Reader <reader@example.com>\n"
        "Subject: HTML only\n"
        "Date: Tue, 30 Apr 2026 11:22:33 +0800\n"
        "Message-ID: <html-only@example.com>\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/html; charset=\"utf-8\"\n"
        "\n"
        "<div>Hello <b>world</b>.</div><p>Second line.</p>"
    )

    parsed = parse_rfc822(raw, provider="gmail", provider_message_id="gmail-1")

    assert parsed.body_text == "\nHello world.\n\nSecond line.\n"
    assert parsed.html_body == "<div>Hello <b>world</b>.</div><p>Second line.</p>"
    assert parsed.snippet == "Hello world. Second line."


def test_parse_gmail_raw_message_decodes_base64url_payload_without_network():
    raw = (
        "From: Feed <feed@example.com>\n"
        "To: Team <team@example.com>\n"
        "Subject: Weekly digest\n"
        "Date: Tue, 30 Apr 2026 11:22:33 +0800\n"
        "Message-ID: <gmail-raw@example.com>\n"
        "Content-Type: text/plain; charset=\"utf-8\"\n"
        "\n"
        "Digest body.\n"
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    parsed = parse_gmail_raw_message({"id": "gmail-msg-1", "threadId": "gmail-thread-1", "raw": encoded})

    assert parsed.provider == "gmail"
    assert parsed.provider_message_id == "gmail-msg-1"
    assert parsed.provider_thread_id == "gmail-thread-1"
    assert parsed.subject == "Weekly digest"
    assert parsed.body_text == "Digest body."
    assert parsed.raw_payload["id"] == "gmail-msg-1"


def test_parse_gmail_raw_message_rejects_payload_without_raw_content():
    try:
        parse_gmail_raw_message({"id": "gmail-msg-2", "threadId": "gmail-thread-2"})
    except ValueError as exc:
        assert str(exc) == "Gmail message payload does not include raw content"
    else:
        raise AssertionError("parse_gmail_raw_message should reject payloads without raw content")

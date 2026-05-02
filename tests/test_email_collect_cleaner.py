from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.email_collect.cleaner import clean_parsed_email, clean_text, html_to_text
from monitor.email_collect.models import ParsedEmailMessage


def test_html_to_text_ignores_script_content_and_tracking_links():
    html = """
    <html>
      <body>
        <script>alert("x")</script>
        <p>Hello <strong>world</strong>.</p>
        <a href="https://tracker.example.com/open?id=1&utm_source=test">Tracked</a>
        <a href="https://example.com/article">Readable Link</a>
      </body>
    </html>
    """

    text = html_to_text(html)

    assert "alert" not in text
    assert "Hello world." in text
    assert "Tracked" in text
    assert "Readable Link" in text


def test_clean_text_removes_quote_chain_boilerplate_and_tracking_urls():
    raw = (
        "Fresh paragraph one.\n\n"
        "Fresh paragraph two with context.\n"
        "https://tracker.example.com/open?id=123&utm_source=email\n"
        "View in browser\n\n"
        "On Tue, Apr 30, 2026 at 10:00 AM Someone <someone@example.com> wrote:\n"
        "> quoted line\n"
    )

    cleaned = clean_text(raw)

    assert cleaned.body_text == "Fresh paragraph one.\n\nFresh paragraph two with context."
    assert cleaned.snippet == "Fresh paragraph one. Fresh paragraph two with context."
    assert cleaned.body_hash == hashlib.sha256(cleaned.body_text.encode("utf-8")).hexdigest()
    assert cleaned.report["removed_quoted_chain"] is True
    assert cleaned.report["removed_boilerplate_lines"] == 1
    assert cleaned.report["is_empty_or_ignored"] is False


def test_clean_parsed_email_uses_html_body_when_plain_body_missing():
    parsed = ParsedEmailMessage(
        provider="gmail",
        provider_message_id="gmail-2",
        body_text="",
        html_body="<div>Alpha</div><p>Beta</p>",
    )

    cleaned = clean_parsed_email(parsed)

    assert cleaned.body_text == "Alpha\n\nBeta"
    assert cleaned.snippet == "Alpha Beta"
    assert cleaned.report["removed_quoted_chain"] is False


def test_clean_text_marks_short_remaining_content_as_ignored():
    cleaned = clean_text("Brief update.")

    assert cleaned.body_text == "Brief update."
    assert cleaned.report["is_empty_or_ignored"] is True

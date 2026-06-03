from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from typing import Any

from .models import CleanEmailMessage

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg"}
_QUOTE_PATTERNS = (
    re.compile(r"(?im)^\s*On .{0,160} wrote:\s*$"),
    re.compile(r"(?im)^\s*-{2,}\s*Original Message\s*-{2,}\s*$"),
    re.compile(r"(?im)^\s*From:\s+.+\n\s*Sent:\s+.+\n\s*To:\s+.+"),
    re.compile(r"(?im)^\s*发件人:\s+.+\n\s*发送时间:\s+.+\n\s*收件人:\s+.+"),
)
_BOILERPLATE_LINE_RE = re.compile(
    r"(?i)\b(unsubscribe|view in browser|manage preferences|email preferences|"
    r"privacy policy|update your preferences|opt out|取消订阅|退订|在浏览器中查看)\b"
)
_TRACKING_URL_RE = re.compile(r"https?://\S*(?:utm_[a-z0-9_]+|track|pixel|open)\S*", re.IGNORECASE)


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "pre":
            self._pre_depth += 1
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href and not _TRACKING_URL_RE.search(href):
                self.parts.append(" ")
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data if self._pre_depth else re.sub(r"[ \t\r\f\v]+", " ", data))

    def text(self) -> str:
        return "".join(self.parts)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    extractor = _HtmlTextExtractor()
    try:
        extractor.feed(value)
        extractor.close()
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", value))
    return html.unescape(extractor.text())


def _collapse_quoted_chain(text: str) -> tuple[str, bool]:
    cut = len(text)
    for pattern in _QUOTE_PATTERNS:
        match = pattern.search(text)
        if match:
            cut = min(cut, match.start())
    if cut < len(text):
        return text[:cut], True
    lines = []
    removed = False
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            removed = True
            continue
        lines.append(line)
    return "\n".join(lines), removed


def clean_text(value: str | None) -> CleanEmailMessage:
    raw = html.unescape(str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    raw = _TRACKING_URL_RE.sub("", raw)
    text, removed_quote = _collapse_quoted_chain(raw)
    kept_lines: list[str] = []
    removed_boilerplate = 0
    for line in text.splitlines():
        normalized_line = re.sub(r"[ \t]+", " ", line).strip()
        if _BOILERPLATE_LINE_RE.search(normalized_line):
            removed_boilerplate += 1
            continue
        kept_lines.append(line.rstrip())
    text = "\n".join(kept_lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    body_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    snippet = re.sub(r"\s+", " ", text).strip()[:240]
    return CleanEmailMessage(
        body_text=text,
        snippet=snippet,
        body_hash=body_hash,
        report={
            "removed_quoted_chain": removed_quote,
            "removed_boilerplate_lines": removed_boilerplate,
            "is_empty_or_ignored": len(text) < 40,
        },
    )


def clean_parsed_email(parsed: Any) -> CleanEmailMessage:
    body = getattr(parsed, "body_text", "") or html_to_text(getattr(parsed, "html_body", ""))
    return clean_text(body)

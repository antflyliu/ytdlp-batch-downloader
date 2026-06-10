from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit, urlunsplit


ProviderName = Literal["exporter_api", "native"]
TaskStatus = Literal["pending", "running", "done", "error", "cancelled"]
SourceMode = Literal["url", "fakeid", "urls"]

SUPPORTED_EXPORT_FORMATS = {
    "html": "html",
    "markdown": "md",
    "text": "txt",
    "json": "json",
}

MP_ARTICLE_URL_RE = re.compile(r"^https://mp\.weixin\.qq\.com/s[/\?]", re.IGNORECASE)
MP_HOST_RE = re.compile(r"^mp\.weixin\.qq\.com/", re.IGNORECASE)


@dataclass
class NativeSession:
    session_id: str
    token: str
    cookies: list[dict[str, str]] = field(default_factory=list)
    nickname: str = ""
    avatar: str = ""
    status: str = "active"
    expires_at: str = ""


@dataclass
class ArticleDownload:
    body: bytes
    content_type: str
    title: str = ""
    metadata: dict = field(default_factory=dict)


def normalize_mp_article_url(value: str) -> str:
    text = html.unescape(str(value or "").strip())
    if text.startswith("//"):
        text = f"https:{text}"
    elif MP_HOST_RE.match(text):
        text = f"https://{text}"
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if parsed.netloc.lower() != "mp.weixin.qq.com":
        return ""
    path = parsed.path or ""
    if path != "/s" and not path.startswith("/s/"):
        return ""
    return urlunsplit(("https", "mp.weixin.qq.com", path, parsed.query, parsed.fragment))


def is_valid_mp_article_url(value: str) -> bool:
    return bool(normalize_mp_article_url(value))


def normalize_account_preview(raw: dict) -> dict:
    return {
        "fakeid": raw.get("fakeid") or "",
        "nickname": raw.get("nickname") or "",
        "alias": raw.get("alias") or "",
        "round_head_img": raw.get("round_head_img") or "",
        "service_type": raw.get("service_type"),
        "signature": raw.get("signature") or "",
        "verify_status": raw.get("verify_status"),
    }


def normalize_article_preview(raw: dict) -> dict:
    link = normalize_mp_article_url(raw.get("link") or raw.get("url") or "")
    return {
        "aid": raw.get("aid") or "",
        "title": raw.get("title") or "",
        "link": link,
        "cover": raw.get("cover") or raw.get("cover_img") or "",
        "digest": raw.get("digest") or "",
        "author_name": raw.get("author_name") or "",
        "update_time": raw.get("update_time") or raw.get("create_time") or 0,
        "create_time": raw.get("create_time") or 0,
    }

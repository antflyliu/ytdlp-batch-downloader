from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


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


def is_valid_mp_article_url(value: str) -> bool:
    return MP_ARTICLE_URL_RE.match((value or "").strip()) is not None


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
    return {
        "aid": raw.get("aid") or "",
        "title": raw.get("title") or "",
        "link": raw.get("link") or raw.get("url") or "",
        "cover": raw.get("cover") or raw.get("cover_img") or "",
        "digest": raw.get("digest") or "",
        "author_name": raw.get("author_name") or "",
        "update_time": raw.get("update_time") or raw.get("create_time") or 0,
        "create_time": raw.get("create_time") or 0,
    }

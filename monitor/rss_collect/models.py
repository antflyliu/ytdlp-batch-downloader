from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedFeedItem:
    title: str
    link: str
    guid: str
    author: str = ""
    published_at: str = ""
    summary: str = ""
    content_html: str = ""
    preview_image: str = ""
    media_attachments: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedFeed:
    title: str
    link: str = ""
    language: str = ""
    items: list[ParsedFeedItem] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedOpmlEntry:
    title: str
    xml_url: str
    site_url: str = ""
    category: str = ""


@dataclass(frozen=True)
class ParsedOpmlDocument:
    entries: list[ParsedOpmlEntry]
    invalid_items: list[dict[str, str]]
    duplicate_items: list[dict[str, str]]

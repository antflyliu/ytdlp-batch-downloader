from __future__ import annotations

import email.utils
import html
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import defusedxml.ElementTree as ET

from .models import ParsedFeed, ParsedFeedItem, ParsedOpmlDocument, ParsedOpmlEntry


class RssParseError(ValueError):
    pass


def normalize_http_url(value: object, base_url: str = "") -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    if base_url:
        text = urljoin(base_url, text)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def _all_children(node: ET.Element, *names: str) -> list[ET.Element]:
    wanted = {name.lower() for name in names}
    return [child for child in list(node) if _local_name(child.tag) in wanted]


def _strip_html(value: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _looks_like_image_url(url: str) -> bool:
    return bool(re.search(r"\.(png|jpe?g|gif|webp|avif|bmp|svg)(?:$|[?#])", url, re.I))


def _preview_image(item: ET.Element, base_url: str) -> str:
    for child in list(item):
        name = _local_name(child.tag)
        url = child.attrib.get("url") or child.attrib.get("href") or ""
        normalized = normalize_http_url(url, base_url)
        if not normalized:
            continue
        mime_type = (child.attrib.get("type") or "").lower()
        medium = (child.attrib.get("medium") or "").lower()
        if name in {"thumbnail", "image"}:
            return normalized
        if name == "content" and (mime_type.startswith("image/") or medium == "image" or _looks_like_image_url(normalized)):
            return normalized
        if name == "enclosure" and (mime_type.startswith("image/") or _looks_like_image_url(normalized)):
            return normalized
    return ""


def _media_attachments(item: ET.Element, base_url: str) -> list[dict[str, object]]:
    attachments: list[dict[str, object]] = []
    seen: set[str] = set()
    for child in list(item):
        name = _local_name(child.tag)
        if name not in {"enclosure", "content"}:
            continue
        url = normalize_http_url(child.attrib.get("url") or child.attrib.get("href"), base_url)
        mime_type = (child.attrib.get("type") or "").strip().lower()
        if not url or url in seen or not (mime_type.startswith("audio/") or mime_type.startswith("video/")):
            continue
        seen.add(url)
        length = child.attrib.get("length") or child.attrib.get("fileSize") or ""
        try:
            size_bytes = int(length) if str(length).isdigit() else None
        except ValueError:
            size_bytes = None
        attachments.append({"url": url, "mime_type": mime_type, "size_bytes": size_bytes})
    return attachments


def parse_feed_xml(xml_text: str, *, feed_url: str = "") -> ParsedFeed:
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        raise RssParseError("RSS/Atom XML 解析失败") from exc

    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in list(root) if _local_name(child.tag) == "channel"), None)
        if channel is None:
            raise RssParseError("RSS 缺少 channel")
        feed_title = _child_text(channel, "title")
        feed_link = normalize_http_url(_child_text(channel, "link"), feed_url)
        language = _child_text(channel, "language")
        item_nodes = _all_children(channel, "item")
    elif root_name == "feed":
        channel = root
        feed_title = _child_text(channel, "title")
        feed_link = ""
        for link in _all_children(channel, "link"):
            rel = (link.attrib.get("rel") or "alternate").lower()
            href = normalize_http_url(link.attrib.get("href") or "", feed_url)
            if href and rel == "alternate":
                feed_link = href
                break
        language = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "")
        item_nodes = _all_children(channel, "entry")
    else:
        raise RssParseError("不支持的 Feed 根节点")

    items: list[ParsedFeedItem] = []
    for node in item_nodes:
        is_atom = _local_name(node.tag) == "entry"
        title = _child_text(node, "title") or "(untitled)"
        raw_link = _child_text(node, "link")
        if is_atom:
            for link in _all_children(node, "link"):
                rel = (link.attrib.get("rel") or "alternate").lower()
                if rel == "alternate":
                    raw_link = link.attrib.get("href") or raw_link
                    break
        link = normalize_http_url(raw_link, feed_link or feed_url)
        guid = _child_text(node, "guid", "id") or link or title
        content_html = _child_text(node, "content", "encoded", "content:encoded")
        summary = _child_text(node, "description", "summary") or _strip_html(content_html)
        published_at = _parse_date(_child_text(node, "pubDate", "published", "updated"))
        items.append(
            ParsedFeedItem(
                title=html.unescape(title.strip()),
                link=link,
                guid=guid.strip(),
                author=_child_text(node, "author", "creator", "dc:creator"),
                published_at=published_at,
                summary=_strip_html(summary),
                content_html=content_html,
                preview_image=_preview_image(node, feed_link or feed_url),
                media_attachments=_media_attachments(node, feed_link or feed_url),
            )
        )

    return ParsedFeed(title=html.unescape(feed_title or feed_url or "RSS Feed"), link=feed_link, language=language, items=items)


def parse_opml_document(xml_text: str) -> ParsedOpmlDocument:
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        raise RssParseError("OPML XML 解析失败") from exc
    if _local_name(root.tag) != "opml":
        raise RssParseError("OPML 根节点无效")
    body = next((child for child in list(root) if _local_name(child.tag) == "body"), None)
    if body is None:
        raise RssParseError("OPML 缺少 body")

    entries: list[ParsedOpmlEntry] = []
    invalid_items: list[dict[str, str]] = []
    duplicate_items: list[dict[str, str]] = []
    seen: set[str] = set()

    def label(node: ET.Element) -> str:
        return (node.attrib.get("text") or node.attrib.get("title") or "").strip()

    def visit(node: ET.Element, category: str = "") -> None:
        xml_url = normalize_http_url(node.attrib.get("xmlUrl") or "")
        raw_xml_url = (node.attrib.get("xmlUrl") or "").strip()
        node_label = label(node)
        if raw_xml_url:
            if not xml_url:
                invalid_items.append({"title": node_label, "xml_url": raw_xml_url, "reason": "invalid_url"})
            elif xml_url in seen:
                duplicate_items.append({"title": node_label or xml_url, "xml_url": xml_url, "reason": "duplicate_in_file"})
            else:
                seen.add(xml_url)
                entries.append(
                    ParsedOpmlEntry(
                        title=node_label or xml_url,
                        xml_url=xml_url,
                        site_url=normalize_http_url(node.attrib.get("htmlUrl") or ""),
                        category=category,
                    )
                )
            return
        outline_type = (node.attrib.get("type") or "").lower()
        if outline_type in {"rss", "atom"}:
            invalid_items.append({"title": node_label, "xml_url": "", "reason": "missing_xml_url"})
            return
        next_category = node_label or category
        for child in list(node):
            if _local_name(child.tag) == "outline":
                visit(child, next_category)

    for child in list(body):
        if _local_name(child.tag) == "outline":
            visit(child, "")

    return ParsedOpmlDocument(entries=entries, invalid_items=invalid_items, duplicate_items=duplicate_items)


def build_opml_document(title: str, feeds: list[dict[str, object]]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value or ""), quote=True)

    by_category: dict[str, list[dict[str, object]]] = {}
    for feed in feeds:
        category = str(feed.get("category") or "")
        by_category.setdefault(category, []).append(feed)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">', "  <head>", f"    <title>{esc(title)}</title>", "  </head>", "  <body>"]
    for category in sorted(k for k in by_category if k):
        lines.append(f'    <outline text="{esc(category)}" title="{esc(category)}">')
        for feed in by_category[category]:
            attrs = [f'text="{esc(feed.get("title") or feed.get("feed_url"))}"', f'title="{esc(feed.get("title") or feed.get("feed_url"))}"', 'type="rss"', f'xmlUrl="{esc(feed.get("feed_url"))}"']
            if feed.get("site_url"):
                attrs.append(f'htmlUrl="{esc(feed.get("site_url"))}"')
            lines.append(f"      <outline {' '.join(attrs)} />")
        lines.append("    </outline>")
    for feed in by_category.get("", []):
        attrs = [f'text="{esc(feed.get("title") or feed.get("feed_url"))}"', f'title="{esc(feed.get("title") or feed.get("feed_url"))}"', 'type="rss"', f'xmlUrl="{esc(feed.get("feed_url"))}"']
        if feed.get("site_url"):
            attrs.append(f'htmlUrl="{esc(feed.get("site_url"))}"')
        lines.append(f"    <outline {' '.join(attrs)} />")
    lines.extend(["  </body>", "</opml>"])
    return "\n".join(lines)

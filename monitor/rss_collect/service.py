from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

import monitor.db as db
from monitor.db.queries import rss_collect as rss_queries

from .parser import build_opml_document, parse_feed_xml, parse_opml_document
from .security import validate_external_http_url, validate_external_ip_address

MAX_OPML_CHARS = 1_000_000
MAX_FEED_REDIRECTS = 5


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class RssCollectService:
    def list_feeds(self) -> list[dict[str, Any]]:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            return rss_queries.list_feeds(conn)

    def save_feed(self, payload: dict[str, Any]) -> dict[str, Any]:
        feed_url = validate_external_http_url(str(payload.get("feed_url") or payload.get("url") or ""))
        title = str(payload.get("title") or feed_url).strip()
        site_url = str(payload.get("site_url") or "").strip()
        if site_url:
            site_url = validate_external_http_url(site_url)
        category = str(payload.get("category") or "").strip()
        interval = _coerce_int(payload.get("fetch_interval_minutes"), default=60, minimum=5, maximum=1440)
        enabled = bool(payload.get("enabled", True))
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            feed_id = rss_queries.upsert_feed(
                conn,
                title=title,
                feed_url=feed_url,
                site_url=site_url,
                category=category,
                enabled=enabled,
                fetch_interval_minutes=interval,
            )
            return rss_queries.get_feed(conn, feed_id) or {}

    def delete_feed(self, feed_id: int) -> bool:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            return rss_queries.delete_feed(conn, feed_id)

    def list_items(self, *, feed_id: int | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            return rss_queries.list_items(conn, feed_id=feed_id, limit=limit, offset=offset)

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            return rss_queries.get_item(conn, item_id)

    def refresh_feed(self, feed_id: int, *, max_items: int = 50) -> dict[str, Any]:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            feed = rss_queries.get_feed(conn, feed_id)
        if not feed:
            raise ValueError("RSS 订阅源不存在")

        try:
            xml_text = self._fetch_feed_xml(str(feed["feed_url"]))
            parsed = parse_feed_xml(xml_text, feed_url=str(feed["feed_url"]))
        except Exception as exc:
            with db.get_connection() as conn:
                rss_queries.update_feed_fetch_state(conn, feed_id, status="error", error=str(exc)[:500])
            raise

        stored = 0
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            if parsed.title and parsed.title != feed["title"]:
                rss_queries.upsert_feed(
                    conn,
                    title=parsed.title,
                    feed_url=str(feed["feed_url"]),
                    site_url=parsed.link or str(feed.get("site_url") or ""),
                    category=str(feed.get("category") or ""),
                    enabled=bool(feed.get("enabled", True)),
                    fetch_interval_minutes=int(feed.get("fetch_interval_minutes") or 60),
                )
            for item in parsed.items[: max(min(max_items, 200), 1)]:
                rss_queries.upsert_item(
                    conn,
                    feed_id=feed_id,
                    guid=item.guid,
                    title=item.title,
                    link=item.link,
                    author=item.author,
                    published_at=item.published_at,
                    summary=item.summary,
                    content_html=item.content_html,
                    preview_image=item.preview_image,
                    media=item.media_attachments,
                )
                stored += 1
            rss_queries.update_feed_fetch_state(conn, feed_id, status="ok", error="")
        return {"ok": True, "feed_id": feed_id, "stored": stored}

    def import_opml(self, xml_text: str) -> dict[str, Any]:
        if len(xml_text or "") > MAX_OPML_CHARS:
            raise ValueError("OPML 内容过大")
        parsed = parse_opml_document(xml_text)
        imported = 0
        invalid_items = list(parsed.invalid_items)
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            for entry in parsed.entries:
                try:
                    feed_url = validate_external_http_url(entry.xml_url)
                    site_url = validate_external_http_url(entry.site_url) if entry.site_url else ""
                except ValueError as exc:
                    invalid_items.append(
                        {
                            "title": entry.title,
                            "xml_url": entry.xml_url,
                            "reason": str(exc),
                        }
                    )
                    continue
                rss_queries.upsert_feed(
                    conn,
                    title=entry.title,
                    feed_url=feed_url,
                    site_url=site_url,
                    category=entry.category,
                )
                imported += 1
        return {
            "ok": True,
            "imported": imported,
            "invalid_items": invalid_items,
            "duplicate_items": parsed.duplicate_items,
        }

    def export_opml(self) -> str:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            feeds = rss_queries.list_feeds(conn)
        return build_opml_document("ytdlp-batch-downloader RSS feeds", feeds)

    def prepare_article_payload(self, item_id: int, *, target_lang: str = "zh-Hans") -> dict[str, Any]:
        item = self.get_item(item_id)
        if not item:
            raise ValueError("RSS 条目不存在")
        text = _article_text_from_item(item)
        if not text.strip():
            raise ValueError("RSS 条目正文为空，无法生成 AI 文章")
        return {
            "source_type": "rss_item",
            "rss_item_id": item_id,
            "article_text": text,
            "source_url": item.get("link") or item.get("feed_url") or "",
            "source_title": item.get("title") or "",
            "target_lang": target_lang,
        }

    def mark_item_article_task(self, item_id: int, task_id: str) -> None:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            rss_queries.set_item_article_task(conn, item_id, task_id)

    @staticmethod
    def _fetch_feed_xml(feed_url: str) -> str:
        current_url = validate_external_http_url(feed_url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler)
        headers = {
            "User-Agent": "ytdlp-batch-downloader RSS collector/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        }
        for _ in range(MAX_FEED_REDIRECTS + 1):
            request = urllib.request.Request(current_url, headers=headers)
            try:
                with opener.open(request, timeout=20) as response:
                    _validate_response_peer(response)
                    data = response.read(2_000_000)
                    charset = response.headers.get_content_charset() or "utf-8"
                    return data.decode(charset, errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code not in {301, 302, 303, 307, 308}:
                    raise RuntimeError(f"RSS 拉取失败: HTTP {exc.code}") from exc
                location = exc.headers.get("Location") or ""
                if not location:
                    raise RuntimeError("RSS 重定向缺少 Location") from exc
                current_url = validate_external_http_url(urljoin(current_url, location))
            except urllib.error.URLError as exc:
                raise RuntimeError(f"RSS 拉取失败: {exc}") from exc
        raise RuntimeError("RSS 重定向次数过多")


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min(number, maximum), minimum)


def _strip_html(value: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _article_text_from_item(item: dict[str, Any]) -> str:
    content = _strip_html(str(item.get("content_html") or ""))
    summary = str(item.get("summary") or "").strip()
    parts = [
        f"标题：{item.get('title') or ''}",
        f"来源：{item.get('feed_title') or ''}",
        f"链接：{item.get('link') or item.get('feed_url') or ''}",
    ]
    if item.get("published_at"):
        parts.append(f"发布时间：{item.get('published_at')}")
    body = content or summary
    if body:
        parts.append("")
        parts.append(body)
    return "\n".join(parts).strip()


def _validate_response_peer(response: Any) -> None:
    sock = None
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    if raw is not None:
        sock = getattr(raw, "_sock", None)
    if sock is None and fp is not None:
        nested_fp = getattr(fp, "fp", None)
        raw = getattr(nested_fp, "raw", None)
        sock = getattr(raw, "_sock", None) if raw is not None else None
    if sock is None:
        raise RuntimeError("RSS 连接 peer 校验失败")
    peer = sock.getpeername()
    if not peer:
        raise RuntimeError("RSS 连接 peer 校验失败")
    validate_external_ip_address(str(peer[0]))

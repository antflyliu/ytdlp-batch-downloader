from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

import monitor.db as db
from monitor.db.queries import rss_collect as rss_queries

from .parser import parse_opml_document
from .security import validate_external_http_url

SOURCE_KEY = "jackyst0/awesome-rsshub-routes"
SOURCE_NAME = "Awesome RSSHub Routes"
HOMEPAGE_URL = "https://github.com/JackyST0/awesome-rsshub-routes"
FEEDS_OPML_URL = "https://raw.githubusercontent.com/JackyST0/awesome-rsshub-routes/main/feeds.opml"
FEED_STATUS_URL = "https://raw.githubusercontent.com/JackyST0/awesome-rsshub-routes/main/feed-status.json"
README_URL = "https://raw.githubusercontent.com/JackyST0/awesome-rsshub-routes/main/README.md"
SOURCE_LICENSE = "CC0-1.0"
MAX_CATALOG_BYTES = 2_000_000


class RssCatalogService:
    def list_catalog(
        self,
        *,
        source_key: str | None = None,
        entry_type: str | None = None,
        category: str | None = None,
        query: str = "",
        available_only: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            entries = rss_queries.list_catalog_entries(
                conn,
                source_key=source_key,
                entry_type=entry_type,
                category=category,
                query=query,
                available_only=available_only,
                limit=limit,
                offset=offset,
            )
            summary = rss_queries.catalog_summary(conn)
        return {"entries": entries, "summary": summary}

    def sync_catalog(self) -> dict[str, Any]:
        try:
            opml_text = self._fetch_text(FEEDS_OPML_URL)
            status_text = self._fetch_text(FEED_STATUS_URL)
            readme_text = self._fetch_text(README_URL)
            result = self._store_catalog(opml_text, status_text, readme_text)
        except Exception as exc:
            with db.get_connection() as conn:
                rss_queries.ensure_catalog_schema(conn)
                rss_queries.upsert_catalog_source(
                    conn,
                    source_key=SOURCE_KEY,
                    name=SOURCE_NAME,
                    homepage_url=HOMEPAGE_URL,
                    feeds_url=FEEDS_OPML_URL,
                    status_url=FEED_STATUS_URL,
                    readme_url=README_URL,
                    license=SOURCE_LICENSE,
                    last_synced_at=rss_queries.now_iso(),
                    last_sync_status="error",
                    last_sync_error=str(exc)[:500],
                )
            raise
        return result

    def import_catalog_entries(self, entry_ids: list[int], *, fetch_interval_minutes: int = 60) -> dict[str, Any]:
        imported = 0
        skipped = 0
        invalid_items: list[dict[str, str]] = []
        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            entries = rss_queries.get_catalog_entries_by_ids(conn, entry_ids)
            for entry in entries:
                if entry.get("entry_type") != "feed" or not entry.get("feed_url"):
                    skipped += 1
                    continue
                try:
                    feed_url = validate_external_http_url(str(entry.get("feed_url") or ""))
                    site_url = validate_external_http_url(str(entry.get("site_url") or "")) if entry.get("site_url") else ""
                except ValueError as exc:
                    invalid_items.append(
                        {
                            "title": str(entry.get("title") or ""),
                            "feed_url": str(entry.get("feed_url") or ""),
                            "reason": str(exc),
                        }
                    )
                    continue
                existing = rss_queries.get_feed_by_url(conn, feed_url)
                rss_queries.upsert_feed(
                    conn,
                    title=str(entry.get("title") or feed_url),
                    feed_url=feed_url,
                    site_url=site_url or str((existing or {}).get("site_url") or ""),
                    category=str(entry.get("category") or ""),
                    enabled=bool(existing["enabled"]) if existing else True,
                    fetch_interval_minutes=int(existing["fetch_interval_minutes"]) if existing else fetch_interval_minutes,
                )
                imported += 1
        return {"ok": True, "imported": imported, "skipped": skipped, "invalid_items": invalid_items}

    def _store_catalog(self, opml_text: str, status_text: str, readme_text: str) -> dict[str, Any]:
        parsed_opml = parse_opml_document(opml_text)
        status_payload = _parse_status_payload(status_text)
        status_by_url = {
            str(item.get("url") or ""): item
            for item in status_payload.get("feeds", [])
            if isinstance(item, dict) and item.get("url")
        }
        checked_at = str(status_payload.get("checkTime") or "")
        seen_keys: list[str] = []

        with db.get_connection() as conn:
            rss_queries.ensure_schema(conn)
            rss_queries.upsert_catalog_source(
                conn,
                source_key=SOURCE_KEY,
                name=SOURCE_NAME,
                homepage_url=HOMEPAGE_URL,
                feeds_url=FEEDS_OPML_URL,
                status_url=FEED_STATUS_URL,
                readme_url=README_URL,
                license=SOURCE_LICENSE,
                last_synced_at=rss_queries.now_iso(),
                last_sync_status="ok",
                last_sync_error="",
                feed_total=_coerce_int(status_payload.get("total"), len(parsed_opml.entries)),
                valid_count=_coerce_int(status_payload.get("valid"), 0),
                invalid_count=_coerce_int(status_payload.get("invalid"), 0),
                limited_count=_coerce_int(status_payload.get("limited"), 0),
                success_rate=str(status_payload.get("successRate") or ""),
            )
            for entry in parsed_opml.entries:
                status = status_by_url.get(entry.xml_url, {})
                entry_key = _entry_key("feed", entry.xml_url)
                seen_keys.append(entry_key)
                rss_queries.upsert_catalog_entry(
                    conn,
                    source_key=SOURCE_KEY,
                    entry_key=entry_key,
                    entry_type="feed",
                    title=entry.title,
                    category=_clean_category(entry.category),
                    feed_url=entry.xml_url,
                    site_url=entry.site_url,
                    status=str(status.get("status") or ""),
                    status_valid=_optional_bool(status.get("valid")),
                    status_limited=bool(status.get("limited")),
                    status_code=_optional_int(status.get("statusCode")),
                    status_error=str(status.get("error") or ""),
                    status_checked_at=checked_at,
                )
            for route in _parse_rsshub_routes(readme_text):
                entry_key = _entry_key("rsshub_route", route["route_template"])
                seen_keys.append(entry_key)
                rss_queries.upsert_catalog_entry(
                    conn,
                    source_key=SOURCE_KEY,
                    entry_key=entry_key,
                    entry_type="rsshub_route",
                    title=route["title"],
                    category=route["category"],
                    route_template=route["route_template"],
                    description=route["description"],
                    status="template",
                    status_valid=None,
                )
            rss_queries.delete_catalog_entries_not_in(conn, SOURCE_KEY, seen_keys)
            summary = rss_queries.catalog_summary(conn)
        return {"ok": True, "summary": summary}

    @staticmethod
    def _fetch_text(url: str) -> str:
        request = urllib.request.Request(
            validate_external_http_url(url),
            headers={
                "User-Agent": "ytdlp-batch-downloader RSS catalog/1.0",
                "Accept": "text/plain, application/json, application/xml, text/xml, */*",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(MAX_CATALOG_BYTES + 1)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"RSS 源库拉取失败: {exc}") from exc
        if len(data) > MAX_CATALOG_BYTES:
            raise RuntimeError("RSS 源库内容过大")
        return data.decode("utf-8", errors="replace")


def _parse_status_payload(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("RSS 源库健康状态 JSON 解析失败") from exc
    return payload if isinstance(payload, dict) else {}


def _parse_rsshub_routes(readme_text: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    in_routes = False
    category = ""
    subcategory = ""
    seen: set[str] = set()
    for raw_line in (readme_text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("## RSSHub Routes"):
            in_routes = True
            continue
        if not in_routes:
            continue
        if line.startswith("## "):
            break
        if line.startswith("### "):
            category = _strip_markdown(line[4:])
            subcategory = ""
            continue
        if line.startswith("#### "):
            subcategory = _strip_markdown(line[5:])
            continue
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3 or parts[0].lower() == "name" or set(parts[0]) <= {"-"}:
            continue
        route = _strip_markdown(parts[1])
        if not route.startswith("/"):
            continue
        route_category = category if not subcategory else f"{category} / {subcategory}"
        key = route
        if key in seen:
            continue
        seen.add(key)
        routes.append(
            {
                "title": _strip_markdown(parts[0]) or route,
                "category": route_category,
                "route_template": route,
                "description": _strip_markdown(parts[2]),
            }
        )
    return routes


def _entry_key(entry_type: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return f"{SOURCE_KEY}:{entry_type}:{digest}"


def _clean_category(value: str) -> str:
    text = (value or "").strip()
    while text and not text[0].isalnum() and not ("\u4e00" <= text[0] <= "\u9fff"):
        text = text[1:].strip()
    return text


def _strip_markdown(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("`", "").strip()


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

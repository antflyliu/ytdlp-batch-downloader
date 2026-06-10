from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rss_feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            feed_url TEXT NOT NULL UNIQUE,
            site_url TEXT,
            category TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            fetch_interval_minutes INTEGER NOT NULL DEFAULT 60,
            last_fetch_at TEXT,
            last_fetch_status TEXT,
            last_fetch_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rss_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_id INTEGER NOT NULL,
            guid TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT,
            author TEXT,
            published_at TEXT,
            summary TEXT,
            content_html TEXT,
            preview_image TEXT,
            media_json TEXT NOT NULL DEFAULT '[]',
            article_task_id TEXT,
            read_status TEXT NOT NULL DEFAULT 'unread',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (feed_id) REFERENCES rss_feeds(id) ON DELETE CASCADE,
            UNIQUE(feed_id, guid)
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_feeds_enabled ON rss_feeds(enabled, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_items_feed_published ON rss_items(feed_id, published_at DESC, id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_items_article_task ON rss_items(article_task_id)")
    ensure_catalog_schema(conn)


def ensure_catalog_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rss_catalog_sources (
            source_key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            homepage_url TEXT,
            feeds_url TEXT,
            status_url TEXT,
            readme_url TEXT,
            license TEXT,
            last_synced_at TEXT,
            last_sync_status TEXT,
            last_sync_error TEXT,
            feed_total INTEGER NOT NULL DEFAULT 0,
            valid_count INTEGER NOT NULL DEFAULT 0,
            invalid_count INTEGER NOT NULL DEFAULT 0,
            limited_count INTEGER NOT NULL DEFAULT 0,
            success_rate TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rss_catalog_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key TEXT NOT NULL,
            entry_key TEXT NOT NULL UNIQUE,
            entry_type TEXT NOT NULL DEFAULT 'feed',
            title TEXT NOT NULL,
            category TEXT,
            feed_url TEXT,
            site_url TEXT,
            route_template TEXT,
            description TEXT,
            status TEXT,
            status_valid INTEGER,
            status_limited INTEGER NOT NULL DEFAULT 0,
            status_code INTEGER,
            status_error TEXT,
            status_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_key) REFERENCES rss_catalog_sources(source_key) ON DELETE CASCADE
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_catalog_source_type ON rss_catalog_entries(source_key, entry_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_catalog_category ON rss_catalog_entries(category COLLATE NOCASE, title COLLATE NOCASE)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rss_catalog_feed_url ON rss_catalog_entries(feed_url)")


def _feed_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    return item


def _catalog_source_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _catalog_entry_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    if item.get("status_valid") is not None:
        item["status_valid"] = bool(item.get("status_valid"))
    item["status_limited"] = bool(item.get("status_limited"))
    item["imported"] = bool(item.get("imported", 0))
    item["feed_id"] = item.get("feed_id")
    return item


def _item_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    try:
        item["media"] = json.loads(item.pop("media_json") or "[]")
    except Exception:
        item["media"] = []
    return item


def list_feeds(conn: sqlite3.Connection, *, enabled: bool | None = None) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if enabled is not None:
        where.append("enabled=?")
        params.append(1 if enabled else 0)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"SELECT * FROM rss_feeds{where_sql} ORDER BY category COLLATE NOCASE, title COLLATE NOCASE, id",
        params,
    ).fetchall()
    return [_feed_from_row(row) for row in rows if row is not None]


def upsert_catalog_source(
    conn: sqlite3.Connection,
    *,
    source_key: str,
    name: str,
    homepage_url: str = "",
    feeds_url: str = "",
    status_url: str = "",
    readme_url: str = "",
    license: str = "",
    last_synced_at: str = "",
    last_sync_status: str = "",
    last_sync_error: str = "",
    feed_total: int = 0,
    valid_count: int = 0,
    invalid_count: int = 0,
    limited_count: int = 0,
    success_rate: str = "",
) -> None:
    now = now_iso()
    existing = conn.execute("SELECT source_key FROM rss_catalog_sources WHERE source_key=?", (source_key,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE rss_catalog_sources
               SET name=?, homepage_url=?, feeds_url=?, status_url=?, readme_url=?, license=?,
                   last_synced_at=?, last_sync_status=?, last_sync_error=?, feed_total=?,
                   valid_count=?, invalid_count=?, limited_count=?, success_rate=?, updated_at=?
               WHERE source_key=?""",
            (
                name,
                homepage_url,
                feeds_url,
                status_url,
                readme_url,
                license,
                last_synced_at,
                last_sync_status,
                last_sync_error,
                int(feed_total or 0),
                int(valid_count or 0),
                int(invalid_count or 0),
                int(limited_count or 0),
                success_rate,
                now,
                source_key,
            ),
        )
        return
    conn.execute(
        """INSERT INTO rss_catalog_sources
           (source_key, name, homepage_url, feeds_url, status_url, readme_url, license,
            last_synced_at, last_sync_status, last_sync_error, feed_total, valid_count,
            invalid_count, limited_count, success_rate, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_key,
            name,
            homepage_url,
            feeds_url,
            status_url,
            readme_url,
            license,
            last_synced_at,
            last_sync_status,
            last_sync_error,
            int(feed_total or 0),
            int(valid_count or 0),
            int(invalid_count or 0),
            int(limited_count or 0),
            success_rate,
            now,
            now,
        ),
    )


def list_catalog_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM rss_catalog_sources ORDER BY updated_at DESC, name COLLATE NOCASE"
    ).fetchall()
    return [_catalog_source_from_row(row) for row in rows if row is not None]


def upsert_catalog_entry(
    conn: sqlite3.Connection,
    *,
    source_key: str,
    entry_key: str,
    entry_type: str,
    title: str,
    category: str = "",
    feed_url: str = "",
    site_url: str = "",
    route_template: str = "",
    description: str = "",
    status: str = "",
    status_valid: bool | None = None,
    status_limited: bool = False,
    status_code: int | None = None,
    status_error: str = "",
    status_checked_at: str = "",
) -> None:
    now = now_iso()
    valid_value = None if status_valid is None else 1 if status_valid else 0
    existing = conn.execute("SELECT id FROM rss_catalog_entries WHERE entry_key=?", (entry_key,)).fetchone()
    values = (
        source_key,
        entry_key,
        entry_type,
        title,
        category,
        feed_url,
        site_url,
        route_template,
        description,
        status,
        valid_value,
        1 if status_limited else 0,
        status_code,
        status_error,
        status_checked_at,
        now,
    )
    if existing:
        conn.execute(
            """UPDATE rss_catalog_entries
               SET source_key=?, entry_key=?, entry_type=?, title=?, category=?, feed_url=?,
                   site_url=?, route_template=?, description=?, status=?, status_valid=?,
                   status_limited=?, status_code=?, status_error=?, status_checked_at=?, updated_at=?
               WHERE id=?""",
            (*values, existing["id"]),
        )
        return
    conn.execute(
        """INSERT INTO rss_catalog_entries
           (source_key, entry_key, entry_type, title, category, feed_url, site_url,
            route_template, description, status, status_valid, status_limited,
            status_code, status_error, status_checked_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (*values, now),
    )


def delete_catalog_entries_not_in(conn: sqlite3.Connection, source_key: str, entry_keys: list[str]) -> None:
    if not entry_keys:
        conn.execute("DELETE FROM rss_catalog_entries WHERE source_key=?", (source_key,))
        return
    placeholders = ",".join("?" for _ in entry_keys)
    conn.execute(
        f"DELETE FROM rss_catalog_entries WHERE source_key=? AND entry_key NOT IN ({placeholders})",
        (source_key, *entry_keys),
    )


def list_catalog_entries(
    conn: sqlite3.Connection,
    *,
    source_key: str | None = None,
    entry_type: str | None = None,
    category: str | None = None,
    query: str = "",
    available_only: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if source_key:
        where.append("e.source_key=?")
        params.append(source_key)
    if entry_type:
        where.append("e.entry_type=?")
        params.append(entry_type)
    if category:
        where.append("e.category=?")
        params.append(category)
    if query:
        where.append("(e.title LIKE ? OR e.category LIKE ? OR e.feed_url LIKE ? OR e.route_template LIKE ? OR e.description LIKE ?)")
        needle = f"%{query}%"
        params.extend([needle, needle, needle, needle, needle])
    if available_only:
        where.append("(e.status_valid IS NULL OR e.status_valid=1 OR e.status_limited=1)")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"""SELECT e.*, f.id AS feed_id, CASE WHEN f.id IS NULL THEN 0 ELSE 1 END AS imported
            FROM rss_catalog_entries e
            LEFT JOIN rss_feeds f ON f.feed_url = e.feed_url
            {where_sql}
            ORDER BY e.category COLLATE NOCASE, e.entry_type, e.title COLLATE NOCASE
            LIMIT ? OFFSET ?""",
        (*params, max(min(int(limit), 1000), 1), max(int(offset), 0)),
    ).fetchall()
    return [_catalog_entry_from_row(row) for row in rows if row is not None]


def get_catalog_entries_by_ids(conn: sqlite3.Connection, entry_ids: list[int]) -> list[dict[str, Any]]:
    ids = [int(entry_id) for entry_id in entry_ids if int(entry_id) > 0]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT e.*, f.id AS feed_id, CASE WHEN f.id IS NULL THEN 0 ELSE 1 END AS imported
            FROM rss_catalog_entries e
            LEFT JOIN rss_feeds f ON f.feed_url = e.feed_url
            WHERE e.id IN ({placeholders})
            ORDER BY e.category COLLATE NOCASE, e.title COLLATE NOCASE""",
        ids,
    ).fetchall()
    return [_catalog_entry_from_row(row) for row in rows if row is not None]


def catalog_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    totals = conn.execute(
        """SELECT
               COUNT(*) AS total,
               SUM(CASE WHEN entry_type='feed' THEN 1 ELSE 0 END) AS feed_count,
               SUM(CASE WHEN entry_type='rsshub_route' THEN 1 ELSE 0 END) AS route_count,
               SUM(CASE WHEN status_valid=1 THEN 1 ELSE 0 END) AS valid_count,
               SUM(CASE WHEN status_limited=1 THEN 1 ELSE 0 END) AS limited_count,
               SUM(CASE WHEN status_valid=0 AND status_limited=0 THEN 1 ELSE 0 END) AS invalid_count,
               COUNT(DISTINCT category) AS category_count
           FROM rss_catalog_entries"""
    ).fetchone()
    categories = [
        row["category"]
        for row in conn.execute(
            "SELECT DISTINCT category FROM rss_catalog_entries WHERE category IS NOT NULL AND category != '' ORDER BY category COLLATE NOCASE"
        ).fetchall()
    ]
    source = conn.execute(
        "SELECT * FROM rss_catalog_sources ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    return {
        "total": int(totals["total"] or 0),
        "feed_count": int(totals["feed_count"] or 0),
        "route_count": int(totals["route_count"] or 0),
        "valid_count": int(totals["valid_count"] or 0),
        "limited_count": int(totals["limited_count"] or 0),
        "invalid_count": int(totals["invalid_count"] or 0),
        "category_count": int(totals["category_count"] or 0),
        "categories": categories,
        "source": _catalog_source_from_row(source),
    }


def get_feed(conn: sqlite3.Connection, feed_id: int) -> dict[str, Any] | None:
    return _feed_from_row(conn.execute("SELECT * FROM rss_feeds WHERE id=?", (feed_id,)).fetchone())


def get_feed_by_url(conn: sqlite3.Connection, feed_url: str) -> dict[str, Any] | None:
    return _feed_from_row(conn.execute("SELECT * FROM rss_feeds WHERE feed_url=?", (feed_url,)).fetchone())


def upsert_feed(
    conn: sqlite3.Connection,
    *,
    title: str,
    feed_url: str,
    site_url: str = "",
    category: str = "",
    enabled: bool = True,
    fetch_interval_minutes: int = 60,
) -> int:
    now = now_iso()
    existing = get_feed_by_url(conn, feed_url)
    if existing:
        conn.execute(
            """UPDATE rss_feeds
               SET title=?, site_url=?, category=?, enabled=?, fetch_interval_minutes=?, updated_at=?
               WHERE id=?""",
            (
                title or existing["title"],
                site_url,
                category,
                1 if enabled else 0,
                max(int(fetch_interval_minutes or 60), 5),
                now,
                existing["id"],
            ),
        )
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO rss_feeds
           (title, feed_url, site_url, category, enabled, fetch_interval_minutes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, feed_url, site_url, category, 1 if enabled else 0, max(int(fetch_interval_minutes or 60), 5), now, now),
    )
    return int(cur.lastrowid)


def update_feed_fetch_state(conn: sqlite3.Connection, feed_id: int, *, status: str, error: str = "") -> None:
    conn.execute(
        "UPDATE rss_feeds SET last_fetch_at=?, last_fetch_status=?, last_fetch_error=?, updated_at=? WHERE id=?",
        (now_iso(), status, error, now_iso(), feed_id),
    )


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> bool:
    cur = conn.execute("DELETE FROM rss_feeds WHERE id=?", (feed_id,))
    return cur.rowcount > 0


def upsert_item(
    conn: sqlite3.Connection,
    *,
    feed_id: int,
    guid: str,
    title: str,
    link: str = "",
    author: str = "",
    published_at: str = "",
    summary: str = "",
    content_html: str = "",
    preview_image: str = "",
    media: list[dict[str, object]] | None = None,
) -> int:
    now = now_iso()
    media_json = json.dumps(media or [], ensure_ascii=False)
    existing = conn.execute(
        "SELECT id FROM rss_items WHERE feed_id=? AND guid=?",
        (feed_id, guid),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE rss_items
               SET title=?, link=?, author=?, published_at=?, summary=?, content_html=?,
                   preview_image=?, media_json=?, updated_at=?
               WHERE id=?""",
            (title, link, author, published_at, summary, content_html, preview_image, media_json, now, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO rss_items
           (feed_id, guid, title, link, author, published_at, summary, content_html,
            preview_image, media_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (feed_id, guid, title, link, author, published_at, summary, content_html, preview_image, media_json, now, now),
    )
    return int(cur.lastrowid)


def list_items(conn: sqlite3.Connection, *, feed_id: int | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if feed_id is not None:
        where.append("feed_id=?")
        params.append(feed_id)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"""SELECT rss_items.*, rss_feeds.title AS feed_title, rss_feeds.feed_url
            FROM rss_items
            JOIN rss_feeds ON rss_feeds.id = rss_items.feed_id
            {where_sql}
            ORDER BY COALESCE(rss_items.published_at, rss_items.created_at) DESC, rss_items.id DESC
            LIMIT ? OFFSET ?""",
        (*params, max(min(int(limit), 200), 1), max(int(offset), 0)),
    ).fetchall()
    return [_item_from_row(row) for row in rows if row is not None]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT rss_items.*, rss_feeds.title AS feed_title, rss_feeds.feed_url
           FROM rss_items
           JOIN rss_feeds ON rss_feeds.id = rss_items.feed_id
           WHERE rss_items.id=?""",
        (item_id,),
    ).fetchone()
    return _item_from_row(row)


def set_item_article_task(conn: sqlite3.Connection, item_id: int, task_id: str) -> None:
    conn.execute("UPDATE rss_items SET article_task_id=?, updated_at=? WHERE id=?", (task_id, now_iso(), item_id))

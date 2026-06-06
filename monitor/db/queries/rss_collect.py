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


def _feed_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
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

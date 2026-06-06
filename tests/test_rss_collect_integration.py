from __future__ import annotations

import sys
from pathlib import Path
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db
import monitor.db.connection as db_connection
from monitor.db.queries import rss_collect as rss_queries
from monitor.rss_collect.parser import build_opml_document, parse_feed_xml, parse_opml_document
from monitor.rss_collect.security import validate_external_http_url
from monitor.rss_collect.service import MAX_OPML_CHARS, RssCollectService, _validate_response_peer


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(monitor_db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(monitor_db, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(monitor_db, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(monitor_db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(db_connection, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    monitor_db.init_db()
    return data_dir


RSS_XML = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>AI Updates</title>
    <link>https://example.com/</link>
    <language>en</language>
    <item>
      <title>New model release</title>
      <link>/posts/model</link>
      <guid>model-1</guid>
      <pubDate>Wed, 01 May 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>Benchmarks and rollout notes for developers.</p>]]></description>
      <media:thumbnail url="https://example.com/cover.png" />
      <enclosure url="https://example.com/audio.mp3" type="audio/mpeg" length="1234" />
    </item>
  </channel>
</rss>
"""


def test_parse_feed_xml_normalizes_rss_items_preview_and_media():
    parsed = parse_feed_xml(RSS_XML, feed_url="https://example.com/feed.xml")

    assert parsed.title == "AI Updates"
    assert parsed.link == "https://example.com/"
    assert len(parsed.items) == 1
    item = parsed.items[0]
    assert item.title == "New model release"
    assert item.link == "https://example.com/posts/model"
    assert item.summary == "Benchmarks and rollout notes for developers."
    assert item.preview_image == "https://example.com/cover.png"
    assert item.media_attachments == [
        {"url": "https://example.com/audio.mp3", "mime_type": "audio/mpeg", "size_bytes": 1234}
    ]


def test_parse_and_build_opml_preserves_categories_and_rejects_duplicates():
    opml = """<opml version="2.0"><body>
      <outline text="AI">
        <outline text="Feed A" type="rss" xmlUrl="https://example.com/a.xml" htmlUrl="https://example.com/" />
        <outline text="Feed A Copy" type="rss" xmlUrl="https://example.com/a.xml" />
      </outline>
      <outline text="Broken" type="rss" />
    </body></opml>"""

    parsed = parse_opml_document(opml)
    assert [(entry.title, entry.category, entry.xml_url) for entry in parsed.entries] == [
        ("Feed A", "AI", "https://example.com/a.xml")
    ]
    assert parsed.duplicate_items[0]["reason"] == "duplicate_in_file"
    assert parsed.invalid_items[0]["reason"] == "missing_xml_url"

    exported = build_opml_document("feeds", [{"title": "Feed A", "feed_url": "https://example.com/a.xml", "category": "AI"}])
    assert '<outline text="AI"' in exported
    assert 'xmlUrl="https://example.com/a.xml"' in exported


def test_xml_parser_rejects_entities():
    payload = """<!DOCTYPE foo [
      <!ENTITY xxe "expanded">
    ]>
    <rss version="2.0"><channel><title>&xxe;</title></channel></rss>"""

    with pytest.raises(Exception):
        parse_feed_xml(payload, feed_url="https://example.com/feed.xml")


def test_rss_service_refreshes_items_and_prepares_article_task(db_env, monkeypatch):
    service = RssCollectService()
    monkeypatch.setattr(RssCollectService, "_fetch_feed_xml", staticmethod(lambda _url: RSS_XML))

    feed = service.save_feed({"title": "Manual title", "feed_url": "https://example.com/feed.xml", "category": "AI"})
    result = service.refresh_feed(feed["id"])
    items = service.list_items(feed_id=feed["id"])

    assert result["stored"] == 1
    assert items[0]["title"] == "New model release"
    assert items[0]["feed_title"] == "AI Updates"

    payload = service.prepare_article_payload(items[0]["id"], target_lang="zh-Hans")
    task_id = monitor_db.create_article_task(
        monitor_video_id=None,
        video_id=None,
        video_url=None,
        video_title=payload["source_title"],
        source_type=payload["source_type"],
        article_text=payload["article_text"],
        source_url=payload["source_url"],
        source_title=payload["source_title"],
        rss_item_id=payload["rss_item_id"],
        target_lang=payload["target_lang"],
    )
    service.mark_item_article_task(items[0]["id"], task_id)

    task = monitor_db.get_article_task(task_id)
    linked = service.get_item(items[0]["id"])
    assert task["source_type"] == "rss_item"
    assert task["rss_item_id"] == items[0]["id"]
    assert "Benchmarks and rollout notes" in task["article_text"]
    assert linked["article_task_id"] == task_id


def test_rss_fetch_revalidates_redirect_locations(monkeypatch):
    class RedirectingOpener:
        def open(self, request, timeout=20):
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "http://127.0.0.1/feed.xml"},
                None,
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: RedirectingOpener())

    with pytest.raises(ValueError):
        RssCollectService._fetch_feed_xml("https://example.com/feed.xml")


def test_rss_peer_validation_fails_closed_without_socket():
    class ResponseWithoutSocket:
        fp = None

    with pytest.raises(RuntimeError, match="peer 校验失败"):
        _validate_response_peer(ResponseWithoutSocket())


def test_opml_import_applies_feed_url_security_policy(db_env):
    service = RssCollectService()
    result = service.import_opml(
        """<opml version="2.0"><body>
          <outline text="Local" type="rss" xmlUrl="http://127.0.0.1/feed.xml" />
          <outline text="Public" type="rss" xmlUrl="https://example.com/feed.xml" />
        </body></opml>"""
    )

    feeds = service.list_feeds()
    assert result["imported"] == 1
    assert feeds[0]["feed_url"] == "https://example.com/feed.xml"
    assert result["invalid_items"][0]["xml_url"] == "http://127.0.0.1/feed.xml"


def test_opml_import_rejects_oversized_payload(db_env):
    service = RssCollectService()

    with pytest.raises(ValueError, match="OPML 内容过大"):
        service.import_opml("x" * (MAX_OPML_CHARS + 1))


def test_init_db_bootstraps_rss_collect_schema(db_env):
    with monitor_db.get_connection() as conn:
        rss_queries.ensure_schema(conn)
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        article_cols = {row["name"] for row in conn.execute("PRAGMA table_info(article_tasks)").fetchall()}

    assert {"rss_feeds", "rss_items"} <= tables
    assert "rss_item_id" in article_cols


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/feed.xml",
        "http://127.0.0.1/feed.xml",
        "http://192.168.1.10/feed.xml",
        "ftp://example.com/feed.xml",
        "https://user:pass@example.com/feed.xml",
    ],
)
def test_rss_url_validation_blocks_unsafe_targets(url):
    with pytest.raises(ValueError):
        validate_external_http_url(url)


def test_rss_items_api_rejects_invalid_feed_id(monkeypatch):
    import server.__main__ as server_main

    handler = object.__new__(server_main.MonitorHandler)
    handler.path = "/api/rss/items?feed_id=abc"
    captured = {}

    def fake_send_json(payload, status=200):
        captured["payload"] = payload
        captured["status"] = status

    monkeypatch.setattr(handler, "_send_json", fake_send_json)

    server_main.MonitorHandler._api_rss_items(handler)

    assert captured["status"] == 400
    assert "feed_id" in captured["payload"]["error"]

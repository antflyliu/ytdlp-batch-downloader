from __future__ import annotations

import sys
from pathlib import Path
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db  # noqa: E402
import monitor.db.connection as db_connection  # noqa: E402
from monitor.db.queries import rss_collect as rss_queries  # noqa: E402
from monitor.rss_collect.parser import RssParseError, build_opml_document, parse_feed_xml, parse_opml_document  # noqa: E402
from monitor.rss_collect.security import validate_external_http_url  # noqa: E402
from monitor.rss_collect.catalog import FEED_STATUS_URL, FEEDS_OPML_URL, README_URL, RssCatalogService  # noqa: E402
from monitor.rss_collect.service import MAX_OPML_CHARS, RssCollectService, _validate_response_peer  # noqa: E402


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


ATOM_XHTML_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Updates</title>
  <link href="https://example.com/" />
  <entry>
    <title>Nested Atom content</title>
    <id>tag:example.com,2026:atom-1</id>
    <author><name>Alice</name></author>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml"><p>Hello <strong>world</strong>.</p></div>
    </content>
  </entry>
</feed>
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


def test_parse_feed_xml_preserves_nested_atom_author_and_xhtml_content():
    parsed = parse_feed_xml(ATOM_XHTML_XML, feed_url="https://example.com/feed.atom")

    item = parsed.items[0]
    assert item.author == "Alice"
    assert "Hello" in item.content_html
    assert "world" in item.content_html
    assert item.summary == "Hello world ."


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
    monkeypatch.setattr(
        "monitor.article_source_archive._default_downloader",
        lambda url: (b"asset", "image/png" if url.endswith(".png") else "audio/mpeg"),
    )

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
        article_source_path=payload["article_source_path"],
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
    assert task["article_source_path"] == payload["article_source_path"]
    assert Path(payload["article_source_path"]).is_file()
    assert "Benchmarks and rollout notes" in task["article_text"]
    assert "assets/asset-001.png" in task["article_text"]
    assert "assets/asset-002" in task["article_text"]
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


def test_rss_fetch_rejects_oversized_feed_instead_of_silently_truncating(monkeypatch):
    class Headers:
        @staticmethod
        def get_content_charset():
            return None

    class OversizedResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(size):
            return b"x" * size

    class OversizedOpener:
        @staticmethod
        def open(_request, timeout=20):
            return OversizedResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: OversizedOpener())
    monkeypatch.setattr("monitor.rss_collect.service._validate_response_peer", lambda _response: None)

    with pytest.raises(RuntimeError, match="Feed 内容过大"):
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


def test_opml_reimport_preserves_existing_feed_runtime_settings(db_env):
    service = RssCollectService()
    service.save_feed(
        {
            "title": "Existing",
            "feed_url": "https://example.com/feed.xml",
            "site_url": "https://example.com/",
            "enabled": False,
            "fetch_interval_minutes": 180,
        }
    )

    result = service.import_opml(
        """<opml version="2.0"><body>
          <outline text="Imported title" type="rss" xmlUrl="https://example.com/feed.xml" />
        </body></opml>"""
    )

    feed = service.list_feeds()[0]
    assert result["imported"] == 1
    assert feed["title"] == "Imported title"
    assert feed["enabled"] is False
    assert feed["fetch_interval_minutes"] == 180
    assert feed["site_url"] == "https://example.com/"


def test_rss_catalog_sync_stores_feeds_health_and_rsshub_routes(db_env, monkeypatch):
    service = RssCatalogService()
    opml = """<opml version="2.0"><body>
      <outline text="AI" title="AI">
        <outline text="Feed A" type="rss" xmlUrl="https://example.com/a.xml" htmlUrl="https://example.com/" />
        <outline text="Feed B" type="rss" xmlUrl="https://example.com/b.xml" />
      </outline>
    </body></opml>"""
    status = """{
      "checkTime": "2026-06-08 11:12:47 (北京时间)",
      "total": 2,
      "valid": 1,
      "invalid": 1,
      "limited": 0,
      "successRate": "50%",
      "feeds": [
        {"name": "Feed A", "url": "https://example.com/a.xml", "status": "valid", "valid": true, "limited": false, "statusCode": 200, "error": null},
        {"name": "Feed B", "url": "https://example.com/b.xml", "status": "invalid", "valid": false, "limited": false, "statusCode": 500, "error": "HTTP 500"}
      ]
    }"""
    readme = """# Awesome RSSHub Routes
## RSSHub Routes
### Social Media
#### Weibo
| Name | Route | Description |
| --- | --- | --- |
| Trending | `/weibo/search/hot` | Real-time trending |
## RSS Tooling
"""

    def fake_fetch(url):
        if url == FEEDS_OPML_URL:
            return opml
        if url == FEED_STATUS_URL:
            return status
        if url == README_URL:
            return readme
        raise AssertionError(url)

    monkeypatch.setattr(RssCatalogService, "_fetch_text", staticmethod(fake_fetch))

    result = service.sync_catalog()
    catalog = service.list_catalog()

    assert result["summary"]["feed_count"] == 2
    assert result["summary"]["route_count"] == 1
    assert result["summary"]["source"]["success_rate"] == "50%"
    feed_a = next(entry for entry in catalog["entries"] if entry["feed_url"] == "https://example.com/a.xml")
    route = next(entry for entry in catalog["entries"] if entry["entry_type"] == "rsshub_route")
    assert feed_a["status_valid"] is True
    assert feed_a["status_code"] == 200
    assert route["title"] == "Trending"
    assert route["route_template"] == "/weibo/search/hot"
    assert route["category"] == "Social Media / Weibo"


def test_rss_catalog_import_selected_feeds_persists_to_rss_feeds(db_env, monkeypatch):
    service = RssCatalogService()
    monkeypatch.setattr(
        RssCatalogService,
        "_fetch_text",
        staticmethod(
            lambda url: {
                FEEDS_OPML_URL: """<opml version="2.0"><body>
                  <outline text="AI">
                    <outline text="Feed A" type="rss" xmlUrl="https://example.com/a.xml" htmlUrl="https://example.com/" />
                  </outline>
                </body></opml>""",
                FEED_STATUS_URL: '{"feeds": []}',
                README_URL: "## RSSHub Routes\n## RSS Tooling\n",
            }[url]
        ),
    )

    service.sync_catalog()
    entry = service.list_catalog()["entries"][0]
    result = service.import_catalog_entries([entry["id"]], fetch_interval_minutes=180)

    feeds = RssCollectService().list_feeds()
    refreshed_catalog = service.list_catalog()["entries"][0]
    assert result["imported"] == 1
    assert feeds[0]["title"] == "Feed A"
    assert feeds[0]["feed_url"] == "https://example.com/a.xml"
    assert feeds[0]["category"] == "AI"
    assert feeds[0]["fetch_interval_minutes"] == 180
    assert refreshed_catalog["imported"] is True
    assert refreshed_catalog["feed_id"] == feeds[0]["id"]


def test_init_db_bootstraps_rss_collect_schema(db_env):
    with monitor_db.get_connection() as conn:
        rss_queries.ensure_schema(conn)
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        article_cols = {row["name"] for row in conn.execute("PRAGMA table_info(article_tasks)").fetchall()}

    assert {"rss_feeds", "rss_items", "rss_catalog_sources", "rss_catalog_entries"} <= tables
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


def test_rss_refresh_api_reports_invalid_feed_content_as_bad_request(monkeypatch):
    import server.__main__ as server_main

    handler = object.__new__(server_main.MonitorHandler)
    captured = {}

    def fake_refresh(_feed_id, *, max_items):
        raise RssParseError("RSS/Atom XML 解析失败")

    def fake_send_json(payload, status=200):
        captured["payload"] = payload
        captured["status"] = status

    monkeypatch.setattr(server_main._rss_collect_service, "refresh_feed", fake_refresh)
    monkeypatch.setattr(handler, "_send_json", fake_send_json)

    server_main.MonitorHandler._api_rss_feed_refresh(handler, "1", {})

    assert captured["status"] == 400
    assert captured["payload"]["error"] == "RSS/Atom XML 解析失败"



def test_rss_catalog_source_delete_decodes_url_encoded_key(db_env, monkeypatch):
    """Regression test: DELETE /api/rss/catalog/sources/custom%3Ainfobubble-support
    should decode %3A to ':' before looking up the source in the database.

    The frontend uses encodeURIComponent() which encodes ':' as '%3A'.
    The server must unquote the path segment in do_DELETE before passing
    it to the service layer. This test exercises the full do_DELETE flow.
    """
    import server.__main__ as server_main

    # 1. Add a source with key "custom:infobubble-support" (contains colon)
    source = server_main._rss_catalog_service.add_source(
        name="infobubble-support",
        feeds_url="https://example.com/feed.xml",
    )
    source_key = source["source_key"]
    assert ":" in source_key, "source_key should contain a colon for this test to be meaningful"

    # 2. Create a handler with the same URL-encoded path the frontend would send
    handler = object.__new__(server_main.MonitorHandler)
    handler.command = "DELETE"
    handler.path = f"/api/rss/catalog/sources/{source_key.replace(':', '%3A')}"

    captured = {}

    def fake_send_json(payload, status=200):
        captured["payload"] = payload
        captured["status"] = status

    monkeypatch.setattr(handler, "_check_rate_limit", lambda: True)
    monkeypatch.setattr(handler, "_send_json", fake_send_json)

    # 3. Call do_DELETE ? this will trigger the path extraction + unquote + delete
    handler.do_DELETE()

    # 4. Verify OK response (means the source was found and deleted)
    assert captured.get("status") == 200, (
        f"Expected 200 OK, got {captured.get('status')}: {captured.get('payload')}"
    )
    assert captured["payload"].get("ok") is True, (
        f"Expected ok=True, got {captured['payload']}"
    )

    # 5. Confirm source is actually deleted from DB
    gone = server_main._rss_catalog_service.get_source(source_key)
    assert gone is None, f"Source '{source_key}' should have been deleted"

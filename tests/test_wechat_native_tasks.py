from __future__ import annotations

from datetime import datetime
from pathlib import Path

from monitor.wechat_collect.models import ArticleDownload
from monitor.wechat_collect.tasks import NativeCollectionTaskService


FIXED_UPDATE_TIME = 1704067200


class FakeProvider:
    def __init__(self, *, articles=None, download_error: Exception | None = None):
        self.articles = articles
        self.download_error = download_error

    def account_by_article_url(self, article_url):
        return {"fakeid": "fakeid-1", "nickname": "测试号"}

    def list_articles(
        self,
        fakeid,
        *,
        keyword="",
        max_articles=50,
        page_size=20,
        begin=0,
        progress=None,
        cancel_check=None,
    ):
        return self.articles or [
            {
                "aid": "224_1",
                "title": "第一篇",
                "link": "https://mp.weixin.qq.com/s/first",
                "update_time": FIXED_UPDATE_TIME,
            }
        ]

    def download_article(self, article_url, export_format):
        if self.download_error:
            raise self.download_error
        return ArticleDownload(
            body=b"# first",
            content_type="text/markdown; charset=utf-8",
            title="第一篇",
            metadata={"title": "第一篇"},
        )


def _init_temp_db(monkeypatch, tmp_path):
    import monitor.db as db
    import monitor.db.connection as db_connection

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()


def test_native_collection_task_persists_results(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)

    service = NativeCollectionTaskService(provider_factory=lambda payload: FakeProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "fakeid",
            "fakeid": "fakeid-1",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)

    assert task["status"] == "done"
    assert task["success"] == 1
    assert "session_id" not in task
    assert "output_dir" not in task
    assert "path" not in task["results"][0]
    assert task["results"][0]["artifact_id"] == f"{task_id}:1"
    assert task["results"][0]["artifact_url"].endswith(f"/{task_id}%3A1")
    assert Path(service.resolve_artifact_path(task["results"][0]["artifact_id"])).is_file()


def test_native_collection_task_reports_error_when_all_downloads_fail(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)

    service = NativeCollectionTaskService(
        provider_factory=lambda payload: FakeProvider(download_error=RuntimeError("download failed"))
    )
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "fakeid",
            "fakeid": "fakeid-1",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)

    assert task["status"] == "error"
    assert task["success"] == 0
    assert task["failed"] == 1
    assert task["error"] == "全部文章导出失败"
    assert task["results"][0]["status"] == "failed"


def test_native_collection_task_does_not_overwrite_existing_output_file(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    date_part = datetime.fromtimestamp(FIXED_UPDATE_TIME).strftime("%Y%m%d")
    existing = output_dir / f"{date_part}-第一篇.md"
    existing.write_text("existing", encoding="utf-8")

    service = NativeCollectionTaskService(provider_factory=lambda payload: FakeProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "fakeid",
            "fakeid": "fakeid-1",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(output_dir),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)
    result_path = Path(service.resolve_artifact_path(task["results"][0]["artifact_id"]))

    assert task["status"] == "done"
    assert existing.read_text(encoding="utf-8") == "existing"
    assert result_path.name == f"{date_part}-第一篇-2.md"
    assert result_path.read_bytes() == b"# first"


def test_native_collection_url_mode_resolves_account_before_listing(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []
    resolved: list[str] = []
    listed: list[tuple[str, int]] = []

    class UrlProvider(FakeProvider):
        def account_by_article_url(self, article_url):
            resolved.append(article_url)
            return {"fakeid": "fakeid-from-url", "nickname": "链接账号"}

        def list_articles(
            self,
            fakeid,
            *,
            keyword="",
            max_articles=50,
            page_size=20,
            begin=0,
            progress=None,
            cancel_check=None,
        ):
            listed.append((fakeid, begin))
            return [{
                "aid": "224_url",
                "title": "链接账号文章",
                "link": "https://mp.weixin.qq.com/s/listed",
                "update_time": FIXED_UPDATE_TIME,
            }]

        def download_article(self, article_url, export_format):
            calls.append((article_url, export_format))
            return super().download_article(article_url, export_format)

    service = NativeCollectionTaskService(provider_factory=lambda payload: UrlProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "url",
            "article_url": "https://mp.weixin.qq.com/s/direct",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)

    assert task["status"] == "done"
    assert resolved == ["https://mp.weixin.qq.com/s/direct"]
    assert listed == [("fakeid-from-url", 0)]
    assert calls == [("https://mp.weixin.qq.com/s/listed", "markdown")]
    assert task["results"][0]["url"] == "https://mp.weixin.qq.com/s/listed"


def test_native_collection_urls_mode_validates_urls_before_download(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)
    calls: list[str] = []

    class UrlProvider(FakeProvider):
        def download_article(self, article_url, export_format):
            calls.append(article_url)
            return super().download_article(article_url, export_format)

    service = NativeCollectionTaskService(provider_factory=lambda payload: UrlProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "urls",
            "urls": ["https://mp.weixin.qq.com/s/ok", "https://example.test/not-mp"],
            "format": "markdown",
            "max_articles": 2,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)

    assert task["status"] == "error"
    assert "文章链接不合法" in task["error"]
    assert calls == []


def test_native_collection_passes_cancel_check_during_article_listing(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)
    seen_cancel_check = []

    class CancelAwareProvider(FakeProvider):
        def list_articles(
            self,
            fakeid,
            *,
            keyword="",
            max_articles=50,
            page_size=20,
            begin=0,
            progress=None,
            cancel_check=None,
        ):
            assert cancel_check is not None
            seen_cancel_check.append(cancel_check())
            return []

    service = NativeCollectionTaskService(provider_factory=lambda payload: CancelAwareProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "fakeid",
            "fakeid": "fakeid-1",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)

    assert seen_cancel_check == [False]


def test_native_proxy_policy_disallows_free_proxy_with_login_cookies(monkeypatch):
    from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan

    class Route:
        proxy = "http://free.example.test:8080"
        proxy_pool = None
        resolved_proxy_source = "system_free"
        provider_tier = "free"
        reason = "free"
        warnings = []
        masked_proxy_endpoint = "http://free.example.test:8080"

    def fake_resolve(account, is_auto_download=False, cookies_file_present=False, user_forced_direct=False):
        return Route()

    monkeypatch.setattr("monitor.wechat_collect.proxy_policy.proxy_router.resolve_proxy_download", fake_resolve)

    plan = resolve_native_proxy_plan({"download_proxy_mode": "system_only"}, cookies_present=True)

    assert plan.proxies == []
    assert plan.source == "direct"
    assert "Cookie" in " ".join(plan.warnings)


def test_native_proxy_policy_uses_auto_mode_for_unsaved_native_context(monkeypatch):
    from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan

    seen = {}

    class Route:
        proxy = None
        proxy_pool = None
        resolved_proxy_source = "direct"
        provider_tier = ""
        reason = "direct"
        warnings = []

    def fake_resolve(account, is_auto_download=False, cookies_file_present=False, user_forced_direct=False):
        seen["account"] = account
        seen["cookies_file_present"] = cookies_file_present
        return Route()

    monkeypatch.setattr("monitor.wechat_collect.proxy_policy.proxy_router.resolve_proxy_download", fake_resolve)

    plan = resolve_native_proxy_plan(cookies_present=True)

    assert plan.source == "direct"
    assert seen["account"]["download_proxy_mode"] == "auto"
    assert seen["cookies_file_present"] is True

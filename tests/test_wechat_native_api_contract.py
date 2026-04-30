from __future__ import annotations

from pathlib import Path
import importlib

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"


def _patch_monitor_db_paths(monkeypatch, db_path: Path, data_dir: Path) -> None:
    import monitor.db as db
    import monitor.db.connection as db_connection

    schema_path = ROOT / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()


def test_wechat_native_routes_are_wired():
    server = SERVER_MAIN.read_text(encoding="utf-8")

    for snippet in [
        '"/api/wechat-native/config"',
        '"/api/wechat-native/login/start"',
        '"/api/wechat-native/login/"',
        '"/api/wechat-native/sessions"',
        '"/api/wechat-native/accounts/search"',
        '"/api/wechat-native/accounts/by-url"',
        '"/api/wechat-native/articles/preview"',
        '"/api/wechat-native/articles/cache"',
        '"/api/wechat-native/tasks/start"',
        '"/api/wechat-native/tasks"',
        '"/api/wechat-native/artifacts/"',
    ]:
        assert snippet in server


def test_wechat_native_imports_do_not_replace_exporter_routes():
    server = SERVER_MAIN.read_text(encoding="utf-8")

    assert "monitor.wechat_collector" in server
    assert '"/api/wechat-collect/start"' in server
    assert "monitor.wechat_collect.native_login" in server
    assert "monitor.wechat_collect.tasks" in server


def test_wechat_native_session_errors_are_structured():
    server = SERVER_MAIN.read_text(encoding="utf-8")

    assert "def _send_wechat_native_error" in server
    assert "session_expired" in server
    assert "provider.check_session()" in server


def test_wechat_native_logout_uses_provider_and_task_api_uses_public_serializer():
    server = SERVER_MAIN.read_text(encoding="utf-8")
    task_service = (ROOT / "monitor" / "wechat_collect" / "tasks.py").read_text(encoding="utf-8")
    serializer = (ROOT / "monitor" / "wechat_collect" / "serializers.py").read_text(encoding="utf-8")

    assert "provider.logout()" in server
    assert "resolve_artifact_path" in server
    assert "_api_wechat_native_artifact" in server
    assert "public_task" in task_service
    assert '"artifact_id"' in serializer
    public_task_body = serializer.split("def public_task", 1)[1]
    assert '"output_dir"' not in public_task_body
    assert '"session_id"' not in public_task_body


def test_wechat_native_artifact_endpoint_serves_resolved_file(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    collect_root = tmp_path / "wechat-collect"
    collect_root.mkdir()
    article = collect_root / "article.md"
    article.write_text("# article", encoding="utf-8")
    captured: dict[str, object] = {"headers": [], "body": b""}

    class FakeTaskService:
        def resolve_artifact_path(self, artifact_id):
            captured["artifact_id"] = artifact_id
            return str(article)

    class FakeWriter:
        def write(self, value):
            captured["body"] = captured["body"] + value

    handler = object.__new__(server.MonitorHandler)
    handler.wfile = FakeWriter()
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})
    handler._allowed_origin = lambda: None
    handler.send_response = lambda status: captured.update({"response": status})
    handler.send_header = lambda key, value: captured["headers"].append((key, value))
    handler.end_headers = lambda: captured.update({"ended": True})

    monkeypatch.setattr(server, "_wechat_native_task_service", FakeTaskService())
    monkeypatch.setattr(server._db, "load_config", lambda: {"wechat_collection_output_dir": str(collect_root)})

    handler._api_wechat_native_artifact("wcn_test:1")

    assert captured["artifact_id"] == "wcn_test:1"
    assert captured["response"] == 200
    assert captured["body"] == b"# article"
    assert any(key == "Content-Type" and value.startswith("text/markdown") for key, value in captured["headers"])
    assert any(key == "Content-Disposition" and value.startswith("attachment;") for key, value in captured["headers"])
    assert ("X-Content-Type-Options", "nosniff") in captured["headers"]


def test_wechat_native_artifact_endpoint_rejects_file_outside_output_dir(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    collect_root = tmp_path / "wechat-collect"
    collect_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# outside", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeTaskService:
        def resolve_artifact_path(self, artifact_id):
            captured["artifact_id"] = artifact_id
            return str(outside)

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "_wechat_native_task_service", FakeTaskService())
    monkeypatch.setattr(server._db, "load_config", lambda: {"wechat_collection_output_dir": str(collect_root)})

    handler._api_wechat_native_artifact("wcn_test:1")

    assert captured["artifact_id"] == "wcn_test:1"
    assert captured["status"] == 400
    assert captured["payload"] == {"error": "无效的公众号采集结果路径"}


def test_wechat_native_session_check_executes_with_proxy_plan(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    proxy_plan = object()

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            captured["session_id"] = session_id
            captured["store"] = store
            captured["proxy_plan"] = proxy_plan

        def check_session(self):
            return {"ok": True}

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", lambda account=None, *, cookies_present=False: proxy_plan)

    handler._api_wechat_native_session_check("sess-1")

    assert captured["session_id"] == "sess-1"
    assert captured["proxy_plan"] is proxy_plan
    assert captured["payload"] == {"ok": True}
    assert captured["status"] == 200


def test_wechat_native_preview_refreshes_upstream_once_then_pages_from_cache(monkeypatch, tmp_path):
    import monitor.db.queries.wechat_collect as queries

    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    _patch_monitor_db_paths(monkeypatch, tmp_path / "monitor.db", tmp_path / "data")

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            captured["session_id"] = session_id
            captured["list_calls"] = []

        def account_by_article_url(self, article_url):
            captured["article_url"] = article_url
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
            captured["list_calls"].append((fakeid, keyword, max_articles, page_size, begin))
            return [
                {
                    "aid": f"aid-{idx}",
                    "title": f"来自账号列表 {idx}",
                    "link": f"https://mp.weixin.qq.com/s/listed-{idx}",
                    "author_name": "链接账号",
                    "update_time": 1_800_000_000 - idx,
                }
                for idx in range(12)
            ]

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", lambda account=None, *, cookies_present=False: object())

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "article_url": "https://mp.weixin.qq.com/s/direct",
        "begin": 0,
        "page_size": 5,
        "max_articles": 12,
    })

    assert captured["status"] == 200
    assert captured["session_id"] == "sess-1"
    assert captured["article_url"] == "https://mp.weixin.qq.com/s/direct"
    assert captured["list_calls"] == [("fakeid-from-url", "", 12, 20, 0)]
    payload = captured["payload"]
    assert payload["account"]["fakeid"] == "fakeid-from-url"
    assert "raw_json" not in payload["account"]
    assert len(payload["articles"]) == 5
    assert payload["articles"][0]["link"] == "https://mp.weixin.qq.com/s/listed-0"
    for article in payload["articles"]:
        assert "raw_json" not in article
        assert "local_path" not in article
        assert "export_format" not in article
        assert "status" not in article
        assert "id" not in article
    assert payload["total_count"] == 12
    assert payload["begin"] == 0
    assert payload["page_size"] == 5
    assert payload["source"] == "upstream_refresh"
    assert queries.get_account("fakeid-from-url")["nickname"] == "链接账号"
    assert queries.count_articles("fakeid-from-url") == 12
    queries.upsert_article(
        "fakeid-from-url",
        {
            "aid": "aid-0",
            "title": "来自账号列表 0",
            "link": "https://mp.weixin.qq.com/s/listed-0",
            "update_time": 1_800_000_000,
        },
        local_path=str(tmp_path / "secret.md"),
        export_format="markdown",
        status="downloaded",
    )

    handler._api_wechat_native_cached_articles({
        "fakeid": "fakeid-from-url",
        "begin": 0,
        "page_size": 10,
    })

    assert captured["status"] == 200
    assert captured["list_calls"] == [("fakeid-from-url", "", 12, 20, 0)]
    assert len(captured["payload"]["articles"]) == 10
    assert captured["payload"]["source"] == "local_cache"
    cached_account = captured["payload"]["account"]
    assert "raw_json" not in cached_account
    for article in captured["payload"]["articles"]:
        assert "raw_json" not in article
        assert "local_path" not in article
        assert "export_format" not in article
        assert "status" not in article
        assert "id" not in article


def test_wechat_native_preview_persists_only_public_selected_account_metadata(monkeypatch, tmp_path):
    import monitor.db.queries.wechat_collect as queries

    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    _patch_monitor_db_paths(monkeypatch, tmp_path / "monitor.db", tmp_path / "data")

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            pass

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
            return [{
                "aid": "aid-1",
                "title": "保留账号元数据",
                "link": "https://mp.weixin.qq.com/s/metadata",
                "update_time": 1_800_000_000,
            }]

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", lambda account=None, *, cookies_present=False: object())

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "fakeid": "fakeid-selected",
        "account_name": "选中的公众号",
        "account": {
            "fakeid": "fakeid-selected",
            "nickname": "搜索结果名称",
            "alias": "alias-selected",
            "round_head_img": "https://img.example/avatar.png",
            "article_biz": "biz-from-search",
            "token": "must-not-persist",
            "cookies": [{"name": "session", "value": "must-not-persist"}],
            "api_token": "must-not-persist",
            "custom_field": "must-not-persist",
        },
        "page_size": 5,
        "max_articles": 1,
    })

    assert captured["status"] == 200
    saved = queries.get_account("fakeid-selected")
    assert saved["nickname"] == "选中的公众号"
    assert saved["alias"] == "alias-selected"
    assert saved["round_head_img"] == "https://img.example/avatar.png"
    assert saved["article_biz"] == "biz-from-search"
    assert "token" not in saved["raw_json"]
    assert "cookies" not in saved["raw_json"]
    assert "api_token" not in saved["raw_json"]
    assert "custom_field" not in saved["raw_json"]
    public_account = captured["payload"]["account"]
    assert public_account["nickname"] == "选中的公众号"
    assert public_account["alias"] == "alias-selected"
    assert public_account["article_biz"] == "biz-from-search"
    assert "raw_json" not in public_account
    assert "token" not in public_account
    assert "cookies" not in public_account
    assert "api_token" not in public_account

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "fakeid": "fakeid-selected",
        "account_name": "二次预览名称",
        "page_size": 5,
        "max_articles": 1,
    })

    saved = queries.get_account("fakeid-selected")
    assert saved["nickname"] == "二次预览名称"
    assert saved["alias"] == "alias-selected"
    assert saved["article_biz"] == "biz-from-search"
    assert "custom_field" not in saved["raw_json"]


def test_wechat_native_preview_refresh_preserves_downloaded_article_state(monkeypatch, tmp_path):
    import monitor.db.queries.wechat_collect as queries

    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    _patch_monitor_db_paths(monkeypatch, tmp_path / "monitor.db", tmp_path / "data")

    queries.upsert_account({"fakeid": "fakeid-downloaded", "nickname": "已采集公众号"})
    queries.upsert_article(
        "fakeid-downloaded",
        {
            "aid": "aid-downloaded",
            "title": "旧标题",
            "link": "https://mp.weixin.qq.com/s/downloaded",
            "update_time": 1_700_000_000,
        },
        local_path=str(tmp_path / "downloaded.md"),
        export_format="markdown",
        status="downloaded",
    )

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            pass

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
            return [{
                "aid": "aid-downloaded",
                "title": "刷新后的标题",
                "link": "https://mp.weixin.qq.com/s/downloaded",
                "update_time": 1_800_000_000,
            }]

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", lambda account=None, *, cookies_present=False: object())

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "fakeid": "fakeid-downloaded",
        "page_size": 5,
        "max_articles": 1,
    })

    saved = queries.list_articles("fakeid-downloaded", limit=1)[0]
    assert captured["status"] == 200
    assert saved["title"] == "刷新后的标题"
    assert saved["status"] == "downloaded"
    assert saved["local_path"] == str(tmp_path / "downloaded.md")
    assert saved["export_format"] == "markdown"


def test_wechat_native_invalid_preview_error_is_structured():
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "article_url": "not-a-url",
    })

    assert captured["status"] == 400
    assert "文章链接不合法" in captured["payload"]["error"]


def test_wechat_native_start_rejects_invalid_article_url_before_creating_task():
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    handler._api_wechat_native_start({
        "session_id": "sess-1",
        "article_url": "https://example.test/not-mp",
    })

    assert captured["status"] == 400
    assert captured["payload"]["error"] == "文章链接不合法"


def test_wechat_native_start_rejects_invalid_urls_array_before_creating_task():
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    handler._api_wechat_native_start({
        "session_id": "sess-1",
        "urls": ["https://mp.weixin.qq.com/s/ok", "https://example.test/not-mp"],
    })

    assert captured["status"] == 400
    assert captured["payload"]["error"] == "文章链接不合法"


def test_wechat_native_start_rejects_non_array_urls_before_creating_task():
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    handler._api_wechat_native_start({
        "session_id": "sess-1",
        "urls": "https://mp.weixin.qq.com/s/ok",
    })

    assert captured["status"] == 400
    assert captured["payload"]["error"] == "urls 必须是文章链接数组"


def test_wechat_native_logout_missing_session_returns_error(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    def missing_provider(*args, **kwargs):
        raise server.WechatSessionError("session missing")

    monkeypatch.setattr(server.MonitorHandler, "_wechat_native_provider", lambda self, session_id: missing_provider())

    handler._api_wechat_native_session_logout("missing-session")

    assert captured["status"] == 401
    assert captured["payload"]["error"] == "session missing"


def test_wechat_native_proxy_context_does_not_forward_request_proxy_overrides(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}
    proxy_plan = object()

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            captured["session_id"] = session_id
            captured["proxy_plan"] = proxy_plan

        def search_accounts(self, keyword, *, begin=0, size=5):
            return []

    def capture_proxy_context(account=None, *, cookies_present=False):
        captured["proxy_context"] = account
        captured["cookies_present"] = cookies_present
        return proxy_plan

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})
    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", capture_proxy_context)

    handler._api_wechat_native_accounts_search({
        "session_id": "sess-1",
        "keyword": "测试号",
        "download_proxy_mode": "system_only",
        "proxy_pool_id": "attacker-controlled",
        "proxy_enabled": True,
    })

    assert captured["status"] == 200
    assert captured["proxy_plan"] is proxy_plan
    assert captured["cookies_present"] is True
    assert captured["proxy_context"] == {}

from __future__ import annotations

from pathlib import Path
import importlib

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"


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


def test_wechat_native_preview_url_mode_resolves_account_and_lists_page(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, *, session_id, store=None, proxy_plan=None):
            captured["session_id"] = session_id

        def account_by_article_url(self, article_url):
            captured["article_url"] = article_url
            return {"fakeid": "fakeid-from-url", "nickname": "链接账号"}

        def list_article_page(self, fakeid, *, keyword="", begin=0, page_size=20):
            captured["page_args"] = (fakeid, keyword, begin, page_size)
            return {
                "articles": [{"title": "来自账号列表", "link": "https://mp.weixin.qq.com/s/listed"}],
                "begin": begin,
                "page_size": page_size,
                "next_begin": None,
                "has_more": False,
                "total_count": 1,
            }

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "NativeMpProvider", FakeProvider)
    monkeypatch.setattr(server, "resolve_native_proxy_plan", lambda account=None, *, cookies_present=False: object())

    handler._api_wechat_native_preview({
        "session_id": "sess-1",
        "article_url": "https://mp.weixin.qq.com/s/direct",
        "begin": 20,
        "page_size": 10,
    })

    assert captured["status"] == 200
    assert captured["session_id"] == "sess-1"
    assert captured["article_url"] == "https://mp.weixin.qq.com/s/direct"
    assert captured["page_args"] == ("fakeid-from-url", "", 20, 10)
    payload = captured["payload"]
    assert payload["account"]["fakeid"] == "fakeid-from-url"
    assert payload["articles"][0]["link"] == "https://mp.weixin.qq.com/s/listed"
    assert payload["begin"] == 20
    assert payload["page_size"] == 10


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

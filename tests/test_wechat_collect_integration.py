from __future__ import annotations

import json
from pathlib import Path

from monitor.wechat_collector import (
    HttpPayload,
    WechatCollectionTaskManager,
    WechatExporterClient,
    resolve_collection_output_dir,
    run_collection,
)

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"
CONFIG_API = ROOT / "frontend-vue" / "src" / "api" / "config.ts"
ROUTER = ROOT / "frontend-vue" / "src" / "router" / "index.ts"
SIDER = ROOT / "frontend-vue" / "src" / "components" / "layout" / "AppSider.vue"


def _json_payload(data: dict) -> HttpPayload:
    return HttpPayload(
        status=200,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
    )


def test_wechat_exporter_client_lists_articles_with_auth_header():
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str], timeout: int) -> HttpPayload:
        calls.append((url, headers))
        assert timeout == 30
        return _json_payload(
            {
                "base_resp": {"ret": 0, "err_msg": "ok"},
                "articles": [
                    {"title": "A", "link": "https://mp.weixin.qq.com/s?__biz=x&mid=1", "update_time": 1},
                    {"title": "B", "link": "https://mp.weixin.qq.com/s?__biz=x&mid=2", "update_time": 2},
                ],
            }
        )

    client = WechatExporterClient(
        base_url="https://down.mptext.top",
        auth_key="auth-key",
        transport=transport,
    )

    articles = client.list_articles("fakeid", max_articles=2, page_size=5)

    assert [item["title"] for item in articles] == ["A", "B"]
    assert calls[0][1]["X-Auth-Key"] == "auth-key"
    assert "/api/public/v1/article" in calls[0][0]
    assert "fakeid=fakeid" in calls[0][0]


def test_run_collection_resolves_account_and_writes_markdown_files(tmp_path):
    def transport(url: str, headers: dict[str, str], timeout: int) -> HttpPayload:
        if "/api/public/v1/accountbyurl" in url:
            return _json_payload(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "list": [{"fakeid": "fakeid-1", "nickname": "测试号"}],
                }
            )
        if "/api/public/v1/article" in url:
            return _json_payload(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "articles": [
                        {
                            "title": "第一篇",
                            "link": "https://mp.weixin.qq.com/s?__biz=x&mid=1",
                            "update_time": 1777210218,
                        },
                        {
                            "title": "第二篇",
                            "link": "https://mp.weixin.qq.com/s?__biz=x&mid=2",
                            "update_time": 1777210219,
                        },
                    ],
                }
            )
        if "/api/public/v1/download" in url:
            return HttpPayload(
                status=200,
                headers={"content-type": "text/markdown; charset=utf-8"},
                body=b"# exported",
            )
        raise AssertionError(url)

    output_dir = resolve_collection_output_dir(None, str(tmp_path))
    manager = WechatCollectionTaskManager()
    task_id = manager.create_task({}, output_dir)
    client = WechatExporterClient(auth_key="auth-key", transport=transport)

    run_collection(
        task_id=task_id,
        task_manager=manager,
        client=client,
        output_dir=output_dir,
        payload={
            "article_url": "https://mp.weixin.qq.com/s?__biz=x&mid=1",
            "format": "markdown",
            "max_articles": 2,
            "delay_seconds": 0,
        },
    )

    task = manager.get_task(task_id)
    assert task["status"] == "done"
    assert task["success"] == 2
    assert len(list(tmp_path.glob("*.md"))) == 2


def test_wechat_collect_routes_and_frontend_nav_are_wired():
    server = SERVER_MAIN.read_text(encoding="utf-8")
    router = ROUTER.read_text(encoding="utf-8")
    sider = SIDER.read_text(encoding="utf-8")
    config_api = CONFIG_API.read_text(encoding="utf-8")

    for snippet in [
        '"/api/wechat-collect/config"',
        '"/api/wechat-collect/preview"',
        '"/api/wechat-collect/start"',
        '"/api/wechat-collect/tasks"',
        '"/api/wechat-collect/auth/check"',
        '"wechat_exporter_auth_key"',
    ]:
        assert snippet in server
    assert "/wechat-collect" in router
    assert "WechatCollect.vue" in router
    assert "wechatCollect" in sider
    assert "wechat_exporter_auth_key?: string" in config_api


def test_wechat_collect_config_masks_and_preserves_auth_key(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "wechat_exporter_auth_key": "collector-secret",
            "wechat_exporter_base_url": "https://down.mptext.top",
        },
    )

    server_main.MonitorHandler._api_config(handler)

    assert sent[0][0]["wechat_exporter_auth_key"] == "***"

    merged = server_main._preserve_masked_config_values(
        {"wechat_exporter_auth_key": "***"},
        {"wechat_exporter_auth_key": "collector-secret"},
    )
    assert merged["wechat_exporter_auth_key"] == "collector-secret"


def test_wechat_exporter_auth_key_is_encrypted_at_rest(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    import config.encryption as encryption
    import config.settings as settings

    cfg_path = tmp_path / "config.json"
    data_dir = tmp_path / "data"
    pkg_dir = tmp_path / "pkg"
    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "get_config_path", lambda: str(cfg_path))
    monkeypatch.setattr(settings, "get_data_dir", lambda: str(data_dir))
    monkeypatch.setattr(settings, "get_pkg_dir", lambda: str(pkg_dir))
    monkeypatch.setattr(encryption, "_get_webhook_enc_key", lambda: key)

    cfg = settings._config_default()
    cfg["wechat_exporter_auth_key"] = "collector-secret"

    settings.save_config(cfg)

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["wechat_exporter_auth_key"] != "collector-secret"
    assert raw["wechat_exporter_auth_key"].startswith("enc:")
    assert settings.load_config()["wechat_exporter_auth_key"] == "collector-secret"

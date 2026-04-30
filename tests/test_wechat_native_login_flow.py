from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor.wechat_collect.errors import WechatLoginError
from monitor.wechat_collect.native_login import NativeLoginManager


class FakeResponse:
    def __init__(self, payload=None, content=b"", headers=None, status_code=200):
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code
        self.text = json.dumps(payload or {}, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.cookies = {"uuid": "uuid-cookie", "bizuin": "biz-cookie"}

    def post(self, url, params=None, data=None, headers=None, timeout=None, proxies=None):
        self.calls.append(("POST", url, params, data, proxies))
        if params and params.get("action") == "startlogin":
            return FakeResponse({"base_resp": {"ret": 0, "err_msg": "ok"}})
        if params and params.get("action") == "login":
            return FakeResponse({"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?t=home/index&token=token-123"})
        raise AssertionError((url, params, data))

    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append(("GET", url, params, None, proxies))
        if params and params.get("action") == "getqrcode":
            return FakeResponse(content=b"png-bytes", headers={"Content-Type": "image/png"})
        if params and params.get("action") == "ask":
            return FakeResponse({"base_resp": {"ret": 0}, "status": 1, "acct_size": 1})
        if "cgi-bin/home" in url:
            html = 'wx.cgiData.nick_name = "测试号"; wx.cgiData.head_img = "https://example.test/head.png";'
            return FakeResponse(content=html.encode("utf-8"))
        raise AssertionError((url, params))


def test_native_login_manager_completes_qr_login(monkeypatch, tmp_path):
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

    manager = NativeLoginManager(session_factory=FakeSession)

    started = manager.start_login()
    qrcode = manager.get_qrcode(started["login_id"])
    scan = manager.poll_scan(started["login_id"])
    confirmed = manager.confirm_login(started["login_id"])

    assert qrcode.body == b"png-bytes"
    assert scan["status"] == 1
    assert confirmed["session_id"]
    assert confirmed["nickname"] == "测试号"


def test_native_login_pending_sessions_expire():
    manager = NativeLoginManager(session_factory=FakeSession, pending_ttl_seconds=0)

    started = manager.start_login()

    with pytest.raises(WechatLoginError, match="已过期"):
        manager.get_qrcode(started["login_id"])


def test_native_login_manager_reuses_proxy_plan_for_pending_login():
    sessions: list[FakeSession] = []
    proxies = {"http": "http://proxy.example.test:8080", "https": "http://proxy.example.test:8080"}

    class ProxyPlan:
        requests_proxies = proxies

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    class Store:
        def save_session(self, **kwargs):
            return "sess-proxy"

    manager = NativeLoginManager(
        session_factory=session_factory,
        store=Store(),
        proxy_plan_factory=lambda: ProxyPlan(),
    )

    started = manager.start_login()
    manager.get_qrcode(started["login_id"])
    manager.poll_scan(started["login_id"])
    manager.confirm_login(started["login_id"])

    assert sessions
    assert [call[4] for call in sessions[0].calls] == [proxies, proxies, proxies, proxies, proxies]

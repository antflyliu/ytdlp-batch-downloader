from __future__ import annotations

import json

import pytest

from monitor.wechat_collect.errors import WechatUpstreamError
from monitor.wechat_collect.html_export import export_article_html
from monitor.wechat_collect.models import NativeSession, normalize_account_preview, normalize_article_preview
from monitor.wechat_collect.native_client import NativeMpClient
from monitor.wechat_collect.providers import NativeMpProvider


def test_normalize_account_preview_keeps_safe_fields_only():
    raw = {
        "fakeid": "MzTest==",
        "nickname": "测试公众号",
        "alias": "test_alias",
        "round_head_img": "https://example.test/head.png",
        "signature": "hello",
        "secret": "must-not-leak",
    }

    preview = normalize_account_preview(raw)

    assert preview == {
        "fakeid": "MzTest==",
        "nickname": "测试公众号",
        "alias": "test_alias",
        "round_head_img": "https://example.test/head.png",
        "service_type": None,
        "signature": "hello",
        "verify_status": None,
    }


def test_normalize_article_preview_accepts_wechat_article_shape():
    raw = {
        "aid": "224_1",
        "title": "标题",
        "link": "https://mp.weixin.qq.com/s/test",
        "cover": "https://example.test/cover.jpg",
        "author_name": "作者",
        "update_time": 1777210218,
        "create_time": 1777210000,
        "digest": "摘要",
    }

    preview = normalize_article_preview(raw)

    assert preview["aid"] == "224_1"
    assert preview["title"] == "标题"
    assert preview["link"] == "https://mp.weixin.qq.com/s/test"
    assert preview["update_time"] == 1777210218


class FakeMpResponse:
    def __init__(
        self,
        payload=None,
        *,
        text: str | None = None,
        content: bytes = b"",
        headers: dict | None = None,
        status_code: int = 200,
    ):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {}, ensure_ascii=False)
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        return None


class FakeMpSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        if "searchbiz" in url:
            return FakeMpResponse(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "list": [{"fakeid": "fakeid-1", "nickname": "测试号"}],
                    "total": 1,
                }
            )
        if "appmsgpublish" in url:
            return FakeMpResponse(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "publish_page": json.dumps(
                        {
                            "total_count": 1,
                            "publish_list": [
                                {
                                    "publish_info": json.dumps(
                                        {
                                            "appmsgex": [
                                                {
                                                    "aid": "224_1",
                                                    "title": "文章",
                                                    "link": "https://mp.weixin.qq.com/s/test",
                                                    "update_time": 1777210218,
                                                }
                                            ]
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        if "logout" in url:
            return FakeMpResponse({"base_resp": {"ret": 0, "err_msg": "ok"}}, status_code=200)
        raise AssertionError((url, params))


def test_native_mp_client_searches_accounts_and_lists_articles():
    native_session = NativeSession(
        session_id="sess",
        token="token-123",
        cookies=[{"name": "bizuin", "value": "cookie-value", "domain": "", "path": "/"}],
    )
    fake_http = FakeMpSession()
    client = NativeMpClient(native_session, http_session=fake_http)

    accounts = client.search_accounts("测试")
    articles = client.list_articles("fakeid-1", max_articles=1, page_size=5)

    assert accounts[0]["fakeid"] == "fakeid-1"
    assert articles[0]["title"] == "文章"
    assert fake_http.calls[0][1]["token"] == "token-123"


def test_native_mp_client_threads_proxy_plan_to_mp_requests():
    proxies = {"http": "http://proxy.example.test:8080", "https": "http://proxy.example.test:8080"}

    class ProxyPlan:
        requests_proxies = proxies

    native_session = NativeSession(
        session_id="sess",
        token="token-123",
        cookies=[{"name": "bizuin", "value": "cookie-value", "domain": "", "path": "/"}],
    )
    fake_http = FakeMpSession()
    client = NativeMpClient(native_session, http_session=fake_http, proxy_plan=ProxyPlan())

    client.search_accounts("测试")
    client.list_articles("fakeid-1", max_articles=1, page_size=5)

    assert fake_http.calls[0][3] == proxies
    assert fake_http.calls[1][3] == proxies


class RepeatedArticlePageSession(FakeMpSession):
    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        if "appmsgpublish" not in url:
            raise AssertionError((url, params))
        if len(self.calls) > 2:
            raise AssertionError("list_articles should stop when a full page adds no new links")
        return FakeMpResponse(
            {
                "base_resp": {"ret": 0, "err_msg": "ok"},
                "publish_page": json.dumps(
                    {
                        "total_count": 0,
                        "publish_list": [
                            {
                                "publish_info": json.dumps(
                                    {
                                        "appmsgex": [
                                            {
                                                "aid": "224_repeat",
                                                "title": "重复文章",
                                                "link": "https://mp.weixin.qq.com/s/repeated",
                                                "update_time": 1777210218,
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        )


def test_native_mp_client_stops_when_full_page_adds_no_new_links():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    fake_http = RepeatedArticlePageSession()
    client = NativeMpClient(native_session, http_session=fake_http)

    articles = client.list_articles("fakeid-1", max_articles=5, page_size=1)

    assert len(articles) == 1
    assert len(fake_http.calls) == 2


class TotalCountArticlePageSession(FakeMpSession):
    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        if len(self.calls) > 2:
            raise AssertionError("list_articles should stop at total_count")
        index = len(self.calls)
        return FakeMpResponse(
            {
                "base_resp": {"ret": 0, "err_msg": "ok"},
                "publish_page": json.dumps(
                    {
                        "total_count": 2,
                        "publish_list": [
                            {
                                "publish_info": json.dumps(
                                    {
                                        "appmsgex": [
                                            {
                                                "aid": f"224_{index}",
                                                "title": f"文章{index}",
                                                "link": f"https://mp.weixin.qq.com/s/{index}",
                                                "update_time": 1777210218,
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        )


def test_native_mp_client_stops_at_total_count():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    fake_http = TotalCountArticlePageSession()
    client = NativeMpClient(native_session, http_session=fake_http)

    articles = client.list_articles("fakeid-1", max_articles=5, page_size=1)

    assert [item["title"] for item in articles] == ["文章1", "文章2"]
    assert len(fake_http.calls) == 2


def test_native_mp_client_cancel_check_stops_between_pages():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    fake_http = TotalCountArticlePageSession()
    client = NativeMpClient(native_session, http_session=fake_http)
    checks = []

    def cancel_check():
        checks.append(True)
        return len(checks) > 1

    articles = client.list_articles("fakeid-1", max_articles=5, page_size=1, cancel_check=cancel_check)

    assert [item["title"] for item in articles] == ["文章1"]
    assert len(fake_http.calls) == 1


class ExpiredSearchSession(FakeMpSession):
    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        return FakeMpResponse({"base_resp": {"ret": 200003, "err_msg": "invalid token"}})


def test_native_mp_client_marks_auth_retcode_as_session_expired():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    client = NativeMpClient(native_session, http_session=ExpiredSearchSession())

    with pytest.raises(WechatUpstreamError) as exc_info:
        client.search_accounts("测试")

    assert exc_info.value.session_expired is True
    assert exc_info.value.code == 200003


class MalformedArticlePageSession(FakeMpSession):
    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        return FakeMpResponse({"base_resp": {"ret": 0, "err_msg": "ok"}, "publish_page": "{bad-json"})


def test_native_mp_client_wraps_malformed_article_payload():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    client = NativeMpClient(native_session, http_session=MalformedArticlePageSession())

    with pytest.raises(WechatUpstreamError, match="响应结构解析失败"):
        client.list_articles("fakeid-1", max_articles=1)


class HomeCheckSession(FakeMpSession):
    def __init__(self, *, logged_out: bool = False):
        super().__init__()
        self.logged_out = logged_out

    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        if self.logged_out:
            return FakeMpResponse(text="<html>login 扫码登录</html>")
        return FakeMpResponse(text='wx.cgiData.nick_name = "测试号"; wx.cgiData.head_img = "https://example.test/head.png";')


def test_native_mp_client_checks_session_against_mp_home():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    client = NativeMpClient(native_session, http_session=HomeCheckSession())

    result = client.check_session()

    assert result["ok"] is True
    assert result["nickname"] == "测试号"


def test_native_mp_client_check_session_detects_logged_out_page():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    client = NativeMpClient(native_session, http_session=HomeCheckSession(logged_out=True))

    with pytest.raises(WechatUpstreamError) as exc_info:
        client.check_session()

    assert exc_info.value.session_expired is True


class LoginPageJsonSession(FakeMpSession):
    def get(self, url, params=None, headers=None, timeout=None, proxies=None):
        self.calls.append((url, params, headers, proxies))
        return FakeMpResponse(
            None,
            text="<html><title>login</title><body>扫码登录</body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )


def test_native_mp_client_marks_login_page_json_response_as_session_expired():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    client = NativeMpClient(native_session, http_session=LoginPageJsonSession())

    with pytest.raises(WechatUpstreamError) as exc_info:
        client.search_accounts("测试")

    assert exc_info.value.session_expired is True


def test_native_mp_client_logout_calls_mp_logout_endpoint():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    fake_http = FakeMpSession()
    client = NativeMpClient(native_session, http_session=fake_http)

    result = client.logout()

    assert result["ok"] is True
    assert "logout" in fake_http.calls[-1][0]
    assert fake_http.calls[-1][1]["token"] == "token-123"


def test_export_article_html_outputs_html_text_markdown_and_json():
    raw_html = """
    <html><body>
      <div id="js_article">
        <h1 id="activity-name">标题</h1>
        <div id="js_content" style="visibility:hidden">
          <p>第一段</p><p><img data-src="https://example.test/a.jpg"></p>
        </div>
      </div>
      <script>window.secret = 1;</script>
    </body></html>
    """

    html_result = export_article_html(raw_html, "html")
    text_result = export_article_html(raw_html, "text")
    markdown_result = export_article_html(raw_html, "markdown")
    json_result = export_article_html(raw_html, "json")

    assert b"js_content" in html_result.body
    assert b"script" not in html_result.body.lower()
    assert "第一段" in text_result.body.decode("utf-8")
    assert "第一段" in markdown_result.body.decode("utf-8")
    assert json_result.metadata["title"] == "标题"


def test_export_article_html_extracts_author_from_markup_variants():
    raw_html = """
    <html><head><meta name="author" content=" 测&nbsp;试 号 "></head><body>
      <div id="js_article">
        <h1 id="activity-name">标题</h1>
        <div id="js_content"><p>正文</p></div>
      </div>
    </body></html>
    """

    result = export_article_html(raw_html, "json")

    assert result.metadata["author"] == "测试号"


def test_native_provider_uses_session_store_and_client(monkeypatch):
    native_session = NativeSession(
        session_id="sess",
        token="token-123",
        cookies=[{"name": "bizuin", "value": "cookie-value", "domain": "", "path": "/"}],
    )

    class Store:
        def get_session(self, session_id):
            assert session_id == "sess"
            return native_session

    fake_http = FakeMpSession()
    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=fake_http)

    accounts = provider.search_accounts("测试")
    articles = provider.list_articles("fakeid-1", max_articles=1)

    assert accounts[0]["nickname"] == "测试号"
    assert articles[0]["link"] == "https://mp.weixin.qq.com/s/test"


def test_native_provider_marks_session_expired_on_upstream_auth_failure():
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])
    marked = {}

    class Store:
        def get_session(self, session_id):
            assert session_id == "sess"
            return native_session

        def mark_expired(self, session_id, message=""):
            marked["session_id"] = session_id
            marked["message"] = message

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=ExpiredSearchSession())

    with pytest.raises(WechatUpstreamError):
        provider.search_accounts("测试")

    assert marked["session_id"] == "sess"
    assert "重新扫码" in marked["message"]


def test_native_provider_article_url_lookup_requires_author_exact_match(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": ""}})(),
    )

    with pytest.raises(ValueError, match="作者"):
        provider.account_by_article_url("https://mp.weixin.qq.com/s/test")


def test_native_provider_article_url_lookup_does_not_use_article_biz_as_fakeid(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    fake_http = FakeMpSession()
    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=fake_http)
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "测试号", "biz": "MzBiz=="}})(),
    )

    account = provider.account_by_article_url("https://mp.weixin.qq.com/s/test")

    assert account["fakeid"] == "fakeid-1"
    assert account["nickname"] == "测试号"
    assert account["article_biz"] == "MzBiz=="
    assert account["article_author"] == "测试号"
    assert account["matched_name"] == "测试号"
    assert account["lookup_mode"] == "author_exact"
    assert "searchbiz" in fake_http.calls[0][0]


def test_native_provider_article_url_lookup_normalizes_author_for_unique_match(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    fake_http = FakeMpSession()
    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=fake_http)
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": " 测\u200b 试 号 "}})(),
    )

    account = provider.account_by_article_url("https://mp.weixin.qq.com/s/test")

    assert account["fakeid"] == "fakeid-1"
    assert account["article_author"] == "测试号"
    assert account["matched_name"] == "测试号"


def test_native_provider_article_url_lookup_uses_unique_normalized_fallback(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "测试号"}})(),
    )
    monkeypatch.setattr(
        provider,
        "search_accounts",
        lambda keyword, *, begin=0, size=20: [{"fakeid": "fakeid-1", "nickname": "测试号｜官方"}],
    )

    account = provider.account_by_article_url("https://mp.weixin.qq.com/s/test")

    assert account["fakeid"] == "fakeid-1"
    assert account["matched_name"] == "测试号｜官方"
    assert account["lookup_mode"] == "author_unique_normalized"


def test_native_provider_article_url_lookup_rejects_ambiguous_normalized_fallback(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "测试号"}})(),
    )
    monkeypatch.setattr(
        provider,
        "search_accounts",
        lambda keyword, *, begin=0, size=20: [
            {"fakeid": "fakeid-1", "nickname": "测试号｜官方"},
            {"fakeid": "fakeid-2", "nickname": "测试号-服务"},
        ],
    )

    with pytest.raises(ValueError, match="多个同名公众号"):
        provider.account_by_article_url("https://mp.weixin.qq.com/s/test")


def test_native_provider_article_url_lookup_rejects_unseparated_prefix_match(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "测试号"}})(),
    )
    monkeypatch.setattr(
        provider,
        "search_accounts",
        lambda keyword, *, begin=0, size=20: [{"fakeid": "fakeid-1", "nickname": "测试号服务"}],
    )

    with pytest.raises(ValueError, match="精确匹配"):
        provider.account_by_article_url("https://mp.weixin.qq.com/s/test")


def test_native_provider_article_url_lookup_rejects_biz_without_author(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "", "biz": "MzBiz=="}})(),
    )

    with pytest.raises(ValueError, match="__biz 不是微信公众号后台 fakeid"):
        provider.account_by_article_url("https://mp.weixin.qq.com/s/test")


def test_native_provider_article_url_lookup_rejects_non_exact_search_match(monkeypatch):
    native_session = NativeSession(session_id="sess", token="token-123", cookies=[])

    class Store:
        def get_session(self, session_id):
            return native_session

    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=FakeMpSession())
    monkeypatch.setattr(
        "monitor.wechat_collect.providers.download_article",
        lambda *args, **kwargs: type("Downloaded", (), {"metadata": {"title": "标题", "author": "另一个号"}})(),
    )

    with pytest.raises(ValueError, match="精确匹配"):
        provider.account_by_article_url("https://mp.weixin.qq.com/s/test")

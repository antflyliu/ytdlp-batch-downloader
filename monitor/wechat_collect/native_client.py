from __future__ import annotations

import json
import re

import requests

from monitor.wechat_collect.errors import WechatUpstreamError, safe_error_message
from monitor.wechat_collect.models import NativeSession, normalize_account_preview, normalize_article_preview

MP_BASE = "https://mp.weixin.qq.com"
SESSION_EXPIRED_RETCODES = {200002, 200003, 200013}
SESSION_EXPIRED_MESSAGE_FRAGMENTS = (
    "token",
    "session",
    "cookie",
    "login",
    "登录",
    "凭证",
    "过期",
)
LOGIN_PAGE_MARKERS = (
    "扫码登录",
    "登录",
    "login",
    "wxlogin",
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)


class NativeMpClient:
    def __init__(self, session: NativeSession, *, http_session=None, timeout: int = 30, proxy_plan=None):
        self.session = session
        self.http = http_session or requests.Session()
        self.timeout = timeout
        self.proxy_plan = proxy_plan
        self._apply_cookies()

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        }

    def _proxies(self):
        return self.proxy_plan.requests_proxies if self.proxy_plan else None

    def _apply_cookies(self) -> None:
        cookies = getattr(self.http, "cookies", None)
        if not hasattr(cookies, "set"):
            return
        for item in self.session.cookies:
            name = item.get("name") or ""
            value = item.get("value") or ""
            if not name or not value:
                continue
            path = item.get("path") or "/"
            domain = (item.get("domain") or "").strip()
            if domain:
                cookies.set(name, value, domain=domain, path=path)
            else:
                cookies.set(name, value, path=path)

    @staticmethod
    def _check_base_resp(payload: dict, operation: str) -> None:
        base_resp = payload.get("base_resp") or {}
        try:
            ret = int(base_resp.get("ret", 0) or 0)
        except (TypeError, ValueError):
            ret = -999999
        if ret == 0:
            return
        err_msg = str(base_resp.get("err_msg") or "")
        session_expired = ret in SESSION_EXPIRED_RETCODES or any(
            fragment in err_msg.lower() for fragment in SESSION_EXPIRED_MESSAGE_FRAGMENTS
        )
        if session_expired:
            raise WechatUpstreamError(
                "登录会话已过期，请重新扫码登录",
                code=ret,
                operation=operation,
                session_expired=True,
            )
        raise WechatUpstreamError(
            f"{operation}失败: {ret}:{err_msg or payload}",
            code=ret,
            operation=operation,
        )

    @staticmethod
    def _response_text(resp) -> str:
        text = getattr(resp, "text", "") or ""
        if not text and getattr(resp, "content", b""):
            text = resp.content.decode("utf-8", errors="ignore")
        return text

    def _get(self, operation: str, url: str, **kwargs):
        try:
            resp = self.http.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise WechatUpstreamError(
                f"{operation}请求失败: {safe_error_message(exc)}",
                operation=operation,
            ) from exc

    @staticmethod
    def _looks_like_logged_out_page(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        has_login_marker = any(marker in lowered or marker in text for marker in LOGIN_PAGE_MARKERS)
        has_mp_state = "wx.cgiData" in text or "publish_page" in text or "base_resp" in text
        return has_login_marker and not has_mp_state

    @staticmethod
    def _read_json_response(resp, operation: str) -> dict:
        try:
            payload = resp.json()
        except ValueError as exc:
            text = NativeMpClient._response_text(resp)
            content_type = str(getattr(resp, "headers", {}).get("Content-Type", "") or "").lower()
            if NativeMpClient._looks_like_logged_out_page(text) or "text/html" in content_type:
                raise WechatUpstreamError(
                    "登录会话已过期，请重新扫码登录",
                    operation=operation,
                    session_expired=True,
                ) from exc
            raise WechatUpstreamError(f"{operation}响应不是有效 JSON", operation=operation) from exc
        if not isinstance(payload, dict):
            raise WechatUpstreamError(f"{operation}响应格式无效", operation=operation)
        return payload

    @staticmethod
    def _loads_json_object(value: str | dict | None, operation: str) -> dict:
        if isinstance(value, dict):
            return value
        try:
            payload = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise WechatUpstreamError(f"{operation}响应结构解析失败") from exc
        if not isinstance(payload, dict):
            raise WechatUpstreamError(f"{operation}响应结构无效")
        return payload

    def check_session(self) -> dict:
        resp = self._get(
            "检查登录会话",
            f"{MP_BASE}/cgi-bin/home",
            params={"t": "home/index", "token": self.session.token, "lang": "zh_CN"},
            headers=self._headers(),
            timeout=self.timeout,
            proxies=self._proxies(),
        )
        text = self._response_text(resp)
        if not text:
            raise WechatUpstreamError("检查登录会话响应为空", operation="检查登录会话")
        if self._looks_like_logged_out_page(text) and "nick_name" not in text:
            raise WechatUpstreamError(
                "登录会话已过期，请重新扫码登录",
                operation="检查登录会话",
                session_expired=True,
            )
        nick_match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"([^"]+)"', text)
        head_match = re.search(r'wx\.cgiData\.head_img\s*=\s*"([^"]+)"', text)
        return {
            "ok": True,
            "nickname": nick_match.group(1) if nick_match else self.session.nickname,
            "avatar": head_match.group(1) if head_match else self.session.avatar,
            "expires_at": self.session.expires_at,
        }

    def logout(self) -> dict:
        resp = self._get(
            "退出登录",
            f"{MP_BASE}/cgi-bin/logout",
            params={"t": "wxm-logout", "token": self.session.token, "lang": "zh_CN"},
            headers=self._headers(),
            timeout=self.timeout,
            proxies=self._proxies(),
        )
        return {"ok": True, "status_code": getattr(resp, "status_code", 200)}

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        keyword = (keyword or "").strip()
        if not keyword:
            raise WechatUpstreamError("搜索关键字不能为空")
        resp = self._get(
            "搜索公众号",
            f"{MP_BASE}/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "begin": max(0, int(begin or 0)),
                "count": max(1, min(int(size or 5), 20)),
                "query": keyword,
                "token": self.session.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            headers=self._headers(),
            timeout=self.timeout,
            proxies=self._proxies(),
        )
        payload = self._read_json_response(resp, "搜索公众号")
        self._check_base_resp(payload, "搜索公众号")
        return [normalize_account_preview(item) for item in payload.get("list") or []]

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 20,
        begin: int = 0,
        progress=None,
        cancel_check=None,
    ) -> list[dict]:
        fakeid = (fakeid or "").strip()
        if not fakeid:
            raise WechatUpstreamError("fakeid 不能为空")
        max_articles = max(1, min(int(max_articles or 50), 1000))
        page_size = max(1, min(int(page_size or 20), 20))
        begin = max(0, int(begin or 0))
        articles: list[dict] = []
        seen_links: set[str] = set()
        while len(articles) < max_articles:
            if cancel_check and cancel_check():
                break
            if progress:
                keep_going = progress(f"正在获取文章列表 offset={begin}")
                if keep_going is False:
                    break
            payload = self._fetch_article_page(fakeid, begin=begin, size=page_size, keyword=keyword)
            page_articles = payload.get("articles") or []
            if not page_articles:
                break
            try:
                total_count = int(payload.get("total_count") or 0)
            except (TypeError, ValueError):
                total_count = 0
            previous_count = len(articles)
            for raw in page_articles:
                preview = normalize_article_preview(raw)
                link = preview.get("link") or ""
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                articles.append({**raw, **preview})
                if len(articles) >= max_articles:
                    break
            if len(articles) == previous_count:
                break
            next_begin = begin + page_size
            if total_count and next_begin >= total_count:
                break
            if len(page_articles) < page_size:
                break
            begin = next_begin
        return articles

    def list_article_page(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        begin: int = 0,
        page_size: int = 20,
    ) -> dict:
        fakeid = (fakeid or "").strip()
        if not fakeid:
            raise WechatUpstreamError("fakeid 不能为空")
        begin = max(0, int(begin or 0))
        page_size = max(1, min(int(page_size or 20), 20))
        payload = self._fetch_article_page(fakeid, begin=begin, size=page_size, keyword=keyword)
        articles = []
        for raw in payload.get("articles") or []:
            preview = normalize_article_preview(raw)
            if preview.get("link"):
                articles.append({**raw, **preview})
        total_count = int(payload.get("total_count") or 0)
        next_begin = begin + page_size
        has_more = bool(articles) and (len(articles) >= page_size) and (not total_count or next_begin < total_count)
        return {
            "articles": articles,
            "begin": begin,
            "page_size": page_size,
            "next_begin": next_begin if has_more else None,
            "has_more": has_more,
            "total_count": total_count,
        }

    def _fetch_article_page(self, fakeid: str, *, begin: int, size: int, keyword: str) -> dict:
        is_searching = bool(keyword)
        resp = self._get(
            "获取文章列表",
            f"{MP_BASE}/cgi-bin/appmsgpublish",
            params={
                "sub": "search" if is_searching else "list",
                "search_field": "7" if is_searching else "null",
                "begin": begin,
                "count": size,
                "query": keyword or "",
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
                "token": self.session.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            headers=self._headers(),
            timeout=self.timeout,
            proxies=self._proxies(),
        )
        payload = self._read_json_response(resp, "获取文章列表")
        self._check_base_resp(payload, "获取文章列表")
        publish_page = self._loads_json_object(payload.get("publish_page"), "获取文章列表")
        publish_list = [
            item for item in publish_page.get("publish_list") or []
            if item.get("publish_info")
        ]
        articles = []
        for item in publish_list:
            publish_info = self._loads_json_object(item.get("publish_info"), "获取文章列表")
            articles.extend(publish_info.get("appmsgex") or [])
        return {"base_resp": payload.get("base_resp"), "articles": articles, "total_count": publish_page.get("total_count", 0)}

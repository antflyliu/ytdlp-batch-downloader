from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests

from monitor.wechat_collect.errors import WechatLoginError, safe_error_message
from monitor.wechat_collect.session_store import NativeSessionStore

MP_BASE = "https://mp.weixin.qq.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)


@dataclass
class BinaryPayload:
    body: bytes
    content_type: str


@dataclass
class PendingLogin:
    created_at: float
    session: requests.Session
    proxy_plan: object | None = None
    finalizing: bool = False


class NativeLoginManager:
    def __init__(
        self,
        *,
        session_factory=None,
        store: NativeSessionStore | None = None,
        proxy_plan=None,
        proxy_plan_factory=None,
        pending_ttl_seconds: int = 600,
    ):
        self._session_factory = session_factory or requests.Session
        self._store = store or NativeSessionStore()
        self._proxy_plan = proxy_plan
        self._proxy_plan_factory = proxy_plan_factory
        self._pending_ttl_seconds = max(0, int(pending_ttl_seconds))
        self._pending: dict[str, PendingLogin] = {}
        self._lock = threading.RLock()

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": USER_AGENT,
        }

    def _resolve_proxy_plan(self):
        if self._proxy_plan_factory:
            return self._proxy_plan_factory()
        return self._proxy_plan

    @staticmethod
    def _proxies(proxy_plan):
        return proxy_plan.requests_proxies if proxy_plan else None

    @staticmethod
    def _read_json_response(resp, operation: str) -> dict:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise WechatLoginError(f"{operation}响应不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise WechatLoginError(f"{operation}响应格式无效")
        return payload

    def _post(self, session, operation: str, url: str, **kwargs):
        try:
            resp = session.post(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise WechatLoginError(f"{operation}请求失败: {safe_error_message(exc)}") from exc

    def _get(self, session, operation: str, url: str, **kwargs):
        try:
            resp = session.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise WechatLoginError(f"{operation}请求失败: {safe_error_message(exc)}") from exc

    def start_login(self) -> dict:
        self._cleanup_pending()
        login_id = secrets.token_hex(12)
        sid = f"{int(time.time() * 1000)}{secrets.randbelow(100)}"
        session = self._session_factory()
        proxy_plan = self._resolve_proxy_plan()
        body = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": 3,
            "sessionid": sid,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        resp = self._post(
            session,
            "创建登录会话",
            f"{MP_BASE}/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data=body,
            headers=self._headers(),
            timeout=30,
            proxies=self._proxies(proxy_plan),
        )
        payload = self._read_json_response(resp, "创建登录会话")
        base_resp = payload.get("base_resp") or {}
        if int(base_resp.get("ret", -1)) != 0:
            raise WechatLoginError(str(base_resp.get("err_msg") or "创建登录会话失败"))
        with self._lock:
            self._pending[login_id] = PendingLogin(
                created_at=time.time(),
                session=session,
                proxy_plan=proxy_plan,
            )
        return {"login_id": login_id, "status": "pending"}

    def _cleanup_pending(self) -> None:
        with self._lock:
            now = time.time()
            expired = [
                login_id
                for login_id, pending in self._pending.items()
                if now - pending.created_at >= self._pending_ttl_seconds
            ]
            for login_id in expired:
                self._pending.pop(login_id, None)

    def _pending_login(self, login_id: str) -> PendingLogin:
        with self._lock:
            self._cleanup_pending()
            pending = self._pending.get(login_id)
            if not pending:
                raise WechatLoginError("登录会话不存在或已过期")
            return pending

    def get_qrcode(self, login_id: str) -> BinaryPayload:
        pending = self._pending_login(login_id)
        session = pending.session
        resp = self._get(
            session,
            "获取登录二维码",
            f"{MP_BASE}/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": int(time.time() * 1000)},
            headers=self._headers(),
            timeout=30,
            proxies=self._proxies(pending.proxy_plan),
        )
        return BinaryPayload(
            body=resp.content,
            content_type=resp.headers.get("Content-Type", "image/png"),
        )

    def poll_scan(self, login_id: str) -> dict:
        pending = self._pending_login(login_id)
        session = pending.session
        resp = self._get(
            session,
            "扫码状态查询",
            f"{MP_BASE}/cgi-bin/scanloginqrcode",
            params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            headers=self._headers(),
            timeout=30,
            proxies=self._proxies(pending.proxy_plan),
        )
        payload = self._read_json_response(resp, "扫码状态查询")
        if int((payload.get("base_resp") or {}).get("ret", 0)) != 0:
            raise WechatLoginError(str((payload.get("base_resp") or {}).get("err_msg") or "扫码状态查询失败"))
        return payload

    def confirm_login(self, login_id: str) -> dict:
        with self._lock:
            pending = self._pending_login(login_id)
            if pending.finalizing:
                raise WechatLoginError("登录会话正在确认，请勿重复提交")
            pending.finalizing = True
        session = pending.session
        try:
            resp = self._post(
                session,
                "登录确认",
                f"{MP_BASE}/cgi-bin/bizlogin",
                params={"action": "login"},
                data={
                    "userlang": "zh_CN",
                    "redirect_url": "",
                    "cookie_forbidden": 0,
                    "cookie_cleaned": 0,
                    "plugin_used": 0,
                    "login_type": 3,
                    "token": "",
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": 1,
                },
                headers=self._headers(),
                timeout=30,
                proxies=self._proxies(pending.proxy_plan),
            )
            payload = self._read_json_response(resp, "登录确认")
            base_resp = payload.get("base_resp") or {}
            if int(base_resp.get("ret", 0) or 0) != 0:
                raise WechatLoginError(str(base_resp.get("err_msg") or "登录确认失败"))
            redirect_url = str(payload.get("redirect_url") or "")
            token = self._extract_token(redirect_url)
            if not token:
                raise WechatLoginError("登录成功响应缺少 token")
            nickname, avatar = self._fetch_login_profile(session, token, pending.proxy_plan)
            cookies = self._cookies_to_list(getattr(session, "cookies", None))
            session_id = self._store.save_session(
                token=token,
                cookies=cookies,
                nickname=nickname,
                avatar=avatar,
            )
            with self._lock:
                self._pending.pop(login_id, None)
            return {"session_id": session_id, "nickname": nickname, "avatar": avatar, "expires_days": 4}
        except Exception:
            with self._lock:
                existing = self._pending.get(login_id)
                if existing is pending:
                    existing.finalizing = False
            raise

    @staticmethod
    def _extract_token(redirect_url: str) -> str:
        parsed = urlparse(f"http://localhost{redirect_url}" if redirect_url.startswith("/") else redirect_url)
        values = parse_qs(parsed.query).get("token") or []
        return values[0] if values else ""

    @staticmethod
    def _cookies_to_list(cookies) -> list[dict[str, str]]:
        if isinstance(cookies, dict):
            return [
                {"name": str(name), "value": str(value), "domain": "", "path": "/"}
                for name, value in cookies.items()
                if value
            ]
        result = []
        for cookie in cookies or []:
            value = getattr(cookie, "value", "")
            if not value:
                continue
            result.append(
                {
                    "name": getattr(cookie, "name", ""),
                    "value": value,
                    "domain": getattr(cookie, "domain", "") or "",
                    "path": getattr(cookie, "path", "") or "/",
                }
            )
        return result

    def _fetch_login_profile(self, session, token: str, proxy_plan=None) -> tuple[str, str]:
        resp = self._get(
            session,
            "获取登录资料",
            f"{MP_BASE}/cgi-bin/home",
            params={"t": "home/index", "token": token, "lang": "zh_CN"},
            headers=self._headers(),
            timeout=30,
            proxies=self._proxies(proxy_plan),
        )
        html = resp.content.decode("utf-8", errors="ignore")
        nick_match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"([^"]+)"', html)
        head_match = re.search(r'wx\.cgiData\.head_img\s*=\s*"([^"]+)"', html)
        return (
            nick_match.group(1) if nick_match else "",
            head_match.group(1) if head_match else "",
        )

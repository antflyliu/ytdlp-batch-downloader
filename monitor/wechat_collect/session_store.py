from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from config.encryption import _decrypt_config_value, _encrypt_config_value
from monitor.db.queries import wechat_collect as queries
from monitor.wechat_collect.errors import WechatSessionError
from monitor.wechat_collect.models import NativeSession


def _now() -> datetime:
    return datetime.now().astimezone()


def _expires_at(days: int = 4) -> str:
    return (_now() + timedelta(days=days)).isoformat(timespec="seconds")


def _encrypt(value: str) -> str:
    return _encrypt_config_value(value)


def _decrypt(value: str) -> str:
    if not value:
        return value
    decrypted = _decrypt_config_value(value)
    if value.startswith("enc:") and decrypted == value:
        raise WechatSessionError("登录会话凭据解密失败，请重新扫码")
    return decrypted


class NativeSessionStore:
    def save_session(
        self,
        *,
        token: str,
        cookies: list[dict[str, str]],
        nickname: str = "",
        avatar: str = "",
        session_id: str | None = None,
    ) -> str:
        if not token:
            raise WechatSessionError("token 不能为空")
        if not cookies:
            raise WechatSessionError("cookies 不能为空")
        session_id = session_id or f"wcs_{secrets.token_hex(16)}"
        queries.upsert_session(
            session_id=session_id,
            token_enc=_encrypt(token),
            cookie_json_enc=_encrypt(json.dumps(cookies, ensure_ascii=False)),
            nickname=nickname,
            avatar=avatar,
            expires_at=_expires_at(),
            status="active",
        )
        return session_id

    def get_session(self, session_id: str) -> NativeSession:
        row = queries.get_session(session_id)
        if not row:
            raise WechatSessionError("登录会话不存在")
        if row.get("status") != "active":
            raise WechatSessionError("登录会话不可用，请重新扫码")
        expires_raw = row.get("expires_at") or ""
        try:
            expires = datetime.fromisoformat(expires_raw)
        except Exception as exc:
            raise WechatSessionError("登录会话过期时间无效") from exc
        if expires <= _now():
            self._invalidate_credentials(session_id, status="expired", last_error="登录会话已过期")
            raise WechatSessionError("登录会话已过期，请重新扫码")
        cookie_json = _decrypt(row.get("cookie_json_enc") or "[]")
        try:
            cookies = json.loads(cookie_json or "[]")
        except json.JSONDecodeError as exc:
            raise WechatSessionError("登录会话 Cookie 格式无效") from exc
        return NativeSession(
            session_id=session_id,
            token=_decrypt(row.get("token_enc") or ""),
            cookies=cookies,
            nickname=row.get("nickname") or "",
            avatar=row.get("avatar") or "",
            status=row.get("status") or "active",
            expires_at=expires_raw,
        )

    def list_public_sessions(self) -> list[dict]:
        self.expire_stale_sessions()
        return queries.list_sessions()

    def expire_stale_sessions(self) -> int:
        now_value = _now().isoformat(timespec="seconds")
        session_ids = queries.list_stale_active_session_ids(now_value)
        for session_id in session_ids:
            self._invalidate_credentials(
                session_id,
                status="expired",
                last_error="登录会话已过期",
            )
        return len(session_ids)

    def mark_error(self, session_id: str, message: str) -> None:
        queries.update_session_status(session_id, status="error", last_error=message)

    def mark_expired(self, session_id: str, message: str = "登录会话已过期，请重新扫码") -> None:
        self._invalidate_credentials(session_id, status="expired", last_error=message)

    def mark_logged_out(self, session_id: str) -> None:
        self._invalidate_credentials(session_id, status="logged_out", last_error="")

    def _invalidate_credentials(self, session_id: str, *, status: str, last_error: str = "") -> None:
        queries.invalidate_session_credentials(
            session_id,
            status=status,
            last_error=last_error,
            token_enc=_encrypt(status),
            cookie_json_enc=_encrypt("[]"),
        )

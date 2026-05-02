from __future__ import annotations

import json
from email.message import EmailMessage
from typing import Any
from base64 import urlsafe_b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import EmailProviderError
from .parser import parse_gmail_raw_message

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_GMAIL_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE)


def normalize_gmail_scopes(scopes: Any = None, default: tuple[str, ...] = DEFAULT_GMAIL_SCOPES) -> list[str]:
    if scopes in (None, ""):
        raw_items: list[Any] = list(default)
    elif isinstance(scopes, str):
        raw_items = [item for chunk in scopes.split(",") for item in chunk.split()]
    elif isinstance(scopes, (list, tuple, set)):
        raw_items = list(scopes)
    else:
        raw_items = list(default)
    normalized: list[str] = []
    for item in raw_items:
        scope = str(item or "").strip()
        if scope and scope not in normalized:
            normalized.append(scope)
    return normalized or list(default)


def build_gmail_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: Any = None,
    login_hint: str = "",
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(normalize_gmail_scopes(scopes)),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GMAIL_AUTH_URL}?{urlencode(params)}"


def exchange_gmail_oauth_code(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    timeout: int = 30,
) -> dict[str, Any]:
    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    try:
        request = Request(
            GMAIL_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise EmailProviderError("Gmail OAuth code exchange failed") from exc


class GmailClient:
    def __init__(self, account: dict[str, Any], *, timeout: int = 30) -> None:
        self.account = account
        self.timeout = timeout

    def refresh_access_token(self) -> str:
        client_id = self.account.get("gmail_client_id") or ""
        client_secret = self.account.get("gmail_client_secret") or ""
        refresh_token = self.account.get("gmail_refresh_token") or ""
        if not client_id or not client_secret or not refresh_token:
            raise EmailProviderError("Gmail OAuth client_id/client_secret/refresh_token are required")
        payload = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        try:
            request = Request(
                GMAIL_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise EmailProviderError(f"Gmail token refresh failed: {exc}") from exc
        token = data.get("access_token")
        if not token:
            raise EmailProviderError("Gmail token refresh response did not include access_token")
        return str(token)

    def _request_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.refresh_access_token()
        url = f"{GMAIL_API_BASE}{path}"
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")}, doseq=True)
        try:
            request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise EmailProviderError(f"Gmail API request failed: {exc}") from exc

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = self.refresh_access_token()
        url = f"{GMAIL_API_BASE}{path}"
        try:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request = Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise EmailProviderError(f"Gmail API request failed: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        profile = self._request_json("/profile")
        return {"ok": True, "emailAddress": profile.get("emailAddress"), "messagesTotal": profile.get("messagesTotal")}

    def test_send_capability(self) -> dict[str, Any]:
        profile = self._request_json("/profile")
        scopes = set(normalize_gmail_scopes(self.account.get("gmail_scope"), ()))
        return {
            "ok": GMAIL_SEND_SCOPE in scopes,
            "emailAddress": profile.get("emailAddress"),
            "scope": GMAIL_SEND_SCOPE,
            "mode": "gmail_api",
        }

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        from_addr: str | None = None,
    ) -> dict[str, Any]:
        message = EmailMessage()
        message["To"] = to
        message["From"] = from_addr or self.account.get("email_address") or "me"
        message["Subject"] = subject
        message.set_content(body_text or "")
        raw = urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        return self._post_json("/messages/send", {"raw": raw})

    def fetch_recent(self, *, max_messages: int = 10, query: str = "", label_ids: list[str] | None = None):
        params: dict[str, Any] = {"maxResults": max(1, min(int(max_messages or 10), 100))}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if self.account.get("include_spam_trash"):
            params["includeSpamTrash"] = "true"
        listing = self._request_json("/messages", params)
        refs = listing.get("messages") or []
        for ref in refs:
            message_id = ref.get("id")
            if not message_id:
                continue
            payload = self._request_json(f"/messages/{message_id}", {"format": "raw"})
            yield parse_gmail_raw_message(payload)

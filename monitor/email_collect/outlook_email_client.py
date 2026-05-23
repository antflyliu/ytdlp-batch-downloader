from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from .errors import EmailProviderError
from .models import ParsedEmailMessage


class OutlookEmailClient:
    def __init__(self, account: dict[str, Any], *, timeout: int = 30) -> None:
        self.account = account
        self.timeout = timeout
        self.base_url = self._normalize_base_url(account.get("outlook_email_base_url"))
        self.api_key = str(account.get("outlook_email_api_key") or "").strip()
        self._opener = build_opener(ProxyHandler({}))

    def _normalize_base_url(self, value: Any) -> str:
        base_url = str(value or "").strip().rstrip("/")
        if not base_url:
            raise EmailProviderError("outlookEmail base_url is required")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise EmailProviderError("outlookEmail base_url must be an http(s) URL")
        if parsed.username or parsed.password:
            raise EmailProviderError("outlookEmail base_url must not include credentials")
        return base_url

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url}/{path.lstrip('/')}"
        clean = {key: value for key, value in (query or {}).items() if value not in (None, "")}
        if clean:
            url = f"{url}?{urlencode(clean)}"
        return url

    def _request_json(self, path: str, query: dict[str, Any] | None = None, *, timeout: int | None = None) -> dict:
        if not self.api_key:
            raise EmailProviderError("outlookEmail api_key is required")
        request = Request(
            self._url(path, query),
            headers={"Accept": "application/json", "X-API-Key": self.api_key},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise EmailProviderError(f"outlookEmail HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise EmailProviderError(f"outlookEmail request failed: {exc}") from exc
        except Exception as exc:
            raise EmailProviderError(f"outlookEmail request failed: {exc}") from exc
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise EmailProviderError("outlookEmail returned non-JSON response") from exc
        if data.get("success") is False:
            raise EmailProviderError(f"outlookEmail returned failure: {data.get('error') or data}")
        return data

    def list_remote_accounts(self, *, limit: int = 100) -> dict:
        return self._request_json(
            "/api/external/accounts",
            {"limit": max(1, min(int(limit or 100), 10000))},
        )

    def test_connection(self) -> dict[str, Any]:
        accounts_payload = self.list_remote_accounts(limit=1)
        remote_email = self._remote_email()
        result: dict[str, Any] = {
            "ok": True,
            "base_url": self.base_url,
            "remote_email": remote_email,
            "account_count": accounts_payload.get("total"),
        }
        if remote_email:
            result["sample_count"] = len(list(self.fetch_recent(max_messages=1)))
        return result

    def fetch_recent(self, *, max_messages: int = 10):
        remote_email = self._remote_email()
        if not remote_email:
            raise EmailProviderError("outlookEmail remote email is required")
        query = {
            "email": remote_email,
            "folder": self.account.get("outlook_email_folder") or "all",
            "top": max(1, min(int(max_messages or 10), 50)),
            "skip": 0,
            "subject_contains": self.account.get("outlook_email_subject_contains") or "",
            "from_contains": self.account.get("outlook_email_from_contains") or "",
            "keyword": self.account.get("outlook_email_keyword") or "",
        }
        payload = self._request_json("/api/external/emails", query, timeout=max(self.timeout, 45))
        for item in payload.get("emails") or []:
            if isinstance(item, dict):
                yield self._parse_message(item, payload)

    def _remote_email(self) -> str:
        return str(self.account.get("outlook_email_remote_email") or self.account.get("email_address") or "").strip()

    def _parse_message(self, item: dict[str, Any], payload: dict[str, Any]) -> ParsedEmailMessage:
        provider_message_id = str(item.get("id") or item.get("message_id") or "").strip()
        if not provider_message_id:
            provider_message_id = hashlib.sha256(
                json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        body_text = str(
            item.get("body_text")
            or item.get("text")
            or item.get("body")
            or item.get("body_preview")
            or item.get("snippet")
            or ""
        )
        html_body = str(item.get("html_body") or item.get("body_html") or "")
        snippet = str(item.get("body_preview") or item.get("snippet") or body_text[:240])
        return ParsedEmailMessage(
            provider="outlook_email",
            provider_message_id=provider_message_id,
            provider_thread_id=str(item.get("conversation_id") or item.get("thread_id") or ""),
            rfc_message_id=str(item.get("internet_message_id") or item.get("rfc_message_id") or ""),
            subject=str(item.get("subject") or ""),
            from_addr=self._address_text(item.get("from") or item.get("from_addr")),
            to_addr=self._address_text(item.get("to") or item.get("to_addr")),
            cc_addr=self._address_text(item.get("cc") or item.get("cc_addr")),
            received_at=str(item.get("date") or item.get("received_at") or ""),
            sent_at=str(item.get("sent_at") or item.get("date") or ""),
            snippet=snippet,
            body_text=body_text,
            html_body=html_body,
            raw_payload={
                "email": item,
                "requested_email": payload.get("requested_email"),
                "resolved_email": payload.get("resolved_email"),
                "matched_alias": payload.get("matched_alias"),
                "method": payload.get("method"),
            },
        )

    def _address_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("email") or value.get("address") or value.get("name") or "")
        if isinstance(value, list):
            parts = []
            for item in value:
                text = self._address_text(item)
                if text:
                    parts.append(text)
            return ", ".join(parts)
        return str(value)

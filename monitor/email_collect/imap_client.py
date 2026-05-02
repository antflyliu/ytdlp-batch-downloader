from __future__ import annotations

import imaplib
import ssl
from typing import Any

from .errors import EmailProviderError
from .parser import parse_rfc822
from .security import validate_mail_endpoint


class ImapClient:
    def __init__(self, account: dict[str, Any], *, timeout: int = 30) -> None:
        self.account = account
        self.timeout = timeout

    def _connect(self):
        host = self.account.get("imap_host") or ""
        port = int(self.account.get("imap_port") or 993)
        security = str(self.account.get("imap_security") or "ssl").lower()
        if not host:
            raise EmailProviderError("IMAP host is required")
        try:
            validate_mail_endpoint(host, port, security, service="imap")
            if security == "ssl":
                client = imaplib.IMAP4_SSL(host, port, timeout=self.timeout)
            else:
                client = imaplib.IMAP4(host, port, timeout=self.timeout)
                if security == "starttls":
                    client.starttls(ssl.create_default_context())
            username = self.account.get("imap_username") or self.account.get("email_address") or ""
            password = self.account.get("imap_password") or ""
            if not username or not password:
                raise EmailProviderError("IMAP username/password are required")
            client.login(username, password)
            return client
        except EmailProviderError:
            raise
        except Exception as exc:
            raise EmailProviderError(f"IMAP connection failed: {exc}") from exc

    def test_connection(self) -> dict[str, Any]:
        client = self._connect()
        try:
            status, mailboxes = client.list()
            if status != "OK":
                raise EmailProviderError("IMAP LIST failed")
            return {"ok": True, "mailbox_count": len(mailboxes or [])}
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def fetch_recent(self, *, max_messages: int = 10, mailbox: str = "INBOX", search: str = "ALL"):
        client = self._connect()
        try:
            status, _ = client.select(mailbox or "INBOX", readonly=True)
            if status != "OK":
                raise EmailProviderError(f"IMAP mailbox select failed: {mailbox}")
            safe_search = search if search in {"ALL", "UNSEEN", "NEW", "RECENT"} else "ALL"
            status, data = client.uid("SEARCH", None, safe_search)
            if status != "OK" or not data:
                return
            uids = (data[0] or b"").split()
            for uid in uids[-max(1, min(int(max_messages or 10), 100)) :]:
                status, fetched = client.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not fetched:
                    continue
                raw = b""
                for item in fetched:
                    if isinstance(item, tuple) and item[1]:
                        raw = item[1]
                        break
                if raw:
                    yield parse_rfc822(raw, provider="imap", provider_message_id=uid.decode("ascii", errors="ignore"))
        finally:
            try:
                client.logout()
            except Exception:
                pass

from __future__ import annotations

import smtplib
import ssl
from typing import Any

from .errors import EmailProviderError
from .security import validate_mail_endpoint


def test_smtp_connection(account: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    host = account.get("smtp_host") or ""
    if not host:
        return {"ok": True, "skipped": True, "reason": "SMTP host is empty"}
    port = int(account.get("smtp_port") or 465)
    security = str(account.get("smtp_security") or "ssl").lower()
    username = account.get("smtp_username") or account.get("email_address") or ""
    password = account.get("smtp_password") or ""
    try:
        validate_mail_endpoint(host, port, security, service="smtp")
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
            client.ehlo()
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
        try:
            if username and password:
                client.login(username, password)
            client.noop()
        finally:
            client.quit()
        return {"ok": True, "host": host, "port": port}
    except Exception as exc:
        raise EmailProviderError(f"SMTP connection failed: {exc}") from exc

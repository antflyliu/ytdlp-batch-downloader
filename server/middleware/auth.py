"""
server/middleware/auth.py — Bearer token authentication middleware.

Extracted from monitor_server.py:
  - _require_auth method (as standalone verify_bearer_token)

The verify_bearer_token function checks the Authorization header against
a token resolved from environment variable or database. It does NOT send
an HTTP response — callers must send the appropriate 401 response.
"""
from __future__ import annotations

import os
import secrets


def get_api_token(db_module=None) -> str:
    """Resolve the current API token: environment variable takes precedence over database."""
    token = os.environ.get("MONITOR_API_TOKEN")
    if token:
        return token
    if db_module is not None:
        return db_module.get_api_token()
    return ""


def verify_bearer_token(
    auth_header: str,
    token: str,
) -> tuple[bool, str | None]:
    """
    Verify that auth_header contains a valid Bearer token matching the expected token.

    Returns:
        (is_valid, error_message) — is_valid=True means authorized, False means unauthorized.
        error_message is a human-readable reason for 401 responses (None when valid).
    """
    if not auth_header.startswith("Bearer "):
        return False, "未授权，请提供 Bearer token"
    provided = auth_header[7:]
    if not secrets.compare_digest(provided, token):
        return False, "无效的 token"
    return True, None

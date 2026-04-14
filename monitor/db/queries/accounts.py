"""
monitor.db.queries.accounts — Monitor account CRUD operations.
"""
from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso, _UNSET
from monitor.db.crypto import encrypt_webhook, decrypt_webhook


def _decrypt_account_webhook(account: dict) -> dict:
    """Decrypt account webhook_url field."""
    if account and account.get("webhook_url"):
        account = dict(account)
        account["webhook_url"] = decrypt_webhook(account["webhook_url"])
    return account


def list_accounts(enabled_only: bool = False) -> list[dict]:
    with get_connection() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM monitor_accounts WHERE enabled=1 ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM monitor_accounts ORDER BY id"
            ).fetchall()
        return [_decrypt_account_webhook(dict(r)) for r in rows]


def get_account(account_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_accounts WHERE id=?", (account_id,)
        ).fetchone()
        return _decrypt_account_webhook(dict(row)) if row else None


def add_account(
    name: str,
    channel_url: str,
    api_key_env: str,
    fetch_mode: str = "playlist",
    fetch_limit: int = 5,
    scan_interval: int = 5,
    notify_enabled: bool = True,
    notify_platform: str = "feishu",
    webhook_url: str | None = None,
    feishu_message_mode: str = "card_json",
    feishu_template_id: str | None = None,
    feishu_scan_template_id: str | None = None,
    api_key_id: int | None = None,
    proxy_pool_id: int | None = None,
    proxy_enabled: bool = False,
    download_proxy_mode: str = "auto",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO monitor_accounts
               (name, channel_url, api_key_env, fetch_mode, fetch_limit,
                scan_interval, enabled, notify_enabled, notify_platform, webhook_url,
                feishu_message_mode, feishu_template_id, feishu_scan_template_id,
                api_key_id, proxy_pool_id, proxy_enabled, download_proxy_mode, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, channel_url, api_key_env, fetch_mode, fetch_limit,
             scan_interval, int(notify_enabled), notify_platform,
             encrypt_webhook(webhook_url),
             feishu_message_mode, feishu_template_id, feishu_scan_template_id,
             api_key_id, proxy_pool_id, int(proxy_enabled), download_proxy_mode,
             now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_account(
    account_id: int,
    name: str | None = None,
    channel_url: str | None = None,
    api_key_env: str | None = None,
    fetch_mode: str | None = None,
    fetch_limit: int | None = None,
    scan_interval: int | None = None,
    enabled: bool | None = None,
    notify_enabled: bool | None = None,
    notify_platform: str | None = None,
    webhook_url=_UNSET,
    feishu_message_mode: str | None = None,
    feishu_template_id=_UNSET,
    feishu_scan_template_id=_UNSET,
    api_key_id=_UNSET,
    proxy_pool_id=_UNSET,
    proxy_enabled=None,
    download_proxy_mode=_UNSET,
) -> None:
    """Update account fields.

    For nullable fields, _UNSET means "don't change", None means "set to NULL".
    """
    fields, values = [], []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if channel_url is not None:
        fields.append("channel_url=?")
        values.append(channel_url)
    if api_key_env is not None:
        fields.append("api_key_env=?")
        values.append(api_key_env)
    if fetch_mode is not None:
        fields.append("fetch_mode=?")
        values.append(fetch_mode)
    if fetch_limit is not None:
        fields.append("fetch_limit=?")
        values.append(fetch_limit)
    if scan_interval is not None:
        fields.append("scan_interval=?")
        values.append(scan_interval)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if notify_enabled is not None:
        fields.append("notify_enabled=?")
        values.append(int(notify_enabled))
    if notify_platform is not None:
        fields.append("notify_platform=?")
        values.append(notify_platform)
    if webhook_url is not _UNSET:
        fields.append("webhook_url=?")
        values.append(encrypt_webhook(webhook_url))
    if feishu_message_mode is not None:
        fields.append("feishu_message_mode=?")
        values.append(feishu_message_mode)
    if feishu_template_id is not _UNSET:
        fields.append("feishu_template_id=?")
        values.append(feishu_template_id)
    if feishu_scan_template_id is not _UNSET:
        fields.append("feishu_scan_template_id=?")
        values.append(feishu_scan_template_id)
    if api_key_id is not _UNSET:
        fields.append("api_key_id=?")
        values.append(api_key_id)
    if proxy_pool_id is not _UNSET:
        fields.append("proxy_pool_id=?")
        values.append(proxy_pool_id)
    if proxy_enabled is not None:
        fields.append("proxy_enabled=?")
        values.append(int(proxy_enabled))
    if download_proxy_mode is not _UNSET:
        fields.append("download_proxy_mode=?")
        values.append(download_proxy_mode)
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(account_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE monitor_accounts SET {','.join(fields)} WHERE id=?", values)


def delete_account(account_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM monitor_accounts WHERE id=?", (account_id,))

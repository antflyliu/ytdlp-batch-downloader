"""
monitor.db.queries.providers — Dynamic proxy provider CRUD operations.
"""
import json

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso, _UNSET
from monitor.db.crypto import encrypt_config_secrets, decrypt_config_secrets


def _parse_provider_json(provider: dict) -> dict:
    """Parse config_json field from string to dict, decrypt sensitive fields."""
    if provider and provider.get("config_json"):
        try:
            provider = dict(provider)
            provider["config_json"] = decrypt_config_secrets(
                json.loads(provider["config_json"])
            )
        except Exception:
            provider["config_json"] = {}
    return provider


def list_dynamic_proxy_providers() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM dynamic_proxy_providers ORDER BY priority ASC, id ASC"
        ).fetchall()
        return [_parse_provider_json(dict(r)) for r in rows]


def get_dynamic_proxy_provider(provider_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dynamic_proxy_providers WHERE id=?", (provider_id,)
        ).fetchone()
        return _parse_provider_json(dict(row)) if row else None


def add_dynamic_proxy_provider(
    name: str,
    billing_tier: str = "free",
    adapter_type: str = "public_feed",
    config_json: dict | None = None,
    enabled: bool = True,
    priority: int = 100,
    supports_cookies: bool = False,
    supports_auto_download: bool = True,
    supports_country_filter: bool = False,
    supports_sticky_session: bool = False,
    risk_level: str = "medium",
    notes: str | None = None,
    refresh_interval_minutes: int = 0,
) -> int:
    """Add a new dynamic proxy provider (sensitive fields in config_json auto-encrypted)."""
    cfg_encrypted = encrypt_config_secrets(config_json or {})
    cfg_str = json.dumps(cfg_encrypted)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO dynamic_proxy_providers
               (name, enabled, billing_tier, adapter_type, priority,
                supports_cookies, supports_auto_download, supports_country_filter,
                supports_sticky_session, risk_level, notes, config_json,
                created_at, updated_at, refresh_interval_minutes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, int(enabled), billing_tier, adapter_type, priority,
             int(supports_cookies), int(supports_auto_download),
             int(supports_country_filter), int(supports_sticky_session),
             risk_level, notes, cfg_str, now_iso(), now_iso(),
             int(refresh_interval_minutes)),
        )
        return cur.lastrowid


def update_dynamic_proxy_provider(
    provider_id: int,
    name: str | None = None,
    enabled: bool | None = None,
    billing_tier: str | None = None,
    adapter_type: str | None = None,
    priority: int | None = None,
    supports_cookies: bool | None = None,
    supports_auto_download: bool | None = None,
    supports_country_filter: bool | None = None,
    supports_sticky_session: bool | None = None,
    risk_level: str | None = None,
    notes: str | None = None,
    config_json: dict | None = None,
    last_health_status: str | None = None,
    last_health_checked_at: str | None = None,
    last_error_message: str | None = _UNSET,
    cooldown_until: str | None = None,
    refresh_interval_minutes: int | None = None,
) -> None:
    """Update a dynamic proxy provider."""
    fields, values = [], []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if billing_tier is not None:
        fields.append("billing_tier=?")
        values.append(billing_tier)
    if adapter_type is not None:
        fields.append("adapter_type=?")
        values.append(adapter_type)
    if priority is not None:
        fields.append("priority=?")
        values.append(priority)
    if supports_cookies is not None:
        fields.append("supports_cookies=?")
        values.append(int(supports_cookies))
    if supports_auto_download is not None:
        fields.append("supports_auto_download=?")
        values.append(int(supports_auto_download))
    if supports_country_filter is not None:
        fields.append("supports_country_filter=?")
        values.append(int(supports_country_filter))
    if supports_sticky_session is not None:
        fields.append("supports_sticky_session=?")
        values.append(int(supports_sticky_session))
    if risk_level is not None:
        fields.append("risk_level=?")
        values.append(risk_level)
    if notes is not None:
        fields.append("notes=?")
        values.append(notes)
    if config_json is not None:
        existing = get_dynamic_proxy_provider(provider_id) or {}
        merged_config = merge_config_secrets(
            config_json,
            existing.get("config_json") or {},
        )
        fields.append("config_json=?")
        values.append(json.dumps(encrypt_config_secrets(merged_config)))
    if last_health_status is not None:
        fields.append("last_health_status=?")
        values.append(last_health_status)
    if last_health_checked_at is not None:
        fields.append("last_health_checked_at=?")
        values.append(last_health_checked_at)
    # None = explicitly clear; _UNSET = don't modify
    if last_error_message is not _UNSET:
        fields.append("last_error_message=?")
        values.append(last_error_message)
    if cooldown_until is not None:
        fields.append("cooldown_until=?")
        values.append(cooldown_until)
    if refresh_interval_minutes is not None:
        fields.append("refresh_interval_minutes=?")
        values.append(int(refresh_interval_minutes))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(provider_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE dynamic_proxy_providers SET {','.join(fields)} WHERE id=?",
            values,
        )


def delete_dynamic_proxy_provider(provider_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM dynamic_proxy_providers WHERE id=?", (provider_id,))


def get_enabled_providers(billing_tier: str | None = None) -> list[dict]:
    """Get enabled proxy providers ordered by priority."""
    with get_connection() as conn:
        if billing_tier is None:
            rows = conn.execute(
                "SELECT * FROM dynamic_proxy_providers WHERE enabled=1 ORDER BY priority ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dynamic_proxy_providers WHERE enabled=1 AND billing_tier=? ORDER BY priority ASC",
                (billing_tier,),
            ).fetchall()
        return [_parse_provider_json(dict(r)) for r in rows]


def merge_config_secrets(new_cfg, old_cfg):
    """Replace '***' masked placeholders with old_cfg values."""
    from monitor.db.crypto import merge_masked_config_secrets
    return merge_masked_config_secrets(new_cfg, old_cfg)

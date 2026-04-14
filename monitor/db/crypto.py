"""
monitor.db.crypto — Encryption utilities for webhook URLs and config secrets.

Provides Fernet-based encryption/decryption for:
- Webhook URLs
- Config JSON sensitive fields
- Proxy candidate passwords
"""
import json

from monitor.db.connection import get_connection, _DATA_DIR, _DB_PATH
from monitor.db.db_core import _SECRET_FIELD_NAMES, now_iso

# Lazy import of Fernet to avoid import overhead when crypto isn't needed
_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet
        _fernet = Fernet(_get_webhook_enc_key())
    return _fernet


def _get_webhook_enc_key() -> bytes:
    """Get/create Fernet encryption key stored in app_state."""
    from cryptography.fernet import Fernet
    # Ensure app_state table exists
    import sqlite3
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.commit()
    row = conn.execute(
        "SELECT value FROM app_state WHERE key='webhook_enc_key'"
    ).fetchone()
    if row:
        conn.close()
        return row[0].encode("utf-8")
    key_str = Fernet.generate_key().decode("utf-8")
    conn.execute(
        "INSERT OR REPLACE INTO app_state (key, value) VALUES ('webhook_enc_key', ?)",
        (key_str,),
    )
    conn.commit()
    conn.close()
    return key_str.encode("utf-8")


# ── Webhook URL encryption ──────────────────────────────────────


def encrypt_webhook(url: str | None) -> str | None:
    """Encrypt webhook URL. Returns 'enc:<base64>' format."""
    if not url:
        return None
    if url.startswith("enc:"):
        return url
    return "enc:" + _get_fernet().encrypt(url.encode("utf-8")).decode("utf-8")


def decrypt_webhook(encrypted: str | None) -> str | None:
    """Decrypt webhook URL. Non-encrypted values pass through unchanged."""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted
    try:
        return _get_fernet().decrypt(encrypted[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted


# ── Config value encryption ─────────────────────────────────────


def encrypt_config_value(value: str) -> str:
    """Fernet-encrypt a single string value. Returns 'enc:<base64>'."""
    if not value:
        return value
    if value.startswith("enc:"):
        return value
    return "enc:" + _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_config_value(value: str) -> str:
    """Fernet-decrypt a single string value. Non-encrypted values pass through."""
    if not value:
        return value
    if not value.startswith("enc:"):
        return value
    try:
        return _get_fernet().decrypt(value[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return value


def encrypt_config_secrets(cfg: dict) -> dict:
    """Recursively encrypt sensitive string fields in a config dict."""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and k.lower() in _SECRET_FIELD_NAMES:
            result[k] = encrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = encrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [
                encrypt_config_value(item) if isinstance(item, str) and k.lower() in _SECRET_FIELD_NAMES else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def decrypt_config_secrets(cfg: dict) -> dict:
    """Recursively decrypt sensitive string fields in a config dict."""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and (v.startswith("enc:") or k.lower() in _SECRET_FIELD_NAMES):
            result[k] = decrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = decrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [
                decrypt_config_value(item) if isinstance(item, str) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def merge_masked_config_secrets(new_cfg, old_cfg):
    """Replace '***' masked placeholders with old_cfg values."""
    if isinstance(new_cfg, dict):
        old_map = old_cfg if isinstance(old_cfg, dict) else {}
        result = {}
        for k, v in new_cfg.items():
            old_v = old_map.get(k)
            if (
                isinstance(v, str)
                and v == "***"
                and k.lower() in _SECRET_FIELD_NAMES
                and old_v is not None
            ):
                result[k] = old_v
            else:
                result[k] = merge_masked_config_secrets(v, old_v)
        return result
    if isinstance(new_cfg, list):
        old_list = old_cfg if isinstance(old_cfg, list) else []
        return [
            merge_masked_config_secrets(item, old_list[idx] if idx < len(old_list) else None)
            for idx, item in enumerate(new_cfg)
        ]
    return new_cfg


# ── Proxy candidate helpers ─────────────────────────────────────


def encrypt_candidate_secret(value: str | None) -> str | None:
    """Fernet-encrypt proxy candidate password. Returns 'enc:<base64>'."""
    if not value:
        return None
    if value.startswith("enc:"):
        return value
    return encrypt_config_value(value)


def decrypt_candidate_secret(encrypted: str | None) -> str | None:
    """Fernet-decrypt proxy candidate password. Non-encrypted pass through."""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted
    return decrypt_config_value(encrypted)

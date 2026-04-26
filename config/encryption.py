"""
config/encryption.py — Fernet encryption for webhooks and config secrets

Extracts encryption logic from monitor/db.py.
Stores/retrieves keys via app_state in monitor.db.
"""
from __future__ import annotations

import os
import sqlite3
import sys

from cryptography.fernet import Fernet

# ── Constants ──────────────────────────────────────────────────

_SECRET_FIELD_NAMES = frozenset([
    "password",
    "auth_secret",
    "api_key",
    "proxy_url",
    "secret",
    "token",
])


def _is_secret_field(field_name: str) -> bool:
    """检查字段名是否为敏感字段（子串匹配，避免复合名如 llm_api_key 漏检）。

    对 llm_api_key → 匹配 "api_key"，telegram_bot_token → 匹配 "token" 等。
    """
    lower = field_name.lower()
    return any(name in lower for name in _SECRET_FIELD_NAMES)


_GLOBAL_WEBHOOK_KEYS = (
    "global_feishu_url",
    "global_dingtalk_url",
    "global_dingtalk_sign_secret",
    "global_wecom_url",
)


# ── Key management ─────────────────────────────────────────────

def _get_db_connection():
    """Get a monitor.db connection for key storage (private helper)."""
    from utils.paths import get_data_dir

    if getattr(sys, "frozen", False):
        _pkg_dir = os.path.join(sys._MEIPASS, "monitor")
        _exe_dir = os.path.dirname(sys.executable)
    else:
        _pkg_dir = os.path.dirname(os.path.abspath(__file__))
        # __file__ is config/encryption.py, parent is config/, grandparent is project root
        _exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    _data_dir = os.path.join(_exe_dir, "data")
    _db_path = os.path.join(_data_dir, "monitor.db")
    return sqlite3.connect(_db_path, check_same_thread=False)


def _ensure_app_state_table(conn) -> None:
    """Create app_state table if not exists (inline, no-op when schema.sql already ran)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )


def _get_webhook_enc_key() -> bytes:
    """
    获取 Webhook URL 加密密钥（从 app_state 读取，不存在则自动生成）。
    使用 Fernet.generate_key() 生成符合规范的 base64 编码密钥。
    """
    conn = _get_db_connection()
    try:
        _ensure_app_state_table(conn)
        row = conn.execute(
            "SELECT value FROM app_state WHERE key='webhook_enc_key'"
        ).fetchone()
        if row:
            return row[0].encode("utf-8")
        key_str = Fernet.generate_key().decode("utf-8")
        conn.execute(
            """INSERT OR REPLACE INTO app_state (key, value) VALUES ('webhook_enc_key', ?)""",
            (key_str,),
        )
        conn.commit()
        return key_str.encode("utf-8")
    finally:
        conn.close()


# ── Webhook encryption ──────────────────────────────────────────

def _encrypt_webhook(url: str | None) -> str | None:
    """加密 Webhook URL，明文为空或已加密则原样返回"""
    if not url:
        return None
    if url.startswith("enc:"):
        return url  # 已加密，跳过
    key = _get_webhook_enc_key()
    f = Fernet(key)
    encrypted = f.encrypt(url.encode("utf-8"))
    return "enc:" + encrypted.decode("utf-8")


def _decrypt_webhook(encrypted: str | None) -> str | None:
    """解密 Webhook URL，非加密值或解密失败则原样返回"""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted  # 明文原样返回
    try:
        key = _get_webhook_enc_key()
        f = Fernet(key)
        return f.decrypt(encrypted[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted  # 解密失败时返回原始值


# ── Config value encryption ────────────────────────────────────

def _encrypt_config_value(value: str) -> str:
    """Fernet 加密单个字符串值，返回 'enc:<base64>' 格式。"""
    if not value:
        return value
    if value.startswith("enc:"):
        return value
    key = _get_webhook_enc_key()
    return "enc:" + Fernet(key).encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_config_value(value: str) -> str:
    """Fernet 解密单个字符串值，非加密值或解密失败原样返回。"""
    if not value:
        return value
    if not value.startswith("enc:"):
        return value
    try:
        key = _get_webhook_enc_key()
        return Fernet(key).decrypt(value[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return value


def _encrypt_config_secrets(cfg: dict) -> dict:
    """递归加密 config_json 中的敏感字符串字段（不修改非字符串值）。"""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and _is_secret_field(k):
            result[k] = _encrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = _encrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [
                _encrypt_config_value(item) if isinstance(item, str) and _is_secret_field(k) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _decrypt_config_secrets(cfg: dict) -> dict:
    """递归解密 config_json 中的敏感字符串字段。"""
    if not isinstance(cfg, dict):
        return cfg
    result = {}
    for k, v in cfg.items():
        if isinstance(v, str) and (v.startswith("enc:") or _is_secret_field(k)):
            result[k] = _decrypt_config_value(v)
        elif isinstance(v, dict):
            result[k] = _decrypt_config_secrets(v)
        elif isinstance(v, list):
            result[k] = [_decrypt_config_value(item) if isinstance(item, str) else item for item in v]
        else:
            result[k] = v
    return result


def _merge_masked_config_secrets(new_cfg, old_cfg):
    """将前端回传的 '***' 敏感占位符替换为旧配置中的真实值。"""
    if isinstance(new_cfg, dict):
        old_map = old_cfg if isinstance(old_cfg, dict) else {}
        result = {}
        for k, v in new_cfg.items():
            old_v = old_map.get(k)
            if (
                isinstance(v, str)
                and v == "***"
                and _is_secret_field(k)
                and old_v is not None
            ):
                result[k] = old_v
            else:
                result[k] = _merge_masked_config_secrets(v, old_v)
        return result
    if isinstance(new_cfg, list):
        old_list = old_cfg if isinstance(old_cfg, list) else []
        return [
            _merge_masked_config_secrets(item, old_list[idx] if idx < len(old_list) else None)
            for idx, item in enumerate(new_cfg)
        ]
    return new_cfg


# ── Candidate secret helpers (for proxy candidates) ───────────

def _encrypt_candidate_secret(value: str | None) -> str | None:
    """Fernet 加密候选密码，返回 'enc:<base64>' 格式。"""
    if not value:
        return None
    if value.startswith("enc:"):
        return value
    return _encrypt_config_value(value)


def _decrypt_candidate_secret(encrypted: str | None) -> str | None:
    """Fernet 解密候选密码，非加密值或解密失败原样返回。"""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted
    return _decrypt_config_value(encrypted)

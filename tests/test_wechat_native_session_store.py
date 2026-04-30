from __future__ import annotations

import importlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet


def _init_temp_db(monkeypatch, tmp_path):
    import config.encryption as encryption
    import monitor.db as db
    import monitor.db.connection as db_connection

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    enc_key = Fernet.generate_key()
    monkeypatch.setattr(encryption, "_get_webhook_enc_key", lambda: enc_key)
    db.init_db()
    return db_path


def test_session_store_reuses_config_encryption_helpers():
    source = (Path(__file__).resolve().parents[1] / "monitor" / "wechat_collect" / "session_store.py").read_text(
        encoding="utf-8"
    )

    assert "from config.encryption import" in source
    assert "_encrypt_config_value" in source
    assert "_decrypt_config_value" in source
    assert "Fernet.generate_key" not in source
    assert "wechat_native_session.key" not in source


def test_session_store_encrypts_token_and_cookies(monkeypatch, tmp_path):
    db_path = _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )

    session = store.get_session(session_id)
    assert session.token == "token-123"
    assert session.cookies[0]["value"] == "cookie-secret"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT token_enc, cookie_json_enc FROM wechat_collect_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] != "token-123"
    assert "cookie-secret" not in row[1]


def test_session_store_public_list_masks_secrets(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )

    public = store.list_public_sessions()

    assert public[0]["session_id"] == session_id
    assert "auth_key" not in public[0]
    encoded = json.dumps(public, ensure_ascii=False)
    assert "token-123" not in encoded
    assert "cookie-secret" not in encoded


def test_session_store_public_list_marks_expired_sessions(monkeypatch, tmp_path):
    db_path = _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )
    expired_at = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE wechat_collect_sessions SET expires_at=? WHERE session_id=?",
            (expired_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    public = store.list_public_sessions()

    assert public[0]["session_id"] == session_id
    assert public[0]["status"] == "expired"
    assert public[0]["last_error"] == "登录会话已过期"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT token_enc, cookie_json_enc FROM wechat_collect_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert store_mod._decrypt(row[0]) == "expired"
    assert store_mod._decrypt(row[1]) == "[]"


def test_get_session_invalidates_credentials_when_session_is_expired(monkeypatch, tmp_path):
    db_path = _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )
    expired_at = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE wechat_collect_sessions SET expires_at=? WHERE session_id=?",
            (expired_at, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        store.get_session(session_id)
    except store_mod.WechatSessionError as exc:
        assert "已过期" in str(exc)
    else:
        raise AssertionError("expired session should not be returned")

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, token_enc, cookie_json_enc FROM wechat_collect_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "expired"
    assert store_mod._decrypt(row[1]) == "expired"
    assert store_mod._decrypt(row[2]) == "[]"


def test_session_store_logout_invalidates_persisted_credentials(monkeypatch, tmp_path):
    db_path = _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )

    store.mark_logged_out(session_id)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, token_enc, cookie_json_enc FROM wechat_collect_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "logged_out"
    assert store_mod._decrypt(row[1]) == "logged_out"
    assert store_mod._decrypt(row[2]) == "[]"

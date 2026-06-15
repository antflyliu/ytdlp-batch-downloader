"""Regression test: AI settings save must not return 400 when LLM provider/base_url change.

Bug repro:
- User opens AI settings page; the cfgLlmApiKey input is pre-filled with the masked sentinel
  '***' returned by GET /api/config for the existing llm_api_key.
- User changes llm_provider (or llm_base_url) and clicks Save without re-entering the key.
- The page used to submit body.llm_api_key='***' as-is; the server's
  _validate_llm_endpoint_secret_reentry rejects it with 400
  ('llm_provider 或 llm_base_url 变更后必须重新输入 llm_api_key').

Expected after fix:
- The page detects provider/base_url change while the api-key field is still the masked
  sentinel, clears the field, and submits body.llm_api_key=''.
- The server then accepts the save (200) and clears the stored key (user must re-enter).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "monitor"))

import server.__main__ as server_main
import monitor.db as db


def _make_handler():
    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    return handler, sent


def _fake_scheduler(monkeypatch):
    class _S:
        def set_global_feishu_url(self, *a, **k): pass
        def set_global_dingtalk_url(self, *a, **k): pass
        def set_global_dingtalk_sign_secret(self, *a, **k): pass
        def set_global_wecom_url(self, *a, **k): pass
        def set_global_telegram_chat_id(self, *a, **k): pass
        def set_global_telegram_token(self, *a, **k): pass
        def _invalidate_config_cache(self): pass
    monkeypatch.setattr(server_main, "_scheduler", _S())
    monkeypatch.setattr(server_main, "_db", db)


def _build_ai_page_body(masked_snapshot, llm_provider, llm_api_key, llm_base_url=None):
    base_url = masked_snapshot.get("llm_base_url", "") if llm_base_url is None else llm_base_url
    return {
        "llm_provider": llm_provider,
        "llm_api_key": llm_api_key,
        "llm_model": masked_snapshot.get("llm_model", ""),
        "llm_base_url": base_url,
        "llm_min_score": masked_snapshot.get("llm_min_score", 7.0),
        "llm_category": masked_snapshot.get("llm_category", "knowledge"),
        "clip_embed_thumbnail": True,
        "clip_embed_subtitle": True,
        "clip_adapt_aspect_ratio": True,
        "default_api_key_id": None,
        "global_feishu_url": "",
        "global_dingtalk_url": "",
        "global_dingtalk_sign_secret": "",
        "global_wecom_url": "",
        "global_telegram_token": "",
        "global_telegram_chat_id": "",
        "quota_budget_per_day": 8000,
        "quota_usage_timezone": "local",
        "channel_meta_max_age_days": 30,
        "notify_on_scan_error": False,
        "scan_error_notify_cooldown_seconds": 300,
        "scan_jitter_seconds": 0,
        "quota_alert_thresholds": [80, 90, 100],
        "channel_meta_health_check_enabled": True,
        "channel_meta_health_check_interval_hours": 24,
        "notify_on_channel_meta_mismatch": True,
        "download_cookies_file": "",
        "download_output_path": "",
        "enable_aria2": True,
        "default_sub_langs": "zh-Hans,en",
        "system_dynamic_proxy_enabled": False,
        "apply_dynamic_proxy_to_new_accounts": True,
        "apply_dynamic_proxy_to_existing_accounts": False,
        "allow_free_proxy": True,
        "allow_free_proxy_for_auto_download": False,
        "allow_free_proxy_with_cookies": True,
        "manual_direct_fallback": True,
        "auto_direct_fallback": False,
        "default_proxy_protocol_order": "http>https>socks5>socks4",
        "default_session_mode": "sticky",
        "default_sticky_minutes": 10,
        "mask_proxy_in_logs": True,
    }


def test_ai_settings_save_with_provider_change_and_masked_key_preserves_no_400(
    monkeypatch, tmp_path
):
    """When the user changes llm_provider on the AI page and the api key input is the
    masked sentinel '***' (the page clears it before submitting), the server must accept
    the save. The page-side fix is what makes body.llm_api_key='' land here; this test
    pins the server contract that an empty api_key on a changed provider returns 200.
    """
    import shutil
    config_path = Path("config.json")
    backup = tmp_path / "config.json.bak"
    shutil.copy(config_path, backup)
    try:
        real_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        # Pre-condition: a key must be set so the masked sentinel is non-empty.
        if not real_cfg.get("llm_api_key"):
            real_cfg["llm_api_key"] = "enc:placeholder"
        config_path.write_text(
            json.dumps(real_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        _fake_scheduler(monkeypatch)
        handler, sent = _make_handler()
        masked = server_main._mask_config_for_response(real_cfg)
        # After the page-side fix, body.llm_api_key is '' (cleared) when provider changed.
        body = _build_ai_page_body(
            masked,
            llm_provider="qwen",  # changed from "openai"
            llm_api_key="",       # cleared by client-side fix
        )
        server_main.MonitorHandler._api_config_save(handler, body)
        assert sent, "save handler should respond"
        payload, status = sent[-1]
        assert status == 200, (
            f"expected 200, got {status} with payload {payload}; "
            "this is the original 400 bug — page-side fix should clear the masked key"
        )
        assert payload.get("ok") is True
    finally:
        shutil.copy(backup, config_path)


def test_ai_settings_save_with_no_change_keeps_existing_key(monkeypatch, tmp_path):
    """No-change save (provider/base_url unchanged) must remain 200 and not clobber the
    stored api key. The page still sends '***' in this case; the server's
    _preserve_masked_config_values restores the encrypted value.
    """
    import shutil
    from config.encryption import _decrypt_config_value
    config_path = Path("config.json")
    backup = tmp_path / "config.json.bak"
    shutil.copy(config_path, backup)
    try:
        real_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        if not real_cfg.get("llm_api_key"):
            real_cfg["llm_api_key"] = "enc:placeholder"
        config_path.write_text(
            json.dumps(real_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        original_plain = _decrypt_config_value(real_cfg["llm_api_key"]) if real_cfg["llm_api_key"].startswith("enc:") else real_cfg["llm_api_key"]

        _fake_scheduler(monkeypatch)
        handler, sent = _make_handler()
        masked = server_main._mask_config_for_response(real_cfg)
        body = _build_ai_page_body(
            masked,
            llm_provider=real_cfg["llm_provider"],
            llm_api_key=masked.get("llm_api_key", ""),  # '***' (unchanged sentinel)
        )
        server_main.MonitorHandler._api_config_save(handler, body)
        payload, status = sent[-1]
        assert status == 200, f"expected 200, got {status} with payload {payload}"
        # The decrypted key must match the original — encryption is non-deterministic
        # (Fernet), so we compare plaintext, not ciphertext.
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        saved_plain = _decrypt_config_value(saved["llm_api_key"]) if saved.get("llm_api_key", "").startswith("enc:") else saved.get("llm_api_key", "")
        assert saved_plain == original_plain, (
            f"no-change save must preserve the stored llm_api_key plaintext "
            f"(was {original_plain!r}, now {saved_plain!r})"
        )
    finally:
        shutil.copy(backup, config_path)

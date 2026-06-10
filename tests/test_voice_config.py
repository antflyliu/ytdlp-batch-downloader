from __future__ import annotations

import json


VOICE_SECRET_KEYS = (
    "openai_speech_api_key",
    "azure_speech_api_key",
    "minimax_speech_api_key",
    "voxcpm_api_key",
    "vibevoice_tts_api_key",
    "vibevoice_asr_api_key",
)


def test_default_config_contains_unified_voice_fields():
    import config.settings as settings

    cfg = settings._config_default()

    assert cfg["voice_provider"] == "edge_tts"
    assert cfg["voice_fallback_order"] == "edge_tts,local_http_tts,silent"
    assert cfg["voice_flow_defaults_json"] == "{}"
    assert cfg["voice_output_dir"].endswith("voice")
    assert cfg["voice_require_disclosure"] is True
    assert cfg["voice_allow_reference_clone"] is False
    assert cfg["voice_allow_prompt_transcript_clone"] is False
    assert cfg["voice_max_text_chars"] == 5000
    assert cfg["transcription_provider"] == "whisper_api"
    assert cfg["openai_speech_base_url"] == "https://api.openai.com/v1"
    assert cfg["azure_speech_output_format"]
    assert cfg["minimax_speech_base_url"] == "https://api.minimax.io"
    assert cfg["minimax_speech_model"] == "speech-2.8-hd"
    assert cfg["voxcpm_model"] == "openbmb/VoxCPM2"


def test_voice_provider_keys_are_encrypted_at_rest(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    import config.encryption as encryption
    import config.settings as settings

    cfg_path = tmp_path / "config.json"
    data_dir = tmp_path / "data"
    pkg_dir = tmp_path / "pkg"
    key = Fernet.generate_key()
    monkeypatch.setattr(settings, "get_config_path", lambda: str(cfg_path))
    monkeypatch.setattr(settings, "get_data_dir", lambda: str(data_dir))
    monkeypatch.setattr(settings, "get_pkg_dir", lambda: str(pkg_dir))
    monkeypatch.setattr(encryption, "_get_webhook_enc_key", lambda: key)

    cfg = settings._config_default()
    for key_name in VOICE_SECRET_KEYS:
        cfg[key_name] = f"{key_name}-secret"

    settings.save_config(cfg)

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    for key_name in VOICE_SECRET_KEYS:
        assert raw[key_name] != cfg[key_name]
        assert raw[key_name].startswith("enc:")

    loaded = settings.load_config()
    for key_name in VOICE_SECRET_KEYS:
        assert loaded[key_name] == f"{key_name}-secret"


def test_config_endpoint_masks_voice_provider_keys(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {key: f"{key}-secret" for key in VOICE_SECRET_KEYS},
    )

    server_main.MonitorHandler._api_config(handler)

    payload, status = sent[0]
    assert status == 200
    for key in VOICE_SECRET_KEYS:
        assert payload[key] == "***"


def test_masked_voice_config_values_preserve_existing_secrets():
    import server.__main__ as server_main

    old_cfg = {key: f"{key}-old" for key in VOICE_SECRET_KEYS}
    new_cfg = {
        "openai_speech_api_key": "***",
        "azure_speech_api_key": "",
        "minimax_speech_api_key": "minimax-new",
        "voxcpm_api_key": "***",
        "vibevoice_tts_api_key": "vibevoice-tts-new",
        "vibevoice_asr_api_key": "***",
    }

    merged = server_main._preserve_masked_config_values(new_cfg, old_cfg)

    assert merged["openai_speech_api_key"] == "openai_speech_api_key-old"
    assert merged["azure_speech_api_key"] == ""
    assert merged["minimax_speech_api_key"] == "minimax-new"
    assert merged["voxcpm_api_key"] == "voxcpm_api_key-old"
    assert merged["vibevoice_tts_api_key"] == "vibevoice-tts-new"
    assert merged["vibevoice_asr_api_key"] == "vibevoice_asr_api_key-old"


def test_config_save_persists_voice_fields_and_preserves_masked_secret(monkeypatch):
    import server.__main__ as server_main

    sent = []
    saved = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "voice_provider": "edge_tts",
            "voice_flow_defaults_json": "{}",
            "openai_speech_api_key": "old-openai-speech",
        },
    )
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: saved.append(dict(cfg)))
    monkeypatch.setattr(server_main._scheduler, "_invalidate_config_cache", lambda: None)

    server_main.MonitorHandler._api_config_save(
        handler,
        {
            "voice_provider": "openai_speech",
            "voice_flow_defaults_json": '{"manual_voice.speech_synthesis":"openai_speech"}',
            "openai_speech_api_key": "***",
            "voice_allow_reference_clone": True,
        },
    )

    assert sent[-1][1] == 200
    assert saved[0]["voice_provider"] == "openai_speech"
    assert saved[0]["voice_allow_reference_clone"] is True
    assert saved[0]["voice_flow_defaults_json"] == '{"manual_voice.speech_synthesis":"openai_speech"}'
    assert saved[0]["openai_speech_api_key"] == "old-openai-speech"


def test_config_save_rejects_invalid_voice_flow_defaults(monkeypatch):
    import server.__main__ as server_main

    sent = []
    saved = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(server_main._db, "load_config", lambda: {})
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: saved.append(dict(cfg)))

    server_main.MonitorHandler._api_config_save(
        handler,
        {"voice_flow_defaults_json": "not-json"},
    )

    assert sent[-1][1] == 400
    assert "voice_flow_defaults_json" in sent[-1][0]["error"]
    assert saved == []


def test_config_save_rejects_unknown_voice_flow_provider(monkeypatch):
    import server.__main__ as server_main

    sent = []
    saved = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(server_main._db, "load_config", lambda: {})
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: saved.append(dict(cfg)))

    server_main.MonitorHandler._api_config_save(
        handler,
        {"voice_flow_defaults_json": '{"manual_voice.speech_synthesis":"evil_provider"}'},
    )

    assert sent[-1][1] == 400
    assert "provider" in sent[-1][0]["error"]
    assert saved == []


def test_config_save_requires_secret_reentry_when_voice_endpoint_host_changes(monkeypatch):
    import server.__main__ as server_main

    sent = []
    saved = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "openai_speech_base_url": "https://api.openai.com/v1",
            "openai_speech_api_key": "old-openai-secret",
        },
    )
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: saved.append(dict(cfg)))

    server_main.MonitorHandler._api_config_save(
        handler,
        {
            "openai_speech_base_url": "https://attacker.example/v1",
            "openai_speech_api_key": "***",
        },
    )

    assert sent[-1][1] == 400
    assert "openai_speech_api_key" in sent[-1][0]["error"]
    assert saved == []


def test_config_save_allows_voice_endpoint_host_change_with_new_secret(monkeypatch):
    import server.__main__ as server_main

    sent = []
    saved = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "openai_speech_base_url": "https://api.openai.com/v1",
            "openai_speech_api_key": "old-openai-secret",
        },
    )
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: saved.append(dict(cfg)))
    monkeypatch.setattr(server_main._scheduler, "_invalidate_config_cache", lambda: None)

    server_main.MonitorHandler._api_config_save(
        handler,
        {
            "openai_speech_base_url": "https://voice-gateway.example/v1",
            "openai_speech_api_key": "new-openai-secret",
        },
    )

    assert sent[-1][1] == 200
    assert saved[0]["openai_speech_base_url"] == "https://voice-gateway.example/v1"
    assert saved[0]["openai_speech_api_key"] == "new-openai-secret"

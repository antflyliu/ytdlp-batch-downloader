from __future__ import annotations


def _handler_with_sender(server_main):
    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    return handler, sent


def test_voice_providers_api_returns_capability_filtered_provider_metadata(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    handler.path = "/api/voice/providers?capability=speech_synthesis&flow=video_generation"

    monkeypatch.setattr(server_main._db, "load_config", lambda: {"voice_provider": "silent"})
    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: None)

    server_main.MonitorHandler._api_voice_providers(handler)

    payload, status = sent[-1]
    assert status == 200
    assert payload["capability"] == "speech_synthesis"
    assert payload["flow"] == "video_generation"
    assert payload["selected_provider"]["provider_id"] == "silent"
    assert [provider["id"] for provider in payload["providers"]] == [
        "edge_tts",
        "local_http_tts",
        "openai_speech",
        "azure_speech",
        "minimax_speech",
        "voxcpm_openai_speech",
        "voxcpm_http",
        "vibevoice_tts",
        "vibevoice_realtime",
        "silent",
    ]
    assert {"id", "label", "capabilities", "configured", "modes", "fields", "safety", "config_reason"} <= set(
        payload["providers"][0]
    )


def test_voice_env_api_returns_diagnostic_payload(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "load_config", lambda: {"voice_output_dir": "data/voice"})
    monkeypatch.setattr(
        server_main.voice_env,
        "check_voice_environment",
        lambda cfg, **kwargs: {"ok": True, "cfg": cfg, "kwargs": kwargs},
    )

    server_main.MonitorHandler._api_voice_env(handler)

    payload, status = sent[-1]
    assert status == 200
    assert payload["ok"] is True
    assert payload["kwargs"] == {"include_remote": False}


def test_voice_env_check_api_allows_explicit_remote_probe(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "load_config", lambda: {})
    monkeypatch.setattr(
        server_main.voice_env,
        "check_voice_environment",
        lambda cfg, **kwargs: {"ok": True, "kwargs": kwargs},
    )

    server_main.MonitorHandler._api_voice_env_check(handler, {"include_remote": True, "timeout_seconds": 7})

    payload, status = sent[-1]
    assert status == 200
    assert payload["kwargs"] == {"include_remote": True, "timeout_seconds": 7}


def test_voice_smoke_test_api_returns_safe_error_without_secret(monkeypatch):
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    monkeypatch.setattr(server_main._db, "load_config", lambda: {"openai_speech_api_key": "sk-secret"})
    monkeypatch.setattr(
        server_main.voice_env,
        "run_voice_smoke_test",
        lambda body, cfg: {"ok": False, "error": f"bad key {cfg['openai_speech_api_key']}"},
    )

    server_main.MonitorHandler._api_voice_smoke_test(handler, {"provider": "openai_speech", "text": "hello"})

    payload, status = sent[-1]
    assert status == 400
    assert payload["ok"] is False
    assert "sk-secret" not in payload["error"]


def test_write_api_rejects_disallowed_cross_origin_request():
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    handler.headers = {"Origin": "https://attacker.example"}

    rejected = server_main.MonitorHandler._reject_disallowed_write_origin(handler)

    assert rejected is True
    assert sent[-1][1] == 403


def test_config_api_requires_json_content_type_for_body():
    import server.__main__ as server_main

    handler, sent = _handler_with_sender(server_main)
    handler.headers = {"Content-Length": "2", "Content-Type": "text/plain"}

    rejected = server_main.MonitorHandler._reject_invalid_json_content_type(handler, "/api/config")

    assert rejected is True
    assert sent[-1][1] == 415

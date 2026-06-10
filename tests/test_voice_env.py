from __future__ import annotations

from pathlib import Path


def test_voice_environment_check_reports_local_status_without_remote_probe(monkeypatch, tmp_path):
    from monitor.voice import env

    monkeypatch.setattr(env.shutil, "which", lambda name: f"C:/bin/{name}.exe" if name in {"ffmpeg", "ffprobe"} else None)
    monkeypatch.setattr(env.shutil, "disk_usage", lambda _path: (1000, 400, 600))
    monkeypatch.setattr(env.importlib.util, "find_spec", lambda _name: None)

    calls = []
    monkeypatch.setattr(env, "_probe_remote_url", lambda *args, **kwargs: calls.append((args, kwargs)))

    payload = env.check_voice_environment(
        {
            "voice_output_dir": str(tmp_path / "voice"),
            "openai_speech_base_url": "https://api.openai.com/v1?api-key=secret",
            "openai_speech_api_key": "sk-secret",
        }
    )

    assert payload["commands"]["ffmpeg"]["available"] is True
    assert payload["commands"]["ffprobe"]["available"] is True
    assert payload["commands"]["docker"]["available"] is False
    assert payload["disk"]["free_bytes"] == 600
    assert payload["remote_base_urls"]["openai_speech"]["status"] == "not_checked"
    assert "secret" not in str(payload)
    assert calls == []


def test_voice_environment_remote_probe_is_explicit_and_sanitized(monkeypatch):
    from monitor.voice import env

    probe_calls = []

    def fake_probe(url, timeout_seconds):
        probe_calls.append((url, timeout_seconds))
        return {"status": "reachable", "status_code": 401}

    monkeypatch.setattr(env, "_probe_remote_url", fake_probe)

    payload = env.check_voice_environment(
        {
            "local_tts_url": "https://user:pass@voice.example/private?api-key=secret",
            "openai_speech_base_url": "https://api.openai.com/v1",
            "openai_speech_api_key": "sk-secret",
        },
        include_remote=True,
        timeout_seconds=9,
    )

    assert probe_calls == [
        ("https://user:pass@voice.example/private?api-key=secret", 9),
        ("https://api.openai.com/v1", 9),
    ]
    assert payload["remote_base_urls"]["local_http_tts"]["url"] == "https://***@voice.example/private"
    assert payload["remote_base_urls"]["local_http_tts"]["status"] == "reachable"
    assert "pass" not in str(payload)
    assert "secret" not in str(payload)


def test_voice_environment_remote_probe_blocks_private_hosts(monkeypatch):
    from monitor.voice import env

    calls = []
    monkeypatch.setattr(env.urllib.request, "urlopen", lambda *args, **kwargs: calls.append((args, kwargs)))

    payload = env.check_voice_environment(
        {"local_tts_url": "http://169.254.169.254/latest/meta-data"},
        include_remote=True,
    )

    assert payload["remote_base_urls"]["local_http_tts"]["status"] == "blocked"
    assert calls == []


def test_voice_provider_payload_filters_by_capability_and_includes_selection(monkeypatch):
    from monitor.voice.capabilities import SPEECH_SYNTHESIS
    from monitor.voice.env import voice_provider_payload

    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: None)

    payload = voice_provider_payload(
        {"voice_provider": "silent", "voice_fallback_order": "edge_tts,local_http_tts,silent"},
        capability=SPEECH_SYNTHESIS,
        flow="video_generation",
    )

    provider_ids = [provider["id"] for provider in payload["providers"]]
    assert provider_ids == [
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
    assert payload["selected_provider"]["provider_id"] == "silent"
    assert payload["selected_provider"]["reason"] == "voice_provider"
    assert [provider["id"] for provider in payload["providers"] if provider["configured"]] == ["silent"]
    assert [provider["id"] for provider in payload["providers"] if provider["selected"]] == ["silent"]


def test_voice_smoke_test_limits_text_and_returns_silent_audio(tmp_path):
    from monitor.voice.env import run_voice_smoke_test

    result = run_voice_smoke_test(
        {
            "provider": "silent",
            "text": "short smoke test",
            "flow": "manual_voice",
        },
        {"voice_output_dir": str(tmp_path), "voice_fallback_order": "silent"},
    )

    audio_path = Path(result["audio_path"])
    assert result["ok"] is True
    assert result["provider"] == "silent"
    assert audio_path.exists()
    assert audio_path.read_bytes()[:4] == b"RIFF"


def test_voice_smoke_test_rejects_long_text(tmp_path):
    from monitor.voice.env import run_voice_smoke_test

    result = run_voice_smoke_test(
        {"provider": "silent", "text": "x" * 301},
        {"voice_output_dir": str(tmp_path), "voice_fallback_order": "silent"},
    )

    assert result["ok"] is False
    assert "300" in result["error"]

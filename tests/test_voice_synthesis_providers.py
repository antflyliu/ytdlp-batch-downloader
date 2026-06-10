from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from monitor.voice.capabilities import SPEECH_SYNTHESIS
from monitor.voice.providers import VoiceProviderRegistry
from monitor.voice.schemas import SpeechSynthesisRequest
from monitor.voice.synthesis import (
    EdgeTtsSpeechProvider,
    LocalHttpTtsProvider,
    SilentSpeechProvider,
    build_synthesis_registry,
    synthesize_speech,
)


def _request(tmp_path, **overrides):
    payload = {
        "text": "hello world",
        "output_dir": tmp_path,
        "provider": "silent",
        "flow": "manual_voice",
        "source": "manual_voice",
        "source_task_id": "voice_1",
    }
    payload.update(overrides)
    return SpeechSynthesisRequest(**payload)


def test_build_synthesis_registry_registers_local_providers():
    registry = build_synthesis_registry()

    assert registry.get("silent").provider_id == "silent"
    assert registry.get("edge-tts").provider_id == "edge_tts"
    assert registry.get("local").provider_id == "local_http_tts"


def test_silent_provider_writes_wav_and_metadata(tmp_path):
    provider = SilentSpeechProvider()

    result = provider.synthesize(_request(tmp_path), {"voice_require_disclosure": True})

    assert result.provider == "silent"
    assert result.path.read_bytes()[:4] == b"RIFF"
    assert result.mime_type == "audio/wav"
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["provider"] == "silent"
    assert metadata["capability"] == SPEECH_SYNTHESIS
    assert metadata["source_task_id"] == "voice_1"
    assert metadata["ai_generated"] is True


def test_synthesize_speech_uses_requested_silent_provider(tmp_path):
    result = synthesize_speech(_request(tmp_path, provider="offline"), {}, build_synthesis_registry())

    assert result.provider == "silent"
    assert result.path.name == "narration.wav"


def test_edge_provider_constructs_command_and_writes_metadata(tmp_path, monkeypatch):
    command_calls = []

    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda name: "C:/bin/edge-tts.exe" if name == "edge-tts" else None)

    def fake_run(command, capture_output, text, timeout):
        command_calls.append(
            {
                "command": command,
                "capture_output": capture_output,
                "text": text,
                "timeout": timeout,
            }
        )
        output_path = Path(command[command.index("--write-media") + 1])
        output_path.write_bytes(b"mp3-audio")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("monitor.voice.synthesis.subprocess.run", fake_run)

    provider = EdgeTtsSpeechProvider()
    result = provider.synthesize(
        _request(tmp_path, provider="edge-tts", voice="en-US-AriaNeural"),
        {"voice_timeout_seconds": 123},
    )

    command = command_calls[0]["command"]
    assert command[:2] == ["C:/bin/edge-tts.exe", "--text"]
    assert "--write-media" in command
    assert command[-2:] == ["--voice", "en-US-AriaNeural"]
    assert command_calls[0]["timeout"] == 123
    assert result.provider == "edge_tts"
    assert result.path.read_bytes() == b"mp3-audio"


def test_edge_provider_reports_failed_command(tmp_path, monkeypatch):
    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: "C:/bin/edge-tts.exe")
    monkeypatch.setattr(
        "monitor.voice.synthesis.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="edge failed", stdout=""),
    )

    with pytest.raises(RuntimeError, match="edge failed"):
        EdgeTtsSpeechProvider().synthesize(_request(tmp_path, provider="edge-tts"), {})


def test_edge_provider_rejects_unsafe_output_name(tmp_path, monkeypatch):
    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: "C:/bin/edge-tts.exe")

    with pytest.raises(ValueError, match="outside voice output root"):
        EdgeTtsSpeechProvider().synthesize(
            _request(tmp_path, provider="edge-tts", output_name="../narration"),
            {},
        )


class FakeHttpResponse:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._data


def test_local_http_provider_posts_tts_json_and_saves_raw_audio(tmp_path, monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append({"request": request, "timeout": timeout})
        return FakeHttpResponse(b"wav-audio", "audio/wav")

    monkeypatch.setattr("monitor.voice.synthesis.urllib.request.urlopen", fake_urlopen)

    result = LocalHttpTtsProvider().synthesize(
        _request(tmp_path, provider="local", voice="voice-a"),
        {"local_tts_url": "http://tts.local", "voice_timeout_seconds": 77},
    )

    body = json.loads(requests[0]["request"].data.decode("utf-8"))
    assert requests[0]["request"].full_url == "http://tts.local/tts"
    assert requests[0]["timeout"] == 77
    assert body["text"] == "hello world"
    assert body["voice"] == "voice-a"
    assert result.provider == "local_http_tts"
    assert result.path.read_bytes() == b"wav-audio"


def test_local_http_provider_does_not_persist_credentials_in_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"wav-audio", "audio/wav"),
    )

    result = LocalHttpTtsProvider().synthesize(
        _request(tmp_path, provider="local"),
        {"local_tts_url": "http://user:pass@tts.local/private?api-key=secret"},
    )

    metadata_text = result.metadata_path.read_text(encoding="utf-8")
    assert "user:pass" not in metadata_text
    assert "secret" not in metadata_text


def test_local_http_json_audio_keeps_unsafe_output_error_visible(tmp_path, monkeypatch):
    payload = json.dumps({"audio_hex": "7761762d617564696f"}).encode("utf-8")
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(payload, "application/json"),
    )

    with pytest.raises(ValueError, match="outside voice output root"):
        LocalHttpTtsProvider().synthesize(
            _request(tmp_path, provider="local", output_name="../narration"),
            {"local_tts_url": "http://tts.local"},
        )


def test_local_http_provider_requires_configured_url(tmp_path):
    with pytest.raises(ValueError, match="local_tts_url"):
        LocalHttpTtsProvider().synthesize(_request(tmp_path, provider="local"), {})


def test_synthesize_speech_uses_supplied_registry(tmp_path):
    registry = VoiceProviderRegistry()
    registry.register(SilentSpeechProvider())

    result = synthesize_speech(_request(tmp_path, provider="silent"), {}, registry)

    assert result.provider == "silent"


def test_synthesize_speech_falls_back_from_edge_runtime_failure_to_local_http(tmp_path, monkeypatch):
    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: "C:/bin/edge-tts.exe")
    monkeypatch.setattr(
        "monitor.voice.synthesis.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="edge failed", stdout=""),
    )
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"wav-audio", "audio/wav"),
    )

    result = synthesize_speech(
        _request(tmp_path, provider="edge-tts"),
        {"local_tts_url": "http://tts.local"},
        build_synthesis_registry(),
    )

    assert result.provider == "local_http_tts"
    assert result.path.read_bytes() == b"wav-audio"


def test_synthesize_speech_respects_no_runtime_fallback_policy(tmp_path, monkeypatch):
    monkeypatch.setattr("monitor.voice.synthesis.shutil.which", lambda _name: "C:/bin/edge-tts.exe")
    monkeypatch.setattr(
        "monitor.voice.synthesis.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="edge failed", stdout=""),
    )
    monkeypatch.setattr(
        "monitor.voice.synthesis.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHttpResponse(b"wav-audio", "audio/wav"),
    )

    with pytest.raises(RuntimeError, match="edge failed"):
        synthesize_speech(
            _request(tmp_path, provider="edge-tts", metadata={"fallback_allowed": False}),
            {"local_tts_url": "http://tts.local"},
            build_synthesis_registry(),
        )


def test_synthesize_speech_does_not_fallback_from_local_runtime_failure(tmp_path, monkeypatch):
    def fail_urlopen(*_args, **_kwargs):
        raise RuntimeError("tts down")

    monkeypatch.setattr("monitor.voice.synthesis.urllib.request.urlopen", fail_urlopen)

    with pytest.raises(RuntimeError, match="tts down"):
        synthesize_speech(
            _request(tmp_path, provider="local"),
            {"local_tts_url": "http://tts.local"},
            build_synthesis_registry(),
        )

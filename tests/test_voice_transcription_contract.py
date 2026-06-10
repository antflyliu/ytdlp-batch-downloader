from __future__ import annotations

import json

from monitor.voice.capabilities import TRANSCRIPTION
from monitor.voice.schemas import TranscriptionRequest
from monitor.voice.transcription import (
    VibeVoiceAsrProvider,
    WhisperApiTranscriptionProvider,
    build_transcription_registry,
    build_voice_registry,
    transcribe_audio,
)


class FakeResponse:
    text = "fallback text"

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_transcription_registry_registers_asr_providers():
    registry = build_transcription_registry()

    assert [provider.provider_id for provider in registry.providers()] == [
        "whisper_local",
        "whisper_api",
        "vibevoice_asr",
        "vibevoice_vllm_asr",
    ]
    assert all(TRANSCRIPTION in provider.info().capabilities for provider in registry.providers())


def test_voice_registry_contains_synthesis_and_transcription_providers():
    registry = build_voice_registry()

    assert registry.get("edge_tts") is not None
    assert registry.get("whisper_api") is not None
    assert registry.get("vibevoice_asr") is not None


def test_whisper_api_posts_openai_compatible_transcription_request(monkeypatch, tmp_path):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        seen["data"] = kwargs.get("data")
        seen["files"] = kwargs.get("files")
        return FakeResponse(
            {
                "text": "hello transcript",
                "language": "en",
                "segments": [{"start": 0, "end": 1.2, "text": "hello transcript"}],
            }
        )

    monkeypatch.setattr("monitor.voice.transcription.requests.post", fake_post)

    result = WhisperApiTranscriptionProvider().transcribe(
        TranscriptionRequest(media_path=media, output_dir=tmp_path / "out", language_hint="en"),
        {
            "whisper_base_url": "https://asr.example/v1-compatible",
            "whisper_api_key": "sk-test",
            "whisper_model": "whisper-1",
        },
    )

    assert seen["url"] == "https://asr.example/v1-compatible/v1/audio/transcriptions"
    assert seen["headers"] == {"Authorization": "Bearer sk-test"}
    assert seen["data"] == {"model": "whisper-1", "language": "en"}
    assert "file" in seen["files"]
    assert result.provider == "whisper_api"
    assert result.text == "hello transcript"
    assert result.transcript_path.read_text(encoding="utf-8") == "hello transcript"
    assert "00:00:00,000 --> 00:00:01,200" in result.srt_path.read_text(encoding="utf-8")
    metadata = json.loads(result.raw_path.read_text(encoding="utf-8"))
    assert metadata["provider"] == "whisper_api"
    assert metadata["capability"] == "transcription"


def test_vibevoice_asr_accepts_generic_transcription_response(monkeypatch, tmp_path):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["data"] = kwargs.get("data")
        return FakeResponse({"transcript": "vibe transcript"})

    monkeypatch.setattr("monitor.voice.transcription.requests.post", fake_post)

    result = VibeVoiceAsrProvider().transcribe(
        TranscriptionRequest(
            media_path=media,
            output_dir=tmp_path / "out",
            language_hint="zh",
            hotwords=["VibeVoice"],
        ),
        {"vibevoice_asr_base_url": "http://127.0.0.1:8000"},
    )

    assert seen["url"] == "http://127.0.0.1:8000/asr"
    assert seen["data"]["language"] == "zh"
    assert seen["data"]["hotwords"] == "VibeVoice"
    assert result.provider == "vibevoice_asr"
    assert result.text == "vibe transcript"


def test_transcribe_audio_resolves_configured_transcription_provider(monkeypatch, tmp_path):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")

    monkeypatch.setattr(
        "monitor.voice.transcription.requests.post",
        lambda *_args, **_kwargs: FakeResponse({"text": "selected by flow default"}),
    )

    result = transcribe_audio(
        TranscriptionRequest(media_path=media, output_dir=tmp_path / "out", flow="article_generation"),
        {
            "voice_flow_defaults_json": '{"article_generation.transcription":"whisper_api"}',
            "whisper_base_url": "https://asr.example",
        },
    )

    assert result.provider == "whisper_api"
    assert result.text == "selected by flow default"

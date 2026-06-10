from __future__ import annotations

import pytest

from scripts import article_generator


def test_article_transcription_keeps_legacy_local_whisper_wrapper(tmp_path, monkeypatch):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    progress_messages = []

    def fake_local(video_path, cfg, *, progress=None):
        assert video_path == str(media)
        assert cfg["whisper_provider"] == "local"
        if progress:
            progress("local progress")
        return "local transcript"

    monkeypatch.setattr(article_generator, "_local_whisper", fake_local)
    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: None)

    result = article_generator._transcribe_article_audio(
        str(media),
        tmp_path / "out",
        {"whisper_provider": "local"},
        task_id="article_1",
        progress=progress_messages.append,
    )

    assert result.provider == "whisper_local"
    assert result.text == "local transcript"
    assert progress_messages == ["local progress"]


def test_article_transcription_flow_default_can_select_whisper_api(tmp_path, monkeypatch):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")

    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: "api transcript")

    result = article_generator._transcribe_article_audio(
        str(media),
        tmp_path / "out",
        {
            "voice_flow_defaults_json": '{"article_generation.transcription":"whisper_api"}',
            "whisper_base_url": "https://asr.example",
        },
        task_id="article_2",
    )

    assert result.provider == "whisper_api"
    assert result.text == "api transcript"


def test_article_transcription_vibevoice_failure_falls_back_when_allowed(tmp_path, monkeypatch):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")

    def fail_vibevoice(*_args, **_kwargs):
        raise RuntimeError("vibevoice unavailable")

    monkeypatch.setattr(article_generator.VibeVoiceAsrProvider, "transcribe", fail_vibevoice)
    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: "fallback transcript")

    result = article_generator._transcribe_article_audio(
        str(media),
        tmp_path / "out",
        {
            "voice_flow_defaults_json": '{"article_generation.transcription":"vibevoice_asr"}',
            "vibevoice_asr_base_url": "http://127.0.0.1:8000",
            "whisper_base_url": "https://asr.example",
        },
        task_id="article_3",
    )

    assert result.provider == "whisper_api"
    assert result.text == "fallback transcript"


def test_article_transcription_vibevoice_failure_prefers_legacy_local_fallback(tmp_path, monkeypatch):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")

    def fail_vibevoice(*_args, **_kwargs):
        raise RuntimeError("vibevoice unavailable")

    monkeypatch.setattr(article_generator.VibeVoiceAsrProvider, "transcribe", fail_vibevoice)
    monkeypatch.setattr(article_generator, "_local_whisper", lambda *_args, **_kwargs: "local fallback")
    monkeypatch.setattr(article_generator, "_remote_whisper", lambda *_args, **_kwargs: "api fallback")

    result = article_generator._transcribe_article_audio(
        str(media),
        tmp_path / "out",
        {
            "voice_flow_defaults_json": '{"article_generation.transcription":"vibevoice_asr"}',
            "vibevoice_asr_base_url": "http://127.0.0.1:8000",
            "whisper_provider": "local",
        },
        task_id="article_3b",
    )

    assert result.provider == "whisper_local"
    assert result.text == "local fallback"


def test_article_transcription_vibevoice_failure_respects_disabled_fallback(tmp_path, monkeypatch):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")

    def fail_vibevoice(*_args, **_kwargs):
        raise RuntimeError("vibevoice unavailable")

    monkeypatch.setattr(article_generator.VibeVoiceAsrProvider, "transcribe", fail_vibevoice)

    with pytest.raises(RuntimeError, match="vibevoice unavailable"):
        article_generator._transcribe_article_audio(
            str(media),
            tmp_path / "out",
            {
                "voice_flow_defaults_json": '{"article_generation.transcription":"vibevoice_asr"}',
                "vibevoice_asr_base_url": "http://127.0.0.1:8000",
                "voice_asr_fallback_allowed": "false",
            },
            task_id="article_4",
        )

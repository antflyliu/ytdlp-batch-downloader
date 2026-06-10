from __future__ import annotations

from monitor.voice.schemas import SpeechSynthesisResult
from monitor.voice.storage import write_silent_wav
from scripts.video_gen_pipeline import VideoGenerationPipeline


def test_video_pipeline_synthesizes_narration_through_voice_facade(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(request, cfg):
        calls.append({"request": request, "cfg": cfg})
        audio_path = write_silent_wav(request.output_dir, request.output_name, duration_sec=0.1)
        return SpeechSynthesisResult(
            provider="fake_voice",
            path=audio_path,
            mime_type="audio/wav",
            duration_sec=0.1,
        )

    monkeypatch.setattr("scripts.video_gen_pipeline.synthesize_speech", fake_synthesize)
    pipeline = VideoGenerationPipeline("video_gen_contract", cfg={"tts_provider": "edge-tts"})

    audio_path, provider, duration = pipeline._synthesize_narration(
        [{"narration": "hello world"}],
        tmp_path,
        {"task_id": "video_1", "tts_workflow": "openai_speech"},
    )

    assert provider == "fake_voice"
    assert audio_path.endswith("narration.wav")
    assert duration > 0
    assert calls[0]["request"].provider == "openai_speech"
    assert calls[0]["request"].flow == "video_generation"
    assert calls[0]["request"].source_task_id == "video_1"


def test_video_pipeline_passes_legacy_tts_provider_when_task_has_no_override(tmp_path, monkeypatch):
    calls = []

    def fake_synthesize(request, cfg):
        calls.append({"request": request, "cfg": cfg})
        audio_path = write_silent_wav(request.output_dir, request.output_name, duration_sec=0.1)
        return SpeechSynthesisResult(provider="fake_voice", path=audio_path, mime_type="audio/wav")

    monkeypatch.setattr("scripts.video_gen_pipeline.synthesize_speech", fake_synthesize)
    pipeline = VideoGenerationPipeline("video_gen_contract", cfg={"tts_provider": "edge-tts"})

    pipeline._synthesize_narration([{"narration": "hello world"}], tmp_path, {})

    assert calls[0]["request"].provider is None
    assert calls[0]["cfg"]["tts_provider"] == "edge-tts"


def test_video_pipeline_global_local_default_without_url_can_fallback_to_silent(tmp_path):
    pipeline = VideoGenerationPipeline(
        "video_gen_contract",
        cfg={"tts_provider": "local", "voice_fallback_order": "silent"},
    )

    audio_path, provider, duration = pipeline._synthesize_narration(
        [{"narration": "hello world"}],
        tmp_path,
        {},
    )

    assert provider == "silent"
    assert duration > 0
    with open(audio_path, "rb") as audio_file:
        assert audio_file.read(4) == b"RIFF"

from __future__ import annotations

from pathlib import Path

from monitor.voice.capabilities import (
    SPEECH_SYNTHESIS,
    TRANSCRIPTION,
    normalize_provider_id,
)
from monitor.voice.providers import ProviderInfo, VoiceProviderRegistry
from monitor.voice.schemas import (
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    TranscriptSegment,
    TranscriptionRequest,
    TranscriptionResult,
)


class FakeProvider:
    def __init__(self, provider_id: str, capabilities: list[str], sort_order: int = 50):
        self.provider_id = provider_id
        self._capabilities = capabilities
        self._sort_order = sort_order

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label=self.provider_id.replace("_", " ").title(),
            capabilities=list(self._capabilities),
            sort_order=self._sort_order,
        )

    def is_configured(self, _cfg):
        return True


def test_voice_provider_aliases_are_normalized():
    assert normalize_provider_id("edge-tts") == "edge_tts"
    assert normalize_provider_id("EDGE") == "edge_tts"
    assert normalize_provider_id("local-tts") == "local_http_tts"
    assert normalize_provider_id("offline") == "silent"
    assert normalize_provider_id("mock") == "silent"
    assert normalize_provider_id("none") == "silent"
    assert normalize_provider_id("voxcpm") == "voxcpm_http"
    assert normalize_provider_id("vibevoice_api") == "vibevoice_tts"


def test_registry_filters_providers_by_capability_and_keeps_sort_order():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("whisper_api", [TRANSCRIPTION], sort_order=20))
    registry.register(FakeProvider("edge_tts", [SPEECH_SYNTHESIS], sort_order=10))
    registry.register(FakeProvider("openai_speech", [SPEECH_SYNTHESIS], sort_order=5))

    synthesis_ids = [provider.provider_id for provider in registry.providers_for_capability(SPEECH_SYNTHESIS)]

    assert synthesis_ids == ["openai_speech", "edge_tts"]
    assert registry.get("edge-tts").provider_id == "edge_tts"
    assert registry.get("whisper_api").provider_id == "whisper_api"


def test_speech_synthesis_request_and_result_contracts_use_paths(tmp_path):
    request = SpeechSynthesisRequest(
        text="hello",
        output_dir=tmp_path,
        provider="edge-tts",
        flow="video_generation",
        source_task_id="video_1",
    )
    result = SpeechSynthesisResult(
        provider="edge_tts",
        path=tmp_path / "narration.mp3",
        mime_type="audio/mpeg",
        metadata_path=tmp_path / "metadata.json",
        raw_metadata={"voice": "en-US-AriaNeural"},
    )

    assert request.output_dir == tmp_path
    assert request.provider == "edge-tts"
    assert request.flow == "video_generation"
    assert result.path == tmp_path / "narration.mp3"
    assert result.raw_metadata["voice"] == "en-US-AriaNeural"


def test_transcription_contract_supports_speaker_segments(tmp_path):
    request = TranscriptionRequest(
        media_path=Path("input.mp4"),
        output_dir=tmp_path,
        provider="vibevoice_asr",
        flow="article_generation",
        hotwords=["VibeVoice"],
    )
    result = TranscriptionResult(
        provider="vibevoice_asr",
        text="hello world",
        segments=[
            TranscriptSegment(start=0.0, end=1.2, text="hello world", speaker="Speaker 1"),
        ],
        transcript_path=tmp_path / "transcript.txt",
    )

    assert request.hotwords == ["VibeVoice"]
    assert result.segments[0].speaker == "Speaker 1"
    assert result.transcript_path == tmp_path / "transcript.txt"

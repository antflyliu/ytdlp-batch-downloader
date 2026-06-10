from __future__ import annotations

from monitor.voice.capabilities import TRANSCRIPTION
from monitor.voice.selection import ProviderSelectionRequest, resolve_provider
from monitor.voice.transcription import build_transcription_registry


def test_article_generation_transcription_uses_flow_default_provider():
    result = resolve_provider(
        ProviderSelectionRequest(flow="article_generation", capability=TRANSCRIPTION),
        {
            "voice_flow_defaults_json": '{"article_generation.transcription":"vibevoice_asr"}',
            "vibevoice_asr_base_url": "http://127.0.0.1:8000",
        },
        build_transcription_registry(),
    )

    assert result.provider_id == "vibevoice_asr"
    assert result.reason == "flow_default"


def test_article_generation_transcription_keeps_legacy_whisper_provider_default():
    result = resolve_provider(
        ProviderSelectionRequest(flow="article_generation", capability=TRANSCRIPTION),
        {
            "whisper_provider": "local",
        },
        build_transcription_registry(),
    )

    assert result.provider_id == "whisper_local"
    assert result.reason == "legacy_whisper_provider"


def test_article_generation_transcription_can_request_whisper_api_directly():
    result = resolve_provider(
        ProviderSelectionRequest(
            flow="article_generation",
            capability=TRANSCRIPTION,
            requested_provider="whisper_api",
        ),
        {
            "whisper_base_url": "https://asr.example",
        },
        build_transcription_registry(),
    )

    assert result.provider_id == "whisper_api"
    assert result.reason == "requested_provider"

from __future__ import annotations

import pytest

from monitor.voice.capabilities import SPEECH_SYNTHESIS, TRANSCRIPTION
from monitor.voice.providers import ProviderInfo, VoiceProviderRegistry
from monitor.voice.selection import (
    ProviderSelectionError,
    ProviderSelectionRequest,
    resolve_provider,
)


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        capabilities: list[str],
        *,
        modes: list[str] | None = None,
        configured: bool = True,
        sort_order: int = 50,
    ):
        self.provider_id = provider_id
        self._capabilities = capabilities
        self._modes = modes or []
        self._configured = configured
        self._sort_order = sort_order

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label=self.provider_id,
            capabilities=list(self._capabilities),
            modes=list(self._modes),
            sort_order=self._sort_order,
        )

    def is_configured(self, _cfg):
        return self._configured


def _registry() -> VoiceProviderRegistry:
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("edge_tts", [SPEECH_SYNTHESIS], sort_order=20))
    registry.register(FakeProvider("local_http_tts", [SPEECH_SYNTHESIS], sort_order=25))
    registry.register(FakeProvider("openai_speech", [SPEECH_SYNTHESIS], sort_order=10))
    registry.register(FakeProvider("azure_speech", [SPEECH_SYNTHESIS], sort_order=30))
    registry.register(FakeProvider("silent", [SPEECH_SYNTHESIS], sort_order=100))
    registry.register(FakeProvider("whisper_local", [TRANSCRIPTION], sort_order=10))
    registry.register(FakeProvider("whisper_api", [TRANSCRIPTION], sort_order=20))
    return registry


def test_task_level_provider_beats_flow_and_global_defaults():
    result = resolve_provider(
        ProviderSelectionRequest(
            capability=SPEECH_SYNTHESIS,
            flow="video_generation",
            requested_provider="openai_speech",
        ),
        {
            "voice_provider": "azure_speech",
            "voice_flow_defaults_json": '{"video_generation.speech_synthesis": "edge-tts"}',
        },
        _registry(),
    )

    assert result.provider_id == "openai_speech"
    assert result.fallback_chain == ["openai_speech"]
    assert result.reason == "requested_provider"


def test_flow_default_beats_global_capability_default():
    result = resolve_provider(
        ProviderSelectionRequest(capability=SPEECH_SYNTHESIS, flow="video_generation"),
        {
            "voice_provider": "azure_speech",
            "voice_flow_defaults_json": {"video_generation.speech_synthesis": "edge-tts"},
        },
        _registry(),
    )

    assert result.provider_id == "edge_tts"
    assert result.reason == "flow_default"


def test_legacy_tts_provider_is_used_when_unified_defaults_are_absent():
    result = resolve_provider(
        ProviderSelectionRequest(capability=SPEECH_SYNTHESIS, flow="video_generation"),
        {"tts_provider": "edge-tts"},
        _registry(),
    )

    assert result.provider_id == "edge_tts"
    assert result.reason == "legacy_tts_provider"


@pytest.mark.parametrize(
    ("tts_workflow", "expected_provider"),
    [
        ("edge-tts", "edge_tts"),
        ("local", "local_http_tts"),
        ("local-tts", "local_http_tts"),
        ("silent", "silent"),
    ],
)
def test_legacy_tts_workflow_beats_flow_and_global_defaults(tts_workflow, expected_provider):
    result = resolve_provider(
        ProviderSelectionRequest(capability=SPEECH_SYNTHESIS, flow="video_generation"),
        {
            "tts_workflow": tts_workflow,
            "voice_provider": "azure_speech",
            "voice_flow_defaults_json": {"video_generation.speech_synthesis": "openai_speech"},
        },
        _registry(),
    )

    assert result.provider_id == expected_provider
    assert result.reason == "legacy_tts_workflow"


def test_legacy_whisper_provider_maps_to_transcription_provider():
    result = resolve_provider(
        ProviderSelectionRequest(capability=TRANSCRIPTION, flow="article_generation"),
        {"whisper_provider": "local"},
        _registry(),
    )

    assert result.provider_id == "whisper_local"
    assert result.reason == "legacy_whisper_provider"


def test_global_voice_provider_does_not_override_transcription_defaults():
    result = resolve_provider(
        ProviderSelectionRequest(capability=TRANSCRIPTION, flow="article_generation"),
        {"voice_provider": "edge_tts", "whisper_provider": "api"},
        _registry(),
    )

    assert result.provider_id == "whisper_api"
    assert result.reason == "legacy_whisper_provider"


def test_transcription_provider_default_is_separate_from_voice_provider():
    result = resolve_provider(
        ProviderSelectionRequest(capability=TRANSCRIPTION, flow="clip_pipeline"),
        {"voice_provider": "edge_tts", "transcription_provider": "whisper-local"},
        _registry(),
    )

    assert result.provider_id == "whisper_local"
    assert result.reason == "transcription_provider"


def test_explicit_unavailable_provider_fails_when_fallback_is_not_allowed():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("openai_speech", [SPEECH_SYNTHESIS], configured=False))
    registry.register(FakeProvider("silent", [SPEECH_SYNTHESIS]))

    with pytest.raises(ProviderSelectionError, match="not configured"):
        resolve_provider(
            ProviderSelectionRequest(
                capability=SPEECH_SYNTHESIS,
                flow="manual_voice",
                requested_provider="openai_speech",
                fallback_allowed=False,
            ),
            {"voice_fallback_order": "silent"},
            registry,
        )


def test_unavailable_requested_provider_can_fallback_when_policy_allows_it():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("openai_speech", [SPEECH_SYNTHESIS], configured=False))
    registry.register(FakeProvider("edge_tts", [SPEECH_SYNTHESIS]))
    registry.register(FakeProvider("silent", [SPEECH_SYNTHESIS]))

    result = resolve_provider(
        ProviderSelectionRequest(
            capability=SPEECH_SYNTHESIS,
            flow="manual_voice",
            requested_provider="openai_speech",
            fallback_allowed=True,
        ),
        {"voice_fallback_order": "edge_tts,silent"},
        registry,
    )

    assert result.provider_id == "edge_tts"
    assert result.fallback_chain == ["openai_speech", "edge_tts"]
    assert result.reason == "fallback"


def test_explicit_real_provider_does_not_fallback_to_silent():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("openai_speech", [SPEECH_SYNTHESIS], configured=False))
    registry.register(FakeProvider("silent", [SPEECH_SYNTHESIS]))

    with pytest.raises(ProviderSelectionError, match="silent fallback is not allowed"):
        resolve_provider(
            ProviderSelectionRequest(
                capability=SPEECH_SYNTHESIS,
                flow="manual_voice",
                requested_provider="openai_speech",
                fallback_allowed=True,
            ),
            {"voice_fallback_order": "silent"},
            registry,
        )


def test_explicit_silent_provider_is_allowed():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("silent", [SPEECH_SYNTHESIS]))

    result = resolve_provider(
        ProviderSelectionRequest(
            capability=SPEECH_SYNTHESIS,
            flow="manual_voice",
            requested_provider="silent",
        ),
        {},
        registry,
    )

    assert result.provider_id == "silent"
    assert result.reason == "requested_provider"


def test_requested_mode_must_be_supported_by_provider():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("edge_tts", [SPEECH_SYNTHESIS], modes=["plain_tts"]))

    with pytest.raises(ProviderSelectionError, match="does not support mode"):
        resolve_provider(
            ProviderSelectionRequest(
                capability=SPEECH_SYNTHESIS,
                flow="manual_voice",
                requested_provider="edge_tts",
                mode="voice_design",
            ),
            {},
            registry,
        )


def test_requested_supported_mode_resolves_provider():
    registry = VoiceProviderRegistry()
    registry.register(FakeProvider("voxcpm_http", [SPEECH_SYNTHESIS], modes=["voice_design"]))

    result = resolve_provider(
        ProviderSelectionRequest(
            capability=SPEECH_SYNTHESIS,
            flow="manual_voice",
            requested_provider="voxcpm_http",
            mode="voice_design",
        ),
        {},
        registry,
    )

    assert result.provider_id == "voxcpm_http"
    assert result.mode == "voice_design"


def test_provider_without_requested_capability_fails_before_fallback():
    with pytest.raises(ProviderSelectionError, match="does not support"):
        resolve_provider(
            ProviderSelectionRequest(
                capability=TRANSCRIPTION,
                flow="article_generation",
                requested_provider="edge-tts",
            ),
            {},
            _registry(),
        )

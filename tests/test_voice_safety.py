from __future__ import annotations

import pytest

from monitor.voice.safety import VoiceSafetyError, validate_synthesis_request
from monitor.voice.schemas import SpeechSynthesisRequest


def _request(tmp_path, **overrides):
    payload = {
        "text": "hello",
        "output_dir": tmp_path,
        "provider": "edge_tts",
    }
    payload.update(overrides)
    return SpeechSynthesisRequest(**payload)


def test_text_length_limit_is_enforced(tmp_path):
    request = _request(tmp_path, text="abcdef")

    with pytest.raises(VoiceSafetyError, match="exceeds voice_max_text_chars"):
        validate_synthesis_request(request, {"voice_max_text_chars": 5})


def test_reference_clone_is_disabled_by_default(tmp_path):
    request = _request(tmp_path, reference_audio_path=str(tmp_path / "voice.wav"))

    with pytest.raises(VoiceSafetyError, match="reference clone is disabled"):
        validate_synthesis_request(request, {})


def test_reference_clone_mode_is_disabled_by_default(tmp_path):
    request = _request(tmp_path, mode="reference_clone")

    with pytest.raises(VoiceSafetyError, match="reference clone is disabled"):
        validate_synthesis_request(request, {})


def test_reference_clone_can_be_enabled(tmp_path):
    request = _request(tmp_path, reference_audio_path=str(tmp_path / "voice.wav"))

    validate_synthesis_request(request, {"voice_allow_reference_clone": True})


def test_prompt_transcript_clone_is_disabled_by_default(tmp_path):
    request = _request(tmp_path, prompt_text="speaker transcript")

    with pytest.raises(VoiceSafetyError, match="prompt transcript clone is disabled"):
        validate_synthesis_request(request, {})


def test_prompt_transcript_clone_mode_is_disabled_by_default(tmp_path):
    request = _request(tmp_path, mode="prompt_transcript_clone")

    with pytest.raises(VoiceSafetyError, match="prompt transcript clone is disabled"):
        validate_synthesis_request(request, {})


def test_prompt_transcript_clone_can_be_enabled(tmp_path):
    request = _request(tmp_path, prompt_text="speaker transcript")

    validate_synthesis_request(request, {"voice_allow_prompt_transcript_clone": True})


def test_empty_text_is_rejected(tmp_path):
    request = _request(tmp_path, text="  \n ")

    with pytest.raises(VoiceSafetyError, match="text is required"):
        validate_synthesis_request(request, {})

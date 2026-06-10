"""Safety gates for voice synthesis requests."""

from __future__ import annotations

from typing import Any, Mapping

from .capabilities import PROMPT_TRANSCRIPT_CLONE, REFERENCE_CLONE
from .schemas import SpeechSynthesisRequest


class VoiceSafetyError(ValueError):
    pass


def validate_synthesis_request(
    request: SpeechSynthesisRequest,
    cfg: Mapping[str, Any] | None = None,
) -> None:
    cfg = cfg or {}
    text = request.text or ""
    if not text.strip():
        raise VoiceSafetyError("speech synthesis text is required")

    max_chars = _positive_int(cfg.get("voice_max_text_chars"), default=5000)
    if len(text) > max_chars:
        raise VoiceSafetyError(f"speech synthesis text exceeds voice_max_text_chars={max_chars}")

    if _uses_reference_clone(request) and not _truthy(cfg.get("voice_allow_reference_clone")):
        raise VoiceSafetyError("reference clone is disabled")

    if _uses_prompt_transcript_clone(request) and not _truthy(cfg.get("voice_allow_prompt_transcript_clone")):
        raise VoiceSafetyError("prompt transcript clone is disabled")


def _uses_reference_clone(request: SpeechSynthesisRequest) -> bool:
    return bool(request.reference_audio_path or request.mode == REFERENCE_CLONE)


def _uses_prompt_transcript_clone(request: SpeechSynthesisRequest) -> bool:
    return bool(request.prompt_text or request.mode == PROMPT_TRANSCRIPT_CLONE)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)

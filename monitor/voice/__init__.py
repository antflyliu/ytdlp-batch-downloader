"""Unified voice provider contracts and selection helpers."""

from .capabilities import (
    PROMPT_TRANSCRIPT_CLONE,
    REFERENCE_CLONE,
    SPEECH_SYNTHESIS,
    SSML,
    STREAMING_SYNTHESIS,
    TRANSCRIPTION,
    VOICE_DESIGN,
    VOICE_LIST,
    normalize_provider_id,
)
from .providers import ProviderInfo, VoiceProviderRegistry
from .schemas import (
    SpeechSynthesisRequest,
    SpeechSynthesisResult,
    TranscriptSegment,
    TranscriptionRequest,
    TranscriptionResult,
)
from .selection import ProviderSelectionError, ProviderSelectionRequest, ProviderSelectionResult, resolve_provider
from .storage import (
    create_voice_task_dir,
    hash_file,
    hash_text,
    resolve_voice_output_root,
    safe_output_path,
    voice_audio_output_path,
    write_audio_bytes,
    write_metadata,
    write_silent_wav,
)
from .synthesis import build_synthesis_registry, synthesize_speech
from .transcription import build_transcription_registry, build_voice_registry, transcribe_audio

__all__ = [
    "PROMPT_TRANSCRIPT_CLONE",
    "REFERENCE_CLONE",
    "SPEECH_SYNTHESIS",
    "SSML",
    "STREAMING_SYNTHESIS",
    "TRANSCRIPTION",
    "VOICE_DESIGN",
    "VOICE_LIST",
    "ProviderInfo",
    "VoiceProviderRegistry",
    "SpeechSynthesisRequest",
    "SpeechSynthesisResult",
    "TranscriptSegment",
    "TranscriptionRequest",
    "TranscriptionResult",
    "ProviderSelectionError",
    "ProviderSelectionRequest",
    "ProviderSelectionResult",
    "normalize_provider_id",
    "resolve_provider",
    "create_voice_task_dir",
    "hash_file",
    "hash_text",
    "resolve_voice_output_root",
    "safe_output_path",
    "voice_audio_output_path",
    "write_audio_bytes",
    "write_metadata",
    "write_silent_wav",
    "build_synthesis_registry",
    "synthesize_speech",
    "build_transcription_registry",
    "build_voice_registry",
    "transcribe_audio",
]

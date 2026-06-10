"""Voice provider capability and provider-id constants."""

from __future__ import annotations

SPEECH_SYNTHESIS = "speech_synthesis"
TRANSCRIPTION = "transcription"
STREAMING_SYNTHESIS = "streaming_synthesis"
VOICE_DESIGN = "voice_design"
REFERENCE_CLONE = "reference_clone"
PROMPT_TRANSCRIPT_CLONE = "prompt_transcript_clone"
SSML = "ssml"
VOICE_LIST = "voice_list"

SILENT = "silent"
EDGE_TTS = "edge_tts"
LOCAL_HTTP_TTS = "local_http_tts"
OPENAI_SPEECH = "openai_speech"
AZURE_SPEECH = "azure_speech"
MINIMAX_SPEECH = "minimax_speech"
VOXCPM_HTTP = "voxcpm_http"
VOXCPM_OPENAI_SPEECH = "voxcpm_openai_speech"
VIBEVOICE_TTS = "vibevoice_tts"
VIBEVOICE_REALTIME = "vibevoice_realtime"
WHISPER_LOCAL = "whisper_local"
WHISPER_API = "whisper_api"
VIBEVOICE_ASR = "vibevoice_asr"
VIBEVOICE_VLLM_ASR = "vibevoice_vllm_asr"

PROVIDER_ALIASES = {
    "edge": EDGE_TTS,
    "edge-tts": EDGE_TTS,
    "edge_tts": EDGE_TTS,
    "local": LOCAL_HTTP_TTS,
    "local-tts": LOCAL_HTTP_TTS,
    "local-http-tts": LOCAL_HTTP_TTS,
    "local_http": LOCAL_HTTP_TTS,
    "local_http_tts": LOCAL_HTTP_TTS,
    "offline": SILENT,
    "offline-silence": SILENT,
    "mock": SILENT,
    "none": SILENT,
    "silent": SILENT,
    "openai": OPENAI_SPEECH,
    "openai-speech": OPENAI_SPEECH,
    "openai_speech": OPENAI_SPEECH,
    "azure": AZURE_SPEECH,
    "azure-speech": AZURE_SPEECH,
    "azure_speech": AZURE_SPEECH,
    "minimax": MINIMAX_SPEECH,
    "minimax-speech": MINIMAX_SPEECH,
    "minimax_speech": MINIMAX_SPEECH,
    "voxcpm": VOXCPM_HTTP,
    "voxcpm-http": VOXCPM_HTTP,
    "voxcpm_http": VOXCPM_HTTP,
    "voxcpm-openai-speech": VOXCPM_OPENAI_SPEECH,
    "voxcpm_openai_speech": VOXCPM_OPENAI_SPEECH,
    "vibevoice": VIBEVOICE_TTS,
    "vibevoice-api": VIBEVOICE_TTS,
    "vibevoice_api": VIBEVOICE_TTS,
    "vibevoice-tts": VIBEVOICE_TTS,
    "vibevoice_tts": VIBEVOICE_TTS,
    "vibevoice-realtime": VIBEVOICE_REALTIME,
    "vibevoice_realtime": VIBEVOICE_REALTIME,
    "whisper-local": WHISPER_LOCAL,
    "whisper_local": WHISPER_LOCAL,
    "whisper-api": WHISPER_API,
    "whisper_api": WHISPER_API,
    "vibevoice-asr": VIBEVOICE_ASR,
    "vibevoice_asr": VIBEVOICE_ASR,
    "vibevoice-vllm-asr": VIBEVOICE_VLLM_ASR,
    "vibevoice_vllm_asr": VIBEVOICE_VLLM_ASR,
}


def normalize_provider_id(value: str | None) -> str:
    """Return the canonical provider id for user/config input."""

    raw = str(value or "").strip().lower().replace(" ", "_")
    if not raw:
        return ""
    return PROVIDER_ALIASES.get(raw, raw.replace("-", "_"))


def split_provider_order(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Parse a comma-separated/list fallback order into canonical provider ids."""

    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    return [provider_id for provider_id in (normalize_provider_id(part) for part in parts) if provider_id]

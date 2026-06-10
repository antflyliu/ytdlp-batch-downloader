"""Transcription provider implementations for the unified voice domain."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping

import requests

from .capabilities import TRANSCRIPTION, VIBEVOICE_ASR, VIBEVOICE_VLLM_ASR, WHISPER_API, WHISPER_LOCAL
from .providers import ProviderInfo, VoiceProviderRegistry
from .schemas import TranscriptSegment, TranscriptionRequest, TranscriptionResult
from .selection import ProviderSelectionRequest, resolve_provider
from .storage import safe_output_path, write_metadata


class WhisperApiTranscriptionProvider:
    provider_id = WHISPER_API

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Whisper API",
            capabilities=[TRANSCRIPTION],
            configured=False,
            fields=["model", "language_hint"],
            modes=["transcription"],
            sort_order=20,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("whisper_base_url") or "").strip())

    def transcribe(self, request: TranscriptionRequest, cfg: Mapping[str, Any]) -> TranscriptionResult:
        media_path = _require_media_path(request.media_path)
        base_url = str(cfg.get("whisper_base_url") or "").rstrip("/")
        if not base_url:
            raise RuntimeError("whisper_base_url is required for whisper_api")
        headers = _bearer_headers(cfg.get("whisper_api_key"))
        data = {"model": str(cfg.get("whisper_model") or "base")}
        language = _language_hint(request, cfg.get("whisper_language"))
        if language:
            data["language"] = language
        with media_path.open("rb") as file_obj:
            response = requests.post(
                f"{base_url}/v1/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": file_obj},
                timeout=int(cfg.get("whisper_timeout_seconds") or 300),
            )
        response.raise_for_status()
        payload = _response_json(response)
        text = _first_text(payload, response.text)
        return _materialize_transcription_result(request, self.provider_id, text, payload)


class WhisperLocalTranscriptionProvider:
    provider_id = WHISPER_LOCAL

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Whisper Local",
            capabilities=[TRANSCRIPTION],
            configured=False,
            fields=["model", "language_hint"],
            modes=["transcription"],
            sort_order=10,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, request: TranscriptionRequest, cfg: Mapping[str, Any]) -> TranscriptionResult:
        media_path = _require_media_path(request.media_path)
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError("faster-whisper is required for whisper_local") from exc
        model_name = str(cfg.get("whisper_model") or "base")
        device = str(cfg.get("whisper_device") or "cpu")
        compute_type = str(cfg.get("whisper_compute_type") or "int8")
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(str(media_path), language=_language_hint(request, cfg.get("whisper_language")) or None)
        normalized_segments = [
            TranscriptSegment(
                start=getattr(segment, "start", None),
                end=getattr(segment, "end", None),
                text=str(getattr(segment, "text", "") or "").strip(),
            )
            for segment in segments
        ]
        text = "\n".join(segment.text for segment in normalized_segments if segment.text).strip()
        raw_metadata = {
            "language": getattr(info, "language", None),
            "duration": getattr(info, "duration", None),
            "segments": [segment.__dict__ for segment in normalized_segments],
        }
        return _materialize_transcription_result(
            request,
            self.provider_id,
            text,
            raw_metadata,
            language=getattr(info, "language", None),
            segments=normalized_segments,
        )


class VibeVoiceAsrProvider:
    provider_id = VIBEVOICE_ASR

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VibeVoice ASR Service",
            capabilities=[TRANSCRIPTION],
            configured=False,
            fields=["model", "language_hint", "hotwords"],
            modes=["transcription"],
            sort_order=80,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("vibevoice_asr_base_url") or "").strip())

    def transcribe(self, request: TranscriptionRequest, cfg: Mapping[str, Any]) -> TranscriptionResult:
        return _post_generic_asr(
            request,
            cfg,
            provider_id=self.provider_id,
            base_url_key="vibevoice_asr_base_url",
            api_key_key="vibevoice_asr_api_key",
            default_endpoint="/asr",
        )


class VibeVoiceVllmAsrProvider(VibeVoiceAsrProvider):
    provider_id = VIBEVOICE_VLLM_ASR

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VibeVoice vLLM ASR Service",
            capabilities=[TRANSCRIPTION],
            configured=False,
            fields=["model", "language_hint", "hotwords"],
            modes=["transcription"],
            sort_order=85,
        )

    def transcribe(self, request: TranscriptionRequest, cfg: Mapping[str, Any]) -> TranscriptionResult:
        return _post_generic_asr(
            request,
            cfg,
            provider_id=self.provider_id,
            base_url_key="vibevoice_vllm_asr_base_url",
            api_key_key="vibevoice_vllm_asr_api_key",
            default_endpoint="/v1/audio/transcriptions",
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("vibevoice_vllm_asr_base_url") or cfg.get("vibevoice_asr_base_url") or "").strip())


def build_transcription_registry() -> VoiceProviderRegistry:
    registry = VoiceProviderRegistry()
    registry.register(WhisperLocalTranscriptionProvider())
    registry.register(WhisperApiTranscriptionProvider())
    registry.register(VibeVoiceAsrProvider())
    registry.register(VibeVoiceVllmAsrProvider())
    return registry


def build_voice_registry() -> VoiceProviderRegistry:
    from .synthesis import build_synthesis_registry

    registry = build_synthesis_registry()
    for provider in build_transcription_registry().providers():
        registry.register(provider)
    return registry


def transcribe_audio(
    request: TranscriptionRequest,
    cfg: Mapping[str, Any] | None = None,
    registry: VoiceProviderRegistry | None = None,
) -> TranscriptionResult:
    cfg = cfg or {}
    registry = registry or build_transcription_registry()
    selection = resolve_provider(
        ProviderSelectionRequest(
            capability=TRANSCRIPTION,
            flow=request.flow,
            mode="transcription",
            requested_provider=request.provider,
            fallback_allowed=bool(request.metadata.get("fallback_allowed", True)),
            options=dict(request.metadata),
        ),
        cfg,
        registry,
    )
    provider = registry.require(selection.provider_id)
    return provider.transcribe(request, cfg)


def _post_generic_asr(
    request: TranscriptionRequest,
    cfg: Mapping[str, Any],
    *,
    provider_id: str,
    base_url_key: str,
    api_key_key: str,
    default_endpoint: str,
) -> TranscriptionResult:
    media_path = _require_media_path(request.media_path)
    base_url = str(cfg.get(base_url_key) or cfg.get("vibevoice_asr_base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError(f"{base_url_key} is required for {provider_id}")
    endpoint = base_url if base_url.endswith(("/asr", "/transcriptions")) else f"{base_url}{default_endpoint}"
    headers = _bearer_headers(cfg.get(api_key_key) or cfg.get("vibevoice_asr_api_key"))
    data = {
        "model": str(cfg.get("vibevoice_asr_model") or cfg.get("whisper_model") or "base"),
        "language": _language_hint(request, cfg.get("whisper_language")) or "",
        "hotwords": ",".join(request.hotwords or []),
    }
    with media_path.open("rb") as file_obj:
        response = requests.post(
            endpoint,
            headers=headers,
            data=data,
            files={"file": file_obj},
            timeout=int(cfg.get("vibevoice_asr_timeout_seconds") or 300),
        )
    response.raise_for_status()
    payload = _response_json(response)
    text = _first_text(payload, response.text)
    return _materialize_transcription_result(request, provider_id, text, payload)


def _materialize_transcription_result(
    request: TranscriptionRequest,
    provider_id: str,
    text: str,
    raw_metadata: Mapping[str, Any] | None = None,
    *,
    language: str | None = None,
    segments: list[TranscriptSegment] | None = None,
) -> TranscriptionResult:
    output_dir = safe_output_path(request.output_dir, ".")
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = safe_output_path(output_dir, "transcript.txt")
    transcript_path.write_text(text, encoding="utf-8")
    normalized_segments = segments or _segments_from_payload(raw_metadata or {})
    srt_path = None
    if normalized_segments:
        srt_path = safe_output_path(output_dir, "transcript.srt")
        srt_path.write_text(_segments_to_srt(normalized_segments), encoding="utf-8")
    metadata_path = write_metadata(
        output_dir,
        {
            "provider": provider_id,
            "capability": TRANSCRIPTION,
            "source": request.source,
            "source_task_id": request.source_task_id or "manual_transcription",
            "input_text_hash": "media",
            "language": language or _payload_language(raw_metadata or {}),
            "segments": [segment.__dict__ for segment in normalized_segments],
            "response_json": raw_metadata or {},
        },
    )
    return TranscriptionResult(
        provider=provider_id,
        text=text,
        language=language or _payload_language(raw_metadata or {}),
        transcript_path=transcript_path,
        srt_path=srt_path,
        raw_path=metadata_path,
        segments=normalized_segments,
        raw_metadata=dict(raw_metadata or {}),
    )


def _require_media_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError("transcription media_path must exist")
    return path


def _bearer_headers(api_key: Any) -> dict[str, str]:
    key = str(api_key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _language_hint(request: TranscriptionRequest, fallback: Any) -> str:
    language = str(request.language_hint or fallback or "").strip()
    return "" if language.lower() in {"", "auto", "none"} else language


def _response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_text(payload: Mapping[str, Any], fallback: str = "") -> str:
    for key in ("text", "transcript", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        if isinstance(message, Mapping) and isinstance(message.get("content"), str):
            return message["content"].strip()
    return str(fallback or "").strip()


def _payload_language(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("language")
    return str(value).strip() if value else None


def _segments_from_payload(payload: Mapping[str, Any]) -> list[TranscriptSegment]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return []
    segments = []
    for item in raw_segments:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=_float_or_none(item.get("start")),
                end=_float_or_none(item.get("end")),
                text=text,
                speaker=str(item.get("speaker") or "").strip() or None,
            )
        )
    return segments


def _segments_to_srt(segments: list[TranscriptSegment]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        start = _srt_timestamp(segment.start or 0)
        end = _srt_timestamp(segment.end if segment.end is not None else (segment.start or 0) + 1)
        label = f"{segment.speaker}: " if segment.speaker else ""
        blocks.append(f"{index}\n{start} --> {end}\n{label}{segment.text}")
    return "\n\n".join(blocks).strip() + "\n"


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    sec = total_seconds % 60
    total_minutes = total_seconds // 60
    minute = total_minutes % 60
    hour = total_minutes // 60
    return f"{hour:02d}:{minute:02d}:{sec:02d},{ms:03d}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

"""Speech synthesis provider implementations and facade."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from .capabilities import (
    AZURE_SPEECH,
    EDGE_TTS,
    LOCAL_HTTP_TTS,
    MINIMAX_SPEECH,
    OPENAI_SPEECH,
    PROMPT_TRANSCRIPT_CLONE,
    REFERENCE_CLONE,
    SILENT,
    SPEECH_SYNTHESIS,
    SSML,
    VIBEVOICE_REALTIME,
    VIBEVOICE_TTS,
    VOICE_DESIGN,
    VOXCPM_HTTP,
    VOXCPM_OPENAI_SPEECH,
)
from .providers import ProviderInfo, VoiceProviderRegistry
from .safety import validate_synthesis_request
from .schemas import SpeechSynthesisRequest, SpeechSynthesisResult
from .selection import ProviderSelectionRequest, resolve_provider
from .storage import hash_text, voice_audio_output_path, write_audio_bytes, write_metadata, write_silent_wav

_MAX_PROVIDER_RESPONSE_BYTES = 100 * 1024 * 1024
_MAX_PROVIDER_ERROR_BYTES = 8192


class SilentSpeechProvider:
    provider_id = SILENT

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Silent WAV",
            capabilities=[SPEECH_SYNTHESIS],
            configured=True,
            sort_order=1000,
        )

    def is_configured(self, _cfg: Mapping[str, Any]) -> bool:
        return True

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        duration_sec = _estimated_duration(request)
        audio_path = write_silent_wav(request.output_dir, request.output_name, duration_sec=duration_sec)
        metadata_path = _write_synthesis_metadata(request, cfg, self.provider_id, {"duration_sec": duration_sec})
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type="audio/wav",
            duration_sec=duration_sec,
            sample_rate=16000,
            metadata_path=metadata_path,
        )


class EdgeTtsSpeechProvider:
    provider_id = EDGE_TTS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Edge TTS",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["voice"],
            modes=["plain_tts"],
            sort_order=20,
        )

    def is_configured(self, _cfg: Mapping[str, Any]) -> bool:
        return bool(_edge_command_path())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        command_path = _edge_command_path()
        if not command_path:
            raise RuntimeError("未找到 edge-tts 命令")
        output_path = voice_audio_output_path(request.output_dir, request.output_name, "mp3")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [command_path, "--text", request.text, "--write-media", str(output_path)]
        voice = request.voice or str(cfg.get("tts_voice") or "").strip()
        if voice:
            command.extend(["--voice", voice])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(cfg),
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "edge-tts synthesis failed").strip())
        metadata_path = _write_synthesis_metadata(request, cfg, self.provider_id, {"voice": voice or None})
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=output_path,
            mime_type="audio/mpeg",
            metadata_path=metadata_path,
            raw_metadata={"voice": voice or None},
        )


class LocalHttpTtsProvider:
    provider_id = LOCAL_HTTP_TTS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Local HTTP TTS",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["voice", "response_format"],
            modes=["plain_tts"],
            sort_order=30,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("local_tts_url") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        raw_url = str(cfg.get("local_tts_url") or "").rstrip("/")
        if not raw_url:
            raise ValueError("local_tts_url 未配置")
        payload = {
            "text": request.text,
            "voice": request.voice or str(cfg.get("tts_voice") or ""),
            "format": request.response_format,
        }
        data, content_type, raw_metadata = _post_json_audio(_local_tts_endpoint(raw_url), payload, _timeout_seconds(cfg))
        if "json" in content_type.lower():
            audio_path, mime_type = _materialize_json_audio(request.output_dir, request.output_name, data, raw_metadata)
        else:
            response_format = _response_format_from_content_type(content_type, request.response_format)
            audio_path = write_audio_bytes(request.output_dir, request.output_name, data, response_format)
            mime_type = _mime_type_for_format(response_format)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {"content_type": content_type, **raw_metadata},
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=mime_type,
            metadata_path=metadata_path,
            raw_metadata=raw_metadata,
        )


class OpenAiSpeechProvider:
    provider_id = OPENAI_SPEECH

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="OpenAI Speech",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["model", "voice", "response_format", "speed", "control_instruction"],
            modes=["plain_tts"],
            safety={"ai_disclosure_required": True},
            sort_order=40,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("openai_speech_api_key") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        api_key = _require_config(cfg, "openai_speech_api_key")
        base_url = str(cfg.get("openai_speech_base_url") or "https://api.openai.com/v1").rstrip("/")
        response_format = _normalized_audio_format(request.response_format, default="mp3")
        payload = {
            "model": request.model or str(cfg.get("openai_speech_model") or "gpt-4o-mini-tts"),
            "input": request.text,
            "voice": request.voice or str(cfg.get("openai_speech_voice") or "alloy"),
            "response_format": response_format,
        }
        if request.speed is not None:
            payload["speed"] = request.speed
        if request.control_instruction:
            payload["instructions"] = request.control_instruction
        endpoint = _append_endpoint(base_url, "audio/speech")
        data, content_type, raw_metadata = _post_json_audio(
            endpoint,
            payload,
            _timeout_seconds(cfg),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        audio_path, mime_type, response_metadata = _materialize_audio_response(
            request.output_dir,
            request.output_name,
            data,
            content_type,
            response_format,
            source_endpoint=endpoint,
            timeout=_timeout_seconds(cfg),
        )
        raw_metadata.update(response_metadata)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {
                "model": payload["model"],
                "voice": payload["voice"],
                "response_format": response_format,
                **raw_metadata,
            },
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=mime_type,
            metadata_path=metadata_path,
            raw_metadata=raw_metadata,
        )


class AzureSpeechProvider:
    provider_id = AZURE_SPEECH

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="Azure Speech",
            capabilities=[SPEECH_SYNTHESIS, SSML],
            fields=["voice", "language", "style", "speed", "pitch", "volume"],
            modes=["plain_tts"],
            sort_order=50,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        has_endpoint = bool(
            str(cfg.get("azure_speech_endpoint") or "").strip()
            or str(cfg.get("azure_speech_region") or "").strip()
        )
        return has_endpoint and bool(str(cfg.get("azure_speech_api_key") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        api_key = _require_config(cfg, "azure_speech_api_key")
        endpoint = _azure_speech_endpoint(cfg)
        voice = request.voice or str(cfg.get("azure_speech_voice") or "").strip()
        if not voice:
            raise ValueError("azure_speech_voice is required")
        language = request.language or _language_from_voice(voice) or "en-US"
        output_format = str(
            cfg.get("azure_speech_output_format") or "riff-24khz-16bit-mono-pcm"
        ).strip()
        ssml = _azure_ssml(request, voice=voice, language=language)
        data, content_type, raw_metadata = _post_bytes(
            endpoint,
            ssml.encode("utf-8"),
            _timeout_seconds(cfg),
            headers={
                "Content-Type": "application/ssml+xml",
                "Ocp-Apim-Subscription-Key": api_key,
                "X-Microsoft-OutputFormat": output_format,
                "User-Agent": "ytdlp-batch-downloader",
            },
        )
        response_format = _azure_response_format(output_format, content_type)
        audio_path = write_audio_bytes(
            request.output_dir,
            request.output_name,
            data,
            response_format,
        )
        mime_type = _mime_type_for_format(response_format)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {
                "voice": voice,
                "language": language,
                "output_format": output_format,
                **raw_metadata,
            },
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=mime_type,
            metadata_path=metadata_path,
            raw_metadata=raw_metadata,
        )


class MiniMaxSpeechProvider:
    provider_id = MINIMAX_SPEECH

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="MiniMax Speech",
            capabilities=[SPEECH_SYNTHESIS, VOICE_DESIGN, REFERENCE_CLONE],
            fields=["model", "voice", "language", "response_format", "speed", "pitch", "volume"],
            modes=["plain_tts", "voice_design", "reference_clone"],
            safety={"reference_clone_requires_opt_in": True},
            sort_order=60,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("minimax_speech_api_key") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        api_key = _require_config(cfg, "minimax_speech_api_key")
        base_url = str(cfg.get("minimax_speech_base_url") or "https://api.minimax.io").rstrip("/")
        if request.mode == VOICE_DESIGN:
            return self._design_voice(request, cfg, base_url=base_url, api_key=api_key)
        if request.mode == REFERENCE_CLONE:
            return self._clone_voice(request, cfg, base_url=base_url, api_key=api_key)
        return self._synthesize_t2a(request, cfg, base_url=base_url, api_key=api_key)

    def _synthesize_t2a(
        self,
        request: SpeechSynthesisRequest,
        cfg: Mapping[str, Any],
        *,
        base_url: str,
        api_key: str,
        voice_override: str | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> SpeechSynthesisResult:
        response_format = _normalized_audio_format(request.response_format, default="mp3")
        if response_format not in {"mp3", "wav", "flac"}:
            raise ValueError("MiniMax non-streaming speech supports mp3, wav, or flac")
        voice = voice_override or request.voice or str(cfg.get("minimax_speech_voice") or "").strip()
        if not voice:
            raise ValueError("minimax_speech_voice or request voice is required")
        payload = {
            "model": request.model or str(cfg.get("minimax_speech_model") or "speech-2.8-hd"),
            "text": request.text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {
                "voice_id": voice,
                "speed": _coerce_number(request.speed, 1.0),
                "vol": _coerce_number(request.volume, 1.0),
                "pitch": _coerce_number(request.pitch, 0),
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": response_format,
                "channel": 1,
            },
        }
        if request.language and request.language != "auto":
            payload["language_boost"] = _minimax_language_boost(request.language)
        endpoint = _append_endpoint(base_url, "v1/t2a_v2")
        data, content_type, raw_metadata = _post_json_audio(
            endpoint,
            payload,
            _timeout_seconds(cfg),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        audio_path, mime_type, response_metadata = _materialize_audio_response(
            request.output_dir,
            request.output_name,
            data,
            content_type,
            response_format,
            source_endpoint=endpoint,
            timeout=_timeout_seconds(cfg),
        )
        raw_metadata.update(response_metadata)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {
                "model": payload["model"],
                "voice": payload["voice_setting"]["voice_id"],
                "response_format": response_format,
                **dict(extra_metadata or {}),
                **raw_metadata,
            },
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=mime_type,
            metadata_path=metadata_path,
            raw_metadata=raw_metadata,
        )

    def _design_voice(
        self,
        request: SpeechSynthesisRequest,
        cfg: Mapping[str, Any],
        *,
        base_url: str,
        api_key: str,
    ) -> SpeechSynthesisResult:
        prompt = str(request.control_instruction or "").strip()
        if not prompt:
            raise ValueError("MiniMax voice_design requires control_instruction")
        if len(request.text) > 500:
            raise ValueError("MiniMax voice_design preview text must be 500 characters or less")
        payload = {"prompt": prompt, "preview_text": request.text}
        if request.voice:
            payload["voice_id"] = request.voice
        data, content_type, raw_metadata = _post_json_audio(
            _append_endpoint(base_url, "v1/voice_design"),
            payload,
            _timeout_seconds(cfg),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if "json" not in content_type.lower():
            raise RuntimeError("MiniMax voice_design returned a non-JSON response")
        try:
            response = json.loads(data.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("MiniMax voice_design returned invalid JSON") from exc
        if not isinstance(response, Mapping):
            raise RuntimeError("MiniMax voice_design returned a non-object response")
        _raise_provider_json_error(response)
        trial_audio = str(response.get("trial_audio") or "").strip()
        voice_id = str(response.get("voice_id") or request.voice or "").strip()
        if not trial_audio or not voice_id:
            raise RuntimeError("MiniMax voice_design did not return trial_audio and voice_id")
        try:
            audio_bytes = bytes.fromhex(trial_audio)
        except ValueError as exc:
            raise RuntimeError("MiniMax voice_design returned invalid trial audio") from exc
        response_format = _normalized_audio_format(request.response_format, default="mp3")
        audio_path = write_audio_bytes(
            request.output_dir,
            request.output_name,
            audio_bytes,
            response_format,
        )
        response_metadata = _response_metadata(response)
        raw_metadata.update(response_metadata)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {
                "mode": VOICE_DESIGN,
                "voice": voice_id,
                "response_format": response_format,
                **raw_metadata,
            },
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=_mime_type_for_format(response_format),
            metadata_path=metadata_path,
            raw_metadata={"voice_id": voice_id, **raw_metadata},
        )

    def _clone_voice(
        self,
        request: SpeechSynthesisRequest,
        cfg: Mapping[str, Any],
        *,
        base_url: str,
        api_key: str,
    ) -> SpeechSynthesisResult:
        reference_path = _validated_minimax_reference_audio(request.reference_audio_path, cfg)
        file_id = _minimax_upload_audio(
            base_url,
            api_key,
            reference_path,
            purpose="voice_clone",
            timeout=_timeout_seconds(cfg),
        )
        voice_id = request.voice or _generated_minimax_voice_id(request.source_task_id)
        clone_payload = {
            "file_id": file_id,
            "voice_id": voice_id,
            "need_noise_reduction": bool(request.denoise_reference),
            "need_volume_normalization": bool(request.metadata.get("normalize_volume", False)),
        }
        clone_data, clone_content_type, clone_metadata = _post_json_audio(
            _append_endpoint(base_url, "v1/voice_clone"),
            clone_payload,
            _timeout_seconds(cfg),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if "json" not in clone_content_type.lower():
            raise RuntimeError("MiniMax voice_clone returned a non-JSON response")
        try:
            clone_response = json.loads(clone_data.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("MiniMax voice_clone returned invalid JSON") from exc
        if not isinstance(clone_response, Mapping):
            raise RuntimeError("MiniMax voice_clone returned a non-object response")
        _raise_provider_json_error(clone_response)
        return self._synthesize_t2a(
            request,
            cfg,
            base_url=base_url,
            api_key=api_key,
            voice_override=voice_id,
            extra_metadata={
                "mode": REFERENCE_CLONE,
                "clone_file_id": file_id,
                "clone_response": _response_metadata(clone_response),
                **clone_metadata,
            },
        )


class VoxCpmOpenAiSpeechProvider:
    provider_id = VOXCPM_OPENAI_SPEECH

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VoxCPM OpenAI-compatible",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["model", "voice", "response_format"],
            modes=["plain_tts"],
            sort_order=70,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("voxcpm_base_url") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        base_url = _require_config(cfg, "voxcpm_base_url").rstrip("/")
        response_format = _normalized_audio_format(request.response_format, default="wav")
        payload = {
            "model": request.model or str(cfg.get("voxcpm_model") or "openbmb/VoxCPM2"),
            "input": request.text,
            "voice": request.voice or str(cfg.get("voxcpm_default_voice") or "default"),
            "response_format": response_format,
        }
        headers = _bearer_headers(cfg.get("voxcpm_api_key"))
        endpoint = _append_endpoint(base_url, "audio/speech", ensure_version=True)
        data, content_type, raw_metadata = _post_json_audio(
            endpoint,
            payload,
            _timeout_seconds(cfg),
            headers=headers,
        )
        audio_path, mime_type, response_metadata = _materialize_audio_response(
            request.output_dir,
            request.output_name,
            data,
            content_type,
            response_format,
            source_endpoint=endpoint,
            timeout=_timeout_seconds(cfg),
        )
        raw_metadata.update(response_metadata)
        metadata_path = _write_synthesis_metadata(
            request,
            cfg,
            self.provider_id,
            {
                "model": payload["model"],
                "voice": payload["voice"],
                "response_format": response_format,
                **raw_metadata,
            },
        )
        return SpeechSynthesisResult(
            provider=self.provider_id,
            path=audio_path,
            mime_type=mime_type,
            metadata_path=metadata_path,
            raw_metadata=raw_metadata,
        )


class VoxCpmHttpProvider:
    provider_id = VOXCPM_HTTP

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VoxCPM HTTP",
            capabilities=[
                SPEECH_SYNTHESIS,
                VOICE_DESIGN,
                REFERENCE_CLONE,
                PROMPT_TRANSCRIPT_CLONE,
            ],
            fields=[
                "model",
                "voice",
                "response_format",
                "control_instruction",
                "reference_audio_path",
                "prompt_text",
            ],
            modes=["plain_tts", "voice_design", "reference_clone", "prompt_transcript_clone"],
            safety={
                "reference_clone_requires_opt_in": True,
                "prompt_transcript_clone_requires_opt_in": True,
            },
            sort_order=80,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("voxcpm_base_url") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        base_url = _require_config(cfg, "voxcpm_base_url").rstrip("/")
        response_format = _normalized_audio_format(request.response_format, default="wav")
        payload = _generic_service_payload(
            request,
            model=request.model or str(cfg.get("voxcpm_model") or "openbmb/VoxCPM2"),
            voice=request.voice or str(cfg.get("voxcpm_default_voice") or "default"),
            response_format=response_format,
            default_control_instruction=str(
                cfg.get("voxcpm_default_control_instruction") or ""
            ).strip(),
        )
        return _synthesize_generic_http(
            provider_id=self.provider_id,
            request=request,
            cfg=cfg,
            endpoint=_append_endpoint(base_url, "tts"),
            payload=payload,
            headers=_bearer_headers(cfg.get("voxcpm_api_key")),
            response_format=response_format,
        )


class VibeVoiceTtsProvider:
    provider_id = VIBEVOICE_TTS

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VibeVoice TTS Service",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["model", "voice", "response_format", "control_instruction"],
            modes=["plain_tts"],
            sort_order=90,
        )

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        return bool(str(cfg.get("vibevoice_tts_base_url") or "").strip())

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        return self._synthesize(request, cfg, streaming=False)

    def _synthesize(
        self,
        request: SpeechSynthesisRequest,
        cfg: Mapping[str, Any],
        *,
        streaming: bool,
    ) -> SpeechSynthesisResult:
        validate_synthesis_request(request, cfg)
        base_url = _require_config(cfg, "vibevoice_tts_base_url").rstrip("/")
        response_format = _normalized_audio_format(request.response_format, default="wav")
        payload = _generic_service_payload(
            request,
            model=request.model
            or str(cfg.get("vibevoice_tts_model") or "microsoft/VibeVoice-Realtime-0.5B"),
            voice=request.voice or str(cfg.get("vibevoice_tts_voice") or "Carter"),
            response_format=response_format,
        )
        payload["streaming"] = streaming
        return _synthesize_generic_http(
            provider_id=self.provider_id,
            request=request,
            cfg=cfg,
            endpoint=_append_endpoint(base_url, "tts"),
            payload=payload,
            headers=_bearer_headers(cfg.get("vibevoice_tts_api_key")),
            response_format=response_format,
        )


class VibeVoiceRealtimeProvider(VibeVoiceTtsProvider):
    provider_id = VIBEVOICE_REALTIME

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self.provider_id,
            label="VibeVoice Realtime Service",
            capabilities=[SPEECH_SYNTHESIS],
            fields=["model", "voice", "response_format", "control_instruction"],
            modes=["plain_tts"],
            sort_order=95,
        )

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        return self._synthesize(request, cfg, streaming=True)


def build_synthesis_registry() -> VoiceProviderRegistry:
    registry = VoiceProviderRegistry()
    registry.register(SilentSpeechProvider())
    registry.register(EdgeTtsSpeechProvider())
    registry.register(LocalHttpTtsProvider())
    registry.register(OpenAiSpeechProvider())
    registry.register(AzureSpeechProvider())
    registry.register(MiniMaxSpeechProvider())
    registry.register(VoxCpmOpenAiSpeechProvider())
    registry.register(VoxCpmHttpProvider())
    registry.register(VibeVoiceTtsProvider())
    registry.register(VibeVoiceRealtimeProvider())
    return registry


def synthesize_speech(
    request: SpeechSynthesisRequest,
    cfg: Mapping[str, Any] | None = None,
    registry: VoiceProviderRegistry | None = None,
) -> SpeechSynthesisResult:
    cfg = cfg or {}
    registry = registry or build_synthesis_registry()
    selection = resolve_provider(
        ProviderSelectionRequest(
            capability=SPEECH_SYNTHESIS,
            flow=request.flow,
            mode=request.mode,
            requested_provider=request.provider,
            fallback_allowed=bool(request.metadata.get("fallback_allowed", True)),
            options=dict(request.metadata),
        ),
        cfg,
        registry,
    )
    provider = registry.require(selection.provider_id)
    try:
        return provider.synthesize(request, cfg)
    except Exception:
        if selection.provider_id == EDGE_TTS and bool(request.metadata.get("fallback_allowed", True)):
            local_provider = registry.get(LOCAL_HTTP_TTS)
            if local_provider is not None and local_provider.is_configured(cfg):
                return local_provider.synthesize(request, cfg)
        raise


def _estimated_duration(request: SpeechSynthesisRequest) -> float:
    explicit = request.metadata.get("estimated_duration_sec")
    try:
        if explicit:
            return max(0.05, float(explicit))
    except (TypeError, ValueError):
        pass
    return max(1.0, min(180.0, len(request.text or "") / 4.5))


def _edge_command_path() -> str | None:
    return shutil.which("edge-tts") or shutil.which("edge-tts.exe")


def _timeout_seconds(cfg: Mapping[str, Any]) -> int:
    try:
        timeout = int(cfg.get("voice_timeout_seconds") or cfg.get("tts_timeout_seconds") or 300)
    except (TypeError, ValueError):
        return 300
    return max(1, timeout)


def _local_tts_endpoint(raw_url: str) -> str:
    if re.search(r"/(tts|synthesize|audio)(/)?$", raw_url, re.I):
        return raw_url
    return f"{raw_url}/tts"


def _post_json_audio(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    headers: Mapping[str, str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(dict(headers or {}))
    return _post_bytes(url, body, timeout, headers=request_headers)


def _post_bytes(
    url: str,
    body: bytes,
    timeout: int,
    headers: Mapping[str, str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers or {}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = _read_limited(response, _MAX_PROVIDER_RESPONSE_BYTES)
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return data, content_type, {
                "endpoint": _endpoint_metadata(url),
                "status_code": getattr(response, "status", None),
            }
    except urllib.error.HTTPError as exc:
        detail = _read_limited(exc, _MAX_PROVIDER_ERROR_BYTES).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _materialize_json_audio(
    output_dir: str | Path,
    output_name: str,
    data: bytes,
    raw_metadata: dict[str, Any],
) -> tuple[Path, str]:
    try:
        payload = json.loads(data.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("local HTTP TTS returned invalid JSON") from exc
    raw_metadata["response_json"] = payload
    audio_hex = _first_string(payload, {"audio", "audio_hex", "hex_audio"})
    if audio_hex:
        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise RuntimeError("local HTTP TTS returned invalid hex audio") from exc
        return write_audio_bytes(output_dir, output_name, audio_bytes, "wav"), "audio/wav"
    raise RuntimeError(f"本地 TTS 未返回可用音频: {payload}")


def _read_limited(stream: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = stream.read(1024 * 1024)
        except TypeError:
            data = stream.read()
            if len(data) > max_bytes:
                raise RuntimeError("speech provider response exceeds size limit")
            return data
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError("speech provider response exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _materialize_audio_response(
    output_dir: str | Path,
    output_name: str,
    data: bytes,
    content_type: str,
    fallback_format: str,
    *,
    source_endpoint: str | None = None,
    timeout: int = 300,
) -> tuple[Path, str, dict[str, Any]]:
    if "json" not in str(content_type or "").lower():
        response_format = _response_format_from_content_type(content_type, fallback_format)
        return (
            write_audio_bytes(output_dir, output_name, data, response_format),
            _mime_type_for_format(response_format),
            {},
        )

    try:
        payload = json.loads(data.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("speech provider returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("speech provider returned a non-object JSON response")
    _raise_provider_json_error(payload)

    response_format = _json_audio_format(payload, fallback_format)
    audio_url = _first_string(payload, {"audio_url", "file_url", "download_url", "url"})
    if audio_url:
        if not _is_same_origin_audio_url(audio_url, source_endpoint):
            raise RuntimeError("speech provider returned an audio URL outside provider origin")
        audio_bytes, downloaded_content_type = _download_audio(
            audio_url,
            source_endpoint=source_endpoint,
            timeout=timeout,
        )
        response_format = _response_format_from_content_type(downloaded_content_type, response_format)
        return (
            write_audio_bytes(output_dir, output_name, audio_bytes, response_format),
            _mime_type_for_format(response_format),
            _response_metadata(payload),
        )

    audio_base64 = _first_string(payload, {"audio_base64", "base64_audio", "audio_b64"})
    if audio_base64:
        try:
            audio_bytes = base64.b64decode(audio_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("speech provider returned invalid base64 audio") from exc
        return (
            write_audio_bytes(output_dir, output_name, audio_bytes, response_format),
            _mime_type_for_format(response_format),
            _response_metadata(payload),
        )

    audio_hex = _first_string(payload, {"audio_hex", "hex_audio"})
    if not audio_hex:
        audio_hex = _first_string(payload, {"audio"})
    if audio_hex:
        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError:
            try:
                audio_bytes = base64.b64decode(audio_hex, validate=True)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("speech provider returned invalid encoded audio") from exc
        return (
            write_audio_bytes(output_dir, output_name, audio_bytes, response_format),
            _mime_type_for_format(response_format),
            _response_metadata(payload),
        )

    audio_path = _first_string(payload, {"audio_path", "file_path", "output_path", "path"})
    if audio_path:
        source_path = _safe_returned_audio_path(output_dir, audio_path)
        if source_path.stat().st_size > _MAX_PROVIDER_RESPONSE_BYTES:
            raise RuntimeError("speech provider returned audio file exceeds size limit")
        response_format = _normalized_audio_format(source_path.suffix, default=response_format)
        return (
            write_audio_bytes(output_dir, output_name, source_path.read_bytes(), response_format),
            _mime_type_for_format(response_format),
            _response_metadata(payload),
        )

    raise RuntimeError(f"speech provider did not return usable audio: {_response_metadata(payload)}")


def _synthesize_generic_http(
    *,
    provider_id: str,
    request: SpeechSynthesisRequest,
    cfg: Mapping[str, Any],
    endpoint: str,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    response_format: str,
) -> SpeechSynthesisResult:
    data, content_type, raw_metadata = _post_json_audio(
        endpoint,
        payload,
        _timeout_seconds(cfg),
        headers=headers,
    )
    audio_path, mime_type, response_metadata = _materialize_audio_response(
        request.output_dir,
        request.output_name,
        data,
        content_type,
        response_format,
        source_endpoint=endpoint,
        timeout=_timeout_seconds(cfg),
    )
    raw_metadata.update(response_metadata)
    metadata_path = _write_synthesis_metadata(
        request,
        cfg,
        provider_id,
        {
            "model": payload.get("model"),
            "voice": payload.get("voice"),
            "response_format": response_format,
            **raw_metadata,
        },
    )
    return SpeechSynthesisResult(
        provider=provider_id,
        path=audio_path,
        mime_type=mime_type,
        metadata_path=metadata_path,
        raw_metadata=raw_metadata,
    )


def _generic_service_payload(
    request: SpeechSynthesisRequest,
    *,
    model: str,
    voice: str,
    response_format: str,
    default_control_instruction: str = "",
) -> dict[str, Any]:
    payload = {
        "text": request.text,
        "voice": voice,
        "model": model,
        "mode": request.mode or "plain_tts",
        "response_format": response_format,
        "normalize_text": request.normalize_text,
        "denoise_reference": request.denoise_reference,
        "streaming": request.streaming,
    }
    control_instruction = request.control_instruction or default_control_instruction
    if control_instruction:
        payload["control_instruction"] = control_instruction
    if request.reference_audio_path:
        payload["reference_audio_path"] = request.reference_audio_path
    if request.prompt_text:
        payload["prompt_text"] = request.prompt_text
    return {key: value for key, value in payload.items() if value is not None}


def _azure_speech_endpoint(cfg: Mapping[str, Any]) -> str:
    endpoint = str(cfg.get("azure_speech_endpoint") or "").strip()
    if endpoint:
        return endpoint
    region = str(cfg.get("azure_speech_region") or "").strip()
    if not region:
        raise ValueError("azure_speech_region or azure_speech_endpoint is required")
    return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"


def _azure_ssml(request: SpeechSynthesisRequest, *, voice: str, language: str) -> str:
    synthesis_ns = "http://www.w3.org/2001/10/synthesis"
    mstts_ns = "https://www.w3.org/2001/mstts"
    xml_ns = "http://www.w3.org/XML/1998/namespace"
    ET.register_namespace("", synthesis_ns)
    ET.register_namespace("mstts", mstts_ns)
    speak = ET.Element(
        f"{{{synthesis_ns}}}speak",
        {"version": "1.0", f"{{{xml_ns}}}lang": language},
    )
    voice_element = ET.SubElement(
        speak,
        f"{{{synthesis_ns}}}voice",
        {"name": voice, f"{{{xml_ns}}}lang": language},
    )
    content_parent = voice_element
    if request.style:
        content_parent = ET.SubElement(
            voice_element,
            f"{{{mstts_ns}}}express-as",
            {"style": request.style},
        )
    prosody_attrs = {}
    if request.speed is not None:
        prosody_attrs["rate"] = _azure_rate(request.speed)
    if request.pitch:
        prosody_attrs["pitch"] = str(request.pitch)
    if request.volume:
        prosody_attrs["volume"] = str(request.volume)
    if prosody_attrs:
        content_parent = ET.SubElement(
            content_parent,
            f"{{{synthesis_ns}}}prosody",
            prosody_attrs,
        )
    content_parent.text = request.text
    return ET.tostring(speak, encoding="unicode")


def _azure_rate(speed: Any) -> str:
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return str(speed)
    percent = round((value - 1.0) * 100)
    return f"{percent:+d}%"


def _language_from_voice(voice: str) -> str:
    match = re.match(r"^([a-z]{2,3}-[A-Z]{2})-", str(voice or ""))
    return match.group(1) if match else ""


def _azure_response_format(output_format: str, content_type: str) -> str:
    lowered = str(output_format or "").lower()
    if "mp3" in lowered:
        return "mp3"
    if "opus" in lowered:
        return "opus"
    if "riff" in lowered:
        return "wav"
    if "raw" in lowered:
        return "pcm"
    return _response_format_from_content_type(content_type, "wav")


def _append_endpoint(base_url: str, endpoint: str, *, ensure_version: bool = False) -> str:
    base = str(base_url or "").rstrip("/")
    suffix = str(endpoint or "").strip("/")
    if ensure_version and not re.search(r"/v\d+$", base, re.I):
        base = f"{base}/v1"
    if base.lower().endswith(f"/{suffix.lower()}"):
        return base
    return f"{base}/{suffix}"


def _bearer_headers(value: Any) -> dict[str, str]:
    token = str(value or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _require_config(cfg: Mapping[str, Any], key: str) -> str:
    value = str(cfg.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _normalized_audio_format(value: Any, *, default: str) -> str:
    normalized = str(value or default).strip().lower().lstrip(".")
    aliases = {"mpeg": "mp3", "wave": "wav"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"mp3", "opus", "aac", "flac", "wav", "pcm"}:
        return default
    return normalized


def _coerce_number(value: Any, default: int | float) -> int | float:
    if value in (None, ""):
        return default
    text = str(value).strip().rstrip("%").replace("dB", "")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return default
    return int(number) if number.is_integer() else number


def _minimax_language_boost(value: str) -> str:
    normalized = str(value or "").strip()
    language_map = {
        "ar": "Arabic",
        "de": "German",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "hi": "Hindi",
        "id": "Indonesian",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "pt": "Portuguese",
        "ru": "Russian",
        "th": "Thai",
        "tr": "Turkish",
        "uk": "Ukrainian",
        "vi": "Vietnamese",
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "zh-hans": "Chinese",
        "zh-hant": "Chinese",
        "zh-hk": "Chinese,Yue",
        "yue": "Chinese,Yue",
    }
    return language_map.get(normalized.lower(), normalized)


def _validated_minimax_reference_audio(value: str | None, cfg: Mapping[str, Any]) -> Path:
    if not value:
        raise ValueError("MiniMax reference_clone requires reference_audio_path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError("MiniMax reference audio file does not exist")
    root = Path(str(cfg.get("voice_reference_audio_dir") or cfg.get("voice_output_dir") or "data/voice")).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("MiniMax reference audio must be inside voice_reference_audio_dir or voice_output_dir") from exc
    if path.suffix.lower() not in {".mp3", ".m4a", ".wav"}:
        raise ValueError("MiniMax reference audio must be mp3, m4a, or wav")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("MiniMax reference audio must be 20 MB or smaller")
    return path


def _generated_minimax_voice_id(source_task_id: str | None) -> str:
    source = re.sub(r"[^A-Za-z0-9_-]+", "", str(source_task_id or ""))[:40]
    suffix = uuid.uuid4().hex[:12]
    return f"Voice{source}{suffix}"[:64]


def _minimax_upload_audio(
    base_url: str,
    api_key: str,
    path: Path,
    *,
    purpose: str,
    timeout: int,
) -> int:
    boundary = f"----VoiceProvider{uuid.uuid4().hex}"
    body = _multipart_file_body(boundary, purpose=purpose, path=path)
    data, content_type, _metadata = _post_bytes(
        _append_endpoint(base_url, "v1/files/upload"),
        body,
        timeout,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    if "json" not in content_type.lower():
        raise RuntimeError("MiniMax file upload returned a non-JSON response")
    try:
        response = json.loads(data.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("MiniMax file upload returned invalid JSON") from exc
    if not isinstance(response, Mapping):
        raise RuntimeError("MiniMax file upload returned a non-object response")
    _raise_provider_json_error(response)
    file_info = response.get("file")
    file_id = file_info.get("file_id") if isinstance(file_info, Mapping) else None
    try:
        return int(file_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("MiniMax file upload did not return file_id") from exc


def _multipart_file_body(boundary: str, *, purpose: str, path: Path) -> bytes:
    safe_filename = path.name.replace('"', "_")
    content_type = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
    }.get(path.suffix.lower(), "application/octet-stream")
    lines = [
        f"--{boundary}\r\n",
        'Content-Disposition: form-data; name="purpose"\r\n\r\n',
        f"{purpose}\r\n",
        f"--{boundary}\r\n",
        f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n',
        f"Content-Type: {content_type}\r\n\r\n",
    ]
    return "".join(lines).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()


def _json_audio_format(payload: Mapping[str, Any], fallback: str) -> str:
    value = _first_string(payload, {"audio_format", "format", "response_format"})
    return _normalized_audio_format(value, default=_normalized_audio_format(fallback, default="wav"))


def _raise_provider_json_error(payload: Mapping[str, Any]) -> None:
    base_resp = payload.get("base_resp")
    if isinstance(base_resp, Mapping):
        status_code = base_resp.get("status_code")
        if status_code not in (None, 0, "0"):
            message = base_resp.get("status_msg") or base_resp.get("message") or "provider error"
            raise RuntimeError(f"speech provider error {status_code}: {message}")
    error = payload.get("error")
    if error:
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("detail") or error
        else:
            message = error
        raise RuntimeError(f"speech provider error: {message}")


def _response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {
        key: _sanitize_response_metadata_value(key, value)
        for key, value in payload.items()
        if _normalized_metadata_key(key)
        not in {
            "audio",
            "audiohex",
            "hexaudio",
            "audiobase64",
            "base64audio",
            "audiob64",
        }
    }
    metadata["response_json"] = _omit_audio_payload(payload)
    return metadata


def _omit_audio_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if _normalized_metadata_key(key) in {
                "audio",
                "audiohex",
                "hexaudio",
                "audiobase64",
                "base64audio",
                "audiob64",
            }:
                result[str(key)] = "<omitted>"
            else:
                result[str(key)] = _sanitize_response_metadata_value(key, item)
        return result
    if isinstance(value, list):
        return [_omit_audio_payload(item) for item in value]
    return value


def _sanitize_response_metadata_value(key: Any, value: Any) -> Any:
    if "url" in _normalized_metadata_key(key) and isinstance(value, str):
        return _sanitize_metadata_url(value)
    return _omit_audio_payload(value)


def _sanitize_metadata_url(raw_url: str) -> str:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "<omitted>"
    host = parsed.hostname or ""
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _normalized_metadata_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _download_audio(
    raw_url: str,
    *,
    source_endpoint: str | None,
    timeout: int,
) -> tuple[bytes, str]:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("speech provider returned an unsupported audio URL")
    if parsed.username or parsed.password:
        raise RuntimeError("speech provider returned an audio URL with embedded credentials")
    _validate_audio_download_host(parsed.hostname, source_endpoint)
    request = urllib.request.Request(raw_url, method="GET")
    with _urlopen_audio(request, timeout=timeout) as response:
        final_url = getattr(response, "geturl", lambda: raw_url)()
        if final_url != raw_url:
            final_parsed = urllib.parse.urlparse(final_url)
            if final_parsed.hostname:
                _validate_audio_download_host(final_parsed.hostname, source_endpoint)
        return (
            _read_limited(response, _MAX_PROVIDER_RESPONSE_BYTES),
            response.headers.get("Content-Type", "application/octet-stream"),
        )


def _is_same_origin_audio_url(raw_url: str, source_endpoint: str | None) -> bool:
    parsed = urllib.parse.urlparse(raw_url)
    source = urllib.parse.urlparse(source_endpoint or "")
    if parsed.scheme not in {"http", "https"} or source.scheme not in {"http", "https"}:
        return False
    parsed_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    source_port = source.port or (443 if source.scheme == "https" else 80)
    return (
        parsed.scheme == source.scheme
        and (parsed.hostname or "").lower() == (source.hostname or "").lower()
        and parsed_port == source_port
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def _urlopen_audio(request: urllib.request.Request, *, timeout: int):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


def _validate_audio_download_host(hostname: str, source_endpoint: str | None) -> None:
    source_host = urllib.parse.urlparse(source_endpoint or "").hostname or ""
    normalized_host = hostname.strip("[]").lower()
    normalized_source = source_host.strip("[]").lower()
    if normalized_host in {"localhost", "localhost.localdomain"}:
        if normalized_host != normalized_source:
            raise RuntimeError("speech provider returned a private audio URL")
        return
    addresses = _resolve_host_addresses(normalized_host)
    if not addresses:
        return
    source_is_same_host = normalized_host == normalized_source
    for address in addresses:
        if address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise RuntimeError("speech provider returned an unsafe audio URL")
        if (address.is_private or address.is_loopback) and not source_is_same_host:
            raise RuntimeError("speech provider returned a private audio URL")


def _resolve_host_addresses(hostname: str) -> list[Any]:
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        raw_address = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    return addresses


def _safe_returned_audio_path(output_dir: str | Path, raw_path: str) -> Path:
    output_root = Path(output_dir).resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = output_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError as exc:
        raise RuntimeError("speech provider returned an unsafe audio path") from exc
    if not candidate.is_file():
        raise RuntimeError("speech provider returned a missing audio path")
    return candidate


def _endpoint_metadata(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.path or "/"


def _first_string(value: Any, keys: set[str]) -> str:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in keys and isinstance(item, str) and item.strip():
                return item.strip()
            nested = _first_string(item, keys)
            if nested:
                return nested
    if isinstance(value, list):
        for item in value:
            nested = _first_string(item, keys)
            if nested:
                return nested
    return ""


def _response_format_from_content_type(content_type: str, fallback: str) -> str:
    lowered = content_type.lower()
    if "mpeg" in lowered or "mp3" in lowered:
        return "mp3"
    if "wav" in lowered or "wave" in lowered:
        return "wav"
    if "aac" in lowered:
        return "aac"
    if "flac" in lowered:
        return "flac"
    if "opus" in lowered:
        return "opus"
    return fallback


def _mime_type_for_format(response_format: str) -> str:
    value = str(response_format or "").lower().lstrip(".")
    if value == "mp3":
        return "audio/mpeg"
    if value == "wav":
        return "audio/wav"
    if value in {"aac", "flac", "opus"}:
        return f"audio/{value}"
    return "application/octet-stream"


def _write_synthesis_metadata(
    request: SpeechSynthesisRequest,
    cfg: Mapping[str, Any],
    provider_id: str,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    metadata = {
        "ai_generated": True,
        "provider": provider_id,
        "capability": SPEECH_SYNTHESIS,
        "source": request.source,
        "source_task_id": request.source_task_id or request.source,
        "input_text_hash": hash_text(request.text),
        "disclosure_required": _truthy(cfg.get("voice_require_disclosure"), default=True),
        "model": request.model,
        "voice": request.voice,
    }
    metadata.update({key: value for key, value in dict(extra or {}).items() if value is not None})
    return write_metadata(request.output_dir, metadata)


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)

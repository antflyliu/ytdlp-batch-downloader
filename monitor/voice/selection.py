"""Flow-aware provider selection for voice capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .capabilities import (
    SILENT,
    SPEECH_SYNTHESIS,
    TRANSCRIPTION,
    WHISPER_API,
    WHISPER_LOCAL,
    normalize_provider_id,
    split_provider_order,
)
from .providers import VoiceProviderRegistry

DEFAULT_SYNTHESIS_FALLBACK_ORDER = ("edge_tts", "local_http_tts", "silent")
DEFAULT_TRANSCRIPTION_FALLBACK_ORDER = ("whisper_api", "whisper_local")


class ProviderSelectionError(ValueError):
    pass


@dataclass
class ProviderSelectionRequest:
    capability: str
    flow: str
    mode: str | None = None
    requested_provider: str | None = None
    fallback_allowed: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSelectionResult:
    provider_id: str
    capability: str
    flow: str
    mode: str | None
    fallback_chain: list[str]
    effective_options: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def resolve_provider(
    request: ProviderSelectionRequest,
    cfg: Mapping[str, Any] | None,
    registry: VoiceProviderRegistry,
) -> ProviderSelectionResult:
    cfg = cfg or {}
    candidates = _selection_candidates(request, cfg)
    attempted: list[str] = []

    for provider_id, reason in candidates:
        provider_id = normalize_provider_id(provider_id)
        if not provider_id or provider_id in attempted:
            continue
        attempted.append(provider_id)
        provider = registry.get(provider_id)
        if provider is None:
            if request.requested_provider and len(attempted) == 1 and not request.fallback_allowed:
                raise ProviderSelectionError(f"voice provider is not registered: {provider_id}")
            continue
        info = provider.info()
        if request.capability not in set(info.capabilities):
            raise ProviderSelectionError(
                f"voice provider {provider_id} does not support capability {request.capability}"
            )
        if request.mode and request.mode not in set(info.modes):
            raise ProviderSelectionError(
                f"voice provider {provider_id} does not support mode {request.mode}"
            )
        if _is_disallowed_silent_fallback(request, provider_id, attempted):
            raise ProviderSelectionError(
                f"silent fallback is not allowed for explicit provider {normalize_provider_id(request.requested_provider)}"
            )
        if provider.is_configured(cfg):
            return ProviderSelectionResult(
                provider_id=provider_id,
                capability=request.capability,
                flow=request.flow,
                mode=request.mode,
                fallback_chain=list(attempted),
                effective_options=dict(request.options),
                reason=reason if len(attempted) == 1 else "fallback",
            )
        if request.requested_provider and len(attempted) == 1 and not request.fallback_allowed:
            raise ProviderSelectionError(f"voice provider {provider_id} is not configured")
        if request.requested_provider and len(attempted) == 1 and not _can_try_fallback(request):
            raise ProviderSelectionError(f"voice provider {provider_id} is not configured")

    if attempted:
        raise ProviderSelectionError(
            f"no configured provider found for capability {request.capability}; attempted: {', '.join(attempted)}"
        )
    raise ProviderSelectionError(f"no provider configured for capability {request.capability}")


def _selection_candidates(
    request: ProviderSelectionRequest,
    cfg: Mapping[str, Any],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    requested = normalize_provider_id(request.requested_provider)
    if requested:
        candidates.append((requested, "requested_provider"))
        if not _can_try_fallback(request):
            return candidates

    task_provider, task_reason = _legacy_task_provider(cfg, request.capability)
    if task_provider:
        candidates.append((task_provider, task_reason))

    flow_default = _flow_default_provider(cfg, request.flow, request.capability)
    if flow_default:
        candidates.append((flow_default, "flow_default"))

    capability_default, reason = _capability_default_provider(cfg, request.capability)
    if capability_default:
        candidates.append((capability_default, reason))

    for provider_id in _fallback_order(cfg, request.capability):
        candidates.append((provider_id, "fallback"))
    return candidates


def _can_try_fallback(request: ProviderSelectionRequest) -> bool:
    return request.fallback_allowed


def _is_disallowed_silent_fallback(
    request: ProviderSelectionRequest,
    provider_id: str,
    attempted: list[str],
) -> bool:
    requested = normalize_provider_id(request.requested_provider)
    return bool(requested and requested != SILENT and provider_id == SILENT and len(attempted) > 1)


def _flow_default_provider(cfg: Mapping[str, Any], flow: str, capability: str) -> str:
    defaults = _parse_flow_defaults(cfg.get("voice_flow_defaults_json"))
    return normalize_provider_id(defaults.get(f"{flow}.{capability}"))


def _legacy_task_provider(cfg: Mapping[str, Any], capability: str) -> tuple[str, str]:
    if capability == SPEECH_SYNTHESIS:
        tts_workflow = normalize_provider_id(cfg.get("tts_workflow"))
        if tts_workflow:
            return tts_workflow, "legacy_tts_workflow"
    return "", ""


def _parse_flow_defaults(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _capability_default_provider(cfg: Mapping[str, Any], capability: str) -> tuple[str, str]:
    if capability == SPEECH_SYNTHESIS:
        voice_provider = normalize_provider_id(cfg.get("voice_provider"))
        if voice_provider:
            return voice_provider, "voice_provider"
        legacy = normalize_provider_id(cfg.get("tts_provider"))
        if legacy:
            return legacy, "legacy_tts_provider"

    if capability == TRANSCRIPTION:
        transcription_provider = normalize_provider_id(cfg.get("transcription_provider"))
        if transcription_provider:
            return transcription_provider, "transcription_provider"
        whisper_provider = str(cfg.get("whisper_provider") or "").strip().lower()
        if whisper_provider == "local":
            return WHISPER_LOCAL, "legacy_whisper_provider"
        if whisper_provider in {"api", "remote", "openai"}:
            return WHISPER_API, "legacy_whisper_provider"

    return "", ""


def _fallback_order(cfg: Mapping[str, Any], capability: str) -> list[str]:
    explicit = split_provider_order(cfg.get("voice_fallback_order"))
    if explicit:
        return explicit
    if capability == SPEECH_SYNTHESIS:
        return list(DEFAULT_SYNTHESIS_FALLBACK_ORDER)
    if capability == TRANSCRIPTION:
        return list(DEFAULT_TRANSCRIPTION_FALLBACK_ORDER)
    return []

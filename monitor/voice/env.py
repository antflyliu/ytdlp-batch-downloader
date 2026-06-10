"""Voice provider discovery, environment diagnostics, and smoke tests."""

from __future__ import annotations

import importlib
import importlib.util
import ipaddress
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Mapping

from .capabilities import normalize_provider_id
from .schemas import SpeechSynthesisRequest
from .selection import ProviderSelectionError, ProviderSelectionRequest, resolve_provider
from .storage import create_voice_task_dir, resolve_voice_output_root
from .synthesis import synthesize_speech
from .transcription import build_voice_registry

_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|authorization|password|secret|subscription[_-]?key|token)", re.I)
_COMMANDS = {
    "ffmpeg": ("ffmpeg", "ffmpeg.exe"),
    "ffprobe": ("ffprobe", "ffprobe.exe"),
    "docker": ("docker", "docker.exe"),
    "nvidia_smi": ("nvidia-smi", "nvidia-smi.exe"),
    "edge_tts": ("edge-tts", "edge-tts.exe"),
}
_OPTIONAL_PACKAGES = {
    "edge_tts": "edge_tts",
    "faster_whisper": "faster_whisper",
    "openai": "openai",
    "torch": "torch",
}
_REMOTE_URL_FIELDS = (
    ("local_http_tts", "local_tts_url", ""),
    ("openai_speech", "openai_speech_base_url", "openai_speech_api_key"),
    ("azure_speech", "azure_speech_endpoint", "azure_speech_api_key"),
    ("minimax_speech", "minimax_speech_base_url", "minimax_speech_api_key"),
    ("voxcpm_http", "voxcpm_base_url", "voxcpm_api_key"),
    ("vibevoice_tts", "vibevoice_tts_base_url", "vibevoice_tts_api_key"),
    ("vibevoice_asr", "vibevoice_asr_base_url", "vibevoice_asr_api_key"),
    ("whisper_api", "whisper_base_url", "whisper_api_key"),
)


def voice_provider_payload(
    cfg: Mapping[str, Any] | None,
    *,
    capability: str | None = None,
    flow: str | None = None,
    registry=None,
) -> dict[str, Any]:
    cfg = cfg or {}
    registry = registry or build_voice_registry()
    normalized_capability = str(capability or "").strip() or None
    normalized_flow = str(flow or "").strip() or None

    providers = (
        registry.providers_for_capability(normalized_capability)
        if normalized_capability
        else registry.providers()
    )

    selected = _selected_provider_payload(cfg, registry, normalized_capability, normalized_flow)
    selected_id = selected.get("provider_id") if selected else ""
    provider_payloads = [
        _provider_info_payload(provider, cfg, selected=provider.provider_id == selected_id)
        for provider in providers
    ]

    return {
        "providers": provider_payloads,
        "capability": normalized_capability,
        "flow": normalized_flow,
        "selected_provider": selected,
    }


def check_voice_environment(
    cfg: Mapping[str, Any] | None,
    *,
    include_remote: bool = False,
    timeout_seconds: int = 3,
) -> dict[str, Any]:
    cfg = cfg or {}
    timeout_seconds = _coerce_timeout(timeout_seconds)
    commands = {name: _command_status(candidates) for name, candidates in _COMMANDS.items()}
    return {
        "ok": True,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "commands": commands,
        "docker": _docker_status(commands.get("docker", {}), timeout_seconds),
        "python_packages": _optional_package_status(),
        "torch": _torch_status(),
        "cuda": _cuda_status(),
        "disk": _disk_status(resolve_voice_output_root(cfg)),
        "remote_base_urls": _remote_base_url_status(cfg, include_remote, timeout_seconds),
    }


def run_voice_smoke_test(body: Mapping[str, Any] | None, cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    body = body or {}
    cfg = cfg or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "smoke test text is required"}
    if len(text) > 300:
        return {"ok": False, "error": "smoke test text must be 300 characters or less"}

    provider = normalize_provider_id(body.get("provider"))
    flow = str(body.get("flow") or "manual_voice").strip() or "manual_voice"
    output_root = resolve_voice_output_root(cfg)
    output_dir = create_voice_task_dir(output_root, f"voice_smoke_{uuid.uuid4().hex[:12]}")
    request = SpeechSynthesisRequest(
        text=text,
        output_dir=output_dir,
        provider=provider or None,
        flow=flow,
        mode=str(body.get("mode") or "").strip() or None,
        voice=str(body.get("voice") or "").strip() or None,
        language=str(body.get("language") or "").strip() or None,
        model=str(body.get("model") or "").strip() or None,
        response_format=str(body.get("response_format") or "wav").strip() or "wav",
        source="voice_smoke_test",
        source_task_id="voice_smoke_test",
        metadata={
            "fallback_allowed": not bool(provider),
            "smoke_test": True,
        },
    )
    try:
        result = synthesize_speech(request, cfg)
    except Exception as exc:
        return {"ok": False, "error": sanitize_error_text(str(exc), cfg)}

    payload = {
        "ok": True,
        "provider": result.provider,
        "audio_path": str(result.path),
        "mime_type": result.mime_type,
        "duration_sec": result.duration_sec,
    }
    if result.metadata_path is not None:
        payload["metadata_path"] = str(result.metadata_path)
    return payload


def sanitize_error_text(text: str, cfg: Mapping[str, Any] | None = None) -> str:
    sanitized = str(text or "")
    for value in _sensitive_values(cfg or {}):
        sanitized = sanitized.replace(value, "***")
    sanitized = re.sub(r"://([^/@\s:]+):([^/@\s]+)@", "://***@", sanitized)
    sanitized = re.sub(r"([?&][^=\s&]*(?:key|token|secret|password)[^=\s&]*=)[^&\s]+", r"\1***", sanitized, flags=re.I)
    return sanitized


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _selected_provider_payload(cfg, registry, capability: str | None, flow: str | None) -> dict[str, Any] | None:
    if not capability or not flow:
        return None
    try:
        selection = resolve_provider(
            ProviderSelectionRequest(capability=capability, flow=flow),
            cfg,
            registry,
        )
    except ProviderSelectionError as exc:
        return {"error": sanitize_error_text(str(exc), cfg)}
    return {
        "provider_id": selection.provider_id,
        "capability": selection.capability,
        "flow": selection.flow,
        "mode": selection.mode,
        "fallback_chain": selection.fallback_chain,
        "reason": selection.reason,
    }


def _provider_info_payload(provider, cfg: Mapping[str, Any], *, selected: bool) -> dict[str, Any]:
    info = provider.info()
    try:
        configured = bool(provider.is_configured(cfg))
    except Exception:
        configured = False
    return {
        "id": info.id,
        "label": info.label,
        "capabilities": list(info.capabilities),
        "configured": configured,
        "modes": list(info.modes),
        "fields": list(info.fields),
        "safety": _provider_safety_payload(info.safety, cfg),
        "config_reason": info.config_reason or _config_reason(info.id, configured),
        "sort_order": info.sort_order,
        "selected": selected,
    }


def _provider_safety_payload(safety: Mapping[str, Any], cfg: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(safety or {})
    payload.setdefault("disclosure_required", coerce_bool(cfg.get("voice_require_disclosure", True)))
    payload.setdefault("reference_clone_allowed", coerce_bool(cfg.get("voice_allow_reference_clone", False)))
    payload.setdefault(
        "prompt_transcript_clone_allowed",
        coerce_bool(cfg.get("voice_allow_prompt_transcript_clone", False)),
    )
    return payload


def _config_reason(provider_id: str, configured: bool) -> str:
    normalized = normalize_provider_id(provider_id)
    if normalized == "silent":
        return "always_available"
    if normalized == "edge_tts":
        return "edge_tts_command_found" if configured else "edge_tts_command_missing"
    if normalized == "local_http_tts":
        return "local_tts_url_configured" if configured else "local_tts_url_missing"
    return "configured" if configured else "not_configured"


def _command_status(candidates: tuple[str, ...]) -> dict[str, Any]:
    path = _first_command_path(candidates)
    return {"available": bool(path), "path": path or ""}


def _first_command_path(candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return ""


def _docker_status(command_status: Mapping[str, Any], timeout_seconds: int) -> dict[str, Any]:
    path = str(command_status.get("path") or "")
    if not path:
        return {"cli_available": False, "daemon_available": False, "status": "docker_cli_missing"}
    try:
        completed = subprocess.run(
            [path, "info", "--format", "{{json .ServerErrors}}"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return {
            "cli_available": True,
            "daemon_available": False,
            "status": "docker_daemon_unreachable",
            "error": sanitize_error_text(str(exc)),
        }
    return {
        "cli_available": True,
        "daemon_available": completed.returncode == 0,
        "status": "ok" if completed.returncode == 0 else "docker_daemon_unreachable",
        "error": sanitize_error_text((completed.stderr or completed.stdout or "").strip()),
    }


def _optional_package_status() -> dict[str, dict[str, Any]]:
    return {
        name: {"available": importlib.util.find_spec(module_name) is not None, "module": module_name}
        for name, module_name in _OPTIONAL_PACKAGES.items()
    }


def _torch_status() -> dict[str, Any]:
    if importlib.util.find_spec("torch") is None:
        return {"available": False, "cuda_available": False}
    try:
        torch = importlib.import_module("torch")
    except Exception as exc:
        return {"available": True, "cuda_available": False, "error": sanitize_error_text(str(exc))}
    cuda_available = bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())
    return {
        "available": True,
        "version": str(getattr(torch, "__version__", "")),
        "cuda_available": cuda_available,
    }


def _cuda_status() -> dict[str, Any]:
    nvidia_path = _first_command_path(_COMMANDS["nvidia_smi"])
    return {"nvidia_smi_available": bool(nvidia_path), "nvidia_smi_path": nvidia_path}


def _disk_status(path: Path) -> dict[str, Any]:
    target = _nearest_existing_path(path)
    total, used, free = shutil.disk_usage(target)
    return {
        "path": str(path),
        "checked_path": str(target),
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
    }


def _nearest_existing_path(path: Path) -> Path:
    current = Path(path).expanduser()
    for candidate in (current, *current.parents):
        if candidate.exists():
            return candidate
    return Path.cwd()


def _remote_base_url_status(
    cfg: Mapping[str, Any],
    include_remote: bool,
    timeout_seconds: int,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for provider_id, url_key, secret_key in _REMOTE_URL_FIELDS:
        raw_url = _remote_url_for_provider(provider_id, url_key, cfg)
        if not raw_url:
            result[provider_id] = {
                "configured": False,
                "has_api_key": bool(secret_key and cfg.get(secret_key)),
                "url": "",
                "status": "not_configured",
            }
            continue
        status = {
            "configured": True,
            "has_api_key": bool(secret_key and cfg.get(secret_key)),
            "url": _sanitize_url(raw_url),
            "status": "not_checked",
        }
        if include_remote:
            status.update(_probe_remote_url(raw_url, timeout_seconds))
        result[provider_id] = {key: sanitize_error_text(value, cfg) if isinstance(value, str) else value for key, value in status.items()}
    return result


def _remote_url_for_provider(provider_id: str, url_key: str, cfg: Mapping[str, Any]) -> str:
    value = str(cfg.get(url_key) or "").strip()
    if value:
        return value
    if provider_id == "azure_speech":
        region = str(cfg.get("azure_speech_region") or "").strip()
        if region:
            return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    return ""


def _probe_remote_url(raw_url: str, timeout_seconds: int) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"status": "invalid_url", "error": "remote provider URL must be http/https"}
    if _is_private_or_unsafe_probe_host(parsed.hostname):
        return {"status": "blocked", "error": "remote provider URL host is not allowed"}
    request = urllib.request.Request(raw_url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return {"status": "reachable", "status_code": response.status}
    except urllib.error.HTTPError as exc:
        if exc.code in {200, 204, 301, 302, 401, 403, 404, 405}:
            return {"status": "reachable", "status_code": exc.code}
        return {"status": "http_error", "status_code": exc.code, "error": sanitize_error_text(str(exc))}
    except Exception as exc:
        return {"status": "unreachable", "error": sanitize_error_text(str(exc))}


def _sanitize_url(raw_url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(raw_url)
        if not parsed.scheme or not parsed.netloc:
            return sanitize_error_text(raw_url)
        host = parsed.hostname or ""
        netloc = f"***@{host}" if parsed.username or parsed.password else host
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    except Exception:
        return sanitize_error_text(raw_url)


def _is_private_or_unsafe_probe_host(hostname: str) -> bool:
    normalized = hostname.strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    addresses = _resolve_probe_host_addresses(normalized)
    return any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    )


def _resolve_probe_host_addresses(hostname: str) -> list[Any]:
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    addresses: list[Any] = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return addresses


def _sensitive_values(cfg: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in cfg.items():
        if _SENSITIVE_KEY_RE.search(str(key)) and isinstance(value, str) and value:
            values.append(value)
    return sorted(values, key=len, reverse=True)


def _coerce_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 3
    return max(1, min(timeout, 30))

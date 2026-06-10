"""Path-safe voice output storage helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_SENSITIVE_KEY_PARTS = (
    "apikey",
    "authorization",
    "password",
    "secret",
    "subscriptionkey",
    "token",
)
_REQUIRED_METADATA_FIELDS = ("provider", "capability", "source", "source_task_id", "input_text_hash")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{idx}" for idx in range(1, 10)),
    *(f"LPT{idx}" for idx in range(1, 10)),
}


def resolve_voice_output_root(cfg: Mapping[str, Any] | None = None) -> Path:
    cfg = cfg or {}
    root = Path(str(cfg.get("voice_output_dir") or "data/voice")).expanduser()
    return root.resolve()


def safe_output_path(root: str | Path, relative_or_name: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    requested = Path(relative_or_name).expanduser()
    if requested.is_absolute():
        candidate = requested.resolve()
    else:
        candidate = (root_path / requested).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"voice output path is outside voice output root: {candidate}") from exc
    return candidate


def create_voice_task_dir(root: str | Path, task_id: str) -> Path:
    task_name = _safe_component(task_id, fallback="voice_task")
    task_dir = safe_output_path(root, task_name)
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def write_metadata(output_dir: str | Path, metadata: Mapping[str, Any]) -> Path:
    output_path = safe_output_path(output_dir, "metadata.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sanitize_metadata(dict(metadata))
    missing = [field for field in _REQUIRED_METADATA_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"missing required voice metadata fields: {', '.join(missing)}")
    payload.setdefault("ai_generated", True)
    payload.setdefault("disclosure_required", True)
    payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def write_audio_bytes(output_dir: str | Path, output_name: str, data: bytes, response_format: str) -> Path:
    output_path = voice_audio_output_path(output_dir, output_name, response_format)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return output_path


def voice_audio_output_path(output_dir: str | Path, output_name: str | Path, response_format: str) -> Path:
    suffix = _audio_suffix(response_format)
    name = _safe_output_name(str(output_name), fallback="output")
    if not name.lower().endswith(suffix):
        name = f"{Path(name).stem}{suffix}"
    return safe_output_path(output_dir, name)


def write_silent_wav(
    output_dir: str | Path,
    output_name: str = "output",
    duration_sec: float = 1.0,
    sample_rate: int = 16000,
) -> Path:
    name = _safe_output_name(output_name, fallback="output")
    if not name.lower().endswith(".wav"):
        name = f"{Path(name).stem}.wav"
    output_path = safe_output_path(output_dir, name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.05, float(duration_sec or 1.0))
    frames = int(math.ceil(duration * sample_rate))
    silence = struct.pack("<h", 0) * frames
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silence)
    return output_path


def hash_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _safe_component(value: str, fallback: str) -> str:
    safe = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("._")
    safe = safe[:120] or fallback
    stem = Path(safe).stem.upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        suffix = Path(safe).suffix
        safe = f"{Path(safe).stem}_{suffix}"
    return safe


def _safe_output_name(value: str, fallback: str) -> str:
    raw = str(value or "").strip()
    if Path(raw).is_absolute() or "/" in raw or "\\" in raw:
        raise ValueError(f"voice output path is outside voice output root: {raw}")
    return _safe_component(raw, fallback=fallback)


def _audio_suffix(response_format: str) -> str:
    value = str(response_format or "wav").strip().lower().lstrip(".")
    if value in {"mpeg", "mp3"}:
        return ".mp3"
    if value in {"wave", "wav"}:
        return ".wav"
    if value in {"aac", "flac", "opus", "pcm"}:
        return f".{value}"
    return ".wav"


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = re.sub(r"[^a-z0-9]+", "", key_text.lower())
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                continue
            sanitized[key_text] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value

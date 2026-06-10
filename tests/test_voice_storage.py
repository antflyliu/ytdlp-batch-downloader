from __future__ import annotations

import json

import pytest

from monitor.voice.storage import (
    create_voice_task_dir,
    hash_file,
    hash_text,
    resolve_voice_output_root,
    safe_output_path,
    write_audio_bytes,
    write_metadata,
    voice_audio_output_path,
    write_silent_wav,
)


def test_resolve_voice_output_root_defaults_to_data_voice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    root = resolve_voice_output_root({})

    assert root == (tmp_path / "data" / "voice").resolve()


def test_resolve_voice_output_root_uses_configured_path(tmp_path):
    configured = tmp_path / "configured-voice"

    root = resolve_voice_output_root({"voice_output_dir": str(configured)})

    assert root == configured.resolve()


def test_safe_output_path_accepts_relative_child(tmp_path):
    root = tmp_path / "voice"

    resolved = safe_output_path(root, "voice_001/output.wav")

    assert resolved == (root / "voice_001" / "output.wav").resolve()


def test_safe_output_path_rejects_path_traversal(tmp_path):
    root = tmp_path / "voice"

    with pytest.raises(ValueError, match="outside voice output root"):
        safe_output_path(root, "../outside.wav")


def test_safe_output_path_rejects_absolute_path_outside_root(tmp_path):
    root = tmp_path / "voice"
    outside = tmp_path / "outside.wav"

    with pytest.raises(ValueError, match="outside voice output root"):
        safe_output_path(root, outside)


def test_create_voice_task_dir_sanitizes_task_id(tmp_path):
    output_dir = create_voice_task_dir(tmp_path, "voice/2026 bad")

    assert output_dir == (tmp_path / "voice_2026_bad").resolve()
    assert output_dir.is_dir()


def test_write_metadata_removes_sensitive_keys(tmp_path):
    metadata_path = write_metadata(
        tmp_path,
        {
            "provider": "openai_speech",
            "capability": "speech_synthesis",
            "source": "manual_voice",
            "source_task_id": "voice_1",
            "input_text_hash": hash_text("hello"),
            "openai_speech_api_key": "secret",
            "nested": {"token": "also-secret", "voice": "alloy"},
        },
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert payload["provider"] == "openai_speech"
    assert "openai_speech_api_key" not in payload
    assert "token" not in payload["nested"]
    assert payload["nested"]["voice"] == "alloy"
    assert payload["created_at"]


def test_write_metadata_removes_hyphenated_and_header_secret_keys(tmp_path):
    metadata_path = write_metadata(
        tmp_path,
        {
            "provider": "azure_speech",
            "capability": "speech_synthesis",
            "source": "manual_voice",
            "source_task_id": "voice_1",
            "input_text_hash": hash_text("hello"),
            "api-key": "secret",
            "headers": {
                "X-API-Key": "secret",
                "Ocp-Apim-Subscription-Key": "secret",
                "safe_header": "kept",
            },
        },
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert "api-key" not in payload
    assert "X-API-Key" not in payload["headers"]
    assert "Ocp-Apim-Subscription-Key" not in payload["headers"]
    assert payload["headers"]["safe_header"] == "kept"


def test_write_metadata_requires_traceability_fields(tmp_path):
    with pytest.raises(ValueError, match="missing required voice metadata fields"):
        write_metadata(tmp_path, {"provider": "edge_tts"})


def test_write_metadata_defaults_disclosure_fields(tmp_path):
    metadata_path = write_metadata(
        tmp_path,
        {
            "provider": "edge_tts",
            "capability": "speech_synthesis",
            "source": "manual_voice",
            "source_task_id": "voice_1",
            "input_text_hash": hash_text("hello"),
        },
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert payload["ai_generated"] is True
    assert payload["disclosure_required"] is True


def test_write_audio_bytes_uses_response_format_suffix(tmp_path):
    path = write_audio_bytes(tmp_path, "output", b"audio", "mp3")

    assert path == tmp_path / "output.mp3"
    assert path.read_bytes() == b"audio"


def test_voice_audio_output_path_rejects_absolute_path(tmp_path):
    with pytest.raises(ValueError, match="outside voice output root"):
        voice_audio_output_path(tmp_path, tmp_path.parent / "outside", "wav")


def test_write_audio_bytes_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="outside voice output root"):
        write_audio_bytes(tmp_path, "../output", b"audio", "wav")


def test_write_silent_wav_creates_riff_file(tmp_path):
    path = write_silent_wav(tmp_path, "silent", duration_sec=0.1)

    assert path.read_bytes()[:4] == b"RIFF"
    assert path.suffix == ".wav"


def test_write_silent_wav_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="outside voice output root"):
        write_silent_wav(tmp_path, "../silent", duration_sec=0.1)


def test_windows_reserved_device_names_are_sanitized(tmp_path):
    path = write_audio_bytes(tmp_path, "CON", b"audio", "wav")

    assert path.name == "CON_.wav"


def test_hash_helpers_are_stable(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("hello", encoding="utf-8")

    assert hash_text("hello") == "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert hash_file(path) == "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

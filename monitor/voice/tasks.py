"""Voice task service for manual synthesis and future transcription tasks."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Mapping

import monitor.db as db

from .capabilities import SPEECH_SYNTHESIS, normalize_provider_id
from .env import sanitize_error_text
from .schemas import SpeechSynthesisRequest
from .storage import create_voice_task_dir, hash_text, resolve_voice_output_root, safe_output_path
from .synthesis import synthesize_speech


class VoiceTaskManager:
    def create_synthesis_task(self, body: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
        body = dict(body or {})
        text = str(body.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        provider = normalize_provider_id(body.get("provider")) or normalize_provider_id(cfg.get("voice_provider")) or "silent"
        source = str(body.get("source") or "manual_voice").strip() or "manual_voice"
        task_id = db.create_voice_task(
            kind="synthesis",
            provider=provider,
            capability=SPEECH_SYNTHESIS,
            mode=str(body.get("mode") or "").strip() or None,
            source=source,
            source_task_id=str(body.get("source_task_id") or "").strip() or None,
            input_text_hash=hash_text(text),
            options=_public_synthesis_options(body),
        )
        output_dir = create_voice_task_dir(resolve_voice_output_root(cfg), task_id)
        input_path = safe_output_path(output_dir, "input.json")
        input_payload = _private_synthesis_options(body)
        input_path.write_text(json.dumps(input_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        db.update_voice_task(task_id, input_path=str(input_path), message="已创建语音任务")
        return task_id

    def start_background(self, task_id: str, cfg: Mapping[str, Any]) -> None:
        threading.Thread(
            target=self.run_task,
            args=(task_id, dict(cfg or {})),
            name=f"voice-task-{task_id}",
            daemon=True,
        ).start()

    def run_task(self, task_id: str, cfg: Mapping[str, Any]) -> dict | None:
        task = db.get_voice_task(task_id)
        if not task:
            return None
        if task.get("cancel_requested"):
            db.update_voice_task(task_id, status="cancelled", progress=0, finished_at=db.now_iso())
            return db.get_voice_task(task_id)
        try:
            db.update_voice_task(task_id, status="running", progress=10, stage="synthesis", message="正在生成语音")
            output_dir = create_voice_task_dir(resolve_voice_output_root(cfg), task_id)
            options = _load_task_options(task, output_dir)
            request = SpeechSynthesisRequest(
                text=str(options.get("text") or ""),
                output_dir=output_dir,
                output_name=str(options.get("output_name") or "narration"),
                provider=task.get("provider"),
                flow=str(options.get("flow") or task.get("source") or "manual_voice"),
                mode=task.get("mode") or options.get("mode"),
                voice=options.get("voice"),
                language=options.get("language"),
                model=options.get("model"),
                response_format=str(options.get("response_format") or "wav"),
                speed=options.get("speed"),
                pitch=options.get("pitch"),
                volume=options.get("volume"),
                style=options.get("style"),
                control_instruction=options.get("control_instruction"),
                reference_audio_path=options.get("reference_audio_path"),
                prompt_text=options.get("prompt_text"),
                normalize_text=options.get("normalize_text"),
                denoise_reference=options.get("denoise_reference"),
                streaming=bool(options.get("streaming", False)),
                source=str(task.get("source") or "manual_voice"),
                source_task_id=str(task.get("source_task_id") or task_id),
                metadata={"fallback_allowed": bool(options.get("fallback_allowed", True))},
            )
            if not request.text:
                raise ValueError("text is required")
            result = synthesize_speech(request, cfg)
            db.update_voice_task(
                task_id,
                provider=result.provider,
                status="done",
                progress=100,
                stage="done",
                message="语音生成完成",
                output_audio_path=str(result.path),
                metadata_path=str(result.metadata_path) if result.metadata_path else None,
                result={
                    "provider": result.provider,
                    "mime_type": result.mime_type,
                    "duration_sec": result.duration_sec,
                    "sample_rate": result.sample_rate,
                },
                finished_at=db.now_iso(),
            )
        except Exception as exc:
            db.update_voice_task(
                task_id,
                status="error",
                progress=100,
                stage="error",
                message="语音生成失败",
                error=sanitize_error_text(str(exc), cfg),
                finished_at=db.now_iso(),
            )
        return db.get_voice_task(task_id)


def _public_synthesis_options(body: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "flow",
        "mode",
        "voice",
        "language",
        "model",
        "response_format",
        "speed",
        "pitch",
        "volume",
        "style",
        "output_name",
        "fallback_allowed",
    }
    return {key: body.get(key) for key in allowed if key in body}


def _private_synthesis_options(body: Mapping[str, Any]) -> dict[str, Any]:
    allowed = set(_public_synthesis_options(body)) | {
        "text",
        "control_instruction",
        "reference_audio_path",
        "prompt_text",
        "normalize_text",
        "denoise_reference",
        "streaming",
    }
    return {key: body.get(key) for key in allowed if key in body}


def _load_task_options(task: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    input_path = str(task.get("input_path") or "").strip()
    if input_path:
        path = safe_output_path(output_dir, input_path)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("voice task input.json is invalid") from exc
    return dict(task.get("options") or {})

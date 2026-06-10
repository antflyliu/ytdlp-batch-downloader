"""Pixelle-style short video generation pipeline.

P0 keeps the dependency surface small while still using real provider
boundaries: ComfyUI is tried first when configured, RunningHub is used only as
an explicit fallback, TTS goes through the configured provider, and the offline
placeholder path remains available for local contract tests with no services.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

import monitor.db as db
from monitor.voice.schemas import SpeechSynthesisRequest
from monitor.voice.synthesis import synthesize_speech
from scripts.llm_client import PROMPT_INPUT_PLACEHOLDER, create_llm_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "templates" / "pixelle-templates"
DEFAULT_COMFY_TIMEOUT_SEC = 600
DEFAULT_RUNNINGHUB_TIMEOUT_SEC = 900


class VideoGenerationCancelled(Exception):
    """Raised when cooperative cancellation is requested."""


def _safe_name(value: str | None, fallback: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value or "").strip("._")
    return text[:80] or fallback


def _json_file(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _generated_file_url(path: str | Path) -> str:
    return f"/api/video-generate/file?path={quote(str(Path(path).resolve()), safe='')}"


def _headers(api_key: str | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def normalize_template_key(template_key: str | None) -> str:
    key = (template_key or "1080x1920/image_default.html").replace("\\", "/").strip("/")
    if not key or key.startswith("../") or "/../" in key:
        raise ValueError("无效的视频模板路径")
    template_path = (TEMPLATE_ROOT / key).resolve()
    template_path.relative_to(TEMPLATE_ROOT.resolve())  # raises if outside TEMPLATE_ROOT
    if not template_path.is_file():
        raise FileNotFoundError(f"视频模板不存在: {key}")
    return key


def list_pixelle_templates() -> list[dict[str, str]]:
    if not TEMPLATE_ROOT.exists():
        return []
    templates = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        rel = path.relative_to(TEMPLATE_ROOT).as_posix()
        templates.append({"name": rel, "value": rel, "label": rel, "path": rel})
    return templates


def _fallback_storyboard(topic: str, script_text: str | None, scene_count: int) -> list[dict[str, str]]:
    if script_text:
        chunks = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", script_text) if part.strip()]
    else:
        chunks = []
    if not chunks:
        chunks = [f"{topic} - 场景 {idx + 1}" for idx in range(max(1, scene_count))]
    scenes = []
    for idx in range(max(1, scene_count)):
        narration = chunks[idx % len(chunks)]
        scenes.append(
            {
                "scene": str(idx + 1),
                "narration": narration,
                "image_prompt": f"editorial illustration, {topic}, scene {idx + 1}",
            }
        )
    return scenes


def _llm_storyboard(cfg: dict[str, Any], topic: str, script_text: str | None, scene_count: int) -> list[dict[str, str]]:
    has_llm_surface = bool(cfg.get("llm_base_url") or cfg.get("llm_api_key") or os.environ.get("LLM_API_KEY"))
    if not has_llm_surface:
        return _fallback_storyboard(topic, script_text, scene_count)
    try:
        client = create_llm_client(
            provider=cfg.get("llm_provider") or "qwen",
            model=cfg.get("llm_model"),
            api_key=cfg.get("llm_api_key"),
            base_url=cfg.get("llm_base_url"),
        )
        payload = {"topic": topic, "script": script_text or "", "scene_count": scene_count}
        prompt = (
            "请输出 JSON 数组，每项包含 scene, narration, image_prompt。"
            "不要输出额外说明。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )
        response = client.call_with_retry(prompt, payload, max_retries=2, temperature=0.4, timeout=180)
        if response:
            parsed = client.parse_json_response(response)
            if isinstance(parsed, list) and parsed:
                return [
                    {
                        "scene": str(item.get("scene") or idx + 1),
                        "narration": str(item.get("narration") or item.get("text") or ""),
                        "image_prompt": str(item.get("image_prompt") or item.get("prompt") or topic),
                    }
                    for idx, item in enumerate(parsed)
                ][: max(1, scene_count)]
    except Exception:
        pass
    return _fallback_storyboard(topic, script_text, scene_count)


def _write_ppm(path: Path, index: int, total: int) -> str:
    width, height = 360, 640
    hue = (index * 47) % 255
    with path.open("w", encoding="ascii") as f:
        f.write(f"P3\n{width} {height}\n255\n")
        for y in range(height):
            row = []
            for x in range(width):
                shade = int(40 + 80 * (x / width) + 80 * (y / height))
                r = (shade + hue) % 255
                g = (shade + 90 + hue // 2) % 255
                b = (210 - shade + hue) % 255
                row.append(f"{r} {g} {b}")
            f.write(" ".join(row) + "\n")
    return str(path)


def _write_silence_wav(path: Path, duration_sec: float) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 16000
    frame_count = max(1, int(duration_sec * sample_rate))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count)
    return str(path)


def _resolve_workflow_ref(workflow_ref: str | None) -> Any | None:
    if not workflow_ref:
        return None
    raw = workflow_ref.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    # Restrict to workflows under PROJECT_ROOT to prevent arbitrary file read
    candidates = [PROJECT_ROOT / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            continue
        if resolved.is_file():
            return json.loads(resolved.read_text(encoding="utf-8"))
    return None


def _inject_comfy_prompt(workflow: Any, prompt_text: str, output_prefix: str) -> Any:
    payload = copy.deepcopy(workflow)
    nodes = payload.values() if isinstance(payload, dict) else []
    text_injected = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get("class_type") or "").lower()
        meta_title = str(node.get("_meta", {}).get("title") or "").lower()
        if "text" in inputs and "negative" not in class_type and "negative" not in meta_title:
            inputs["text"] = prompt_text
            text_injected = True
        if "filename_prefix" in inputs:
            inputs["filename_prefix"] = output_prefix
        if "seed" in inputs and isinstance(inputs.get("seed"), int):
            inputs["seed"] = int(time.time() * 1000) % 2_147_483_647
    if not text_injected:
        raise ValueError("ComfyUI workflow 中未找到可注入 prompt 的 text 输入")
    return payload


def _extract_comfy_image_refs(history_payload: dict[str, Any], prompt_id: str) -> list[dict[str, Any]]:
    history = history_payload.get(prompt_id, history_payload)
    if isinstance(history, dict) and prompt_id in history and isinstance(history[prompt_id], dict):
        history = history[prompt_id]
    outputs = history.get("outputs", {}) if isinstance(history, dict) else {}
    refs: list[dict[str, Any]] = []
    for output in outputs.values() if isinstance(outputs, dict) else []:
        if not isinstance(output, dict):
            continue
        for item in output.get("images", []) or []:
            if isinstance(item, dict):
                refs.append(item)
    return refs


def _save_bytes(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def _download_url(url: str, path: Path, headers: dict[str, str] | None = None, timeout: int = 180) -> str:
    response = requests.get(url, headers=headers or {}, timeout=timeout)
    response.raise_for_status()
    return _save_bytes(path, response.content)


def _materialize_file_reference(ref: Any, path: Path, headers: dict[str, str] | None = None) -> str | None:
    if not ref:
        return None
    if isinstance(ref, bytes):
        return _save_bytes(path, ref)
    if isinstance(ref, str):
        value = ref.strip()
        if value.startswith("data:") and "," in value:
            return _save_bytes(path, base64.b64decode(value.split(",", 1)[1]))
        if value.startswith("http://") or value.startswith("https://"):
            return _download_url(value, path, headers=headers)
        candidate = Path(value)
        if candidate.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, path)
            return str(path)
    if isinstance(ref, dict):
        for key in ("audio_base64", "image_base64", "base64", "data"):
            if isinstance(ref.get(key), str):
                value = ref[key]
                if "," in value and value.startswith("data:"):
                    value = value.split(",", 1)[1]
                return _save_bytes(path, base64.b64decode(value))
        nested = _first_file_reference(ref)
        if nested and nested is not ref:
            return _materialize_file_reference(nested, path, headers=headers)
    return None


def _first_file_reference(payload: Any) -> Any | None:
    if isinstance(payload, str):
        value = payload.strip()
        if (
            value.startswith(("http://", "https://", "data:"))
            or re.search(r"\.(png|jpg|jpeg|webp|wav|mp3|m4a)(\?|$)", value, re.I)
            or Path(value).is_file()
        ):
            return value
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _first_file_reference(item)
            if found:
                return found
    if isinstance(payload, dict):
        for key in (
            "fileUrl",
            "file_url",
            "imageUrl",
            "image_url",
            "audioUrl",
            "audio_url",
            "url",
            "path",
            "filePath",
            "file_path",
            "output",
            "outputs",
            "data",
        ):
            if key in payload:
                found = _first_file_reference(payload[key])
                if found:
                    return found
        for value in payload.values():
            found = _first_file_reference(value)
            if found:
                return found
    return None


def _response_json(response: requests.Response) -> Any:
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"服务返回非 JSON 响应: {response.text[:200]}") from exc


class VideoGenerationPipeline:
    def __init__(self, task_id: str, cfg: dict[str, Any] | None = None):
        self.task_id = task_id
        self.cfg = cfg or db.load_config()
        self.stages: dict[str, dict[str, Any]] = {}

    def _stage(self, key: str, status: str, message: str = "") -> None:
        self.stages[key] = {"status": status, "message": message}
        db.update_video_gen_task(self.task_id, current_stage=key, stages=self.stages)

    def _check_cancelled(self) -> None:
        task = db.get_video_gen_task(self.task_id)
        if task and task.get("cancel_requested"):
            raise VideoGenerationCancelled("视频生成任务已取消")

    def run(self) -> dict[str, Any]:
        task = db.get_video_gen_task(self.task_id)
        if not task:
            raise ValueError(f"video generation task not found: {self.task_id}")
        if task.get("cancel_requested"):
            db.update_video_gen_task(self.task_id, status="cancelled", finished_at=db.now_iso())
            return db.get_video_gen_task(self.task_id) or {}

        output_root = Path(self.cfg.get("video_gen_output_dir") or "output/video-gen")
        output_dir = output_root / self.task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        template_key = normalize_template_key(task.get("template_key") or self.cfg.get("video_gen_default_template"))
        topic = task.get("topic") or "AI generated story"
        scene_count = int(task.get("scene_count") or self.cfg.get("video_gen_default_scene_count") or 5)
        db.update_video_gen_task(
            self.task_id,
            status="running",
            template_key=template_key,
            output_dir=str(output_dir),
        )

        try:
            self._stage("storyboard", "running", "正在生成分镜")
            storyboard = _llm_storyboard(self.cfg, topic, task.get("script_text"), scene_count)
            storyboard = self._apply_prompt_prefix(storyboard, task)
            storyboard_path = _json_file(output_dir / "storyboard.json", storyboard)
            db.update_video_gen_task(self.task_id, storyboard_path=storyboard_path)
            self._stage("storyboard", "done", "分镜已生成")

            self._check_cancelled()
            self._stage("images", "running", "正在生成画面资产")
            image_paths, image_provider = self._generate_scene_images(storyboard, output_dir, task)
            self._stage("images", "done", f"画面资产已生成（{image_provider}）")

            self._check_cancelled()
            self._stage("tts", "running", "正在生成旁白音频")
            audio_path, audio_provider, audio_duration = self._synthesize_narration(storyboard, output_dir, task)
            self._stage("tts", "done", f"旁白音频已生成（{audio_provider}）")

            self._check_cancelled()
            self._stage("render", "running", "正在使用 FFmpeg 合成视频")
            duration_per_scene = max(1.0, audio_duration / max(1, len(image_paths)))
            video_path = self._render_video(output_dir, image_paths, audio_path, duration_per_scene)
            file_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
            result = {
                "video_path": video_path,
                "video_url": _generated_file_url(video_path),
                "output_url": _generated_file_url(video_path),
                "storyboard_path": storyboard_path,
                "storyboard_url": _generated_file_url(storyboard_path),
                "assets": {
                    "images": image_paths,
                    "audio": audio_path,
                    "audio_url": _generated_file_url(audio_path),
                    "template": template_key,
                    "image_provider": image_provider,
                    "tts_provider": audio_provider,
                },
            }
            db.update_video_gen_task(
                self.task_id,
                status="done",
                current_stage="done",
                video_path=video_path,
                duration_sec=audio_duration,
                file_size=file_size,
                stages={**self.stages, "render": {"status": "done", "message": "视频已生成"}},
                result=result,
                finished_at=db.now_iso(),
            )
            return db.get_video_gen_task(self.task_id) or {}
        except VideoGenerationCancelled as exc:
            db.update_video_gen_task(
                self.task_id,
                status="cancelled",
                error=str(exc),
                cancel_requested=False,
                finished_at=db.now_iso(),
            )
            return db.get_video_gen_task(self.task_id) or {}
        except Exception as exc:
            db.update_video_gen_task(
                self.task_id,
                status="error",
                error=str(exc),
                finished_at=db.now_iso(),
            )
            return db.get_video_gen_task(self.task_id) or {}

    def _apply_prompt_prefix(self, storyboard: list[dict[str, str]], task: dict[str, Any]) -> list[dict[str, str]]:
        prefix = (task.get("prompt_prefix") or self.cfg.get("video_gen_prompt_prefix") or "").strip()
        if not prefix:
            return storyboard
        updated = []
        for scene in storyboard:
            next_scene = dict(scene)
            prompt = next_scene.get("image_prompt") or next_scene.get("narration") or ""
            next_scene["image_prompt"] = f"{prefix}, {prompt}" if prompt else prefix
            updated.append(next_scene)
        return updated

    def _generate_scene_images(
        self,
        storyboard: list[dict[str, str]],
        output_dir: Path,
        task: dict[str, Any],
    ) -> tuple[list[str], str]:
        comfy_url = str(self.cfg.get("comfyui_url") or "").rstrip("/")
        runninghub_url = str(self.cfg.get("runninghub_url") or "").rstrip("/")
        runninghub_api_key = str(self.cfg.get("runninghub_api_key") or "").strip()
        workflow_ref = (task.get("image_workflow") or "").strip()

        if comfy_url:
            try:
                return (
                    [
                        self._generate_comfyui_image(scene, output_dir, workflow_ref, idx)
                        for idx, scene in enumerate(storyboard)
                    ],
                    "comfyui",
                )
            except Exception as comfy_exc:
                if runninghub_url or runninghub_api_key:
                    return (
                        [
                            self._generate_runninghub_image(scene, output_dir, workflow_ref, idx)
                            for idx, scene in enumerate(storyboard)
                        ],
                        "runninghub",
                    )
                raise RuntimeError(f"ComfyUI 生成配图失败，且未配置 RunningHub 回退: {comfy_exc}") from comfy_exc

        if runninghub_url or runninghub_api_key:
            return (
                [
                    self._generate_runninghub_image(scene, output_dir, workflow_ref, idx)
                    for idx, scene in enumerate(storyboard)
                ],
                "runninghub",
            )

        return (
            [_write_ppm(output_dir / f"scene_{idx + 1:02d}.ppm", idx, len(storyboard)) for idx, _ in enumerate(storyboard)],
            "offline-placeholder",
        )

    def _generate_comfyui_image(
        self,
        scene: dict[str, str],
        output_dir: Path,
        workflow_ref: str,
        index: int,
    ) -> str:
        workflow = _resolve_workflow_ref(workflow_ref)
        if workflow is None:
            raise ValueError("已配置 ComfyUI，但缺少可读取的 image_workflow JSON")
        base_url = str(self.cfg.get("comfyui_url") or "").rstrip("/")
        client_id = str(uuid.uuid4())
        prompt_text = scene.get("image_prompt") or scene.get("narration") or f"scene {index + 1}"
        prompt_payload = _inject_comfy_prompt(workflow, prompt_text, f"{_safe_name(self.task_id, 'video_gen')}_{index + 1:02d}")
        queue_response = requests.post(
            f"{base_url}/prompt",
            headers=_headers(self.cfg.get("comfyui_api_key")),
            json={"prompt": prompt_payload, "client_id": client_id},
            timeout=60,
        )
        queue_payload = _response_json(queue_response)
        prompt_id = queue_payload.get("prompt_id") or queue_payload.get("data", {}).get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id: {queue_payload}")

        deadline = time.time() + int(self.cfg.get("comfyui_timeout_seconds") or DEFAULT_COMFY_TIMEOUT_SEC)
        while time.time() < deadline:
            self._check_cancelled()
            history_response = requests.get(
                f"{base_url}/history/{prompt_id}",
                headers=_headers(self.cfg.get("comfyui_api_key")),
                timeout=60,
            )
            history_payload = _response_json(history_response)
            refs = _extract_comfy_image_refs(history_payload, prompt_id)
            if refs:
                params = {
                    "filename": refs[0].get("filename"),
                    "subfolder": refs[0].get("subfolder", ""),
                    "type": refs[0].get("type", "output"),
                }
                view_response = requests.get(
                    f"{base_url}/view",
                    headers=_headers(self.cfg.get("comfyui_api_key")),
                    params=params,
                    timeout=180,
                )
                view_response.raise_for_status()
                return _save_bytes(output_dir / f"scene_{index + 1:02d}.png", view_response.content)
            time.sleep(2)
        raise TimeoutError("ComfyUI 配图任务超时")

    def _generate_runninghub_image(
        self,
        scene: dict[str, str],
        output_dir: Path,
        workflow_ref: str,
        index: int,
    ) -> str:
        api_key = str(self.cfg.get("runninghub_api_key") or "").strip()
        if not api_key:
            raise ValueError("RunningHub 回退需要配置 runninghub_api_key")
        webapp_id = workflow_ref.removeprefix("runninghub:").strip()
        if not webapp_id:
            raise ValueError("RunningHub 回退需要在 image_workflow 中提供 webappId")
        base_url = (str(self.cfg.get("runninghub_url") or "").rstrip("/") or "https://www.runninghub.ai")
        prompt_text = scene.get("image_prompt") or scene.get("narration") or f"scene {index + 1}"
        body = {
            "apiKey": api_key,
            "webappId": webapp_id,
            "nodeInfoList": [
                {
                    "nodeId": str(self.cfg.get("runninghub_prompt_node_id") or "prompt"),
                    "fieldName": str(self.cfg.get("runninghub_prompt_field") or "prompt"),
                    "fieldValue": prompt_text,
                    "description": "prompt",
                }
            ],
        }
        run_payload = _response_json(requests.post(f"{base_url}/task/openapi/ai-app/run", json=body, timeout=60))
        data = run_payload.get("data", run_payload) if isinstance(run_payload, dict) else {}
        task_id = data.get("taskId") or data.get("task_id") or data.get("id")
        if not task_id:
            direct_ref = _first_file_reference(run_payload)
            materialized = _materialize_file_reference(direct_ref, output_dir / f"scene_{index + 1:02d}.png")
            if materialized:
                return materialized
            raise RuntimeError(f"RunningHub 未返回 taskId: {run_payload}")

        deadline = time.time() + int(self.cfg.get("runninghub_timeout_seconds") or DEFAULT_RUNNINGHUB_TIMEOUT_SEC)
        status_body = {"apiKey": api_key, "taskId": task_id}
        while time.time() < deadline:
            self._check_cancelled()
            status_payload = _response_json(requests.post(f"{base_url}/task/openapi/status", json=status_body, timeout=60))
            status_data = status_payload.get("data", status_payload) if isinstance(status_payload, dict) else {}
            status = str(
                status_data.get("status")
                or status_data.get("taskStatus")
                or status_data.get("state")
                or ""
            ).lower()
            if status in {"failed", "fail", "error"}:
                raise RuntimeError(f"RunningHub 配图任务失败: {status_payload}")
            if status in {"success", "succeeded", "finished", "completed", "done"}:
                for endpoint in ("outputs", "output"):
                    try:
                        output_payload = _response_json(
                            requests.post(f"{base_url}/task/openapi/{endpoint}", json=status_body, timeout=60)
                        )
                    except Exception:
                        continue
                    ref = _first_file_reference(output_payload)
                    materialized = _materialize_file_reference(ref, output_dir / f"scene_{index + 1:02d}.png")
                    if materialized:
                        return materialized
                ref = _first_file_reference(status_payload)
                materialized = _materialize_file_reference(ref, output_dir / f"scene_{index + 1:02d}.png")
                if materialized:
                    return materialized
            time.sleep(3)
        raise TimeoutError("RunningHub 配图任务超时")

    def _synthesize_narration(
        self,
        storyboard: list[dict[str, str]],
        output_dir: Path,
        task: dict[str, Any],
    ) -> tuple[str, str, float]:
        text = "\n".join(scene.get("narration") or scene.get("image_prompt") or "" for scene in storyboard).strip()
        if not text:
            text = task.get("topic") or "AI generated video"
        requested_provider = str(task.get("tts_workflow") or "").strip() or None
        estimated_duration = max(4.0, min(180.0, len(text) / 4.5))
        result = synthesize_speech(
            SpeechSynthesisRequest(
                text=text,
                output_dir=output_dir,
                output_name="narration",
                provider=requested_provider,
                flow="video_generation",
                voice=str(self.cfg.get("tts_voice") or "") or None,
                source="video_generation",
                source_task_id=str(task.get("task_id") or self.task_id),
                metadata={"estimated_duration_sec": estimated_duration},
            ),
            self.cfg,
        )
        audio_path = str(result.path)
        duration = _probe_audio_duration(audio_path, result.duration_sec or estimated_duration)
        return audio_path, result.provider, duration

    def _synthesize_edge_tts(self, text: str, output_dir: Path) -> str:
        command_path = shutil.which("edge-tts") or shutil.which("edge-tts.exe")
        if not command_path:
            raise RuntimeError("未找到 edge-tts 命令，且未配置 local_tts_url 回退")
        output_path = output_dir / "narration.mp3"
        command = [command_path, "--text", text, "--write-media", str(output_path)]
        voice = str(self.cfg.get("tts_voice") or "").strip()
        if voice:
            command.extend(["--voice", voice])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "edge-tts 合成失败").strip())
        return str(output_path)

    def _synthesize_local_tts(self, text: str, output_dir: Path) -> str:
        raw_url = str(self.cfg.get("local_tts_url") or "").rstrip("/")
        if not raw_url:
            raise ValueError("local_tts_url 未配置")
        url = raw_url if re.search(r"/(tts|synthesize|audio)(/)?$", raw_url, re.I) else f"{raw_url}/tts"
        response = requests.post(
            url,
            json={"text": text, "voice": self.cfg.get("tts_voice") or "", "format": "wav"},
            timeout=300,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type:
            payload = response.json()
            ref = _first_file_reference(payload) or payload
            materialized = _materialize_file_reference(ref, output_dir / "narration.wav")
            if materialized:
                return materialized
            raise RuntimeError(f"本地 TTS 未返回可用音频: {payload}")
        suffix = ".mp3" if "mpeg" in content_type or "mp3" in content_type else ".wav"
        return _save_bytes(output_dir / f"narration{suffix}", response.content)

    def _render_video(self, output_dir: Path, image_paths: list[str], audio_path: str, duration_per_scene: float) -> str:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 FFmpeg，无法合成视频")
        if not image_paths:
            raise RuntimeError("缺少画面资产，无法合成视频")
        concat_path = output_dir / "frames.txt"
        lines: list[str] = []
        for image_path in image_paths:
            safe_path = Path(image_path).resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{safe_path}'")
            lines.append(f"duration {duration_per_scene}")
        lines.append(f"file '{Path(image_paths[-1]).resolve().as_posix()}'")
        concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        final_path = output_dir / "final.mp4"
        command = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            audio_path,
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(final_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "FFmpeg 合成失败").strip())
        return str(final_path)


def _probe_audio_duration(audio_path: str, fallback: float) -> float:
    path = Path(audio_path)
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                return max(1.0, wav.getnframes() / float(wav.getframerate()))
        except Exception:
            pass
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode == 0:
                return max(1.0, float(completed.stdout.strip()))
        except Exception:
            pass
    return fallback


def run_video_gen_task(task_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return VideoGenerationPipeline(task_id, cfg=cfg).run()

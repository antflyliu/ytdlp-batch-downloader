"""Article illustration generation — auto-insert AI-generated images into article body.

Triggered when article body exceeds MIN_CHARS_FOR_IMAGE (default 300).
Uses LLM to analyze the article and determine where/how to insert illustrations.
Supports multiple providers with fallback: minimax → openai → gemini.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger("article_image_generator")

# ── Config defaults ────────────────────────────────────────────────
MIN_CHARS_FOR_IMAGE = 300  # 正文少于该字数不生成配图
CHARS_PER_IMAGE = 1400  # 每 N 个字符一张配图
MAX_IMAGES = 4  # 最多生成配图数量
DEFAULT_IMAGE_SIZE = "3:4"  # 正文配图比例
DEFAULT_COVER_SIZE = "2.35:1"  # 封面比例（消息列表）
IMAGE_TIMEOUT_SECONDS = 300
VIDEO_FRAME_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"}


@dataclass
class ImagePlan:
    """One illustration plan — position (char offset) and prompt."""
    position: int  # character offset in body
    prompt: str
    caption: str  # alt text for the image

    def to_dict(self) -> dict:
        return {"position": self.position, "prompt": self.prompt, "caption": self.caption}


# ── LLM: analyze body → list of ImagePlan ──────────────────────────

def _analyze_illustration_plan(
    body: str,
    title: str,
    cfg: dict[str, Any],
) -> list[ImagePlan]:
    """Use LLM to analyze article body and return illustration insertion plans."""
    import scripts.llm_client as llm_client_mod

    n_images = _image_count_for_body(body, cfg)
    if n_images == 0:
        return []

    prompt = f"""你是一个专业的新媒体编辑。请分析以下文章，在适当位置插入{n_images}张配图。

文章标题：{title}

文章正文：
{body}

请返回一个JSON数组，每个元素描述一张配图：
[
  {{"position": 200, "prompt": "配图描述英文提示词", "caption": "图片说明"}},
  ...
]

position: 在正文中的字符偏移量（0=开头），必须分散在文章不同段落
prompt: 英文提示词，用于AI绘图工具生成图片。要求：
  - 16:9 或 3:4 比例
  - 风格与文章内容相符
  - 简洁、具体、避免歧义
  - 不含文字
caption: 中文图片说明（10字以内）

要求：
- 必须恰好{n_images}张图
- position必须递增分布，覆盖文章不同部分
- position范围：0 到 {len(body)}
- 仅返回JSON数组，不要任何解释"""

    try:
        client = llm_client_mod.create_llm_client(
            provider=cfg.get("llm_provider") or "qwen",
            model=cfg.get("llm_model") or "",
            api_key=cfg.get("llm_api_key"),
            base_url=cfg.get("llm_base_url"),
        )
        response = client.call_with_retry(prompt, max_retries=2, timeout=60)
    except Exception as exc:
        _log.warning("[配图] LLM分析失败: %s", exc)
        return []

    response_text = str(response or "").strip()
    if not response_text:
        _log.warning("[配图] LLM未返回配图计划，跳过自动配图")
        return []

    # Parse JSON response
    try:
        # Try to extract JSON from response
        json_match = re.search(r"\[\s*\{.*?\}\s*\]", response_text, re.DOTALL)
        if not json_match:
            _log.warning("[配图] LLM响应中未找到JSON数组，响应前100字符: %s", response_text[:100])
            return []
        plans_data = json.loads(json_match.group(0))
        if not isinstance(plans_data, list):
            _log.warning("[配图] LLM响应不是数组类型，实际类型: %s", type(plans_data).__name__)
            return []
        plans = []
        for item in plans_data:
            if not isinstance(item, dict):
                continue
            try:
                prompt_text = str(item.get("prompt", "")).strip()
                if not prompt_text:
                    continue
                plans.append(
                    ImagePlan(
                        position=int(item.get("position", 0)),
                        prompt=prompt_text,
                        caption=str(item.get("caption", "")).strip(),
                    )
                )
            except (ValueError, TypeError):
                continue
        _log.info("[配图] LLM分析得到 %d 张配图计划", len(plans))
        return plans
    except (json.JSONDecodeError, TypeError) as exc:
        _log.warning("[配图] JSON解析失败: %s", exc)
        return []


def _image_count_for_body(body: str, cfg: dict[str, Any]) -> int:
    try:
        chars_per_image = int(cfg.get("article_inline_image_chars_per_image") or CHARS_PER_IMAGE)
    except (TypeError, ValueError):
        chars_per_image = CHARS_PER_IMAGE
    try:
        max_images = int(cfg.get("article_inline_image_max_images") or MAX_IMAGES)
    except (TypeError, ValueError):
        max_images = MAX_IMAGES
    chars_per_image = max(chars_per_image, 800)
    max_images = min(max(max_images, 1), 6)
    return min(max_images, max(1, len(body.strip()) // chars_per_image))


def _heading_contexts(body: str, count: int) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"(?m)^#{2,4}\s+(.+)$", body or ""))
    if not matches:
        step = max(1, len(body) // (count + 1))
        return [(min(len(body), step * (idx + 1)), "文章关键观点") for idx in range(count)]
    if len(matches) <= count:
        selected = matches
    else:
        selected = []
        for idx in range(count):
            source_index = round(idx * (len(matches) - 1) / max(1, count - 1))
            selected.append(matches[source_index])
    return [(match.start(), match.group(1).strip()) for match in selected]


def _fallback_illustration_plan(body: str, title: str, cfg: dict[str, Any]) -> list[ImagePlan]:
    count = _image_count_for_body(body, cfg)
    plans = []
    for position, heading in _heading_contexts(body, count):
        prompt = (
            "Editorial illustration for a Chinese science and technology article, "
            "cinematic but clean, no text, no watermark, warm professional lighting. "
            f"Article topic: {title}. Section idea: {heading}."
        )
        caption = re.sub(r"[#*`_>\[\]()（）]", "", heading).strip()[:10] or "配图"
        plans.append(ImagePlan(position=position, prompt=prompt, caption=caption))
    _log.info("[配图] 使用规则兜底生成 %d 张配图计划", len(plans))
    return plans


def _snap_image_insert_position(body: str, position: int) -> int:
    """Move arbitrary LLM offsets to paragraph boundaries before insertion."""
    text = body or ""
    if not text:
        return 0
    pos = min(max(int(position or 0), 0), len(text))
    if pos in (0, len(text)):
        return pos
    if text[max(0, pos - 2) : pos] == "\n\n" or text[pos : pos + 2] == "\n\n":
        return pos

    candidates: list[tuple[int, int]] = []
    next_boundary = text.find("\n\n", pos)
    if next_boundary >= 0:
        candidates.append((abs(next_boundary - pos), next_boundary + 2))
    previous_boundary = text.rfind("\n\n", 0, pos)
    if previous_boundary >= 0:
        candidates.append((abs(pos - (previous_boundary + 2)), previous_boundary + 2))
    if candidates:
        distance, snapped = min(candidates, key=lambda item: item[0])
        if distance <= 500:
            return min(max(snapped, 0), len(text))

    next_line = text.find("\n", pos)
    if next_line >= 0:
        return next_line + 1
    return pos


def _insert_image_markdown(body: str, position: int, caption: str, image_path: str) -> str:
    pos = _snap_image_insert_position(body, position)
    image_md = f"![{caption}]({image_path})"
    prefix = body[:pos].rstrip()
    suffix = body[pos:].lstrip("\n")
    if prefix and suffix:
        return f"{prefix}\n\n{image_md}\n\n{suffix}"
    if prefix:
        return f"{prefix}\n\n{image_md}\n"
    if suffix:
        return f"{image_md}\n\n{suffix}"
    return image_md


# ── Video keyframes ────────────────────────────────────────────────

def _resolve_ffmpeg(cfg: dict[str, Any], executable: str) -> str | None:
    configured = str(cfg.get(f"{executable}_path") or "").strip()
    if configured:
        return configured
    return shutil.which(f"{executable}.exe") or shutil.which(executable)


def _probe_duration_seconds(video_path: Path, cfg: dict[str, Any]) -> float | None:
    ffprobe = _resolve_ffmpeg(cfg, "ffprobe")
    if not ffprobe:
        return None
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
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            return None
        return float((completed.stdout or "").strip())
    except Exception:
        return None


def _keyframe_timestamps(duration: float | None, count: int) -> list[float]:
    if not duration or duration <= 0:
        return [20.0 + idx * 45.0 for idx in range(count)]
    start = min(max(duration * 0.12, 8.0), max(1.0, duration * 0.25))
    end = max(start + 1.0, duration * 0.88)
    if count == 1:
        return [(start + end) / 2]
    return [start + ((end - start) * idx / (count - 1)) for idx in range(count)]


def _opencv_remove_corner_watermark(image_path: Path) -> Path | None:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    height, width = image.shape[:2]
    corner_w = max(48, int(width * 0.22))
    corner_h = max(32, int(height * 0.16))
    regions = [
        (0, 0, corner_w, corner_h),
        (width - corner_w, 0, corner_w, corner_h),
        (0, height - corner_h, corner_w, corner_h),
        (width - corner_w, height - corner_h, corner_w, corner_h),
    ]
    mask = np.zeros((height, width), dtype=np.uint8)
    detected = False
    for x, y, w, h in regions:
        crop = image[y : y + h, x : x + w]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        edge_density = float(np.count_nonzero(edges)) / float(max(1, w * h))
        bright_density = float(np.count_nonzero(gray > 210)) / float(max(1, w * h))
        if edge_density > 0.035 and bright_density > 0.015:
            detected = True
            mask[y : y + h, x : x + w] = 255
    if not detected:
        return image_path
    cleaned = cv2.inpaint(image, mask, 5, cv2.INPAINT_TELEA)
    cleaned_path = image_path.with_name(f"{image_path.stem}_clean{image_path.suffix}")
    cv2.imwrite(str(cleaned_path), cleaned)
    return cleaned_path


def _postprocess_keyframe_watermark(image_path: Path, cfg: dict[str, Any]) -> Path:
    if not bool(cfg.get("article_keyframe_watermark_removal_enabled", True)):
        return image_path
    cleaned = _opencv_remove_corner_watermark(image_path)
    if cleaned is None:
        _log.info("[配图/关键帧] 未安装 OpenCV，跳过去水印后处理: %s", image_path)
        return image_path
    if cleaned != image_path:
        _log.info("[配图/关键帧] 检测到疑似角标水印，已生成去水印版本: %s", cleaned)
    return cleaned


def _extract_video_keyframes(
    video_path: str | Path | None,
    output_dir: Path,
    body: str,
    cfg: dict[str, Any],
) -> list[tuple[int, str, str]]:
    if not video_path:
        return []
    source = Path(video_path)
    if not source.is_file() or source.suffix.lower() not in VIDEO_FRAME_EXTENSIONS:
        return []
    ffmpeg = _resolve_ffmpeg(cfg, "ffmpeg")
    if not ffmpeg:
        _log.warning("[配图/关键帧] 未找到 ffmpeg，无法从视频提取关键帧")
        return []
    count = _image_count_for_body(body, cfg)
    duration = _probe_duration_seconds(source, cfg)
    timestamps = _keyframe_timestamps(duration, count)
    contexts = _heading_contexts(body, count)
    frame_dir = output_dir / "images" / "keyframes"
    frame_dir.mkdir(parents=True, exist_ok=True)
    generated: list[tuple[int, str, str]] = []
    for idx, timestamp in enumerate(timestamps):
        frame_path = frame_dir / f"keyframe_{idx + 1:03d}.jpg"
        try:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{timestamp:.2f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if completed.returncode != 0 or not frame_path.is_file():
                _log.warning("[配图/关键帧] 第 %d 帧提取失败: %s", idx + 1, (completed.stderr or "")[:200])
                continue
            final_path = _postprocess_keyframe_watermark(frame_path, cfg)
            position, caption = contexts[min(idx, len(contexts) - 1)]
            rel_path = final_path.relative_to(output_dir).as_posix()
            generated.append((position, caption[:10] or "视频关键帧", rel_path))
        except Exception as exc:
            _log.warning("[配图/关键帧] 第 %d 帧提取异常: %s", idx + 1, exc)
    return generated


# ── Image generation providers ─────────────────────────────────────

def _append_api_endpoint(base_url: str, endpoint_path: str) -> str:
    base = str(base_url or "").rstrip("/")
    endpoint = "/" + endpoint_path.strip("/")
    if not base:
        return endpoint
    parsed = urllib.parse.urlparse(base)
    path = parsed.path.rstrip("/")
    if path.endswith(endpoint):
        return base
    if path.endswith("/v1") and endpoint.startswith("/v1/"):
        return base + endpoint[len("/v1"):]
    return base + endpoint


def _first_string(payload: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        return item
                    found = _first_string(item, keys)
                    if found:
                        return found
        for value in payload.values():
            found = _first_string(value, keys)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _first_string(item, keys)
            if found:
                return found
    return None


def _response_failed_count(response: Any) -> int:
    if not isinstance(response, dict):
        return 0
    for container_key in ("metadata", "data"):
        container = response.get(container_key)
        if not isinstance(container, dict):
            continue
        value = container.get("failed_count")
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _decode_image_base64(value: str) -> bytes:
    data = value.strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    return base64.b64decode(data)


def _image_suffix_from_bytes(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _openai_size_for_aspect(aspect_ratio: str) -> str:
    if aspect_ratio == "1:1":
        return "1024x1024"
    if aspect_ratio in {"9:16", "3:4"}:
        return "1024x1536"
    return "1536x1024"


def _openai_size_for_model(model: str, aspect_ratio: str) -> str:
    if model.startswith("dall-e-3"):
        if aspect_ratio in {"9:16", "3:4"}:
            return "1024x1792"
        if aspect_ratio in {"16:9", "4:3", "2.35:1"}:
            return "1792x1024"
        return "1024x1024"
    if model.startswith("dall-e"):
        return "1024x1024"
    return _openai_size_for_aspect(aspect_ratio)


def _openai_can_inherit_llm_credentials(cfg: dict[str, Any]) -> bool:
    if str(cfg.get("llm_provider") or "").lower() != "openai":
        return False
    llm_base_url = str(cfg.get("llm_base_url") or "").strip()
    if not llm_base_url:
        return True
    return urllib.parse.urlparse(llm_base_url).netloc.lower() == "api.openai.com"


def _validate_openai_image_base_url(model: str, base_url: str) -> None:
    if not str(model or "").startswith("gpt-image-"):
        return
    host = urllib.parse.urlparse(base_url).netloc.lower()
    if host and host != "api.openai.com":
        raise ValueError("gpt-image-* 模型仅支持 OpenAI 官方图片接口: https://api.openai.com/v1")


def _openai_image_api_key(cfg: dict[str, Any]) -> str:
    api_key = str(cfg.get("openai_api_key") or "").strip()
    if api_key:
        return api_key
    if _openai_can_inherit_llm_credentials(cfg):
        return str(cfg.get("llm_api_key") or "").strip()
    return ""


def _openai_image_base_url(cfg: dict[str, Any], model: str) -> str:
    base_url = str(cfg.get("openai_base_url") or "").strip()
    if not base_url and _openai_can_inherit_llm_credentials(cfg):
        base_url = str(cfg.get("llm_base_url") or "").strip()
    base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
    _validate_openai_image_base_url(model, base_url)
    return base_url


def _generate_with_minimax(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Generate image via MiniMax API."""
    api_key = cfg.get("minimax_api_key") or ""
    base_url = str(cfg.get("minimax_base_url") or "https://api.minimaxi.com").rstrip("/")
    model = cfg.get("minimax_image_model") or "image-01"
    if not api_key:
        _log.warning("[配图/MiniMax] 未配置API Key")
        return None

    url = _append_api_endpoint(base_url, "/v1/image_generation")
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": "3:4",
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": bool(cfg.get("minimax_prompt_optimizer", True)),
        "aigc_watermark": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        base_resp = data.get("base_resp") if isinstance(data, dict) else None
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
            _log.warning("[配图/MiniMax] API失败: %s", base_resp.get("status_msg") or data)
            return None
        if _response_failed_count(data):
            _log.warning("[配图/MiniMax] 部分失败: %s", data)
            return None
        image_base64 = _first_string(data, ("image_base64", "image_base64s", "base64"))
        if image_base64:
            return _decode_image_base64(image_base64)
        image_url = _first_string(data, ("image_urls", "url", "image_url")) or ""
        if not image_url:
            _log.warning("[配图/MiniMax] 响应无图片数据: %s", data)
            return None
        # Download image
        img_req = urllib.request.Request(image_url)
        with urllib.request.urlopen(img_req, timeout=60) as img_resp:
            return img_resp.read()
    except Exception as exc:
        _log.warning("[配图/MiniMax] 生成失败: %s", exc)
        return None


def _generate_with_openai(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Generate image via OpenAI-compatible API (includes DALL-E, Imagen, etc.)."""
    model = str(cfg.get("openai_image_model") or "gpt-image-2")
    api_key = _openai_image_api_key(cfg)
    if not api_key:
        _log.warning("[配图/OpenAI] 未配置API Key")
        return None
    try:
        base_url = _openai_image_base_url(cfg, model)
    except ValueError as exc:
        _log.warning("[配图/OpenAI] 配置无效: %s", exc)
        return None

    url = f"{base_url}/images/generations"
    aspect_ratio = str(cfg.get("article_image_aspect_ratio") or DEFAULT_IMAGE_SIZE)
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": cfg.get("article_openai_image_size") or _openai_size_for_model(model, aspect_ratio),
    }
    quality = cfg.get("openai_image_quality") or ("standard" if model.startswith("dall-e") else "medium")
    if model.startswith("dall-e-3"):
        payload["response_format"] = "url"
        payload["quality"] = quality
    elif model.startswith("dall-e"):
        payload["response_format"] = "url"
    else:
        payload["quality"] = quality
        payload["output_format"] = "png"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        image_base64 = _first_string(data, ("b64_json", "image_base64", "base64"))
        if image_base64:
            return _decode_image_base64(image_base64)
        image_url = _first_string(data, ("url",)) or ""
        if not image_url:
            _log.warning("[配图/OpenAI] 响应无图片数据: %s", data)
            return None
        img_req = urllib.request.Request(image_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(img_req, timeout=60) as img_resp:
            return img_resp.read()
    except Exception as exc:
        _log.warning("[配图/OpenAI] 生成失败: %s", exc)
        return None


def _generate_with_gemini(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Generate image via Gemini Imagen API."""
    api_key = cfg.get("gemini_api_key") or ""
    base_url = str(cfg.get("gemini_base_url") or "https://generativelanguage.googleapis.com").rstrip("/")
    model = cfg.get("gemini_image_model") or "imagen-4.0-generate-001"
    if not api_key:
        _log.warning("[配图/Gemini] 未配置API Key")
        return None

    url = f"{base_url}/v1beta/models/{urllib.parse.quote(model, safe='')}:predict"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "3:4"},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        # Gemini Imagen returns base64 encoded image
        image_bytes_b64 = _first_string(data, ("bytesBase64Encoded", "image_base64", "base64"))
        if not image_bytes_b64:
            _log.warning("[配图/Gemini] 响应无图片数据: %s", str(data)[:200])
            return None
        return _decode_image_base64(image_bytes_b64)
    except Exception as exc:
        _log.warning("[配图/Gemini] 生成失败: %s", exc)
        return None


def _provider_order(cfg: dict[str, Any]) -> list[str]:
    primary = str(cfg.get("image_generation_provider") or "").strip().lower()
    raw_order = str(cfg.get("image_generation_fallback_order") or "minimax,openai,gemini").strip()
    order: list[str] = []
    if primary:
        order.append(primary)
    for item in re.split(r"[,>\s]+", raw_order):
        provider = item.strip().lower()
        if provider and provider not in order:
            order.append(provider)
    return order


def _generate_image(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Try the selected provider first, then configured fallback providers."""
    tried: list[str] = []
    for prov in _provider_order(cfg):
        if prov == "minimax":
            tried.append("MiniMax")
            data = _generate_with_minimax(prompt, cfg)
            if data:
                _log.info("[配图] MiniMax 生成成功")
                return data
        elif prov == "openai":
            tried.append("OpenAI")
            data = _generate_with_openai(prompt, cfg)
            if data:
                _log.info("[配图] OpenAI 生成成功")
                return data
        elif prov == "gemini":
            tried.append("Gemini")
            data = _generate_with_gemini(prompt, cfg)
            if data:
                _log.info("[配图] Gemini 生成成功")
                return data
        elif prov == "local":
            _log.warning("[配图] 本地图片生成暂不支持，跳过")
            continue
    _log.warning("[配图] 所有提供商均失败: %s", tried)
    return None


# ── Core pipeline ──────────────────────────────────────────────────

def generate_illustrations(
    body: str,
    title: str,
    output_dir: Path,
    cfg: dict[str, Any],
    *,
    source_type: str = "video",
    video_path: str | Path | None = None,
) -> tuple[str, list[str]]:
    """
    Generate and insert AI illustrations into article body.

    Returns: (body_with_images, list_of_image_paths)
    """
    if len(body.strip()) < MIN_CHARS_FOR_IMAGE:
        _log.info("[配图] 正文仅 %d 字，跳过配图生成（门槛 %d）", len(body), MIN_CHARS_FOR_IMAGE)
        return body, []

    if source_type == "video" and bool(cfg.get("article_prefer_video_keyframes", True)):
        keyframes = _extract_video_keyframes(video_path, output_dir, body, cfg)
        if keyframes:
            result_body = body
            for pos, caption, img_path in sorted(keyframes, key=lambda item: item[0], reverse=True):
                result_body = _insert_image_markdown(result_body, pos, caption, img_path)
            image_paths = [path for _, _, path in keyframes]
            _log.info("[配图/关键帧] 已插入 %d 张视频关键帧", len(image_paths))
            return result_body, image_paths

    plans = _analyze_illustration_plan(body, title, cfg)
    if not plans:
        _log.warning("[配图] LLM未返回有效计划，使用规则兜底计划")
        plans = _fallback_illustration_plan(body, title, cfg)
    if not plans:
        return body, []

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Sort by position descending so insertions don't shift offsets
    plans.sort(key=lambda p: p.position, reverse=True)

    generated: list[tuple[int, str, str]] = []  # (position, caption, path)

    for i, plan in enumerate(plans):
        _log.info("[配图] 生成第 %d 张，位置 %d，prompt: %s", i + 1, plan.position, plan.prompt[:80])
        image_bytes = _generate_image(plan.prompt, cfg)
        if image_bytes:
            image_suffix = _image_suffix_from_bytes(image_bytes)
            img_path = images_dir / f"img_{i+1:03d}{image_suffix}"
            img_path.write_bytes(image_bytes)
            _log.info("[配图] 已保存: %s", img_path)
            generated.append((plan.position, plan.caption, f"images/img_{i+1:03d}{image_suffix}"))
        else:
            _log.warning("[配图] 第 %d 张生成失败，跳过", i + 1)

    if not generated:
        return body, []

    # Insert images (already sorted descending by position)
    result_body = body
    for pos, caption, img_path in generated:
        result_body = _insert_image_markdown(result_body, pos, caption, img_path)

    image_paths = [path for _, _, path in generated]
    _log.info("[配图] 已插入 %d 张配图到文章", len(generated))
    return result_body, image_paths

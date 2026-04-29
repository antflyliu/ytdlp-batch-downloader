"""Article illustration generation — auto-insert AI-generated images into article body.

Triggered when article body exceeds MIN_CHARS_FOR_IMAGE (default 300).
Uses LLM to analyze the article and determine where/how to insert illustrations.
Supports multiple providers with fallback: minimax → openai → gemini.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger("article_image_generator")

# ── Config defaults ────────────────────────────────────────────────
MIN_CHARS_FOR_IMAGE = 300  # 正文少于该字数不生成配图
CHARS_PER_IMAGE = 400  # 每 N 个字符一张配图
MAX_IMAGES = 10  # 最多生成配图数量
DEFAULT_IMAGE_SIZE = "3:4"  # 正文配图比例
DEFAULT_COVER_SIZE = "2.35:1"  # 封面比例（消息列表）
IMAGE_TIMEOUT_SECONDS = 300


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

    n_images = min(MAX_IMAGES, max(1, len(body) // CHARS_PER_IMAGE))
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
        response = client.call_with_retry(prompt, body[:2000], max_retries=2, timeout=60)
    except Exception as exc:
        _log.warning("[配图] LLM分析失败: %s", exc)
        return []

    # Parse JSON response
    try:
        # Try to extract JSON from response
        json_match = re.search(r"\[\s*\{.*?\}\s*\]", response, re.DOTALL)
        if not json_match:
            _log.warning("[配图] LLM响应中未找到JSON数组，响应前100字符: %s", response[:100])
            return []
        plans_data = json.loads(json_match.group(0))
        if not isinstance(plans_data, list):
            _log.warning("[配图] LLM响应不是数组类型，实际类型: %s", type(plans_data).__name__)
            return []
        plans = []
        for item in plans_data:
            try:
                plans.append(ImagePlan(
                    position=int(item.get("position", 0)),
                    prompt=str(item.get("prompt", "")),
                    caption=str(item.get("caption", "")),
                ))
            except (ValueError, TypeError):
                continue
        _log.info("[配图] LLM分析得到 %d 张配图计划", len(plans))
        return plans
    except json.JSONDecodeError as exc:
        _log.warning("[配图] JSON解析失败: %s", exc)
        return []


# ── Image generation providers ─────────────────────────────────────

def _generate_with_minimax(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Generate image via MiniMax API."""
    api_key = cfg.get("minimax_api_key") or ""
    base_url = str(cfg.get("minimax_base_url") or "https://api.minimax.io").rstrip("/")
    model = cfg.get("minimax_image_model") or "image-01"
    if not api_key:
        _log.warning("[配图/MiniMax] 未配置API Key")
        return None

    url = f"{base_url}/v1/image_generation"
    payload = {
        "model": model,
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": "3:4",
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
        image_url = (
            data.get("data", [{}])[0].get("url")
            or data.get("image_url")
            or ""
        )
        if not image_url:
            _log.warning("[配图/MiniMax] 响应无URL: %s", data)
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
    api_key = cfg.get("openai_api_key") or ""
    base_url = str(cfg.get("openai_base_url") or "https://api.openai.com/v1").rstrip("/")
    model = cfg.get("openai_image_model") or "dall-e-3"
    if not api_key:
        _log.warning("[配图/OpenAI] 未配置API Key")
        return None

    url = f"{base_url}/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "url",
    }
    quality = cfg.get("openai_image_quality") or "standard"
    if model.startswith("dall-e") and quality:
        payload["quality"] = quality
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
        image_url = (
            data.get("data", [{}])[0].get("url")
            or data.get("url")
            or ""
        )
        if not image_url:
            _log.warning("[配图/OpenAI] 响应无URL: %s", data)
            return None
        img_req = urllib.request.Request(image_url)
        with urllib.request.urlopen(img_req, timeout=60) as img_resp:
            return img_resp.read()
    except Exception as exc:
        _log.warning("[配图/OpenAI] 生成失败: %s", exc)
        return None


def _generate_with_gemini(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Generate image via Gemini Imagen API."""
    api_key = cfg.get("gemini_api_key") or ""
    base_url = str(cfg.get("gemini_base_url") or "https://generativelanguage.googleapis.com").rstrip("/")
    model = cfg.get("gemini_image_model") or "imagen-3.0-generate-001"
    if not api_key:
        _log.warning("[配图/Gemini] 未配置API Key")
        return None

    url = f"{base_url}/v1beta/models/{model}:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1},
    }
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode())
        # Gemini Imagen returns base64 encoded image
        image_bytes_b64 = (
            data.get("predictions", [{}])[0].get("bytesBase64Encoded", "")
            or data.get("image", {}).get("bytesBase64Encoded", "")
        )
        if not image_bytes_b64:
            _log.warning("[配图/Gemini] 响应无图片数据: %s", str(data)[:200])
            return None
        import base64
        return base64.b64decode(image_bytes_b64)
    except Exception as exc:
        _log.warning("[配图/Gemini] 生成失败: %s", exc)
        return None


def _generate_image(prompt: str, cfg: dict[str, Any]) -> bytes | None:
    """Try providers in order: minimax → openai → gemini."""
    provider = cfg.get("image_generation_provider") or "minimax"
    fallback_order = [
        p.strip() for p in
        (cfg.get("image_generation_fallback_order") or "minimax,openai,gemini").split(",")
        if p.strip()
    ]
    tried: list[str] = []
    for prov in fallback_order:
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
) -> tuple[str, list[str]]:
    """
    Generate and insert AI illustrations into article body.

    Returns: (body_with_images, list_of_image_paths)
    """
    if len(body.strip()) < MIN_CHARS_FOR_IMAGE:
        _log.info("[配图] 正文仅 %d 字，跳过配图生成（门槛 %d）", len(body), MIN_CHARS_FOR_IMAGE)
        return body, []

    plans = _analyze_illustration_plan(body, title, cfg)
    if not plans:
        _log.warning("[配图] LLM未返回有效计划，跳过")
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
            img_path = images_dir / f"img_{i+1:03d}.png"
            img_path.write_bytes(image_bytes)
            _log.info("[配图] 已保存: %s", img_path)
            generated.append((plan.position, plan.caption, f"images/img_{i+1:03d}.png"))
        else:
            _log.warning("[配图] 第 %d 张生成失败，跳过", i + 1)

    if not generated:
        return body, []

    # Insert images (already sorted descending by position)
    result_body = body
    for pos, caption, img_path in generated:
        img_md = f'\n![{caption}]({img_path})\n'
        # Clamp position
        pos = min(pos, len(result_body))
        result_body = result_body[:pos] + img_md + result_body[pos:]

    image_paths = [path for _, _, path in generated]
    _log.info("[配图] 已插入 %d 张配图到文章", len(generated))
    return result_body, image_paths

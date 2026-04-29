"""Shared AI image generation provider layer.

The provider abstraction is intentionally small: business workflows pass a
prompt, target aspect ratio, and output path, while each provider handles its
own API shape and returns a materialized local image file.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_FALLBACK_ORDER = ("minimax", "openai", "gemini", "local")


@dataclass
class ImageGenerationRequest:
    prompt: str
    output_path: str | Path
    purpose: str = "wechat_cover"
    aspect_ratio: str = "16:9"
    size: str | None = None
    quality: str = "medium"
    output_format: str = "png"
    reference_images: list[str] = field(default_factory=list)


@dataclass
class ImageGenerationResult:
    provider: str
    path: Path
    mime_type: str = "image/png"
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class ImageProvider:
    name = "provider"

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}

    def is_configured(self) -> bool:
        return True

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        raise NotImplementedError


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 180) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _save_base64_image(path: Path, data: str) -> Path:
    value = data.strip()
    if "," in value and value.startswith("data:"):
        value = value.split(",", 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(value))
    return path


def _download_url(url: str, path: Path, headers: dict[str, str] | None = None) -> Path:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=180) as resp:
        content = resp.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _output_path(request: ImageGenerationRequest) -> Path:
    return Path(request.output_path)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _write_placeholder_png(path: Path, prompt: str, aspect_ratio: str) -> Path:
    width, height = (900, 383)
    if aspect_ratio == "1:1":
        width, height = (768, 768)
    elif aspect_ratio == "9:16":
        width, height = (720, 1280)
    elif aspect_ratio == "3:4":
        width, height = (768, 1024)
    seed = sum(ord(ch) for ch in prompt) % 97
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            wave = ((x * 3 + y * 2 + seed) // 37) % 24
            rows.extend((194 + wave, 110 + wave // 2, 78 + (seed % 21)))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def _normalize_fallback_order(value: Any, primary: Any = None) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,>\s]+", str(value or ",".join(DEFAULT_FALLBACK_ORDER)))
    order = []
    primary_name = str(primary or "").strip().lower()
    if primary_name:
        order.append(primary_name)
    for item in raw:
        name = str(item).strip().lower()
        if name and name not in order:
            order.append(name)
    if "local" not in order:
        order.append("local")
    return order


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


class MiniMaxImageProvider(ImageProvider):
    name = "minimax"

    def is_configured(self) -> bool:
        return bool(str(self.cfg.get("minimax_api_key") or "").strip())

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        api_key = str(self.cfg.get("minimax_api_key") or "").strip()
        base_url = str(self.cfg.get("minimax_base_url") or "https://api.minimax.io").rstrip("/")
        model = str(self.cfg.get("minimax_image_model") or "image-01")
        payload = {
            "model": model,
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "response_format": "base64",
            "n": 1,
        }
        response = _post_json(
            f"{base_url}/v1/image_generation",
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout=int(self.cfg.get("image_generation_timeout_seconds") or 180),
        )
        base_resp = response.get("base_resp") if isinstance(response, dict) else None
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
            raise RuntimeError(str(base_resp.get("status_msg") or response))
        if isinstance(response.get("data"), dict) and response["data"].get("failed_count"):
            raise RuntimeError(f"MiniMax 图片生成部分失败: {response}")
        image_data = _first_string(response, ("image_base64", "image_base64s", "base64"))
        image_url = _first_string(response, ("image_urls", "url", "image_url"))
        path = _output_path(request)
        if image_data:
            _save_base64_image(path, image_data)
        elif image_url:
            _download_url(image_url, path)
        else:
            raise RuntimeError(f"MiniMax 未返回图片数据: {response}")
        return ImageGenerationResult(provider=self.name, path=path, raw_metadata=response)


class OpenAIImageProvider(ImageProvider):
    name = "openai"

    def is_configured(self) -> bool:
        return bool(self._api_key())

    def _can_inherit_llm_credentials(self) -> bool:
        if str(self.cfg.get("llm_provider") or "").lower() != "openai":
            return False
        llm_base_url = str(self.cfg.get("llm_base_url") or "").strip()
        if not llm_base_url:
            return True
        host = urllib.parse.urlparse(llm_base_url).netloc.lower()
        return host == "api.openai.com"

    def _api_key(self) -> str:
        api_key = str(self.cfg.get("openai_api_key") or "").strip()
        if api_key:
            return api_key
        if self._can_inherit_llm_credentials():
            return str(self.cfg.get("llm_api_key") or "").strip()
        return ""

    def _base_url(self) -> str:
        base_url = str(self.cfg.get("openai_base_url") or "").strip()
        if base_url:
            self._validate_base_url_for_model(base_url)
            return base_url.rstrip("/")
        if self._can_inherit_llm_credentials():
            llm_base_url = str(self.cfg.get("llm_base_url") or "").strip()
            if llm_base_url:
                self._validate_base_url_for_model(llm_base_url)
                return llm_base_url.rstrip("/")
        return "https://api.openai.com/v1"

    def _validate_base_url_for_model(self, base_url: str) -> None:
        model = str(self.cfg.get("openai_image_model") or "gpt-image-2").strip()
        if not model.startswith("gpt-image-"):
            return
        host = urllib.parse.urlparse(base_url).netloc.lower()
        if host and host != "api.openai.com":
            raise ValueError("gpt-image-* 模型仅支持 OpenAI 官方图片接口: https://api.openai.com/v1")

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        api_key = self._api_key()
        base_url = self._base_url()
        model = str(self.cfg.get("openai_image_model") or "gpt-image-2")
        payload = {
            "model": model,
            "prompt": request.prompt,
            "n": 1,
            "size": request.size or self.cfg.get("openai_image_size") or _openai_size_for_ratio(request.aspect_ratio),
            "quality": request.quality or self.cfg.get("openai_image_quality") or "medium",
        }
        if request.output_format:
            payload["output_format"] = request.output_format
        response = _post_json(
            f"{base_url}/images/generations",
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout=int(self.cfg.get("image_generation_timeout_seconds") or 300),
        )
        image_data = _first_string(response, ("b64_json", "image_base64", "base64"))
        image_url = _first_string(response, ("url",))
        path = _output_path(request)
        if image_data:
            _save_base64_image(path, image_data)
        elif image_url:
            _download_url(image_url, path, {"Authorization": f"Bearer {api_key}"})
        else:
            raise RuntimeError(f"OpenAI 未返回图片数据: {response}")
        return ImageGenerationResult(provider=self.name, path=path, raw_metadata=response)


class GeminiImageProvider(ImageProvider):
    name = "gemini"

    def is_configured(self) -> bool:
        return bool(str(self.cfg.get("gemini_api_key") or "").strip())

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        api_key = str(self.cfg.get("gemini_api_key") or "").strip()
        base_url = str(self.cfg.get("gemini_base_url") or "https://generativelanguage.googleapis.com").rstrip("/")
        model = str(self.cfg.get("gemini_image_model") or "imagen-4.0-generate-001")
        payload = {
            "instances": [{"prompt": request.prompt}],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": request.aspect_ratio,
            },
        }
        url = f"{base_url}/v1beta/models/{urllib.parse.quote(model, safe='')}:predict"
        response = _post_json(
            url,
            payload,
            {"x-goog-api-key": api_key},
            timeout=int(self.cfg.get("image_generation_timeout_seconds") or 300),
        )
        image_data = _first_string(response, ("bytesBase64Encoded", "image_base64", "base64"))
        image_url = _first_string(response, ("url", "image_url"))
        path = _output_path(request)
        if image_data:
            _save_base64_image(path, image_data)
        elif image_url:
            _download_url(image_url, path)
        else:
            raise RuntimeError(f"Gemini 未返回图片数据: {response}")
        return ImageGenerationResult(provider=self.name, path=path, raw_metadata=response)


class LocalPlaceholderImageProvider(ImageProvider):
    name = "local"

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        path = _write_placeholder_png(_output_path(request), request.prompt, request.aspect_ratio)
        return ImageGenerationResult(provider=self.name, path=path)


def _openai_size_for_ratio(aspect_ratio: str) -> str:
    if aspect_ratio == "1:1":
        return "1024x1024"
    if aspect_ratio in {"9:16", "3:4"}:
        return "1024x1536"
    return "1536x1024"


def _build_provider(name: str, cfg: dict[str, Any]) -> ImageProvider:
    providers: dict[str, type[ImageProvider]] = {
        "minimax": MiniMaxImageProvider,
        "openai": OpenAIImageProvider,
        "gemini": GeminiImageProvider,
        "local": LocalPlaceholderImageProvider,
    }
    provider_cls = providers.get(name)
    if provider_cls is None:
        raise ValueError(f"未知图片生成提供商: {name}")
    return provider_cls(cfg)


def generate_image_with_fallback(
    request: ImageGenerationRequest,
    cfg: dict[str, Any],
) -> ImageGenerationResult:
    errors: list[str] = []
    for name in _normalize_fallback_order(
        cfg.get("image_generation_fallback_order"),
        cfg.get("image_generation_provider"),
    ):
        try:
            provider = _build_provider(name, cfg)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if not provider.is_configured():
            errors.append(f"{name}: 未配置")
            continue
        try:
            return provider.generate(request)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
    raise RuntimeError("图片生成失败: " + "; ".join(errors))


def build_wechat_cover_prompt(title: str, digest: str | None = None) -> str:
    parts = [
        "微信公众号文章封面图，16:9 横版，现代中文媒体封面，干净留白，暖色调，专业但不夸张。",
        "不要生成可读的小字或水印，画面应适合作为公众号图文封面。",
        f"主题标题: {title.strip()}",
    ]
    if digest:
        parts.append(f"文章摘要: {digest.strip()[:240]}")
    return "\n".join(parts)

"""WeChat Official Account article publishing.

This module ports the API path used by baoyu-post-to-wechat's
``scripts/wechat-api.ts`` into the Python monitor service. It supports two
separate operations: create a draft, and create a draft then submit it for
freepublish.
"""
from __future__ import annotations

from typing import Any

import html
import ipaddress
import json
import logging
import mimetypes
import os
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_log = logging.getLogger("monitor.wechat_publisher")

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
UPLOAD_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
PUBLISH_URL = "https://api.weixin.qq.com/cgi-bin/freepublish/submit"

_ACCESS_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_DEFAULT_COVER_FILENAME = "_wechat_default_cover.png"
_MAX_REMOTE_IMAGE_BYTES = 10 * 1024 * 1024
_ALLOWED_MARKDOWN_LINK_SCHEMES = {"http", "https", "mailto"}


@dataclass
class WechatPublishResult:
    success: bool
    wx_article_id: Optional[str] = None
    wx_url: Optional[str] = None
    error: Optional[str] = None


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        value = value.strip().strip("\"'")
        values[key.strip()] = value
    return values


def _load_baoyu_wechat_env() -> dict[str, str]:
    project_env = _load_env_file(Path.cwd() / ".baoyu-skills" / ".env")
    user_env = _load_env_file(Path.home() / ".baoyu-skills" / ".env")
    return {**user_env, **project_env}


def _normalize_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _format_wechat_api_error(operation: str, payload: dict) -> str:
    errmsg = str(payload.get("errmsg") or payload)
    errcode = str(payload.get("errcode") or "")
    lower_msg = errmsg.lower()
    is_invalid_ip = (
        errcode == "40164"
        or ("invalid ip" in lower_msg and "not in whitelist" in lower_msg)
    )
    if not is_invalid_ip:
        if "invalid media_id" in lower_msg:
            return (
                f"{operation} 失败: 微信返回 invalid media_id。"
                "图文草稿必须使用当前公众号下的永久图片素材作为封面 thumb_media_id。"
                "请确认封面图片可上传，或重新保存草稿以自动生成默认封面。"
                f"微信原始错误: {errmsg}"
            )
        return f"{operation} 失败: {errmsg}"

    ip_match = re.search(r"\binvalid ip\s+([0-9]{1,3}(?:\.[0-9]{1,3}){3})\b", errmsg, re.I)
    if not ip_match:
        ip_match = re.search(r"\b([0-9]{1,3}(?:\.[0-9]{1,3}){3})\b", errmsg)
    ip_hint = f" {ip_match.group(1)}" if ip_match else ""
    return (
        f"{operation} 失败: 当前服务器出口 IP{ip_hint} 未加入微信公众号后台 IP 白名单。"
        "请在微信公众号后台「设置与开发」->「基本配置」->「IP 白名单」中添加该 IP 后重试。"
        f"微信原始错误: {errmsg}"
    )


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _write_default_cover_png(path: Path) -> None:
    width, height = 900, 383
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            accent = int(190 + (x / width) * 35)
            shade = int(238 - (y / height) * 34)
            band = 18 if ((x + y) // 48) % 2 == 0 else 0
            rows.extend(
                (
                    min(255, accent + band),
                    max(120, shade - band // 2),
                    max(90, 202 - band),
                )
            )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _ensure_default_cover_image(*, base_dir: str | Path | None, data_dir: str | Path | None) -> str:
    cover_dir = Path(base_dir) if base_dir else Path(data_dir or "output/articles")
    cover_path = cover_dir / _DEFAULT_COVER_FILENAME
    if not cover_path.is_file():
        _write_default_cover_png(cover_path)
    return str(cover_path)


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_blocked_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_public_image_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"不支持的远程图片地址: {url}")

    host = parsed.hostname.strip("[]").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise PermissionError(f"禁止读取本机图片地址: {host}")

    try:
        if _is_blocked_ip(host):
            raise PermissionError(f"禁止读取内网图片地址: {host}")
        return parsed
    except ValueError:
        pass

    try:
        addr_infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"无法解析远程图片域名: {host}") from exc
    for addr_info in addr_infos:
        address = addr_info[4][0]
        if _is_blocked_ip(address):
            raise PermissionError(f"禁止读取内网图片地址: {host}")
    return parsed


def _read_remote_image_bytes(image_url: str) -> tuple[bytes, str, str]:
    parsed = _validate_public_image_url(image_url)
    req = urllib.request.Request(image_url, headers={"User-Agent": "ytdlp-batch-downloader/monitor"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        final_url = resp.geturl()
        if final_url and final_url != image_url:
            parsed = _validate_public_image_url(final_url)
        content_type = (resp.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise ValueError(f"远程资源不是图片: {content_type}")
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > _MAX_REMOTE_IMAGE_BYTES:
                    raise ValueError("远程图片超过大小限制")
            except ValueError as exc:
                if "超过大小限制" in str(exc):
                    raise
        file_bytes = resp.read(_MAX_REMOTE_IMAGE_BYTES + 1)
    if len(file_bytes) > _MAX_REMOTE_IMAGE_BYTES:
        raise ValueError("远程图片超过大小限制")
    filename = Path(urllib.parse.unquote(parsed.path)).name or "image.jpg"
    return file_bytes, filename, content_type


class WechatPublisher:
    """WeChat Official Account publisher using the public API."""

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        data_dir: str | None = None,
    ):
        from config.settings import load_config

        cfg = load_config()
        baoyu_env = _load_baoyu_wechat_env()
        self.app_id = (
            app_id
            if app_id is not None
            else cfg.get("wechat_app_id") or os.environ.get("WECHAT_APP_ID") or baoyu_env.get("WECHAT_APP_ID") or ""
        ).strip()
        self.app_secret = (
            app_secret
            if app_secret is not None
            else cfg.get("wechat_app_secret")
            or os.environ.get("WECHAT_APP_SECRET")
            or baoyu_env.get("WECHAT_APP_SECRET")
            or ""
        ).strip()
        self.data_dir = data_dir or cfg.get("article_output_dir") or "output/articles"
        self.default_author = cfg.get("wechat_default_author") or ""
        self.default_theme = cfg.get("wechat_default_theme") or "default"
        self.default_color = cfg.get("wechat_default_color") or "blue"
        self.cfg = cfg
        self._validate_credentials()

    def _validate_credentials(self) -> None:
        if not self.app_id:
            raise ValueError("wechat_app_id is required")
        if not self.app_secret:
            raise ValueError("wechat_app_secret is required")
        if not re.match(r"^wx[a-zA-Z0-9]{16}$", self.app_id):
            raise ValueError(f"wechat_app_id 格式不正确: {self.app_id}")

    def _get_access_token(self) -> str:
        cache_key = self.app_id
        cached = _ACCESS_TOKEN_CACHE.get(cache_key)
        if cached:
            token, expire_at = cached
            if time.time() < expire_at - 60:
                return token

        query = urllib.parse.urlencode(
            {
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            }
        )
        try:
            with urllib.request.urlopen(f"{TOKEN_URL}?{query}", timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"获取 access_token 失败: {exc}") from exc

        if payload.get("errcode"):
            raise RuntimeError(_format_wechat_api_error("获取 access_token", payload))
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("获取 access_token 失败: 响应缺少 access_token")
        expires_in = int(payload.get("expires_in") or 7200)
        _ACCESS_TOKEN_CACHE[cache_key] = (token, time.time() + expires_in)
        return token

    def _api_post(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                return {"errcode": exc.code, "errmsg": str(exc)}
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API 请求失败: {exc}") from exc

    def _safe_base_dir(self, base_dir: str | Path | None = None) -> Path | None:
        if not base_dir:
            return None
        candidate = Path(base_dir).expanduser().resolve()
        data_root = Path(self.data_dir or "output/articles").expanduser().resolve()
        if _is_path_inside(candidate, data_root):
            return candidate
        _log.warning("忽略不在文章输出目录内的本地路径: %s", candidate)
        return None

    def _allowed_local_image_roots(self, base_dir: str | Path | None = None) -> list[Path]:
        data_root = Path(self.data_dir or "output/articles").expanduser().resolve()
        roots = [data_root]
        safe_base = self._safe_base_dir(base_dir)
        if safe_base and safe_base not in roots:
            roots.append(safe_base)
        return roots

    def _upload_image(self, image_path: str | None, *, base_dir: str | Path | None = None) -> dict | None:
        if not image_path:
            return None
        file_bytes, filename, content_type = _read_image_bytes(
            image_path,
            base_dir=base_dir,
            allowed_roots=self._allowed_local_image_roots(base_dir),
        )
        token = self._get_access_token()
        boundary = f"----WechatBoundary{int(time.time() * 1000)}"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = head + file_bytes + tail
        req = urllib.request.Request(
            f"{UPLOAD_URL}?access_token={urllib.parse.quote(token)}&type=image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"图片上传失败: {exc}") from exc
        if payload.get("errcode"):
            raise RuntimeError(_format_wechat_api_error("图片上传", payload))
        if isinstance(payload.get("url"), str) and payload["url"].startswith("http://"):
            payload["url"] = payload["url"].replace("http://", "https://", 1)
        return payload

    def _resolve_thumb_media_id(
        self,
        *,
        first_media_id: str,
        title: str,
        content: str,
        cover_image: str | None,
        base_dir: str | Path | None = None,
    ) -> str:
        cover_payload = None
        if cover_image:
            try:
                cover_payload = self._upload_image(cover_image, base_dir=base_dir)
            except Exception as exc:
                _log.warning("显式封面上传失败，继续尝试生成封面: %s", exc)
        thumb_media_id = (cover_payload or {}).get("media_id") or first_media_id
        if thumb_media_id:
            return thumb_media_id

        generated_cover = self._generate_wechat_cover(title=title, content=content, base_dir=base_dir)
        default_cover_payload = self._upload_image(generated_cover, base_dir=base_dir)
        thumb_media_id = (default_cover_payload or {}).get("media_id") or ""
        if not thumb_media_id:
            raise RuntimeError("创建草稿失败: 默认封面上传成功但未返回 media_id")
        return thumb_media_id

    def _generate_wechat_cover(
        self,
        *,
        title: str,
        content: str,
        base_dir: str | Path | None = None,
    ) -> str:
        safe_base_dir = self._safe_base_dir(base_dir)
        default_cover = _ensure_default_cover_image(base_dir=safe_base_dir, data_dir=self.data_dir)
        try:
            from scripts.image_generation import (
                ImageGenerationRequest,
                build_wechat_cover_prompt,
                generate_image_with_fallback,
            )

            output_dir = safe_base_dir if safe_base_dir else Path(default_cover).parent
            output_path = output_dir / "wechat_ai_cover.png"
            prompt = build_wechat_cover_prompt(title, _digest_from_html(content))
            result = generate_image_with_fallback(
                ImageGenerationRequest(
                    prompt=prompt,
                    output_path=output_path,
                    purpose="wechat_cover",
                    aspect_ratio="16:9",
                    size=str(self.cfg.get("openai_image_size") or "1536x1024"),
                    quality=str(self.cfg.get("openai_image_quality") or "medium"),
                    output_format="png",
                ),
                self.cfg,
            )
            return str(result.path)
        except Exception as exc:
            _log.warning("AI 生成公众号封面失败，使用本地默认封面: %s", exc)
            return default_cover

    def _upload_images_in_html(self, content: str, *, base_dir: str | Path | None = None) -> tuple[str, str, list[str]]:
        img_regex = re.compile(r"<img[^>]*\ssrc=[\"']([^\"']+)[\"'][^>]*>", re.I)
        updated = content
        first_media_id = ""
        all_media_ids: list[str] = []
        for match in list(img_regex.finditer(content)):
            full_tag, src = match.group(0), match.group(1)
            if src.startswith("https://mmbiz.qpic.cn"):
                continue
            local_match = re.search(r"data-local-path=[\"']([^\"']+)[\"']", full_tag)
            image_ref = local_match.group(1) if local_match else src
            try:
                payload = self._upload_image(image_ref, base_dir=base_dir)
            except Exception as exc:
                _log.warning("跳过无法上传的正文图片 %s: %s", image_ref, exc)
                continue
            if not payload:
                continue
            media_id = payload.get("media_id") or ""
            image_url = payload.get("url") or src
            if media_id:
                all_media_ids.append(media_id)
                first_media_id = first_media_id or media_id
            new_tag = re.sub(r"\ssrc=[\"'][^\"']+[\"']", f' src="{html.escape(image_url, quote=True)}"', full_tag)
            new_tag = re.sub(r"\sdata-local-path=[\"'][^\"']+[\"']", "", new_tag)
            updated = updated.replace(full_tag, new_tag, 1)
        updated = re.sub(r"\sdata-local-path=[\"'][^\"']+[\"']", "", updated)
        return updated, first_media_id, all_media_ids

    def _create_draft(
        self,
        *,
        title: str,
        content: str,
        author: str | None = None,
        digest: str | None = None,
        thumb_media_id: str | None = None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
    ) -> str:
        token = self._get_access_token()
        article: dict[str, Any] = {
            "article_type": "news",
            "title": title,
            "content": content,
            "need_open_comment": 1 if _normalize_bool(need_open_comment) else 0,
            "only_fans_can_comment": 1 if _normalize_bool(only_fans_can_comment) else 0,
        }
        if thumb_media_id:
            article["thumb_media_id"] = thumb_media_id
        if author:
            article["author"] = author[:16]
        if digest:
            article["digest"] = digest[:120]
        payload = self._api_post(f"{DRAFT_URL}?access_token={urllib.parse.quote(token)}", {"articles": [article]})
        if payload.get("errcode"):
            raise RuntimeError(_format_wechat_api_error("创建草稿", payload))
        media_id = payload.get("media_id")
        if not media_id:
            raise RuntimeError(f"创建草稿成功但未返回 media_id: {payload}")
        return media_id

    def _submit_publish(self, media_id: str) -> dict:
        token = self._get_access_token()
        payload = self._api_post(
            f"{PUBLISH_URL}?access_token={urllib.parse.quote(token)}",
            {"media_id": media_id},
        )
        if payload.get("errcode"):
            raise RuntimeError(_format_wechat_api_error("提交发布", payload))
        return payload

    def save_to_draft(
        self,
        title: str,
        content: str,
        *,
        author: str | None = None,
        cover_image: str | None = None,
        digest: str | None = None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
        base_dir: str | Path | None = None,
    ) -> WechatPublishResult:
        """Create a WeChat draft without submitting a mass publish."""
        try:
            content, first_media_id, _all_media_ids = self._upload_images_in_html(content, base_dir=base_dir)
            thumb_media_id = self._resolve_thumb_media_id(
                first_media_id=first_media_id,
                title=title,
                content=content,
                cover_image=cover_image,
                base_dir=base_dir,
            )
            media_id = self._create_draft(
                title=title,
                content=content,
                author=author or self.default_author,
                digest=digest or _digest_from_html(content),
                thumb_media_id=thumb_media_id,
                need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
            return WechatPublishResult(success=True, wx_article_id=media_id)
        except Exception as exc:
            _log.error("保存到微信公众号草稿箱失败: %s", exc)
            return WechatPublishResult(success=False, error=str(exc))

    def publish_now(
        self,
        title: str,
        content: str,
        *,
        author: str | None = None,
        cover_image: str | None = None,
        digest: str | None = None,
        need_open_comment: bool = True,
        only_fans_can_comment: bool = False,
        base_dir: str | Path | None = None,
    ) -> WechatPublishResult:
        """Create a draft and submit it to WeChat freepublish."""
        try:
            content, first_media_id, _all_media_ids = self._upload_images_in_html(content, base_dir=base_dir)
            thumb_media_id = self._resolve_thumb_media_id(
                first_media_id=first_media_id,
                title=title,
                content=content,
                cover_image=cover_image,
                base_dir=base_dir,
            )
            media_id = self._create_draft(
                title=title,
                content=content,
                author=author or self.default_author,
                digest=digest or _digest_from_html(content),
                thumb_media_id=thumb_media_id,
                need_open_comment=need_open_comment,
                only_fans_can_comment=only_fans_can_comment,
            )
            publish_payload = self._submit_publish(media_id)
            return WechatPublishResult(
                success=True,
                wx_article_id=str(publish_payload.get("publish_id") or media_id),
                wx_url=publish_payload.get("article_url"),
            )
        except Exception as exc:
            _log.error("微信公众号立即群发失败: %s", exc)
            return WechatPublishResult(success=False, error=str(exc))


def _read_image_bytes(
    image_path: str,
    *,
    base_dir: str | Path | None = None,
    allowed_roots: list[Path] | None = None,
) -> tuple[bytes, str, str]:
    if image_path.startswith(("http://", "https://")):
        file_bytes, filename, content_type = _read_remote_image_bytes(image_path)
    else:
        path = Path(image_path)
        if not path.is_absolute() and base_dir:
            path = Path(base_dir) / path
        path = path.expanduser().resolve()
        roots = [root.expanduser().resolve() for root in (allowed_roots or [])]
        if roots and not any(_is_path_inside(path, root) for root in roots):
            raise PermissionError(f"图片路径不在允许的文章输出目录内: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"图片不存在: {path}")
        file_bytes = path.read_bytes()
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
    if not file_bytes:
        raise ValueError(f"图片为空: {image_path}")
    return file_bytes, filename, content_type


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$", raw)
    if not match:
        return {}, raw
    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip("\"'")
    return frontmatter, match.group(2)


def _extract_title(frontmatter: dict[str, str], body: str, fallback: str) -> str:
    if frontmatter.get("title"):
        return frontmatter["title"].strip()
    for pattern in (r"^#\s+(.+)$", r"^选题[:：]\s*(.+)$", r"^标题[:：]\s*(.+)$"):
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return fallback


def _digest_from_html(content: str) -> str:
    text = re.sub(r"<[^>]+>", "", content)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:120]


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((.+?)\)", _safe_markdown_link, escaped)
    return escaped


def _safe_markdown_link(match: re.Match[str]) -> str:
    label = match.group(1)
    raw_url = html.unescape(match.group(2)).strip()
    parsed = urllib.parse.urlparse(raw_url)
    scheme = parsed.scheme.lower()
    if (
        scheme not in _ALLOWED_MARKDOWN_LINK_SCHEMES
        or (scheme in {"http", "https"} and not parsed.netloc)
        or (scheme == "mailto" and not parsed.path)
    ):
        return f"{label} ({html.escape(raw_url, quote=False)})" if raw_url else label
    return f'<a href="{html.escape(raw_url, quote=True)}">{label}</a>'


def build_article_content_from_draft(draft_path: str | Path) -> tuple[str, str]:
    """Parse draft.md into a title and simple WeChat-compatible HTML."""
    path = Path(draft_path)
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(raw)
    title = _extract_title(frontmatter, body, path.stem)
    base_dir = path.parent

    html_parts: list[str] = []
    in_code = False
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if stripped.startswith("类型：") or stripped.startswith("类型:") or stripped.startswith("生成时间："):
            continue
        h_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if h_match:
            level = min(6, max(2, len(h_match.group(1)) + 1))
            html_parts.append(f"<h{level}>{_inline_markdown(h_match.group(2).strip())}</h{level}>")
            continue
        img_match = re.match(r"!\[(.*?)\]\((.+?)\)", stripped)
        if img_match:
            alt, src = img_match.groups()
            image_path = src
            if not re.match(r"^https?://", src):
                image_path = str((base_dir / src).resolve())
            html_parts.append(
                '<p><img src="{src}" alt="{alt}" data-local-path="{local}" style="max-width:100%;"/></p>'.format(
                    src=html.escape(src, quote=True),
                    alt=html.escape(alt, quote=True),
                    local=html.escape(image_path, quote=True),
                )
            )
            continue
        if stripped.startswith(">"):
            html_parts.append(f"<blockquote>{_inline_markdown(stripped.lstrip('> ').strip())}</blockquote>")
            continue
        if stripped in {"---", "***"}:
            continue
        html_parts.append(f"<p>{_inline_markdown(stripped)}</p>")

    return title, "\n".join(html_parts)


def convert_md_to_html_for_wechat(input_path: str | Path) -> tuple[str, str]:
    """Compatibility wrapper used by the HTTP API layer."""
    return build_article_content_from_draft(input_path)

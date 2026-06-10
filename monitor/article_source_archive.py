from __future__ import annotations

import hashlib
import html
import ipaddress
import mimetypes
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import requests

import monitor.db as db

MAX_ASSET_BYTES = 25 * 1024 * 1024
ASSET_REQUEST_TIMEOUT = (10, 60)

_FILENAME_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".bmp",
    ".svg",
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".opus",
    ".mp4",
    ".webm",
    ".mov",
    ".pdf",
}


AssetDownloader = Callable[[str], tuple[bytes, str]]


@dataclass(slots=True)
class ArticleSourceArchiveResult:
    markdown_path: str
    markdown_text: str
    asset_paths: list[str] = field(default_factory=list)
    reused: bool = False


def archive_article_source(
    *,
    source_type: str,
    source_id: object,
    title: object = "",
    source_url: object = "",
    text: object = "",
    html_body: object = "",
    media: list[dict[str, Any]] | None = None,
    root: str | Path | None = None,
    downloader: AssetDownloader | None = None,
    prefer_text: bool = False,
) -> ArticleSourceArchiveResult:
    """Persist a source article as local markdown plus downloaded media assets.

    The archive path is stable for a source_type/source_id pair so repeated
    article-generation tasks reuse the existing local material instead of
    downloading linked assets again.
    """
    source_type_key = _safe_segment(source_type or "unknown")
    source_url_text = str(source_url or "").strip()
    source_id_key = _source_id_segment(source_id, source_url_text, title)
    host_key = _host_segment(source_url_text)
    archive_dir = _archive_root(root) / source_type_key / host_key / source_id_key
    markdown_path = archive_dir / "source.md"
    if markdown_path.is_file():
        return ArticleSourceArchiveResult(
            markdown_path=str(markdown_path),
            markdown_text=markdown_path.read_text(encoding="utf-8", errors="replace"),
            asset_paths=[str(path) for path in sorted((archive_dir / "assets").glob("*"))],
            reused=True,
        )

    archive_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = archive_dir / "assets"
    localizer = _AssetLocalizer(asset_dir, source_url_text, downloader=downloader)
    html_text = str(html_body or "")
    text_body = str(text or "").strip()
    html_markdown = (
        _RichHtmlMarkdownConverter(base_url=source_url_text, localizer=localizer).convert(html_text)
        if html_text.strip()
        else ""
    )
    if prefer_text and text_body:
        body = text_body
        if html_markdown and _plain_compact(html_markdown) not in _plain_compact(text_body):
            body = f"{body}\n\n## 原始 HTML 正文\n\n{html_markdown}"
    else:
        body = html_markdown or text_body
    media_section = _media_markdown(media or [], localizer)
    markdown_text = _build_source_markdown(
        source_type=source_type_key,
        title=str(title or "").strip(),
        source_url=source_url_text,
        body=body,
        media_section=media_section,
    )
    markdown_path.write_text(markdown_text, encoding="utf-8")
    return ArticleSourceArchiveResult(
        markdown_path=str(markdown_path),
        markdown_text=markdown_text,
        asset_paths=[str(archive_dir / item) for item in localizer.relative_paths],
        reused=False,
    )


def _archive_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    return Path(str(getattr(db, "_DATA_DIR", "data"))).expanduser().resolve() / "article-source-archive"


def _safe_segment(value: object, *, fallback: str = "item", max_length: int = 80) -> str:
    text = _FILENAME_SAFE_RE.sub("_", str(value or "").strip())
    text = re.sub(r"\s+", "-", text).strip(" ._-")
    return (text[:max_length].rstrip(" ._-") or fallback).lower()


def _source_id_segment(source_id: object, source_url: str, title: object) -> str:
    raw = str(source_id or "").strip()
    if raw:
        return _safe_segment(raw, fallback="item")
    key = source_url or str(title or "")
    digest = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"source-{digest}"


def _host_segment(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return _safe_segment(parsed.hostname, fallback="web")
    return "local"


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def _asset_extension(url: str, content_type: str = "") -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(mime) if mime else ""
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _MEDIA_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _default_downloader(url: str) -> tuple[bytes, str]:
    response = requests.get(
        url,
        headers={"User-Agent": "ytdlp-batch-downloader/article-source-archive"},
        timeout=ASSET_REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_ASSET_BYTES:
            raise RuntimeError("asset exceeds max archive size")
        chunks.append(chunk)
    return b"".join(chunks), response.headers.get("content-type", "")


class _AssetLocalizer:
    def __init__(self, asset_dir: Path, base_url: str, *, downloader: AssetDownloader | None = None):
        self.asset_dir = asset_dir
        self.base_url = base_url
        self.downloader = downloader or _default_downloader
        self._url_to_relative: dict[str, str] = {}
        self.relative_paths: list[str] = []

    def localize(self, raw_url: str, *, force: bool = False) -> str:
        url = urljoin(self.base_url, html.unescape(str(raw_url or "").strip()))
        if not _is_public_http_url(url):
            return raw_url
        if not force and not _looks_like_downloadable_media(url):
            return url
        if url in self._url_to_relative:
            return self._url_to_relative[url]
        try:
            content, content_type = self.downloader(url)
        except Exception:
            return url
        if not content:
            return url
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        target = self.asset_dir / f"asset-{len(self._url_to_relative) + 1:03d}{_asset_extension(url, content_type)}"
        target.write_bytes(content)
        relative = f"assets/{target.name}"
        self._url_to_relative[url] = relative
        self.relative_paths.append(relative)
        return relative


def _looks_like_downloadable_media(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in _MEDIA_EXTENSIONS


class _RichHtmlMarkdownConverter(HTMLParser):
    def __init__(self, *, base_url: str, localizer: _AssetLocalizer):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.localizer = localizer
        self.parts: list[str] = []
        self._link_stack: list[str] = []
        self._skip_depth = 0
        self._list_depth = 0

    def convert(self, value: str) -> str:
        self.feed(value or "")
        self.close()
        return _normalize_markdown_spacing("".join(self.parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "section", "article", "div", "blockquote"}:
            self._append("\n\n")
        elif tag in {"br"}:
            self._append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self._append("\n\n" + "#" * min(level, 6) + " ")
        elif tag in {"ul", "ol"}:
            self._list_depth += 1
            self._append("\n")
        elif tag == "li":
            self._append("\n- ")
        elif tag == "a":
            href = urljoin(self.base_url, html.unescape(attrs_dict.get("href", "").strip()))
            self._link_stack.append(href)
            self._append("[")
        elif tag == "img":
            src = attrs_dict.get("src") or attrs_dict.get("data-src") or ""
            alt = attrs_dict.get("alt") or "image"
            if src:
                local = self.localizer.localize(src, force=True)
                self._append(f"\n\n![{_escape_markdown_label(alt)}]({local})\n\n")
        elif tag in {"audio", "video", "source"}:
            src = attrs_dict.get("src") or ""
            if src:
                local = self.localizer.localize(src, force=True)
                label = "音频" if tag == "audio" else "视频"
                self._append(f"\n\n- [{label}]({local})\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            href = self._link_stack.pop() if self._link_stack else ""
            if _looks_like_downloadable_media(href):
                href = self.localizer.localize(href, force=True)
            self._append(f"]({href})" if href else "]")
        elif tag in {"p", "section", "article", "div", "blockquote", "li"}:
            self._append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._append("\n\n")
        elif tag in {"ul", "ol"} and self._list_depth:
            self._list_depth -= 1
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _WHITESPACE_RE.sub(" ", data or "")
        if text:
            self._append(text)

    def _append(self, value: str) -> None:
        self.parts.append(value)


def _escape_markdown_label(value: object) -> str:
    return str(value or "").replace("[", "\\[").replace("]", "\\]")


def _normalize_markdown_spacing(value: str) -> str:
    lines = [line.rstrip() for line in html.unescape(value or "").splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^\s+-\s+", "- ", text)
    return text.strip()


def _plain_compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _media_markdown(media: list[dict[str, Any]], localizer: _AssetLocalizer) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for item in media:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("src") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        mime_type = str(item.get("mime_type") or item.get("content_type") or "").lower()
        local = localizer.localize(url, force=True)
        if mime_type.startswith("image/") or _looks_like_image(url):
            lines.append(f"![media]({local})")
        else:
            label = "媒体文件"
            if mime_type.startswith("audio/"):
                label = "音频文件"
            elif mime_type.startswith("video/"):
                label = "视频文件"
            lines.append(f"- [{label}]({local})")
    return "\n".join(lines).strip()


def _looks_like_image(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg"}


def _build_source_markdown(
    *,
    source_type: str,
    title: str,
    source_url: str,
    body: str,
    media_section: str,
) -> str:
    lines = [f"# {title or 'Untitled Source'}", "", f"来源类型：{source_type}"]
    if source_url:
        lines.append(f"原始链接：{source_url}")
    lines.append("")
    if body:
        lines.append(body.strip())
        lines.append("")
    if media_section:
        lines.append("## 媒体资源")
        lines.append("")
        lines.append(media_section)
        lines.append("")
    return "\n".join(lines).strip() + "\n"

from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

from monitor.wechat_collect.errors import WechatArticleError, safe_error_message
from monitor.wechat_collect.models import ArticleDownload, SUPPORTED_EXPORT_FORMATS, is_valid_mp_article_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")
AUTHOR_BOUNDARY_CHARS = set('-_/|｜·•:：,，.。()（）【】[]{}<>《》"\'“”‘’')


def normalize_author_name(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))
    text = ZERO_WIDTH_RE.sub("", text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def author_match_key(value: str) -> str:
    return re.sub(r"[\s\-_/|｜·•:：,，.。()（）【】\[\]{}<>《》\"'“”‘’]+", "", normalize_author_name(value)).casefold()


def is_author_name_match(candidate: str, target: str) -> bool:
    candidate_key = author_match_key(candidate)
    target_key = author_match_key(target)
    if not candidate_key or not target_key:
        return False
    if candidate_key == target_key:
        return True
    candidate_name = normalize_author_name(candidate).casefold()
    target_name = normalize_author_name(target).casefold()
    return _has_author_boundary(candidate_name, target_name) or _has_author_boundary(target_name, candidate_name)


def _has_author_boundary(longer: str, shorter: str) -> bool:
    if not longer or not shorter or longer == shorter:
        return False
    if longer.startswith(shorter):
        suffix = longer[len(shorter):].lstrip()
        return bool(suffix) and suffix[0] in AUTHOR_BOUNDARY_CHARS
    if longer.endswith(shorter):
        prefix = longer[: -len(shorter)].rstrip()
        return bool(prefix) and prefix[-1] in AUTHOR_BOUNDARY_CHARS
    return False


def _strip_scripts(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", "", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", "", value, flags=re.I)
    return value


def _extract_title(value: str) -> str:
    for pattern in (
        r'<h1[^>]+id=["\']activity-name["\'][^>]*>([\s\S]*?)</h1>',
        r"<title[^>]*>([\s\S]*?)</title>",
    ):
        match = re.search(pattern, value, flags=re.I)
        if match:
            return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return ""


def _extract_author(value: str) -> str:
    for pattern in (
        r'id=["\']js_name["\'][^>]*>([\s\S]*?)</',
        r'<meta[^>]+(?:name|property)=["\'](?:author|og:article:author)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:author|og:article:author)["\']',
        r'\b(?:nickname|profile_nickname|author)\s*[:=]\s*["\']([^"\']+)["\']',
    ):
        match = re.search(pattern, value, flags=re.I)
        if match:
            author = normalize_author_name(match.group(1))
            if author:
                return author
    return ""


def extract_article_biz(url: str = "", raw_html: str = "") -> str:
    parsed = urlparse((url or "").strip())
    query = parse_qs(parsed.query)
    for key in ("__biz", "biz"):
        values = query.get(key) or []
        if values and values[0]:
            return unquote(values[0]).strip()
    for pattern in (
        r"\b__biz\s*=\s*['\"]([^'\"]+)['\"]",
        r"\bbiz\s*=\s*['\"]([^'\"]+)['\"]",
        r"['\"]__biz['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"(?:\?|&amp;|&)__biz=([^&'\"\s<>]+)",
    ):
        match = re.search(pattern, raw_html or "", flags=re.I)
        if match:
            return unquote(html.unescape(match.group(1))).strip()
    return ""


def _extract_js_article(value: str) -> str:
    match = re.search(r'<div[^>]+id=["\']js_article["\'][^>]*>([\s\S]*?)</div>\s*</body>', value, flags=re.I)
    if match:
        return match.group(0)
    content_match = re.search(r'<div[^>]+id=["\']js_content["\'][^>]*>([\s\S]*?)</div>', value, flags=re.I)
    return content_match.group(0) if content_match else value


def _normalize_images(value: str) -> str:
    return re.sub(
        r'(<img\b[^>]*?)\sdata-src=(["\'])([^"\']+)\2',
        lambda m: f'{m.group(1)} src="{html.escape(m.group(3), quote=True)}"',
        value,
        flags=re.I,
    )


def _text_from_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _markdown_from_html(value: str) -> str:
    text = _text_from_html(value)
    title = _extract_title(value)
    if title and not text.startswith(title):
        return f"# {title}\n\n{text}".strip()
    return text


def export_article_html(raw_html: str, export_format: str) -> ArticleDownload:
    fmt = (export_format or "html").strip().lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise WechatArticleError(f"不支持的导出格式: {export_format}")
    cleaned = _normalize_images(_strip_scripts(raw_html))
    article_html = _extract_js_article(cleaned)
    title = _extract_title(cleaned)
    author = _extract_author(cleaned)
    biz = extract_article_biz(raw_html=cleaned)
    metadata = {"title": title, "author": author, "biz": biz}
    if fmt == "html":
        body = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="referrer" content="no-referrer">'
            '<style>body{max-width:667px;margin:0 auto;padding:20px;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.6}img{max-width:100%}</style>'
            "</head><body>"
            + article_html
            + "</body></html>"
        ).encode("utf-8")
        return ArticleDownload(body=body, content_type="text/html; charset=utf-8", title=title, metadata=metadata)
    if fmt == "text":
        return ArticleDownload(body=_text_from_html(article_html).encode("utf-8"), content_type="text/plain; charset=utf-8", title=title, metadata=metadata)
    if fmt == "markdown":
        return ArticleDownload(body=_markdown_from_html(article_html).encode("utf-8"), content_type="text/markdown; charset=utf-8", title=title, metadata=metadata)
    payload = {"title": title, "author": author, "biz": biz, "text": _text_from_html(article_html), "html": article_html}
    return ArticleDownload(
        body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json; charset=utf-8",
        title=title,
        metadata=payload,
    )


def download_article(
    url: str,
    export_format: str,
    *,
    http_session=None,
    timeout: int = 30,
    proxies: dict[str, str] | None = None,
) -> ArticleDownload:
    if not is_valid_mp_article_url(url):
        raise WechatArticleError("文章链接不合法")
    http = http_session or requests.Session()
    try:
        resp = http.get(
            url,
            headers={"Referer": "https://mp.weixin.qq.com/", "Origin": "https://mp.weixin.qq.com", "User-Agent": USER_AGENT},
            timeout=timeout,
            proxies=proxies,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise WechatArticleError(f"文章下载失败: {safe_error_message(exc)}") from exc
    result = export_article_html(resp.text, export_format)
    if not result.metadata.get("biz"):
        result.metadata["biz"] = extract_article_biz(url=url, raw_html=resp.text)
    return result

from __future__ import annotations

import os
import html
import ipaddress
import mimetypes
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from monitor.db.queries import wechat_collect as queries
from monitor.wechat_collect.errors import WechatTaskError, safe_error_message
from monitor.wechat_collect.models import SUPPORTED_EXPORT_FORMATS, is_valid_mp_article_url, normalize_mp_article_url
from monitor.wechat_collect.providers import NativeMpProvider
from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan
from monitor.wechat_collect.serializers import public_task

FILENAME_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
HTML_IMAGE_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])(https?://[^"\']+)(\2)', re.IGNORECASE)
ASSET_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)
ASSET_REQUEST_TIMEOUT = (10, 60)
ASSET_DOWNLOAD_ATTEMPTS = 3
ASSET_RETRY_BACKOFF_SECONDS = 0.5
ASSET_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def sanitize_filename(value: str, *, fallback: str = "article", max_length: int = 90) -> str:
    safe = FILENAME_SAFE_RE.sub("_", (value or "").strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        safe = fallback
    return safe[:max_length].rstrip(" .") or fallback


def resolve_output_dir(requested: str | None, configured_root: str) -> str:
    root = Path(configured_root).expanduser().resolve()
    target = Path(requested).expanduser().resolve() if requested else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WechatTaskError("输出路径必须位于配置的公众号采集目录下") from exc
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def unique_output_path(output_dir: Path, base: str, extension: str, used: set[str]) -> Path:
    existing = {path.name.lower() for path in output_dir.iterdir() if path.is_file()}
    filename = f"{base}.{extension}"
    suffix = 2
    while filename.lower() in used or filename.lower() in existing:
        filename = f"{base}-{suffix}.{extension}"
        suffix += 1
    used.add(filename.lower())
    return output_dir / filename


def _is_public_http_asset_url(value: str) -> bool:
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
    parsed = urlparse(url)
    wx_fmt = (parse_qs(parsed.query).get("wx_fmt") or [""])[0].lower()
    if wx_fmt in {"jpg", "jpeg", "png", "gif", "webp"}:
        return ".jpg" if wx_fmt == "jpeg" else f".{wx_fmt}"
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(mime) if mime else ""
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _is_retryable_asset_error(exc: requests.RequestException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return isinstance(exc, requests.HTTPError) and status_code in ASSET_RETRY_STATUS_CODES


def _download_asset(url: str, asset_dir: Path, index: int, session, *, referer: str = "") -> str | None:
    normalized_url = html.unescape((url or "").strip())
    if not _is_public_http_asset_url(normalized_url):
        return None
    response = None
    for attempt in range(1, ASSET_DOWNLOAD_ATTEMPTS + 1):
        try:
            response = session.get(
                normalized_url,
                headers={
                    "User-Agent": ASSET_USER_AGENT,
                    "Referer": referer or "https://mp.weixin.qq.com/",
                },
                timeout=ASSET_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt >= ASSET_DOWNLOAD_ATTEMPTS or not _is_retryable_asset_error(exc):
                return None
            if ASSET_RETRY_BACKOFF_SECONDS > 0:
                time.sleep(ASSET_RETRY_BACKOFF_SECONDS * attempt)
    if response is None:
        return None
    extension = _asset_extension(normalized_url, response.headers.get("content-type", ""))
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / f"image-{index}{extension}"
    target.write_bytes(response.content)
    return target.name


def _localize_article_assets(body: bytes, content_type: str, out_path: Path, metadata: dict) -> bytes:
    if not metadata.get("localize_assets"):
        return body
    lowered = (content_type or "").lower()
    if "markdown" not in lowered and "html" not in lowered:
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    asset_dir = out_path.parent / f"{out_path.stem}_assets"
    session = requests.Session()
    source_url = str(metadata.get("source_url") or "")
    url_to_relpath: dict[str, str] = {}

    def local_path_for(url: str) -> str | None:
        normalized_url = html.unescape((url or "").strip())
        if normalized_url in url_to_relpath:
            return url_to_relpath[normalized_url]
        filename = _download_asset(normalized_url, asset_dir, len(url_to_relpath) + 1, session, referer=source_url)
        if not filename:
            return None
        relpath = f"{asset_dir.name}/{filename}"
        url_to_relpath[normalized_url] = relpath
        return relpath

    if "markdown" in lowered:
        def replace_markdown_image(match: re.Match) -> str:
            local = local_path_for(match.group(2))
            if not local:
                return match.group(0)
            return f"![{match.group(1)}]({local})"

        text = MARKDOWN_IMAGE_RE.sub(replace_markdown_image, text)
    else:
        def replace_html_image(match: re.Match) -> str:
            local = local_path_for(match.group(3))
            if not local:
                return match.group(0)
            return f"{match.group(1)}{match.group(2)}{local}{match.group(4)}"

        text = HTML_IMAGE_SRC_RE.sub(replace_html_image, text)
    return text.encode("utf-8")


def _selected_article_from_url_entry(entry, index: int) -> dict | None:
    now = int(time.time())
    if isinstance(entry, dict):
        url = normalize_mp_article_url(entry.get("link") or entry.get("url") or "")
        if not url:
            return None
        article = {
            "aid": str(entry.get("aid") or ""),
            "title": str(entry.get("title") or "").strip() or f"article-{index}",
            "link": url,
            "url": url,
            "digest": str(entry.get("digest") or ""),
            "cover": str(entry.get("cover") or entry.get("cover_img") or ""),
            "author_name": str(entry.get("author_name") or ""),
            "update_time": entry.get("update_time") or entry.get("create_time") or now,
            "create_time": entry.get("create_time") or entry.get("update_time") or 0,
        }
        return article
    url = normalize_mp_article_url(entry)
    if not url:
        return None
    return {"title": f"article-{index}", "link": url, "url": url, "update_time": now, "create_time": 0}


def _raw_url_from_url_entry(entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("link") or entry.get("url") or "").strip()
    return str(entry).strip()


class NativeCollectionTaskService:
    def __init__(self, *, provider_factory=None):
        self.provider_factory = provider_factory or self._default_provider_factory

    def _default_provider_factory(self, payload: dict):
        proxy_context = {
            key: value
            for key, value in {
                "fakeid": payload.get("fakeid"),
                "nickname": payload.get("account_name"),
            }.items()
            if value
        }
        proxy_plan = resolve_native_proxy_plan(proxy_context, cookies_present=True)
        return NativeMpProvider(session_id=payload.get("session_id") or "", proxy_plan=proxy_plan)

    def create_task(self, payload: dict, *, output_dir: str) -> str:
        task_id = f"wcn_{uuid.uuid4().hex[:12]}"
        queries.create_task(payload, task_id=task_id, output_dir=output_dir)
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        task = queries.get_task(task_id)
        return public_task(task) if task else None

    def list_tasks(self) -> list[dict]:
        return [public_task(task) for task in queries.list_tasks(provider="native")]

    def request_cancel(self, task_id: str) -> bool:
        return queries.request_cancel(task_id)

    def resolve_artifact_path(self, artifact_id: str) -> str:
        raw = (artifact_id or "").strip()
        if ":" not in raw:
            raise WechatTaskError("公众号采集结果标识无效")
        task_id, index_raw = raw.split(":", 1)
        try:
            index = int(index_raw)
        except ValueError as exc:
            raise WechatTaskError("公众号采集结果标识无效") from exc
        if index < 1:
            raise WechatTaskError("公众号采集结果标识无效")
        task = queries.get_task(task_id)
        if not task:
            raise WechatTaskError("公众号采集任务不存在")
        results = task.get("results") or []
        if index > len(results):
            raise WechatTaskError("公众号采集结果不存在")
        result = results[index - 1]
        if result.get("status") != "success" or not result.get("path"):
            raise WechatTaskError("公众号采集结果不可用")
        return str(Path(result["path"]).expanduser().resolve())

    def start_background(self, task_id: str) -> None:
        thread = threading.Thread(target=self.run_task, args=(task_id,), name=f"wechat-native-{task_id}", daemon=True)
        thread.start()

    def _finished_at(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _is_cancelled(self, task_id: str) -> bool:
        latest = queries.get_task(task_id)
        return bool(latest and latest.get("cancel_requested"))

    def _cancel_if_requested(self, task_id: str) -> bool:
        if not self._is_cancelled(task_id):
            return False
        queries.update_task(
            task_id,
            status="cancelled",
            current="已取消",
            finished_at=self._finished_at(),
        )
        return True

    def _sleep_with_cancel(self, task_id: str, delay_seconds: float) -> None:
        deadline = time.time() + delay_seconds
        while True:
            if self._cancel_if_requested(task_id):
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def run_task(self, task_id: str) -> None:
        task = queries.get_task(task_id)
        if not task:
            return
        if self._cancel_if_requested(task_id):
            return
        queries.update_task(task_id, status="running", current="正在启动")
        try:
            if self._cancel_if_requested(task_id):
                return
            payload = {
                "provider": "native",
                "session_id": task.get("session_id"),
                "source_mode": task.get("source_mode"),
                "fakeid": task.get("fakeid"),
                "article_url": task.get("article_url"),
                "account_name": task.get("account_name"),
                "urls": task.get("urls") or [],
                "keyword": task.get("keyword") or "",
                "format": task.get("export_format") or "markdown",
            }
            if self._cancel_if_requested(task_id):
                return
            provider = self.provider_factory(payload)
            if self._cancel_if_requested(task_id):
                return
            articles, account = self._resolve_articles(provider, task)
            if self._cancel_if_requested(task_id):
                return
            queries.update_task(task_id, total=len(articles), current=f"已获取 {len(articles)} 篇文章")
            if not articles:
                raise WechatTaskError("没有获取到可导出的文章")
            self._download_articles(task_id, provider, task, articles, account)
            latest = queries.get_task(task_id)
            finished_at = self._finished_at()
            if latest and (latest.get("cancel_requested") or latest.get("status") == "cancelled"):
                queries.update_task(task_id, status="cancelled", current="已取消", finished_at=finished_at)
            elif latest and int(latest.get("success") or 0) == 0 and int(latest.get("failed") or 0) > 0:
                queries.update_task(
                    task_id,
                    status="error",
                    error="全部文章导出失败",
                    current="采集失败",
                    finished_at=finished_at,
                )
            else:
                queries.update_task(task_id, status="done", current="采集完成", finished_at=finished_at)
        except Exception as exc:
            queries.update_task(
                task_id,
                status="error",
                error=safe_error_message(exc),
                current="采集失败",
                finished_at=self._finished_at(),
            )

    def _resolve_articles(self, provider, task: dict) -> tuple[list[dict], dict]:
        raw_urls = task.get("urls") or []
        if raw_urls and not isinstance(raw_urls, list):
            raise WechatTaskError("urls 必须是文章链接数组")
        max_articles = max(1, min(int(task.get("max_articles") or 50), 1000))
        for entry in raw_urls[:max_articles]:
            raw_url = _raw_url_from_url_entry(entry)
            if raw_url and not normalize_mp_article_url(raw_url):
                raise WechatTaskError("文章链接不合法")
        selected_articles = [
            article
            for idx, entry in enumerate(raw_urls[:max_articles], start=1)
            if (article := _selected_article_from_url_entry(entry, idx))
        ]
        if selected_articles:
            for article in selected_articles:
                if not is_valid_mp_article_url(article.get("link") or article.get("url") or ""):
                    raise WechatTaskError("文章链接不合法")
            return selected_articles[:max_articles], {}
        if (task.get("source_mode") or "") == "urls":
            raise WechatTaskError("urls 至少提供一个合法文章链接")
        if (task.get("source_mode") or "") == "url" and task.get("article_url"):
            article_url = normalize_mp_article_url(task.get("article_url") or "")
            if not is_valid_mp_article_url(article_url):
                raise WechatTaskError("文章链接不合法")
            task = {**task, "article_url": article_url}
        fakeid = task.get("fakeid") or ""
        account = {}
        if not fakeid:
            account = provider.account_by_article_url(task.get("article_url") or "")
            fakeid = account.get("fakeid") or ""
            if not fakeid:
                raise WechatTaskError("无法解析公众号 fakeid")
        elif task.get("account_name"):
            account = {"fakeid": fakeid, "nickname": task.get("account_name") or ""}
        def report_progress(current: str) -> bool:
            queries.update_task(task["task_id"], current=current)
            return not self._is_cancelled(task["task_id"])

        articles = provider.list_articles(
            fakeid,
            keyword=task.get("keyword") or "",
            max_articles=max_articles,
            page_size=max(1, min(int(task.get("page_size") or 20), 20)),
            begin=0,
            progress=report_progress,
            cancel_check=lambda: self._is_cancelled(task["task_id"]),
        )
        queries.upsert_account(account or {"fakeid": fakeid})
        for article in articles:
            queries.upsert_article(fakeid, article)
        return articles, account

    def _download_articles(self, task_id: str, provider, task: dict, articles: list[dict], account: dict) -> None:
        fmt = task.get("export_format") or "markdown"
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            raise WechatTaskError(f"不支持的导出格式: {fmt}")
        extension = SUPPORTED_EXPORT_FORMATS[fmt]
        output_dir = Path(task.get("output_dir") or os.getcwd())
        output_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        delay_seconds = max(0.0, min(float(task.get("delay_seconds") or 0.0), 30.0))
        fakeid = task.get("fakeid") or account.get("fakeid") or ""
        for idx, article in enumerate(articles, start=1):
            if self._cancel_if_requested(task_id):
                return
            url = normalize_mp_article_url(article.get("link") or article.get("url") or "")
            title = article.get("title") or f"article-{idx}"
            update_time = int(article.get("update_time") or article.get("create_time") or time.time())
            date_part = datetime.fromtimestamp(update_time).strftime("%Y%m%d")
            base = sanitize_filename(f"{date_part}-{title}", fallback=f"article-{idx}")
            out_path = unique_output_path(output_dir, base, extension, used)
            try:
                queries.update_task(task_id, current=f"正在导出 {idx}/{len(articles)}: {title}")
                downloaded = provider.download_article(url, fmt)
                body = _localize_article_assets(
                    downloaded.body,
                    downloaded.content_type,
                    out_path,
                    downloaded.metadata or {},
                )
                out_path.write_bytes(body)
                if fakeid:
                    queries.upsert_article(fakeid, article, local_path=str(out_path), export_format=fmt, status="downloaded")
                queries.append_task_result(
                    task_id,
                    {
                        "status": "success",
                        "title": downloaded.title or title,
                        "url": url,
                        "path": str(out_path),
                        "content_type": downloaded.content_type,
                    },
                )
            except Exception as exc:
                queries.append_task_result(
                    task_id,
                    {"status": "failed", "title": title, "url": url, "error": safe_error_message(exc)},
                )
            if delay_seconds and idx < len(articles):
                self._sleep_with_cancel(task_id, delay_seconds)
                if self._is_cancelled(task_id):
                    return

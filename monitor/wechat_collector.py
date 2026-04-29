"""WeChat article collection via wechat-article-exporter public API.

The integration is intentionally dependency-free so the monitor server can keep
using the standard-library HTTP stack.  It supports the public hosted service
and private deployments by making the base URL configurable.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_EXPORTER_BASE_URL = "https://down.mptext.top"
SUPPORTED_EXPORT_FORMATS = {
    "html": "html",
    "markdown": "md",
    "text": "txt",
    "json": "json",
}

_ARTICLE_URL_RE = re.compile(r"^https://mp\.weixin\.qq\.com/s[/\?]", re.IGNORECASE)
_FILENAME_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class WechatCollectionError(RuntimeError):
    """Raised when the upstream exporter or collection workflow fails."""


@dataclass
class HttpPayload:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], int], HttpPayload]


def normalize_exporter_base_url(value: str | None) -> str:
    """Return a normalized base URL for a hosted or self-hosted exporter."""
    base = (value or DEFAULT_EXPORTER_BASE_URL).strip().rstrip("/")
    if not base:
        base = DEFAULT_EXPORTER_BASE_URL
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WechatCollectionError("wechat_exporter_base_url 必须是 http(s) URL")
    return base


def sanitize_filename(value: str, *, fallback: str = "article", max_length: int = 90) -> str:
    """Make a Windows-safe, readable filename segment."""
    safe = _FILENAME_SAFE_RE.sub("_", (value or "").strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        safe = fallback
    return safe[:max_length].rstrip(" .") or fallback


def is_valid_mp_article_url(value: str) -> bool:
    return _ARTICLE_URL_RE.match((value or "").strip()) is not None


class WechatExporterClient:
    """Small client for wechat-article-exporter public API endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_key: str | None = None,
        timeout: int = 30,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = normalize_exporter_base_url(base_url)
        self.auth_key = (auth_key or "").strip()
        self.timeout = max(3, int(timeout or 30))
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "*/*",
            "User-Agent": "ytdlp-batch-downloader/wechat-collector",
        }
        if self.auth_key:
            headers["X-Auth-Key"] = self.auth_key
        return headers

    def _build_url(self, path: str, params: dict | None = None) -> str:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        if params:
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"
        return url

    def _fetch(self, path: str, params: dict | None = None) -> HttpPayload:
        url = self._build_url(path, params)
        headers = self._headers()
        if self._transport:
            return self._transport(url, headers, self.timeout)
        req = Request(url, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                return HttpPayload(
                    status=int(getattr(resp, "status", 200)),
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    body=resp.read(),
                )
        except HTTPError as exc:
            body = exc.read()
            raise WechatCollectionError(f"导出服务 HTTP {exc.code}: {body[:200]!r}") from exc
        except URLError as exc:
            raise WechatCollectionError(f"无法连接导出服务: {exc.reason}") from exc

    @staticmethod
    def _check_response_payload(data) -> None:
        if not isinstance(data, dict):
            return
        base_resp = data.get("base_resp")
        if isinstance(base_resp, dict) and int(base_resp.get("ret", 0) or 0) != 0:
            raise WechatCollectionError(str(base_resp.get("err_msg") or "导出服务返回错误"))
        if int(data.get("code", 0) or 0) < 0:
            raise WechatCollectionError(str(data.get("msg") or "导出服务返回错误"))

    def _fetch_json(self, path: str, params: dict | None = None) -> dict:
        payload = self._fetch(path, params)
        try:
            data = json.loads(payload.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WechatCollectionError("导出服务未返回 JSON") from exc
        self._check_response_payload(data)
        return data

    def verify_auth_key(self) -> dict:
        """Validate X-Auth-Key against the exporter instance."""
        if not self.auth_key:
            raise WechatCollectionError("wechat_exporter_auth_key 未配置")
        return self._fetch_json("/api/public/v1/authkey")

    def account_by_article_url(self, article_url: str) -> dict:
        if not self.auth_key:
            raise WechatCollectionError("采集公众号列表需要配置 wechat_exporter_auth_key")
        if not is_valid_mp_article_url(article_url):
            raise WechatCollectionError("请输入有效的 mp.weixin.qq.com/s?... 文章链接")
        data = self._fetch_json("/api/public/v1/accountbyurl", {"url": article_url})
        accounts = data.get("list") or []
        if not accounts:
            raise WechatCollectionError(str(data.get("resolved_name") or "未识别到公众号"))
        return accounts[0]

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 5,
        progress: Callable[[str], None] | None = None,
    ) -> list[dict]:
        if not self.auth_key:
            raise WechatCollectionError("采集公众号文章列表需要配置 wechat_exporter_auth_key")
        fakeid = (fakeid or "").strip()
        if not fakeid:
            raise WechatCollectionError("fakeid 不能为空")
        max_articles = max(1, min(int(max_articles or 50), 1000))
        page_size = max(1, min(int(page_size or 5), 20))
        begin = 0
        articles: list[dict] = []
        seen_links: set[str] = set()

        while len(articles) < max_articles:
            if progress:
                progress(f"正在获取文章列表 offset={begin}")
            data = self._fetch_json(
                "/api/public/v1/article",
                {
                    "fakeid": fakeid,
                    "begin": begin,
                    "size": page_size,
                    "keyword": keyword,
                },
            )
            page_articles = data.get("articles") or []
            if not isinstance(page_articles, list) or not page_articles:
                break
            for item in page_articles:
                link = str(item.get("link") or item.get("url") or "").strip()
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                articles.append(item)
                if len(articles) >= max_articles:
                    break
            if len(page_articles) < page_size:
                break
            begin += page_size

        return articles

    def download_article(self, article_url: str, export_format: str) -> tuple[bytes, str]:
        fmt = (export_format or "markdown").strip().lower()
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            raise WechatCollectionError(f"不支持的导出格式: {export_format}")
        if not is_valid_mp_article_url(article_url):
            raise WechatCollectionError("文章链接不合法")
        payload = self._fetch(
            "/api/public/v1/download",
            {"url": article_url, "format": fmt},
        )
        content_type = payload.headers.get("content-type", "")
        if "json" in content_type.lower():
            try:
                data = json.loads(payload.body.decode("utf-8"))
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                self._check_response_payload(data)
        return payload.body, content_type


class WechatCollectionTaskManager:
    """In-memory task manager for the local monitor process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def create_task(self, payload: dict, output_dir: str) -> str:
        task_id = uuid.uuid4().hex[:12]
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        task = {
            "task_id": task_id,
            "status": "running",
            "total": 0,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current": "等待启动",
            "account": {},
            "payload": dict(payload or {}),
            "output_dir": output_dir,
            "results": [],
            "cancel_requested": False,
            "created_at": now,
            "finished_at": None,
            "error": "",
        }
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return sorted(
                [self._public_snapshot(task, include_results=False) for task in self._tasks.values()],
                key=lambda item: item.get("created_at") or "",
                reverse=True,
            )

    def get_task(self, task_id: str, *, include_results: bool = True) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return self._public_snapshot(task, include_results=include_results) if task else None

    def set_total(self, task_id: str, total: int, account: dict | None = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["total"] = int(total)
            if account:
                task["account"] = dict(account)

    def update_current(self, task_id: str, current: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["current"] = current

    def add_result(self, task_id: str, result: dict) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["results"].append(dict(result))
            task["completed"] = len(task["results"])
            if result.get("status") == "success":
                task["success"] += 1
            else:
                task["failed"] += 1
            task["current"] = result.get("title") or result.get("url") or task.get("current", "")

    def finish(self, task_id: str, *, error: str = "", cancelled: bool = False) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "cancelled" if cancelled else "error" if error else "done"
            task["error"] = error
            task["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    def request_cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.get("status") not in {"running"}:
                return False
            task["cancel_requested"] = True
            task["current"] = "正在取消"
            return True

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task.get("cancel_requested"))

    @staticmethod
    def _public_snapshot(task: dict | None, *, include_results: bool) -> dict:
        if not task:
            return {}
        payload = {
            "task_id": task.get("task_id"),
            "status": task.get("status"),
            "total": task.get("total", 0),
            "completed": task.get("completed", 0),
            "success": task.get("success", 0),
            "failed": task.get("failed", 0),
            "current": task.get("current", ""),
            "account": task.get("account") or {},
            "output_dir": task.get("output_dir", ""),
            "cancel_requested": bool(task.get("cancel_requested")),
            "created_at": task.get("created_at"),
            "finished_at": task.get("finished_at"),
            "error": task.get("error", ""),
        }
        if include_results:
            payload["results"] = list(task.get("results") or [])
        return payload


def default_collection_output_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "wechat-articles")


def resolve_collection_output_dir(requested: str | None, configured_root: str) -> str:
    root = Path(configured_root).expanduser().resolve()
    target = Path(requested).expanduser().resolve() if requested else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WechatCollectionError("输出路径必须位于 wechat_collection_output_dir 下") from exc
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def run_collection(
    *,
    task_id: str,
    task_manager: WechatCollectionTaskManager,
    client: WechatExporterClient,
    output_dir: str,
    payload: dict,
) -> None:
    """Run a collection task synchronously; intended for a background thread."""
    fmt = str(payload.get("format") or "markdown").strip().lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise WechatCollectionError(f"不支持的导出格式: {fmt}")
    delay_seconds = max(0.0, min(float(payload.get("delay_seconds", 1.0) or 0.0), 30.0))
    max_articles = max(1, min(int(payload.get("max_articles", 50) or 50), 1000))
    keyword = str(payload.get("keyword") or "").strip()
    page_size = max(1, min(int(payload.get("page_size", 5) or 5), 20))
    provided_urls = [
        str(url).strip()
        for url in (payload.get("urls") or [])
        if str(url).strip()
    ]

    account: dict = {}
    if provided_urls:
        articles = [
            {
                "title": f"article-{idx}",
                "link": url,
                "update_time": int(time.time()),
            }
            for idx, url in enumerate(provided_urls[:max_articles], start=1)
        ]
    else:
        fakeid = str(payload.get("fakeid") or "").strip()
        article_url = str(payload.get("article_url") or "").strip()
        if not fakeid:
            task_manager.update_current(task_id, "正在从文章链接识别公众号")
            account = client.account_by_article_url(article_url)
            fakeid = str(account.get("fakeid") or "").strip()
        else:
            account = {
                "fakeid": fakeid,
                "nickname": str(payload.get("account_name") or fakeid),
            }
        articles = client.list_articles(
            fakeid,
            keyword=keyword,
            max_articles=max_articles,
            page_size=page_size,
            progress=lambda current: task_manager.update_current(task_id, current),
        )

    task_manager.set_total(task_id, len(articles), account)
    if not articles:
        raise WechatCollectionError("没有获取到可导出的文章")

    used_names: set[str] = set()
    extension = SUPPORTED_EXPORT_FORMATS[fmt]
    for idx, article in enumerate(articles, start=1):
        if task_manager.is_cancel_requested(task_id):
            task_manager.finish(task_id, cancelled=True)
            return

        url = str(article.get("link") or article.get("url") or "").strip()
        title = str(article.get("title") or f"article-{idx}").strip()
        update_time = int(article.get("update_time") or article.get("create_time") or time.time())
        date_part = datetime.fromtimestamp(update_time).strftime("%Y%m%d")
        name_base = sanitize_filename(f"{date_part}-{title}", fallback=f"article-{idx}")
        filename = f"{name_base}.{extension}"
        suffix = 2
        while filename.lower() in used_names:
            filename = f"{name_base}-{suffix}.{extension}"
            suffix += 1
        used_names.add(filename.lower())
        out_path = Path(output_dir) / filename

        try:
            task_manager.update_current(task_id, f"正在导出 {idx}/{len(articles)}: {title}")
            body, content_type = client.download_article(url, fmt)
            out_path.write_bytes(body)
            task_manager.add_result(
                task_id,
                {
                    "status": "success",
                    "title": title,
                    "url": url,
                    "path": str(out_path),
                    "content_type": content_type,
                },
            )
        except Exception as exc:  # keep the batch going
            task_manager.add_result(
                task_id,
                {
                    "status": "failed",
                    "title": title,
                    "url": url,
                    "error": str(exc),
                },
            )
        if delay_seconds and idx < len(articles):
            time.sleep(delay_seconds)

    task_manager.finish(task_id)

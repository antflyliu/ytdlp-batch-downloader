from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from monitor.db.queries import wechat_collect as queries
from monitor.wechat_collect.errors import WechatTaskError, safe_error_message
from monitor.wechat_collect.models import SUPPORTED_EXPORT_FORMATS, is_valid_mp_article_url
from monitor.wechat_collect.providers import NativeMpProvider
from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan
from monitor.wechat_collect.serializers import public_task

FILENAME_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


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
        urls = [str(url).strip() for url in raw_urls if str(url).strip()]
        max_articles = max(1, min(int(task.get("max_articles") or 50), 1000))
        if urls:
            for url in urls[:max_articles]:
                if not is_valid_mp_article_url(url):
                    raise WechatTaskError("文章链接不合法")
            return [
                {"title": f"article-{idx}", "link": url, "update_time": int(time.time())}
                for idx, url in enumerate(urls[:max_articles], start=1)
            ], {}
        if (task.get("source_mode") or "") == "urls":
            raise WechatTaskError("urls 至少提供一个合法文章链接")
        if (task.get("source_mode") or "") == "url" and task.get("article_url"):
            article_url = str(task.get("article_url") or "").strip()
            if not is_valid_mp_article_url(article_url):
                raise WechatTaskError("文章链接不合法")
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
            url = article.get("link") or article.get("url") or ""
            title = article.get("title") or f"article-{idx}"
            update_time = int(article.get("update_time") or article.get("create_time") or time.time())
            date_part = datetime.fromtimestamp(update_time).strftime("%Y%m%d")
            base = sanitize_filename(f"{date_part}-{title}", fallback=f"article-{idx}")
            out_path = unique_output_path(output_dir, base, extension, used)
            try:
                queries.update_task(task_id, current=f"正在导出 {idx}/{len(articles)}: {title}")
                downloaded = provider.download_article(url, fmt)
                out_path.write_bytes(downloaded.body)
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

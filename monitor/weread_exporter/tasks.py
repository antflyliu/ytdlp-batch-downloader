from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
import re
from typing import Callable
from urllib.parse import quote

from monitor.db.queries import weread_exporter as queries
from monitor.weread_exporter.core import (
    BROWSER_MODE_AUTO,
    BROWSER_MODE_PERSISTENT,
    DEFAULT_CHROME_CDP_INITIAL_URL,
    WeReadExportError,
    WeReadPlaywrightRunner,
    chrome_cdp_available,
    configured_browser_mode,
    configured_chrome_cdp_endpoint,
    ensure_chrome_cdp_with_options,
    find_chrome_executable,
    parse_book_id,
    playwright_available,
)

BOOK_ID_RE = re.compile(r"^[0-9A-Za-z]{16,64}$")


def default_output_root(data_dir: str) -> str:
    return str((Path(data_dir) / "weread_exports").resolve())


def default_cache_dir(data_dir: str) -> str:
    return str((Path(data_dir) / "weread_browser_profile").resolve())


def default_cdp_profile_dir(data_dir: str) -> str:
    return str((Path(data_dir) / "weread_chrome_cdp_profile").resolve())


def resolve_output_dir(requested: str | None, configured_root: str) -> str:
    root = Path(configured_root).expanduser().resolve()
    text = (requested or "").strip()
    target = (root / text).resolve() if text and not Path(text).is_absolute() else Path(text or root).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("输出路径必须位于微信读书导出目录下") from exc
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def public_task(task: dict | None) -> dict:
    if not task:
        return {}
    task_id = str(task.get("task_id") or "")
    results = []
    for index, item in enumerate(task.get("results") or [], start=1):
        result = {
            "kind": item.get("kind") or "",
            "status": item.get("status") or "",
            "title": item.get("title") or "",
            "path": item.get("path") or "",
            "error": item.get("error") or "",
            "pages": item.get("pages") or 0,
            "chars": item.get("chars") or 0,
            "content_type": item.get("content_type") or "",
        }
        if result["path"] and result["status"] in {"success", "skipped"}:
            artifact_id = f"{task_id}:{index}"
            result["artifact_id"] = artifact_id
            result["artifact_name"] = Path(str(result["path"])).name
            result["artifact_url"] = f"/api/weread-exporter/artifacts/{quote(artifact_id, safe='')}"
        results.append(result)
    return {
        "task_id": task_id,
        "book_id": task.get("book_id") or "",
        "book_input": task.get("book_input") or "",
        "title": task.get("title") or "",
        "author": task.get("author") or "",
        "output_dir": task.get("output_dir") or "",
        "cache_dir": task.get("cache_dir") or "",
        "save_raw": bool(task.get("save_raw")),
        "status": task.get("status") or "",
        "total": task.get("total") or 0,
        "completed": task.get("completed") or 0,
        "success": task.get("success") or 0,
        "failed": task.get("failed") or 0,
        "skipped": task.get("skipped") or 0,
        "current": task.get("current") or "",
        "error": task.get("error") or "",
        "cancel_requested": bool(task.get("cancel_requested")),
        "created_at": task.get("created_at") or "",
        "updated_at": task.get("updated_at") or "",
        "finished_at": task.get("finished_at") or "",
        "results": results,
        "meta": task.get("meta") or {},
    }


class WeReadExportTaskService:
    def __init__(
        self,
        *,
        runner_factory: Callable[..., WeReadPlaywrightRunner] | None = None,
        lock_wait_timeout: float = 60,
    ):
        self.runner_factory = runner_factory or WeReadPlaywrightRunner
        self.lock_wait_timeout = max(0, float(lock_wait_timeout))
        self._run_lock = threading.Lock()

    def config(self, *, data_dir: str) -> dict:
        endpoint = configured_chrome_cdp_endpoint()
        return {
            "playwright_installed": playwright_available(),
            "output_root": default_output_root(data_dir),
            "cache_dir": default_cache_dir(data_dir),
            "requires_visible_browser": True,
            "browser_mode": configured_browser_mode(),
            "browser_mode_default": BROWSER_MODE_AUTO,
            "chrome_cdp_endpoint": endpoint,
            "chrome_cdp_available": chrome_cdp_available(endpoint),
            "chrome_cdp_launchable": find_chrome_executable() is not None,
            "chrome_cdp_profile_dir": default_cdp_profile_dir(data_dir),
            "source_project": "antflyliu/weread-exporter",
            "supported_formats": ["markdown"],
        }

    def start_chrome_cdp(
        self,
        *,
        data_dir: str,
        endpoint: str | None = None,
        profile_dir: str | None = None,
        initial_url: str = DEFAULT_CHROME_CDP_INITIAL_URL,
    ) -> dict:
        result = ensure_chrome_cdp_with_options(
            data_dir=data_dir,
            endpoint=endpoint,
            profile_dir=profile_dir,
            initial_url=initial_url,
        )
        return {
            **result,
            "chrome_cdp_available": chrome_cdp_available(result.get("endpoint") or endpoint or configured_chrome_cdp_endpoint()),
            "chrome_cdp_endpoint": result.get("endpoint") or endpoint or configured_chrome_cdp_endpoint(),
            "chrome_cdp_profile_dir": result.get("profile_dir") or profile_dir or default_cdp_profile_dir(data_dir),
        }

    def create_task(self, payload: dict, *, data_dir: str) -> str:
        book_input = str(payload.get("book") or payload.get("book_input") or payload.get("book_id") or "").strip()
        book_id = parse_book_id(book_input)
        if not book_id:
            raise ValueError("微信读书 book URL 或 book_id 不能为空")
        if not BOOK_ID_RE.fullmatch(book_id):
            raise ValueError("微信读书 book_id 格式无效")
        output_root = default_output_root(data_dir)
        output_dir = resolve_output_dir(payload.get("output_dir"), output_root)
        cache_dir = default_cache_dir(data_dir)
        cdp_endpoint = str(payload.get("chrome_cdp_endpoint") or configured_chrome_cdp_endpoint()).strip().rstrip("/")
        cdp_profile_dir = str(payload.get("chrome_cdp_profile_dir") or default_cdp_profile_dir(data_dir)).strip()
        task_id = f"wrd_{uuid.uuid4().hex[:12]}"
        queries.create_task(
            {
                **payload,
                "book_id": book_id,
                "book_input": book_input,
                "save_raw": payload.get("save_raw", True),
                "meta": {
                    "chrome_cdp_endpoint": cdp_endpoint,
                    "chrome_cdp_profile_dir": cdp_profile_dir,
                },
            },
            task_id=task_id,
            output_dir=output_dir,
            cache_dir=cache_dir,
        )
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        task = queries.get_task(task_id)
        return public_task(task) if task else None

    def list_tasks(self) -> list[dict]:
        return [public_task(task) for task in queries.list_tasks()]

    def request_cancel(self, task_id: str) -> bool:
        return queries.request_cancel(task_id)

    def start_background(self, task_id: str) -> None:
        thread = threading.Thread(target=self.run_task, args=(task_id,), name=f"weread-export-{task_id}", daemon=True)
        thread.start()

    def mark_incomplete_tasks_interrupted(self) -> int:
        return queries.mark_incomplete_tasks_interrupted()

    def resolve_artifact_path(self, artifact_id: str) -> str:
        raw = (artifact_id or "").strip()
        if ":" not in raw:
            raise ValueError("微信读书导出结果标识无效")
        task_id, index_raw = raw.split(":", 1)
        try:
            index = int(index_raw)
        except ValueError as exc:
            raise ValueError("微信读书导出结果标识无效") from exc
        if index < 1:
            raise ValueError("微信读书导出结果标识无效")
        task = queries.get_task(task_id)
        if not task:
            raise ValueError("微信读书导出任务不存在")
        results = task.get("results") or []
        if index > len(results):
            raise ValueError("微信读书导出结果不存在")
        result = results[index - 1]
        if result.get("status") not in {"success", "skipped"} or not result.get("path"):
            raise ValueError("微信读书导出结果不可用")
        return str(Path(result["path"]).expanduser().resolve())

    def _finished_at(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _is_cancelled(self, task_id: str) -> bool:
        latest = queries.get_task(task_id)
        return bool(latest and latest.get("cancel_requested"))

    def _handle_progress(self, task_id: str, event: dict) -> None:
        fields = {}
        for key in ("title", "author", "total", "current", "meta"):
            if key in event:
                fields[key] = event[key]
        if fields:
            queries.update_task(task_id, **fields)
        result = event.get("result")
        if isinstance(result, dict):
            queries.append_task_result(task_id, result)

    def _create_runner(self, *, task_id: str, chrome_cdp_endpoint: str) -> WeReadPlaywrightRunner:
        kwargs = {
            "progress": lambda event: self._handle_progress(task_id, event),
            "cancel_check": lambda: self._is_cancelled(task_id),
            "chrome_cdp_endpoint": chrome_cdp_endpoint,
        }
        try:
            return self.runner_factory(**kwargs)
        except TypeError as exc:
            if "chrome_cdp_endpoint" not in str(exc):
                raise
            kwargs.pop("chrome_cdp_endpoint")
            return self.runner_factory(**kwargs)

    def run_task(self, task_id: str) -> None:
        queries.update_task(task_id, current="等待当前导出任务结束")
        if not self._run_lock.acquire(timeout=self.lock_wait_timeout):
            queries.update_task(
                task_id,
                status="error",
                error="已有微信读书导出任务仍在运行，请取消旧任务或稍后重试",
                current="等待启动超时",
                finished_at=self._finished_at(),
            )
            return
        try:
            task = queries.get_task(task_id)
            if not task:
                return
            if self._is_cancelled(task_id):
                queries.update_task(task_id, status="cancelled", current="已取消", finished_at=self._finished_at())
                return
            queries.update_task(task_id, status="running", current="正在启动微信读书导出")
            try:
                data_dir = str(Path(str(task.get("cache_dir") or "")).expanduser().resolve().parent)
                meta = task.get("meta") or {}
                chrome_cdp_endpoint = str(meta.get("chrome_cdp_endpoint") or configured_chrome_cdp_endpoint()).strip().rstrip("/")
                chrome_cdp_profile_dir = str(meta.get("chrome_cdp_profile_dir") or default_cdp_profile_dir(data_dir)).strip()
                if configured_browser_mode() != BROWSER_MODE_PERSISTENT:
                    launch_result = ensure_chrome_cdp_with_options(
                        data_dir=data_dir,
                        endpoint=chrome_cdp_endpoint,
                        profile_dir=chrome_cdp_profile_dir,
                        initial_url=DEFAULT_CHROME_CDP_INITIAL_URL,
                    )
                    if launch_result.get("available"):
                        self._handle_progress(task_id, {"current": "已准备可复用 Chrome 会话"})
                    else:
                        self._handle_progress(task_id, {"current": "Chrome CDP 暂不可用，继续使用独立 Chromium 会话"})
                runner = self._create_runner(task_id=task_id, chrome_cdp_endpoint=chrome_cdp_endpoint)
                result = runner.run(
                    book_id=str(task.get("book_id") or ""),
                    output_dir=str(task.get("output_dir") or ""),
                    cache_dir=str(task.get("cache_dir") or ""),
                    save_raw=bool(task.get("save_raw")),
                )
                latest = queries.get_task(task_id) or {}
                status = "cancelled" if latest.get("cancel_requested") else "done"
                queries.update_task(
                    task_id,
                    status=status,
                    title=result.title,
                    author=result.author,
                    total=result.total,
                    current="已取消" if status == "cancelled" else "导出完成",
                    finished_at=self._finished_at(),
                )
            except WeReadExportError as exc:
                status = "cancelled" if "取消" in str(exc) and self._is_cancelled(task_id) else "error"
                queries.update_task(
                    task_id,
                    status=status,
                    error="" if status == "cancelled" else str(exc),
                    current="已取消" if status == "cancelled" else "导出失败",
                    finished_at=self._finished_at(),
                )
            except Exception as exc:
                queries.update_task(
                    task_id,
                    status="error",
                    error=str(exc),
                    current="导出失败",
                    finished_at=self._finished_at(),
                )
        finally:
            self._run_lock.release()

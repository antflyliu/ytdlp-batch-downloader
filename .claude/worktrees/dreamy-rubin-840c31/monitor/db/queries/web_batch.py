"""
monitor.db.queries.web_batch — Persisted web batch task operations.
"""
import json

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def _normalize_web_batch_task_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    try:
        item["results"] = json.loads(item.get("results_json") or "[]")
    except Exception:
        item["results"] = []
    try:
        item["urls"] = json.loads(item.get("urls") or "[]")
    except Exception:
        item["urls"] = []
    item.pop("results_json", None)
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    return item


def save_web_batch_task(task: dict) -> None:
    """Insert or update a persisted web batch task snapshot."""
    payload = {
        "task_id": task.get("task_id"),
        "task_kind": task.get("task_kind", "web_batch"),
        "source_name": task.get("source_name"),
        "output_path": task.get("output_path"),
        "status": task.get("status", "running"),
        "total": int(task.get("total", 0)),
        "completed": int(task.get("completed", 0)),
        "success": int(task.get("success", 0)),
        "failed": int(task.get("failed", 0)),
        "current_video": task.get("current_video") or "",
        "error": task.get("error"),
        "cancel_requested": int(bool(task.get("cancel_requested"))),
        "cancel_message": task.get("cancel_message"),
        "results_json": json.dumps(task.get("results", []) or [], ensure_ascii=False),
        "urls": json.dumps(task.get("urls", []) or [], ensure_ascii=False),
        "created_at": task.get("created_at") or now_iso(),
        "finished_at": task.get("finished_at"),
        "updated_at": now_iso(),
    }
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO web_batch_tasks
               (task_id, task_kind, source_name, output_path, status, total, completed, success, failed,
                current_video, error, cancel_requested, cancel_message, results_json, urls,
                created_at, finished_at, updated_at)
               VALUES (:task_id, :task_kind, :source_name, :output_path, :status, :total, :completed, :success, :failed,
                       :current_video, :error, :cancel_requested, :cancel_message, :results_json, :urls,
                       :created_at, :finished_at, :updated_at)
               ON CONFLICT(task_id) DO UPDATE SET
                 task_kind=excluded.task_kind,
                 source_name=excluded.source_name,
                 output_path=excluded.output_path,
                 status=excluded.status,
                 total=excluded.total,
                 completed=excluded.completed,
                 success=excluded.success,
                 failed=excluded.failed,
                 current_video=excluded.current_video,
                 error=excluded.error,
                 cancel_requested=excluded.cancel_requested,
                 cancel_message=excluded.cancel_message,
                 results_json=excluded.results_json,
                 urls=excluded.urls,
                 created_at=excluded.created_at,
                 finished_at=excluded.finished_at,
                 updated_at=excluded.updated_at""",
            payload,
        )


def get_web_batch_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM web_batch_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return _normalize_web_batch_task_row(row)


def list_web_batch_tasks(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM web_batch_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_normalize_web_batch_task_row(row) for row in rows]


def mark_incomplete_web_batch_tasks_interrupted() -> None:
    """Mark stale running/cancelling tasks as interrupted on startup."""
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE web_batch_tasks
               SET status='error',
                   error=COALESCE(error, '服务重启导致任务中断'),
                   current_video='服务重启导致任务中断',
                   finished_at=COALESCE(finished_at, ?),
                   updated_at=?,
                   cancel_requested=0
               WHERE status IN ('running', 'cancelling')""",
            (now, now),
        )

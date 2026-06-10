from __future__ import annotations

import json
from typing import Any

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def _json_dumps(value: Any, fallback: Any) -> str:
    return json.dumps(value if value is not None else fallback, ensure_ascii=False)


def _json_loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS weread_export_tasks (
            task_id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            book_input TEXT,
            title TEXT,
            author TEXT,
            output_dir TEXT NOT NULL,
            cache_dir TEXT NOT NULL,
            save_raw INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            total INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            current TEXT,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            result_json TEXT NOT NULL DEFAULT '[]',
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weread_export_tasks_created_at "
        "ON weread_export_tasks(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weread_export_tasks_status "
        "ON weread_export_tasks(status, created_at DESC)"
    )


def _normalize_task(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["save_raw"] = bool(item.get("save_raw"))
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    item["results"] = _json_loads(item.pop("result_json", "[]"), [])
    item["meta"] = _json_loads(item.pop("meta_json", "{}"), {})
    return item


def create_task(payload: dict, *, task_id: str, output_dir: str, cache_dir: str) -> None:
    now = now_iso()
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO weread_export_tasks
               (task_id, book_id, book_input, title, author, output_dir, cache_dir,
                save_raw, status, current, result_json, meta_json, created_at, updated_at)
               VALUES (?, ?, ?, '', '', ?, ?, ?, 'pending', ?, '[]', ?, ?, ?)""",
            (
                task_id,
                payload.get("book_id") or "",
                payload.get("book_input") or payload.get("book") or "",
                output_dir,
                cache_dir,
                1 if payload.get("save_raw", True) else 0,
                "等待启动",
                _json_dumps(payload.get("meta"), {}),
                now,
                now,
            ),
        )


def get_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM weread_export_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return _normalize_task(row)


def list_tasks(*, limit: int = 50, offset: int = 0) -> list[dict]:
    with get_connection() as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """SELECT *
               FROM weread_export_tasks
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (max(1, min(int(limit or 50), 200)), max(0, int(offset or 0))),
        ).fetchall()
    return [_normalize_task(row) for row in rows]


def update_task(task_id: str, **fields) -> None:
    allowed = {
        "title",
        "author",
        "status",
        "total",
        "completed",
        "success",
        "failed",
        "skipped",
        "current",
        "error",
        "cancel_requested",
        "finished_at",
        "meta",
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "cancel_requested":
            value = int(bool(value))
        elif key == "meta":
            key = "meta_json"
            value = _json_dumps(value, {})
        assignments.append(f"{key}=?")
        values.append(value)
    if not assignments:
        return
    assignments.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            f"UPDATE weread_export_tasks SET {', '.join(assignments)} WHERE task_id=?",
            values,
        )


def append_task_result(task_id: str, result: dict) -> None:
    task = get_task(task_id)
    if not task:
        return
    results = list(task.get("results") or [])
    results.append(result)
    progress_results = [item for item in results if item.get("kind") != "artifact"]
    success = sum(1 for item in progress_results if item.get("status") == "success")
    failed = sum(1 for item in progress_results if item.get("status") == "failed")
    skipped = sum(1 for item in progress_results if item.get("status") == "skipped")
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            """UPDATE weread_export_tasks
               SET result_json=?, completed=?, success=?, failed=?, skipped=?, current=?, updated_at=?
               WHERE task_id=?""",
            (
                _json_dumps(results, []),
                len(progress_results),
                success,
                failed,
                skipped,
                result.get("title") or result.get("path") or task.get("current") or "",
                now_iso(),
                task_id,
            ),
        )


def request_cancel(task_id: str) -> bool:
    task = get_task(task_id)
    if not task or task.get("status") not in {"pending", "running"}:
        return False
    update_task(task_id, cancel_requested=True, current="正在取消")
    return True


def mark_incomplete_tasks_interrupted() -> int:
    now = now_iso()
    with get_connection() as conn:
        ensure_schema(conn)
        cursor = conn.execute(
            """UPDATE weread_export_tasks
               SET status='interrupted',
                   current='服务重启导致任务中断',
                   error='服务重启导致任务中断',
                   updated_at=?,
                   finished_at=?
               WHERE status IN ('pending', 'running')""",
            (now, now),
        )
        return int(cursor.rowcount or 0)

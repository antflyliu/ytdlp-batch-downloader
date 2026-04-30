from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def public_session(row: dict) -> dict:
    return {
        "session_id": row.get("session_id") or "",
        "nickname": row.get("nickname") or "",
        "avatar": row.get("avatar") or "",
        "status": row.get("status") or "",
        "expires_at": row.get("expires_at") or "",
        "last_checked_at": row.get("last_checked_at") or "",
        "last_error": row.get("last_error") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def public_task(task: dict) -> dict:
    if not task:
        return {}
    task_id = str(task.get("task_id") or "")
    public = {
        "task_id": task_id,
        "provider": task.get("provider") or "",
        "source_mode": task.get("source_mode") or "",
        "fakeid": task.get("fakeid") or "",
        "article_url": task.get("article_url") or "",
        "account_name": task.get("account_name") or "",
        "keyword": task.get("keyword") or "",
        "export_format": task.get("export_format") or "",
        "max_articles": task.get("max_articles") or 0,
        "page_size": task.get("page_size") or 0,
        "delay_seconds": task.get("delay_seconds") or 0,
        "status": task.get("status") or "",
        "total": task.get("total") or 0,
        "completed": task.get("completed") or 0,
        "success": task.get("success") or 0,
        "failed": task.get("failed") or 0,
        "current": task.get("current") or "",
        "error": task.get("error") or "",
        "cancel_requested": bool(task.get("cancel_requested")),
        "created_at": task.get("created_at") or "",
        "updated_at": task.get("updated_at") or "",
        "finished_at": task.get("finished_at") or "",
        "results": [],
    }
    results = []
    for index, item in enumerate(task.get("results") or [], start=1):
        result = {
            "status": item.get("status") or "",
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "error": item.get("error") or "",
            "content_type": item.get("content_type") or "",
        }
        if item.get("status") == "success":
            path_value = str(item.get("path") or "")
            artifact_id = f"{task_id}:{index}"
            result["artifact_id"] = artifact_id
            result["artifact_name"] = Path(path_value).name if path_value else ""
            result["artifact_url"] = f"/api/wechat-native/artifacts/{quote(artifact_id, safe='')}"
        results.append(result)
    public["results"] = results
    return public

from __future__ import annotations

import json
from typing import Any

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def _json_dumps(value: Any) -> str:
    fallback = [] if isinstance(value, list) else {}
    return json.dumps(value if value is not None else fallback, ensure_ascii=False)


def _json_loads(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _normalize_task(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["urls"] = _json_loads(item.pop("urls_json", "[]"), [])
    item["results"] = _json_loads(item.pop("result_json", "[]"), [])
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    return item


def upsert_session(
    *,
    session_id: str,
    token_enc: str,
    cookie_json_enc: str,
    nickname: str = "",
    avatar: str = "",
    expires_at: str,
    status: str = "active",
) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_sessions
               (session_id, token_enc, cookie_json_enc, nickname, avatar, status,
                expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 token_enc=excluded.token_enc,
                 cookie_json_enc=excluded.cookie_json_enc,
                 nickname=excluded.nickname,
                 avatar=excluded.avatar,
                 status=excluded.status,
                 expires_at=excluded.expires_at,
                 updated_at=excluded.updated_at""",
            (session_id, token_enc, cookie_json_enc, nickname, avatar, status, expires_at, now, now),
        )


def get_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_collect_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT session_id, nickname, avatar, status, expires_at,
                      last_checked_at, last_error, created_at, updated_at
               FROM wechat_collect_sessions
               ORDER BY updated_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def expire_stale_sessions(now_iso_value: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE wechat_collect_sessions
               SET status='expired',
                   last_error='登录会话已过期',
                   last_checked_at=?,
                   updated_at=?
               WHERE status='active' AND expires_at <= ?""",
            (now_iso_value, now_iso_value, now_iso_value),
        )
        return int(cursor.rowcount or 0)


def list_stale_active_session_ids(now_iso_value: str) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT session_id
               FROM wechat_collect_sessions
               WHERE status='active' AND expires_at <= ?""",
            (now_iso_value,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def update_session_status(session_id: str, *, status: str, last_error: str = "") -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE wechat_collect_sessions
               SET status=?, last_error=?, last_checked_at=?, updated_at=?
               WHERE session_id=?""",
            (status, last_error, now, now, session_id),
        )


def invalidate_session_credentials(
    session_id: str,
    *,
    status: str,
    last_error: str = "",
    token_enc: str,
    cookie_json_enc: str,
) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE wechat_collect_sessions
               SET status=?,
                   token_enc=?,
                   cookie_json_enc=?,
                   last_error=?,
                   last_checked_at=?,
                   updated_at=?
               WHERE session_id=?""",
            (status, token_enc, cookie_json_enc, last_error, now, now, session_id),
        )


def upsert_account(account: dict) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_accounts
               (fakeid, nickname, alias, round_head_img, service_type, signature,
                verify_status, raw_json, last_synced_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fakeid) DO UPDATE SET
                 nickname=excluded.nickname,
                 alias=excluded.alias,
                 round_head_img=excluded.round_head_img,
                 service_type=excluded.service_type,
                 signature=excluded.signature,
                 verify_status=excluded.verify_status,
                 raw_json=excluded.raw_json,
                 last_synced_at=excluded.last_synced_at,
                 updated_at=excluded.updated_at""",
            (
                account.get("fakeid"),
                account.get("nickname"),
                account.get("alias"),
                account.get("round_head_img"),
                account.get("service_type"),
                account.get("signature"),
                account.get("verify_status"),
                _json_dumps(account),
                now,
                now,
                now,
            ),
        )


def get_account(fakeid: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_collect_accounts WHERE fakeid = ?",
            (fakeid,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    raw = _json_loads(item.get("raw_json"), {})
    if isinstance(raw, dict):
        item = {**raw, **item}
    item["raw_json"] = raw
    return item


def upsert_article(
    fakeid: str,
    article: dict,
    *,
    local_path: str = "",
    export_format: str = "",
    status: str = "listed",
) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_articles
               (fakeid, aid, title, link, digest, cover, author_name, update_time,
                create_time, raw_json, local_path, export_format, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(link) DO UPDATE SET
                 fakeid=excluded.fakeid,
                 aid=excluded.aid,
                 title=excluded.title,
                 digest=excluded.digest,
                 cover=excluded.cover,
                 author_name=excluded.author_name,
                 update_time=excluded.update_time,
                 create_time=excluded.create_time,
                 raw_json=excluded.raw_json,
                 local_path=COALESCE(NULLIF(excluded.local_path, ''), wechat_collect_articles.local_path),
                 export_format=COALESCE(NULLIF(excluded.export_format, ''), wechat_collect_articles.export_format),
                 status=CASE
                   WHEN excluded.status = 'listed' THEN wechat_collect_articles.status
                   ELSE excluded.status
                 END,
                 updated_at=excluded.updated_at""",
            (
                fakeid,
                article.get("aid"),
                article.get("title"),
                article.get("link") or article.get("url"),
                article.get("digest"),
                article.get("cover") or article.get("cover_img"),
                article.get("author_name"),
                article.get("update_time"),
                article.get("create_time"),
                _json_dumps(article),
                local_path,
                export_format,
                status,
                now,
                now,
            ),
        )


def _article_where(fakeid: str, keyword: str = "") -> tuple[str, list[Any]]:
    where = ["fakeid = ?"]
    params: list[Any] = [fakeid]
    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        where.append("(title LIKE ? OR digest LIKE ? OR author_name LIKE ? OR link LIKE ?)")
        params.extend([like, like, like, like])
    return " AND ".join(where), params


def _normalize_article_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    raw = _json_loads(item.get("raw_json"), {})
    merged = raw if isinstance(raw, dict) else {}
    merged = {**merged, **item}
    merged["raw_json"] = raw
    merged["link"] = merged.get("link") or merged.get("url") or ""
    merged["url"] = merged.get("url") or merged.get("link") or ""
    return merged


def count_articles(fakeid: str, *, keyword: str = "") -> int:
    where_sql, params = _article_where(fakeid, keyword)
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM wechat_collect_articles WHERE {where_sql}",
            params,
        ).fetchone()
    return int(row[0] if row else 0)


def list_articles(
    fakeid: str,
    *,
    keyword: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    where_sql, params = _article_where(fakeid, keyword)
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT *
                FROM wechat_collect_articles
                WHERE {where_sql}
                ORDER BY COALESCE(update_time, create_time, 0) DESC, id DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return [item for row in rows if (item := _normalize_article_row(row))]


def list_article_page(fakeid: str, *, keyword: str = "", begin: int = 0, page_size: int = 20) -> dict:
    begin = max(0, int(begin or 0))
    page_size = max(1, min(int(page_size or 20), 100))
    total_count = count_articles(fakeid, keyword=keyword)
    articles = list_articles(fakeid, keyword=keyword, limit=page_size, offset=begin)
    next_begin = begin + page_size
    has_more = next_begin < total_count
    return {
        "articles": articles,
        "total_count": total_count,
        "begin": begin,
        "page_size": page_size,
        "next_begin": next_begin if has_more else None,
        "has_more": has_more,
    }


def create_task(payload: dict, *, task_id: str, output_dir: str) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_tasks
               (task_id, provider, session_id, source_mode, fakeid, article_url,
                account_name, urls_json, keyword, export_format, output_dir,
                max_articles, page_size, delay_seconds,
                status, current, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                task_id,
                payload.get("provider") or "native",
                payload.get("session_id"),
                payload.get("source_mode") or "url",
                payload.get("fakeid"),
                payload.get("article_url"),
                payload.get("account_name"),
                _json_dumps(payload.get("urls") or []),
                payload.get("keyword"),
                payload.get("format") or payload.get("export_format") or "markdown",
                output_dir,
                int(payload.get("max_articles") or 50),
                int(payload.get("page_size") or 20),
                float(payload.get("delay_seconds") if payload.get("delay_seconds") is not None else 1.0),
                "等待启动",
                now,
                now,
            ),
        )


def get_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_collect_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return _normalize_task(row)


def list_tasks(*, provider: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    where = []
    params = []
    if provider:
        where.append("provider=?")
        params.append(provider)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT * FROM wechat_collect_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return [_normalize_task(row) for row in rows]


def update_task(task_id: str, **fields) -> None:
    allowed = {
        "status", "total", "completed", "success", "failed", "current",
        "error", "cancel_requested", "finished_at",
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "cancel_requested":
            value = int(bool(value))
        assignments.append(f"{key}=?")
        values.append(value)
    if not assignments:
        return
    assignments.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE wechat_collect_tasks SET {', '.join(assignments)} WHERE task_id=?",
            values,
        )


def append_task_result(task_id: str, result: dict) -> None:
    task = get_task(task_id)
    if not task:
        return
    results = list(task.get("results") or [])
    results.append(result)
    success = sum(1 for item in results if item.get("status") == "success")
    failed = len(results) - success
    with get_connection() as conn:
        conn.execute(
            """UPDATE wechat_collect_tasks
               SET result_json=?, completed=?, success=?, failed=?, current=?, updated_at=?
               WHERE task_id=?""",
            (
                _json_dumps(results),
                len(results),
                success,
                failed,
                result.get("title") or result.get("url") or task.get("current"),
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

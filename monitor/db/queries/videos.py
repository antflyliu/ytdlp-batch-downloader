"""
monitor.db.queries.videos — Monitor video CRUD and query operations.
"""
from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso, _escape_like


def insert_videos(videos: list[dict], account_id: int, event_id: int) -> int:
    """Batch insert videos. Returns actual inserted count (ignores UNIQUE conflicts)."""
    if not videos:
        return 0
    now = now_iso()
    with get_connection() as conn:
        cur = conn.executemany(
            """INSERT OR IGNORE INTO monitor_videos
               (video_id, account_id, event_id, channel_id, channel_handle,
                title, description, url, published_at, upload_date, duration_sec,
                view_count, like_count, comment_count, thumbnail_url,
                fetched_at, notify_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    v["video_id"],
                    account_id,
                    event_id,
                    v.get("channel_id"),
                    v.get("channel_handle"),
                    v["title"],
                    v.get("description", ""),
                    v["url"],
                    v.get("published_at", ""),
                    v.get("upload_date"),
                    v.get("duration_sec"),
                    v.get("view_count"),
                    v.get("like_count"),
                    v.get("comment_count"),
                    v.get("thumbnail_url"),
                    v.get("fetched_at", now),
                    "pending",
                    now,
                )
                for v in videos
            ],
        )
        return cur.rowcount


def get_new_video_ids(new_videos: list[dict]) -> set[str]:
    """Return video_ids not yet in monitor_videos table."""
    if not new_videos:
        return set()
    vid_list = [v["video_id"] for v in new_videos]
    placeholders = ",".join("?" * len(vid_list))
    with get_connection() as conn:
        existing = {
            r[0] for r in conn.execute(
                f"SELECT video_id FROM monitor_videos WHERE video_id IN ({placeholders})",
                vid_list,
            ).fetchall()
        }
    return {vid for vid in vid_list if vid not in existing}


def mark_notify_sent(video_ids: list[str], sent_at: str | None = None) -> None:
    if not video_ids:
        return
    sent_at = sent_at or now_iso()
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monitor_videos SET notify_status='sent', notify_sent_at=? "
            f"WHERE video_id IN ({placeholders})",
            [sent_at] + video_ids,
        )


def mark_notify_failed(video_ids: list[str], error: str) -> None:
    if not video_ids:
        return
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monitor_videos SET notify_status='failed', notify_error=? "
            f"WHERE video_id IN ({placeholders})",
            [error] + video_ids,
        )


def get_account_videos(
    account_id: int,
    title_kw: str | None = None,
    url_kw: str | None = None,
    sort_by: str = "published_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """Paginated video list with search and sorting. Returns (videos, total_count)."""
    ALLOWED_SORT = {
        "published_at": "published_at",
        "view_count": "view_count",
        "like_count": "like_count",
        "comment_count": "comment_count",
    }
    order_col = ALLOWED_SORT.get(sort_by, "published_at")
    order_dir = "DESC" if sort_dir == "desc" else "ASC"

    where_clauses = ["account_id = ?"]
    params: list = [account_id]

    if title_kw:
        where_clauses.append("title LIKE ?")
        params.append(f"%{_escape_like(title_kw)}%")
    if url_kw:
        where_clauses.append("url LIKE ?")
        params.append(f"%{_escape_like(url_kw)}%")

    where_sql = " AND ".join(where_clauses)

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM monitor_videos WHERE {where_sql}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""SELECT
                id, video_id, title, description, url,
                published_at, upload_date, duration_sec,
                view_count, like_count, comment_count,
                notify_status, download_status, download_at, download_path,
                fetched_at,
                retry_count, failed_reason, failed_at
               FROM monitor_videos
               WHERE {where_sql}
               ORDER BY {order_col} {order_dir}
               LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total


def update_videos_download_status(
    video_ids: list[int],
    status: str | None = None,
    download_at: str | None = None,
    download_path: str | None = None,
    download_error: str | None = None,
    retry_count: int | None = None,
    failed_reason: str | None = None,
    failed_at: str | None = None,
) -> int:
    """Batch update video download status and retry fields. Returns rows affected."""
    if not video_ids:
        return 0
    fields = []
    values: list = []
    if status:
        fields.append("download_status = ?")
        values.append(status)
    if download_at:
        fields.append("downloaded_at = ?")
        values.append(download_at)
    if download_path:
        fields.append("downloaded_path = ?")
        values.append(download_path)
    if download_error:
        fields.append("download_error = ?")
        values.append(download_error)
    if retry_count is not None:
        fields.append("retry_count = ?")
        values.append(retry_count)
    if failed_reason is not None:
        fields.append("failed_reason = ?")
        values.append(failed_reason)
    if failed_at is not None:
        fields.append("failed_at = ?")
        values.append(failed_at)
    if not fields:
        return 0
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        cur = conn.execute(
            f"UPDATE monitor_videos SET {', '.join(fields)} WHERE id IN ({placeholders})",
            values + video_ids,
        )
        return cur.rowcount


def get_videos_by_ids(video_ids: list[int]) -> list[dict]:
    """Get videos by monitor_videos.id list."""
    if not video_ids:
        return []
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT id, video_id, title, url, download_status, account_id,
                       retry_count, failed_reason, failed_at
                FROM monitor_videos WHERE id IN ({placeholders})""",
            video_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def reset_videos_for_retry(video_ids: list[int], account_id: int) -> None:
    """
    Reset failed videos to pending for retry.
    Uses parameterized queries to prevent SQL injection.
    """
    if not video_ids:
        return
    placeholders = ",".join("?" * len(video_ids))
    with get_connection() as conn:
        conn.execute(
            f"""UPDATE monitor_videos
               SET download_status = 'pending',
                   retry_count = 0,
                   failed_reason = NULL,
                   failed_at = NULL,
                   failed_event_id = NULL
               WHERE id IN ({placeholders})
               AND download_status = 'failed'""",
            video_ids,
        )


def mark_stale_running_videos_interrupted() -> None:
    """
    Mark running videos as failed on process restart.
    Prevents zombie tasks where download_status='running' never ends.
    """
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE monitor_videos
               SET download_status = 'failed',
                   failed_reason = '服务重启导致任务中断',
                   failed_at = ?,
                   retry_count = 0
               WHERE download_status = 'running'""",
            (now,),
        )


def get_account_videos_filtered(
    account_id: int,
    status: str | None = None,
) -> list[dict]:
    """Get account videos optionally filtered by download_status."""
    with get_connection() as conn:
        if status:
            rows = conn.execute(
                """SELECT id, video_id, title, url, download_status,
                          retry_count, failed_reason, failed_at
                   FROM monitor_videos
                   WHERE account_id = ? AND download_status = ?
                   ORDER BY created_at DESC LIMIT 100""",
                (account_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, video_id, title, url, download_status,
                          retry_count, failed_reason, failed_at
                   FROM monitor_videos
                   WHERE account_id = ?
                   ORDER BY created_at DESC LIMIT 100""",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]

"""
monitor.db.queries.logs — Download decision logs and scheduler run logs.
"""
from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def log_download_decision(
    account_id: int | None,
    account_name: str | None,
    video_count: int,
    is_auto_download: bool,
    cookies_present: bool,
    resolved_proxy_source: str,
    resolved_provider_name: str | None,
    resolved_provider_tier: str | None,
    resolved_country: str | None = None,
    resolved_session_mode: str | None = None,
    fallback_depth: int = 0,
    masked_proxy_endpoint: str | None = None,
    decision_reason: str = "",
    warnings: str | None = None,
) -> None:
    """Log a download routing decision."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO download_decision_logs
               (account_id, account_name, video_count, is_auto_download,
                cookies_present, resolved_proxy_source, resolved_provider_name,
                resolved_provider_tier, resolved_country, resolved_session_mode,
                fallback_depth, masked_proxy_endpoint, decision_reason, warnings, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, account_name, video_count, int(is_auto_download),
             int(cookies_present), resolved_proxy_source, resolved_provider_name,
             resolved_provider_tier, resolved_country, resolved_session_mode,
             fallback_depth, masked_proxy_endpoint, decision_reason, warnings,
             now_iso()),
        )


def get_download_decision_logs(account_id: int | None = None, limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        if account_id is not None:
            rows = conn.execute(
                "SELECT * FROM download_decision_logs WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM download_decision_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def add_provider_scheduler_run(
    provider_id: int | None,
    provider_name: str | None,
    job_type: str,
    status: str,
    raw_count: int = 0,
    valid_count: int = 0,
    message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_ms: int | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO provider_scheduler_runs
               (provider_id, provider_name, job_type, status, raw_count, valid_count, message, started_at, finished_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (provider_id, provider_name, job_type, status, raw_count, valid_count, message,
             started_at or now_iso(), finished_at, duration_ms),
        )
        return cur.lastrowid


def list_provider_scheduler_runs(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM provider_scheduler_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

"""
monitor.db.queries.candidates — Dynamic proxy candidate CRUD and helpers.
"""
from urllib.parse import quote

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso, _UNSET
from monitor.db.crypto import encrypt_candidate_secret, decrypt_candidate_secret


def _build_runtime_proxy_url(
    protocol: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Build a runtime-usable proxy URL from individual fields."""
    if username and password:
        user_part = f"{quote(username)}:{quote(password)}"
        return f"{protocol}://{user_part}@{host}:{port}"
    return f"{protocol}://{host}:{port}"


def _healthy_preview_sort_key_row(r: dict) -> tuple[int, int, float]:
    """Sort key for healthy candidates: latency ascending, then score descending."""
    lm = r.get("latency_ms")
    if isinstance(lm, int) and lm >= 0:
        tier = 0
        lat = lm
    else:
        tier = 1
        lat = 0
    sc = r.get("score", 0.0)
    score_f = float(sc) if isinstance(sc, (int, float)) else 0.0
    return (tier, lat, -score_f)


def rank_healthy_candidates_preview_aligned(rows: list[dict]) -> list[dict]:
    """Sort healthy rows same as preview: latency -> score."""
    healthy = [
        r
        for r in rows
        if str(r.get("last_probe_status") or "").strip().lower() == "healthy"
    ]
    if not healthy:
        return []
    return sorted(healthy, key=_healthy_preview_sort_key_row)


def pick_healthy_fastest_top_candidate(rows: list[dict]) -> dict | None:
    """Pick the lowest-latency healthy candidate."""
    ranked = rank_healthy_candidates_preview_aligned(rows)
    if not ranked:
        return None
    best = ranked[0]
    sc = best.get("score", 0.0)
    score_f = float(sc) if isinstance(sc, (int, float)) else 0.0
    return {
        "masked_proxy_endpoint": best.get("masked_proxy_endpoint"),
        "last_probe_status": best.get("last_probe_status"),
        "latency_ms": best.get("latency_ms"),
        "score": score_f,
    }


def build_runtime_proxy_url(candidate: dict) -> str:
    """Reconstruct a runtime-usable proxy URL from a candidate record."""
    password_enc = candidate.get("password_enc")
    password = decrypt_candidate_secret(password_enc) if password_enc else None
    return _build_runtime_proxy_url(
        candidate.get("protocol", "http"),
        candidate.get("host", ""),
        candidate.get("port", ""),
        candidate.get("username") or None,
        password,
    )


def add_proxy_candidate(
    provider_id: int,
    protocol: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    auth_type: str = "none",
    country_code: str | None = None,
    region: str | None = None,
    city: str | None = None,
    anonymity: str | None = None,
    risk_level: str = "medium",
    supports_https: bool = True,
    supports_cookies: bool = False,
    supports_auto_download: bool = True,
    supports_sticky_session: bool = False,
    latency_ms: int | None = None,
    last_probe_status: str = "unknown",
    last_probe_at: str | None = None,
    score: float = 0.0,
    provider_reference_id: str | None = None,
    ttl_expires_at: str | None = None,
    masked_proxy_endpoint: str | None = None,
) -> int:
    """
    Insert or refresh a proxy candidate (idempotent via candidate_key dedup).
    Returns candidate ID (new or existing).
    """
    candidate_key = f"{provider_id}:{protocol}:{host}:{port}:{username or ''}"
    password_enc = encrypt_candidate_secret(password)
    if masked_proxy_endpoint is None:
        masked_ep = (
            f"{protocol}://***:****@{host}:{port}"
            if username or password
            else f"{protocol}://{host}:{port}"
        )
    else:
        masked_ep = masked_proxy_endpoint

    now = now_iso()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM dynamic_proxy_candidates WHERE candidate_key=?",
            (candidate_key,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    provider_id=?, protocol=?, host=?, port=?,
                    username=?, password_enc=?, auth_type=?,
                    masked_proxy_endpoint=?, country_code=?, region=?, city=?,
                    anonymity=?, risk_level=?, supports_https=?,
                    supports_cookies=?, supports_auto_download=?,
                    supports_sticky_session=?, latency_ms=?,
                    last_probe_status=?, last_probe_at=?, score=?,
                    provider_reference_id=?, ttl_expires_at=?,
                    last_seen_at=?, updated_at=?
                   WHERE candidate_key=?""",
                (
                    provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_ep, country_code, region, city,
                    anonymity, risk_level, int(supports_https),
                    int(supports_cookies), int(supports_auto_download),
                    int(supports_sticky_session), latency_ms,
                    last_probe_status, last_probe_at or None, score,
                    provider_reference_id, ttl_expires_at,
                    now, now,
                    candidate_key,
                ),
            )
            return existing[0]
        else:
            cur = conn.execute(
                """INSERT INTO dynamic_proxy_candidates
                   (candidate_key, provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_proxy_endpoint, country_code, region, city,
                    anonymity, risk_level, supports_https,
                    supports_cookies, supports_auto_download, supports_sticky_session,
                    latency_ms, last_probe_status, last_probe_at,
                    score, provider_reference_id, ttl_expires_at,
                    last_seen_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate_key, provider_id, protocol, host, port,
                    username, password_enc, auth_type,
                    masked_ep, country_code, region, city,
                    anonymity, risk_level, int(supports_https),
                    int(supports_cookies), int(supports_auto_download), int(supports_sticky_session),
                    latency_ms, last_probe_status, last_probe_at,
                    score, provider_reference_id, ttl_expires_at,
                    now, now, now,
                ),
            )
            return cur.lastrowid


def get_proxy_candidate(candidate_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dynamic_proxy_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
        return dict(row) if row else None


def get_proxy_candidate_by_provider(
    provider_id: int,
    valid_only: bool = True,
    order_by_score_desc: bool = True,
) -> list[dict]:
    """
    Get candidates for a provider.
    valid_only: filter by ttl_expires_at > now.
    order_by_score_desc: score DESC (default) vs id ASC.
    """
    now = now_iso()
    order_clause = "ORDER BY score DESC" if order_by_score_desc else "ORDER BY id ASC"
    with get_connection() as conn:
        if valid_only:
            rows = conn.execute(
                f"""SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=? AND (ttl_expires_at IS NULL OR ttl_expires_at > ?)
                   {order_clause}""",
                (provider_id, now),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT * FROM dynamic_proxy_candidates
                   WHERE provider_id=?
                   {order_clause}""",
                (provider_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def delete_expired_candidates() -> int:
    """Delete expired candidates. Returns count deleted."""
    now = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM dynamic_proxy_candidates WHERE ttl_expires_at IS NOT NULL AND ttl_expires_at <= ?",
            (now,),
        )
        return cur.rowcount


def cleanup_stale_candidates(stale_days: int = 7) -> int:
    """Delete long-down candidates (>stale_days). Returns count deleted."""
    from datetime import datetime, timedelta
    cutoff = (
        datetime.now().astimezone() - timedelta(days=stale_days)
    ).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            """DELETE FROM dynamic_proxy_candidates
               WHERE last_probe_status = 'down'
                 AND last_probe_at IS NOT NULL
                 AND last_probe_at <= ?""",
            (cutoff,),
        )
        return cur.rowcount


def update_candidate_quality(
    candidate_id: int,
    success: bool,
    latency_ms: int | None = None,
    error_message: str | None = None,
    failure_category: str | None = None,
) -> None:
    """Update candidate quality metrics (success/failure)."""
    now = now_iso()
    with get_connection() as conn:
        if success:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    success_count = success_count + 1,
                    consecutive_failures = 0,
                    last_success_at = ?,
                    latency_ms = COALESCE(?, latency_ms),
                    last_error_message = NULL,
                    failure_category = NULL,
                    updated_at = ?
                   WHERE id=?""",
                (now, latency_ms, now, candidate_id),
            )
        else:
            conn.execute(
                """UPDATE dynamic_proxy_candidates SET
                    failure_count = failure_count + 1,
                    consecutive_failures = consecutive_failures + 1,
                    last_failure_at = ?,
                    latency_ms = COALESCE(?, latency_ms),
                    last_error_message = ?,
                    failure_category = ?,
                    updated_at = ?
                   WHERE id=?""",
                (now, latency_ms, error_message, failure_category, now, candidate_id),
            )

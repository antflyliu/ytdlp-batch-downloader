"""
monitor.db.queries.api_keys — API key CRUD operations.
"""
from monitor.db.connection import get_connection
from monitor.db.db_core import _today_str, now_iso, _UNSET


def list_api_keys() -> list[dict]:
    """List all API keys with today's quota usage."""
    from monitor import quota as _quota
    today = _quota.get_quota_date_key()
    with get_connection() as conn:
        # 见 monitor.db.list_api_keys：避免 ak.quota_used 与 COALESCE(aqu.api_calls) AS quota_used 列名冲突
        rows = conn.execute(
            """SELECT ak.id,
                      ak.key_value,
                      ak.name,
                      ak.daily_quota,
                      ak.quota_reset_at,
                      ak.is_active,
                      ak.created_at,
                      ak.updated_at,
                      COALESCE(aqu.api_calls, 0) AS quota_used,
                      COALESCE(aqu.scans_done, 0) AS scans_done,
                      COALESCE(aqu.blocked_scans, 0) AS blocked_scans
               FROM api_keys ak
               LEFT JOIN api_quota_usage aqu
                 ON aqu.api_key_value = ak.key_value
                AND aqu.date_key = ?
               ORDER BY ak.id""",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_api_key(key_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE id=?", (key_id,)
        ).fetchone()
        return dict(row) if row else None


def get_api_key_by_value(key_value: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_value=?", (key_value,)
        ).fetchone()
        return dict(row) if row else None


def add_api_key(key_value: str, name: str, daily_quota: int = 10000) -> int:
    """Add a new API key."""
    today = _today_str()
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO api_keys
               (key_value, name, daily_quota, quota_used, quota_reset_at,
                is_active, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, 1, ?, ?)""",
            (key_value, name, daily_quota, today, now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_api_key(
    key_id: int,
    name: str | None = None,
    key_value: str | None = None,
    daily_quota: int | None = None,
    is_active: bool | None = None,
) -> None:
    fields, values = [], []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if key_value:
        fields.append("key_value=?")
        values.append(key_value)
    if daily_quota is not None:
        fields.append("daily_quota=?")
        values.append(daily_quota)
    if is_active is not None:
        fields.append("is_active=?")
        values.append(int(is_active))
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(key_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE api_keys SET {','.join(fields)} WHERE id=?", values)


def delete_api_key(key_id: int) -> None:
    """Delete API key (linked accounts' api_key_id will be SET NULL)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))


def incr_api_key_quota(key_value: str, calls: int = 1, scans: int = 0) -> None:
    """Increment API key quota usage."""
    import monitor.quota as _quota
    _quota.incr(key_value, calls=calls, scans=scans)

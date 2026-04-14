"""
monitor.db.queries.proxy_pools — Proxy pool CRUD operations.
"""
from urllib.parse import urlparse

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def _validate_proxy_url(url: str) -> str:
    """Validate proxy URL format. Supports http/https/socks5/socks4."""
    if not url:
        raise ValueError("代理地址不能为空")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https", "socks5", "socks4", "socks"):
        raise ValueError(f"不支持的协议: {scheme}，支持 http/https/socks5/socks4")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    return url.strip()


def list_proxy_pools() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM proxy_pools ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_proxy_pool(pool_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM proxy_pools WHERE id=?", (pool_id,)
        ).fetchone()
        return dict(row) if row else None


def add_proxy_pool(name: str, proxy_url: str) -> int:
    """Add a new proxy pool (URL format already validated)."""
    proxy_url = _validate_proxy_url(proxy_url)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO proxy_pools (name, proxy_url, enabled, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?)""",
            (name, proxy_url, now_iso(), now_iso()),
        )
        return cur.lastrowid


def update_proxy_pool(
    pool_id: int,
    name: str | None = None,
    proxy_url: str | None = None,
    enabled: bool | None = None,
) -> None:
    """Update proxy pool fields (URL format already validated)."""
    if proxy_url is not None:
        proxy_url = _validate_proxy_url(proxy_url)
    fields, values = [], []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if proxy_url is not None:
        fields.append("proxy_url=?")
        values.append(proxy_url)
    if enabled is not None:
        fields.append("enabled=?")
        values.append(int(enabled))
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now_iso())
    values.append(pool_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE proxy_pools SET {','.join(fields)} WHERE id=?", values)


def delete_proxy_pool(pool_id: int) -> None:
    """Delete proxy pool (linked accounts' proxy_pool_id cleared, proxy_enabled=0)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE monitor_accounts SET proxy_pool_id=NULL, proxy_enabled=0 WHERE proxy_pool_id=?",
            (pool_id,),
        )
        conn.execute("DELETE FROM proxy_pools WHERE id=?", (pool_id,))

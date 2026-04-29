"""tests/test_provider_scheduler_crud.py — Step 1: refresh_interval_minutes schema + CRUD"""
import sqlite3
import tempfile
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_isolated_db():
    """Create a temp DB with fresh schema, return (get_connection_func, cleanup_func)."""
    import monitor.db as _db
    orig = _db.get_connection
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)

    def factory():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    _db.get_connection = factory
    _db.init_db()

    def cleanup():
        _db.get_connection = orig
        conn.close()
        if os.path.exists(path):
            try:
                os.unlink(path)
            except PermissionError:
                pass

    return cleanup


def test_add_dynamic_proxy_provider_accepts_refresh_interval_minutes():
    """ADD accepts refresh_interval_minutes and persists it."""
    import monitor.db as _db

    cleanup = _make_isolated_db()
    try:
        provider_id = _db.add_dynamic_proxy_provider(
            name="Test Provider",
            billing_tier="free",
            adapter_type="public_feed",
            refresh_interval_minutes=30,
        )

        fetched = _db.get_dynamic_proxy_provider(provider_id)
        assert fetched is not None
        assert fetched.get("refresh_interval_minutes") == 30, \
            f"Expected 30, got {fetched.get('refresh_interval_minutes')}"
    finally:
        cleanup()


def test_update_dynamic_proxy_provider_changes_refresh_interval_minutes():
    """UPDATE changes refresh_interval_minutes and persists it."""
    import monitor.db as _db

    cleanup = _make_isolated_db()
    try:
        provider_id = _db.add_dynamic_proxy_provider(
            name="Test Provider 2",
            billing_tier="paid",
            adapter_type="list_api",
            refresh_interval_minutes=15,
        )

        assert _db.get_dynamic_proxy_provider(provider_id).get("refresh_interval_minutes") == 15

        _db.update_dynamic_proxy_provider(provider_id, refresh_interval_minutes=60)

        updated = _db.get_dynamic_proxy_provider(provider_id)
        assert updated.get("refresh_interval_minutes") == 60, \
            f"Expected 60, got {updated.get('refresh_interval_minutes')}"
    finally:
        cleanup()


def test_add_dynamic_proxy_provider_defaults_refresh_interval_to_zero():
    """ADD without refresh_interval_minutes defaults to 0 (periodic refresh disabled)."""
    import monitor.db as _db

    cleanup = _make_isolated_db()
    try:
        provider_id = _db.add_dynamic_proxy_provider(
            name="Default Provider",
            billing_tier="free",
            adapter_type="public_feed",
        )

        fetched = _db.get_dynamic_proxy_provider(provider_id)
        assert fetched.get("refresh_interval_minutes") == 0
    finally:
        cleanup()

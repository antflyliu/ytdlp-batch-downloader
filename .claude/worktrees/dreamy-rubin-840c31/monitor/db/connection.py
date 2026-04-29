"""
monitor.db.connection — Database connection and path setup.

Handles:
- PyInstaller-compatible path resolution (via utils.paths)
- WAL-mode connection context manager
- DB/data directory paths
"""
import os
import sqlite3
from contextlib import contextmanager

# ── Paths via utils.paths ──────────────────────────────────────
from utils.paths import get_pkg_dir, get_exe_dir, get_data_dir, get_db_path, get_schema_path, get_config_path

_PKG_DIR = get_pkg_dir()
_EXE_DIR = get_exe_dir()
_DATA_DIR = get_data_dir()
_DB_PATH = get_db_path()
_SCHEMA_PATH = get_schema_path()
_CONFIG_PATH = get_config_path()

# ── Test helpers ──────────────────────────────────────────────


def _set_db_path(path):
    """For testing only: override the DB path."""
    global _DB_PATH
    _DB_PATH = path


def _set_data_dir(path):
    """For testing only: override the data directory."""
    global _DATA_DIR, _DB_PATH
    _DATA_DIR = path
    _DB_PATH = os.path.join(_DATA_DIR, "monitor.db")


def _reset_paths():
    """Reset paths to default (for testing)."""
    global _DATA_DIR, _DB_PATH, _PKG_DIR, _EXE_DIR, _SCHEMA_PATH, _CONFIG_PATH
    _PKG_DIR = get_pkg_dir()
    _EXE_DIR = get_exe_dir()
    _DATA_DIR = get_data_dir()
    _DB_PATH = get_db_path()
    _SCHEMA_PATH = get_schema_path()
    _CONFIG_PATH = get_config_path()


# ── Connection context manager ─────────────────────────────────


@contextmanager
def get_connection():
    """Thread-safe DB connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

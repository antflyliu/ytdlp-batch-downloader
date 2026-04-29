"""
utils/paths.py — Shared PyInstaller-compatible path resolution
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_exe_dir() -> str:
    """Project root directory"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # __file__ = utils/paths.py → go up two levels to project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_pkg_dir() -> str:
    """monitor/ package directory"""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "monitor")
    return os.path.join(get_exe_dir(), "monitor")


def get_data_dir() -> str:
    """Writable data directory"""
    d = os.path.join(get_exe_dir(), "data")
    os.makedirs(d, exist_ok=True)
    return d


def get_db_path() -> str:
    """Monitor SQLite database path"""
    return os.path.join(get_data_dir(), "monitor.db")


def get_config_path() -> str:
    """config.json path"""
    return os.path.join(get_exe_dir(), "config.json")


def get_schema_path() -> str:
    """schema.sql path"""
    return os.path.join(get_pkg_dir(), "schema.sql")


def get_static_dir() -> Path:
    """monitor_web static directory (at project root)"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "monitor_web"
    return Path(__file__).parent.parent / "monitor_web"


def get_log_dir() -> str:
    """Log directory (exe同级 logs/)"""
    return os.path.join(get_exe_dir(), "logs")

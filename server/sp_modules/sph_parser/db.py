"""sph_parse_history 表 + CRUD。

DB 路径：与现有 monitor.db 同库（路径在 monitor/db._get_db_connection 中）。
启动时由 monitor/db.py 调 init_schema() 建表。
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("sph.db")

# 默认路径与 monitor.db 同；测试时由 monkeypatch 覆盖
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "monitor.db",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sph_parse_history (
    id                TEXT PRIMARY KEY,
    sph_url           TEXT NOT NULL,
    video_title       TEXT,
    author_nickname   TEXT,
    cover_url         TEXT,
    video_url         TEXT NOT NULL,
    description       TEXT,
    downloaded        INTEGER NOT NULL DEFAULT 0,
    downloaded_path   TEXT,
    downloaded_at     TEXT,
    parse_status      TEXT NOT NULL DEFAULT 'success',
    parse_error       TEXT,
    parsed_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sph_parsed_at ON sph_parse_history(parsed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sph_downloaded ON sph_parse_history(downloaded);
"""


def init_schema() -> None:
    """建 sph_parse_history 表。幂等，可重复调用。"""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def insert_history(item: dict[str, Any]) -> None:
    """插入一条解析记录。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO sph_parse_history (
                id, sph_url, video_title, author_nickname, cover_url,
                video_url, description, downloaded, downloaded_path,
                parse_status, parse_error, parsed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["sph_url"],
                item.get("video_title", ""),
                item.get("author_nickname", ""),
                item.get("cover_url", ""),
                item["video_url"],
                item.get("description", ""),
                1 if item.get("downloaded") else 0,
                item.get("downloaded_path"),
                item.get("parse_status", "success"),
                item.get("parse_error"),
                item.get("parsed_at") or _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_history(limit: int = 20, offset: int = 0, keyword: str | None = None) -> list[dict]:
    """分页查询解析历史。"""
    where = ""
    params: list = []
    if keyword:
        where = "WHERE video_title LIKE ? OR author_nickname LIKE ?"
        params = [f"%{keyword}%", f"%{keyword}%"]
    sql = (
        f"SELECT * FROM sph_parse_history {where} "
        f"ORDER BY parsed_at DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_history(keyword: str | None = None) -> int:
    where = ""
    params: list = []
    if keyword:
        where = "WHERE video_title LIKE ? OR author_nickname LIKE ?"
        params = [f"%{keyword}%", f"%{keyword}%"]
    conn = sqlite3.connect(_DB_PATH)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM sph_parse_history {where}", params).fetchone()[0]
    finally:
        conn.close()


def get_history(history_id: str) -> dict | None:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM sph_parse_history WHERE id = ?", (history_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_downloaded(history_id: str, path: str) -> None:
    """标记一条记录为已下载。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            "UPDATE sph_parse_history SET downloaded=1, downloaded_path=?, downloaded_at=? WHERE id=?",
            (path, _now_iso(), history_id),
        )
        conn.commit()
    finally:
        conn.close()

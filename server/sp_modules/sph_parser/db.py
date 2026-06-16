"""sph_parse_history 表 + CRUD。

DB 路径：与现有 monitor.db 同库（路径在 monitor/db.get_db_path() 中）。
启动时由 monitor/db.py 调 init_schema() 建表。

修复：_DB_PATH 不再硬编码到 server/data/，改走 monitor.get_db_path() 拿项目根
data/monitor.db。否则 SPH 表与业务表会分裂到两个 DB，备份/迁移/查询都会漏。
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("sph.db")


def _get_db_path() -> str:
    """始终走 monitor.db.get_db_path()，保证 SPH 表与业务表同库。"""
    # 延迟 import：避免 monitor.db 启动时反向 import sph_db 触发循环
    from monitor import db as _monitor_db
    return _monitor_db.get_db_path()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sph_parse_history (
    id                TEXT PRIMARY KEY,
    sph_url           TEXT NOT NULL,
    video_title       TEXT,
    author_nickname   TEXT,
    cover_url         TEXT,
    video_url         TEXT NOT NULL,
    h264_video_url    TEXT,
    h265_video_url    TEXT,
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
CREATE INDEX IF NOT EXISTS idx_sph_sph_url ON sph_parse_history(sph_url);
"""


def init_schema() -> None:
    """建 sph_parse_history 表。幂等，可重复调用。"""
    path = _get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        # 旧表迁移：缺新列时补上（不影响已存在记录）
        cur = conn.execute("PRAGMA table_info(sph_parse_history)")
        cols = {r[1] for r in cur.fetchall()}
        if "h264_video_url" not in cols:
            conn.execute("ALTER TABLE sph_parse_history ADD COLUMN h264_video_url TEXT")
        if "h265_video_url" not in cols:
            conn.execute("ALTER TABLE sph_parse_history ADD COLUMN h265_video_url TEXT")
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def insert_history(item: dict[str, Any]) -> None:
    """插入一条解析记录。"""
    conn = sqlite3.connect(_get_db_path())
    try:
        conn.execute(
            """
            INSERT INTO sph_parse_history (
                id, sph_url, video_title, author_nickname, cover_url,
                video_url, h264_video_url, h265_video_url, description,
                downloaded, downloaded_path, parse_status, parse_error, parsed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["sph_url"],
                item.get("video_title", ""),
                item.get("author_nickname", ""),
                item.get("cover_url", ""),
                item["video_url"],
                item.get("h264_video_url") or "",
                item.get("h265_video_url") or "",
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


def update_history(history_id: str, fields: dict[str, Any]) -> int:
    """按 id 更新解析记录（用于"重新解析"按原 id 刷新视频链接）。

    不会触碰 downloaded / downloaded_path / downloaded_at —— 重新解析不应重置下载状态。
    返回受影响行数（0 = id 不存在）。
    """
    allowed = {
        "video_title", "author_nickname", "cover_url", "video_url",
        "h264_video_url", "h265_video_url", "description",
        "parse_status", "parse_error", "parsed_at",
    }
    sets: list[str] = []
    params: list = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return 0
    params.append(history_id)
    conn = sqlite3.connect(_get_db_path())
    try:
        cur = conn.execute(
            f"UPDATE sph_parse_history SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount
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
    conn = sqlite3.connect(_get_db_path())
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
    conn = sqlite3.connect(_get_db_path())
    try:
        return conn.execute(f"SELECT COUNT(*) FROM sph_parse_history {where}", params).fetchone()[0]
    finally:
        conn.close()


def get_history(history_id: str) -> dict | None:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM sph_parse_history WHERE id = ?", (history_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_downloaded(history_id: str, path: str) -> None:
    """标记一条记录为已下载。"""
    conn = sqlite3.connect(_get_db_path())
    try:
        conn.execute(
            "UPDATE sph_parse_history SET downloaded=1, downloaded_path=?, downloaded_at=? WHERE id=?",
            (path, _now_iso(), history_id),
        )
        conn.commit()
    finally:
        conn.close()

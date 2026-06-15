"""sph_parse_history 表 CRUD 测试（每测试独立 tmp_path db）。"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sp_modules.sph_parser import db as sph_db


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """重定向 monitor.db 到 tmp_path，避免污染真实数据。"""
    db_file = tmp_path / "monitor.db"
    monkeypatch.setattr(sph_db, "_DB_PATH", str(db_file))
    sph_db.init_schema()
    yield db_file


def test_init_schema_creates_table(tmp_db):
    conn = sqlite3.connect(str(tmp_db))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sph_parse_history'"
    )
    assert cur.fetchone() is not None


def test_insert_and_get_history(tmp_db):
    item = {
        "id": "uuid-1",
        "sph_url": "https://weixin.qq.com/sph/xxx",
        "video_title": "测试视频",
        "author_nickname": "作者A",
        "cover_url": "https://x/c.jpg",
        "video_url": "https://x/v?encfilekey=ENC&token=TK",
        "description": "desc",
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    }
    sph_db.insert_history(item)
    rows = sph_db.list_history(limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0]["id"] == "uuid-1"
    assert rows[0]["video_title"] == "测试视频"
    assert rows[0]["downloaded"] == 0  # SQLite INTEGER


def test_list_history_pagination_and_keyword(tmp_db):
    for i in range(5):
        sph_db.insert_history({
            "id": f"u-{i}",
            "sph_url": f"https://x/{i}",
            "video_title": f"标题{i}",
            "author_nickname": "张三",
            "cover_url": "",
            "video_url": "https://x?v=1",
            "description": "",
            "downloaded": False,
            "downloaded_path": None,
            "parse_status": "success",
            "parse_error": None,
        })
    rows = sph_db.list_history(limit=2, offset=0)
    assert len(rows) == 2
    rows = sph_db.list_history(limit=10, offset=0, keyword="标题2")
    assert len(rows) == 1
    assert rows[0]["id"] == "u-2"


def test_mark_downloaded(tmp_db):
    sph_db.insert_history({
        "id": "u-1",
        "sph_url": "x",
        "video_title": "t",
        "author_nickname": "a",
        "cover_url": "",
        "video_url": "v",
        "description": "",
        "downloaded": False,
        "downloaded_path": None,
        "parse_status": "success",
        "parse_error": None,
    })
    sph_db.mark_downloaded("u-1", "D:/videos/abc.mp4")
    rows = sph_db.list_history(limit=1)
    assert rows[0]["downloaded"] == 1
    assert rows[0]["downloaded_path"] == "D:/videos/abc.mp4"
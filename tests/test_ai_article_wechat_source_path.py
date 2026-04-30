from __future__ import annotations

from pathlib import Path

import monitor.db as db
import monitor.db.connection as db_connection
from scripts.article_generator import run_article_task


def _init_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()


def test_article_generator_rejects_wechat_source_path_outside_collect_root(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)
    collect_root = tmp_path / "wechat-collect"
    collect_root.mkdir()
    outside_source = tmp_path / "outside.md"
    outside_source.write_text("outside", encoding="utf-8")

    task_id = db.create_article_task(
        None,
        None,
        None,
        "outside",
        source_type="wechat_article",
        article_source_path=str(outside_source),
        target_lang="zh-Hans",
        auto_translate=False,
    )

    task = run_article_task(
        task_id,
        cfg={
            "wechat_collection_output_dir": str(collect_root),
            "article_output_dir": str(tmp_path / "articles"),
        },
    )

    assert task["status"] == "error"
    assert "公众号采集输出目录" in task["error"]

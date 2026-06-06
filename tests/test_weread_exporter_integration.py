from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db
import monitor.db.connection as db_connection
from monitor.db.queries import weread_exporter as weread_queries
from monitor.weread_exporter.core import WeReadExportResult, parse_book_id
from monitor.weread_exporter.tasks import WeReadExportTaskService, default_output_root, resolve_output_dir


@pytest.fixture()
def db_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(monitor_db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(monitor_db, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(monitor_db, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(monitor_db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(db_connection, "_CONFIG_PATH", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"), raising=False)
    monitor_db.init_db()
    return data_dir


def test_parse_book_id_accepts_weread_url_or_plain_id():
    assert parse_book_id("https://weread.qq.com/web/bookDetail/dd6324f0813ab9f97g019a24") == "dd6324f0813ab9f97g019a24"
    assert parse_book_id("dd6324f0813ab9f97g019a24") == "dd6324f0813ab9f97g019a24"
    assert parse_book_id("https://weread.qq.com/web/reader/abcdekabcdekabcdek12kabc32ef") == "abcdekabcdekabcdek12"


def test_init_db_bootstraps_weread_export_schema(db_env):
    with monitor_db.get_connection() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    assert "weread_export_tasks" in tables


def test_resolve_output_dir_rejects_paths_outside_export_root(tmp_path):
    root = tmp_path / "exports"
    inside = resolve_output_dir("books", str(root))

    assert Path(inside).is_dir()
    assert Path(inside).resolve().relative_to(root.resolve())
    with pytest.raises(ValueError):
        resolve_output_dir(str(tmp_path.parent), str(root))


def test_weread_task_service_rejects_invalid_book_ids(db_env):
    service = WeReadExportTaskService()

    with pytest.raises(ValueError, match="book_id"):
        service.create_task({"book": "../../outside"}, data_dir=str(db_env))


def test_weread_task_service_runs_with_fake_runner(db_env):
    class FakeRunner:
        def __init__(self, *, progress, cancel_check):
            self.progress = progress
            self.cancel_check = cancel_check

        def run(self, *, book_id, output_dir, cache_dir, save_raw):
            assert book_id == "dd6324f0813ab9f97g019a24"
            assert cache_dir
            assert save_raw is False
            out_path = Path(output_dir) / "测试书.md"
            out_path.write_text("# 测试书\n\n正文", encoding="utf-8")
            self.progress({
                "title": "测试书",
                "author": "测试作者",
                "total": 1,
                "current": "导出测试章节",
                "meta": {"title": "测试书", "chapters": [{"id": 1, "title": "第一章"}]},
            })
            self.progress({
                "result": {
                    "status": "success",
                    "title": "第一章",
                    "path": str(out_path),
                    "content_type": "text/markdown",
                }
            })
            self.progress({
                "result": {
                    "kind": "artifact",
                    "status": "success",
                    "title": "测试书 合并 Markdown",
                    "path": str(out_path),
                    "content_type": "text/markdown",
                }
            })
            return WeReadExportResult(
                title="测试书",
                author="测试作者",
                total=1,
                ok=1,
                failed=0,
                skipped=0,
                merged_path=str(out_path),
                meta_path="",
            )

    service = WeReadExportTaskService(runner_factory=FakeRunner)
    task_id = service.create_task(
        {
            "book": "https://weread.qq.com/web/bookDetail/dd6324f0813ab9f97g019a24",
            "save_raw": False,
        },
        data_dir=str(db_env),
    )
    service.run_task(task_id)

    task = service.get_task(task_id)
    assert task is not None
    assert task["status"] == "done"
    assert task["title"] == "测试书"
    assert task["total"] == 1
    assert task["completed"] == 1
    assert task["success"] == 1
    assert len(task["results"]) == 2
    assert task["results"][1]["kind"] == "artifact"
    assert task["results"][1]["artifact_url"].startswith("/api/weread-exporter/artifacts/")
    assert Path(service.resolve_artifact_path(task["results"][1]["artifact_id"])).is_file()
    assert Path(task["output_dir"]).resolve().relative_to(Path(default_output_root(str(db_env))).resolve())


def test_weread_query_request_cancel_only_running_tasks(db_env):
    service = WeReadExportTaskService()
    task_id = service.create_task({"book": "dd6324f0813ab9f97g019a24"}, data_dir=str(db_env))

    assert weread_queries.request_cancel(task_id) is True
    task = weread_queries.get_task(task_id)
    assert task and task["cancel_requested"] is True

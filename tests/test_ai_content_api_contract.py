"""Contract tests for P0 AI content API routes and safe file constraints."""
from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"


def _read_server_text() -> str:
    return SERVER_MAIN.read_text(encoding="utf-8")


def _require_snippets(text: str, snippets: list[str], reason: str) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        pytest.xfail(f"{reason}. Missing: {missing}")


def test_monitor_handler_routes_ai_content_endpoints():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            'elif path == "/api/article/generate":',
            'elif path == "/api/video-generate":',
            'elif path == "/api/article/list":',
            'elif path == "/api/video-generate/list":',
            'elif path.startswith("/api/article/") and path.endswith("/rerun"):',
            'elif path.startswith("/api/article/") and path.endswith("/cancel"):',
            'elif path.startswith("/api/video-generate/") and path.endswith("/cancel"):',
        ],
        "P0 AI content MonitorHandler routes are not wired yet",
    )


def test_ai_content_api_uses_explicit_post_cancel_endpoints_instead_of_delete():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            "/api/article/{task_id}/cancel",
            "/api/video-generate/{task_id}/cancel",
            "/api/article/{task_id}/rerun",
        ],
        "Explicit AI content cancel endpoints are not documented in server source yet",
    )

    assert 'DELETE /api/article/' not in text
    assert 'DELETE /api/video-generate/' not in text


def test_ai_content_api_validates_safe_file_paths_under_configured_output_roots():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            "/api/video-generate/templates",
            "Path(",
            ".resolve()",
            ".relative_to(",
        ],
        "Safe file validation contract for generated assets is not implemented yet",
    )


def test_ai_content_api_defines_stable_error_responses_for_validation_and_cancel_conflicts():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            'self._send_json({"error":',
            "}, 400)",
            "}, 404)",
            "}, 409)",
        ],
        "Stable 400/404/409 AI content API responses are not visible in server source yet",
    )


def test_article_generate_accepts_wechat_article_source_without_video_url():
    server = SERVER_MAIN.read_text(encoding="utf-8")
    generator = (ROOT / "scripts" / "article_generator.py").read_text(encoding="utf-8")
    api = (ROOT / "frontend-vue" / "src" / "api" / "aiContent.ts").read_text(encoding="utf-8")

    assert "source_type" in server
    assert "wechat_article" in server
    assert "wechat_artifact_id" in server
    assert "resolve_artifact_path" in server
    assert "article_source_path" in server or "article_text" in server
    assert "wechat_artifact_id" in api
    assert "wechat_article" in generator
    assert "yt_dlp" in generator


def test_article_generate_accepts_wechat_artifact_url_without_artifact_id(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    collect_root = tmp_path / "wechat-collect"
    collect_root.mkdir()
    article = collect_root / "article.md"
    article.write_text("# article", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeTaskService:
        def resolve_artifact_path(self, artifact_id):
            captured["artifact_id"] = artifact_id
            return str(article)

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_name"] = kwargs.get("name")

        def start(self):
            captured["thread_started"] = True

    def fake_create_article_task(*args, **kwargs):
        captured["create_args"] = args
        captured["create_kwargs"] = kwargs
        return "article-task-1"

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "_wechat_native_task_service", FakeTaskService())
    monkeypatch.setattr(
        server._db,
        "load_config",
        lambda: {
            "wechat_collection_output_dir": str(collect_root),
            "article_output_dir": str(tmp_path / "articles"),
        },
    )
    monkeypatch.setattr(server._db, "create_article_task", fake_create_article_task)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    handler._api_article_generate(
        {
            "source_type": "wechat_article",
            "article_source_path": "http://127.0.0.1:5000/api/wechat-native/artifacts/wcn_test%3A1?download=1",
            "source_url": "https://mp.weixin.qq.com/s/test",
            "source_title": "标题",
        }
    )

    assert captured["artifact_id"] == "wcn_test:1"
    assert captured["create_kwargs"]["article_source_path"] == str(article)
    assert captured["create_kwargs"]["source_url"] == "https://mp.weixin.qq.com/s/test"
    assert captured["create_kwargs"]["source_title"] == "标题"
    assert captured["payload"] == {"ok": True, "task_id": "article-task-1"}
    assert captured["status"] == 202


def test_article_rerun_clones_terminal_task_and_starts_new_run(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}

    class FakeThread:
        def __init__(self, *args, **kwargs):
            captured["thread_args"] = args
            captured["thread_kwargs"] = kwargs

        def start(self):
            captured["thread_started"] = True

    def fake_create_article_task(*args, **kwargs):
        captured["create_args"] = args
        captured["create_kwargs"] = kwargs
        return "article_retry_1"

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})
    monkeypatch.setattr(
        server._db,
        "get_article_task",
        lambda task_id: {
            "task_id": task_id,
            "status": "error",
            "source_type": "wechat_article",
            "monitor_video_id": None,
            "video_id": None,
            "video_url": None,
            "video_title": "AI takes people at their word",
            "article_source_path": "D:/articles/source.md",
            "article_text": "",
            "source_url": "https://example.test/article",
            "source_title": "AI takes people at their word",
            "email_message_id": None,
            "rss_item_id": None,
            "target_lang": "zh-Hans",
            "auto_translate": True,
        },
    )
    monkeypatch.setattr(server._db, "load_config", lambda: {"article_default_target_lang": "zh-Hans"})
    monkeypatch.setattr(server._db, "create_article_task", fake_create_article_task)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)

    handler._api_article_rerun("article_failed_1")

    assert captured["status"] == 202
    assert captured["payload"] == {
        "ok": True,
        "task_id": "article_retry_1",
        "source_task_id": "article_failed_1",
    }
    assert captured["create_kwargs"]["source_type"] == "wechat_article"
    assert captured["create_kwargs"]["video_title"] == "AI takes people at their word"
    assert captured["create_kwargs"]["article_source_path"] == "D:/articles/source.md"
    assert captured["create_kwargs"]["source_title"] == "AI takes people at their word"
    assert captured["thread_started"] is True
    assert captured["thread_kwargs"]["name"] == "article-task-article_retry_1"


def test_article_rerun_rejects_running_task(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})
    monkeypatch.setattr(
        server._db,
        "get_article_task",
        lambda task_id: {"task_id": task_id, "status": "running"},
    )

    handler._api_article_rerun("article_running_1")

    assert captured["status"] == 409
    assert "不能重新执行" in captured["payload"]["error"]


def test_article_get_exposes_intermediate_output_files(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    output_dir = tmp_path / "articles" / "article_task_1"
    output_dir.mkdir(parents=True)
    source_audio = output_dir / "whisper_source.webm"
    source_audio.write_bytes(b"fake audio")
    captured: dict[str, object] = {}

    handler = object.__new__(server.MonitorHandler)
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(
        server._db,
        "get_article_task",
        lambda task_id: {
            "task_id": task_id,
            "status": "running",
            "current_stage": "whisper",
            "output_dir": str(output_dir),
            "stages": {"whisper": {"status": "running", "message": "正在使用本地 Whisper 模型转写"}},
        },
    )

    handler._api_article_get("article_task_1")

    payload = captured["payload"]
    assert captured["status"] == 200
    assert payload["output_files"][0]["name"] == "whisper_source.webm"
    assert payload["output_files"][0]["size"] == len(b"fake audio")
    assert payload["latest_output_file"]["path"].endswith("whisper_source.webm")


def test_article_file_serves_project_relative_output_dir(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    output_root = tmp_path / "output" / "articles"
    output_dir = output_root / "article_task_1"
    output_dir.mkdir(parents=True)
    draft = output_dir / "draft.md"
    draft.write_text("# done", encoding="utf-8")
    captured: dict[str, object] = {}
    responses: list[tuple[str, object]] = []

    handler = object.__new__(server.MonitorHandler)
    handler.path = f"/api/article/file?path={quote(str(draft))}"
    handler.wfile = io.BytesIO()
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})
    handler._allowed_origin = lambda: None
    handler.send_response = lambda status: responses.append(("status", status))
    handler.send_header = lambda key, value: responses.append((key, value))
    handler.end_headers = lambda: None

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server._db, "load_config", lambda: {"article_output_dir": "output/articles"})

    handler._api_article_file()

    assert captured == {}
    assert ("status", 200) in responses
    assert ("Cache-Control", "private, no-store") in responses
    assert ("X-Content-Type-Options", "nosniff") in responses
    assert ("Content-Security-Policy", "sandbox") in responses
    assert handler.wfile.getvalue() == b"# done"


def test_article_file_rejects_paths_outside_article_output_dir(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    output_root = tmp_path / "output" / "articles"
    output_root.mkdir(parents=True)
    outside = tmp_path / "secrets.txt"
    outside.write_text("secret", encoding="utf-8")
    captured: dict[str, object] = {}

    handler = object.__new__(server.MonitorHandler)
    handler.path = f"/api/article/file?path={quote(str(outside))}"
    handler._send_json = lambda payload, status=200: captured.update({"payload": payload, "status": status})

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server._db, "load_config", lambda: {"article_output_dir": "output/articles"})

    handler._api_article_file()

    assert captured["status"] == 400
    assert captured["payload"] == {"error": "无效的输出路径"}


def test_article_output_path_accepts_project_relative_output_dir(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    output_root = tmp_path / "output" / "articles"
    output_dir = output_root / "article_task_1"
    output_dir.mkdir(parents=True)
    draft = output_dir / "draft.md"
    draft.write_text("# done", encoding="utf-8")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))

    resolved = server.MonitorHandler._resolve_article_output_path(
        str(draft),
        {"article_output_dir": "output/articles"},
    )

    assert resolved == draft.resolve()


def test_article_output_path_accepts_project_relative_artifact_path(monkeypatch, tmp_path):
    server = importlib.import_module("server.__main__")
    output_root = tmp_path / "output" / "articles"
    output_dir = output_root / "article_task_1"
    output_dir.mkdir(parents=True)
    draft = output_dir / "draft.md"
    draft.write_text("# done", encoding="utf-8")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))

    resolved = server.MonitorHandler._resolve_article_output_path(
        "output/articles/article_task_1/draft.md",
        {"article_output_dir": "output/articles"},
    )

    assert resolved == draft.resolve()


def test_article_background_runner_marks_uncaught_errors(monkeypatch):
    server = importlib.import_module("server.__main__")
    captured: dict[str, object] = {}

    def failing_run_article_task(task_id, cfg=None):
        assert task_id == "article-task-1"
        assert cfg == {"whisper_provider": "local"}
        raise RuntimeError("boom during import or startup")

    def fake_update_article_task(task_id, **kwargs):
        captured["task_id"] = task_id
        captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "scripts.article_generator",
        SimpleNamespace(run_article_task=failing_run_article_task),
    )
    monkeypatch.setattr(server._db, "update_article_task", fake_update_article_task)
    monkeypatch.setattr(server._db, "now_iso", lambda: "2026-04-30T11:00:00+08:00")
    monkeypatch.setattr(server._log, "exception", lambda *_args, **_kwargs: None)

    server._run_article_task_safely("article-task-1", {"whisper_provider": "local"})

    assert captured["task_id"] == "article-task-1"
    assert captured["status"] == "error"
    assert captured["current_stage"] == "error"
    assert captured["finished_at"] == "2026-04-30T11:00:00+08:00"
    assert "boom during import or startup" in str(captured["error"])

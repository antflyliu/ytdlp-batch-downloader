from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path
import asyncio

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db
import monitor.db.connection as db_connection
from monitor.db.queries import weread_exporter as weread_queries
import monitor.weread_exporter.core as weread_core
import monitor.weread_exporter.tasks as weread_tasks
from monitor.weread_exporter.core import WeReadExportError, WeReadExportResult, WeReadPlaywrightRunner, parse_book_id
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


def test_weread_runner_auto_mode_prefers_existing_chrome_cdp(tmp_path):
    class FakeContext:
        pass

    class FakeBrowser:
        def __init__(self):
            self.contexts = [FakeContext()]
            self.close_called = False

        async def close(self):
            self.close_called = True

    class FakeChromium:
        def __init__(self):
            self.browser = FakeBrowser()
            self.launch_called = False
            self.cdp_endpoint = ""
            self.cdp_timeout = None

        async def connect_over_cdp(self, endpoint_url, *, timeout):
            self.cdp_endpoint = endpoint_url
            self.cdp_timeout = timeout
            return self.browser

        async def launch_persistent_context(self, *args, **kwargs):
            self.launch_called = True
            return FakeContext()

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

    fake = FakePlaywright()
    runner = WeReadPlaywrightRunner(browser_mode="auto", chrome_cdp_endpoint="http://127.0.0.1:9333")

    session = asyncio.run(runner._open_browser_context(fake, tmp_path))
    asyncio.run(session.close())

    assert session.kind == "chrome_cdp"
    assert session.context is fake.chromium.browser.contexts[0]
    assert fake.chromium.cdp_endpoint == "http://127.0.0.1:9333"
    assert fake.chromium.cdp_timeout == 3000
    assert fake.chromium.launch_called is False
    assert fake.chromium.browser.close_called is False


def test_weread_runner_auto_mode_falls_back_to_persistent_context(tmp_path):
    class FakeContext:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    class FakeChromium:
        def __init__(self):
            self.persistent_context = FakeContext()
            self.launch_args = None

        async def connect_over_cdp(self, endpoint_url, *, timeout):
            raise RuntimeError("connection refused")

        async def launch_persistent_context(self, *args, **kwargs):
            self.launch_args = (args, kwargs)
            return self.persistent_context

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

    fake = FakePlaywright()
    progress_events = []
    runner = WeReadPlaywrightRunner(
        browser_mode="auto",
        chrome_cdp_endpoint="http://127.0.0.1:9333",
        progress=progress_events.append,
    )

    session = asyncio.run(runner._open_browser_context(fake, tmp_path))
    asyncio.run(session.close())

    assert session.kind == "persistent"
    assert session.context is fake.chromium.persistent_context
    assert fake.chromium.launch_args is not None
    assert fake.chromium.persistent_context.closed is True
    assert any("独立" in str(event.get("current") or "") for event in progress_events)


def test_weread_runner_forced_chrome_cdp_reports_connection_error(tmp_path):
    class FakeChromium:
        async def connect_over_cdp(self, endpoint_url, *, timeout):
            raise RuntimeError("connection refused")

    class FakePlaywright:
        chromium = FakeChromium()

    runner = WeReadPlaywrightRunner(browser_mode="chrome_cdp", chrome_cdp_endpoint="http://127.0.0.1:9333")

    with pytest.raises(WeReadExportError, match="Chrome CDP"):
        asyncio.run(runner._open_browser_context(FakePlaywright(), tmp_path))


def test_weread_runner_fetches_book_meta_with_context_request():
    class FakeResponse:
        def __init__(self, payload):
            self.ok = True
            self.status = 200
            self._payload = payload

        def json(self):
            return self._payload

    class FakeRequest:
        def __init__(self):
            self.calls = []

        async def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            return FakeResponse({"title": "测试书", "author": "测试作者"})

        async def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            return FakeResponse({
                "data": [
                    {
                        "updated": [
                            {"chapterUid": 1, "title": "第一章", "wordCount": 123},
                        ]
                    }
                ]
            })

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()

        async def new_page(self):
            raise AssertionError("metadata fetch should not use page.evaluate")

    runner = WeReadPlaywrightRunner()
    context = FakeContext()

    meta = asyncio.run(runner.fetch_book_meta(context, "dd6324f0813ab9f97g019a24"))

    assert meta == {
        "title": "测试书",
        "author": "测试作者",
        "chapters": [{"id": 1, "title": "第一章", "words": 123}],
    }
    assert context.request.calls[0][0] == "GET"
    assert context.request.calls[0][1].endswith("/book/info?bookId=dd6324f0813ab9f97g019a24")
    assert context.request.calls[1][0] == "POST"
    assert context.request.calls[1][2]["data"] == {
        "bookIds": ["dd6324f0813ab9f97g019a24"],
        "synckeys": [0],
        "teenmode": 0,
    }


def test_weread_runner_prefers_current_web_reader_metadata():
    class FakeResponse:
        def __init__(self, payload):
            self.ok = True
            self.status = 200
            self.status_text = "OK"
            self._payload = payload

        def json(self):
            return self._payload

    class FakeRequest:
        def __init__(self):
            self.calls = []

        async def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            assert url.startswith("https://weread.qq.com/web/book/readInfo?bookId=815574")
            return FakeResponse({
                "bookInfo": {
                    "bookId": "815574",
                    "title": "商业的本质",
                    "author": "杰克·韦尔奇 苏茜·韦尔奇",
                    "lastChapterIdx": 22,
                    "maxFreeInfo": {"maxfreeChapterUid": 28},
                    "copyrightChapterUids": [23],
                }
            })

        async def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            assert url == "https://weread.qq.com/web/book/outline"
            assert kwargs["data"]["bookId"] == "815574"
            assert 24 in kwargs["data"]["chapterUids"]
            return FakeResponse({
                "itemsArray": [
                    {"chapterUid": 23, "version": 0},
                    {
                        "chapterUid": 24,
                        "version": 30012,
                        "items": [{"text": "导读 管理之美在于亦步亦趋的践行", "level": 1}],
                    },
                    {
                        "chapterUid": 25,
                        "version": 30013,
                        "items": [{"text": "中文版序 商业是探求真实、建立互信的过程", "level": 1}],
                    },
                ]
            })

    class FakePage:
        def __init__(self):
            self.goto_calls = []
            self.closed = False

        async def goto(self, url, **kwargs):
            self.goto_calls.append((url, kwargs))

        async def evaluate(self, _script):
            return {
                "webBookId": "815574",
                "title": "商业的本质",
                "author": "杰克·韦尔奇 苏茜·韦尔奇",
            }

        async def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()
            self.page = FakePage()

        async def new_page(self):
            return self.page

    runner = WeReadPlaywrightRunner()
    context = FakeContext()

    meta = asyncio.run(runner.fetch_book_meta(context, "4a232bb05c71d64a2ea0506"))

    assert context.page.goto_calls == [
        ("https://weread.qq.com/web/reader/4a232bb05c71d64a2ea0506", {"wait_until": "domcontentloaded", "timeout": 30000})
    ]
    assert context.page.closed is True
    assert meta["title"] == "商业的本质"
    assert meta["author"] == "杰克·韦尔奇 苏茜·韦尔奇"
    assert meta["web_book_id"] == "815574"
    assert meta["reader_book_id"] == "4a232bb05c71d64a2ea0506"
    assert meta["chapters"] == [
        {"id": 24, "title": "导读 管理之美在于亦步亦趋的践行", "words": 0},
        {"id": 25, "title": "中文版序 商业是探求真实、建立互信的过程", "words": 0},
    ]
    assert context.request.calls[0][0] == "GET"
    assert context.request.calls[1][0] == "POST"


def test_weread_runner_retries_current_web_book_id_candidates():
    class FakeResponse:
        def __init__(self, payload):
            self.ok = True
            self.status = 200
            self.status_text = "OK"
            self._payload = payload

        def json(self):
            return self._payload

    class FakeRequest:
        def __init__(self):
            self.calls = []

        async def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            if "bookId=3300035099" in url:
                return FakeResponse({
                    "bookInfo": {
                        "bookId": "3300035099",
                        "title": "底层逻辑2：理解商业世界的本质",
                        "author": "刘润",
                        "lastChapterIdx": 30,
                        "maxFreeInfo": {"maxfreeChapterUid": 39},
                        "copyrightChapterUids": [34],
                    }
                })
            return FakeResponse({"bookInfo": {"bookId": "cpPlatform_ciP8oppqpzLpqhxJK9LLVg"}})

        async def post(self, url, **kwargs):
            self.calls.append(("POST", url, kwargs))
            if kwargs["data"]["bookId"] == "3300035099":
                return FakeResponse({
                    "itemsArray": [
                        {"chapterUid": 34, "version": 0},
                        {
                            "chapterUid": 37,
                            "version": 30015,
                            "items": [{"text": "数学是用来描述万物本质的语言", "level": 1}],
                        },
                    ]
                })
            return FakeResponse({
                "itemsArray": [
                    {"chapterUid": uid, "version": 0}
                    for uid in kwargs["data"]["chapterUids"][:5]
                ]
            })

    class FakePage:
        def __init__(self):
            self.closed = False

        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, _script):
            return {
                "webBookId": "cpPlatform_ciP8oppqpzLpqhxJK9LLVg",
                "webBookIds": [
                    "cpPlatform_ciP8oppqpzLpqhxJK9LLVg",
                    "3300035099",
                    "0b0322e0813ab7435g0197d8",
                ],
                "title": "底层逻辑2：理解商业世界的本质",
                "author": "刘润",
            }

        async def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()
            self.page = FakePage()

        async def new_page(self):
            return self.page

    runner = WeReadPlaywrightRunner()
    context = FakeContext()

    meta = asyncio.run(runner.fetch_book_meta(context, "0b0322e0813ab7435g0197d8"))

    requested_book_ids = [
        call[2]["data"]["bookId"]
        for call in context.request.calls
        if call[0] == "POST" and call[1] == "https://weread.qq.com/web/book/outline"
    ]
    assert requested_book_ids == ["cpPlatform_ciP8oppqpzLpqhxJK9LLVg", "3300035099"]
    assert context.page.closed is True
    assert meta["web_book_id"] == "3300035099"
    assert meta["reader_book_id"] == "0b0322e0813ab7435g0197d8"
    assert meta["chapters"] == [
        {"id": 37, "title": "数学是用来描述万物本质的语言", "words": 0},
    ]


def test_weread_runner_fetch_chapter_does_not_wait_for_networkidle(monkeypatch):
    class FakeKeyboard:
        def __init__(self):
            self.presses = []

        async def press(self, key):
            self.presses.append(key)

    class FakePage:
        def __init__(self):
            self.goto_calls = []
            self.init_scripts = []
            self.keyboard = FakeKeyboard()
            self.url = ""
            self.closed = False
            self.evaluated = []
            self.count_calls = 0

        async def add_init_script(self, script):
            self.init_scripts.append(script)

        async def goto(self, url, **kwargs):
            self.url = url
            self.goto_calls.append((url, kwargs))

        async def evaluate(self, script):
            self.evaluated.append(script)
            if script == "() => window.__wr_count()":
                self.count_calls += 1
                return 12
            if script == "() => window.__wr_mark()":
                return None
            if script == "() => window.__wr_chars":
                return [{"t": "测", "x": 1, "y": 1}, {"t": "试", "x": 2, "y": 1}]
            if script == "() => window.__wr_page_marks":
                return [0, 2]
            raise AssertionError(f"unexpected evaluate script: {script}")

        async def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.page = FakePage()

        async def new_page(self):
            return self.page

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(weread_core.asyncio, "sleep", fake_sleep)

    context = FakeContext()
    runner = WeReadPlaywrightRunner()
    result = asyncio.run(runner.fetch_chapter(context, "4a232bb05c71d64a2ea0506", 24))

    assert result["ok"] is True
    assert context.page.goto_calls == [
        (
            f"https://weread.qq.com/web/reader/4a232bb05c71d64a2ea0506k{weread_core.wr_hash('24')}",
            {"wait_until": "domcontentloaded", "timeout": 45000},
        )
    ]
    assert context.page.closed is True


def test_weread_runner_reuses_valid_web_session_without_opening_login():
    class FakeResponse:
        ok = True
        status = 200

        def json(self):
            return {"userVid": "55544444"}

    class FakeRequest:
        def __init__(self):
            self.urls = []

        async def get(self, url, **kwargs):
            self.urls.append((url, kwargs))
            return FakeResponse()

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()

        async def cookies(self, _url):
            return [{"name": "wr_vid", "value": "55544444"}]

        async def new_page(self):
            raise AssertionError("valid web session should not open the login page")

    progress_events = []
    runner = WeReadPlaywrightRunner(progress=progress_events.append)
    context = FakeContext()

    assert asyncio.run(runner.ensure_login(context, book_id="4a232bb05c71d64a2ea0506")) is True
    assert len(context.request.urls) == 1
    assert "/web/user?userVid=55544444" in context.request.urls[0][0]
    assert any("已登录" in str(event.get("current") or "") for event in progress_events)


def test_weread_runner_falls_back_to_page_fetch_when_context_request_is_unauthorized():
    class UnauthorizedResponse:
        ok = False
        status = 401
        status_text = "LOGIN ERR"

        def json(self):
            raise AssertionError("unauthorized response body should not be parsed")

    class FakeRequest:
        async def get(self, *_args, **_kwargs):
            return UnauthorizedResponse()

    class FakePage:
        def __init__(self):
            self.goto_calls = []
            self.closed = False

        async def goto(self, url, **kwargs):
            self.goto_calls.append((url, kwargs))

        async def evaluate(self, _script, book_id):
            assert book_id == "dd6324f0813ab9f97g019a24"
            return {
                "title": "页面会话书籍",
                "author": "页面作者",
                "chapters": [{"id": 1, "title": "第一章", "words": 100}],
            }

        async def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()
            self.page = FakePage()

        async def new_page(self):
            return self.page

    progress_events = []
    runner = WeReadPlaywrightRunner(progress=progress_events.append)
    context = FakeContext()

    meta = asyncio.run(runner.fetch_book_meta(context, "dd6324f0813ab9f97g019a24"))

    assert meta["title"] == "页面会话书籍"
    assert context.page.goto_calls[0][0] == "https://weread.qq.com/web/reader/dd6324f0813ab9f97g019a24"
    assert context.page.goto_calls[-1][0] == "https://weread.qq.com/web/shelf"
    assert context.page.closed is True
    assert any("页面会话" in str(event.get("current") or "") for event in progress_events)


def test_weread_runner_ensure_login_waits_when_book_info_returns_401(monkeypatch):
    class FakeResponse:
        def __init__(self, status, status_text=""):
            self.ok = status < 400
            self.status = status
            self.status_text = status_text

    class FakeRequest:
        def __init__(self):
            self.statuses = [401, 401, 200]
            self.urls = []

        async def get(self, url, **_kwargs):
            self.urls.append(url)
            return FakeResponse(self.statuses.pop(0), "LOGIN ERR")

    class FakePage:
        def __init__(self):
            self.goto_calls = []
            self.url = "https://weread.qq.com/web/shelf"
            self.closed = False

        async def goto(self, url, **kwargs):
            self.goto_calls.append((url, kwargs))
            self.url = url

        async def close(self):
            self.closed = True

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()
            self.page = FakePage()

        async def new_page(self):
            return self.page

        async def cookies(self, _url):
            return [{"name": "wr_vid", "value": "55544444"}]

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(weread_core.asyncio, "sleep", fake_sleep)
    progress_events = []
    runner = WeReadPlaywrightRunner(progress=progress_events.append)
    context = FakeContext()

    assert asyncio.run(runner.ensure_login(context, book_id="dd6324f0813ab9f97g019a24")) is True
    assert context.page.goto_calls[0][0] == "https://weread.qq.com/web/shelf"
    assert context.page.goto_calls[1][0] == "https://weread.qq.com/web/login"
    assert context.page.closed is True
    assert len(context.request.urls) == 3
    assert all("/web/user?userVid=55544444" in url for url in context.request.urls)
    assert any("重新登录" in str(event.get("current") or "") for event in progress_events)


def test_launch_chrome_cdp_starts_debuggable_chrome(tmp_path, monkeypatch):
    availability = iter([False, False, True])
    popen_calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))
            self.pid = 1234

    monkeypatch.setattr(weread_core, "chrome_cdp_available", lambda *_args, **_kwargs: next(availability))
    monkeypatch.setattr(weread_core, "find_chrome_executable", lambda: "C:/Chrome/chrome.exe")
    monkeypatch.setattr(weread_core.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(weread_core.time, "sleep", lambda _seconds: None)

    result = weread_core.launch_chrome_cdp(
        endpoint="http://127.0.0.1:9333",
        profile_dir=tmp_path / "profile",
        initial_url="https://weread.qq.com/web/shelf",
        timeout=1,
    )

    assert result["available"] is True
    assert result["started"] is True
    assert result["pid"] == 1234
    args = popen_calls[0][0]
    assert args[0] == "C:/Chrome/chrome.exe"
    assert "--remote-debugging-port=9333" in args
    assert f"--user-data-dir={tmp_path / 'profile'}" in args
    assert "https://weread.qq.com/web/shelf" in args


def test_weread_task_service_auto_starts_cdp_before_runner(db_env, monkeypatch):
    started = []
    runner_endpoints = []

    def fake_ensure(*, data_dir, endpoint=None, profile_dir=None, initial_url=None):
        started.append((data_dir, endpoint, profile_dir, initial_url))
        return {"available": True, "started": True}

    class FakeRunner:
        def __init__(self, *, progress, cancel_check, chrome_cdp_endpoint=None):
            self.progress = progress
            self.cancel_check = cancel_check
            runner_endpoints.append(chrome_cdp_endpoint)

        def run(self, *, book_id, output_dir, cache_dir, save_raw):
            out_path = Path(output_dir) / "测试书.md"
            out_path.write_text("# 测试书\n\n正文", encoding="utf-8")
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
                author="",
                total=1,
                ok=1,
                failed=0,
                skipped=0,
                merged_path=str(out_path),
                meta_path="",
            )

    monkeypatch.setattr(weread_tasks, "configured_browser_mode", lambda: "auto")
    monkeypatch.setattr(weread_tasks, "ensure_chrome_cdp_with_options", fake_ensure)

    service = WeReadExportTaskService(runner_factory=FakeRunner)
    task_id = service.create_task(
        {
            "book": "dd6324f0813ab9f97g019a24",
            "chrome_cdp_endpoint": "http://127.0.0.1:9444",
            "chrome_cdp_profile_dir": str(db_env / "custom-cdp-profile"),
        },
        data_dir=str(db_env),
    )
    service.run_task(task_id)

    assert started == [
        (
            str(db_env),
            "http://127.0.0.1:9444",
            str(db_env / "custom-cdp-profile"),
            "https://weread.qq.com/web/shelf",
        )
    ]
    assert runner_endpoints == ["http://127.0.0.1:9444"]
    assert service.get_task(task_id)["status"] == "done"


def test_weread_task_service_does_not_leave_pending_when_worker_is_busy(db_env):
    class FakeRunner:
        def __init__(self, *, progress, cancel_check):
            self.progress = progress
            self.cancel_check = cancel_check

        def run(self, **_kwargs):
            raise AssertionError("runner should not start while lock is held")

    service = WeReadExportTaskService(runner_factory=FakeRunner, lock_wait_timeout=0)
    task_id = service.create_task({"book": "dd6324f0813ab9f97g019a24"}, data_dir=str(db_env))

    service._run_lock.acquire()
    try:
        service.run_task(task_id)
    finally:
        service._run_lock.release()

    task = service.get_task(task_id)
    assert task["status"] == "error"
    assert task["current"] == "等待启动超时"
    assert "已有微信读书导出任务仍在运行" in task["error"]

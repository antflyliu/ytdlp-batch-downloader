"""Behavior-focused tests for the Web UI batch download flow."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

import server.__main__ as _server_main  # noqa: E402 — actual implementation location


class _ImmediateThread:
    """Run background work synchronously for deterministic tests."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target
        self.daemon = daemon

    def start(self):
        if self._target:
            self._target()


def _build_multipart(parts: list[dict], boundary: str = "test-boundary") -> tuple[bytes, dict[str, str]]:
    chunks: list[bytes] = []
    for part in parts:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        disposition = f'Content-Disposition: form-data; name="{part["name"]}"'
        if part.get("filename") is not None:
            disposition += f'; filename="{part["filename"]}"'
        chunks.append((disposition + "\r\n").encode("utf-8"))
        if part.get("content_type"):
            chunks.append(f'Content-Type: {part["content_type"]}\r\n'.encode("utf-8"))
        chunks.append(b"\r\n")
        chunks.append(part["data"])
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return body, headers


def _make_handler(monitor_server_module):
    handler = object.__new__(monitor_server_module.MonitorHandler)
    sent: list[tuple[int, dict]] = []

    def _send_json(data, status=200):
        sent.append((status, data))

    handler._send_json = _send_json
    return handler, sent


class TestBatchUploadApiBehavior(unittest.TestCase):
    def test_upload_returns_upload_id_and_stores_full_urls(self):
        import monitor_server

        handler, sent = _make_handler(monitor_server)
        body, headers = _build_multipart([{
            "name": "file",
            "filename": "urls.txt",
            "content_type": "text/plain",
            "data": b"https://youtube.com/watch?v=0\n",
        }])
        handler.headers = headers
        handler.rfile = io.BytesIO(body)
        all_urls = [
            f"https://youtube.com/watch?v={idx}"
            for idx in range(6)
        ]
        upload_store = monitor_server._BatchUploadStore()

        with mock.patch.object(_server_main, "_batch_upload_mgr", upload_store):
            with mock.patch("Youtube_Downloader.read_urls_from_file", return_value=all_urls):
                handler._handle_multipart_upload()

        status, payload = sent[-1]
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("upload_id", payload)
        self.assertEqual(payload["filename"], "urls.txt")
        self.assertEqual(payload["url_count"], 6)
        self.assertEqual(payload["preview_urls"], all_urls[:5])
        self.assertNotIn("urls", payload)

        stored = upload_store.get_upload(payload["upload_id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["urls"], all_urls)


class TestBatchStartApiBehavior(unittest.TestCase):
    def test_start_uses_full_server_side_upload_set(self):
        import monitor_server
        from monitor.proxy_router import ProxyRouteResult

        handler, sent = _make_handler(monitor_server)
        upload_store = monitor_server._BatchUploadStore()
        task_mgr = monitor_server._DownloadTaskManager()
        all_urls = [f"https://youtube.com/watch?v={idx}" for idx in range(7)]
        upload_id = upload_store.create_upload("batch.txt", all_urls)

        fake_route = ProxyRouteResult(
            resolved_mode="direct",
            proxy=None,
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="direct",
            reason="直连",
            warnings=[],
            fallback_depth=0,
            masked_proxy_endpoint=None,
            session_mode=None,
            cookies_file_present=False,
        )
        batch_calls: dict[str, object] = {}

        def _fake_batch_download(urls, output_path, resolution, **kwargs):
            batch_calls["urls"] = list(urls)
            batch_calls["output_path"] = output_path
            batch_calls["resolution"] = resolution
            batch_calls["kwargs"] = kwargs
            return [{"URL": url, "状态": "成功", "信息": "ok"} for url in urls]

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "download_output_path": tmpdir,
                "enable_aria2": False,
                "manual_direct_fallback": True,
                "download_cookies_file": "",
            }
            with mock.patch.object(_server_main, "_batch_upload_mgr", upload_store):
                with mock.patch.object(_server_main, "_task_mgr", task_mgr):
                    with mock.patch("server.__main__._db.load_config", return_value=cfg):
                        with mock.patch("server.__main__._db.save_web_batch_task"):
                            with mock.patch("server.__main__.resolve_for_web_batch_download", return_value=fake_route) as mock_route:
                                with mock.patch("server.__main__.log_download_decision"):
                                    with mock.patch("server.__main__.batch_download", side_effect=_fake_batch_download):
                                        with mock.patch("threading.Thread", _ImmediateThread):
                                            handler._api_batch_download_start({
                                                "upload_id": upload_id,
                                                "resolution": "1080p",
                                                "no_subs": True,
                                                "sub_langs": "",
                                                "proxy_pool_id": None,
                                                "cookies_file": None,
                                                "output_path": "",
                                            })

        status, payload = sent[-1]
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["queued"], len(all_urls))
        self.assertEqual(payload["upload_id"], upload_id)
        self.assertEqual(batch_calls["urls"], all_urls)
        self.assertEqual(batch_calls["resolution"], "1080p")
        mock_route.assert_called_once_with(
            proxy_pool_id=None,
            cookies_file_present=False,
            user_forced_direct=False,
        )

        task = task_mgr.get_task(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["total"], len(all_urls))
        self.assertEqual(task["status"], "done")

    def test_start_accepts_global_config_output_path_and_forwards_proxy_pool_id(self):
        import monitor_server
        from monitor.proxy_router import ProxyRouteResult

        handler, sent = _make_handler(monitor_server)
        upload_store = monitor_server._BatchUploadStore()
        task_mgr = monitor_server._DownloadTaskManager()
        upload_id = upload_store.create_upload("batch.csv", ["https://youtube.com/watch?v=1"])

        fake_route = ProxyRouteResult(
            resolved_mode="account_static",
            proxy="http://proxy.example:8080",
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="account_static",
            reason="账户固定代理可用",
            warnings=[],
            fallback_depth=0,
            masked_proxy_endpoint="http://***@proxy.example:8080",
            session_mode=None,
            cookies_file_present=False,
        )
        batch_kwargs: dict[str, object] = {}

        def _fake_batch_download(urls, output_path, resolution, **kwargs):
            batch_kwargs.update(kwargs)
            return [{"URL": urls[0], "状态": "成功", "信息": "ok"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "download_output_path": tmpdir,
                "enable_aria2": False,
                "manual_direct_fallback": True,
                "download_cookies_file": "",
            }
            with mock.patch.object(_server_main, "_batch_upload_mgr", upload_store):
                with mock.patch.object(_server_main, "_task_mgr", task_mgr):
                    with mock.patch("server.__main__._db.load_config", return_value=cfg):
                        with mock.patch("server.__main__._db.save_web_batch_task"):
                            with mock.patch("server.__main__.resolve_for_web_batch_download", return_value=fake_route) as mock_route:
                                with mock.patch("server.__main__.log_download_decision"):
                                    with mock.patch("server.__main__.batch_download", side_effect=_fake_batch_download):
                                        with mock.patch("threading.Thread", _ImmediateThread):
                                            handler._api_batch_download_start({
                                                "upload_id": upload_id,
                                                "resolution": "best",
                                                "no_subs": True,
                                                "proxy_pool_id": "7",
                                                "output_path": "",
                                            })

        status, payload = sent[-1]
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        mock_route.assert_called_once_with(
            proxy_pool_id=7,
            cookies_file_present=False,
            user_forced_direct=False,
        )
        self.assertEqual(batch_kwargs["proxy"], "http://proxy.example:8080")
        self.assertFalse(batch_kwargs["direct_fallback_after_proxies_exhausted"])

    def test_task_status_api_normalizes_download_results(self):
        import monitor_server

        handler, sent = _make_handler(monitor_server)
        task_mgr = monitor_server._DownloadTaskManager()
        task_id = task_mgr.create_task(
            [{"url": "https://youtube.com/watch?v=1"}],
            "D:/videos",
            task_kind="web_batch",
            source_name="urls.txt",
            persist_task=False,
        )
        task_mgr.finish_task(task_id, [{
            "URL": "https://youtube.com/watch?v=1",
            "状态": "成功",
            "信息": "下载成功 | 代理: 直连",
        }])

        with mock.patch.object(_server_main, "_task_mgr", task_mgr):
            handler._api_batch_task_status(task_id)

        status, payload = sent[-1]
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], [{
            "url": "https://youtube.com/watch?v=1",
            "status": "成功",
            "info": "下载成功 | 代理: 直连",
        }])

    def test_resolve_download_output_path_allows_global_config_dir(self):
        import monitor_server

        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = monitor_server._resolve_download_output_path("", {
                "download_output_path": tmpdir,
            })
        self.assertTrue(resolved)

    def test_task_manager_list_sorts_newest_first_and_cleans_old_finished_tasks(self):
        import monitor_server

        mgr = monitor_server._DownloadTaskManager()
        old_finished_at = (datetime.now(timezone.utc) - timedelta(hours=2)).astimezone().isoformat(timespec="seconds")
        fresh_finished_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        mgr._tasks = {
            "old": {
                "task_id": "old",
                "status": "cancelled",
                "total": 1,
                "completed": 1,
                "success": 1,
                "failed": 0,
                "current_video": "",
                "results": [],
                "output_path": "D:/videos",
                "cancel_requested": True,
                "cancel_message": "下载任务已取消",
                "created_at": "2026-04-10T08:00:00+08:00",
                "finished_at": old_finished_at,
            },
            "new": {
                "task_id": "new",
                "status": "done",
                "total": 1,
                "completed": 1,
                "success": 1,
                "failed": 0,
                "current_video": "",
                "results": [],
                "output_path": "D:/videos",
                "cancel_requested": False,
                "cancel_message": None,
                "created_at": "2026-04-10T09:00:00+08:00",
                "finished_at": fresh_finished_at,
            },
        }

        tasks = mgr.list_tasks()
        self.assertEqual([task["task_id"] for task in tasks], ["new"])
        self.assertNotIn("old", mgr._tasks)

    def test_batch_task_history_is_persisted_and_readable_without_in_memory_state(self):
        import monitor.db as db
        import monitor_server

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "monitor.db")
            cfg_path = os.path.join(tmpdir, "config.json")
            with ExitStack() as stack:
                db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
                stack.enter_context(mock.patch.object(db, "_DB_PATH", db_path))
                stack.enter_context(mock.patch.object(db, "_DATA_DIR", tmpdir))
                stack.enter_context(mock.patch.object(db, "_CONFIG_PATH", cfg_path))
                stack.enter_context(mock.patch.object(db_conn, "_DB_PATH", db_path))
                stack.enter_context(mock.patch.object(db_conn, "_DATA_DIR", tmpdir))
                stack.enter_context(mock.patch.object(db_conn, "_CONFIG_PATH", cfg_path))
                db.init_db()

                task_mgr = monitor_server._DownloadTaskManager()
                task_id = task_mgr.create_task(
                    [{"url": "https://youtube.com/watch?v=1"}],
                    "D:/videos",
                    task_kind="web_batch",
                    source_name="urls.txt",
                    persist_task=True,
                )
                task_mgr.update_progress(task_id, 1, "完成第 1/1 个视频")
                task_mgr.finish_task(task_id, [{
                    "URL": "https://youtube.com/watch?v=1",
                    "状态": "成功",
                    "信息": "ok",
                }])
                task_mgr._tasks.clear()

                persisted = db.get_web_batch_task(task_id)
                self.assertIsNotNone(persisted)
                self.assertEqual(persisted["source_name"], "urls.txt")
                self.assertEqual(persisted["status"], "done")

                handler, sent = _make_handler(monitor_server)
                with mock.patch.object(_server_main, "_task_mgr", task_mgr):
                    handler._api_batch_task_status(task_id)

                status, payload = sent[-1]
                self.assertEqual(status, 200)
                self.assertEqual(payload["task_id"], task_id)
                self.assertEqual(payload["source_name"], "urls.txt")
                self.assertEqual(payload["status"], "done")

    def test_init_db_marks_stale_running_web_batch_tasks_interrupted(self):
        import monitor.db as db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "monitor.db")
            cfg_path = os.path.join(tmpdir, "config.json")
            with ExitStack() as stack:
                db_conn = __import__("monitor.db.connection", fromlist=["_DB_PATH"])
                stack.enter_context(mock.patch.object(db, "_DB_PATH", db_path))
                stack.enter_context(mock.patch.object(db, "_DATA_DIR", tmpdir))
                stack.enter_context(mock.patch.object(db, "_CONFIG_PATH", cfg_path))
                stack.enter_context(mock.patch.object(db_conn, "_DB_PATH", db_path))
                stack.enter_context(mock.patch.object(db_conn, "_DATA_DIR", tmpdir))
                stack.enter_context(mock.patch.object(db_conn, "_CONFIG_PATH", cfg_path))
                db.init_db()
                db.save_web_batch_task({
                    "task_id": "stale-task",
                    "task_kind": "web_batch",
                    "source_name": "stale.txt",
                    "persist_task": True,
                    "status": "running",
                    "total": 3,
                    "completed": 1,
                    "success": 1,
                    "failed": 0,
                    "current_video": "still running",
                    "results": [],
                    "output_path": "D:/videos",
                    "created_at": "2026-04-10T10:00:00+08:00",
                    "finished_at": None,
                })

                db.init_db()
                persisted = db.get_web_batch_task("stale-task")
                self.assertEqual(persisted["status"], "error")
                self.assertEqual(persisted["current_video"], "服务重启导致任务中断")

    def test_cancel_endpoint_marks_running_task_and_worker_finishes_as_cancelled(self):
        import monitor_server
        from Youtube_Downloader import BatchDownloadCancelled
        from monitor.proxy_router import ProxyRouteResult

        start_handler, start_sent = _make_handler(monitor_server)
        cancel_handler, cancel_sent = _make_handler(monitor_server)
        upload_store = monitor_server._BatchUploadStore()
        task_mgr = monitor_server._DownloadTaskManager()
        upload_id = upload_store.create_upload("batch.txt", ["https://youtube.com/watch?v=1"])

        fake_route = ProxyRouteResult(
            resolved_mode="direct",
            proxy=None,
            proxy_pool=None,
            provider_name=None,
            provider_tier=None,
            resolved_proxy_source="direct",
            reason="直连",
            warnings=[],
            fallback_depth=0,
            masked_proxy_endpoint=None,
            session_mode=None,
            cookies_file_present=False,
        )
        started = threading.Event()

        def _fake_batch_download(urls, output_path, resolution, **kwargs):
            started.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if kwargs["should_cancel"]():
                    raise BatchDownloadCancelled("下载任务已取消", results=[])
                time.sleep(0.01)
            return []

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "download_output_path": tmpdir,
                "enable_aria2": False,
                "manual_direct_fallback": True,
                "download_cookies_file": "",
            }
            with mock.patch.object(_server_main, "_batch_upload_mgr", upload_store):
                with mock.patch.object(_server_main, "_task_mgr", task_mgr):
                    with mock.patch("server.__main__._db.load_config", return_value=cfg):
                        with mock.patch("server.__main__._db.save_web_batch_task"):
                            with mock.patch("server.__main__.resolve_for_web_batch_download", return_value=fake_route):
                                with mock.patch("server.__main__.log_download_decision"):
                                    with mock.patch("server.__main__.batch_download", side_effect=_fake_batch_download):
                                        start_handler._api_batch_download_start({
                                            "upload_id": upload_id,
                                            "resolution": "best",
                                            "no_subs": True,
                                            "proxy_pool_id": None,
                                            "output_path": "",
                                        })

                                        task_id = start_sent[-1][1]["task_id"]
                                        self.assertTrue(started.wait(timeout=1))

                                        cancel_handler._api_batch_task_cancel(task_id)

                                        deadline = time.time() + 2
                                        while time.time() < deadline:
                                            task = task_mgr.get_task(task_id)
                                            if task and task["status"] == "cancelled":
                                                break
                                            time.sleep(0.01)

        status, payload = cancel_sent[-1]
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "cancelling")

        task = task_mgr.get_task(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "cancelled")
        self.assertTrue(task["cancel_requested"])
        self.assertEqual(task["cancel_message"], "下载任务已取消")


if __name__ == "__main__":
    unittest.main()

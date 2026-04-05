"""
monitor_server.py — YouTube 视频监控 Web 服务
REST API 后端 + 静态文件服务

用法:
    python monitor_server.py              # 启动 Web UI
    python monitor_server.py --port 8765  # 指定端口
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

# ── 项目路径注入 ──────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import monitor.db as _db
import monitor.scheduler as _scheduler
import monitor.cache as _cache
import monitor.quota as _quota
import logging_config
from Youtube_Downloader import batch_download, build_aria2_opts

_log = logging_config.get_logger("monitor_server")


# ── 下载任务管理器 ────────────────────────────────────────────
class _DownloadTaskManager:
    """
    线程安全的后台下载任务管理器。
    每个任务跟踪进度、状态和每个视频的下载结果。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def create_task(self, video_records: list[dict], output_path: str) -> str:
        """创建下载任务，返回 task_id"""
        task_id = uuid.uuid4().hex[:12]
        task = {
            "task_id": task_id,
            "status": "running",
            "total": len(video_records),
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current_video": "",
            "results": [],
            "output_path": output_path,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "finished_at": None,
        }
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def update_progress(self, task_id: str, completed: int, status_text: str):
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t["completed"] = completed
                t["current_video"] = status_text

    def finish_task(self, task_id: str, results: list[dict]):
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t["status"] = "done"
                t["results"] = results
                t["completed"] = t["total"]
                t["success"] = sum(1 for r in results if r.get("状态") == "成功")
                t["failed"] = sum(1 for r in results if r.get("状态") == "失败")
                t["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                t["status"] = "error"
                t["error"] = error
                t["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            t = self._tasks.get(task_id)
            return dict(t) if t else None

    def cleanup_old(self, max_age_sec: int = 3600):
        """清理超过 max_age_sec 的已完成任务"""
        now = datetime.now().astimezone()
        with self._lock:
            to_del = []
            for tid, t in self._tasks.items():
                if t["status"] in ("done", "error") and t.get("finished_at"):
                    try:
                        fin = datetime.fromisoformat(t["finished_at"])
                        if (now - fin).total_seconds() > max_age_sec:
                            to_del.append(tid)
                    except Exception:
                        pass
            for tid in to_del:
                del self._tasks[tid]


_task_mgr = _DownloadTaskManager()

# ── PyInstaller 兼容路径 ───────────────────────────────────────
if getattr(sys, "frozen", False):
    _STATIC_DIR = Path(sys._MEIPASS) / "monitor_web"
else:
    _STATIC_DIR = Path(__file__).parent / "monitor_web"
_INDEX_HTML = _STATIC_DIR / "index.html"


class MonitorHandler(SimpleHTTPRequestHandler):
    """REST API + 静态文件服务器"""

    # ── 工具方法 ─────────────────────────────────────────────

    def _send_json(self, data, status=200):
        """发送 JSON 响应（含 CORS headers）"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_json(self):
        """读取并解析 JSON 请求体，失败返回 None"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(content_length))
        except Exception:
            return None

    def _path_only(self):
        """去掉查询字符串，只保留路径"""
        return self.path.split("?")[0]

    def _require_auth(self):
        """验证 Bearer token，失败返回 401"""
        if not hasattr(MonitorHandler, "_api_token") or MonitorHandler._api_token is None:
            # 优先环境变量，回退数据库
            MonitorHandler._api_token = os.environ.get("MONITOR_API_TOKEN") or _db.get_api_token()
        token = MonitorHandler._api_token
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json({"error": "未授权，请提供 Bearer token"}, 401)
            return False
        provided = auth_header[7:]
        if not secrets.compare_digest(provided, token):
            self._send_json({"error": "无效的 token"}, 401)
            return False
        return True

    def _mask_key(self, key_value: str) -> str:
        """返回 API Key 的掩码版本（首4+末4字符）"""
        if len(key_value) <= 12:
            return key_value[:4] + "••••••"
        return key_value[:4] + "••••••••" + key_value[-4:]

    # ── HTTP 方法 ────────────────────────────────────────────

    def do_GET(self):
        path = self._path_only()
        # /api/status 是健康检查，跳过认证
        if path == "/api/status":
            self._api_status()
            return
        # 其余所有 /api/* 均需认证
        if not self._require_auth():
            return
        if path == "/api/accounts":
            self._api_accounts()
        elif path == "/api/events":
            self._api_events()
        elif path == "/api/stats":
            self._api_stats()
        elif path == "/api/config":
            self._api_config()
        elif path == "/api/token":
            self._api_token_info()
        elif path == "/api/cache":
            self._api_cache_list()
        elif path == "/api/quota":
            self._api_quota()
        elif path == "/api/api-keys":
            self._api_api_keys_list()
        elif path.startswith("/api/api-keys/"):
            parts = path.split("/")
            action = parts[-1]
            if action == "add":
                self._api_api_key_add(self._read_json() or {})
            elif action.isdigit():
                self._api_api_key_update(int(action), self._read_json() or {})
        elif path.startswith("/api/download-tasks/"):
            task_id = path.split("/")[-1]
            self._api_download_task_status(task_id)
        elif path.startswith("/api/accounts/") and "/videos" in path:
            acc_id = path.split("/")[3]
            self._api_account_videos(acc_id)
        else:
            super().do_GET()

    def do_POST(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        body = self._read_json()
        if body is None:
            self._send_json({"error": "invalid json body"}, 400)
            return
        path = self._path_only()
        if path == "/api/scheduler/start":
            self._api_scheduler_start(body)
        elif path == "/api/scheduler/stop":
            self._api_scheduler_stop()
        elif path == "/api/scheduler/reload":
            self._api_scheduler_reload()
        elif path == "/api/accounts":
            self._api_account_add(body)
        elif path == "/api/accounts/scan":
            self._api_account_scan(body)
        elif path.startswith("/api/accounts/") and "/videos/batch-download" in path:
            acc_id = path.split("/")[3]
            self._api_account_videos_batch_download(acc_id, body)
        elif path == "/api/config":
            self._api_config_save(body)
        elif path == "/api/api-keys":
            self._api_api_key_add(body)
        elif path.startswith("/api/api-keys/") and path.endswith("/update"):
            key_id_str = path.split("/")[-2]
            if key_id_str.isdigit():
                self._api_api_key_update(int(key_id_str), body)
        elif path.startswith("/api/api-keys/"):
            pass  # handled in do_GET/do_DELETE; POST via /api/api-keys or /api/api-keys/{id}/update
        elif path == "/api/cache/refresh":
            self._api_cache_refresh(body)
        elif path == "/api/cache/clear":
            self._api_cache_clear()
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_DELETE(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        path = self._path_only()
        if path.startswith("/api/accounts/"):
            acc_id = path.split("/")[-1]
            self._api_account_delete(acc_id)
        elif path.startswith("/api/api-keys/"):
            key_id = path.split("/")[-1]
            if key_id.isdigit():
                self._api_api_key_delete(int(key_id))
        elif path.startswith("/api/cache/"):
            handle = path.split("/api/cache/", 1)[-1]
            self._api_cache_delete(handle)
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ── REST API ────────────────────────────────────────────

    def _api_status(self):
        is_running = _scheduler.is_running()
        next_runs = _scheduler.get_next_run_times() if is_running else []
        self._send_json({"running": is_running, "next_runs": next_runs})

    def _api_accounts(self):
        accounts = _db.list_accounts()
        result = [{
            "id": a["id"],
            "name": a["name"],
            "channel_url": a["channel_url"],
            "api_key_env": a["api_key_env"],
            "api_key_id": a.get("api_key_id"),   # 新增
            "fetch_mode": a["fetch_mode"],
            "fetch_limit": a["fetch_limit"],
            "scan_interval": a["scan_interval"],
            "enabled": bool(a["enabled"]),
            "notify_enabled": bool(a["notify_enabled"]),
            "notify_platform": a["notify_platform"],
            "webhook_url": a["webhook_url"] or "",
            "feishu_message_mode": a.get("feishu_message_mode", "card_json"),
            "feishu_template_id": a.get("feishu_template_id") or "",
            "feishu_scan_template_id": a.get("feishu_scan_template_id") or "",
        } for a in accounts]
        self._send_json(result)

    def _api_events(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        limit = int(params.get("limit", ["20"])[0])
        events = _db.get_recent_events(limit)
        result = [{
            "id": e["id"],
            "account_name": e["account_name"],
            "channel_url": e["channel_url"],
            "status": e["status"],
            "total_videos": e["total_videos"],
            "new_videos": e["new_videos"],
            "error_message": e["error_message"] or "",
            "duration_ms": e["duration_ms"],
            "scan_started_at": e["scan_started_at"],
            "scan_ended_at": e["scan_ended_at"] or "",
        } for e in events]
        self._send_json(result)

    def _api_stats(self):
        rows = _db.get_account_stats()
        result = [{
            "id": r["id"],
            "name": r["name"],
            "channel_url": r["channel_url"],
            "total_scans": r["total_scans"],
            "total_new_videos": r["total_new_videos"],
            "last_scan_at": r["last_scan_at"] or "",
            "is_running": bool(r["is_running"]),
        } for r in rows]
        self._send_json(result)

    def _api_config(self):
        """
        GET /api/config — 获取全局配置
        返回包含 default_sub_langs、download_cookies_file 等所有配置项
        """
        self._send_json(_db.load_config())

    def _api_token_info(self):
        """GET /api/token — 返回当前 Bearer token（需认证）"""
        token = os.environ.get("MONITOR_API_TOKEN") or _db.get_api_token()
        self._send_json({"token": token})

    def _api_config_save(self, body):
        """
        POST /api/config — 保存全局配置
        可保存: global_feishu_url, global_dingtalk_url, global_wecom_url,
               quota_budget_per_day, download_cookies_file, download_output_path,
               enable_aria2, default_sub_langs
        """
        cfg = _db.load_config()
        for key in ["global_feishu_url", "global_dingtalk_url", "global_wecom_url",
                    "quota_budget_per_day", "download_cookies_file", "download_output_path",
                    "enable_aria2", "default_sub_langs", "default_api_key_id"]:
            if key in body:
                cfg[key] = body[key]
        path = _db.get_config_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        _scheduler.set_global_feishu_url(cfg.get("global_feishu_url") or None)
        _scheduler.set_global_dingtalk_url(cfg.get("global_dingtalk_url") or None)
        _scheduler.set_global_wecom_url(cfg.get("global_wecom_url") or None)
        self._send_json({"ok": True})

    def _api_scheduler_start(self, body: dict):
        auto_dl = bool(body.get("auto_download", False))
        ok = _scheduler.start(auto_download=auto_dl)
        self._send_json({"ok": ok})

    def _api_scheduler_stop(self):
        ok = _scheduler.stop()
        self._send_json({"ok": ok})

    def _api_scheduler_reload(self):
        n = _scheduler.reload_jobs()
        self._send_json({"ok": True, "active_jobs": n})

    def _api_account_add(self, body):
        try:
            account_id = body.get("id")
            # api_key_id: None=清空, 0=清空, >0=指定Key, absent=_UNSET(不修改)
            api_key_id_val = body.get("api_key_id")
            api_key_id_param = None  # None = _UNSET (不修改)
            if api_key_id_val is not None:
                api_key_id_param = int(api_key_id_val) if api_key_id_val else None

            if account_id:
                # 编辑模式 → UPDATE
                _db.update_account(
                    account_id=int(account_id),
                    name=body.get("name", ""),
                    channel_url=body.get("channel_url", ""),
                    api_key_env=body.get("api_key_env"),
                    fetch_mode=body.get("fetch_mode"),
                    fetch_limit=int(body["fetch_limit"]) if str(body.get("fetch_limit", "")).isdigit() else None,
                    scan_interval=int(body["scan_interval"]) if str(body.get("scan_interval", "")).isdigit() else None,
                    enabled=bool(body.get("enabled")) if "enabled" in body else None,
                    notify_enabled=bool(body.get("notify_enabled")) if "notify_enabled" in body else None,
                    notify_platform=body.get("notify_platform"),
                    webhook_url=body.get("webhook_url") or None,
                    feishu_message_mode=body.get("feishu_message_mode"),
                    feishu_template_id=body.get("feishu_template_id") or None,
                    feishu_scan_template_id=body.get("feishu_scan_template_id") or None,
                    api_key_id=api_key_id_param,
                )
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self._send_json({"ok": True, "id": account_id})
            else:
                # 新增模式 → INSERT
                account_id = _db.add_account(
                    name=body.get("name", ""),
                    channel_url=body.get("channel_url", ""),
                    api_key_env=body.get("api_key_env", "YOUTUBE_Data_API_V3"),
                    fetch_mode=body.get("fetch_mode", "playlist"),
                    fetch_limit=int(body.get("fetch_limit", 5)),
                    scan_interval=int(body.get("scan_interval", 5)),
                    notify_enabled=bool(body.get("notify_enabled", True)),
                    notify_platform=body.get("notify_platform", "feishu"),
                    webhook_url=body.get("webhook_url") or None,
                    feishu_message_mode=body.get("feishu_message_mode", "card_json"),
                    feishu_template_id=body.get("feishu_template_id") or None,
                    feishu_scan_template_id=body.get("feishu_scan_template_id") or None,
                    api_key_id=api_key_id_param,
                )
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self._send_json({"ok": True, "id": account_id})
        except Exception:
            _log.error("账户操作异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_account_scan(self, body):
        acc_id = int(body.get("account_id", 0))
        auto_dl = bool(body.get("auto_download", False))
        _scheduler.trigger_scan(acc_id, auto_download=auto_dl)
        self._send_json({"ok": True})

    def _api_account_delete(self, acc_id):
        try:
            _db.delete_account(int(acc_id))
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("账户删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_cache_list(self):
        """GET /api/cache — 列出所有缓存"""
        self._send_json(_cache.list_all_cache())

    def _api_cache_refresh(self, body):
        """POST /api/cache/refresh — 从 API 刷新指定 handle 的缓存"""
        handle = body.get("handle", "")
        api_key = body.get("api_key", "")
        if not handle or not api_key:
            self._send_json({"error": "handle 和 api_key 均必填"}, 400)
            return
        result = _cache.refresh_from_api(handle, api_key)
        self._send_json(result, 200 if result["success"] else 500)

    def _api_cache_delete(self, handle):
        """DELETE /api/cache/{handle} — 删除指定缓存"""
        ok = _cache.delete_channel_meta(handle)
        self._send_json({"ok": ok})

    def _api_cache_clear(self):
        """POST /api/cache/clear — 清空所有缓存"""
        count = _cache.clear_all_cache()
        self._send_json({"ok": True, "cleared": count})

    def _api_quota(self):
        """GET /api/quota — 获取所有 API Key 今日 quota 使用情况"""
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        rows = _quota.get_all_usage(today)
        # 补充 per-key 配额上限，掩码 key_value
        for row in rows:
            raw_key = row.get("api_key_env", "")
            if raw_key:
                row["api_key_env"] = self._mask_key(raw_key)
            ak = _db.get_api_key_by_value(raw_key) if raw_key else None
            if ak:
                row["daily_quota"] = ak.get("daily_quota", 8000)
                row["key_name"] = ak.get("name", "")
                row["is_active"] = bool(ak.get("is_active"))
            else:
                row["daily_quota"] = 8000
                row["key_name"] = ""
                row["is_active"] = True
        self._send_json({"items": rows})

    # ── API Key CRUD ─────────────────────────────────────────

    def _api_api_keys_list(self):
        """GET /api/api-keys — 列出所有 API Key（key_value 已掩码）"""
        keys = _db.list_api_keys()
        result = [{
            "id": k["id"],
            "name": k["name"],
            "key_value": self._mask_key(k["key_value"]),
            "daily_quota": k["daily_quota"],
            "quota_used": k.get("quota_used") or 0,
            "scans_done": k.get("scans_done") or 0,
            "blocked_scans": k.get("blocked_scans") or 0,
            "is_active": bool(k["is_active"]),
            "created_at": k["created_at"],
        } for k in keys]
        self._send_json(result)

    def _api_api_key_add(self, body):
        """POST /api/api-keys — 新增 API Key"""
        try:
            key_value = body.get("key_value", "").strip()
            name = body.get("name", "").strip()
            daily_quota = int(body.get("daily_quota", 10000)) if str(body.get("daily_quota", "")).isdigit() else 10000
            if not key_value or not name:
                self._send_json({"error": "API Key 和名称均不能为空"}, 400)
                return
            key_id = _db.add_api_key(key_value, name, daily_quota)
            self._send_json({"ok": True, "id": key_id})
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                self._send_json({"error": "该 API Key 已存在"}, 400)
            else:
                _log.error("API Key 操作异常", exc_info=True)
                self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_api_key_update(self, key_id: int, body):
        """POST /api/api-keys/{id} — 更新 API Key"""
        try:
            name = body.get("name")
            key_value = body.get("key_value", "").strip() or None
            daily_quota = int(body["daily_quota"]) if str(body.get("daily_quota", "")).isdigit() else None
            is_active = bool(body.get("is_active")) if "is_active" in body else None
            _db.update_api_key(
                key_id,
                name=name if name else None,
                key_value=key_value,
                daily_quota=daily_quota,
                is_active=is_active,
            )
            self._send_json({"ok": True})
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                self._send_json({"error": "该 API Key 已存在"}, 400)
            else:
                _log.error("API Key 更新异常", exc_info=True)
                self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_api_key_delete(self, key_id: int):
        """DELETE /api/api-keys/{id} — 删除 API Key"""
        try:
            _db.delete_api_key(key_id)
            self._send_json({"ok": True})
        except Exception:
            _log.error("API Key 删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_account_videos(self, acc_id: str):
        """GET /api/accounts/{id}/videos — 分页查询账户视频"""
        try:
            acc_id_int = int(acc_id)
        except ValueError:
            self._send_json({"error": "无效账户 ID"}, 400)
            return

        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)

        title_kw = params.get("title_kw", [None])[0] or None
        url_kw   = params.get("url_kw",   [None])[0] or None
        sort_by   = params.get("sort_by",   ["published_at"])[0]
        sort_dir  = params.get("sort_dir",  ["desc"])[0]
        page      = int(params.get("page",  ["1"])[0])
        page_size = int(params.get("page_size", ["20"])[0])

        videos, total = _db.get_account_videos(
            account_id=acc_id_int,
            title_kw=title_kw,
            url_kw=url_kw,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=min(page_size, 100),
        )
        self._send_json({
            "videos": videos,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        })

    def _api_account_videos_batch_download(self, acc_id: str, body: dict):
        """
        POST /api/accounts/{id}/videos/batch-download — 批量下载视频（Python yt_dlp 库）

        Request Body:
            video_ids    (int[])   必填，monitor_videos 表的主键 ID 列表
            sub_langs   (str)     可选，字幕语言代码，逗号分隔，如 "zh-Hans,en"
                                 仅在 no_subs=False 时生效；Web UI 字幕开关开启时传入
            no_subs     (bool)    可选，默认 True（不下载字幕，避免 WhisperX 拖慢）
                                 设为 False + sub_langs 有值时，yt-dlp 下载官方字幕
            output_path (str)     可选，下载保存路径，未填则取全局配置。
                                 已通过规范化 + 允许根目录校验防目录穿越。
            cookies_file(str)     可选，Cookie 文件路径，未填则取全局配置

        Response:
            200: {ok: true, task_id: str, queued: int}
            400: {error: "未选择视频" | "video_ids 必须为数组" | "video_ids 数组元素必须为整数" | ...}
            404: {error: "未找到视频记录"}
        """
        video_ids = body.get("video_ids", [])
        if not isinstance(video_ids, list):
            self._send_json({"error": "video_ids 必须为数组"}, 400)
            return
        for vid in video_ids:
            if not isinstance(vid, int):
                self._send_json({"error": "video_ids 数组元素必须为整数"}, 400)
                return
        if not video_ids:
            self._send_json({"error": "未选择视频"}, 400)
            return

        cfg = _db.load_config()

        output_path = body.get("output_path", "").strip()
        if not output_path:
            output_path = cfg.get("download_output_path", "").strip()
        if not output_path:
            output_path = os.path.join(_PROJECT_ROOT, "videos")

        # 路径安全校验：规范化并限制在允许范围内
        abs_output = os.path.abspath(output_path)
        abs_root = os.path.abspath(_PROJECT_ROOT)
        # 允许：项目根目录下任何子目录 + 全局配置中明确设置的路径
        cfg_abs = os.path.abspath(cfg.get("download_output_path", "")) if cfg.get("download_output_path") else ""
        allowed_roots = [abs_root, cfg_abs] if cfg_abs else [abs_root]
        if not any(abs_output.startswith(r) for r in allowed_roots):
            self._send_json({"error": "输出路径必须在允许范围内"}, 400)
            return

        os.makedirs(abs_output, exist_ok=True)

        video_records = _db.get_videos_by_ids(video_ids)
        if not video_records:
            self._send_json({"error": "未找到视频记录"}, 404)
            return

        urls = [v["url"] for v in video_records if v.get("url")]
        if not urls:
            self._send_json({"error": "视频记录中无有效 URL"}, 400)
            return

        task_id = _task_mgr.create_task(video_records, abs_output)
        _log.info(f"创建下载任务: task_id={task_id} 视频数={len(urls)} 输出={abs_output}")

        _db.update_videos_download_status(video_ids, "downloading")

        sub_langs = body.get("sub_langs")   # Web UI 显式传入，未传则不下载字幕
        no_subs = body.get("no_subs", True)  # 默认不下载字幕（避免 WhisperX 拖慢）
        cookies_file = body.get("cookies_file") or cfg.get("download_cookies_file", "") or None
        # cookies_file 存在性校验（不存在时 yt-dlp 静默跳过，但给出提示）
        if cookies_file and not os.path.isfile(cookies_file):
            _log.warning(f"Cookie 文件不存在，将跳过 Cookie: {cookies_file}")
            cookies_file = None
        enable_aria2 = bool(cfg.get("enable_aria2", False))
        extra_ydl_opts = build_aria2_opts() if enable_aria2 else None

        def _bg_download():
            try:
                def progress_cb(progress, status_text):
                    completed = int(progress * len(urls))
                    _task_mgr.update_progress(task_id, completed, status_text)

                results = batch_download(
                    urls,
                    abs_output,
                    'best',
                    progress_callback=progress_cb,
                    sub_langs=sub_langs if not no_subs else None,
                    no_subs=no_subs,
                    cookies_file=cookies_file,
                    extra_ydl_opts=extra_ydl_opts,
                )

                _task_mgr.finish_task(task_id, results)

                url_to_vid = {v["url"]: v["id"] for v in video_records}
                success_ids = []
                failed_ids = []
                for r in results:
                    vid = url_to_vid.get(r.get("URL"))
                    if not vid:
                        continue
                    if r.get("状态") == "成功":
                        success_ids.append(vid)
                    else:
                        failed_ids.append(vid)

                now_str = _db.now_iso()
                if success_ids:
                    _db.update_videos_download_status(
                        success_ids, "downloaded",
                        download_at=now_str,
                        download_path=abs_output,
                    )
                if failed_ids:
                    _db.update_videos_download_status(
                        failed_ids, "failed",
                        download_error="yt-dlp 下载失败",
                    )

                _log.info(f"下载任务完成: task_id={task_id} 成功={len(success_ids)} 失败={len(failed_ids)}")

            except Exception as e:
                _task_mgr.fail_task(task_id, str(e))
                _db.update_videos_download_status(video_ids, "failed", download_error=str(e))
                _log.error(f"下载任务异常: task_id={task_id} error={e}")

        threading.Thread(target=_bg_download, daemon=True).start()

        self._send_json({
            "ok": True,
            "task_id": task_id,
            "queued": len(urls),
            "message": f"{len(urls)} 个视频已开始下载",
        })

    def _api_download_task_status(self, task_id: str):
        """GET /api/download-tasks/{task_id} — 查询下载任务进度"""
        task = _task_mgr.get_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json({
            "task_id": task["task_id"],
            "status": task["status"],
            "total": task["total"],
            "completed": task["completed"],
            "success": task["success"],
            "failed": task["failed"],
            "current_video": task.get("current_video", ""),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "finished_at": task.get("finished_at"),
        })

    # ── 静态文件服务覆盖 ──────────────────────────────────────

    def translate_path(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        return str(_STATIC_DIR / path.lstrip("/"))


def serve(port: int = 5000):
    os.makedirs(_STATIC_DIR, exist_ok=True)
    if not _INDEX_HTML.exists():
        _log.error(f"index.html not found at {_STATIC_DIR}")
        _INDEX_HTML.write_text("<html><body><h1>UI not found</h1></body></html>", encoding="utf-8")
    server = HTTPServer(("127.0.0.1", port), MonitorHandler)
    print(f"\n🌐 监控 Web UI: http://127.0.0.1:{port}")
    print("   按 Ctrl+C 停止\n")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="YouTube Monitor Web Server")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _db.init_db()
    _db.ensure_app_state_table()

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    serve(args.port)


if __name__ == "__main__":
    main()

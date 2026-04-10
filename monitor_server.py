"""
monitor_server.py — YouTube 视频监控 Web 服务
REST API 后端 + 静态文件服务

用法:
    python monitor_server.py              # 启动 Web UI
    python monitor_server.py --port 8765  # 指定端口
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import secrets
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver
from pathlib import Path
from urllib.parse import parse_qs

# ── 项目路径注入 ──────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import monitor.db as _db
import monitor.scheduler as _scheduler
import monitor.provider_scheduler as _provider_scheduler
import monitor.cache as _cache
import monitor.quota as _quota
import logging_config
from Youtube_Downloader import batch_download, build_aria2_opts
from monitor.dynamic_provider_resolver import resolve_for_manual_download, log_download_decision

_log = logging_config.get_logger("monitor_server")

# ── 速率限制器（每 IP 每分钟 N 次请求；本机回环默认豁免，见 _check_rate_limit）──
_RATE_LIMIT_WINDOW = 60  # 秒
_RATE_LIMIT_MAX = 600    # 非回环客户端每窗口上限（仪表盘 + 多弹窗轮询仍可能触顶）
_rate_limiter: dict[str, collections.deque] = {}
_rate_limiter_lock = threading.Lock()


def _get_client_ip() -> str:
    """从请求中提取真实 IP（支持 X-Forwarded-For）"""
    # SimpleHTTPRequestHandler 不提供 parsed headers as dict,
    # 用 self.headers.get directly in handler context
    return ""  # placeholder, overridden in handler


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

    def list_tasks(self) -> list:
        """返回所有任务列表。"""
        with self._lock:
            return [dict(t) for t in self._tasks.values()]

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


_YOUTUBE_URL_RE = re.compile(
    r"^https://(www\.)?(youtube\.com|youtu\.be)/"
)
_YOUTUBE_HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,100}$")
_YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,40}$")


def _is_valid_youtube_url(url: str) -> bool:
    """验证频道输入是否合法：支持 @handle、UC 频道 ID 或完整 YouTube URL（防 javascript: 等伪协议注入）"""
    if not url:
        return False
    value = url.strip()
    return (
        _YOUTUBE_URL_RE.match(value) is not None
        or _YOUTUBE_HANDLE_RE.match(value) is not None
        or _YOUTUBE_CHANNEL_ID_RE.match(value) is not None
    )


class MonitorHandler(SimpleHTTPRequestHandler):
    """REST API + 静态文件服务器"""

    # ── 工具方法 ─────────────────────────────────────────────

    # localhost origin 白名单（CORS L-3）
    _LOCALHOST_ORIGIN_RE = re.compile(
        r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    )

    def _allowed_origin(self) -> str | None:
        """返回允许的 CORS origin，若请求 origin 不在白名单则返回 None"""
        origin = self.headers.get("Origin", "")
        if self._LOCALHOST_ORIGIN_RE.match(origin):
            return origin
        return None

    def _rate_limit_client_ip(self) -> str:
        """客户端 IP（优先 X-Forwarded-For 首段）。"""
        xff = self.headers.get("X-Forwarded-For", "")
        return (xff.split(",")[0].strip() if xff else self.client_address[0]) or ""

    def _rate_limit_exempt_loopback(self, ip: str) -> bool:
        """本机访问不做全局限流（单用户监控台易与轮询叠加导致误伤 429）。"""
        if not ip:
            return False
        ip = ip.strip()
        if ip in ("127.0.0.1", "::1"):
            return True
        if ip.startswith("127."):
            return True
        if ip.startswith("::ffff:127."):
            return True
        return False

    def _check_rate_limit(self) -> bool:
        """
        速率限制：每 IP 每分钟最多 _RATE_LIMIT_MAX 次请求。
        返回 True 表示通过，False 表示触发限流（已发送 429）。
        """
        ip = self._rate_limit_client_ip()
        if self._rate_limit_exempt_loopback(ip):
            return True
        now = time.time()
        with _rate_limiter_lock:
            if ip not in _rate_limiter:
                _rate_limiter[ip] = collections.deque(maxlen=_RATE_LIMIT_MAX)
            times = _rate_limiter[ip]
            # 清理过期时间戳
            cutoff = now - _RATE_LIMIT_WINDOW
            while times and times[0] < cutoff:
                times.popleft()
            if len(times) >= _RATE_LIMIT_MAX:
                self.send_response(429)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Retry-After", str(_RATE_LIMIT_WINDOW))
                origin = self._allowed_origin()
                if origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": "请求过于频繁，请稍后再试"}, ensure_ascii=False).encode("utf-8")
                )
                return False
            times.append(now)
        return True

    def _path_skips_rate_limit(self, path: str) -> bool:
        """不参与全局限流的路径（高频只读轮询；仅 do_GET 调用）。"""
        if path.startswith("/api/download-tasks/"):
            return True
        if path in ("/api/provider-scheduler/logs", "/api/provider-scheduler/status"):
            return True
        return False

    def _send_json(self, data, status=200):
        """发送 JSON 响应（含 CORS headers）"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
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

    def _mask_proxy_url(self, url: str) -> str:
        """返回代理 URL 的掩码版本（隐藏认证信息）"""
        if not url:
            return url
        # 处理 user:pass@host:port 格式
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)
            if parsed.username:
                netloc = f"***@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        except Exception:
            pass
        # 回退：包含 @ 则说明有认证信息，掩码
        if '@' in url:
            scheme, rest = url.split('://', 1)
            return f"{scheme}://***@{rest.split('@', 1)[1]}"
        return url

    # ── HTTP 方法 ────────────────────────────────────────────

    def do_GET(self):
        path = self._path_only()
        # 非 API 路径视为静态资源，匿名访问；路径安全由 translate_path() + resolve 边界保证
        if not path.startswith("/api/"):
            try:
                super().do_GET()
            except (ConnectionAbortedError, BrokenPipeError):
                _log.warning("静态响应期间客户端中断连接: %s", path)
            return
        # /api/status 是健康检查，跳过认证和限流
        if path == "/api/status":
            self._api_status()
            return
        # 其余所有 /api/* 均需认证和限流
        if not self._require_auth():
            return
        if not self._path_skips_rate_limit(path) and not self._check_rate_limit():
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
        elif path == "/api/proxy-pools":
            self._api_proxy_pools_list()
        elif path == "/api/dynamic-providers":
            self._api_dynamic_providers_list()
        elif path == "/api/provider-scheduler/status":
            self._api_provider_scheduler_status()
        elif path == "/api/provider-scheduler/logs":
            self._api_provider_scheduler_logs()
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/candidates/preview"):
            pid = path.split("/")[-3]
            if pid.isdigit():
                self._api_dynamic_provider_candidates_preview(int(pid))
            else:
                self._send_json({"error": "无效的提供方 ID"}, 400)
        elif path == "/api/routing-preview":
            self._api_routing_preview()
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
        elif path == "/api/batch/tasks":
            self._api_batch_tasks_list()
        elif path.startswith("/api/batch/tasks/"):
            task_id = path.split("/")[-1]
            self._api_batch_task_status(task_id)
        else:
            super().do_GET()

    def do_HEAD(self):
        path = self._path_only()
        # 非 API 路径视为静态资源，匿名访问
        if not path.startswith("/api/"):
            super().do_HEAD()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
            return
        self.send_error(404, "未知 API")

    def do_POST(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
            return
        path = self._path_only()
        if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
            if path == "/api/batch/upload":
                self._handle_multipart_upload()
                return
            self._send_json({"error": "未知 multipart API"}, 404)
            return
        body = self._read_json()
        if body is None:
            self._send_json({"error": "invalid json body"}, 400)
            return
        if path == "/api/scheduler/start":
            self._api_scheduler_start(body)
        elif path == "/api/scheduler/stop":
            self._api_scheduler_stop()
        elif path == "/api/scheduler/reload":
            self._api_scheduler_reload()
        elif path == "/api/provider-scheduler/start":
            self._api_provider_scheduler_start()
        elif path == "/api/provider-scheduler/stop":
            self._api_provider_scheduler_stop()
        elif path == "/api/provider-scheduler/reload":
            self._api_provider_scheduler_reload()
        elif path == "/api/provider-scheduler/run-once":
            self._api_provider_scheduler_run_once()
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
        elif path == "/api/proxy-pools":
            self._api_proxy_pool_add(body)
        elif path == "/api/dynamic-providers":
            self._api_dynamic_provider_add(body)
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/update"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_update(int(pid), body)
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/health-check"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_health_check(int(pid))
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/refresh"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_refresh(int(pid))
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/cooldown/clear"):
            pid = path.split("/")[-3]
            if pid.isdigit():
                self._api_dynamic_provider_cooldown_clear(int(pid))
        elif path == "/api/system/shutdown":
            self._api_system_shutdown()
        elif path.startswith("/api/proxy-pools/") and path.endswith("/update"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_proxy_pool_update(int(pid), body)
        elif path == "/api/batch/upload":
            self._handle_multipart_upload()
        elif path == "/api/batch/start":
            self._api_batch_download_start(body)
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_DELETE(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
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
        elif path.startswith("/api/proxy-pools/"):
            pid = path.split("/")[-1]
            if pid.isdigit():
                self._api_proxy_pool_delete(int(pid))
        elif path.startswith("/api/dynamic-providers/"):
            pid = path.split("/")[-1]
            if pid.isdigit():
                self._api_dynamic_provider_delete(int(pid))
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ── REST API ────────────────────────────────────────────

    def _api_status(self):
        is_running = _scheduler.is_running()
        next_runs = _scheduler.get_next_run_times() if is_running else []
        self._send_json({"running": is_running, "next_runs": next_runs})

    def _api_system_shutdown(self):
        """POST /api/system/shutdown — 安全关闭当前 Web UI 进程（需 Bearer token）"""
        self._send_json({"ok": True, "message": "server shutting down"})
        threading.Thread(target=self.server.shutdown, daemon=True, name="monitor-server-shutdown").start()

    def _api_accounts(self):
        accounts = _db.list_accounts()
        result = [{
            "id": a["id"],
            "name": a["name"],
            "channel_url": a["channel_url"],
            "api_key_env": a["api_key_env"],
            "api_key_id": a.get("api_key_id"),
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
            "proxy_pool_id": a.get("proxy_pool_id"),
            "proxy_enabled": bool(a.get("proxy_enabled", 0)),
            "download_proxy_mode": a.get("download_proxy_mode", "auto"),
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
               enable_aria2, default_sub_langs, default_api_key_id
        """
        cfg = _db.load_config()
        for key in [
            "global_feishu_url", "global_dingtalk_url", "global_dingtalk_sign_secret", "global_wecom_url",
            "quota_budget_per_day", "download_cookies_file", "download_output_path",
            "enable_aria2", "default_sub_langs", "default_api_key_id",
            # 系统默认动态代理配置
            "system_dynamic_proxy_enabled", "apply_dynamic_proxy_to_new_accounts",
            "apply_dynamic_proxy_to_existing_accounts", "manual_download_route_policy",
            "auto_download_route_policy", "allow_free_proxy",
            "allow_free_proxy_for_auto_download", "allow_free_proxy_with_cookies",
            "manual_direct_fallback", "auto_direct_fallback",
            "default_proxy_country_codes", "default_proxy_protocol_order",
            "default_session_mode", "default_sticky_minutes",
            "candidate_prefetch_count", "candidate_validate_count",
            "validated_pool_ttl_seconds", "provider_cooldown_seconds",
            "proxy_probe_timeout_seconds", "mask_proxy_in_logs",
        ]:
            if key in body:
                cfg[key] = body[key]
        # 校验 default_api_key_id 引用有效性
        default_key_id = cfg.get("default_api_key_id")
        if default_key_id:
            ak = _db.get_api_key(default_key_id)
            if not ak:
                self._send_json({"error": f"指定的默认 API Key (id={default_key_id}) 不存在"}, 400)
                return
        try:
            _db.save_config(cfg)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        _scheduler.set_global_feishu_url(cfg.get("global_feishu_url") or None)
        _scheduler.set_global_dingtalk_url(cfg.get("global_dingtalk_url") or None)
        _scheduler.set_global_dingtalk_sign_secret(cfg.get("global_dingtalk_sign_secret") or None)
        _scheduler.set_global_wecom_url(cfg.get("global_wecom_url") or None)
        _scheduler._invalidate_config_cache()
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

    def _api_provider_scheduler_status(self):
        running = _provider_scheduler.is_running()
        next_runs = _provider_scheduler.get_next_run_times() if running else []
        self._send_json({"running": running, "next_runs": next_runs})

    def _api_provider_scheduler_logs(self):
        self._send_json(_db.list_provider_scheduler_runs())

    def _api_provider_scheduler_start(self):
        ok = _provider_scheduler.start()
        self._send_json({"ok": ok})

    def _api_provider_scheduler_stop(self):
        ok = _provider_scheduler.stop()
        self._send_json({"ok": ok})

    def _api_provider_scheduler_reload(self):
        n = _provider_scheduler.reload_jobs()
        self._send_json({"ok": True, "active_jobs": n})

    def _api_provider_scheduler_run_once(self):
        result = _provider_scheduler.run_once()
        self._send_json(result)

    def _api_account_add(self, body):
        try:
            # 基础验证
            if not body.get("name", "").strip():
                self._send_json({"error": "账户名称不能为空"}, 400)
                return
            channel_url = body.get("channel_url", "").strip()
            if not channel_url:
                self._send_json({"error": "频道 URL 不能为空"}, 400)
                return
            if not _is_valid_youtube_url(channel_url):
                self._send_json({"error": "频道 URL 必须为合法的 YouTube URL、@handle 或 UC 频道 ID"}, 400)
                return

            account_id = body.get("id")
            # api_key_id: None=清空, 0=清空, >0=指定Key, absent=_UNSET(不修改)
            api_key_id_val = body.get("api_key_id")
            api_key_id_param = None  # None = _UNSET (不修改)
            if api_key_id_val is not None:
                api_key_id_param = int(api_key_id_val) if api_key_id_val else None

            # proxy_pool_id: None=清空, 0=清空, >0=指定池, absent=_UNSET(不修改)
            proxy_pool_id_val = body.get("proxy_pool_id")
            proxy_pool_id_param = None
            if proxy_pool_id_val is not None:
                proxy_pool_id_param = int(proxy_pool_id_val) if proxy_pool_id_val else None

            if account_id:
                # 编辑模式 → UPDATE
                _db.update_account(
                    account_id=int(account_id),
                    name=body.get("name", "").strip(),
                    channel_url=channel_url,
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
                    proxy_pool_id=proxy_pool_id_param,
                    proxy_enabled=bool(body.get("proxy_enabled")) if "proxy_enabled" in body else None,
                    download_proxy_mode=body.get("download_proxy_mode", "auto"),
                )
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self._send_json({"ok": True, "id": account_id})
            else:
                # 新增模式 → INSERT
                account_id = _db.add_account(
                    name=body.get("name", "").strip(),
                    channel_url=channel_url,
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
                    proxy_pool_id=proxy_pool_id_param,
                    proxy_enabled=bool(body.get("proxy_enabled", False)),
                    download_proxy_mode=body.get("download_proxy_mode", "auto"),
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
        # 预加载所有 API Key 到内存字典（避免 N+1 查询）
        all_keys = {k["key_value"]: k for k in _db.list_api_keys()}
        for row in rows:
            raw_key = row.get("api_key_env", "")
            if raw_key:
                row["api_key_env"] = self._mask_key(raw_key)
            ak = all_keys.get(raw_key)
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
        """DELETE /api/api-keys/{id} — 删除 API Key（返回受影响账户供前端提示）"""
        try:
            # 查找使用此 Key 的账户
            accounts = [a for a in _db.list_accounts() if a.get("api_key_id") == key_id]
            affected = [{"id": a["id"], "name": a["name"]} for a in accounts]
            _db.delete_api_key(key_id)
            self._send_json({"ok": True, "affected_accounts": affected})
        except Exception:
            _log.error("API Key 删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    # ── 代理池 CRUD ──────────────────────────────────────────

    def _api_proxy_pools_list(self):
        """GET /api/proxy-pools — 列出所有代理池（URL 已掩码，不含认证信息）"""
        pools = _db.list_proxy_pools()
        result = [{
            "id": p["id"],
            "name": p["name"],
            "proxy_url": self._mask_proxy_url(p["proxy_url"]),
            "enabled": bool(p["enabled"]),
            "created_at": p["created_at"],
        } for p in pools]
        self._send_json(result)

    def _api_proxy_pool_add(self, body):
        """POST /api/proxy-pools — 新增代理池"""
        try:
            name = body.get("name", "").strip()
            proxy_url = body.get("proxy_url", "").strip()
            if not name or not proxy_url:
                self._send_json({"error": "名称和代理地址均不能为空"}, 400)
                return
            pool_id = _db.add_proxy_pool(name, proxy_url)
            self._send_json({"ok": True, "id": pool_id})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception:
            _log.error("代理池操作异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_proxy_pool_update(self, pool_id: int, body):
        """PUT /api/proxy-pools/{id}/update — 更新代理池"""
        try:
            name = body.get("name", "").strip() or None
            proxy_url = body.get("proxy_url", "").strip() or None
            enabled = bool(body.get("enabled")) if "enabled" in body else None
            if proxy_url is not None and not proxy_url:
                self._send_json({"error": "代理地址不能为空"}, 400)
                return
            _db.update_proxy_pool(pool_id, name=name, proxy_url=proxy_url, enabled=enabled)
            self._send_json({"ok": True})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception:
            _log.error("代理池更新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_proxy_pool_delete(self, pool_id: int):
        """DELETE /api/proxy-pools/{id} — 删除代理池"""
        try:
            accounts = [a for a in _db.list_accounts() if a.get("proxy_pool_id") == pool_id]
            affected = [{"id": a["id"], "name": a["name"]} for a in accounts]
            _db.delete_proxy_pool(pool_id)
            self._send_json({"ok": True, "affected_accounts": affected})
        except Exception:
            _log.error("代理池删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    # ── Dynamic Proxy Provider API ──────────────────────────────

    def _api_dynamic_providers_list(self):
        """GET /api/dynamic-providers — 列出所有动态代理提供方"""
        providers = _db.list_dynamic_proxy_providers()
        result = []
        for p in providers:
            cfg = p.get("config_json", {}) or {}
            preview = dict(cfg)
            if "password" in preview:
                preview["password"] = "***"
            if "auth_secret" in preview:
                preview["auth_secret"] = "***"
            if "api_key" in preview:
                preview["api_key"] = "***"

            cooldown_until = p.get("cooldown_until")
            is_in_cooldown = False
            if cooldown_until:
                try:
                    cooldown_dt = datetime.fromisoformat(cooldown_until)
                    now_dt = datetime.now(cooldown_dt.tzinfo) if cooldown_dt.tzinfo else datetime.now()
                    is_in_cooldown = cooldown_dt > now_dt
                except Exception:
                    is_in_cooldown = False

            status_map = {
                "healthy": "可用",
                "degraded": "降级",
                "auth_error": "认证失败",
                "down": "不可用",
                "not_started": "未启动",
            }
            status_text = "冷却中" if is_in_cooldown else status_map.get(p.get("last_health_status") or "", "未知")

            capabilities = []
            if p.get("supports_cookies"):
                capabilities.append("Cookie 下载可用")
            if p.get("supports_auto_download"):
                capabilities.append("自动下载可用")
            if p.get("supports_country_filter"):
                capabilities.append("支持国家筛选")
            if p.get("supports_sticky_session"):
                capabilities.append("支持粘性会话")

            masked_preview = None
            if p.get("adapter_type") == "rotating_gateway":
                protocol = cfg.get("protocol", "http")
                gateway_host = cfg.get("gateway_host")
                gateway_port = cfg.get("gateway_port")
                username = cfg.get("username", "")
                if gateway_host and gateway_port:
                    raw_url = f"{protocol}://{username + ':***@' if username else ''}{gateway_host}:{gateway_port}"
                    masked_preview = _db.mask_proxy_url(raw_url)
            elif p.get("adapter_type") == "local_gateway":
                local_proxy = cfg.get("local_proxy_url")
                masked_preview = _db.mask_proxy_url(local_proxy) if local_proxy else None

            result.append({
                "id": p["id"],
                "name": p["name"],
                "enabled": bool(p["enabled"]),
                "billing_tier": p.get("billing_tier", "free"),
                "adapter_type": p.get("adapter_type", "public_feed"),
                "priority": p.get("priority", 100),
                "refresh_interval_minutes": p.get("refresh_interval_minutes", 0),
                "supports_cookies": bool(p.get("supports_cookies")),
                "supports_auto_download": bool(p.get("supports_auto_download")),
                "supports_country_filter": bool(p.get("supports_country_filter")),
                "supports_sticky_session": bool(p.get("supports_sticky_session")),
                "risk_level": p.get("risk_level", "medium"),
                "notes": p.get("notes") or "",
                "config_json": preview,
                "masked_preview": masked_preview,
                "status_text": status_text,
                "capabilities": capabilities,
                "last_health_status": p.get("last_health_status") or "",
                "last_health_checked_at": p.get("last_health_checked_at") or "",
                "last_error_message": p.get("last_error_message") or "",
                "is_in_cooldown": is_in_cooldown,
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
            })
        self._send_json(result)

    def _api_dynamic_provider_add(self, body: dict):
        """POST /api/dynamic-providers — 新增动态代理提供方"""
        try:
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "名称不能为空"}, 400)
                return
            provider_id = _db.add_dynamic_proxy_provider(
                name=name,
                billing_tier=body.get("billing_tier", "free"),
                adapter_type=body.get("adapter_type", "public_feed"),
                config_json=body.get("config_json") or {},
                enabled=bool(body.get("enabled", True)),
                priority=int(body.get("priority", 100)),
                supports_cookies=bool(body.get("supports_cookies", False)),
                supports_auto_download=bool(body.get("supports_auto_download", True)),
                supports_country_filter=bool(body.get("supports_country_filter", False)),
                supports_sticky_session=bool(body.get("supports_sticky_session", False)),
                risk_level=body.get("risk_level", "medium"),
                notes=body.get("notes") or None,
                refresh_interval_minutes=int(body.get("refresh_interval_minutes") or 0),
            )
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True, "id": provider_id})
        except Exception:
            _log.error("动态代理提供方新增异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_update(self, provider_id: int, body: dict):
        """POST /api/dynamic-providers/{id}/update — 更新动态代理提供方"""
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            update_kwargs = {}
            if "name" in body:
                update_kwargs["name"] = body["name"].strip()
            if "enabled" in body:
                update_kwargs["enabled"] = bool(body["enabled"])
            if "billing_tier" in body:
                update_kwargs["billing_tier"] = body["billing_tier"]
            if "adapter_type" in body:
                update_kwargs["adapter_type"] = body["adapter_type"]
            if "priority" in body:
                update_kwargs["priority"] = int(body["priority"])
            if "supports_cookies" in body:
                update_kwargs["supports_cookies"] = bool(body["supports_cookies"])
            if "supports_auto_download" in body:
                update_kwargs["supports_auto_download"] = bool(body["supports_auto_download"])
            if "supports_country_filter" in body:
                update_kwargs["supports_country_filter"] = bool(body["supports_country_filter"])
            if "supports_sticky_session" in body:
                update_kwargs["supports_sticky_session"] = bool(body["supports_sticky_session"])
            if "refresh_interval_minutes" in body:
                update_kwargs["refresh_interval_minutes"] = int(body["refresh_interval_minutes"])
            if "risk_level" in body:
                update_kwargs["risk_level"] = body["risk_level"]
            if "notes" in body:
                update_kwargs["notes"] = body["notes"] or None
            if "config_json" in body:
                update_kwargs["config_json"] = body["config_json"]
            _db.update_dynamic_proxy_provider(provider_id, **update_kwargs)
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("动态代理提供方更新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_delete(self, provider_id: int):
        """DELETE /api/dynamic-providers/{id} — 删除动态代理提供方"""
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            _db.delete_dynamic_proxy_provider(provider_id)
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("动态代理提供方删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_health_check(self, provider_id: int):
        """POST /api/dynamic-providers/{id}/health-check — 触发健康检查"""
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return

            from monitor.provider_health import check_provider_health
            result = check_provider_health(provider_id)

            cfg = _db.load_config()
            cooldown_seconds = cfg.get("provider_cooldown_seconds", 600)
            cooldown_until: str | None = None
            if result.status in ("down", "degraded"):
                from datetime import timedelta
                cooldown_until = (
                    datetime.now().astimezone() + timedelta(seconds=cooldown_seconds)
                ).isoformat(timespec="seconds")

            _db.update_dynamic_proxy_provider(
                provider_id,
                last_health_status=result.status,
                last_health_checked_at=_db.now_iso(),
                last_error_message=result.error_message,
                cooldown_until=cooldown_until,
            )

            self._send_json({
                "ok": True,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error_message": result.error_message,
                "response_code": result.response_code,
                "cooldown_until": cooldown_until,
            })
        except Exception:
            _log.error("动态代理健康检查异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_candidates_preview(self, provider_id: int):
        """GET /api/dynamic-providers/{id}/candidates/preview — 返回候选预览（掩码）"""
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            rows = _db.get_proxy_candidate_by_provider(provider_id, valid_only=False)
            preview = []
            status_counts: dict[str, int] = {}
            latency_values: list[int] = []
            score_values: list[float] = []
            for row in rows[:10]:
                preview.append({
                    "id": row.get("id"),
                    "candidate_key": row.get("candidate_key"),
                    "protocol": row.get("protocol"),
                    "host": row.get("host"),
                    "port": row.get("port"),
                    "masked_proxy_endpoint": row.get("masked_proxy_endpoint"),
                    "last_probe_status": row.get("last_probe_status"),
                    "score": row.get("score", 0.0),
                })
            for row in rows:
                status = row.get("last_probe_status") or "unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
                latency = row.get("latency_ms")
                if isinstance(latency, int):
                    latency_values.append(latency)
                score = row.get("score")
                if isinstance(score, (int, float)):
                    score_values.append(float(score))
            latency_summary = {
                "count": len(latency_values),
                "min_ms": min(latency_values) if latency_values else None,
                "max_ms": max(latency_values) if latency_values else None,
            }
            score_summary = {
                "count": len(score_values),
                "min_score": min(score_values) if score_values else None,
                "max_score": max(score_values) if score_values else None,
            }
            top_candidate = _db.pick_healthy_fastest_top_candidate(rows)
            self._send_json({
                "provider_id": provider_id,
                "provider_name": existing.get("name", ""),
                "preview": preview,
                "total_count": len(rows),
                "status_counts": status_counts,
                "latency_summary": latency_summary,
                "score_summary": score_summary,
                "top_candidate": top_candidate,
            })
        except Exception:
            _log.error("动态代理候选预览异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_refresh(self, provider_id: int):
        """POST /api/dynamic-providers/{id}/refresh — 手动刷新 provider 候选"""
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            result = _scheduler.refresh_dynamic_provider(provider_id)
            self._send_json(result)
        except Exception:
            _log.error("动态代理提供方手动刷新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_cooldown_clear(self, provider_id: int):
        """POST /api/dynamic-providers/{id}/cooldown/clear — 清除冷却"""
        try:
            _db.update_dynamic_proxy_provider(
                provider_id,
                cooldown_until=None,
                last_health_status="healthy",
                last_health_checked_at=_db.now_iso(),
                last_error_message=None,
            )
            self._send_json({"ok": True})
        except Exception:
            _log.error("清除代理提供方冷却异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_routing_preview(self):
        """
        GET /api/routing-preview — 预览下载路由决策（不触发实际下载）

        Query params:
            account_id   (int)   必填，账户 ID
            auto         (0|1)   可选，默认 0（0=手动下载, 1=自动下载）
            cookies      (0|1)   可选，默认 0（0=无cookie, 1=有cookie）
            direct       (0|1)   可选，默认 0（0=正常路由, 1=强制直连）

        Returns the ProxyRouteResult fields so the caller can preview
        what proxy will be used before triggering a download.
        """
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)

        try:
            raw_account_id = params.get("account_id", [None])[0]
            if raw_account_id in (None, "", "0"):
                raise ValueError("missing")
            account_id = int(raw_account_id)
        except (ValueError, TypeError):
            self._send_json({"error": "account_id 必填且必须为整数"}, 400)
            return

        is_auto_download = params.get("auto", ["0"])[0] in ("1", "true")
        cookies_present = params.get("cookies", ["0"])[0] in ("1", "true")
        user_forced_direct = params.get("direct", ["0"])[0] in ("1", "true")

        account = _db.get_account(account_id)
        if not account:
            self._send_json({"error": "账户不存在"}, 404)
            return

        if user_forced_direct:
            from monitor.proxy_router import ProxyRouteResult
            route = ProxyRouteResult(
                resolved_mode="direct",
                proxy=None,
                proxy_pool=None,
                provider_name=None,
                provider_tier=None,
                resolved_proxy_source="direct",
                reason="用户显式指定直连",
                warnings=[],
                fallback_depth=0,
                masked_proxy_endpoint=None,
                session_mode=None,
                cookies_file_present=cookies_present,
            )
        else:
            from monitor.dynamic_provider_resolver import resolve_for_manual_download, resolve_for_auto_download
            if is_auto_download:
                route = resolve_for_auto_download(account_id)
            else:
                route = resolve_for_manual_download(account_id, cookies_present)

        self._send_json({
            "account_id": account_id,
            "account_name": account.get("name", ""),
            "download_proxy_mode": account.get("download_proxy_mode", "auto"),
            "is_auto_download": is_auto_download,
            "cookies_present": cookies_present,
            "user_forced_direct": user_forced_direct,
            "routing": {
                "resolved_mode": route.resolved_mode,
                "resolved_proxy_source": route.resolved_proxy_source,
                "provider_name": route.provider_name,
                "provider_tier": route.provider_tier,
                "masked_proxy_endpoint": route.masked_proxy_endpoint,
                "session_mode": route.session_mode,
                "fallback_depth": route.fallback_depth,
                "reason": route.reason,
                "warnings": route.warnings,
            },
        })

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
        # 使用 realpath 解析符号链接，防止 UNC 路径绕过 startswith() 检查
        abs_output = os.path.realpath(os.path.abspath(output_path))
        abs_root = os.path.abspath(_PROJECT_ROOT)
        # 允许：项目根目录下任何子目录 + 全局配置中明确设置的路径
        cfg_abs = os.path.realpath(os.path.abspath(cfg.get("download_output_path", ""))) if cfg.get("download_output_path") else ""
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

        # ── 统一代理解析（替换旧的 proxy = _db.get_account_proxy()）───
        account = _db.get_account(int(acc_id))
        if not account:
            self._send_json({"error": "账户不存在"}, 404)
            return

        # user_forced_direct: 允许请求体传 direct=true 强制直连
        user_forced_direct = bool(body.get("direct", False))

        cookies_file = body.get("cookies_file") or cfg.get("download_cookies_file", "") or None
        if cookies_file and not os.path.isfile(cookies_file):
            _log.warning(f"Cookie 文件不存在，将跳过 Cookie: {cookies_file}")
            cookies_file = None
        cookies_present = bool(cookies_file)

        # Resolve proxy using unified routing
        route = resolve_for_manual_download(int(acc_id), cookies_present)

        # Override with user_forced_direct if specified
        if user_forced_direct:
            from monitor.proxy_router import ProxyRouteResult
            route = ProxyRouteResult(
                resolved_mode="direct",
                proxy=None,
                proxy_pool=None,
                provider_name=None,
                provider_tier=None,
                resolved_proxy_source="direct",
                reason="用户显式指定直连",
                warnings=[],
                fallback_depth=0,
                masked_proxy_endpoint=None,
                session_mode=None,
                cookies_file_present=cookies_present,
            )

        # 手动下载：代理池/单代理试完后是否允许直连（与全局「手动下载直连兜底」一致）
        direct_fallback_after_proxies = bool(cfg.get("manual_direct_fallback", True)) and not user_forced_direct

        # Log the decision
        log_download_decision(
            route_result=route,
            account_id=int(acc_id),
            account_name=account.get("name", ""),
            video_count=len(urls),
            is_auto_download=False,
        )

        _log.info(
            f"[Manual Download] account={acc_id} route={route.resolved_proxy_source} "
            f"provider={route.provider_name or 'N/A'} reason={route.reason} "
            f"proxy={route.masked_proxy_endpoint or 'direct'}"
        )

        # Handle routing failure
        if route.resolved_mode == "failed":
            self._send_json({
                "ok": False,
                "error": route.reason,
                "routing": {
                    "source": route.resolved_proxy_source,
                    "provider": route.provider_name,
                    "masked_endpoint": route.masked_proxy_endpoint,
                    "reason": route.reason,
                    "warnings": route.warnings,
                    "session_mode": route.session_mode,
                },
            }, 400)
            return

        # Determine what to pass to batch_download
        resolved_proxy: str | None = None
        resolved_proxy_pool: list[str] | None = None
        if route.resolved_proxy_source == "direct":
            resolved_proxy = None
        elif route.resolved_proxy_source == "account_static":
            resolved_proxy = route.proxy
        elif route.resolved_proxy_source in ("system_paid", "system_free"):
            # proxy_pool takes priority over proxy for dynamic providers
            if route.proxy_pool:
                resolved_proxy_pool = route.proxy_pool
            else:
                resolved_proxy = route.proxy

        task_id = _task_mgr.create_task(video_records, abs_output)
        _log.info(
            f"创建下载任务: task_id={task_id} 视频数={len(urls)} "
            f"输出={abs_output} 路由={route.resolved_proxy_source}"
            f"{' [proxy]' if resolved_proxy else ''}"
            f"{' [proxy_pool]' if resolved_proxy_pool else ''}"
        )

        _db.update_videos_download_status(video_ids, "downloading")

        sub_langs = body.get("sub_langs")   # Web UI 显式传入，未传则不下载字幕
        no_subs = body.get("no_subs", True)  # 默认不下载字幕（避免 WhisperX 拖慢）
        enable_aria2 = bool(cfg.get("enable_aria2", False))
        # 代理由 batch_download 每轮注入；此处仅用占位构建 aria2 骨架，避免与动态池首包不一致
        extra_ydl_opts = build_aria2_opts(None) if enable_aria2 else None

        def _bg_download():
            try:
                def progress_cb(progress, status_text):
                    completed = int(progress * len(urls))
                    _task_mgr.update_progress(task_id, completed, status_text)

                results = batch_download(
                    urls,
                    abs_output,
                    'best',
                    proxy=resolved_proxy,
                    proxy_pool=resolved_proxy_pool,
                    progress_callback=progress_cb,
                    sub_langs=sub_langs if not no_subs else None,
                    no_subs=no_subs,
                    cookies_file=cookies_file,
                    extra_ydl_opts=extra_ydl_opts,
                    direct_fallback_after_proxies_exhausted=direct_fallback_after_proxies,
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
            "total": len(urls),
            "message": f"{len(urls)} 个视频已开始下载",
            "routing": {
                "source": route.resolved_proxy_source,
                "provider": route.provider_name,
                "provider_tier": route.provider_tier,
                "masked_endpoint": route.masked_proxy_endpoint,
                "reason": route.reason,
                "warnings": route.warnings,
                "session_mode": route.session_mode,
            },
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

    # ── Batch Download API ─────────────────────────────────────

    def _handle_multipart_upload(self):
        """POST /api/batch/upload — 接收上传的 Excel/CSV/TXT 文件，解析 URL 列表。"""
        try:
            import cgi

            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            if "file" not in form:
                self._send_json({"ok": False, "error": "未上传文件"}, 400)
                return
            file_item = form["file"]
            if isinstance(file_item, list):
                file_item = file_item[0] if file_item else None
            file_obj = getattr(file_item, "file", None) if file_item is not None else None
            if file_item is None or file_obj is None:
                self._send_json({"ok": False, "error": "未上传文件"}, 400)
                return

            filename = getattr(file_item, "filename", None) or "upload"
            data = file_obj.read()
            if not data:
                self._send_json({"ok": False, "error": "文件为空"}, 400)
                return

            # 保存到临时文件，解析后删除
            suffix = pathlib.Path(filename).suffix
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, mode="wb"
            ) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                from Youtube_Downloader import read_urls_from_file

                urls = read_urls_from_file(tmp_path)
                if not isinstance(urls, list) or not urls:
                    self._send_json({"ok": False, "error": "文件中未找到有效 URL"}, 400)
                    return
                preview = urls[:5]
                self._send_json({
                    "ok": True,
                    "filename": filename,
                    "url_count": len(urls),
                    "urls": preview,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as ex:
            self._send_json({"ok": False, "error": str(ex)}, 500)

    def _api_batch_download_start(self, body: dict):
        """POST /api/batch/start — 从 URL 列表启动批量下载。"""
        urls = body.get("urls", [])
        if not isinstance(urls, list) or not urls:
            self._send_json({"error": "urls 必须为非空数组"}, 400)
            return

        cfg = _db.load_config()
        default_out = cfg.get("download_output_path", "").strip()
        output_path = body.get("output_path", "").strip() or default_out
        if not output_path:
            output_path = os.path.join(_PROJECT_ROOT, "videos")

        # 路径安全校验
        abs_output = pathlib.Path(output_path).resolve()
        abs_root = pathlib.Path(_PROJECT_ROOT).resolve()
        if not str(abs_output).startswith(str(abs_root)):
            self._send_json({"error": "输出路径必须在允许范围内"}, 400)
            return
        os.makedirs(abs_output, exist_ok=True)

        default_cookies = cfg.get("download_cookies_file", "") or None
        cookies_file = body.get("cookies_file", "") or default_cookies
        if cookies_file and not os.path.isfile(cookies_file):
            cookies_file = None

        resolution = body.get("resolution", "best")
        no_subs = bool(body.get("no_subs", False))
        sub_langs = body.get("sub_langs", "zh-Hans,en") if not no_subs else None

        # 代理解析：走手动下载路由
        route = resolve_for_manual_download(None, bool(cookies_file))

        if route.resolved_proxy_source == "direct":
            resolved_proxy = None
        elif route.resolved_proxy_source in ("system_paid", "system_free"):
            resolved_proxy = route.proxy
        elif route.resolved_proxy_source == "account_static":
            resolved_proxy = route.proxy
        else:
            resolved_proxy = None

        # aria2 加速
        enable_aria2 = cfg.get("enable_aria2", False)
        _aria2_proxy = build_aria2_opts(resolved_proxy) if resolved_proxy else None
        extra_ydl_opts = _aria2_proxy if enable_aria2 else None

        video_records = [{"url": u} for u in urls]
        task_id = _task_mgr.create_task(video_records, str(abs_output))

        def progress_wrapper(progress: float, status: str):
            _task_mgr.update_progress(task_id, int(progress * len(urls)), status)

        def run():
            try:
                results = batch_download(
                    urls,
                    str(abs_output),
                    resolution,
                    proxy=resolved_proxy,
                    progress_callback=progress_wrapper,
                    sub_langs=sub_langs,
                    no_subs=no_subs,
                    cookies_file=cookies_file,
                    extra_ydl_opts=extra_ydl_opts,
                )
                _task_mgr.finish_task(task_id, results)
            except Exception as ex:
                _task_mgr.fail_task(task_id, str(ex))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._send_json({"ok": True, "task_id": task_id})

    def _api_batch_tasks_list(self):
        """GET /api/batch/tasks — 返回所有批次任务。"""
        tasks = _task_mgr.list_tasks()
        self._send_json({"tasks": tasks})

    def _api_batch_task_status(self, task_id: str):
        """GET /api/batch/tasks/:id — 返回单个任务详情。"""
        task = _task_mgr.get_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(task)

    # ── 静态文件服务覆盖 ──────────────────────────────────────

    def translate_path(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        from urllib.parse import urlparse, unquote
        rel = unquote(urlparse(path).path).lstrip("/")
        candidate = (_STATIC_DIR / rel).resolve()
        static_root = _STATIC_DIR.resolve()
        if candidate != static_root and static_root not in candidate.parents:
            return str(static_root / "index.html")
        return str(candidate)


def serve(port: int = 5000):
    os.makedirs(_STATIC_DIR, exist_ok=True)
    if not _INDEX_HTML.exists():
        _log.error(f"index.html not found at {_STATIC_DIR}")
        _INDEX_HTML.write_text("<html><body><h1>UI not found</h1></body></html>", encoding="utf-8")
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        """支持并发的 HTTPServer（每请求一个线程）"""
        daemon_threads = True
    server = ThreadedHTTPServer(("127.0.0.1", port), MonitorHandler)
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

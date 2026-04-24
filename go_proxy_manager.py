"""
go_proxy_manager.py — Go MitM 代理子进程生命周期管理。

职责：
- 启动/停止 Go 可执行文件
- 健康检查（轮询 /health 端点）
- 自动重启（最多 MAX_RESTARTS 次）
- WebSocket 事件接收（转发为 Python 回调 + SSE 广播）
"""
from __future__ import annotations

import json as _json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from codecs import getreader
from config.settings import load_config
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

_log = logging.getLogger("go_proxy_manager")

# ── 配置常量 ────────────────────────────────────────────────
DEFAULT_PROXY_PORT = 8899
HEALTH_CHECK_INTERVAL = 1.0  # 秒
HEALTH_CHECK_TIMEOUT = 2.0   # 秒
MAX_RESTARTS = 3
STARTUP_TIMEOUT = 30         # 秒


def _find_executable() -> Optional[str]:
    """查找 Go 可执行文件路径（按优先级）。"""
    # 1. 环境变量覆盖
    if os.environ.get("RES_DOWNLOADER_EXE"):
        p = os.environ["RES_DOWNLOADER_EXE"]
        if Path(p).exists():
            return p
    # 2. Python 项目目录（相对路径）
    project_root = Path(__file__).parent
    local_exe = project_root / "res-downloader.exe"
    if local_exe.exists():
        return str(local_exe)
    # 3. res-downloader 源码目录
    resd_dir = Path("D:/WORKSPACE/video-download-space/res-downloader")
    src_exe = resd_dir / "res-downloader.exe"
    if src_exe.exists():
        return str(src_exe)
    return None


@dataclass
class ProxyEvent:
    """WebSocket 事件数据结构。"""
    event: str
    data: dict


class GoProxyManager:
    """
    Go MitM 代理子进程管理器。

    线程安全：所有公共方法可在任意线程调用。
    """

    def __init__(
        self,
        proxy_port: int = DEFAULT_PROXY_PORT,
        on_resource_found: Optional[Callable[[dict], None]] = None,
        on_download_progress: Optional[Callable[[dict], None]] = None,
        on_proxy_started: Optional[Callable[[dict], None]] = None,
        on_proxy_stopped: Optional[Callable[[dict], None]] = None,
    ):
        self.proxy_port = proxy_port
        self._process: Optional[subprocess.Popen] = None
        self._restart_count = 0
        self._stopping = False
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_running = False

        # 事件回调
        self._on_resource_found = on_resource_found
        self._on_download_progress = on_download_progress
        self._on_proxy_started = on_proxy_started
        self._on_proxy_stopped = on_proxy_stopped

        # SSE 广播队列（所有 SSE 消费者共享同一个队列实例）
        self._event_queue: queue.Queue[Optional[dict]] = queue.Queue(maxsize=256)

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.proxy_port}"

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """
        启动 Go 子进程，等待其就绪。
        抛出 RuntimeError 如果启动失败或超时。
        """
        if self.is_running:
            _log.warning("Go proxy already running, skipping start")
            return

        exe_path = _find_executable()
        if not exe_path:
            raise RuntimeError(
                "Go 可执行文件未找到。请设置 RES_DOWNLOADER_EXE 环境变量 "
                "或确保 res-downloader.exe 存在于项目目录或 "
                "D:/WORKSPACE/video-download-space/res-downloader/"
            )

        _log.info("Starting Go proxy: %s (port=%s)", exe_path, self.proxy_port)

        self._process = subprocess.Popen(
            [exe_path, "-port", str(self.proxy_port)],
            env=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        # 后台线程：捕获 Go 子进程 stdout，转发到 Python 日志
        def _read_go_stdout():
            import codecs
            reader = codecs.getreader('utf-8')(self._process.stdout)
            for line in reader:
                _log.info("[SPAWN stdout] %s", line.rstrip())
        self._stdout_thread = threading.Thread(target=_read_go_stdout, daemon=True)
        self._stdout_thread.start()

        # 等待健康检查通过
        started_at = time.time()
        while time.time() - started_at < STARTUP_TIMEOUT:
            if not self.is_running:
                raise RuntimeError(f"Go 进程启动后立即退出，exit code={self._process.returncode}")
            try:
                r = requests.get(
                    f"{self.api_base}/health",
                    timeout=HEALTH_CHECK_TIMEOUT,
                )
                if r.status_code == 200:
                    _log.info("Go proxy started successfully (pid=%d)", self._process.pid)
                    self._restart_count = 0
                    self._stopping = False
                    self._start_ws_client()
                    if self._on_proxy_started:
                        self._on_proxy_started({"port": self.proxy_port})
                    return
            except requests.exceptions.RequestException:
                _log.debug("Go proxy health check failed (retrying)")
            time.sleep(HEALTH_CHECK_INTERVAL)

        # 超时未就绪，尝试终止
        self._process.terminate()
        self._process.wait(timeout=5)
        raise RuntimeError(
            f"Go 代理启动超时（{STARTUP_TIMEOUT}s），"
            f"/health 端点未响应。请检查日志。"
        )

    def stop(self) -> None:
        """优雅停止 Go 子进程。"""
        self._stopping = True
        self._stop_ws_client()

        if self._process is None:
            return

        _log.info("Stopping Go proxy (pid=%d)", self._process.pid)
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _log.warning("Go proxy did not exit gracefully, killing")
            self._process.kill()
            self._process.wait()
        finally:
            self._process = None
            if self._on_proxy_stopped:
                self._on_proxy_stopped({})

    def restart(self) -> None:
        """重启 Go 子进程（自动重启逻辑调用）。"""
        if self._stopping:
            return
        if self._restart_count >= MAX_RESTARTS:
            _log.error("Max restarts (%d) reached, giving up", MAX_RESTARTS)
            return
        self._restart_count += 1
        _log.warning("Restarting Go proxy (attempt %d/%d)", self._restart_count, MAX_RESTARTS)
        try:
            self.stop()
        except Exception:
            _log.debug("Ignoring stop() error during restart")
        time.sleep(1)
        try:
            self.start()
        except RuntimeError as e:
            _log.error("Restart failed: %s", e)

        # ── REST API 封装 ────────────────────────────────────────

    def get_config(self) -> dict:
        """获取 Go 侧配置。"""
        r = requests.get(f"{self.api_base}/api/get-config", timeout=5)
        r.raise_for_status()
        return r.json()

    def update_config(self, config: dict) -> dict:
        """更新 Go 侧配置。"""
        r = requests.post(f"{self.api_base}/api/set-config", json=config, timeout=5)
        r.raise_for_status()
        return r.json()

    def trigger_download(self, url: str, output_path: str = "") -> dict:
        """触发下载任务。"""
        r = requests.post(
            f"{self.api_base}/api/download",
            json={"url": url, "output_path": output_path},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def clear_resources(self) -> dict:
        """清空资源列表。"""
        r = requests.post(f"{self.api_base}/api/clear", timeout=5)
        r.raise_for_status()
        return r.json()

    def delete_resources(self, signs: list[str]) -> dict:
        """删除指定资源。"""
        r = requests.post(
            f"{self.api_base}/api/delete",
            json={"sign": signs},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    def set_resource_type(self, types: str) -> dict:
        """设置资源类型过滤（逗号分隔，如 "video,audio,image"）。"""
        r = requests.post(
            f"{self.api_base}/api/set-type",
            json={"type": types},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    def cancel_download(self, task_id: str) -> dict:
        """取消下载任务。"""
        r = requests.post(
            f"{self.api_base}/api/cancel",
            json={"id": task_id},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    def wx_file_decode(self, media_info: dict, filename: str, decode_str: str) -> dict:
        """解密微信加密文件。"""
        payload = {
            "MediaInfo": media_info,
            "filename": filename,
            "decodeStr": decode_str,
        }
        r = requests.post(
            f"{self.api_base}/api/wx-file-decode",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def batch_export(self, content: str) -> dict:
        """批量导出资源列表。"""
        r = requests.post(
            f"{self.api_base}/api/batch-export",
            json={"content": content},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def open_folder(self, file_path: str) -> dict:
        """打开包含指定文件的目录。"""
        r = requests.post(
            f"{self.api_base}/api/open-folder",
            json={"filePath": file_path},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()

    # ── WebSocket 客户端 ─────────────────────────────────────

    def _start_ws_client(self) -> None:
        """启动 WebSocket 监听线程（后台）。"""
        self._ws_running = True
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()

    def _stop_ws_client(self) -> None:
        """停止 WebSocket 监听线程。"""
        self._ws_running = False
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=3)
        self._ws_thread = None

    def _ws_loop(self) -> None:
        """WebSocket 接收循环（运行在独立线程）。"""
        _log.info("[WS] WebSocket thread starting for port %d", self.proxy_port)
        try:
            import websocket as _ws_module
        except ImportError as e:
            _log.error("[WS] Failed to import websocket-client: %s", e)
            return
        import logging as _ws_log
        _ws_log = logging.getLogger("go_proxy_manager.ws")
        ws_url = f"ws://127.0.0.1:{self.proxy_port}/ws"
        while self._ws_running and self.is_running:
            try:
                _ws_log.info("[WS] Connecting to %s", ws_url)
                ws = _ws_module.create_connection(
                    ws_url,
                    timeout=10,
                    enable_multithread=True,
                )
                _ws_log.info("[WS] Connected to %s", ws_url)
                while self._ws_running and self.is_running:
                    msg = ws.recv()
                    _ws_log.debug("[WS] recv: %s", msg[:120] if msg else "")
                    self._dispatch_ws_message(msg)
                ws.close()
            except Exception as e:
                if self._ws_running and not self._stopping:
                    _ws_log.warning("[WS] disconnected: %s, reconnecting in 2s...", e)
                    time.sleep(2)
                else:
                    break

    def _dispatch_ws_message(self, raw: str) -> None:
        """解析 WebSocket 消息并触发对应回调 + SSE 广播。"""
        try:
            msg = _json.loads(raw)
        except Exception:
            _log.warning("Invalid WS message: %s", raw[:100])
            return

        event = msg.get("event", "")
        raw_data = msg.get("data", "")

        # res-downloader 的 send() 先将数据Marshal为 {"type": t, "data": mediaInfo}
        # 然后作为字符串传入 EmitEvent，再次Marshal为 {"event": t, "data": <json字符串>}
        # 因此 data 字段可能是一个已经Marshal过的字符串，需要解析
        parsed = raw_data
        try:
            if isinstance(raw_data, str):
                parsed = _json.loads(raw_data)
            elif isinstance(raw_data, dict):
                parsed = raw_data
        except Exception:
            _log.warning("Failed to parse WS data: %s", str(raw_data)[:100])
            parsed = {}

        # Go send() 额外包装了 {"type": ..., "data": ...}，需要解包获取真正的 mediaInfo
        # downloadProgress 的 data 字段是 dict（不是字符串），直接可用
        if isinstance(parsed, dict) and "data" in parsed:
            inner = parsed["data"]
            if isinstance(inner, str):
                try:
                    inner = _json.loads(inner)
                except Exception:
                    pass
            # SSE 广播：用 Go send() 的原始包装（type + data），浏览器端自行解包
            sse_data = parsed
        else:
            sse_data = parsed

        # 触发回调（传入解包后的数据）
        if event == "newResources" and self._on_resource_found:
            self._on_resource_found(sse_data)
        elif event == "downloadProgress" and self._on_download_progress:
            self._on_download_progress(sse_data)

        # SSE 广播（放入队列，非阻塞）
        broadcast = {"event": event, "data": sse_data}
        try:
            self._event_queue.put_nowait(broadcast)
        except queue.Full:
            _log.warning("SSE event queue full, dropping event: %s", event)

    def get_event(self, timeout: float = 30.0) -> Optional[dict]:
        """
        从 SSE 队列中获取一个事件。
        供 SSE endpoint 调用。timeout=0 时立即返回（非阻塞）。
        Returns None 表示队列为空或超时。
        """
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def event_queue_size(self) -> int:
        """返回当前队列中的事件数量。"""
        return self._event_queue.qsize()


# ── 全局单例 ───────────────────────────────────────────────
_manager: Optional[GoProxyManager] = None
_manager_lock = threading.Lock()


def get_proxy_manager(
    proxy_port: int | None = None,
) -> GoProxyManager:
    """获取全局 GoProxyManager 单例（线程安全）。

    若未指定 proxy_port，则从 config.json 读取 proxy_sniffer_port。
    若已存在单例但端口与配置不符，先停止旧实例（如果运行中）再重建。
    """
    global _manager
    # 读取配置中的端口
    if proxy_port is None:
        try:
            cfg = load_config()
            proxy_port = int(cfg.get("proxy_sniffer_port") or DEFAULT_PROXY_PORT)
        except Exception:
            proxy_port = DEFAULT_PROXY_PORT
    with _manager_lock:
        need_stop = _manager is not None and _manager.proxy_port != proxy_port and _manager.is_running
        needs_new = _manager is None or _manager.proxy_port != proxy_port
    if need_stop:
        # 在锁外停止旧进程，避免阻塞其他调用者
        _manager.stop()
    with _manager_lock:
        if needs_new:
            _manager = GoProxyManager(proxy_port=proxy_port)
        return _manager


def reset_proxy_manager() -> None:
    """重置全局单例（测试用）。"""
    global _manager
    with _manager_lock:
        if _manager:
            _manager.stop()
        _manager = None

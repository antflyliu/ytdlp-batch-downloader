"""
go_proxy_manager.py — Go MitM 代理子进程生命周期管理。

职责：
- 启动/停止 Go 可执行文件
- 健康检查（轮询 /health 端点）
- 自动重启（最多 MAX_RESTARTS 次）
- WebSocket 事件接收（转发为 Python 回调）

使用方式：
    from go_proxy_manager import get_proxy_manager
    mgr = get_proxy_manager()
    mgr.start()
    # ...
    mgr.stop()
"""
from __future__ import annotations

import os
import sys
import time
import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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
            [exe_path],
            env=None,  # 使用继承的环境变量
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

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
                pass
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
            pass
        time.sleep(1)
        try:
            self.start()
        except RuntimeError as e:
            _log.error("Restart failed: %s", e)

    # ── REST API 封装 ────────────────────────────────────────

    def get_resources(self) -> list[dict]:
        """获取已嗅探到的资源列表。"""
        r = requests.get(f"{self.api_base}/api/resources", timeout=5)
        r.raise_for_status()
        return r.json().get("resources", [])

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
        import json as _json

        ws_url = f"ws://127.0.0.1:{self.proxy_port}/ws"
        while self._ws_running and self.is_running:
            try:
                # 使用 websocket-client 库
                import websocket as _ws_module
                ws = _ws_module.create_connection(
                    ws_url,
                    timeout=30,
                    enable_multithread=True,
                )
                _log.debug("WebSocket connected to %s", ws_url)
                while self._ws_running and self.is_running:
                    msg = ws.recv()
                    self._dispatch_ws_message(msg)
                ws.close()
            except Exception as e:
                if self._ws_running and not self._stopping:
                    _log.debug("WebSocket disconnected: %s, reconnecting...", e)
                    time.sleep(2)
                break

    def _dispatch_ws_message(self, raw: str) -> None:
        """解析 WebSocket 消息并触发对应回调。"""
        import json as _json

        try:
            msg = _json.loads(raw)
        except Exception:
            _log.warning("Invalid WS message: %s", raw[:100])
            return

        event = msg.get("event", "")
        data = msg.get("data", {})

        if event == "resource_found" and self._on_resource_found:
            self._on_resource_found(data)
        elif event == "download_progress" and self._on_download_progress:
            self._on_download_progress(data)


# ── 全局单例 ────────────────────────────────────────────────
_manager: Optional[GoProxyManager] = None
_manager_lock = threading.Lock()


def get_proxy_manager(
    proxy_port: int = DEFAULT_PROXY_PORT,
) -> GoProxyManager:
    """获取全局 GoProxyManager 单例（线程安全）。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = GoProxyManager(proxy_port=proxy_port)
        return _manager


def reset_proxy_manager() -> None:
    """重置全局单例（测试用）。"""
    global _manager
    with _manager_lock:
        if _manager:
            _manager.stop()
        _manager = None

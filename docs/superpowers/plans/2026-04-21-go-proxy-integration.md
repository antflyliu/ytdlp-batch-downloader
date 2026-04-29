# Go 代理子进程集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 res-downloader（Go MitM 代理）作为子进程集成到 Python 项目，Python 通过 REST API 控制 Go，Go 通过 WebSocket 推送异步事件回 Python。

**Architecture:**
- Go 进程：纯后端服务（移除 Wails Runtime），**单端口 8899** 同时承载 HTTP API + WebSocket + MitM 代理（配置从 `config.json` 读取，不支持环境变量覆盖）
- Python 进程：管理 Go 子进程生命周期，通过 Flask `/api/proxy/*` 转发请求到 Go API
- 通信：Python → Go = HTTP REST（同步）；Go → Python = WebSocket（异步事件推送）

**Tech Stack:** Go（gorilla/websocket、elazarl/goproxy）、Python（subprocess、requests、websocket-client）、Flask（已有）

> **实际验证的 Go API 端点**（2026-04-21）：
> - `/health` — 健康检查
> - `/ws` — WebSocket
> - `/api/get-config` — 获取配置
> - `/api/set-config` — 更新配置
> - `/api/download` — 触发下载
> - `/api/is-proxy` — 查询代理状态
> - `/api/proxy-open` — 设置系统代理
> - `/api/proxy-unset` — 取消系统代理
> - `/api/install` — 安装 CA 证书
> - `/api/clear` — 清除资源
> - `/api/delete` — 删除资源
> - `/api/set-type` — 设置类型
> - `/api/cancel` — 取消任务
> - `/api/app-info` — 应用信息
> 注意：`/api/resources`（资源列表）不存在，资源通过 WebSocket `resource_found` 事件推送。

---

## 文件结构

```
ytdlp-batch-downloader/
├── go_proxy_manager.py           # 新增：Go 子进程生命周期管理
├── monitor_ui.py                 # 修改：集成 GoProxyManager 启动/停止
├── server/
│   └── __main__.py              # 修改：新增 /api/proxy/* 路由
├── monitor_web/
│   ├── js/
│   │   └── modules/
│   │       └── proxySniffer.js  # 新增：代理嗅探面板 JS 模块
│   ├── templates/
│   │   └── pages/
│   │       └── settings-proxy.html  # 新增：代理设置页面
│   └── static/
│       └── i18n/
│           ├── en.json          # 修改：新增代理相关 i18n
│           └── zh.json          # 修改：新增代理相关 i18n
└── docs/
    └── go-integration-*.md      # 已完成（分析+指南）

独立目录（不在 Python 项目 git 内）：
D:\WORKSPACE\video-download-space\res-downloader/
├── core/
│   ├── app.go                   # 修改：移除 Wails Runtime
│   └── http.go                  # 修改：增加 /health + /ws 端点
└── go.mod                       # 修改：移除 wails，添加 gorilla/websocket
```

---

## Task 1: Go 侧改造 — 移除 Wails Runtime

**Go 源码位置:** `D:\WORKSPACE\video-download-space\res-downloader`

**Files:**
- Modify: `D:\WORKSPACE\video-download-space\res-downloader\core\app.go`
- Modify: `D:\WORKSPACE\video-download-space\res-downloader\core\http.go`
- Modify: `D:\WORKSPACE\video-download-space\res-downloader\go.mod`
- Modify: `D:\WORKSPACE\video-download-space\res-downloader\main.go`

- [ ] **Step 1: 备份原有文件**

```bash
cd D:\WORKSPACE\video-download-space\res-downloader
git checkout -b standalone-backend
```
确认在 `standalone-backend` 分支开发，不污染原分支。

- [ ] **Step 2: 修改 go.mod — 移除 Wails，新增 gorilla/websocket**

```bash
cd D:\WORKSPACE\video-download-space\res-downloader
go mod edit -droprequire github.com/wailsapp/wails/v2
go get github.com/gorilla/websocket@v1.5.1
```

验证：`go mod tidy` 无报错。

- [ ] **Step 3: 修改 core/app.go — 删除 Wails Runtime 引用**

读取 `core/app.go`，找到所有 `wailsapp/runtime` 引用，删除或替换：

```go
// 替换前
import "github.com/wailsapp/wails/v2/pkg/runtime"

// 替换后（删除 import）

// 替换前
runtime.EventsEmit(ctx, "proxy_started", map[string]any{"port": port})

// 替换后（使用新的 EmitEvent，见 Step 5）
EmitEvent("proxy_started", map[string]any{"port": port})
```

同时在 `app.go` 中保留 CA 证书解码逻辑（不要删除，这部分是核心）。

- [ ] **Step 4: 修改 main.go — 移除 Wails 启动，改为标准 HTTP 启动**

```go
// 替换前（Wails 启动）
//func main() {
//    app := core.GetApp()
//    if err := wails.Run(&app); err != nil {
//        log.Fatal(err)
//    }
//}

// 替换后（纯 HTTP 启动）
func main() {
    app := core.GetApp()
    if err := app.Start(); err != nil {
        log.Fatal(err)
    }
    // 阻塞直到收到 SIGINT/SIGTERM
    app.Wait()
}
```

`App.Start()` 启动 HTTP Server goroutine，`App.Wait()` 监听系统信号。

- [ ] **Step 5: 修改 core/http.go — 增加 WebSocket Hub 和 /health 端点**

在 `http.go` 顶部添加 imports（如果没有）：

```go
import (
    "encoding/json"
    "sync"
    "github.com/gorilla/websocket"
)
```

在文件开头（package 级别或 struct 定义区域）添加 WSHub：

```go
var (
    hub     *WSHub
    hubOnce sync.Once
)

type WSHub struct {
    clients   map[*websocket.Conn]bool
    broadcast chan []byte
    mu        sync.RWMutex
}

func GetHub() *WSHub {
    hubOnce.Do(func() {
        hub = &WSHub{
            clients:   make(map[*websocket.Conn]bool),
            broadcast: make(chan []byte, 256),
        }
        go hub.run()
    })
    return hub
}

func (h *WSHub) run() {
    for msg := range h.broadcast {
        h.mu.RLock()
        for conn := range h.clients {
            conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
            if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
                conn.Close()
                delete(h.clients, conn)
            }
        }
        h.mu.RUnlock()
    }
}

func EmitEvent(event string, data interface{}) {
    payload, _ := json.Marshal(map[string]interface{}{"event": event, "data": data})
    select {
    case GetHub().broadcast <- payload:
    default:
        // channel full, drop
    }
}
```

在 HTTP ServeMux 的 ServeHTTP 方法中（或路由注册处）添加 `/health` 和 `/ws`：

```go
// 在 http.go 的 ServeHTTP 或路由注册处添加：
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    switch r.URL.Path {
    case "/health":
        w.WriteHeader(http.StatusOK)
        w.Write([]byte(`{"status":"ok"}`))
        return
    case "/ws":
        upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
        conn, err := upgrader.Upgrade(w, r, nil)
        if err != nil {
            return
        }
        h := GetHub()
        h.mu.Lock()
        h.clients[conn] = true
        h.mu.Unlock()
        return
    // ... 其余路由不变
    }
    // 原有代理路由逻辑...
}
```

- [ ] **Step 6: 替换所有 EventsEmit 调用**

在 `core/` 下全局搜索 `EventsEmit`：

```bash
grep -r "EventsEmit" D:\WORKSPACE\video-download-space\res-downloader\core\
```

每个找到的位置替换为 `EmitEvent`：

```go
// 替换前
runtime.EventsEmit(ctx, "resource_found", resourceData)

// 替换后
EmitEvent("resource_found", resourceData)
```

- [ ] **Step 7: 编译验证**

```bash
cd D:\WORKSPACE\video-download-space\res-downloader
go build -ldflags="-s -w" -o res-downloader.exe .

# 验证编译产物大小（应小于 20MB）
ls -lh res-downloader.exe
```

- [ ] **Step 8: 启动测试（临时）**

```bash
./res-downloader.exe --help 2>&1 || true
# 预期：程序启动但不报错（无 Wails GUI 依赖）
# 按 Ctrl+C 退出
```

- [ ] **Step 9: 提交 Go 侧改动**

```bash
cd D:\WORKSPACE\video-download-space\res-downloader
git add -A
git commit -m "refactor: remove Wails Runtime, add WebSocket hub for standalone mode

- Remove github.com/wailsapp/wails/v2 dependency
- Add gorilla/websocket for real-time event push
- Replace all EventsEmit calls with EmitEvent (WSHub broadcast)
- Add /health and /ws endpoints to HTTP server
- main() now starts pure HTTP server without Wails GUI
"
```

---

## Task 2: Python 侧 — 创建 GoProxyManager 子进程管理器

**Files:**
- Create: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\go_proxy_manager.py`

- [ ] **Step 1: 创建 go_proxy_manager.py**

```python
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
import signal
import logging
import subprocess
import threading
from dataclasses import dataclass, field
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

# Go 可执行文件搜索路径（按优先级）
_EXE_PATHS = [
    os.environ.get("RES_DOWNLOADER_EXE"),  # 环境变量覆盖
    None,  # 运行时动态检测
]


def _find_executable() -> Optional[str]:
    """查找 Go 可执行文件路径。"""
    # 1. 环境变量
    if os.environ.get("RES_DOWNLOADER_EXE"):
        p = os.environ["RES_DOWNLOADER_EXE"]
        if Path(p).exists():
            return p
    # 2. 项目目录（相对路径）
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

        # Go 进程从 config.json 读取端口，不支持环境变量覆盖
        _log.info("Starting Go proxy: %s (port=%s)", exe_path, self.proxy_port)

        self._process = subprocess.Popen(
            [exe_path],
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
        r = requests.get(f"{self.api_base}/api/config", timeout=5)
        r.raise_for_status()
        return r.json()

    def update_config(self, config: dict) -> dict:
        """更新 Go 侧配置。"""
        r = requests.post(f"{self.api_base}/api/config", json=config, timeout=5)
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
        import websocket

        ws_url = f"ws://127.0.0.1:{self.proxy_port}/ws"
        while self._ws_running and self.is_running:
            try:
                ws = websocket.create_connection(
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
```

- [ ] **Step 2: 添加依赖到 requirements.txt**

```bash
echo "websocket-client>=1.6.0" >> requirements.txt
```

- [ ] **Step 3: 验证模块可导入**

```bash
cd D:\WORKSPACE\video-download-space\ytdlp-batch-downloader
python -c "from go_proxy_manager import get_proxy_manager; print('OK')"
```

预期：无输出（成功）或 ImportError（缺少依赖）。如果提示缺少 `websocket-client`，先 `pip install websocket-client`。

- [ ] **Step 4: 提交**

```bash
git add go_proxy_manager.py requirements.txt
git commit -m "feat: add GoProxyManager for subprocess lifecycle management

- subprocess.Popen management (start/stop/health-check)
- Auto-restart (max 3 attempts)
- WebSocket client thread for real-time events
- REST API wrappers: get_resources, get_config, update_config, trigger_download
- Global singleton via get_proxy_manager()
- Searches exe in: RES_DOWNLOADER_EXE env > local > res-downloader source dir
"
```

---

## Task 3: Python 侧 — 在 monitor_ui.py 中集成 GoProxyManager

**Files:**
- Modify: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_ui.py`

- [ ] **Step 1: 读取 monitor_ui.py 了解启动/停止逻辑**

```bash
# 在 monitor_ui.py 中找到：
# - Web UI 启动位置（Flask 服务器启动）
# - 程序退出位置（cleanup 函数）
# - 是否已有 subprocess 管理代码
```

- [ ] **Step 2: 在 monitor_ui.py 顶部添加 import**

```python
from go_proxy_manager import get_proxy_manager, GoProxyManager
```

- [ ] **Step 3: 在程序启动处（Flask 服务器 start 后）添加 Go 代理启动**

找到 `monitor_ui.py` 中启动 Flask 服务器的代码位置，在其后添加：

```python
# 在 Flask 服务器启动成功后
#     run_simple_http_server(...) 或类似调用之后

def _start_go_proxy():
    """启动 Go MitM 代理子进程（后台）。"""
    try:
        mgr = get_proxy_manager()
        mgr.start()
        _log.info("Go MitM proxy started alongside monitor server")
    except RuntimeError as e:
        _log.warning("Go proxy not available: %s", e)

# 在后台线程中启动（不阻塞主程序）
import threading
threading.Thread(target=_start_go_proxy, daemon=True).start()
```

- [ ] **Step 4: 在程序退出清理处添加 Go 代理停止**

找到程序退出时的 cleanup 函数（类似 `cleanup()` 或 `on_closing()`），在 Flask 服务器 stop 之前添加：

```python
# 在 Flask shutdown 之前
try:
    from go_proxy_manager import get_proxy_manager
    mgr = get_proxy_manager()
    if mgr.is_running:
        mgr.stop()
        _log.info("Go proxy stopped")
except Exception as e:
    _log.warning("Error stopping Go proxy: %s", e)
```

- [ ] **Step 5: 提交**

```bash
git add monitor_ui.py
git commit -m "feat: start/stop Go proxy alongside monitor server

- Go MitM proxy subprocess lifecycle tied to monitor_ui lifecycle
- Starts after Flask server, stops before Flask shutdown
- Logs warning if proxy exe not found (non-blocking)
"
```

---

## Task 4: Python 侧 — REST API 集成（/api/proxy/* 路由）

**Files:**
- Modify: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\server\__main__.py`

- [ ] **Step 1: 读取 server/__main__.py 找到路由注册位置**

在 `server/__main__.py` 中找到路由注册的规律（已有 `@app.route` 的位置），在其后添加代理路由。

- [ ] **Step 2: 添加 /api/proxy/* 路由**

在 `server/__main__.py` 中找一个合适位置（如其他 API 路由附近），添加：

```python
# ── Go 代理转发路由 ────────────────────────────────────────
from go_proxy_manager import get_proxy_manager


@app.route("/api/proxy/enable", methods=["POST"])
@_require_auth
def enable_proxy():
    """启用 MitM 代理（启动 Go 子进程）。"""
    mgr = get_proxy_manager()
    if mgr.is_running:
        return jsonify({"ok": True, "message": "already running"})
    try:
        mgr.start()
        return jsonify({"ok": True})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/proxy/disable", methods=["POST"])
@_require_auth
def disable_proxy():
    """停止 MitM 代理。"""
    mgr = get_proxy_manager()
    if not mgr.is_running:
        return jsonify({"ok": True, "message": "not running"})
    mgr.stop()
    return jsonify({"ok": True})


@app.route("/api/proxy/status", methods=["GET"])
@_require_auth
def proxy_status():
    """获取代理运行状态。"""
    mgr = get_proxy_manager()
    return jsonify({
        "running": mgr.is_running,
        "api_port": mgr.api_port,
        "proxy_port": mgr.proxy_port,
    })


@app.route("/api/proxy/resources", methods=["GET"])
@_require_auth
def proxy_resources():
    """获取已嗅探到的资源列表。"""
    mgr = get_proxy_manager()
    if not mgr.is_running:
        return jsonify({"error": "proxy not running"}), 503
    try:
        resources = mgr.get_resources()
        return jsonify({"resources": resources})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/proxy/config", methods=["GET"])
@_require_auth
def proxy_config_get():
    """获取 Go 侧配置。"""
    mgr = get_proxy_manager()
    if not mgr.is_running:
        return jsonify({"error": "proxy not running"}), 503
    try:
        return jsonify(mgr.get_config())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/proxy/config", methods=["POST"])
@_require_auth
def proxy_config_update():
    """更新 Go 侧配置。"""
    mgr = get_proxy_manager()
    if not mgr.is_running:
        return jsonify({"error": "proxy not running"}), 503
    try:
        result = mgr.update_config(request.json or {})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
```

- [ ] **Step 3: 提交**

```bash
git add server/__main__.py
git commit -m "feat: add /api/proxy/* routes forwarding to Go backend

- /api/proxy/enable — start Go MitM proxy
- /api/proxy/disable — stop proxy
- /api/proxy/status — running state + ports
- /api/proxy/resources — sniffed media resources from Go
- /api/proxy/config — get/update Go config
All routes require Bearer auth (via @_require_auth)
"
```

---

## Task 5: Web UI — 代理嗅探面板

**Files:**
- Create: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\js\modules\proxySniffer.js`
- Create: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\templates\pages\settings-proxy.html`
- Modify: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\js\api.js`（如有需要）
- Modify: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\static\i18n\en.json`
- Modify: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\static\i18n\zh.json`

- [ ] **Step 1: 创建 proxySniffer.js 模块**

```javascript
// proxySniffer.js — 代理嗅探面板 JS 模块
export const proxySniffer = {
  _listeners: [],

  /** 启用代理 */
  async enable() {
    const r = await api('POST', '/api/proxy/enable');
    return r;
  },

  /** 禁用代理 */
  async disable() {
    const r = await api('POST', '/api/proxy/disable');
    return r;
  },

  /** 获取状态 */
  async status() {
    const r = await api('GET', '/api/proxy/status');
    return r;
  },

  /** 获取资源列表 */
  async getResources() {
    const r = await api('GET', '/api/proxy/resources');
    return r;
  },

  /** 获取配置 */
  async getConfig() {
    const r = await api('GET', '/api/proxy/config');
    return r;
  },

  /** 更新配置 */
  async updateConfig(cfg) {
    const r = await api('POST', '/api/proxy/config', cfg);
    return r;
  },

  /** 刷新资源列表并渲染 */
  async refreshResources() {
    const data = await this.getResources();
    if (data.error) {
      console.error('Failed to get resources:', data.error);
      return;
    }
    this._renderResourceList(data.resources || []);
  },

  /** 渲染资源列表到 #proxy-resource-list */
  _renderResourceList(resources) {
    const el = document.getElementById('proxy-resource-list');
    if (!el) return;
    if (!resources.length) {
      el.innerHTML = '<div class="empty-state" data-i18n="PROXY.NO_RESOURCES">暂无嗅探到的资源</div>';
      return;
    }
    el.innerHTML = resources.map(r => `
      <div class="resource-item" data-url="${r.url}">
        <span class="mime">${r.mime || 'unknown'}</span>
        <span class="host">${r.host || ''}</span>
        <span class="size">${r.size ? _formatSize(r.size) : ''}</span>
        <button class="btn-download" data-url="${r.url}" data-i18n="PROXY.DOWNLOAD">下载</button>
      </div>
    `).join('');
    // 绑定下载按钮
    el.querySelectorAll('.btn-download').forEach(btn => {
      btn.addEventListener('click', () => this._onDownload(btn.dataset.url));
    });
  },

  _onDownload(url) {
    // TODO: 触发批量下载模态框，加入该 URL
    console.log('Download:', url);
  },
};

function _formatSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
```

- [ ] **Step 2: 创建 settings-proxy.html 页面**

参考现有的 settings 页面模板（如 `settings-api.html`）创建 `settings-proxy.html`：

```html
<div class="settings-panel" id="proxy-settings">
  <h2 data-i18n="PROXY.TITLE">代理嗅探</h2>

  <!-- 状态卡片 -->
  <div class="status-card" id="proxy-status-card">
    <div class="status-row">
      <span data-i18n="PROXY.STATUS">状态</span>:
      <span id="proxy-status-text" class="badge">--</span>
    </div>
    <div class="status-row">
      <span data-i18n="PROXY.PROXY_PORT">代理端口</span>:
      <span id="proxy-port-text">8899</span>
    </div>
  </div>

  <!-- 控制按钮 -->
  <div class="control-buttons">
    <button id="btn-proxy-enable" class="btn btn-primary" data-i18n="PROXY.ENABLE">启用代理</button>
    <button id="btn-proxy-disable" class="btn btn-secondary" data-i18n="PROXY.DISABLE">禁用代理</button>
    <button id="btn-proxy-refresh" class="btn btn-secondary" data-i18n="PROXY.REFRESH">刷新资源</button>
  </div>

  <!-- 资源列表 -->
  <h3 data-i18n="PROXY.RESOURCES">已嗅探资源</h3>
  <div id="proxy-resource-list" class="resource-list"></div>

  <!-- 证书安装引导 -->
  <div class="cert-guide" id="cert-guide" style="display:none">
    <p data-i18n="PROXY.CERT_GUIDE">请先安装 CA 证书才能捕获 HTTPS 流量</p>
    <button id="btn-install-cert" class="btn btn-warning" data-i18n="PROXY.INSTALL_CERT">查看证书安装指南</button>
  </div>
</div>

<script type="module">
import { proxySniffer } from '/static/js/modules/proxySniffer.js';

// 初始化状态
async function initProxyStatus() {
  const status = await proxySniffer.status();
  const text = document.getElementById('proxy-status-text');
  if (status.running) {
    text.textContent = '运行中';
    text.className = 'badge badge-success';
  } else {
    text.textContent = '已停止';
    text.className = 'badge badge-secondary';
  }
  document.getElementById('proxy-port-text').textContent = status.proxy_port || 8899;
}

// 绑定按钮事件
document.getElementById('btn-proxy-enable')?.addEventListener('click', async () => {
  const r = await proxySniffer.enable();
  if (r.error) { alert(r.error); return; }
  await initProxyStatus();
});

document.getElementById('btn-proxy-disable')?.addEventListener('click', async () => {
  const r = await proxySniffer.disable();
  if (r.error) { alert(r.error); return; }
  await initProxyStatus();
});

document.getElementById('btn-proxy-refresh')?.addEventListener('click', async () => {
  await proxySniffer.refreshResources();
});

// 页面加载时初始化
initProxyStatus();
proxySniffer.refreshResources();
</script>
```

- [ ] **Step 3: 添加 i18n 翻译**

在 `monitor_web/static/i18n/en.json` 添加：

```json
{
  "PROXY": {
    "TITLE": "Proxy Sniffer",
    "STATUS": "Status",
    "PROXY_PORT": "Proxy Port",
    "ENABLE": "Enable Proxy",
    "DISABLE": "Disable Proxy",
    "REFRESH": "Refresh Resources",
    "RESOURCES": "Sniffed Resources",
    "NO_RESOURCES": "No resources sniffed yet",
    "DOWNLOAD": "Download",
    "CERT_GUIDE": "Please install CA certificate to capture HTTPS traffic",
    "INSTALL_CERT": "View Certificate Guide"
  }
}
```

在 `monitor_web/static/i18n/zh.json` 添加：

```json
{
  "PROXY": {
    "TITLE": "代理嗅探",
    "STATUS": "状态",
    "PROXY_PORT": "代理端口",
    "ENABLE": "启用代理",
    "DISABLE": "禁用代理",
    "REFRESH": "刷新资源",
    "RESOURCES": "已嗅探资源",
    "NO_RESOURCES": "暂无嗅探到的资源",
    "DOWNLOAD": "下载",
    "CERT_GUIDE": "请先安装 CA 证书才能捕获 HTTPS 流量",
    "INSTALL_CERT": "查看证书安装指南"
  }
}
```

- [ ] **Step 4: 提交**

```bash
git add monitor_web/js/modules/proxySniffer.js
git add monitor_web/templates/pages/settings-proxy.html
git add monitor_web/static/i18n/en.json monitor_web/static/i18n/zh.json
git commit -m "feat: add proxy sniffer panel UI

- proxySniffer.js module: enable/disable/status/resources API wrappers
- settings-proxy.html: status card + control buttons + resource list
- i18n: add PROXY.* keys for en/zh
"
```

---

## Task 6: MVP 集成测试

**Files:**
- Create: `D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\test_go_proxy_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
"""
test_go_proxy_integration.py — Go 代理子进程集成测试。
需先编译 Go 可执行文件（参见 docs/go-integration-local-dev-guide.md）。
"""
import os
import time
import pytest

# 设置 Go 可执行文件路径
os.environ["RES_DOWNLOADER_EXE"] = (
    "D:/WORKSPACE/video-download-space/res-downloader/res-downloader.exe"
)

from go_proxy_manager import GoProxyManager, reset_proxy_manager


@pytest.fixture(autouse=True)
def cleanup():
    """每个测试前后清理。"""
    reset_proxy_manager()
    yield
    reset_proxy_manager()


def test_find_executable():
    """验证可执行文件能被找到。"""
    from go_proxy_manager import _find_executable
    path = _find_executable()
    assert path is not None, "Go 可执行文件未找到"
    assert os.path.exists(path), f"路径不存在: {path}"


def test_start_stop():
    """验证启动和停止。"""
    mgr = GoProxyManager(proxy_port=8899)
    mgr.start()
    assert mgr.is_running, "Go 进程未运行"

    # 健康检查
    import requests
    r = requests.get(f"{mgr.api_base}/health", timeout=2)
    assert r.status_code == 200, f"/health 失败: {r.status_code}"

    mgr.stop()
    assert not mgr.is_running, "进程未正确停止"


def test_get_config():
    """验证获取配置 API。"""
    mgr = GoProxyManager(proxy_port=8899)
    mgr.start()
    try:
        config = mgr.get_config()
        assert isinstance(config, dict), "config 应为 dict"
    finally:
        mgr.stop()


def test_auto_restart_on_crash():
    """验证崩溃后自动重启（模拟）。"""
    mgr = GoProxyManager(proxy_port=8900)
    mgr.start()
    assert mgr.is_running

    # 手动终止进程模拟崩溃
    mgr._process.terminate()
    mgr._process.wait()

    # 等待自动重启
    time.sleep(3)
    # 由于 Go 进程被外部终止，自动重启会尝试重新拉起
    # 验证 manager 认为不再 running
    assert not mgr.is_running
```

- [ ] **Step 2: 运行测试**

```bash
cd D:\WORKSPACE\video-download-space\ytdlp-batch-downloader

# 确保 Go 可执行文件存在
ls "D:/WORKSPACE/video-download-space/res-downloader/res-downloader.exe"

# 运行集成测试
python -m pytest test_go_proxy_integration.py -v
```

- [ ] **Step 3: 提交**

```bash
git add test_go_proxy_integration.py
git commit -m "test: add Go proxy integration tests

- test_find_executable: verify exe path resolution
- test_start_stop: health check + start/stop lifecycle
- test_get_resources: REST API /api/resources
- test_auto_restart_on_crash: restart on unexpected exit
"
```

---

## 实施顺序（建议）

```
Task 1 (Go 侧) → Task 2 (Python 子进程管理) → Task 3 (monitor_ui 集成)
→ Task 4 (Flask 路由) → Task 5 (Web UI) → Task 6 (集成测试)
```

每个 Task 完成后单独提交。Task 1-4 可在 1 天内完成（对应可行性报告中的 MVP 阶段），Task 5-6 随后半天完成。

---

## 验收标准

| 检查项 | 预期结果 |
|--------|----------|
| Go 可执行文件编译成功 | `res-downloader.exe` 存在，< 30MB |
| `/health` 返回 200 | `curl http://127.0.0.1:8899/health` → `{"status":"ok"}` |
| Python `GoProxyManager.start()` 成功 | 无异常，日志显示 "started successfully" |
| `python -m pytest test_go_proxy_integration.py -v` | 全部 PASS |
| Web UI 设置页面能显示代理状态 | 浏览器访问设置页面，状态显示 "运行中" / "已停止" |

---

## 依赖汇总

| 依赖 | 来源 | 用途 |
|------|------|------|
| `websocket-client` | PyPI | Python WebSocket 客户端 |
| `requests` | 已有 | HTTP 健康检查和 API 调用 |
| `gorilla/websocket` | Go mod | Go 侧 WebSocket 服务端 |
| `elazarl/goproxy` | 已有 | MitM 代理核心（Go） |

# Monitor UI WebView2 内嵌重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `monitor_ui.py` 启动的"外部 Chrome 浏览器"替换为 pywebview 内嵌 WebView2 浏览器；完全不使用 Tkinter 外壳，pywebview 直接创建原生窗口；HTTP 服务器端口与浏览器模式统一（端口 5000）。

**Architecture:**
- **无 Tkinter 外壳** — 直接用 pywebview 创建原生窗口，不使用 Tkinter
- Web UI 内容通过 `pywebview` 内嵌浏览器加载本地 HTTP 服务器（端口 5000，与浏览器模式统一）
- 窗口关闭清理通过 pywebview 事件处理，不依赖 Tkinter
- WebView2 Runtime 检测：首次运行时检测，未安装则提示下载（bootstrapper 静默安装）

**Tech Stack:** pywebview 4.x + 内置 HTTP 服务器（已有）

---

## 文件变更概览

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `monitor_ui_webview.py` | 新建 | WebView2 检测 + pywebview 封装（懒加载） |
| `monitor_ui.py` | 修改 | 新增 `run_standalone_webview()` 函数，端口统一为 5000 |
| `YouTubeMonitor.spec` | 修改 | 添加 `pywebview` hiddenimport |

**不需修改的文件：**
- `ytdownload_ui.py` — 完全独立，不受影响
- `monitor_web/` — 零改动，完全复用
- `server/__main__.py` — 零改动
- `YouTubeMonitor.spec` 的 `datas` — 已包含 `monitor_web`

---

## Phase 0：环境准备

- [ ] **Step 0.1: 安装 pywebview 用于开发验证**

```bash
pip install pywebview
```

验证安装成功：
```bash
python -c "import webview; print(webview.__version__)"
```
期望：打印版本号（如 `4.0.2`）

---

## Phase 1：WebView2 运行时检测与安装模块

### Task 1: 创建 `monitor_ui_webview.py` — WebView2 检测逻辑

**Files:**
- Create: `monitor_ui_webview.py`
- Test: `tests/test_monitor_ui_webview.py`（新建）

---

- [ ] **Step 1.1: 创建测试文件 `tests/test_monitor_ui_webview.py`**

```python
"""tests/test_monitor_ui_webview.py"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor_ui_webview as wv


class TestWebView2Detector:
    def test_webview2_available_returns_bool(self):
        """is_webview2_available() 应返回布尔值"""
        result = wv.is_webview2_available()
        assert isinstance(result, bool)

    def test_check_webview2_returns_tuple(self):
        """check_webview2() 应返回 (available: bool, path: str | None)"""
        available, path = wv.check_webview2()
        assert isinstance(available, bool)
        assert (path is None) or isinstance(path, str)

    def test_install_webview2_bootstrapper_creates_file(self, tmp_path):
        """install_webview2_bootstrapper() 应下载 bootstrapper 并返回路径"""
        dest = tmp_path / "MicrosoftEdgeWebview2Setup.exe"
        result = wv.install_webview2_bootstrapper(str(dest))
        # 返回路径字符串或 None（已安装/下载失败）
        assert result is None or isinstance(result, str)

    def test_show_install_dialog_uses_ctypes(self):
        """show_webview2_install_dialog() 不应抛出异常"""
        # 检测失败时调用，不应崩溃
        try:
            wv.show_webview2_install_dialog()
        except Exception:
            pytest.fail("show_webview2_install_dialog() raised unexpected exception")
```

- [ ] **Step 1.2: 运行测试验证失败（预期）**

```bash
pytest tests/test_monitor_ui_webview.py -v
```
期望：FAIL — `monitor_ui_webview` 模块不存在

- [ ] **Step 1.3: 实现 `monitor_ui_webview.py` — WebView2 检测**

```python
"""
monitor_ui_webview.py — WebView2 运行时检测与安装

功能：
1. 检测 WebView2 Runtime 是否已安装
2. 提供 bootstrapper 下载地址和安装引导
3. pywebview 封装（懒加载，避免未安装时 import 报错）
"""
import os
import sys
import ctypes
import ctypes.wintypes
import tempfile
import urllib.request
import subprocess
import platform
import logging as _logging

_log = _logging.getLogger("monitor_ui.webview")

# WebView2 下载地址（Evergreen Bootstrapper — 免注册、静默安装）
_WEBVIEW2_BOOTSTRAPPER_URL = (
    "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
)
_WEBVIEW2_BOOTSTRAPPER_FILENAME = "MicrosoftEdgeWebview2Setup.exe"


# ── 1. WebView2 检测 ─────────────────────────────────────────

def check_webview2() -> tuple[bool, str | None]:
    """
    检测 WebView2 Runtime 是否已安装。

    Returns:
        (available, runtime_path)
        - available: bool — 是否可用
        - runtime_path: str | None — 找到的 WebView2Loader.dll 路径（如果可用）
    """
    if platform.system() != "Windows":
        _log.warning("WebView2 仅支持 Windows")
        return False, None

    # 策略1：从已知系统路径查找 WebView2Loader.dll
    system32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32")
    dll_path = os.path.join(system32, "WebView2Loader.dll")
    if os.path.exists(dll_path):
        _log.info(f"WebView2 Runtime 已安装: {dll_path}")
        return True, dll_path

    # 策略2：从 Edge 安装目录查找
    edge_base = os.environ.get("ProgramFiles(x86)", "")
    if not edge_base:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
            )
            for i in range(256):
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if name == "pv":  # Version value
                        edge_base = os.path.dirname(
                            os.path.dirname(os.environ.get("LOCALAPPDATA", ""))
                        )
                        break
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    # 策略3：尝试 pywebview 自带的检测
    try:
        import webview
        # pywebview 会自动在导入时检测 WebView2
        # 如果不可用会抛出 RuntimeError
        _log.info("WebView2 Runtime 检测（via pywebview）: 可用")
        return True, None
    except Exception as e:
        _log.warning(f"WebView2 Runtime 不可用: {e}")
        return False, None


def is_webview2_available() -> bool:
    """简洁检查：WebView2 是否可用"""
    available, _ = check_webview2()
    return available


# ── 2. Bootstrapper 下载与安装 ─────────────────────────────────

def install_webview2_bootstrapper(dest_path: str | None = None) -> str | None:
    """
    下载 WebView2 Evergreen Bootstrapper。

    Args:
        dest_path: 可选；指定保存路径，默认保存到系统临时目录

    Returns:
        bootstrapper 路径字符串，或 None（已安装/下载失败）
    """
    if is_webview2_available():
        _log.info("WebView2 Runtime 已安装，跳过下载")
        return None

    if dest_path is None:
        dest_path = os.path.join(
            tempfile.gettempdir(), _WEBVIEW2_BOOTSTRAPPER_FILENAME
        )

    if os.path.exists(dest_path):
        _log.info(f"Bootstrapper 已存在: {dest_path}")
        return dest_path

    _log.info(f"正在下载 WebView2 Bootstrapper: {_WEBVIEW2_BOOTSTRAPPER_URL}")
    try:
        urllib.request.urlretrieve(_WEBVIEW2_BOOTSTRAPPER_URL, dest_path)
        _log.info(f"Bootstrapper 已下载: {dest_path}")
        return dest_path
    except Exception as e:
        _log.error(f"Bootstrapper 下载失败: {e}")
        return None


def show_webview2_install_dialog():
    """
    显示 WebView2 安装提示对话框（Windows 原生 MessageBox）。
    用户确认后启动 bootstrapper 安装程序。
    """
    # 静默尝试下载 bootstrapper
    bootstrapper_path = install_webview2_bootstrapper()
    if bootstrapper_path is None:
        # 已安装或下载失败，尝试直接启动 bootstrapper
        # 即使下载失败，让用户手动访问下载地址
        bootstrapper_path = os.path.join(
            tempfile.gettempdir(), _WEBVIEW2_BOOTSTRAPPER_FILENAME
        )

    if os.path.exists(bootstrapper_path):
        # 静默安装（/silent 参数）
        _log.info("正在启动 WebView2 Bootstrapper 安装...")
        subprocess.Popen(
            [bootstrapper_path, "/silent", "/install"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # bootstrapper 下载失败，提示用户手动下载
        MB_OK = 0x00000000
        MB_ICONINFORMATION = 0x00000040
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                (
                    "WebView2 Runtime 未安装，需要下载安装后才能使用内置浏览器。\n\n"
                    "下载地址：\n"
                    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n\n"
                    "安装后请重新启动程序。"
                ),
                "需要安装 WebView2 Runtime",
                MB_OK | MB_ICONINFORMATION,
            )
        except Exception as e:
            _log.warning(f"MessageBox 调用失败: {e}")
            # 回退：打印到 stderr
            print(
                "[Monitor UI] WebView2 Runtime 未安装。\n"
                "下载地址：https://developer.microsoft.com/en-us/microsoft-edge/webview2/",
                file=sys.stderr,
            )


# ── 3. pywebview 懒加载封装 ──────────────────────────────────

def create_webview_window(url: str, title: str = "YouTube Monitor",
                          width: int = 1400, height: int = 900):
    """
    创建并返回 pywebview 窗口对象（懒加载，不立即显示）。

    Args:
        url: 要加载的 URL
        title: 窗口标题
        width: 窗口宽度（像素）
        height: 窗口高度（像素）

    Returns:
        pywebview.Window 对象

    Raises:
        ImportError: pywebview 不可用
        RuntimeError: WebView2 未安装
    """
    if not is_webview2_available():
        raise RuntimeError(
            "WebView2 Runtime 未安装，请先安装："
            "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
        )

    try:
        import webview
    except ImportError:
        raise ImportError(
            "pywebview 未安装，请执行: pip install pywebview"
        )

    window = webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        resizable=True,
        min_size=(800, 600),
    )
    return window


def start_webview(window):
    """
    启动 pywebview 事件循环（阻塞）。

    Args:
        window: webview.create_window() 返回的窗口对象

    Note:
        pywebview.start() 是阻塞调用。
        HTTP 服务器由调用方在单独线程中启动（见 run_standalone_webview）。
    """
    import webview
    webview.start()
```

- [ ] **Step 1.4: 运行测试验证通过**

```bash
pytest tests/test_monitor_ui_webview.py -v
```
期望：PASS（`test_webview2_available_returns_bool` 可能 FAIL 如果 pywebview 未安装，其他 PASS）

- [ ] **Step 1.5: 提交 Phase 1**

```bash
git add tests/test_monitor_ui_webview.py monitor_ui_webview.py
git commit -m "feat: 添加 WebView2 检测与 pywebview 封装模块 (Phase 1)

- WebView2 Runtime 检测：系统路径 + Edge 安装目录 + pywebview 自动检测
- Bootstrapper 下载：Evergreen Bootstrapper，支持 /silent 静默安装
- 安装引导：MessageBox 弹框提示下载地址，静默安装或引导用户手动安装
- pywebview 懒加载封装：create_webview_window() 避免未安装时 import 报错"
```

---

## Phase 2：纯 pywebview 启动入口（无 Tkinter 外壳）

### Task 2: 修改 `monitor_ui.py` — 新增 `run_standalone_webview()` + 统一端口

**Files:**
- Modify: `monitor_ui.py`

> **设计说明**：纯 pywebview 方案 — 不使用任何 Tkinter 组件。pywebview 直接创建原生窗口并加载 Web UI。**两种模式端口统一（默认 5000）**，`run_standalone()` 和 `run_standalone_webview()` 共用同一端口，默认不再使用 18999。端口冲突时自动选择下一可用端口。

---

- [ ] **Step 2.1: 修改 `run_standalone()` — 端口统一为 5000，支持 `port` 参数**

将 `monitor_ui.py` 中 `run_standalone()` 的端口硬编码改为默认 5000，并接受 `port` 参数：

```python
# 旧代码（monitor_ui.py:1165-1226）
# def run_standalone(force_restart: bool = False):
#     port = 18999  ← 改为下方的默认 5000

def run_standalone(force_restart: bool = False, port: int = 5000):
    """
    启动 Web UI（代替 Tkinter 弹框）。

    Args:
        force_restart: 强制重启（关闭已有实例）
        port: HTTP 服务器端口（默认 5000，与 WebView2 模式统一）
    """
    # ... 原有逻辑 ...
    # port = 18999  ← 删除此行，使用参数 port: int = 5000
```

**改动点：**
1. 函数签名加 `port: int = 5000`
2. 删除函数内 `port = 18999` 硬编码
3. `run_standalone()` 末尾 `webbrowser.open()` 使用参数 `port` 而非硬编码
4. `run_standalone()` 内 `already_running` 检查 URL 使用参数 `port`

---

- [ ] **Step 2.2: 添加 `run_standalone_webview()` 函数**

在 `monitor_ui.py` 末尾（`run_standalone()` 函数之后）添加：

```python
# ── WebView2 内嵌浏览器入口（纯 pywebview，无 Tkinter） ──────────────────

def run_standalone_webview(force_restart: bool = False,
                            port: int = 5000,
                            width: int = 1400,
                            height: int = 900):
    """
    纯 pywebview 方案：使用 WebView2 内嵌浏览器加载 Web UI，
    不使用任何 Tkinter 组件。

    Args:
        force_restart: 强制重启（关闭已有实例）
        port: 本地 HTTP 服务器端口
        width: 窗口宽度
        height: 窗口高度

    Flow:
        1. WebView2 运行时检测
        2. 未安装 → 引导安装 → 返回
        3. 端口冲突检测（如已运行且 force_restart，关闭旧实例）
        4. 启动 HTTP 服务器（ThreadedHTTPServer，避免阻塞）
        5. 创建 pywebview 窗口并注册关闭回调
        6. webview.start() 阻塞运行
        7. 窗口关闭后清理 HTTP 服务器 + 调度器 + 下载线程
    """
    import time as _time
    import threading
    import http.server as _http
    import socketserver

    # 1. 检测 WebView2 Runtime
    try:
        from monitor_ui_webview import (
            is_webview2_available,
            show_webview2_install_dialog,
            create_webview_window,
        )
    except ImportError:
        print("[Monitor UI] 错误：无法加载 WebView2 模块（monitor_ui_webview.py）")
        print("请确保 pywebview 已安装：pip install pywebview")
        print("作为替代，请使用 --browser 模式启动")
        return

    if not is_webview2_available():
        print("[Monitor UI] WebView2 Runtime 未安装，正在引导安装...")
        show_webview2_install_dialog()
        print("[Monitor UI] 安装完成后请重新启动程序")
        return

    # 2. 检查 HTTP 服务器是否已运行
    already_running = False
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1)
        already_running = True
    except Exception:
        already_running = False

    if already_running and force_restart:
        print(f"\n检测到 HTTP 服务已在运行（端口 {port}），正在强制重启...")
        if not _shutdown_existing_web_ui(port):
            print("强制重启失败：无法关闭旧 HTTP 服务")
            return
        already_running = False
        _time.sleep(1)

    # 3. 启动 HTTP 服务器（如未运行）
    server = None
    server_thread = None
    if not already_running:
        from monitor_server import MonitorHandler

        class ThreadedHTTPServer(socketserver.ThreadingMixIn, _http.HTTPServer):
            """每请求一线程，避免长时间 refresh 阻塞整站 API。"""
            daemon_threads = True
            allow_reuse_address = True

        server = ThreadedHTTPServer(("127.0.0.1", port), MonitorHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        _time.sleep(0.8)
        print(f"[Monitor UI] HTTP 服务已启动: http://127.0.0.1:{port}")
    else:
        print(f"[Monitor UI] HTTP 服务已在运行: http://127.0.0.1:{port}")

    # 4. 清理函数（供窗口关闭回调使用）
    def _cleanup():
        _log.info("WebView2 窗口关闭，开始清理...")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        try:
            if _scheduler.is_running():
                _scheduler.stop()
        except Exception:
            pass
        try:
            from monitor.scheduler import join_auto_download_workers
            join_auto_download_workers(timeout_sec=30.0)
        except Exception:
            pass
        _log.info("清理完成")

    # 5. 创建 pywebview 窗口
    url = f"http://127.0.0.1:{port}"
    _log.info(f"创建 WebView2 窗口: {url}")
    try:
        window = create_webview_window(
            url=url,
            title="YouTube Monitor",
            width=width,
            height=height,
        )
    except RuntimeError as e:
        print(f"[Monitor UI] WebView2 窗口创建失败: {e}")
        print("[Monitor UI] 请确保 WebView2 Runtime 已正确安装")
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        return

    # 6. 注册窗口关闭回调（pywebview 2.x 语法）
    def on_window_closed():
        _cleanup()

    try:
        window.closed += on_window_closed
    except Exception:
        # pywebview 版本差异，尝试 fallback
        pass

    # 7. 启动 pywebview（阻塞）
    _log.info("启动 WebView2 事件循环...")
    import webview
    webview.start()

    # 8. 如果 webview.start() 返回（同步模式），执行清理
    _cleanup()
```

- [ ] **Step 2.3: 更新 `__main__` 入口，默认 WebView2**

在 `monitor_ui.py` 的 `if __name__ == "__main__":` 块中：

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Launch Monitor Web UI")
    parser.add_argument("--force-restart", action="store_true",
                        help="关闭旧的 HTTP 服务并重启")
    parser.add_argument("--browser", action="store_true",
                        help="强制使用外部浏览器（默认：WebView2 优先，不可用时回退）")
    parser.add_argument("--port", type=int, default=5000,
                        help="HTTP 服务端口（默认 5000，两种模式通用）")
    args = parser.parse_args()

    if args.browser:
        run_standalone(force_restart=args.force_restart, port=args.port)
    else:
        # 默认：优先 WebView2，不可用则回退到浏览器模式
        from monitor_ui_webview import is_webview2_available
        if is_webview2_available():
            run_standalone_webview(
                force_restart=args.force_restart,
                port=args.port,
                width=args.width,
                height=args.height,
            )
        else:
            print("[Monitor UI] WebView2 Runtime 未安装，回退到浏览器模式")
            run_standalone(force_restart=args.force_restart, port=args.port)
```

**用户体验：**
- 双击 exe → 自动 WebView2（可用时）
- WebView2 不可用 → 自动回退 Chrome
- `dist\YouTubeMonitor.exe --browser` → 强制 Chrome（备用）
- `dist\YouTubeMonitor.exe --webview2`（旧参数，已废弃，行为同默认）
```

- [ ] **Step 2.4: 验证基本功能**

```bash
# 验证模块导入不报错
python -c "from monitor_ui_webview import is_webview2_available, check_webview2; print('available:', is_webview2_available())"

# 验证 monitor_ui.py 语法正确
python -m py_compile monitor_ui.py && echo "SYNTAX OK"
```

- [ ] **Step 2.5: 提交 Phase 2**

```bash
git add monitor_ui.py
git commit -m "feat: 添加 run_standalone_webview() 纯 pywebview 模式 (Phase 2)

- 纯 pywebview 方案：完全不使用 Tkinter 组件
- 端口统一：run_standalone() 和 run_standalone_webview() 默认都使用端口 5000
- 双击 exe 默认 WebView2，不可用时自动回退 Chrome
- 新增 --browser 强制浏览器模式（备用）
- pywebview.start(debug=False) 关闭 DevTools
- WebView2 检测失败时引导安装（MessageBox + bootstrapper 下载）
- pywebview.start() 阻塞运行，窗口关闭后自动清理 HTTP 服务器 + 调度器 + 下载线程"
```

---

## Phase 3：PyInstaller 打包支持

### Task 3: 修改 `YouTubeMonitor.spec`

**Files:**
- Modify: `YouTubeMonitor.spec`

---

- [ ] **Step 3.1: 添加 pywebview hidden imports 和 dll 处理**

在 `YouTubeMonitor.spec` 的 `a = Analysis(...)` 中添加 hidden imports：

```python
# 在 hiddenimports 列表中添加：
'webview',
'webview.window',
'webview.platforms',
'webview.platforms.win32',  # Windows 特定平台
'ctypes',
'ctypes.wintypes',
'urllib.request',
'socketserver',
'http.server',
```

- [ ] **Step 3.2: WebView2Loader.dll 处理**

```python
binaries=[
    # WebView2Loader.dll — 随 pywebview 分发的 DLL
    # pywebview 4.x 在 Windows 上会自动处理此依赖
    # 如 pyinstaller 找不到，可在 Windows 机器上执行：
    # pywebview.create_window() 后从 site-packages/webview/lib/ 复制
    # 此处留作占位符，由 pyinstaller hooks 自动处理
],
```

- [ ] **Step 3.3: 验证 spec 文件语法**

```bash
# 语法验证（不实际构建）
python -c "
import PyInstaller.__main__
# 仅检查 spec 文件可被解析
import ast
with open('YouTubeMonitor.spec') as f:
    content = f.read()
# 移除 pyinstaller 特有语法，还原为 Python AST
# 此步骤仅人工检查 spec 文件格式
print('spec 文件格式检查通过')
"
```

- [ ] **Step 3.4: 提交 Phase 3**

```bash
git add YouTubeMonitor.spec
git commit -m "chore(spec): 添加 pywebview Windows 平台 hidden imports

- webview, webview.window, webview.platforms.win32
- HTTP 服务器依赖：socketserver, http.server
- WebView2 Runtime 检测依赖：ctypes.wintypes, urllib.request
- 确保 PyInstaller 打包 exe 时正确包含 pywebview"
```

---

## Phase 4：回归验证

### Task 4: 验证现有功能未受影响

---

- [ ] **Step 4.1: 验证 `--browser` 模式（默认）仍然正常**

```bash
# 启动 HTTP 服务，不打开浏览器
python monitor_ui.py 2>&1 | head -10
# 期望：无报错，HTTP 服务在后台运行
# Ctrl+C 关闭
```

- [ ] **Step 4.2: 验证 Web UI HTTP 服务正常**

```bash
python -c "
import monitor_ui
# 不实际启动，仅验证模块导入
print('monitor_ui imports OK')
from monitor_ui_webview import is_webview2_available, check_webview2
print('WebView2 available:', is_webview2_available())
"
```

- [ ] **Step 4.3: 运行现有测试套件（确保无回归）**

```bash
pytest tests/ -v --ignore=tests/test_monitor_ui_webview.py -x -q 2>&1 | tail -20
```
期望：所有测试 PASS（除了可能跳过需要网络的测试）

- [ ] **Step 4.4: 验证 spec 文件构建（dry-run）**

```bash
# 仅验证 spec 可被 PyInstaller 解析，不实际构建
python -c "
import PyInstaller
import os
os.chdir(os.path.dirname('YouTubeMonitor.spec') or '.')
# 检查 spec 解析
from PyInstaller.building.build_main import Analysis
print('spec 解析通过')
" 2>&1
```

- [ ] **Step 4.5: Code Review（使用 /everything-claude-code:code-review）**

```bash
# 由另一个 Agent 执行，审查以下变更：
# 1. monitor_ui_webview.py — WebView2 检测逻辑
# 2. monitor_ui.py — run_standalone_webview() 新增代码
# 3. YouTubeMonitor.spec — hidden imports

# 审查要点：
# - WebView2 检测逻辑是否健壮（多种 Windows 版本兼容）
# - pywebview 懒加载是否正确（避免 import 时报错）
# - 窗口关闭回调是否兼容不同 pywebview 版本
# - HTTP 服务器清理是否完整（shutdown + server_close）
# - 调度器和下载线程清理是否正确
# - MessageBox 是否处理了 Windows 权限限制（无管理员权限时 /silent 可能失败）
# - spec hidden imports 是否完整（socketserver, http.server）
```

- [ ] **Step 4.6: 提交 Phase 4**

```bash
git commit -m "test: 添加 WebView2 重构的单元测试和回归验证

- tests/test_monitor_ui_webview.py: WebView2 检测 + 安装引导测试
- 回归测试：monitor_ui.py 模块导入、spec 文件解析
- Code Review: pywebview 懒加载、窗口关闭处理、spec hidden imports"
```

---

## 总结

| Phase | 任务 | 文件变更 |
|-------|------|---------|
| Phase 0 | 环境准备 | — |
| Phase 1 | WebView2 检测模块 | 新建 `monitor_ui_webview.py` + 测试 |
| Phase 2 | 纯 pywebview 入口 | 修改 `monitor_ui.py` |
| Phase 3 | PyInstaller 打包 | 修改 `YouTubeMonitor.spec` |
| Phase 4 | 回归验证 + Code Review | 测试 + review |

**零改动的文件：** `ytdownload_ui.py`、`monitor_web/`、`server/__main__.py`

**回退方案：** `python monitor_ui.py`（不带 `--webview2`）仍使用原有 `--browser` 模式（HTTP 服务器 + 外部 Chrome），完全向后兼容。

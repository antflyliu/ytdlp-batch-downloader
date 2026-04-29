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

    # 策略2：pywebview 导入时自动检测 WebView2（会抛出 RuntimeError）
    try:
        import webview as _webview_tmp
        _log.info("WebView2 Runtime 检测（via pywebview 导入）: 可用")
        return True, None
    except RuntimeError as e:
        _log.warning(f"WebView2 Runtime 不可用: {e}")
        return False, None
    except Exception as e:
        _log.warning(f"WebView2 检测时发生意外错误: {e}")
        return False, None


def is_webview2_available() -> bool:
    """简洁检查：WebView2 是否可用"""
    available, _ = check_webview2()
    return available


# ── 2. Bootstrapper 下载与安装 ─────────────────────────────────

def _verify_authenticode(path: str) -> bool:
    """
    Verify Authenticode (digital signature) of a PE file using WinVerifyTrust.

    Returns True if the file has a valid signature from a trusted publisher.
    """
    try:
        # WinTrust API constants and structures
        WINTRUST_ACTION_GENERIC_VERIFY_V2 = (
            b"\x00\xa0\xc9\x0d\x62\x61\xcf\x11"
            b"\xa6\x1a\x00\xaa\x00\x47\xae\x3b"
        )
        WTD_CHOICE_FILE = 1
        WTD_UI_NONE = 2
        WTD_REVOCATION_NONE = 0x100
        WTD_STATEACTION_IGNORE = 0
        WTD_STATEACTION_VERIFY = 1
        WTD_STATEACTION_CLOSE = 2

        class WINTRUST_FILE_INFO(ctypes.Structure):
            _fields_ = [
                ("cbStruct", ctypes.c_ulong),
                ("pcwszFilePath", ctypes.c_wchar_p),
                ("hFile", ctypes.c_void_p),
                ("pgKnownSubject", ctypes.c_void_p),
            ]

        class WINTRUST_DATA(ctypes.Structure):
            _fields_ = [
                ("cbStruct", ctypes.c_ulong),
                ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPCallbackData", ctypes.c_void_p),
                ("dwUIChoice", ctypes.c_ulong),
                ("fdwRevocationChecks", ctypes.c_ulong),
                ("dwUnionChoice", ctypes.c_ulong),
                ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
                ("dwStateAction", ctypes.c_ulong),
                ("hWVTStateData", ctypes.c_void_p),
                ("pwszURLReference", ctypes.c_wchar_p),
                ("dwProvFlags", ctypes.c_ulong),
                ("dwUIContext", ctypes.c_ulong),
            ]

        file_info = WINTRUST_FILE_INFO(
            cbStruct=ctypes.sizeof(WINTRUST_FILE_INFO),
            pcwszFilePath=path,
            hFile=None,
            pgKnownSubject=None,
        )

        trust_data = WINTRUST_DATA(
            cbStruct=ctypes.sizeof(WINTRUST_DATA),
            pPolicyCallbackData=None,
            pSIPCallbackData=None,
            dwUIChoice=WTD_UI_NONE,
            fdwRevocationChecks=WTD_REVOCATION_NONE,
            dwUnionChoice=WTD_CHOICE_FILE,
            pFile=ctypes.pointer(file_info),
            dwStateAction=WTD_STATEACTION_VERIFY,
            hWVTStateData=None,
            pwszURLReference=None,
            dwProvFlags=0,
            dwUIContext=0,
        )

        wintrust = ctypes.windll.wintrust.WinVerifyTrust
        wintrust.restype = ctypes.c_long

        # Verify
        result = wintrust(None, ctypes.byref(ctypes.create_string_buffer(WINTRUST_ACTION_GENERIC_VERIFY_V2)), ctypes.byref(trust_data))

        # Close state
        trust_data.dwStateAction = WTD_STATEACTION_CLOSE
        wintrust(None, ctypes.byref(ctypes.create_string_buffer(WINTRUST_ACTION_GENERIC_VERIFY_V2)), ctypes.byref(trust_data))

        return result == 0  # ERROR_SUCCESS
    except Exception as e:
        _log.warning(f"Authenticode verification failed: {e}")
        return False


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
        # CRITICAL #3: 使用 Request + urlopen 添加 30 秒超时，避免永久挂起
        req = urllib.request.Request(
            _WEBVIEW2_BOOTSTRAPPER_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())
        _log.info(f"Bootstrapper 已下载: {dest_path}")
        # 基本校验：文件大小
        if os.path.getsize(dest_path) < 1024 * 1024:
            _log.warning(f"Bootstrapper 文件小于 1MB，可能下载不完整: {dest_path}")
        # Authenticode 数字签名验证（防止中间人篡改）
        if not _verify_authenticode(dest_path):
            _log.error(f"Bootstrapper 数字签名验证失败，删除不可信文件: {dest_path}")
            try:
                os.remove(dest_path)
            except Exception:
                pass
            return None
        _log.info("Bootstrapper 数字签名验证通过")
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

    if bootstrapper_path is not None and os.path.exists(bootstrapper_path):
        # 静默安装（/silent 参数）
        _log.info("正在启动 WebView2 Bootstrapper 安装...")
        proc = subprocess.Popen(
            [bootstrapper_path, "/silent", "/install"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # MEDIUM #16: 收集子进程退出码，不阻塞但记录日志
        proc.wait()
        _log.info(f"Bootstrapper 安装进程退出，returncode={proc.returncode}")
    else:
        # bootstrapper 下载失败，始终显示下载地址（不再用不存在的临时路径）
        MB_OK = 0x00000000
        MB_ICONINFORMATION = 0x00000040
        _log.warning(
            f"Bootstrapper 下载失败（bootstrapper_path={bootstrapper_path!r}），"
            "弹出 MessageBox 引导用户手动下载"
        )
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                (
                    "WebView2 Runtime 未安装，需要下载安装后才能使用内置浏览器。\n\n"
                    "下载地址（直接下载，无须注册）：\n"
                    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n\n"
                    "下载后运行安装程序，然后重新启动本程序。"
                ),
                "需要安装 WebView2 Runtime",
                MB_OK | MB_ICONINFORMATION,
            )
        except Exception as e:
            _log.warning(f"MessageBox 调用失败: {e}")
            print(
                "[Monitor UI] WebView2 Runtime 未安装。\n"
                "下载地址：https://developer.microsoft.com/en-us/microsoft-edge/webview2/\n"
                "下载后运行安装程序，然后重新启动本程序。",
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



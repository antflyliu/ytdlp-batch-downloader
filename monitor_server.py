"""
monitor_server.py — 转发到 server.__main__.py

保留入口兼容性：`python monitor_server.py` 仍可启动服务。
实际实现已移至 server/__main__.py。
"""
# ruff: noqa: E402, N818
import sys as _sys

# 先导入 server.__main__（实际实现），供直接引用和 AttrProxy 使用
import server.__main__ as _server_main


# ── AttrProxy ─────────────────────────────────────────────────────────────────
# server/routes/*.py 中的 Mixin 通过
#   _db = __import__("monitor_server", fromlist=["_db"])._db
# 动态查找，得到 monitor_server._db（AttrProxy 实例）。
#
# 当 mixin 方法访问 self._db.load_config() 时：
#   1. self._db 是 AttrProxy 实例
#   2. "load_config" 不在 __slots__，触发 __getattr__
#   3. AttrProxy.__getattr__("load_config") → getattr(monitor_server, "_db").load_config
#   4. monitor_server._db 在 patch 后指向 FakeDB，返回 FakeDB.load_config
#
# 测试时：mock.patch.object(monitor_server, "_db", FakeDB()) 替换了
# monitor_server._db 绑定。AttrProxy.__getattr__ 每次都通过 getattr() 重新查找，
# 因此能访问到 patch 后的 FakeDB。
#
# __dict__ 是必须的：mock.patch() 用 target.__dict__[name] 存储原始值。
class _AttrProxy:
    """Forward attribute access to the live monitor_server._xxx (respects patches)."""
    __slots__ = ("_name", "__dict__")

    def __init__(self, name: str):
        self._name = name
        # __dict__ 是 mock 必需的（mock.patch 用 __dict__ 存储原始值）
        object.__setattr__(self, "__dict__", {})

    def __repr__(self):
        return f"<AttrProxy {self._name!r}>"

    def __getattr__(self, item):
        # 每次都从 monitor_server 模块查找，支持 patch.object 替换
        return getattr(_sys.modules["monitor_server"], self._name)


# ── 重新导出 server.__main__ 中的符号 ───────────────────────────────────────
from server.__main__ import (
    MonitorHandler,
    _PROJECT_ROOT,
    _STATIC_DIR,
    _INDEX_HTML,
    serve,
    main,
    __doc__,
    _provider_scheduler,
    _cache,
    _quota,
    _rate_limiter,
    _rate_limiter_lock,
    _WEB_BATCH_ACCOUNT_NAME,
    _YOUTUBE_URL_RE,
    _YOUTUBE_HANDLE_RE,
    _YOUTUBE_CHANNEL_ID_RE,
    _normalize_fs_path,
    _is_path_within,
    _resolve_download_output_path,
    _resolve_cookies_file,
    _route_to_download_targets,
    _normalize_batch_result,
    _serialize_batch_task,
    _is_valid_youtube_url,
    batch_download,
    log_download_decision,
    resolve_for_web_batch_download,
)

from Youtube_Downloader import BatchDownloadCancelled
from server.__main__ import (
    _task_mgr as _real_task_mgr,
    _batch_upload_mgr as _real_batch_mgr,
    _DownloadTaskManager,
    _BatchUploadStore,
    _db as _real_db,
    _scheduler as _real_scheduler,
)


# Mixin 动态查找的符号用 AttrProxy（patch.object 替换后 mixin 仍能访问新值）
_db = _AttrProxy("_db")
_scheduler = _AttrProxy("_scheduler")
_provider_scheduler = _AttrProxy("_provider_scheduler")
_cache = _AttrProxy("_cache")
_quota = _AttrProxy("_quota")
_task_mgr = _AttrProxy("_task_mgr")
_batch_upload_mgr = _AttrProxy("_batch_upload_mgr")
_batch_upload_mgr_cls = _AttrProxy("_BatchUploadStore")
_task_mgr_cls = _AttrProxy("_DownloadTaskManager")


# ── 动态转发 ─────────────────────────────────────────────────────────────────
# fallback for symbols not explicitly re-exported (SimpleHTTPRequestHandler, etc.)
def __getattr__(name: str):
    if hasattr(_server_main, name):
        return getattr(_server_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
"""
日志配置 — 所有模块共用
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

# PyInstaller 打包后 __file__ 指向临时解压目录，用 sys._MEIPASS 或 sys.executable 定位
if getattr(sys, 'frozen', False):
    # exe 所在目录（PyInstaller --onedir 模式）
    _EXE_DIR = Path(sys.executable).parent.resolve()
    _PROJECT_ROOT = _EXE_DIR
else:
    # 源码运行模式
    _PROJECT_ROOT = Path(__file__).parent.resolve()

_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_FILE = _LOG_DIR / "ytdl.log"

# 确保目录存在
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# 格式：时间 | 级别 | 模块名 | 消息
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_shared_file_handler: logging.Handler | None = None


def _is_locked_file_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 32


class WindowsSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler variant that keeps writing if Windows blocks rollover."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except OSError as exc:
                    if not _is_locked_file_error(exc):
                        raise
                    # Another process/thread still has the log open. Skip this
                    # rollover attempt and append the record to the active file.
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


def _get_shared_file_handler() -> logging.Handler:
    global _shared_file_handler
    if _shared_file_handler is None:
        file_handler = WindowsSafeRotatingFileHandler(
            _LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FMT))
        _shared_file_handler = file_handler
    return _shared_file_handler


def get_logger(name: str) -> logging.Logger:
    """
    返回以 name 命名的 logger。
    首次调用时配置全局 file handler（所有模块共享）。
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    shared_handler = _get_shared_file_handler()
    if shared_handler not in logger.handlers:
        logger.addHandler(shared_handler)

    return logger

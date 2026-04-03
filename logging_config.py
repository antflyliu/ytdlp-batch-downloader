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

# 禁用传播到根 logger（避免重复输出）
_root_configured = False


def get_logger(name: str) -> logging.Logger:
    """
    返回以 name 命名的 logger。
    首次调用时配置全局 file handler（所有模块共享）。
    """
    global _root_configured
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # 全局 file handler（只配置一次）
        if not _root_configured:
            file_handler = logging.handlers.RotatingFileHandler(
                _LOG_FILE,
                maxBytes=10 * 1024 * 1024,   # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FMT)
            file_handler.setFormatter(formatter)
            # 不加 root handler，只给子 logger 用
            _root_configured = True

        # 每个 logger 自己的 handler
        fh = logging.handlers.RotatingFileHandler(
            _LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATE_FMT))
        logger.addHandler(fh)

    return logger

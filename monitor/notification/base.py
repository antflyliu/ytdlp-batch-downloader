"""
monitor.notification.base — shared constants, types, and utilities
"""

import logging
from datetime import datetime
from typing import Literal

import requests

import logging_config
import monitor.db as _db

_log = logging_config.get_logger("monitor.notification")

# ── Module-level file handler (managed by setup_file_logging) ─────────────────
_file_handler: logging.Handler | None = None

# ── Types & Constants ──────────────────────────────────────────────────────────

Platform = Literal["feishu", "dingtalk", "wecom"]

FEISHU_MODE_CARD = "card_json"
FEISHU_MODE_TEMPLATE = "template"
_FEISHU_MAX_ITEMS = 10

_FEISHU_CARD_SCHEMA = "2.0"
_FEISHU_HEADER_COLORS: dict[str, str] = {
    "new_video": "purple",
    "scan_ok": "blue",
    "scan_new": "green",
}

_FEISHU_MD_V2_ESCAPE_MAP: list[tuple[str, str]] = [
    ("&", "&amp;"),
    ("#", "&#35;"),
    ("!", "&#33;"),
    ("<", "&#60;"),
    (">", "&#62;"),
    ("\\", "&#92;"),
    ("[", "&#91;"),
    ("]", "&#93;"),
    ("(", "&#40;"),
    (")", "&#41;"),
    ("*", "&#42;"),
    ("_", "&#95;"),
    ("~", "&#126;"),
    ("`", "&#96;"),
]


# ── Shared Utilities ───────────────────────────────────────────────────────────

def _feishu_now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _escape_lark_md(text: str) -> str:
    """转义飞书 Markdown 特殊字符，防止破坏模板渲染"""
    if not text:
        return ""
    for src, dst in (
        ("\\", "\\\\"),
        ("[", "\\["),
        ("]", "\\]"),
        ("(", "\\("),
        (")", "\\)"),
        ("*", "\\*"),
        ("_", "\\_"),
        ("`", "\\`"),
    ):
        text = text.replace(src, dst)
    return text


def _escape_feishu_md_v2(text: str) -> str:
    """转义用户文本中的 Markdown 特殊字符（飞书 JSON 2.0 HTML 实体方式）"""
    if not text:
        return ""
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    for src, dst in _FEISHU_MD_V2_ESCAPE_MAP:
        text = text.replace(src, dst)
    return text


def _sanitize_url_for_md(url: str) -> str:
    """处理 URL 中可能破坏 Markdown 链接语法的字符"""
    if not url:
        return ""
    return url.replace(")", "%29").replace(" ", "%20")


def _format_duration_sec(sec: int | float | None) -> str:
    """将视频时长（秒）格式化为 H:MM:SS 或 M:SS；缺失或无效时返回 "—"。"""
    if sec is None:
        return "—"
    try:
        total = int(sec)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── File Logging ───────────────────────────────────────────────────────────────

def setup_file_logging(log_dir: str) -> None:
    global _file_handler
    import os
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "monitor_events.log")
    _file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    _logger = logging.getLogger("monitor.notification")
    _logger.setLevel(logging.INFO)
    if _file_handler not in _logger.handlers:
        _logger.addHandler(_file_handler)


def _file_log(account_name: str, channel_url: str, videos: list[dict], duration_ms: int) -> str:
    lines = [
        f"=== 新视频检测 ===",
        f"账户: {account_name}",
        f"频道: {channel_url}",
        f"新增视频数: {len(videos)}",
        f"耗时: {duration_ms}ms",
        "",
    ]
    for v in videos:
        lines.append(
            f"  [{v.get('published_at', '')[:10]}] {v.get('title', '')[:60]}"
            f" | 观看 {v.get('view_count', 0) or 0:,} | {v.get('url', '')}"
        )
    return "\n".join(lines)

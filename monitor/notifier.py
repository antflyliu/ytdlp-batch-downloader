"""
monitor.notifier — 多平台通知器
支持：日志文件 / 飞书 / 钉钉 / 企业微信
"""
import logging
from datetime import datetime
from typing import Literal

import requests

import logging_config
import monitor.db as _db

_log = logging_config.get_logger("monitor.notifier")

# 文件日志 handler
_file_handler: logging.Handler | None = None

# 平台类型
Platform = Literal["feishu", "dingtalk", "wecom"]

# 模板模式常量
FEISHU_MODE_CARD = "card_json"
FEISHU_MODE_TEMPLATE = "template"
_FEISHU_MAX_ITEMS = 10  # 模板变量中最多展示的视频数

# 飞书卡片 JSON 2.0 常量
_FEISHU_CARD_SCHEMA = "2.0"
_FEISHU_HEADER_COLORS: dict[str, str] = {
    "new_video": "purple",
    "scan_ok": "blue",
    "scan_new": "green",
}


# ── 飞书模板专用工具函数 ───────────────────────────────────────────────────

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


# 飞书 JSON 2.0 Markdown 使用 HTML 实体转义（官方文档）。
# 顺序关键：& 先转义防止后续实体中 & 被重复转义；
# # 紧随其后，因为后续替换均产生 &#XX; 格式，若 # 在后面会导致双重转义。
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


def _escape_feishu_md_v2(text: str) -> str:
    """转义用户文本中的 Markdown 特殊字符（飞书 JSON 2.0 HTML 实体方式）。

    仅用于需要「原样展示」的用户生成内容（如视频标题），
    不要对已经包含 Markdown 语法的模板字符串调用此函数。
    """
    if not text:
        return ""
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    for src, dst in _FEISHU_MD_V2_ESCAPE_MAP:
        text = text.replace(src, dst)
    return text


def _sanitize_url_for_md(url: str) -> str:
    """处理 URL 中可能破坏 Markdown 链接语法 [text](url) 的字符。

    主要防御 `)` 提前关闭链接、空格截断 href 等情况。
    """
    if not url:
        return ""
    return url.replace(")", "%29").replace(" ", "%20")


def _format_duration_sec(sec: int | float | None) -> str:
    """将视频时长（秒）格式化为 H:MM:SS 或 M:SS；缺失或无效时返回 \"—\"。"""
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


def _format_feishu_video_variable(v: dict) -> dict:
    """将单个视频 dict 格式化为模板变量"""
    pub_date = (v.get("published_at") or v.get("upload_date") or "")[:10]
    views = int(v.get("view_count") or 0)
    likes = int(v.get("like_count") or 0)
    comments = int(v.get("comment_count") or 0)
    title = _escape_lark_md((v.get("title") or "").strip())
    url = v.get("url", "")
    duration_text = _format_duration_sec(v.get("duration_sec"))

    return {
        "title": title,
        "title_link": f"[{title}]({url})" if url else title,
        "video_url": url,
        "published_date": pub_date,
        "duration_text": duration_text,
        "view_count_text": f"{views:,}",
        "like_count_text": f"{likes:,}",
        "comment_count_text": f"{comments:,}",
        "stats_line": (
            f"📅 {pub_date}  ⏱ {duration_text}  👁 {views:,}  👍 {likes:,}"
        ),
        "thumbnail_url": v.get("thumbnail_url", ""),
    }


def _build_feishu_template_variables(
    account_name: str,
    channel_name: str | None,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """构建飞书详情通知的模板变量"""
    show_videos = videos[:_FEISHU_MAX_ITEMS]
    real_channel_name = (
        channel_name
        or (show_videos[0].get("channel_handle") if show_videos else None)
        or account_name
    )

    return {
        "account_name": account_name,
        "channel_name": real_channel_name,
        "channel_url": channel_url,
        "total_count": str(len(videos)),
        "display_count": str(len(show_videos)),
        "generated_at": _feishu_now_str(),
        "summary_text": f"共发现 {len(videos)} 个新视频，本卡展示前 {len(show_videos)} 个",
        "overflow_text": (
            f"还有 {len(videos) - len(show_videos)} 个新视频未展开"
            if len(videos) > len(show_videos)
            else "本次已展示全部新视频"
        ),
        "video_list": [_format_feishu_video_variable(v) for v in show_videos],
    }


def _build_feishu_scan_template_variables(
    account_name: str,
    channel_name: str | None,
    channel_url: str,
    total_videos: int,
    new_videos: int,
) -> dict:
    """构建飞书扫描确认通知的模板变量"""
    return {
        "account_name": account_name,
        "channel_name": channel_name or account_name,
        "channel_url": channel_url,
        "total_videos": str(total_videos),
        "new_videos": str(new_videos),
        "status_text": "扫描正常，无新视频" if new_videos == 0 else f"扫描完成，新增 {new_videos} 个视频",
        "generated_at": _feishu_now_str(),
    }


def _build_feishu_template_payload(template_id: str, template_variable: dict) -> dict:
    """构建飞书模板卡片发送请求"""
    return {
        "msg_type": "interactive",
        "card": {
            "type": "template",
            "data": {
                "template_id": template_id,
                "template_variable": template_variable,
            },
        },
    }


# ── 文件日志 ────────────────────────────────────────────────────────────────

def setup_file_logging(log_dir: str) -> None:
    global _file_handler
    import os
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "monitor_events.log")
    _file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    _logger = logging.getLogger("monitor.notifier")
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


# ── 飞书 JSON 2.0 Markdown 内容构建器 ──────────────────────────────────────


def _build_summary_md(
    channel_url: str,
    video_count: int,
    *,
    channel_name: str | None = None,
) -> str:
    """构建卡片摘要区的 Markdown 文本"""
    display_name = (
        _escape_feishu_md_v2(channel_name) if channel_name
        else _escape_feishu_md_v2(channel_url)
    )
    lines = [
        f"**频道**：{display_name}",
        f"**新增**：{video_count} 个视频",
        f"**发送时间**：{_feishu_now_str()}",
    ]
    return "\n".join(lines)


def _build_video_list_md(videos: list[dict], max_items: int = _FEISHU_MAX_ITEMS) -> str:
    """构建视频列表区的 Markdown 文本（编号 + 标题链接 + 统计行）"""
    show = videos[:max_items]
    lines: list[str] = []
    for idx, v in enumerate(show, 1):
        title = _escape_feishu_md_v2((v.get("title") or "").strip())
        url = _sanitize_url_for_md(v.get("url", ""))
        pub_date = (v.get("published_at") or v.get("upload_date") or "")[:10]
        views = int(v.get("view_count") or 0)
        likes = int(v.get("like_count") or 0)
        comments = int(v.get("comment_count") or 0)
        duration_text = _format_duration_sec(v.get("duration_sec"))

        title_part = f"[{title}]({url})" if url else title
        lines.append(f"**{idx}.** {title_part}")
        stats = (
            f"📅 {pub_date}  ⏱ {duration_text}  👁 {views:,}  "
            f"👍 {likes:,}  💬 {comments:,}"
        )
        lines.append(stats)
        if idx < len(show):
            lines.append("")
    return "\n".join(lines)


def _build_footer_md(total: int, displayed: int) -> str:
    """构建页脚区的 Markdown 文本（溢出提示）"""
    if total > displayed:
        return f"还有 **{total - displayed}** 个新视频未展示"
    return "本次已展示全部新视频"


def _build_feishu_card_v2(
    account_name: str,
    channel_url: str,
    videos: list[dict],
    *,
    channel_name: str | None = None,
    header_color: str | None = None,
) -> dict:
    """飞书 JSON 2.0 卡片（Markdown 组件），用于新视频通知。

    https://open.feishu.cn/document/feishu-cards/card-json-v2-components/content-components/rich-text
    """
    color = header_color or _FEISHU_HEADER_COLORS["new_video"]
    displayed = min(len(videos), _FEISHU_MAX_ITEMS)

    elements: list[dict] = [
        {
            "tag": "markdown",
            "content": _build_summary_md(
                channel_url, len(videos), channel_name=channel_name,
            ),
            "text_align": "left",
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": _build_video_list_md(videos),
            "text_align": "left",
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": _build_footer_md(len(videos), displayed),
            "text_align": "left",
            "text_size": "notation",
        },
    ]

    return {
        "msg_type": "interactive",
        "card": {
            "schema": _FEISHU_CARD_SCHEMA,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🎬 {account_name} — {len(videos)} 个新视频",
                },
                "template": color,
            },
            "body": {
                "elements": elements,
            },
        },
    }


# ── 通知平台构建器（旧版 v1 保留供回退） ──────────────────────────────────

def _build_feishu_card(
    account_name: str,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """
    飞书 Interactive Card
    https://open.feishu.cn/document/ukTMukTMukTM/uADOwUjLwgDM14CM4ATN
    """
    video_items = []
    for v in videos[:10]:
        pub_date = (v.get("published_at") or "")[:10]
        views = v.get("view_count") or 0
        likes = v.get("like_count") or 0
        duration_text = _format_duration_sec(v.get("duration_sec"))
        video_items.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{v.get('title', '')}**\n"
                    f"📅 {pub_date}  ⏱ {duration_text}  👁 {views:,}  👍 {likes:,}\n"
                    f"[👉 前往观看]({v.get('url', '')})"
                ),
            },
        })
        video_items.append({"tag": "hr"})

    if len(videos) > 10:
        video_items.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"_...还有 {len(videos) - 10} 个新视频_"},
        })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🎬 {account_name} — {len(videos)} 个新视频"},
                "template": "purple",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**频道**: {channel_url}\n"
                            f"**新增**: {len(videos)} 个视频\n"
                            f"**发送时间**: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
                        ),
                    },
                },
                {"tag": "hr"},
                *video_items,
            ],
        },
    }


def _build_dingtalk_text(
    account_name: str,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """
    钉钉自定义机器人 Text 消息
    https://developers.dingtalk.com/document/app/custom-robot-text messages
    """
    lines = [f"🎬 {account_name} — {len(videos)} 个新视频"]
    lines.append(f"📺 频道: {channel_url}")
    lines.append(f"⏰ {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    for v in videos[:20]:
        pub_date = (v.get("published_at") or "")[:10]
        views = v.get("view_count") or 0
        lines.append(
            f"• [{pub_date}] {v.get('title', '')[:50]}\n"
            f"  👁 {views:,}  {v.get('url', '')}"
        )
    if len(videos) > 20:
        lines.append(f"\n...还有 {len(videos) - 20} 个新视频")
    return {"msgtype": "text", "text": {"content": "\n".join(lines)}}


def _build_dingtalk_markdown(
    account_name: str,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """
    钉钉自定义机器人 Markdown 消息（推荐）
    """
    items = [f"### 🎬 {account_name} — {len(videos)} 个新视频"]
    items.append(f"**📺 频道**: {channel_url}")
    items.append(f"**⏰ 发送时间**: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    items.append("")
    for v in videos[:10]:
        pub_date = (v.get("published_at") or "")[:10]
        views = v.get("view_count") or 0
        items.append(
            f"- **[{v.get('title', '')[:40]}]({v.get('url', '')})**"
        )
        items.append(f"  📅 {pub_date} | 👁 {views:,}")
    if len(videos) > 10:
        items.append(f"\n> ...还有 {len(videos) - 10} 个新视频")
    return {"msgtype": "markdown", "markdown": {"title": f"{account_name}", "text": "\n\n".join(items)}}


def _build_wecom_textcard(
    account_name: str,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """
    企业微信群机器人 Card 消息（TextCard 类型）
    https://developer.work.weixin.qq.com/document/path/91770
    """
    desc_lines = []
    for v in videos[:10]:
        pub_date = (v.get("published_at") or "")[:10]
        views = v.get("view_count") or 0
        desc_lines.append(
            f"📹 {v.get('title', '')[:40]}\n"
            f"   📅 {pub_date} | 👁 {views:,} | [链接]({v.get('url', '')})"
        )
    if len(videos) > 10:
        desc_lines.append(f"...还有 {len(videos) - 10} 个新视频")

    return {
        "msgtype": "textcard",
        "textcard": {
            "title": f"🎬 {account_name} — {len(videos)} 个新视频",
            "description": "\n\n".join(desc_lines),
            "btntxt": "查看更多",
            "url": channel_url,
        },
    }


# ── 统一构建入口 ────────────────────────────────────────────────────────────

def build_notify_payload(
    platform: Platform,
    account_name: str,
    channel_url: str,
    videos: list[dict],
    *,
    channel_name: str | None = None,
    feishu_message_mode: str = FEISHU_MODE_CARD,
    feishu_template_id: str | None = None,
) -> dict:
    """根据平台类型构建通知消息体（飞书支持 card_json / template 双模式）"""
    if platform == "feishu":
        if feishu_message_mode == FEISHU_MODE_TEMPLATE and feishu_template_id:
            return _build_feishu_template_payload(
                feishu_template_id,
                _build_feishu_template_variables(account_name, channel_name, channel_url, videos),
            )
        if feishu_message_mode == FEISHU_MODE_TEMPLATE and not feishu_template_id:
            _log.warning(
                "飞书已配置 template 模式，但未提供 feishu_template_id，自动回退到 card_json"
            )
        return _build_feishu_card_v2(
            account_name, channel_url, videos, channel_name=channel_name,
        )
    elif platform == "dingtalk":
        return _build_dingtalk_markdown(account_name, channel_url, videos)
    elif platform == "wecom":
        return _build_wecom_textcard(account_name, channel_url, videos)
    else:
        raise ValueError(f"不支持的平台: {platform}")


# ── HTTP 发送 ───────────────────────────────────────────────────────────────

def _send_webhook(
    url: str,
    payload: dict,
    platform: Platform,
    timeout: int = 10,
) -> tuple[bool, str]:
    """通用的 Webhook 发送函数"""
    if not url:
        return False, "未配置 Webhook URL"

    try:
        resp = requests.post(url, json=payload, timeout=timeout)

        if platform == "feishu":
            data = resp.json()
            if resp.status_code == 200 and data.get("code") in (0, None):
                return True, str(data)
            return False, f"Feishu错误: {data}"

        elif platform == "dingtalk":
            data = resp.json()
            if resp.status_code == 200 and data.get("errcode") == 0:
                return True, str(data)
            return False, f"DingTalk错误: code={data.get('errcode')} msg={data.get('errmsg')}"

        elif platform == "wecom":
            data = resp.json()
            if resp.status_code == 200 and data.get("errcode") == 0:
                return True, str(data)
            return False, f"WeCom错误: code={data.get('errcode')} msg={data.get('errmsg')}"

        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"

    except requests.Timeout:
        return False, "请求超时"
    except Exception as e:
        return False, str(e)


def _redact_webhook_url(webhook_url: str) -> str:
    """仅保留平台与主机信息，避免 access_token 落库。"""
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(webhook_url)
    except Exception:
        return "[redacted webhook]"
    if not parsed.scheme or not parsed.netloc:
        return "[redacted webhook]"
    return f"{parsed.scheme}://{parsed.netloc}/[redacted]"


def _build_scan_confirm_payload(
    platform: Platform,
    account_name: str,
    channel_url: str,
    total_videos: int,
    new_videos: int,
    *,
    channel_name: str | None = None,
    feishu_message_mode: str = FEISHU_MODE_CARD,
    feishu_scan_template_id: str | None = None,
) -> dict:
    """构建扫描完成的确认消息（无新视频时发送），飞书支持 template 模式"""
    if platform == "feishu":
        if feishu_message_mode == FEISHU_MODE_TEMPLATE and feishu_scan_template_id:
            return _build_feishu_template_payload(
                feishu_scan_template_id,
                _build_feishu_scan_template_variables(
                    account_name, channel_name, channel_url, total_videos, new_videos
                ),
            )
        color = _FEISHU_HEADER_COLORS["scan_new" if new_videos > 0 else "scan_ok"]
        status = (
            f"扫描完成，新增 {new_videos} 个视频" if new_videos > 0
            else "扫描正常，无新视频"
        )
        safe_url = _escape_feishu_md_v2(channel_url)
        md_content = "\n".join([
            f"**频道**：{safe_url}",
            f"**API 返回**：{total_videos} 个视频",
            f"**新增视频**：{new_videos} 个",
            f"**状态**：{status}",
            f"**发送时间**：{_feishu_now_str()}",
        ])
        return {
            "msg_type": "interactive",
            "card": {
                "schema": _FEISHU_CARD_SCHEMA,
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"✅ {account_name} — 扫描完成",
                    },
                    "template": color,
                },
                "body": {
                    "elements": [{
                        "tag": "markdown",
                        "content": md_content,
                        "text_align": "left",
                    }],
                },
            },
        }
    elif platform == "dingtalk":
        return {
            "msgtype": "text",
            "text": {
                "content": (
                    f"✅ {account_name} — 扫描完成\n"
                    f"📺 频道: {channel_url}\n"
                    f"📊 API返回: {total_videos} 个视频\n"
                    f"🆕 新增: {new_videos} 个\n"
                    f"⏰ {_feishu_now_str()}"
                ),
            },
        }
    elif platform == "wecom":
        return {
            "msgtype": "textcard",
            "textcard": {
                "title": f"✅ {account_name} — 扫描完成",
                "description": (
                    f"📺 频道: {channel_url}\n"
                    f"📊 API返回: {total_videos} 个\n"
                    f"🆕 新增: {new_videos} 个\n"
                    f"✅ 扫描正常，无新视频"
                ),
                "btntxt": "查看频道",
                "url": channel_url,
            },
        }
    raise ValueError(f"不支持的平台: {platform}")


def notify(
    event_id: int,
    account_id: int,
    account_name: str,
    channel_url: str,
    videos: list[dict],
    platform: Platform,
    webhook_url: str | None,
    duration_ms: int,
    total_videos: int = 0,
    log_dir: str | None = None,
    *,
    channel_name: str | None = None,
    feishu_message_mode: str = FEISHU_MODE_CARD,
    feishu_template_id: str | None = None,
    feishu_scan_template_id: str | None = None,
) -> None:
    """
    统一通知入口：文件日志 + 指定平台 Webhook
    仅在有新视频时由 scheduler 调用，无新视频不推送消息。

    :param total_videos: API 返回的总视频数
    :param feishu_message_mode: 飞书发送模式，card_json（默认）或 template
    :param feishu_template_id: 飞书详情卡片模板ID（template 模式用）
    :param feishu_scan_template_id: 飞书扫描确认模板ID（template 模式用）
    """
    now_str = _db.now_iso()

    # ── 1. 文件日志 ──────────────────────────────────────
    if videos:
        msg = _file_log(account_name, channel_url, videos, duration_ms)
        _log.info(msg)
        if log_dir and _file_handler:
            logging.getLogger("monitor.notifier").info(msg)

    # ── 2. Webhook ──────────────────────────────────────
    if not webhook_url:
        _log.warning(f"未配置 Webhook（{platform}），跳过推送: {account_name}")
        return

    if not videos:
        _log.info(f"无新视频，跳过 Webhook 推送: {account_name}")
        return

    redacted_webhook = _redact_webhook_url(webhook_url)
    _log.info(
        f"准备发送 {platform} 通知: {account_name} ({len(videos)} 个新视频) "
        f"mode={feishu_message_mode} webhook={redacted_webhook}"
    )
    payload = build_notify_payload(
        platform, account_name, channel_url, videos,
        channel_name=channel_name,
        feishu_message_mode=feishu_message_mode,
        feishu_template_id=feishu_template_id,
    )
    success, response = _send_webhook(webhook_url, payload, platform)
    _log_result(platform, account_name, len(videos), success, response, event_id, account_id, now_str, webhook_url)
    if success:
        _log.info(f"✅ {platform} 通知发送成功: {account_name} → {response[:120]}")
        video_ids = [v["video_id"] for v in videos]
        _db.mark_notify_sent(video_ids, now_str)
    else:
        _log.error(f"❌ {platform} 通知发送失败: {account_name} → {response[:200]}")


def _log_result(
    platform: str,
    account_name: str,
    video_count: int,
    success: bool,
    response: str,
    event_id: int,
    account_id: int,
    now_str: str,
    webhook_url: str,
) -> None:
    """记录通知结果到日志表"""
    http_status = 200 if success else None
    resp_text = response[:500]
    redacted_webhook = _redact_webhook_url(webhook_url)
    with _db.get_connection() as conn:
        conn.execute(
            """INSERT INTO monitor_notify_logs
               (event_id, account_id, account_name, video_count, platform, webhook_url,
                http_status, response_text, sent_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (event_id, account_id, account_name, video_count, platform, redacted_webhook,
             http_status, resp_text, now_str),
        )

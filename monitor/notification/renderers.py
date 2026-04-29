"""
monitor.notification.renderers — High-level card builders and payload factory
"""
import logging_config
import time
from urllib.parse import urlsplit

import requests as _requests

from .base import (
    FEISHU_MODE_CARD,
    FEISHU_MODE_TEMPLATE,
    _escape_feishu_md_v2,
    _feishu_now_str,
    _format_duration_sec,
    _FEISHU_CARD_SCHEMA,
    _FEISHU_HEADER_COLORS,
    _FEISHU_MAX_ITEMS,
    _sanitize_url_for_md,
)
from .feishu import (
    _build_feishu_scan_template_variables,
    _build_feishu_template_payload,
    _build_feishu_template_variables,
)
from .dingtalk import (
    _build_dingtalk_markdown,
    _build_dingtalk_text,
    finalize_dingtalk_webhook_url,
)
from .telegram import _build_telegram_message, _escape_telegram_markdownv2
from .wecom import _build_wecom_textcard


# ── Feishu JSON 2.0 Markdown 内容构建器 ──────────────────────────────────────


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


def _build_feishu_card(
    account_name: str,
    channel_url: str,
    videos: list[dict],
) -> dict:
    """
    飞书 Interactive Card（旧版 v1 保留供回退）
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
                            f"**发送时间**: {_feishu_now_str()}"
                        ),
                    },
                },
                {"tag": "hr"},
                *video_items,
            ],
        },
    }


# ── Scan Confirm Payload ───────────────────────────────────────────────────────


def _build_scan_confirm_payload(
    platform: "Platform",
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


# ── Public Payload Factory ─────────────────────────────────────────────────────

def build_notify_payload(
    platform: "Platform",
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
            import logging_config
            _log = logging_config.get_logger("monitor.notification")
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
    elif platform == "telegram":
        return _build_telegram_message(account_name, channel_url, videos, channel_name=channel_name)
    else:
        raise ValueError(f"不支持的平台: {platform}")


# ── HTTP Sending Utilities ─────────────────────────────────────────────────────


def _send_webhook(
    url: str,
    payload: dict,
    platform: "Platform",
    timeout: int = 60,
    retry_intervals: tuple[int, ...] = (5, 10, 15),
    account_name: str | None = None,
    telegram_chat_id: str | None = None,
) -> tuple[bool, str]:
    """通用的 Webhook 发送函数，带重试机制（间隔 5s/10s/15s）"""
    if not url:
        return False, "未配置 Webhook URL"

    last_error = ""
    _log = logging_config.get_logger("monitor.notification")
    acc_label = f" {account_name} →" if account_name else ""

    # Telegram：注入 chat_id 到 payload，并构造完整的 API URL
    if platform == "telegram" and telegram_chat_id:
        payload = {**payload, "chat_id": telegram_chat_id}
        # url 是 Bot Token，构造标准 Telegram Bot API 端点
        api_url = f"https://api.telegram.org/bot{url}/sendMessage"
    else:
        api_url = url

    for attempt, wait_sec in enumerate([0, *retry_intervals], start=1):
        if wait_sec > 0:
            time.sleep(wait_sec)

        try:
            resp = _requests.post(api_url, json=payload, timeout=timeout)

            if platform == "feishu":
                data = resp.json()
                if resp.status_code == 200 and data.get("code") in (0, None):
                    return True, str(data)
                last_error = f"Feishu错误: {data}"

            elif platform == "dingtalk":
                data = resp.json()
                if resp.status_code == 200 and data.get("errcode") == 0:
                    return True, str(data)
                last_error = f"DingTalk错误: code={data.get('errcode')} msg={data.get('errmsg')}"

            elif platform == "wecom":
                data = resp.json()
                if resp.status_code == 200 and data.get("errcode") == 0:
                    return True, str(data)
                last_error = f"WeCom错误: code={data.get('errcode')} msg={data.get('errmsg')}"

            elif platform == "telegram":
                data = resp.json()
                if resp.status_code == 200 and data.get("ok"):
                    return True, str(data)
                last_error = f"Telegram错误: {data.get('description', data)}"

            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"

        except _requests.Timeout:
            last_error = "请求超时"
        except Exception as e:
            last_error = str(e)

        # 非最后一次尝试，继续重试
        if attempt <= len(retry_intervals):
            _log.warning(f"{platform} 第 {attempt} 次发送失败（等待 {wait_sec}s）:{acc_label} {last_error}")

    return False, last_error


def _redact_webhook_url(webhook_url: str) -> str:
    """仅保留平台与主机信息，避免 access_token 落库。"""
    try:
        parsed = urlsplit(webhook_url)
    except Exception:
        return "[redacted webhook]"
    if not parsed.scheme or not parsed.netloc:
        return "[redacted webhook]"
    return f"{parsed.scheme}://{parsed.netloc}/[redacted]"


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
    import monitor.db as _db

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


# ── AI Clip Notification Builders ──────────────────────────────────────────────

from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# 限制展示数量
_MAX_CLIPS_NOTIFY = 8
_MAX_COLLS_NOTIFY = 4


def _clip_score_emoji(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score >= 8.5:
        return "🟢"
    if score >= 7.0:
        return "🟡"
    if score >= 5.5:
        return "🟠"
    return "⚪"


def _clip_score_label(score: float | None) -> str:
    if score is None:
        return "未评分"
    return f"{score:.1f}"


def _clip_duration_label(seconds: float | int | None) -> str:
    if seconds is None:
        return "未知"
    if isinstance(seconds, float):
        seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Feishu ─────────────────────────────────────────────────────────────────────

def _build_clip_feishu_card(
    video_title: str | None,
    clips: list[dict],
    collections: list[dict],
) -> dict:
    """飞书 JSON 2.0 卡片（Markdown），展示切片结果"""
    color = _FEISHU_HEADER_COLORS.get("new_video", "purple")
    shown = clips[:_MAX_CLIPS_NOTIFY]
    shown_colls = collections[:_MAX_COLLS_NOTIFY]

    # 摘要区
    clip_md_parts = [
        f"**视频**：{_escape_feishu_md_v2(video_title or '未知视频')}",
        f"**切片数**：{len(clips)} 个（展示 {len(shown)} 个）",
        f"**合集数**：{len(collections)} 个（展示 {len(shown_colls)} 个）",
        f"**发送时间**：{_feishu_now_str()}",
    ]
    clip_md_parts.append("")
    clip_md_parts.append("## 🎬 高分切片")
    clip_md_parts.append("")

    for idx, clip in enumerate(shown, 1):
        title = _escape_feishu_md_v2(clip.get("title") or f"切片 {idx}")
        score = clip.get("score")
        duration = clip.get("duration")
        start = clip.get("start_time")
        emoji = _clip_score_emoji(score)
        score_lbl = _clip_score_label(score)
        dur_lbl = _clip_duration_label(duration)
        start_lbl = _clip_duration_label(start) if start is not None else "—"

        clip_md_parts.append(
            f"**{idx}.** {title} {emoji} {score_lbl}分"
        )
        clip_md_parts.append(
            f"⏱ {dur_lbl} | ⏳ 从 {start_lbl} 开始"
        )
        clip_md_parts.append("")

    if len(clips) > _MAX_CLIPS_NOTIFY:
        clip_md_parts.append(f"_...还有 {len(clips) - _MAX_CLIPS_NOTIFY} 个切片未展示_")
        clip_md_parts.append("")

    if shown_colls:
        clip_md_parts.append("## 🎞️ 视频合集")
        clip_md_parts.append("")
        for idx, coll in enumerate(shown_colls, 1):
            coll_title = _escape_feishu_md_v2(coll.get("title") or f"合集 {idx}")
            coll_desc = _escape_feishu_md_v2(coll.get("description") or "")
            coll_dur = _clip_duration_label(coll.get("duration"))
            clip_md_parts.append(f"**{idx}.** {coll_title} ⏱ {coll_dur}")
            if coll_desc:
                clip_md_parts.append(f"_{coll_desc}_")
            clip_md_parts.append("")

    return {
        "msg_type": "interactive",
        "card": {
            "schema": _FEISHU_CARD_SCHEMA,
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"✂️ AI 切片完成 — {len(clips)} 个切片",
                },
                "template": color,
            },
            "body": {
                "elements": [{
                    "tag": "markdown",
                    "content": "\n".join(clip_md_parts),
                    "text_align": "left",
                }],
            },
        },
    }


# ── DingTalk ─────────────────────────────────────────────────────────────────

def _build_clip_dingtalk_markdown(
    video_title: str | None,
    clips: list[dict],
    collections: list[dict],
) -> dict:
    """钉钉 Markdown 格式切片通知"""
    shown = clips[:_MAX_CLIPS_NOTIFY]
    shown_colls = collections[:_MAX_COLLS_NOTIFY]

    lines: list[str] = [
        f"## ✂️ AI 切片完成",
        "",
        f"**视频**：{video_title or '未知视频'}",
        f"**切片数**：{len(clips)} 个 | **合集数**：{len(collections)} 个",
        "",
        "### 🎬 高分切片",
        "",
    ]

    for idx, clip in enumerate(shown, 1):
        title = clip.get("title") or f"切片 {idx}"
        score = clip.get("score")
        duration = clip.get("duration")
        start = clip.get("start_time")
        emoji = _clip_score_emoji(score)
        score_lbl = _clip_score_label(score)
        dur_lbl = _clip_duration_label(duration)
        start_lbl = _clip_duration_label(start) if start is not None else "—"

        lines.append(
            f"{idx}. **{title}** {emoji} {score_lbl}分"
        )
        lines.append(
            f"   ⏱ {dur_lbl} | ⏳ 从 {start_lbl} 开始"
        )
        lines.append("")

    if len(clips) > _MAX_CLIPS_NOTIFY:
        lines.append(f"> _...还有 {len(clips) - _MAX_CLIPS_NOTIFY} 个切片未展示_")
        lines.append("")

    if shown_colls:
        lines.append("### 🎞️ 视频合集")
        lines.append("")
        for idx, coll in enumerate(shown_colls, 1):
            coll_title = coll.get("title") or f"合集 {idx}"
            coll_dur = _clip_duration_label(coll.get("duration"))
            lines.append(f"{idx}. **{coll_title}** ⏱ {coll_dur}")
            if coll.get("description"):
                lines.append(f"   _{coll.get('description')}_")
            lines.append("")

    return {
        "msgtype": "markdown",
        "markdown": {
            "title": f"AI 切片完成 — {video_title or '未知视频'}",
            "text": "\n".join(lines),
        },
    }


# ── Telegram ───────────────────────────────────────────────────────────────────

def _build_clip_telegram_message(
    video_title: str | None,
    clips: list[dict],
    collections: list[dict],
) -> dict:
    """Telegram MarkdownV2 格式切片通知"""
    shown = clips[:_MAX_CLIPS_NOTIFY]
    shown_colls = collections[:_MAX_COLLS_NOTIFY]

    safe_title = _escape_telegram_markdownv2(video_title or "未知视频")
    lines: list[str] = [
        f"✂️ *AI 切片完成*",
        "",
        f"*📺 视频*：{safe_title}",
        f"*📊 切片*：{len(clips)} 个（展示 {len(shown)} 个）",
        f"*🎞️ 合集*：{len(collections)} 个（展示 {len(shown_colls)} 个）",
        "",
        "*🎬 高分切片*",
        "",
    ]

    for idx, clip in enumerate(shown, 1):
        title = _escape_telegram_markdownv2(clip.get("title") or f"切片 {idx}")
        score = clip.get("score")
        duration = clip.get("duration")
        start = clip.get("start_time")
        emoji = _clip_score_emoji(score)
        score_lbl = _clip_score_label(score)
        dur_lbl = _clip_duration_label(duration)
        start_lbl = _clip_duration_label(start) if start is not None else "—"

        lines.append(
            f"{idx}\\. *{title}* {emoji} {score_lbl}分"
        )
        lines.append(
            f"   ⏱ {dur_lbl} | ⏳ 从 {start_lbl} 开始"
        )
        lines.append("")

    if len(clips) > _MAX_CLIPS_NOTIFY:
        lines.append(f"_...还有 {len(clips) - _MAX_CLIPS_NOTIFY} 个切片_")
        lines.append("")

    if shown_colls:
        lines.append("*🎞️ 视频合集*")
        lines.append("")
        for idx, coll in enumerate(shown_colls, 1):
            coll_title = _escape_telegram_markdownv2(coll.get("title") or f"合集 {idx}")
            coll_dur = _clip_duration_label(coll.get("duration"))
            lines.append(f"{idx}\\. *{coll_title}* ⏱ {coll_dur}")
            if coll.get("description"):
                desc = _escape_telegram_markdownv2(coll.get("description"))
                lines.append(f"   _{desc}_")
            lines.append("")

    return {
        "parse_mode": "MarkdownV2",
        "text": "\n".join(lines),
    }


# ── WeCom ─────────────────────────────────────────────────────────────────────

def _build_clip_wecom_textcard(
    video_title: str | None,
    clips: list[dict],
    collections: list[dict],
) -> dict:
    """企业微信 TextCard 格式切片通知"""
    shown = clips[:_MAX_CLIPS_NOTIFY]

    clip_lines: list[str] = []
    for idx, clip in enumerate(shown, 1):
        title = clip.get("title") or f"切片 {idx}"
        score = clip.get("score")
        emoji = _clip_score_emoji(score)
        dur_lbl = _clip_duration_label(clip.get("duration"))
        clip_lines.append(f"{idx}. {title} {emoji} {score}分 ⏱{dur_lbl}")

    clip_summary = "\n".join(clip_lines) if clip_lines else "无切片"

    return {
        "msgtype": "textcard",
        "textcard": {
            "title": f"✂️ AI 切片完成 — {video_title or '未知视频'}",
            "description": (
                f"📺 视频：{video_title or '未知视频'}\n"
                f"🎬 切片：{len(clips)} 个 | 🎞️ 合集：{len(collections)} 个\n"
                f"---\n{clip_summary}"
            ),
            "btntxt": "查看详情",
            "url": "https://github.com",
        },
    }


# ── Public Factory ─────────────────────────────────────────────────────────────

def build_clip_notify_payload(
    platform: Literal["feishu", "dingtalk", "wecom", "telegram"],
    clips: list[dict],
    collections: list[dict],
    video_title: str | None = None,
) -> dict:
    """构建 AI 切片结果通知消息体"""
    if platform == "feishu":
        return _build_clip_feishu_card(video_title, clips, collections)
    if platform == "dingtalk":
        return _build_clip_dingtalk_markdown(video_title, clips, collections)
    if platform == "telegram":
        return _build_clip_telegram_message(video_title, clips, collections)
    if platform == "wecom":
        return _build_clip_wecom_textcard(video_title, clips, collections)
    raise ValueError(f"不支持的平台: {platform}")


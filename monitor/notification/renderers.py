"""
monitor.notification.renderers — High-level card builders and payload factory
"""
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
    else:
        raise ValueError(f"不支持的平台: {platform}")


# ── HTTP Sending Utilities ─────────────────────────────────────────────────────

import requests as _requests
from urllib.parse import urlsplit


def _send_webhook(
    url: str,
    payload: dict,
    platform: "Platform",
    timeout: int = 60,
) -> tuple[bool, str]:
    """通用的 Webhook 发送函数"""
    if not url:
        return False, "未配置 Webhook URL"

    try:
        resp = _requests.post(url, json=payload, timeout=timeout)

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

    except _requests.Timeout:
        return False, "请求超时"
    except Exception as e:
        return False, str(e)


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

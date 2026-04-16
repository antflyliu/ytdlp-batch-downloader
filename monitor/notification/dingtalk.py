"""
monitor.notification.dingtalk — DingTalk builders and webhook URL finalizer
"""
import base64
import hashlib
import hmac
import time
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .base import _format_duration_sec

if TYPE_CHECKING:
    from .base import Platform


def finalize_dingtalk_webhook_url(webhook_url: str, dingtalk_sign_secret: str | None) -> str:
    """
    钉钉自定义机器人加签：在 URL 查询串中附加 timestamp、sign。
    未配置密钥或 URL 为空时返回原 URL（兼容未开启加签的机器人）。
    """
    if not webhook_url or not (dingtalk_sign_secret or "").strip():
        return webhook_url
    secret = dingtalk_sign_secret.strip()
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign_b64 = base64.b64encode(digest).decode("utf-8")
    parts = urlsplit(webhook_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["timestamp"] = timestamp
    query["sign"] = sign_b64
    new_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


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
    钉钉自定义机器人 Markdown 消息（推荐），与飞书/Telegram 消息字段对齐。
    包含：时长、观看数、点赞数、评论数。
    """
    from .base import _format_duration_sec
    items = [f"### 🎬 {account_name} — {len(videos)} 个新视频"]
    items.append(f"**📺 频道**: {channel_url}")
    items.append(f"**⏰ 发送时间**: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    items.append("")
    for v in videos[:10]:
        pub_date = (v.get("published_at") or v.get("upload_date") or "")[:10]
        views = int(v.get("view_count") or 0)
        likes = int(v.get("like_count") or 0)
        comments = int(v.get("comment_count") or 0)
        duration_text = _format_duration_sec(v.get("duration_sec"))
        items.append(
            f"- **[{v.get('title', '')[:40]}]({v.get('url', '')})**"
        )
        stats = f"📅 {pub_date}  ⏱ {duration_text}  👁 {views:,}  👍 {likes:,}  💬 {comments:,}"
        items.append(f"  {stats}")
    if len(videos) > 10:
        items.append(f"\n> ...还有 {len(videos) - 10} 个新视频")
    return {"msgtype": "markdown", "markdown": {"title": f"{account_name}", "text": "\n\n".join(items)}}

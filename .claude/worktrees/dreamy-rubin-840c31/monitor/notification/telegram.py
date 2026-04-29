"""
monitor.notification.telegram — Telegram Bot 消息构建与发送

Telegram Bot API Reference:
https://core.telegram.org/bots/api#sendmessage
https://core.telegram.org/bots/api#markdownv2-style

配置项（与企微/钉钉一致的全局 Webhook 模式）:
  global_telegram_token  — Bot Token，格式: <bot_id>:<token>
  global_telegram_chat_id — 接收消息的 Chat ID（整数或字符串）
"""
from .base import _format_duration_sec


def _escape_telegram_markdownv2(text: str) -> str:
    """
    转义 Telegram MarkdownV2 特殊字符，防止破坏解析。

    需要转义的字符（按官方文档）：
    '_' '*' '[' ']' '(' ')' '~' '`' '>' '#' '+' '-' '=' '|'
    '{' '}' '.' '!'

    注意：'|' 在 v2 中用于分隔样式，不需要转义即可出现在文本中。
    """
    if not text:
        return ""
    for ch in r"\_[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _build_telegram_text(
    account_name: str,
    channel_url: str,
    videos: list[dict],
    channel_name: str | None = None,
) -> dict:
    """
    构建 Telegram 纯文本消息（MarkdownV2 格式），与飞书/钉钉消息字段对齐。

    消息结构：
    🎬 <account_name> — <n> 个新视频

    📺 频道：<channel_name>
    🔗 链接：<channel_url>

    1. <视频标题>
       📅 <pub_date> | ⏱ <duration> | 👁 <views> | 👍 <likes> | 💬 <comments>
       <url>

    ...
    """
    lines: list[str] = []

    # Header
    display_name = channel_name or channel_url
    lines.append(f"🎬 *{_escape_telegram_markdownv2(account_name)}* — *{len(videos)}* 个新视频")
    lines.append("")
    lines.append(f"📺 频道：{_escape_telegram_markdownv2(display_name)}")
    lines.append(f"🔗 链接：{_escape_telegram_markdownv2(channel_url)}")
    lines.append("")

    # Video list
    for idx, v in enumerate(videos[:10], 1):
        title = _escape_telegram_markdownv2((v.get("title") or "").strip())
        pub_date = (v.get("published_at") or v.get("upload_date") or "")[:10]
        views = int(v.get("view_count") or 0)
        likes = int(v.get("like_count") or 0)
        comments = int(v.get("comment_count") or 0)
        duration_text = _format_duration_sec(v.get("duration_sec"))
        url = v.get("url", "")

        lines.append(f"{idx}\\. *{title}*")
        stats = f"📅 {_escape_telegram_markdownv2(pub_date)} \\| ⏱ {_escape_telegram_markdownv2(duration_text)} \\| 👁 {_escape_telegram_markdownv2(f'{views:,}')} \\| 👍 {_escape_telegram_markdownv2(f'{likes:,}')} \\| 💬 {_escape_telegram_markdownv2(f'{comments:,}')}"
        lines.append(f"   {stats}")
        lines.append(f"   {_escape_telegram_markdownv2(url)}")
        lines.append("")

    if len(videos) > 10:
        lines.append(f"\\.\\.\\. 还有 *{len(videos) - 10}* 个新视频未展示")

    return {
        "parse_mode": "MarkdownV2",
        "text": "\n".join(lines),
    }


def _build_telegram_message(
    account_name: str,
    channel_url: str,
    videos: list[dict],
    channel_name: str | None = None,
) -> dict:
    """
    构建 Telegram sendMessage 请求体。

    与企微 TextCard / 钉钉 Markdown 同地位的消息构建函数。
    调用方负责拼装完整请求 URL：
        https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>
    """
    content = _build_telegram_text(account_name, channel_url, videos, channel_name)
    return {
        "chat_id": None,  # 填充 chat_id 是调用方职责
        "text": content["text"],
        "parse_mode": content["parse_mode"],
        "disable_web_page_preview": False,
    }

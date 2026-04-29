"""
monitor.notification.wecom — WeCom builders
"""
from .base import _format_duration_sec


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

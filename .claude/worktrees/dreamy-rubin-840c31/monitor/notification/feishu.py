"""
monitor.notification.feishu — Feishu template builders
"""
from .base import (
    _escape_lark_md,
    _feishu_now_str,
    _format_duration_sec,
    _FEISHU_MAX_ITEMS,
)


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

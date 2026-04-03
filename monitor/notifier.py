"""
monitor.notifier — 多平台通知器
支持：日志文件 / 飞书 / 钉钉 / 企业微信
"""
import logging
from datetime import datetime, timezone
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


# ── 飞书模板专用工具函数 ───────────────────────────────────────────────────

def _feishu_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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


def _format_feishu_video_variable(v: dict) -> dict:
    """将单个视频 dict 格式化为模板变量"""
    pub_date = (v.get("published_at") or v.get("upload_date") or "")[:10]
    views = int(v.get("view_count") or 0)
    likes = int(v.get("like_count") or 0)
    comments = int(v.get("comment_count") or 0)
    title = _escape_lark_md((v.get("title") or "").strip())
    url = v.get("url", "")

    return {
        "title": title,
        "title_link": f"[{title}]({url})" if url else title,
        "video_url": url,
        "published_date": pub_date,
        "view_count_text": f"{views:,}",
        "like_count_text": f"{likes:,}",
        "comment_count_text": f"{comments:,}",
        "stats_line": f"📅 {pub_date}  👁 {views:,}  👍 {likes:,}",
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


# ── 通知平台构建器 ────────────────────────────────────────────────────────

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
        video_items.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{v.get('title', '')}**\n"
                    f"📅 {pub_date}  👁 {views:,}  👍 {likes:,}\n"
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
                            f"**时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
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
    lines.append(f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
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
    items.append(f"**⏰ 时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
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
                f"飞书已配置 template 模式，但未提供 feishu_template_id，自动回退到硬编码卡片"
            )
        return _build_feishu_card(account_name, channel_url, videos)
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


# ── 统一通知入口 ───────────────────────────────────────────────────────────

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
        # 没有 scan 模板时，使用硬编码确认卡片
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"✅ {account_name} — 扫描完成"},
                    "template": "green" if new_videos > 0 else "blue",
                },
                "elements": [{
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**频道**: {channel_url}\n"
                            f"**API 返回**: {total_videos} 个视频\n"
                            f"**新增视频**: {new_videos} 个\n"
                            f"**状态**: 扫描正常，无新视频\n"
                            f"**时间**: {_feishu_now_str()}"
                        ),
                    },
                }],
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
    即使无新视频也会发送确认通知（验证 Webhook 可达性）

    :param total_videos: API 返回的总视频数
    :param feishu_message_mode: 飞书发送模式，card_json（默认）或 template
    :param feishu_template_id: 飞书详情卡片模板ID（template 模式用）
    :param feishu_scan_template_id: 飞书扫描确认模板ID（template 模式用）
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 1. 文件日志 ──────────────────────────────────────
    if videos:
        msg = _file_log(account_name, channel_url, videos, duration_ms)
        _log.info(msg)
        if log_dir and _file_handler:
            logging.getLogger("monitor.notifier").info(msg)

    # ── 2. Webhook ──────────────────────────────────────
    if not webhook_url:
        _log.info(f"未配置 Webhook（{platform}），跳过推送: {account_name}")
        return

    if videos:
        # 有新视频：发送详情卡片（支持 template 模式）
        payload = build_notify_payload(
            platform, account_name, channel_url, videos,
            channel_name=channel_name,
            feishu_message_mode=feishu_message_mode,
            feishu_template_id=feishu_template_id,
        )
        success, response = _send_webhook(webhook_url, payload, platform)
        _log_result(platform, account_name, len(videos), success, response, event_id, account_id, now_str, webhook_url)
        if success:
            video_ids = [v["video_id"] for v in videos]
            _db.mark_notify_sent(video_ids, now_str)
    else:
        # 无新视频：发送扫描完成确认（验证 Webhook 可达，支持 template 模式）
        payload = _build_scan_confirm_payload(
            platform, account_name, channel_url, total_videos, 0,
            channel_name=channel_name,
            feishu_message_mode=feishu_message_mode,
            feishu_scan_template_id=feishu_scan_template_id,
        )
        success, response = _send_webhook(webhook_url, payload, platform)
        _log_result(platform, account_name, 0, success, response, event_id, account_id, now_str, webhook_url)


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
    with _db.get_connection() as conn:
        conn.execute(
            """INSERT INTO monitor_notify_logs
               (event_id, account_id, account_name, video_count, platform, webhook_url,
                http_status, response_text, sent_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (event_id, account_id, account_name, video_count, platform, webhook_url,
             http_status, resp_text, now_str),
        )

"""
monitor.notifier — 多平台通知器
支持：日志文件 / 飞书 / 钉钉 / 企业微信

⚠️ 兼容垫片：所有 builder 函数已移至 monitor/notification/ 子包。
本文件从 monitor.notification 重新导出公开接口，保持向后兼容。
新代码应直接导入 monitor.notification。
"""
import logging
from typing import Literal

import logging_config
import monitor.db as _db
from monitor import notification
from monitor.notification import (
    _file_handler,
    _file_log,
    _log_result,
    _redact_webhook_url,
    _send_webhook,
)

_log = logging_config.get_logger("monitor.notifier")

# ── Re-export public types & constants ─────────────────────────────────────────

Platform = Literal["feishu", "dingtalk", "wecom"]
FEISHU_MODE_CARD = notification.FEISHU_MODE_CARD
FEISHU_MODE_TEMPLATE = notification.FEISHU_MODE_TEMPLATE

# Public builders
build_notify_payload = notification.build_notify_payload
finalize_dingtalk_webhook_url = notification.finalize_dingtalk_webhook_url

# File logging
setup_file_logging = notification.setup_file_logging


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
    dingtalk_sign_secret: str | None = None,
) -> None:
    """
    统一通知入口：文件日志 + 指定平台 Webhook
    仅在有新视频时由 scheduler 调用，无新视频不推送消息。

    :param total_videos: API 返回的总视频数
    :param feishu_message_mode: 飞书发送模式，card_json（默认）或 template
    :param feishu_template_id: 飞书详情卡片模板ID（template 模式用）
    :param feishu_scan_template_id: 飞书扫描确认模板ID（template 模式用）
    :param dingtalk_sign_secret: 钉钉机器人加签密钥（SEC…），按账户配置；仅 platform=dingtalk 时生效
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
    send_url = (
        finalize_dingtalk_webhook_url(webhook_url, dingtalk_sign_secret)
        if platform == "dingtalk"
        else webhook_url
    )
    success, response = _send_webhook(send_url, payload, platform)
    _log_result(platform, account_name, len(videos), success, response, event_id, account_id, now_str, send_url)
    if success:
        _log.info(f"[ok] {platform} 通知发送成功: {account_name} → {response[:120]}")
        video_ids = [v["video_id"] for v in videos]
        _db.mark_notify_sent(video_ids, now_str)
    else:
        _log.error(f"[fail] {platform} 通知发送失败: {account_name} → {response[:200]}")

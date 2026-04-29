#!/usr/bin/env python3
"""
scripts/clip_notifier.py — AI 切片结果通知

将 Pipeline 切片结果通过 Webhook 推送到飞书/钉钉/企业微信/Telegram。

用法（作为模块调用）:
    from scripts.clip_notifier import notify_pipeline_result
    ctx = run_pipeline(...)
    notify_pipeline_result(ctx)

CLI 单独调用:
    python scripts/clip_notifier.py --clips output/clips/clips_metadata.json --notify feishu

依赖:
    monitor.notification.renderers.build_clip_notify_payload
    config.settings.load_config
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Literal, Optional

# ── Project root for imports ───────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from monitor.notification.renderers import (
    build_clip_notify_payload,
    finalize_dingtalk_webhook_url,
    _send_webhook as _send_webhook_raw,
    _redact_webhook_url,
)
from monitor.notification.base import Platform

import logging_config

_log = logging_config.get_logger("clip_notifier")

# ── Retry intervals for notification webhook ───────────────────────────────────

_RETRY_INTERVALS = (5, 10, 15)
_WEBHOOK_TIMEOUT = 60


# ── Public API ─────────────────────────────────────────────────────────────────

def notify_pipeline_result(
    ctx,
    platform: Platform | None = None,
    webhook_url: str | None = None,
    dingtalk_sign_secret: str | None = None,
    telegram_chat_id: str | None = None,
    video_title: str | None = None,
) -> dict[str, bool]:
    """
    发送 Pipeline 切片结果通知。

    Args:
        ctx:                  PipelineContext 实例（含 generated_clips / generated_collections）
        platform:            通知平台（feishu/dingtalk/wecom/telegram），None 时自动从配置读取
        webhook_url:         Webhook URL，None 时从全局配置读取
        dingtalk_sign_secret: 钉钉加签密钥（仅 dingtalk 平台用）
        telegram_chat_id:    Telegram Chat ID（仅 telegram 平台用）
        video_title:         原始视频标题（用于摘要展示）

    Returns:
        {"<platform>": (success: bool, message: str), ...}
    """
    clips = ctx.generated_clips if hasattr(ctx, "generated_clips") else []
    collections = ctx.generated_collections if hasattr(ctx, "generated_collections") else []

    if not clips and not collections:
        _log.info("无切片结果，跳过通知")
        return {}

    success_map: dict[str, tuple[bool, str]] = {}

    # 自动从全局配置读取平台和 URL
    if platform is None or webhook_url is None:
        cfg = _load_config_safe()
        if platform is None:
            platform = _detect_platform_from_config(cfg)
        if webhook_url is None:
            webhook_url = _get_webhook_url_from_config(cfg, platform)
        if dingtalk_sign_secret is None:
            dingtalk_sign_secret = cfg.get("global_dingtalk_sign_secret") or ""
        if telegram_chat_id is None:
            telegram_chat_id = cfg.get("global_telegram_chat_id") or ""

    if not platform or not webhook_url:
        _log.warning("未配置通知平台或 Webhook URL，跳过通知")
        return {}

    payload = build_clip_notify_payload(
        platform,
        clips,
        collections,
        video_title=video_title,
    )

    send_url = webhook_url
    if platform == "dingtalk" and dingtalk_sign_secret:
        send_url = finalize_dingtalk_webhook_url(webhook_url, dingtalk_sign_secret)

    redacted = _redact_webhook_url(webhook_url)
    _log.info(
        f"发送 AI 切片通知: platform={platform} clips={len(clips)} "
        f"collections={len(collections)} webhook={redacted}"
    )

    ok, err = _send_webhook_raw(
        send_url,
        payload,
        platform,
        timeout=_WEBHOOK_TIMEOUT,
        retry_intervals=_RETRY_INTERVALS,
        telegram_chat_id=telegram_chat_id if platform == "telegram" else None,
    )

    if ok:
        _log.info(f"AI 切片通知发送成功: {platform}")
        success_map[platform] = (True, "发送成功")
    else:
        _log.error(f"AI 切片通知发送失败: {platform} — {err}")
        success_map[platform] = (False, err)

    return success_map


def notify_from_json(
    metadata_path: str | Path,
    platform: Platform | None = None,
    webhook_url: str | None = None,
    video_title: str | None = None,
) -> dict[str, bool]:
    """
    从 JSON 文件读取切片元数据并发送通知。

    适用于 CLI 单独调用：
        python scripts/clip_notifier.py --clips output/clips/clips_metadata.json --notify feishu
    """
    path = Path(metadata_path)
    if not path.exists():
        raise FileNotFoundError(f"切片元数据文件不存在: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    clips = data.get("clips", [])
    collections = data.get("collections", [])

    # 构造一个轻量上下文对象
    class _Ctx:
        def __init__(self, c, colls):
            self.generated_clips = c
            self.generated_collections = colls

    ctx = _Ctx(clips, collections)
    return notify_pipeline_result(ctx, platform=platform, webhook_url=webhook_url, video_title=video_title)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_config_safe() -> dict:
    """安全加载配置（出错时返回空字典）"""
    try:
        from config.settings import load_config
        return load_config()
    except Exception as e:
        _log.warning(f"加载配置失败: {e}")
        return {}


def _detect_platform_from_config(cfg: dict) -> Literal["feishu", "dingtalk", "wecom", "telegram"] | None:
    """根据全局配置判断使用哪个通知平台（优先非空 Webhook URL）"""
    if cfg.get("global_feishu_url"):
        return "feishu"
    if cfg.get("global_dingtalk_url"):
        return "dingtalk"
    if cfg.get("global_wecom_url"):
        return "wecom"
    if cfg.get("global_telegram_token"):
        return "telegram"
    return None


def _get_webhook_url_from_config(
    cfg: dict,
    platform: Platform | None,
) -> str | None:
    if platform == "feishu":
        return cfg.get("global_feishu_url") or None
    if platform == "dingtalk":
        return cfg.get("global_dingtalk_url") or None
    if platform == "wecom":
        return cfg.get("global_wecom_url") or None
    if platform == "telegram":
        return cfg.get("global_telegram_token") or None
    return None


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AI 切片结果通知发送工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/clip_notifier.py --clips output/clips/clips_metadata.json --notify feishu
  python scripts/clip_notifier.py --clips output/clips/clips_metadata.json --notify dingtalk \\
      --webhook https://oapi.dingtalk.com/robot/send?access_token=xxx
        """,
    )
    parser.add_argument(
        "--clips", required=True,
        help="切片元数据 JSON 文件路径（通常是 clips_metadata.json）"
    )
    parser.add_argument(
        "--notify", choices=["feishu", "dingtalk", "wecom", "telegram"],
        help="通知平台，不指定则自动从全局配置读取"
    )
    parser.add_argument(
        "--webhook",
        help="Webhook URL（不指定则从全局配置读取）"
    )
    parser.add_argument(
        "--video-title",
        help="原始视频标题（用于通知摘要）"
    )
    args = parser.parse_args()

    platform: Platform | None = args.notify
    webhook_url = args.webhook

    result = notify_from_json(
        args.clips,
        platform=platform,
        webhook_url=webhook_url,
        video_title=args.video_title,
    )

    if not result:
        print("未发送任何通知（无切片结果或未配置平台）")
        sys.exit(1)

    for plat, (ok, msg) in result.items():
        status = "✅ 成功" if ok else "❌ 失败"
        print(f"{status} [{plat}] {msg}")

    sys.exit(0 if all(ok for ok, _ in result.values()) else 1)


if __name__ == "__main__":
    main()

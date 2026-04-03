"""
monitor.scheduler — APScheduler 后台调度器
在独立线程中运行，负责按配置间隔扫描各账户
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import apscheduler.schedulers.background
import apscheduler.triggers.interval

import logging_config
import monitor.db as _db
import monitor.detector as _detector
import monitor.fetcher as _fetcher
import monitor.notifier as _notifier
import monitor.quota as _quota

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler

_log = logging_config.get_logger("monitor.scheduler")

# 平台级全局 Webhook URL
_GLOBAL_WEBHOOKS: dict[str, str | None] = {}
_GLOBAL_WEBHOOKS_LOADED = False


def _ensure_global_webhooks() -> None:
    """确保全局 Webhook 已加载（模块加载时 + 每次扫描前）"""
    global _GLOBAL_WEBHOOKS, _GLOBAL_WEBHOOKS_LOADED
    if _GLOBAL_WEBHOOKS_LOADED:
        return
    try:
        config_path = _db.get_config_path()
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            _GLOBAL_WEBHOOKS["feishu"]    = cfg.get("global_feishu_url") or None
            _GLOBAL_WEBHOOKS["dingtalk"] = cfg.get("global_dingtalk_url") or None
            _GLOBAL_WEBHOOKS["wecom"]   = cfg.get("global_wecom_url") or None
    except Exception:
        pass
    _GLOBAL_WEBHOOKS_LOADED = True

# PyInstaller 兼容路径
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = os.path.dirname(os.path.dirname(_PKG_DIR))

# 日志目录（exe 同级 logs/）
_LOG_DIR = os.path.join(_EXE_DIR, "logs")


# 已发送过的 quota 报警（key = f"{api_key}:{threshold}"，避免重复发送）
_quota_alerted: set[str] = set()


def _send_quota_alert(account: dict, api_key: str, usage: dict, budget: int) -> None:
    """发送 quota 预警/耗尽报警（优先账户级 Webhook，其次全局）"""
    platform = account.get("notify_platform", "feishu")
    webhook_url = (
        account.get("webhook_url")
        or _GLOBAL_WEBHOOKS.get(platform)
        or _GLOBAL_WEBHOOKS.get("feishu")
    )
    if not webhook_url:
        _log.warning(f"quota 报警无 Webhook URL，跳过: {account['name']}")
        return
    _quota.send_alert(api_key, usage, budget, webhook_url)


def _check_quota_alert(account: dict, api_key: str, budget: int) -> None:
    """检查是否需要发送 quota 预警（80%/90%/100%）"""
    _, usage = _quota.check_budget(api_key, budget)
    used = usage["api_calls"]
    for threshold in (80, 90, 100):
        alert_key = f"{api_key}:{threshold}"
        if alert_key in _quota_alerted:
            continue
        if threshold == 100:
            should_alert = used >= budget
        else:
            should_alert = used >= int(budget * threshold / 100)
        if should_alert:
            _quota_alerted.add(alert_key)
            _send_quota_alert(account, api_key, usage, budget)
            _log.warning(f"quota 预警已发送: {threshold}% ({used}/{budget}) — {account['name']}")
            break

def set_global_feishu_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["feishu"] = url
    _log.info(f"全局飞书 Webhook 已更新: {'已设置' if url else '未设置'}")

def set_global_dingtalk_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["dingtalk"] = url
    _log.info(f"全局钉钉 Webhook 已更新: {'已设置' if url else '未设置'}")

def set_global_wecom_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["wecom"] = url
    _log.info(f"全局企微 Webhook 已更新: {'已设置' if url else '未设置'}")


# 共享调度器实例
_scheduler: "BackgroundScheduler | None" = None
_scheduler_lock = threading.Lock()


def _scan_account(account_id: int) -> None:
    """
    执行单个账户的扫描任务
    在 APScheduler 的线程池中执行
    """
    start_time = time.perf_counter()

    # 确保全局 Webhook 配置已加载（无论从 UI 还是调度器触发）
    _ensure_global_webhooks()

    account = _db.get_account(account_id)
    if not account:
        _log.error(f"账户不存在: id={account_id}")
        return

    if not account["enabled"]:
        _log.info(f"账户已禁用，跳过: {account['name']} ({account['channel_url']})")
        return

    # 读取 API Key
    api_key = os.environ.get(account["api_key_env"], "")
    if not api_key:
        _log.error(f"环境变量未设置: {account['api_key_env']} (账户={account['name']})")
        _db.finish_event(
            event_id=0, status="error",
            total_videos=0, new_videos=0,
            error_message=f"环境变量未设置: {account['api_key_env']}",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        return

    # ── Quota 预算检查 ─────────────────────────────────────────
    budget = _quota.get_budget_limit(account["api_key_env"])
    allowed, usage = _quota.check_budget(api_key, budget)
    if not allowed:
        _log.warning(
            f"Quota 已达上限（{usage['api_calls']}/{budget}），跳过扫描: {account['name']}"
        )
        _quota.incr_blocked(api_key)
        _db.finish_event(
            event_id=0, status="quota_exceeded",
            total_videos=0, new_videos=0,
            error_message=f"Quota 已达上限: {usage['api_calls']}/{budget}",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        # 发送 quota 耗尽报警
        _send_quota_alert(account, api_key, usage, budget)
        return

    event_id = _db.create_event(account_id, account["name"])
    _log.info(
        f"扫描开始: 账户={account['name']} 模式={account['fetch_mode']} "
        f"限制={account['fetch_limit']} event_id={event_id}"
    )

    try:
        # ── 1. 获取视频 ────────────────────────────────────
        fetcher = _fetcher.YouTubeFetcher(
            api_key=api_key,
            fetch_mode=account["fetch_mode"],
            fetch_limit=account["fetch_limit"],
            view_threshold=0,
        )
        videos, channel_info = fetcher.fetch(account["channel_url"])

        if not videos:
            _db.finish_event(event_id, "success", 0, 0, duration_ms=int((time.perf_counter() - start_time) * 1000))
            _log.info(f"扫描完成（无视频）: {account['name']}")
            _check_quota_alert(account, api_key, budget)
            _quota.incr(api_key, scans=1)
            return

        # ── 2. 检测新视频 ──────────────────────────────────
        new_videos = _detector.detect_new(videos)

        # ── 3. 写入数据库 ──────────────────────────────────
        if new_videos:
            inserted = _db.insert_videos(new_videos, account_id, event_id)
            _log.info(f"写入数据库: {account['name']} 新增={inserted} 总获取={len(videos)}")
        else:
            inserted = 0
            _log.info(f"无新视频: {account['name']} (API返回={len(videos)})")

        _db.finish_event(
            event_id,
            status="success",
            total_videos=len(videos),
            new_videos=inserted,
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )

        # ── 4. 发送通知 ────────────────────────────────────
        _ensure_global_webhooks()
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        if account["notify_enabled"]:
            # 优先用账户级 Webhook，其次全局 Webhook
            webhook_url = account.get("webhook_url") or _GLOBAL_WEBHOOKS.get(account.get("notify_platform", "feishu"))
            channel_name = (channel_info or {}).get("channel_name") or account["name"]
            _notifier.notify(
                event_id=event_id,
                account_id=account_id,
                account_name=account["name"],
                channel_url=account["channel_url"],
                videos=new_videos,
                platform=account.get("notify_platform", "feishu"),
                webhook_url=webhook_url,
                duration_ms=duration_ms,
                total_videos=len(videos),
                log_dir=_LOG_DIR,
                channel_name=channel_name,
                feishu_message_mode=account.get("feishu_message_mode", "card_json"),
                feishu_template_id=account.get("feishu_template_id"),
                feishu_scan_template_id=account.get("feishu_scan_template_id"),
            )

        _log.info(
            f"扫描完成: 账户={account['name']} "
            f"API返回={len(videos)} 新增={inserted} 耗时={duration_ms}ms"
        )

        # ── 5. Quota 预警检查 ────────────────────────────────
        _check_quota_alert(account, api_key, budget)
        # 更新扫描次数统计
        _quota.incr(api_key, scans=1)

    except Exception as e:
        _log.error(f"扫描异常: 账户={account['name']} — {e}")
        _db.finish_event(
            event_id,
            status="error",
            total_videos=0, new_videos=0,
            error_message=str(e),
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )


def start() -> bool:
    """
    启动调度器
    """
    global _scheduler

    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            _log.warning("调度器已在运行中")
            return False

        # 初始化日志
        _notifier.setup_file_logging(_LOG_DIR)

        # 读取全局配置（从 db 模块的兼容路径）
        config_path = _db.get_config_path()
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 加载各平台全局 Webhook
            _GLOBAL_WEBHOOKS["feishu"]    = cfg.get("global_feishu_url")
            _GLOBAL_WEBHOOKS["dingtalk"] = cfg.get("global_dingtalk_url")
            _GLOBAL_WEBHOOKS["wecom"]   = cfg.get("global_wecom_url")
            _log.info(f"全局 Webhook 已加载: 飞书={bool(_GLOBAL_WEBHOOKS['feishu'])} "
                      f"钉钉={bool(_GLOBAL_WEBHOOKS['dingtalk'])} "
                      f"企微={bool(_GLOBAL_WEBHOOKS['wecom'])}")

        # 初始化数据库
        _db.init_db()
        _db.ensure_app_state_table()

        _scheduler = apscheduler.schedulers.background.BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={
                "coalesce": True,       # 合并错失的执行为一次
                "max_instances": 1,     # 同一账户同时最多一个任务
                "misfire_grace_time": 60,
            },
        )

        # 加载账户并注册任务
        accounts = _db.list_accounts(enabled_only=True)
        if not accounts:
            _log.warning("没有已启用的监控账户，调度器将以空配置启动")

        for acc in accounts:
            _scheduler.add_job(
                func=_scan_account,
                trigger=apscheduler.triggers.interval.IntervalTrigger(
                    minutes=acc["scan_interval"],
                    start_date=datetime.now(timezone.utc),
                ),
                args=[acc["id"]],
                id=f"account_{acc['id']}",
                name=f"{acc['name']} ({acc['channel_url']})",
                replace_existing=True,
            )
            _log.info(
                f"注册任务: {acc['name']} 间隔={acc['scan_interval']}分钟 "
                f"模式={acc['fetch_mode']} 限制={acc['fetch_limit']}"
            )

        _scheduler.start()

        # 持久化运行状态
        _db.set_scheduler_state({
            "running": True,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

        _log.info(f"调度器已启动，共注册 {len(accounts)} 个任务")
        return True


def stop() -> bool:
    """
    停止调度器
    """
    global _scheduler

    with _scheduler_lock:
        if not _scheduler or not _scheduler.running:
            _log.warning("调度器未运行")
            return False

        _scheduler.shutdown(wait=True)
        _db.set_scheduler_state({"running": False, "stopped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        _log.info("调度器已停止")
        return True


def reload_jobs() -> int:
    """
    重新加载所有账户任务（添加新账户 / 更新间隔 / 删除失效账户）
    返回注册的任务数量
    """
    if not _scheduler or not _scheduler.running:
        _log.warning("调度器未运行，无法重载")
        return 0

    accounts = _db.list_accounts(enabled_only=True)
    current_job_ids = {_j.id for _j in _scheduler.get_jobs()}
    target_job_ids = {f"account_{acc['id']}" for acc in accounts}

    # 移除已删除的账户
    for job_id in current_job_ids - target_job_ids:
        _scheduler.remove_job(job_id)
        _log.info(f"移除失效任务: {job_id}")

    # 添加/更新账户
    for acc in accounts:
        job_id = f"account_{acc['id']}"
        job_kwargs = {
            "func": _scan_account,
            "trigger": apscheduler.triggers.interval.IntervalTrigger(
                minutes=acc["scan_interval"],
                start_date=datetime.now(timezone.utc),
            ),
            "args": [acc["id"]],
            "name": f"{acc['name']} ({acc['channel_url']})",
            "replace_existing": True,
        }
        if job_id in current_job_ids:
            # 更新已有任务的间隔（先移除再添加以更新 trigger）
            _scheduler.reschedule_job(job_id, **job_kwargs)
        else:
            _scheduler.add_job(**job_kwargs)
        _log.info(f"{'更新' if job_id in current_job_ids else '添加'}任务: {acc['name']} @ {acc['scan_interval']}min")

    active_count = len(_scheduler.get_jobs())
    _log.info(f"任务重载完成，当前活跃: {active_count}")
    return active_count


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def get_next_run_times(limit: int = 20) -> list[dict]:
    """返回所有任务的下次执行时间"""
    if not _scheduler or not _scheduler.running:
        return []
    jobs = _scheduler.get_jobs()
    return [
        {
            "id": j.id,
            "name": j.name,
            "next_run": j.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if j.next_run_time else None,
        }
        for j in jobs
    ]

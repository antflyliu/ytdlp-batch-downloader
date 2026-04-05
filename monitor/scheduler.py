"""
monitor.scheduler — APScheduler 后台调度器
在独立线程中运行，负责按配置间隔扫描各账户
"""
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING

import apscheduler.schedulers.background
import apscheduler.triggers.interval

import logging_config
import monitor.db as _db
import monitor.detector as _detector
import monitor.fetcher as _fetcher
import monitor.notifier as _notifier
import monitor.quota as _quota
from concurrent.futures import ThreadPoolExecutor
from Youtube_Downloader import batch_download, build_aria2_opts

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

# PyInstaller 兼容路径（统一基于 __file__ 推导，确保源码/打包模式一致）
#   源码：__file__ = monitor/scheduler.py → _PKG_DIR = monitor/ → _EXE_DIR = 项目根/
#   打包（onedir）：sys._MEIPASS = exe所在目录/ + 打包资源 → _PKG_DIR = exe所在目录/Monitor → _EXE_DIR = exe所在目录
#   打包（onefile）：sys._MEIPASS = _MEIPASS temp dir → _PKG_DIR = temp/Monitor → _EXE_DIR = temp（错误！）
#   → 解决方案：_EXE_DIR 在打包模式用 sys.executable 的父目录，但 videos/ 路径应始终基于项目根目录
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = os.path.dirname(_PKG_DIR)

# 项目根目录（用于下载等应始终指向项目源码根的路径，不依赖 sys.executable）
_MONITOR_ROOT = _PKG_DIR  # = monitor/

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


def _resolve_api_key(account: dict) -> tuple[str | None, dict | None, int]:
    """
    解析账户使用的 API Key。
    返回 (api_key_value, api_key_record, budget)。

    优先级：账户 api_key_id → 系统 default_api_key_id → 账户 api_key_env 环境变量（兼容）
    """
    cfg = _db.load_config()
    api_key = None
    api_key_record = None
    budget = cfg.get("quota_budget_per_day", 8000)

    # 1. 账户指定了 api_key_id
    if account.get("api_key_id"):
        ak = _db.get_api_key(account["api_key_id"])
        if ak and ak.get("is_active"):
            api_key = ak["key_value"]
            api_key_record = ak
            budget = ak.get("daily_quota", budget)
        elif ak:
            _log.warning(f"账户 {account['name']} 的 API Key [{ak['name']}] 已禁用，使用兜底方案")
        else:
            _log.warning(f"账户 {account['name']} 的 API Key ID={account['api_key_id']} 不存在，使用兜底方案")

    # 2. 兜底：系统默认 API Key
    if not api_key:
        default_id = cfg.get("default_api_key_id")
        if default_id:
            ak = _db.get_api_key(default_id)
            if ak and ak.get("is_active"):
                api_key = ak["key_value"]
                api_key_record = ak
                budget = ak.get("daily_quota", budget)
                _log.info(f"使用系统默认 API Key: {ak['name']}")

    # 3. 兜底：旧环境变量方式（兼容）
    if not api_key:
        api_key = os.environ.get(account["api_key_env"], "")
        if api_key:
            _log.info(f"使用环境变量兜底: {account['api_key_env']}")

    return api_key, api_key_record, budget


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

# 稳妥配置：2 线程池 × 2 分片 = 4 并发（安全不触发 YouTube 429）
_auto_dl_pool = ThreadPoolExecutor(max_workers=2)

# 调度器运行期间的自动下载开关（由 start() 设置，stop() 重置）
_auto_download_on_scan: bool = False


def _auto_download_videos(video_records: list[dict]) -> None:
    """
    后台线程池执行：并发下载新视频（max_workers=2，每视频 2 分片）
    避免触发 YouTube 429 限流。

    字幕：始终不下载字幕（no_subs=True），不触发 WhisperX，专注快速下载视频。
    """
    if not video_records:
        return

    urls = [r["url"] for r in video_records if r.get("url")]
    if not urls:
        return

    cfg = _db.load_config()
    output_path = cfg.get("download_output_path", "").strip()
    if not output_path:
        # 兜底：始终基于 monitor/ 的父目录（项目根），不受 sys.executable 位置影响
        output_path = os.path.join(_MONITOR_ROOT, "..", "videos")
        output_path = os.path.normpath(output_path)
    os.makedirs(output_path, exist_ok=True)

    cookies_file = cfg.get("download_cookies_file", "") or None
    enable_aria2 = bool(cfg.get("enable_aria2", False))
    extra_ydl_opts = build_aria2_opts() if enable_aria2 else None

    BATCH_SIZE = 2
    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i:i + BATCH_SIZE]
        chunk_records = video_records[i:i + BATCH_SIZE]
        chunk_ids = [r["id"] for r in chunk_records]

        _log.info(
            f"自动下载批次 {i // BATCH_SIZE + 1}: "
            f"{len(chunk)} 个视频 (第 {i + 1}~{i + len(chunk)} 个，共 {len(urls)} 个)"
            f"{' [aria2]' if enable_aria2 else ''}"
        )

        def _dl_batch(batch_urls, batch_ids):
            try:
                _db.update_videos_download_status(batch_ids, "downloading")
                results = batch_download(
                    batch_urls,
                    output_path,
                    "best",
                    cookies_file=cookies_file,
                    concurrent_fragments=2,
                    no_subs=True,  # 自动下载不下载字幕，避免触发 WhisperX CPU 推理
                    extra_ydl_opts=extra_ydl_opts,
                )

                success_ids = []
                failed_ids = []
                for idx, r in enumerate(results):
                    vid = batch_ids[idx] if idx < len(batch_ids) else None
                    if not vid:
                        continue
                    if r.get("状态") == "成功":
                        success_ids.append(vid)
                    else:
                        failed_ids.append(vid)

                now_str = _db.now_iso()
                if success_ids:
                    _db.update_videos_download_status(
                        success_ids, "downloaded",
                        download_at=now_str,
                        download_path=output_path,
                    )
                if failed_ids:
                    _db.update_videos_download_status(
                        failed_ids, "failed",
                        download_error="auto download failed",
                    )

                _log.info(
                    f"批次下载完成: 成功={len(success_ids)} 失败={len(failed_ids)}"
                )
            except Exception as exc:
                _log.error("自动下载批次异常", exc_info=True)
                _db.update_videos_download_status(
                    batch_ids, "failed",
                    download_error=f"自动下载失败: {type(exc).__name__}",
                )

        _auto_dl_pool.submit(_dl_batch, chunk, chunk_ids)

    _log.info(f"自动下载任务已全部提交: {len(urls)} 个视频")


def trigger_scan(account_id: int, auto_download: bool = False) -> None:
    """
    公开方法：触发指定账户的手动扫描。
    替代直接调用 _scan_account()，提供稳定的公开接口。
    """
    _scan_account(account_id, auto_download=auto_download)


def _scan_account(account_id: int, auto_download: bool = False) -> None:
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

    # 解析 API Key（优先级：账户指定 → 系统默认 → 环境变量兼容）
    api_key, api_key_record, budget = _resolve_api_key(account)
    if not api_key:
        _log.error(f"无法解析 API Key (账户={account['name']})")
        _db.finish_event(
            event_id=0, status="error",
            total_videos=0, new_videos=0,
            error_message="无法解析 API Key，请检查 API Key 配置",
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        return

    # ── Quota 预算检查 ─────────────────────────────────────────
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
            _db.incr_api_key_quota(api_key, scans=1)
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

        # ── 4. 发送通知（仅当有新视频时才发送，避免每次扫描都推送消息） ──
        _ensure_global_webhooks()
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        _log.info(
            f"通知决策: notify_enabled={account['notify_enabled']} "
            f"new_videos={len(new_videos) if new_videos else 0} "
            f"platform={account.get('notify_platform','feishu')} "
            f"feishu_mode={account.get('feishu_message_mode','card_json')} "
            f"account_webhook={bool(account.get('webhook_url'))} "
            f"global_webhook={bool(_GLOBAL_WEBHOOKS.get(account.get('notify_platform','feishu')))}"
        )
        if account["notify_enabled"] and new_videos:
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
        elif account["notify_enabled"] and not new_videos:
            _log.info(f"无新视频，跳过通知推送: {account['name']}")

        _log.info(
            f"扫描完成: 账户={account['name']} "
            f"API返回={len(videos)} 新增={inserted} 耗时={duration_ms}ms"
        )

        # ── 新增：自动下载新视频 ───────────────────────────────
        # 显式参数（立即扫描）或全局开关（定时扫描）均可触发
        effective_auto_dl = auto_download or _auto_download_on_scan
        if effective_auto_dl and inserted > 0:
            with _db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, url FROM monitor_videos WHERE event_id = ?",
                    (event_id,),
                ).fetchall()
            new_video_records = [dict(r) for r in rows]

            threading.Thread(
                target=_auto_download_videos,
                args=(new_video_records,),
                daemon=True,
                name=f"auto-dl-{event_id}",
            ).start()
            _log.info(f"自动下载已触发: {inserted} 个新视频")

        # ── 5. Quota 预警检查 ────────────────────────────────
        _check_quota_alert(account, api_key, budget)
        # 更新扫描次数统计
        _db.incr_api_key_quota(api_key, scans=1)

    except Exception as e:
        _log.error(f"扫描异常: 账户={account['name']} — {e}")
        _db.finish_event(
            event_id,
            status="error",
            total_videos=0, new_videos=0,
            error_message=str(e),
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )


def start(auto_download: bool = False) -> bool:
    """
    启动调度器
    auto_download: 启动后每次扫描到新视频是否自动下载（当前扫描有效，非全局持久化）
    """
    global _scheduler, _auto_download_on_scan

    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            _log.warning("调度器已在运行中")
            return False

        _auto_download_on_scan = auto_download

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
                    start_date=datetime.now().astimezone(),
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
            "started_at": _db.now_iso(),
        })

        _log.info(
            f"调度器已启动，共注册 {len(accounts)} 个任务"
            f"{'（自动下载已开启）' if auto_download else ''}"
        )
        return True


def stop() -> bool:
    """
    停止调度器
    """
    global _scheduler, _auto_download_on_scan

    with _scheduler_lock:
        if not _scheduler or not _scheduler.running:
            _log.warning("调度器未运行")
            return False

        _auto_download_on_scan = False
        _scheduler.shutdown(wait=True)
        _db.set_scheduler_state({"running": False, "stopped_at": _db.now_iso()})
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
                start_date=datetime.now().astimezone(),
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

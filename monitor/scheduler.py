"""
monitor.scheduler — APScheduler 后台调度器
在独立线程中运行，负责按配置间隔扫描各账户
"""
import os
import random
import threading
import json
import time
from datetime import datetime
from typing import TYPE_CHECKING

import apscheduler.schedulers.background
import apscheduler.triggers.interval

import logging_config
import monitor.db as _db
from monitor.video_paths import resolve_downloaded_video_path
import monitor.detector as _detector
import monitor.fetcher as _fetcher
import monitor.notifier as _notifier
import monitor.quota as _quota
from concurrent.futures import ThreadPoolExecutor
from Youtube_Downloader import batch_download, build_aria2_opts
from utils.paths import get_pkg_dir, get_exe_dir, get_log_dir

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler

_log = logging_config.get_logger("monitor.scheduler")

# ── 下载退避状态（线程安全）────────────────────────────────────────────
import random as _random

_proxy_cooldown_until: dict[str, float] = {}   # proxy_url → 退避截止时间（monotonic）
_proxy_retry_count: dict[str, int] = {}        # proxy_url → 当前重试次数
_proxy_lock = threading.Lock()                  # 保护 proxy 退避字典

_direct_cooldown_until: float | None = None    # 全局直连退避截止时间
_direct_retry_count: int = 0
_direct_lock = threading.Lock()                # 保护直连退避字典


def _get_backoff_seconds(retry_count: int) -> float:
    """退避时间 = min(60 * retry_count, 180) + jitter(0~10)"""
    return min(60 * retry_count, 180) + _random.uniform(0, 10)


def _wait_for_proxy_cooldown(proxy: str) -> bool:
    """等待 proxy 退避结束。返回 True 表示已退出等待（退避完成）。"""
    with _proxy_lock:
        deadline = _proxy_cooldown_until.get(proxy)
    if deadline is None:
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return True
    time.sleep(remaining)
    return True


def _set_proxy_cooldown(proxy: str, retry_count: int) -> None:
    """设置 proxy 退避状态（线程安全）"""
    with _proxy_lock:
        now = time.monotonic()
        # 清理已过期的 proxy key，防止字典无限膨胀
        expired = [k for k, v in _proxy_cooldown_until.items() if v <= now]
        for k in expired:
            _proxy_cooldown_until.pop(k, None)
            _proxy_retry_count.pop(k, None)
        _proxy_cooldown_until[proxy] = now + _get_backoff_seconds(retry_count)
        _proxy_retry_count[proxy] = retry_count


def _wait_for_direct_cooldown() -> bool:
    """等待全局直连退避结束。"""
    global _direct_cooldown_until
    with _direct_lock:
        deadline = _direct_cooldown_until
    if deadline is None:
        return True
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return True
    time.sleep(remaining)
    return True


def _set_direct_cooldown(retry_count: int) -> None:
    """设置全局直连退避状态（线程安全）"""
    global _direct_cooldown_until, _direct_retry_count
    now = time.monotonic()
    with _direct_lock:
        # 在锁内检查并清理已过期的退避（避免 TOCTOU 竞态）
        if _direct_cooldown_until is not None and _direct_cooldown_until <= now:
            _direct_cooldown_until = None
            _direct_retry_count = 0
        _direct_cooldown_until = now + _get_backoff_seconds(retry_count)
        _direct_retry_count = retry_count

# 平台级全局 Webhook URL
_GLOBAL_WEBHOOKS: dict[str, str | None] = {}
_GLOBAL_WEBHOOKS_LOADED = False
_GLOBAL_DINGTALK_SIGN_SECRET: str | None = None
_GLOBAL_TELEGRAM_CHAT_ID: str | None = None
_GLOBAL_TELEGRAM_TOKEN: str | None = None

# 模块级配置缓存（避免每次扫描重复读取 config.json）
_config_cache: dict | None = None


def _get_config() -> dict:
    """获取配置（带模块级缓存，外部保存配置时需调用 _invalidate_config_cache）"""
    global _config_cache
    if _config_cache is None:
        _config_cache = _db.load_config()
    return _config_cache


def _invalidate_config_cache() -> None:
    """配置已更新，清空缓存，下次 _get_config 会重新加载"""
    global _config_cache
    _config_cache = None


def _ensure_global_webhooks() -> None:
    """确保全局 Webhook 已加载（模块加载时 + 每次扫描前）"""
    global _GLOBAL_WEBHOOKS, _GLOBAL_WEBHOOKS_LOADED, _GLOBAL_DINGTALK_SIGN_SECRET, _GLOBAL_TELEGRAM_CHAT_ID, _GLOBAL_TELEGRAM_TOKEN
    if _GLOBAL_WEBHOOKS_LOADED:
        return
    try:
        cfg = _get_config()
        _GLOBAL_WEBHOOKS["feishu"] = cfg.get("global_feishu_url") or None
        _GLOBAL_WEBHOOKS["dingtalk"] = cfg.get("global_dingtalk_url") or None
        _GLOBAL_WEBHOOKS["wecom"] = cfg.get("global_wecom_url") or None
        _GLOBAL_DINGTALK_SIGN_SECRET = cfg.get("global_dingtalk_sign_secret") or None
        _GLOBAL_TELEGRAM_CHAT_ID = cfg.get("global_telegram_chat_id") or None
        _GLOBAL_TELEGRAM_TOKEN = cfg.get("global_telegram_token") or None
    except Exception:
        pass
    _GLOBAL_WEBHOOKS_LOADED = True

# PyInstaller 兼容路径（统一基于 utils.paths）
_PKG_DIR = get_pkg_dir()
_EXE_DIR = get_exe_dir()

# 项目根目录（用于下载等应始终指向项目源码根的路径，不依赖 sys.executable）
_MONITOR_ROOT = _PKG_DIR  # = monitor/

# 日志目录（exe 同级 logs/）
_LOG_DIR = get_log_dir()


# 已发送过的 quota 报警（key = f"{api_key}:{date}:{threshold}"）
_quota_alerted: set[str] = set()
# 与 quota 统计日对齐：换日时清空集合，避免长年运行只增不减
_quota_alerted_for_date_key: str | None = None


def _prune_quota_alerted_for_new_quota_day() -> None:
    """配额统计日切换时丢弃已记录 key，与 get_quota_date_key 口径一致。"""
    global _quota_alerted_for_date_key
    today = _quota.get_quota_date_key()
    if _quota_alerted_for_date_key != today:
        _quota_alerted.clear()
        _quota_alerted_for_date_key = today

# 扫描失败告警防抖（account_id -> 上次发送时间戳）
_scan_error_notify_lock = threading.Lock()
_scan_error_last_notify: dict[int, float] = {}


def _send_quota_alert(account: dict, api_key: str, usage: dict, budget: int) -> None:
    """发送 quota 预警/耗尽报警（优先账户级 Webhook，其次全局）"""
    platform = account.get("notify_platform", "feishu")
    if platform == "telegram":
        webhook_url = (
            account.get("telegram_bot_token")
            or _GLOBAL_TELEGRAM_TOKEN
        )
    else:
        webhook_url = (
            account.get("webhook_url")
            or _GLOBAL_WEBHOOKS.get(platform)
            or _GLOBAL_WEBHOOKS.get("feishu")
        )
    if not webhook_url:
        _log.warning(f"quota 报警无 Webhook URL，跳过: {account['name']}")
        return
    use_global_dingtalk_secret = platform == "dingtalk" and not account.get("webhook_url")
    _quota.send_alert(
        api_key,
        usage,
        budget,
        webhook_url,
        platform=platform,
        dingtalk_sign_secret=(
            account.get("dingtalk_sign_secret")
            or (_GLOBAL_DINGTALK_SIGN_SECRET if use_global_dingtalk_secret else None)
        ),
        telegram_chat_id=_GLOBAL_TELEGRAM_CHAT_ID if platform == "telegram" else None,
    )


def _resolve_api_key(account: dict) -> tuple[str | None, dict | None, int]:
    """
    解析账户使用的 API Key。
    返回 (api_key_value, api_key_record, budget)。

    优先级：账户 api_key_id → 系统 default_api_key_id → 账户 api_key_env 环境变量（兼容）
    """
    cfg = _get_config()
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
        api_key = os.environ.get(account.get("api_key_env") or "", "")
        if api_key:
            _log.info(f"使用环境变量兜底: {account.get('api_key_env')}")

    return api_key, api_key_record, budget


def _check_quota_alert(account: dict, api_key: str, budget: int) -> None:
    """检查是否需要发送 quota 预警（阈值来自配置 quota_alert_thresholds，默认 80/90/100）。"""
    _prune_quota_alerted_for_new_quota_day()
    cfg = _get_config()
    raw = cfg.get("quota_alert_thresholds")
    if isinstance(raw, list) and len(raw) > 0:
        try:
            thresholds = sorted({int(x) for x in raw if 1 <= int(x) <= 100})
        except (TypeError, ValueError):
            thresholds = [80, 90, 100]
    else:
        thresholds = [80, 90, 100]
    if not thresholds:
        thresholds = [80, 90, 100]

    _, usage = _quota.check_budget(api_key, budget)
    used = usage["api_calls"]
    today = _quota.get_quota_date_key()
    for threshold in thresholds:
        alert_key = f"{api_key}:{today}:{threshold}"
        if alert_key in _quota_alerted:
            continue
        if threshold >= 100:
            should_alert = used >= budget
        else:
            should_alert = used >= int(budget * threshold / 100)
        if should_alert:
            _quota_alerted.add(alert_key)
            _send_quota_alert(account, api_key, usage, budget)
            _log.warning(f"quota 预警已发送: {threshold}% ({used}/{budget}) — {account['name']}")
            break


def _maybe_notify_scan_error(account: dict, error_message: str) -> None:
    """扫描异常时按配置发送 Webhook，带防抖（scan_error_notify_cooldown_seconds）。"""
    cfg = _get_config()
    if not cfg.get("notify_on_scan_error"):
        return
    cooldown = int(cfg.get("scan_error_notify_cooldown_seconds") or 300)
    account_id = int(account["id"])
    now = time.monotonic()
    with _scan_error_notify_lock:
        last = _scan_error_last_notify.get(account_id)
        if last is not None and (now - last) < cooldown:
            _log.info(f"扫描失败告警已防抖跳过: {account['name']} ({cooldown}s 内)")
            return
        _scan_error_last_notify[account_id] = now

    platform = account.get("notify_platform", "feishu")
    if platform == "telegram":
        webhook_url = (
            account.get("telegram_bot_token")
            or _GLOBAL_TELEGRAM_TOKEN
        )
    else:
        webhook_url = (
            account.get("webhook_url")
            or _GLOBAL_WEBHOOKS.get(platform)
            or _GLOBAL_WEBHOOKS.get("feishu")
        )
    if not webhook_url:
        _log.warning(f"扫描失败告警无 Webhook URL，跳过: {account['name']}")
        return
    use_global_dingtalk_secret = platform == "dingtalk" and not account.get("webhook_url")
    _quota.send_scan_error_alert(
        account["name"],
        account.get("channel_url", ""),
        error_message,
        webhook_url,
        platform=platform,
        dingtalk_sign_secret=(
            account.get("dingtalk_sign_secret")
            or (_GLOBAL_DINGTALK_SIGN_SECRET if use_global_dingtalk_secret else None)
        ),
        telegram_chat_id=_GLOBAL_TELEGRAM_CHAT_ID if platform == "telegram" else None,
    )

def set_global_feishu_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["feishu"] = url
    _log.info(f"全局飞书 Webhook 已更新: {'已设置' if url else '未设置'}")

def set_global_dingtalk_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["dingtalk"] = url
    _log.info(f"全局钉钉 Webhook 已更新: {'已设置' if url else '未设置'}")


def set_global_dingtalk_sign_secret(secret: str | None) -> None:
    global _GLOBAL_DINGTALK_SIGN_SECRET
    _GLOBAL_DINGTALK_SIGN_SECRET = secret
    _log.info(f"全局钉钉加签密钥已更新: {'已设置' if secret else '未设置'}")

def set_global_wecom_url(url: str | None) -> None:
    _GLOBAL_WEBHOOKS["wecom"] = url
    _log.info(f"全局企微 Webhook 已更新: {'已设置' if url else '未设置'}")

def set_global_telegram_chat_id(chat_id: str | None) -> None:
    """设置全局 Telegram Chat ID"""
    global _GLOBAL_TELEGRAM_CHAT_ID
    _GLOBAL_TELEGRAM_CHAT_ID = chat_id
    _log.info(f"全局 Telegram Chat ID 已更新: {chat_id if chat_id else '未设置'}")

def set_global_telegram_token(token: str | None) -> None:
    """设置全局 Telegram Bot Token（用于通知投递）"""
    global _GLOBAL_TELEGRAM_TOKEN
    _GLOBAL_TELEGRAM_TOKEN = token
    _log.info(f"全局 Telegram Bot Token 已更新: {'已设置' if token else '未设置'}")


# provider refresh singleflight state
_refresh_locks: dict[int, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()
_refresh_results: dict[int, dict] = {}


def _get_refresh_lock(provider_id: int) -> threading.Lock:
    with _refresh_locks_guard:
        lock = _refresh_locks.get(provider_id)
        if lock is None:
            lock = threading.Lock()
            _refresh_locks[provider_id] = lock
        return lock


def refresh_dynamic_provider(provider_id: int) -> dict:
    """Task 9: refresh one dynamic provider and persist normalized candidates."""
    lock = _get_refresh_lock(provider_id)
    if not lock.acquire(blocking=False):
        with lock:
            return dict(_refresh_results.get(provider_id, {
                "ok": False,
                "provider_id": provider_id,
                "raw_count": 0,
                "valid_count": 0,
                "error": "refresh_in_progress",
            }))

    try:
        provider = _db.get_dynamic_proxy_provider(provider_id)
        if not provider:
            result = {
                "ok": False,
                "provider_id": provider_id,
                "raw_count": 0,
                "valid_count": 0,
                "error": "provider_not_found",
            }
            _refresh_results[provider_id] = result
            return dict(result)

        from monitor.candidate_probe_transport import UrllibCandidateTransport
        from monitor.provider_templates import fetch_provider_candidates
        from monitor.proxy_validator import CandidateProbeValidator

        candidates = fetch_provider_candidates(provider, {})
        validator = CandidateProbeValidator(transport=UrllibCandidateTransport())
        status_counts: dict[str, int] = {}
        latency_values: list[int] = []
        score_values: list[float] = []
        top_candidate: dict | None = None
        top_healthy_key: tuple[int, int] | None = None
        for candidate in candidates:
            probe_result = None
            try:
                import asyncio
                probe_result = asyncio.run(validator.probe_lightweight(candidate, timeout=8))
            except Exception:
                probe_result = None
            probe_status = probe_result.status if probe_result is not None else getattr(candidate, "last_probe_status", "unknown")
            probe_latency = probe_result.latency_ms if probe_result is not None else getattr(candidate, "latency_ms", None)
            score = getattr(candidate, "score", 0.0)
            score_value = float(score) if isinstance(score, (int, float)) else 0.0

            status_counts[probe_status] = status_counts.get(probe_status, 0) + 1
            if isinstance(probe_latency, int):
                latency_values.append(probe_latency)
            score_values.append(score_value)
            if probe_status == "healthy":
                if isinstance(probe_latency, int) and probe_latency >= 0:
                    hkey = (0, probe_latency, -score_value)
                else:
                    hkey = (1, 0, -score_value)
                # 与 db.pick_healthy_fastest_top_candidate 一致：latency_ms 升序取最小，并列 score 高者优先
                if top_healthy_key is None or hkey < top_healthy_key:
                    top_healthy_key = hkey
                    top_candidate = {
                        "masked_proxy_endpoint": getattr(candidate, "masked_proxy_endpoint", None),
                        "last_probe_status": probe_status,
                        "latency_ms": probe_latency,
                        "score": score_value,
                    }

            _db.add_proxy_candidate(
                provider_id=provider_id,
                protocol=candidate.protocol,
                host=candidate.host,
                port=candidate.port,
                username=getattr(candidate, "username", None),
                auth_type=getattr(candidate, "auth_type", "none"),
                country_code=getattr(candidate, "country_code", None),
                region=getattr(candidate, "region", None),
                city=getattr(candidate, "city", None),
                anonymity=getattr(candidate, "anonymity", None),
                risk_level=getattr(candidate, "risk_level", "medium"),
                supports_https=getattr(candidate, "supports_https", True),
                supports_cookies=getattr(candidate, "supports_cookies", False),
                supports_auto_download=getattr(candidate, "supports_auto_download", True),
                supports_sticky_session=getattr(candidate, "supports_sticky_session", False),
                latency_ms=probe_latency,
                last_probe_status=probe_status,
                last_probe_at=getattr(candidate, "last_probe_at", None),
                score=score_value,
                provider_reference_id=getattr(candidate, "provider_reference_id", None),
                ttl_expires_at=getattr(candidate, "ttl_expires_at", None),
                masked_proxy_endpoint=None,
            )

        latency_summary = {
            "count": len(latency_values),
            "min_ms": min(latency_values) if latency_values else None,
            "max_ms": max(latency_values) if latency_values else None,
        }
        score_summary = {
            "count": len(score_values),
            "min_score": min(score_values) if score_values else None,
            "max_score": max(score_values) if score_values else None,
        }

        result = {
            "ok": True,
            "provider_id": provider_id,
            "raw_count": len(candidates),
            "valid_count": len(candidates),
            "status_counts": status_counts,
            "latency_summary": latency_summary,
            "score_summary": score_summary,
            "top_candidate": top_candidate,
        }
        _refresh_results[provider_id] = result
        return dict(result)
    finally:
        lock.release()


def _cleanup_stale_and_expired_candidates() -> None:
    """每日清理任务：删除过期 TTL 候选 + 长期 down 候选。"""
    try:
        deleted_expired = _db.delete_expired_candidates()
    except Exception:
        deleted_expired = 0
        _log.warning("delete_expired_candidates failed", exc_info=True)
    try:
        deleted_stale = _db.cleanup_stale_candidates(stale_days=7)
    except Exception:
        deleted_stale = 0
        _log.warning("cleanup_stale_candidates failed", exc_info=True)
    total = deleted_expired + deleted_stale
    if total > 0:
        _log.info(f"候选清理完成: 过期={deleted_expired} 长期down={deleted_stale} 总计={total}")


# 共享调度器实例
_scheduler: "BackgroundScheduler | None" = None
_scheduler_lock = threading.Lock()

# 稳妥配置：2 线程池 × 2 分片 = 4 并发（安全不触发 YouTube 429）
_auto_dl_pool: ThreadPoolExecutor | None = ThreadPoolExecutor(max_workers=2)

# stop() 时对池子使用 shutdown(wait=False) 后，worker 仍可能运行；需保留引用以便进程退出时 join
_pending_join_pools: list[ThreadPoolExecutor] = []

# 调度器运行期间的自动下载开关（由 start() 设置，stop() 重置）
_auto_download_on_scan: bool = False

# 调度器关闭取消标志（由 stop() 设置，运行中的任务应周期性检查并提前退出）
_scheduler_cancelled: bool = False

# ── per-account 下载池（替代全局 _auto_dl_pool）─────────────────────────
_account_pools: dict[int, ThreadPoolExecutor] = {}   # account_id → 独立池
_account_pools_lock = threading.Lock()                # 保护账户池创建/销毁
_POOL_MAX_WORKERS = 2  # 每账户最大并发下载数


def _ensure_account_pool(account_id: int) -> ThreadPoolExecutor:
    """获取或创建指定账户的独立下载池（线程安全）"""
    with _account_pools_lock:
        if account_id not in _account_pools:
            _account_pools[account_id] = ThreadPoolExecutor(max_workers=_POOL_MAX_WORKERS)
        return _account_pools[account_id]


def _shutdown_account_pool(account_id: int, wait: bool = False) -> None:
    """关闭指定账户的下载池"""
    with _account_pools_lock:
        pool = _account_pools.pop(account_id, None)
    if pool is None:
        return
    try:
        pool.shutdown(wait=wait, cancel_futures=True)
    except TypeError:
        pool.shutdown(wait=wait)


def _ensure_auto_download_pool() -> ThreadPoolExecutor:
    global _auto_dl_pool
    if _auto_dl_pool is None:
        _auto_dl_pool = ThreadPoolExecutor(max_workers=2)
    return _auto_dl_pool


def is_scheduler_cancelled() -> bool:
    """检查调度器是否已请求取消（用于运行中的任务提前退出）。"""
    return _scheduler_cancelled


def _shutdown_auto_download_pool(wait: bool = False) -> None:
    global _auto_dl_pool
    pool = _auto_dl_pool
    _auto_dl_pool = None
    if pool is None:
        return
    try:
        pool.shutdown(wait=wait, cancel_futures=True)
    except TypeError:
        pool.shutdown(wait=wait)
    if not wait:
        _pending_join_pools.append(pool)


def join_auto_download_workers(timeout_sec: float | None = 30.0) -> None:
    """
    进程退出前调用：等待自动下载线程池里尚未结束的工作线程。

    「停止监控」时 _shutdown_auto_download_pool(wait=False) 不会等待正在执行的
    batch_download；ThreadPoolExecutor 的 worker 为非 daemon 线程，会导致解释器
    在 main 返回后仍阻塞。此处对 wait=False 阶段遗留的池子逐个 join worker。

    注意：绝不能用 shutdown(wait=True) 无超时等待——若 batch_download/yt-dlp
    卡死，会无限阻塞，Ctrl+C 后用户会看到「正在等待…」永远结束不了。
    统一用 shutdown(wait=False)+按 deadline join 各 worker，总耗时受 timeout_sec 约束。
    """
    global _auto_dl_pool

    if _auto_dl_pool is not None:
        pool = _auto_dl_pool
        _auto_dl_pool = None
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
        _pending_join_pools.append(pool)

    if not _pending_join_pools:
        return

    deadline = time.monotonic() + (timeout_sec if timeout_sec is not None else 86400.0)
    if timeout_sec is not None:
        print(f"正在等待后台自动下载结束（最多 {timeout_sec:.0f} 秒）...")
    else:
        print("正在等待后台自动下载结束...")

    # stop() / 上一段已对池 shutdown(wait=False)：join 各 worker（实现细节 _threads），受 deadline 约束。
    while _pending_join_pools:
        pool = _pending_join_pools.pop(0)
        threads = getattr(pool, "_threads", None) or ()
        for t in list(threads):
            while t.is_alive():
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    _pending_join_pools.insert(0, pool)
                    _log.warning(
                        "join_auto_download_workers: 超时，仍有后台下载线程未结束，强制结束进程"
                    )
                    print("⚠️ 等待超时，强制结束进程（未完成的下载可能被中断）")
                    os._exit(0)
                t.join(timeout=remaining)
        _log.debug("join_auto_download_workers: 已 join 一个线程池")

    _log.info("join_auto_download_workers: 完成")


def _submit_download_batch(
    batch_urls, batch_records, batch_ids, output_path, proxy, cookies_file,
    extra_ydl_opts, cfg, pool, account_id,
):
    """提交一个下载手次到线程池"""
    def _dl_batch():
        try:
            _db.update_videos_download_status(batch_ids, "downloading")
            results = batch_download(
                batch_urls,
                output_path,
                "best",
                proxy=proxy,
                cookies_file=cookies_file,
                concurrent_fragments=2,
                no_subs=not cfg.get("auto_clip_enabled", False),
                extra_ydl_opts=extra_ydl_opts,
            )

            now_str = _db.now_iso()
            for idx2, r in enumerate(results):
                vid = batch_ids[idx2] if idx2 < len(batch_ids) else None
                if not vid:
                    continue
                if r.get("状态") == "成功":
                    file_path = r.get("video_path") or output_path
                    _db.update_videos_download_status(
                        [vid], "downloaded",
                        download_at=now_str,
                        download_path=file_path,
                        retry_count=0,
                    )
                    success_records = _db.get_videos_by_ids([vid])
                    _maybe_trigger_auto_clip(success_records, cfg)
                elif r.get("is_rate_limited"):
                    _handle_rate_limited(
                        vid, batch_urls[idx2], batch_records[idx2],
                        proxy, output_path, cookies_file, extra_ydl_opts, cfg,
                    )
                else:
                    _db.update_videos_download_status(
                        [vid], "failed",
                        download_error=r.get("信息", ""),
                        retry_count=0,
                        failed_reason="batch_download_error",
                        failed_at=now_str,
                    )
        except Exception as exc:
            _log.error("手次下载异常", exc_info=True)
            _db.update_videos_download_status(
                batch_ids, "failed",
                download_error=f"自动下载异常: {type(exc).__name__}",
                retry_count=0,
                failed_reason="batch_download_exception",
                failed_at=_db.now_iso(),
            )

    if pool is not None:
        pool.submit(_dl_batch)
    else:
        threading.Thread(target=_dl_batch, daemon=True).start()


def _handle_rate_limited(
    vid: int, url: str, record: dict,
    proxy: str | None, output_path: str,
    cookies_file, extra_ydl_opts, cfg,
    retry_count: int = 0,
):
    """
    处理单个视频的 429 退避重试逻辑。使用循环避免递归深度风险。
    最多 3 次代理退避后切换直连，直连最多 3 次退避。
    """
    MAX_RETRIES = 3
    while True:
        is_proxy = proxy is not None
        if is_proxy:
            _wait_for_proxy_cooldown(proxy)
            retry_count += 1
            _log.warning(f"代理退避结束，重试视频: {url} (retry={retry_count})")
            _db.update_videos_download_status([vid], retry_count=retry_count)
            try:
                results = batch_download(
                    [url], output_path, "best",
                    proxy=proxy,
                    cookies_file=cookies_file,
                    concurrent_fragments=2,
                    extra_ydl_opts=extra_ydl_opts,
                )
                r = results[0] if results else {}
                if r.get("状态") == "成功":
                    _db.update_videos_download_status(
                        [vid], "downloaded",
                        download_path=r.get("video_path", ""),
                        retry_count=0,
                    )
                    return
                if r.get("is_rate_limited"):
                    if retry_count >= MAX_RETRIES:
                        _log.warning(f"代理退避重试 {retry_count} 次后仍 429，切换直连: {url}")
                        proxy = None  # 切换直连
                        retry_count = 0
                        continue
                    _set_proxy_cooldown(proxy, retry_count)
                    # 继续循环
                else:
                    _db.update_videos_download_status(
                        [vid], "failed",
                        download_error=r.get("信息"),
                        retry_count=0,
                        failed_reason="proxy_download_error",
                        failed_at=_db.now_iso(),
                    )
                    return
            except Exception as exc:
                _db.update_videos_download_status(
                    [vid], "failed",
                    download_error=f"退避重试异常: {exc}",
                    retry_count=0,
                    failed_reason="backoff_exception",
                    failed_at=_db.now_iso(),
                )
                return
        else:
            # 直连退避（委托给循环处理）
            _handle_direct_fallback(
                vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg,
                initial_retry_count=retry_count,
            )
            return


def _handle_direct_fallback(
    vid, url, record, output_path, cookies_file, extra_ydl_opts, cfg,
    initial_retry_count: int = 0,
):
    """直连 429 退避重试（独立于代理退避），使用循环避免递归深度风险。"""
    retry_count = initial_retry_count
    MAX_RETRIES = 3

    while True:
        _wait_for_direct_cooldown()
        retry_count += 1
        _db.update_videos_download_status([vid], retry_count=retry_count)

        if retry_count > MAX_RETRIES:
            _db.update_videos_download_status(
                [vid], "failed",
                download_error=f"429 rate limit after {MAX_RETRIES} retries",
                retry_count=0,
                failed_reason="direct_rate_limit_exhausted",
                failed_at=_db.now_iso(),
            )
            return

        _set_direct_cooldown(retry_count)
        _log.warning(f"直连退避 {retry_count}/{MAX_RETRIES} 次: {url}")

        try:
            results = batch_download(
                [url], output_path, "best",
                proxy=None,
                cookies_file=cookies_file,
                concurrent_fragments=2,
                extra_ydl_opts=extra_ydl_opts,
            )
            r = results[0] if results else {}
            if r.get("状态") == "成功":
                _db.update_videos_download_status(
                    [vid], "downloaded",
                    download_path=r.get("video_path", ""),
                    retry_count=0,
                )
                return
            if not r.get("is_rate_limited"):
                _db.update_videos_download_status(
                    [vid], "failed",
                    download_error=r.get("信息"),
                    retry_count=0,
                    failed_reason="direct_download_error",
                    failed_at=_db.now_iso(),
                )
                return
            # 继续循环（is_rate_limited=True）
        except Exception as exc:
            _db.update_videos_download_status(
                [vid], "failed",
                download_error=f"直连退避重试异常: {exc}",
                retry_count=0,
                failed_reason="direct_backoff_exception",
                failed_at=_db.now_iso(),
            )
            return


def _auto_download_videos(
    video_records: list[dict],
    proxy: str | None = None,
    account_id: int | None = None,
) -> None:
    """per-account 子池执行下载支持 429 指数退遇重试"""
    if not video_records:
        return
    urls = [r["url"] for r in video_records if r.get("url")]
    if not urls:
        return

    cfg = _get_config()
    output_path = cfg.get("download_output_path", "").strip()
    if not output_path:
        output_path = os.path.join(_MONITOR_ROOT, "..", "videos")
        output_path = os.path.normpath(output_path)
    os.makedirs(output_path, exist_ok=True)

    cookies_file = cfg.get("download_cookies_file", "") or None
    enable_aria2 = bool(cfg.get("enable_aria2", False))
    extra_ydl_opts = build_aria2_opts() if enable_aria2 else None

    BATCH_SIZE = 2
    pool = _ensure_account_pool(account_id) if account_id else _ensure_auto_download_pool()

    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i:i + BATCH_SIZE]
        chunk_records = video_records[i:i + BATCH_SIZE]
        chunk_ids = [r["id"] for r in chunk_records]

        _log.info(
            f"自动下载批次 {i // BATCH_SIZE + 1}: "
            f"{len(chunk)} 个视频 "
            f"{'[aria2]' if enable_aria2 else ''}"
            f"{'[proxy]' if proxy else '[direct]'}"
        )

        _submit_download_batch(
            chunk, chunk_records, chunk_ids, output_path, proxy,
            cookies_file, extra_ydl_opts, cfg, pool, account_id,
        )

    _log.info(f"自动下载任务已全部提交: {len(urls)} 个视频")


def trigger_scan(account_id: int, auto_download: bool = False) -> None:
    """
    公开方法：触发指定账户的手动扫描（立即扫描）。
    供 server/__main__.py 的 Web UI 端点调用。
    """
    _scan_account(account_id, auto_download=auto_download)


def _scan_account(account_id: int, auto_download: bool = False, from_scheduler: bool = False) -> None:
    """
    执行单个账户的扫描任务。
    from_scheduler: 区分来自 APScheduler 定时调度还是手动触发。调度器关闭时只有
    定时调度任务需要跳过，手动扫描（立即扫描）不受影响。
    """
    start_time = time.perf_counter()

    # 确保全局 Webhook 配置已加载（无论从 UI 还是调度器触发）
    _ensure_global_webhooks()

    # 仅调度器定时任务在关闭时提前退出；手动触发（立即扫描）不受此标志影响
    if from_scheduler and _scheduler_cancelled:
        _log.info(f"调度器已关闭，跳过账户扫描: id={account_id}")
        return

    _log.info(f"开始扫描账户: id={account_id}")

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

    cfg_scan = _get_config()
    # 错峰：在扫描 worker 内同步 sleep，会延长本账户本回合占用线程的时间；
    # 账户/任务量较大时请适度减小 scan_jitter_seconds 以免拖长排队。
    jmax = int(cfg_scan.get("scan_jitter_seconds") or 0)
    if jmax > 0:
        delay = random.randint(0, jmax)
        if delay > 0:
            _log.info(f"扫描错峰延迟 {delay}s: {account['name']}")
            time.sleep(delay)

    try:
        # ── 1. 获取视频 ────────────────────────────────────
        proxy = _db.get_account_proxy(account)
        fetcher = _fetcher.YouTubeFetcher(
            api_key=api_key,
            fetch_mode=account["fetch_mode"],
            fetch_limit=account["fetch_limit"],
            view_threshold=0,
            proxy=proxy,
        )
        videos, channel_info = fetcher.fetch(
            account["channel_url"],
            should_cancel=is_scheduler_cancelled,
        )

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
            f"account_telegram_token={bool(account.get('telegram_bot_token'))} "
            f"global_webhook={bool(account.get('webhook_url')) or (account.get('notify_platform') == 'telegram' and bool(_GLOBAL_TELEGRAM_TOKEN)) or bool(_GLOBAL_WEBHOOKS.get(account.get('notify_platform','feishu')))}"
        )
        if account["notify_enabled"] and new_videos:
            platform = account.get("notify_platform", "feishu")
            if platform == "telegram":
                webhook_url = account.get("telegram_bot_token") or _GLOBAL_TELEGRAM_TOKEN
            else:
                webhook_url = account.get("webhook_url")
                if not webhook_url:
                    webhook_url = _GLOBAL_WEBHOOKS.get(platform)
            use_global_dingtalk_secret = (
                account.get("notify_platform", "feishu") == "dingtalk"
                and not account.get("webhook_url")
            )
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
                dingtalk_sign_secret=(
                    account.get("dingtalk_sign_secret")
                    or (_GLOBAL_DINGTALK_SIGN_SECRET if use_global_dingtalk_secret else None)
                ),
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
        # 解析代理（账户启用时从 proxy_pool 中获取）
        proxy = _db.get_account_proxy(account)
        if proxy:
            # 仅记录已使用代理，不记录完整 URL（含认证信息）
            try:
                from urllib.parse import urlparse
                parsed = urlparse(proxy)
                proxy_repr = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{parsed.hostname}"
            except Exception:
                proxy_repr = "[已启用]"
            _log.info(f"自动下载将使用代理: {account['name']} → {proxy_repr}")

        if effective_auto_dl and inserted > 0:
            with _db.get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, url, account_id FROM monitor_videos WHERE event_id = ?",
                    (event_id,),
                ).fetchall()
            new_video_records = [dict(r) for r in rows]

            threading.Thread(
                target=_auto_download_videos,
                args=(new_video_records, proxy, account["id"]),
                daemon=True,
                name=f"auto-dl-{event_id}",
            ).start()
            _log.info(f"自动下载已触发: {inserted} 个新视频{(' [proxy]' if proxy else '')}")

        # ── 5. Quota 预警检查 ────────────────────────────────
        _check_quota_alert(account, api_key, budget)
        # 更新扫描次数统计
        _db.incr_api_key_quota(api_key, scans=1)

    except Exception as e:
        _log.error(f"扫描异常: 账户={account['name']} — {e}")
        err_text = str(e)
        _db.finish_event(
            event_id,
            status="error",
            total_videos=0, new_videos=0,
            error_message=err_text,
            duration_ms=int((time.perf_counter() - start_time) * 1000),
        )
        _ensure_global_webhooks()
        try:
            _maybe_notify_scan_error(account, err_text)
        except Exception as notify_exc:
            _log.warning(f"扫描失败告警发送异常: {notify_exc}")


def start(auto_download: bool = False) -> tuple[bool, bool]:
    """
    启动调度器

    auto_download: 启动后每次扫描到新视频是否自动下载（当前扫描有效，非全局持久化）

    Returns:
        (ok, already_running): ok 为 True 表示成功；already_running 为 True 表示本次为幂等调用
        （调度器已在运行，仅同步了 auto_download 选项）。
    """
    global _scheduler, _auto_download_on_scan, _scheduler_cancelled

    # 防御：确保启动时取消标志为 False（进程重启后可省此行，兼作安全兜底）
    if _scheduler_cancelled:
        _log.warning("start() 发现 _scheduler_cancelled=True（可能上次 stop 未完全清理），强制重置")
        _scheduler_cancelled = False
    else:
        _log.info(f"调度器启动中... _scheduler={_scheduler is not None}")

    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            # 幂等：重复「启动」请求视为成功，避免 Web UI 收到 ok:false（重复点击/双请求等）
            _auto_download_on_scan = auto_download
            _log.info(
                "调度器已在运行中，已同步自动下载选项并返回成功（幂等启动）"
                f"{'（自动下载开）' if auto_download else ''}"
            )
            return True, True

        _auto_download_on_scan = auto_download
        _ensure_auto_download_pool()

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
            _GLOBAL_TELEGRAM_CHAT_ID = cfg.get("global_telegram_chat_id")
            _log.info(f"全局 Webhook 已加载: 飞书={bool(_GLOBAL_WEBHOOKS['feishu'])} "
                      f"钉钉={bool(_GLOBAL_WEBHOOKS['dingtalk'])} "
                      f"企微={bool(_GLOBAL_WEBHOOKS['wecom'])} "
                      f"Telegram Chat ID={bool(_GLOBAL_TELEGRAM_CHAT_ID)}")

        # 初始化数据库
        _db.init_db()
        _db.ensure_app_state_table()

        # 重启恢复：将 running 状态标记为 failed（防止僵尸任务）
        _db.mark_stale_running_videos_interrupted()

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
                kwargs={"from_scheduler": True},
                id=f"account_{acc['id']}",
                name=f"{acc['name']} ({acc['channel_url']})",
                replace_existing=True,
            )
            _log.info(
                f"注册任务: {acc['name']} 间隔={acc['scan_interval']}分钟 "
                f"模式={acc['fetch_mode']} 限制={acc['fetch_limit']}"
            )

        # 注册动态代理 provider 周期性刷新任务
        providers = _db.list_dynamic_proxy_providers()
        for prov in providers:
            if not prov.get("enabled"):
                continue
            interval = prov.get("refresh_interval_minutes", 0)
            if interval <= 0:
                continue
            _scheduler.add_job(
                func=refresh_dynamic_provider,
                trigger=apscheduler.triggers.interval.IntervalTrigger(
                    minutes=interval,
                    start_date=datetime.now().astimezone(),
                ),
                args=[prov["id"]],
                id=f"provider_refresh_{prov['id']}",
                name=f"ProviderRefresh {prov['name']}",
                replace_existing=True,
            )
            _log.info(
                f"注册 Provider 刷新任务: {prov['name']} 间隔={interval}分钟"
            )

        # 注册每日候选清理任务
        _scheduler.add_job(
            func=_cleanup_stale_and_expired_candidates,
            trigger=apscheduler.triggers.interval.IntervalTrigger(
                hours=24,
                start_date=datetime.now().astimezone(),
            ),
            id="cleanup_stale_candidates",
            name="CleanupStaleCandidates",
            replace_existing=True,
        )
        _log.info("注册候选清理任务: 每24小时清理一次")

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
        return True, False


def stop() -> bool:
    """
    停止调度器
    """
    global _scheduler, _auto_download_on_scan, _scheduler_cancelled

    with _scheduler_lock:
        if not _scheduler or not _scheduler.running:
            _log.warning("调度器未运行")
            return False

        _auto_download_on_scan = False
        _scheduler_cancelled = True
        scheduler = _scheduler
        _scheduler = None

    try:
        scheduler.shutdown(wait=False)
    finally:
        _shutdown_auto_download_pool(wait=False)
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

    # Provider refresh jobs
    providers = _db.list_dynamic_proxy_providers()
    target_provider_job_ids = set()
    for prov in providers:
        if not prov.get("enabled"):
            continue
        interval = prov.get("refresh_interval_minutes", 0)
        if interval <= 0:
            continue
        job_id = f"provider_refresh_{prov['id']}"
        target_provider_job_ids.add(job_id)
        job_kwargs = {
            "func": refresh_dynamic_provider,
            "trigger": apscheduler.triggers.interval.IntervalTrigger(
                minutes=interval,
                start_date=datetime.now().astimezone(),
            ),
            "args": [prov["id"]],
            "name": f"ProviderRefresh {prov['name']}",
            "replace_existing": True,
        }
        if job_id in current_job_ids:
            _scheduler.reschedule_job(job_id, **job_kwargs)
        else:
            _scheduler.add_job(**job_kwargs)
        _log.info(f"{'更新' if job_id in current_job_ids else '添加'}Provider刷新: {prov['name']} @ {interval}min")

    # 移除不再需要的 provider refresh jobs
    all_current_ids = {_j.id for _j in _scheduler.get_jobs()}
    for job_id in all_current_ids:
        if job_id.startswith("provider_refresh_") and job_id not in target_provider_job_ids:
            _scheduler.remove_job(job_id)
            _log.info(f"移除失效 Provider 刷新任务: {job_id}")

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
# ── Auto-clip trigger (Stage 3.2) ─────────────────────────────────────────────
# Append to monitor/scheduler.py

def _run_auto_clip_for_video(video_record: dict, cfg: dict) -> None:
    """对单个已下载视频执行 AI 切片 pipeline（后台线程运行）"""
    from pathlib import Path

    video_path_str = resolve_downloaded_video_path(video_record)
    if not video_path_str:
        _log.warning("[auto-clip] 无法解析已下载视频路径，跳过")
        return

    video_path = Path(video_path_str)
    if not video_path.is_file():
        _log.warning(f"[auto-clip] 视频路径无效，跳过: {video_path}")
        return

    video_dir = video_path.parent

    # 获取账户代理（用于 LLM API 请求）
    account_proxy = None
    if video_record.get("account_id"):
        account = _db.get_account(video_record["account_id"])
        if account:
            account_proxy = _db.get_account_proxy(account)
    video_stem = video_path.stem  # 不含扩展名的文件名
    sub_path = None

    # 优先精确匹配：同名字幕（无语言代码）
    for ext in (".srt", ".vtt"):
        candidate = video_dir / f"{video_stem}{ext}"
        if candidate.exists():
            sub_path = candidate
            break

    # 其次模糊匹配：video.*.srt / video.*.vtt（带语言代码，如 video.en.vtt）
    if not sub_path:
        for candidate in video_dir.iterdir():
            if candidate.is_file() and candidate.stem.startswith(video_stem + ".") and candidate.suffix in (".srt", ".vtt"):
                sub_path = candidate
                break

    if not sub_path:
        _log.info(f"[auto-clip] 字幕文件不存在（支持 .srt/.vtt），跳过: {video_stem}")
        return

    try:
        from scripts.llm_client import create_llm_client
        from scripts.clip_pipeline import ClipPipeline

        llm_client = create_llm_client(
            provider=cfg.get("llm_provider"),
            model=cfg.get("llm_model") or None,
            api_key=cfg.get("llm_api_key") or None,
            base_url=cfg.get("llm_base_url") or None,
        )

        output_dir = video_path.parent / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)

        pipeline = ClipPipeline(
            llm_client=llm_client,
            output_dir=str(output_dir),
            min_score=float(cfg.get("llm_min_score", 7.0)),
        )

        _log.info(f"[auto-clip] 开始切片: {video_path.name}")
        ctx = pipeline.run(
            str(video_path),
            str(sub_path),
            category=cfg.get("llm_category", "knowledge"),
        )

        _log.info(
            f"[auto-clip] 完成: {video_path.name} — "
            f"{len(ctx.generated_clips)} 切片, "
            f"{len(ctx.generated_collections)} 合集"
        )

        if cfg.get("auto_clip_notify_enabled"):
            from scripts.clip_notifier import notify_pipeline_result
            try:
                notify_pipeline_result(
                    ctx,
                    video_title=video_record.get("title") or video_path.stem,
                )
                _log.info("[auto-clip] 通知发送完成")
            except Exception as exc:
                _log.warning(f"[auto-clip] 通知发送失败: {exc}")

    except FileNotFoundError as exc:
        _log.warning(f"[auto-clip] 文件缺失跳过: {exc}")
    except Exception as exc:
        _log.error(f"[auto-clip] pipeline 异常: {video_path.name} — {exc}", exc_info=True)


def _maybe_trigger_auto_clip(video_records: list[dict], cfg: dict) -> None:
    """检查配置后为已下载视频异步触发 auto-clip"""
    if not cfg.get("auto_clip_enabled"):
        return

    for record in video_records:
        if record.get("download_status") == "downloaded" and record.get("download_path"):
            threading.Thread(
                target=_run_auto_clip_for_video,
                args=(record, cfg),
                daemon=True,
                name=f"auto-clip-{record.get('id', '?')}",
            ).start()

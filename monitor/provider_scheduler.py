"""monitor.provider_scheduler — 独立的动态代理提供方调度器

只负责：
- list_api/public_feed/custom list-like provider refresh jobs
- stale/expired candidate cleanup jobs
- run-once bulk provider refresh
"""
import threading
from datetime import datetime
import time
from typing import TYPE_CHECKING

import apscheduler.schedulers.background
import apscheduler.triggers.interval

import logging_config
import monitor.db as _db
from monitor.scheduler import refresh_dynamic_provider, _cleanup_stale_and_expired_candidates

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler

_log = logging_config.get_logger("monitor.provider_scheduler")

_provider_scheduler: "BackgroundScheduler | None" = None
_provider_scheduler_lock = threading.Lock()


def _iter_refreshable_providers() -> list[dict]:
    providers = _db.list_dynamic_proxy_providers()
    result = []
    for p in providers:
        if not p.get("enabled"):
            continue
        if p.get("adapter_type") not in ("list_api", "public_feed"):
            continue
        interval = int(p.get("refresh_interval_minutes") or 0)
        if interval <= 0:
            continue
        result.append(p)
    return result


def _record_run(provider_id, provider_name, job_type, status, raw_count=0, valid_count=0, message=None, started_at=None, finished_at=None, duration_ms=None):
    _db.add_provider_scheduler_run(
        provider_id=provider_id,
        provider_name=provider_name,
        job_type=job_type,
        status=status,
        raw_count=raw_count,
        valid_count=valid_count,
        message=message,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


def _run_scheduled_refresh(provider_id: int) -> None:
    """APScheduler 定时回调：拉取列表并写入与 run_once 一致的调度运行记录。"""
    prov = _db.get_dynamic_proxy_provider(provider_id)
    name = prov.get("name") if prov else None
    started = _db.now_iso()
    t0 = time.perf_counter()
    _log.info(
        "scheduled provider refresh start provider_id=%s name=%s",
        provider_id,
        name,
    )
    try:
        result = refresh_dynamic_provider(provider_id)
        _record_run(
            provider_id=provider_id,
            provider_name=name,
            job_type="refresh",
            status="success" if result.get("ok") else "error",
            raw_count=int(result.get("raw_count") or 0),
            valid_count=int(result.get("valid_count") or 0),
            message=result.get("error") or "ok",
            started_at=started,
            finished_at=_db.now_iso(),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        _record_run(
            provider_id=provider_id,
            provider_name=name,
            job_type="refresh",
            status="error",
            raw_count=0,
            valid_count=0,
            message=str(exc),
            started_at=started,
            finished_at=_db.now_iso(),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        _log.exception(
            "scheduled provider refresh failed provider_id=%s",
            provider_id,
        )
        raise


def _run_cleanup_job() -> None:
    started = _db.now_iso()
    t0 = time.perf_counter()
    try:
        _cleanup_stale_and_expired_candidates()
        _record_run(
            provider_id=None,
            provider_name=None,
            job_type='cleanup',
            status='success',
            message='provider cleanup completed',
            started_at=started,
            finished_at=_db.now_iso(),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        _record_run(
            provider_id=None,
            provider_name=None,
            job_type='cleanup',
            status='error',
            message=str(exc),
            started_at=started,
            finished_at=_db.now_iso(),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
        raise


def start() -> bool:
    global _provider_scheduler
    with _provider_scheduler_lock:
        if _provider_scheduler and _provider_scheduler.running:
            _log.warning("provider scheduler already running")
            return False

        _provider_scheduler = apscheduler.schedulers.background.BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            },
        )

        for prov in _iter_refreshable_providers():
            interval = int(prov.get("refresh_interval_minutes") or 0)
            _provider_scheduler.add_job(
                func=_run_scheduled_refresh,
                trigger=apscheduler.triggers.interval.IntervalTrigger(
                    minutes=interval,
                    start_date=datetime.now().astimezone(),
                ),
                args=[prov["id"]],
                id=f"provider_refresh_{prov['id']}",
                name=f"ProviderRefresh {prov['name']}",
                replace_existing=True,
            )

        _provider_scheduler.add_job(
            func=_run_cleanup_job,
            trigger=apscheduler.triggers.interval.IntervalTrigger(
                hours=24,
                start_date=datetime.now().astimezone(),
            ),
            id="provider_cleanup_candidates",
            name="ProviderCleanupCandidates",
            replace_existing=True,
        )

        _provider_scheduler.start()
        _log.info("provider scheduler started")
        return True


def stop() -> bool:
    global _provider_scheduler
    with _provider_scheduler_lock:
        if not _provider_scheduler or not _provider_scheduler.running:
            _log.warning("provider scheduler not running")
            return False
        _provider_scheduler.shutdown(wait=True)
        _log.info("provider scheduler stopped")
        return True


def reload_jobs() -> int:
    if not _provider_scheduler or not _provider_scheduler.running:
        _log.warning("provider scheduler not running")
        return 0

    current_job_ids = {_j.id for _j in _provider_scheduler.get_jobs()}
    target_job_ids = set()

    for prov in _iter_refreshable_providers():
        interval = int(prov.get("refresh_interval_minutes") or 0)
        job_id = f"provider_refresh_{prov['id']}"
        target_job_ids.add(job_id)
        _provider_scheduler.add_job(
            func=_run_scheduled_refresh,
            trigger=apscheduler.triggers.interval.IntervalTrigger(
                minutes=interval,
                start_date=datetime.now().astimezone(),
            ),
            args=[prov["id"]],
            id=job_id,
            name=f"ProviderRefresh {prov['name']}",
            replace_existing=True,
        )

    # keep cleanup job alive
    cleanup_job_id = "provider_cleanup_candidates"
    target_job_ids.add(cleanup_job_id)
    if cleanup_job_id not in current_job_ids:
        _provider_scheduler.add_job(
            func=_run_cleanup_job,
            trigger=apscheduler.triggers.interval.IntervalTrigger(
                hours=24,
                start_date=datetime.now().astimezone(),
            ),
            id=cleanup_job_id,
            name="ProviderCleanupCandidates",
            replace_existing=True,
        )

    for job_id in list({_j.id for _j in _provider_scheduler.get_jobs()}):
        if job_id not in target_job_ids:
            _provider_scheduler.remove_job(job_id)

    return len(_provider_scheduler.get_jobs())


def run_once() -> dict:
    providers = _iter_refreshable_providers()
    results = []
    for p in providers:
        started = _db.now_iso()
        t0 = time.perf_counter()
        try:
            result = refresh_dynamic_provider(p["id"])
        except Exception as exc:
            result = {
                "ok": False,
                "provider_id": p["id"],
                "raw_count": 0,
                "valid_count": 0,
                "error": str(exc),
            }
        results.append(result)
        _record_run(
            provider_id=p["id"],
            provider_name=p.get("name"),
            job_type='refresh',
            status='success' if result.get('ok') else 'error',
            raw_count=int(result.get('raw_count') or 0),
            valid_count=int(result.get('valid_count') or 0),
            message=result.get('error') or 'ok',
            started_at=started,
            finished_at=_db.now_iso(),
            duration_ms=int((time.perf_counter() - t0) * 1000),
        )
    return {
        "ok": True,
        "provider_count": len(providers),
        "results": results,
    }


def is_running() -> bool:
    return _provider_scheduler is not None and _provider_scheduler.running


def get_next_run_times(limit: int = 20) -> list[dict]:
    if not _provider_scheduler or not _provider_scheduler.running:
        return []
    jobs = _provider_scheduler.get_jobs()
    return [
        {
            "id": j.id,
            "name": j.name,
            "next_run": j.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if j.next_run_time else None,
        }
        for j in jobs[:limit]
    ]

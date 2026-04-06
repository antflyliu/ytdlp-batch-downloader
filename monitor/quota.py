"""
monitor.quota — YouTube API Quota 追踪模块
按 API Key + 日期追踪 API 调用次数，支持预算上限和报警

内部使用 SQLAlchemy Core（通过 monitor.database 统一引擎）。
"""
import json
import logging
import urllib.request
from datetime import datetime

from sqlalchemy import select

from monitor.database import (
    get_connection,
    create_all_tables,
    make_upsert,
    t_api_quota_usage,
)

_log = logging.getLogger("monitor.quota")


# ── 数据库 schema ───────────────────────────────────────────────

def _ensure_schema():
    """确保 api_quota_usage 表存在。

    由 create_all_tables() 处理全部表创建，此函数仅作为向后兼容入口。
    """
    create_all_tables()


# ── 工具 ───────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


# ── 核心 API ───────────────────────────────────────────────────

def get_usage(api_key_value: str, date_key: str | None = None) -> dict:
    """获取某 API Key 某日的 quota 使用情况"""
    date_key = date_key or _today()
    aqu = t_api_quota_usage
    with get_connection() as conn:
        row = conn.execute(
            select(aqu).where(
                (aqu.c.api_key_value == api_key_value)
                & (aqu.c.date_key == date_key)
            )
        ).mappings().fetchone()
        if row:
            return dict(row)
        return {
            "api_key_value": api_key_value,
            "date_key": date_key,
            "api_calls": 0,
            "scans_done": 0,
            "blocked_scans": 0,
            "updated_at": None,
        }


def get_all_usage(date_key: str | None = None) -> list[dict]:
    """获取所有 API Key 今日的使用情况"""
    date_key = date_key or _today()
    aqu = t_api_quota_usage
    with get_connection() as conn:
        rows = conn.execute(
            select(aqu)
            .where(aqu.c.date_key == date_key)
            .order_by(aqu.c.api_calls.desc())
        ).mappings().all()
        return [dict(r) for r in rows]


def incr(api_key_value: str, calls: int = 1, scans: int = 0) -> None:
    """增加 API 调用计数（当日）"""
    today = _today()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    stmt = make_upsert(
        t_api_quota_usage,
        index_elements=["api_key_value", "date_key"],
        update_columns=["api_calls", "scans_done", "updated_at"],
    )
    try:
        with get_connection() as conn:
            # 先检查是否存在
            aqu = t_api_quota_usage
            row = conn.execute(
                select(aqu.c.api_calls, aqu.c.scans_done).where(
                    (aqu.c.api_key_value == api_key_value)
                    & (aqu.c.date_key == today)
                )
            ).fetchone()
            if row:
                existing_calls, existing_scans = row
                conn.execute(
                    aqu.update()
                    .where(
                        (aqu.c.api_key_value == api_key_value)
                        & (aqu.c.date_key == today)
                    )
                    .values(
                        api_calls=existing_calls + calls,
                        scans_done=existing_scans + scans,
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    aqu.insert().values(
                        api_key_value=api_key_value,
                        date_key=today,
                        api_calls=calls,
                        scans_done=scans,
                        blocked_scans=0,
                        updated_at=now,
                    )
                )
    except Exception as e:
        _log.warning("incr 失败: %s", e)


def incr_blocked(api_key_value: str) -> None:
    """增加被阻止的扫描次数"""
    today = _today()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    aqu = t_api_quota_usage
    try:
        with get_connection() as conn:
            row = conn.execute(
                select(aqu.c.blocked_scans).where(
                    (aqu.c.api_key_value == api_key_value)
                    & (aqu.c.date_key == today)
                )
            ).fetchone()
            if row:
                conn.execute(
                    aqu.update()
                    .where(
                        (aqu.c.api_key_value == api_key_value)
                        & (aqu.c.date_key == today)
                    )
                    .values(blocked_scans=row[0] + 1, updated_at=now)
                )
            else:
                conn.execute(
                    aqu.insert().values(
                        api_key_value=api_key_value,
                        date_key=today,
                        api_calls=0,
                        scans_done=0,
                        blocked_scans=1,
                        updated_at=now,
                    )
                )
    except Exception as e:
        _log.warning("incr_blocked 失败: %s", e)


def check_budget(api_key_value: str, budget: int) -> tuple[bool, dict]:
    """检查是否允许扫描

    :return: (allowed, usage_info)
             allowed=False 表示已达上限
    """
    usage = get_usage(api_key_value)
    allowed = usage["api_calls"] < budget
    return allowed, usage


def get_budget_limit(api_key: str) -> int:
    """获取指定 API Key 的每日预算上限。
    优先级：api_keys 表中的 per-key 配额 > config 中的全局配额。
    """
    try:
        import monitor.db as _db

        ak = _db.get_api_key_by_value(api_key)
        if ak:
            return ak.get("daily_quota", 8000)
        cfg = _db.load_config()
        return cfg.get("quota_budget_per_day", 8000)
    except Exception:
        return 8000


def _mask_key(key: str) -> str:
    """返回 API Key 掩码版本（首4+末4字符）"""
    if len(key) <= 12:
        return key[:4] + "••••••"
    return key[:4] + "••••••••" + key[-4:]


def send_alert(
    api_key_value: str,
    usage: dict,
    budget: int,
    webhook_url: str | None,
) -> None:
    """发送 quota 耗尽报警"""
    if not webhook_url:
        return
    percent = int(usage["api_calls"] / budget * 100) if budget > 0 else 100
    msg = {
        "msg_type": "text",
        "content": {
            "text": (
                f"⚠️ YouTube API Quota 预警\n\n"
                f"API Key: `{_mask_key(api_key_value)}`\n"
                f"今日已用: {usage['api_calls']} / {budget} ({percent}%)\n"
                f"扫描次数: {usage['scans_done']} 次\n"
                f"已阻止: {usage['blocked_scans']} 次\n"
                f"时间: {usage.get('updated_at', 'N/A')}"
            )
        },
    }
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(msg, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info("quota 报警已发送: %s", resp.status)
    except Exception as e:
        _log.warning("发送 quota 报警失败: %s", e)

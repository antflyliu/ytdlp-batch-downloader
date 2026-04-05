"""
monitor.quota — YouTube API Quota 追踪模块
按 API Key + 日期追踪 API 调用次数，支持预算上限和报警
"""
import logging
import os
import sys
import sqlite3
from datetime import datetime
from typing import Literal

# ── 路径（与 db.py 保持一致）────────────────────────────────────
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _PKG_DIR

_DATA_DIR = os.path.join(_EXE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

_DB_PATH = os.path.join(_DATA_DIR, "monitor.db")
_log = logging.getLogger("monitor.quota")

# ── 数据库 schema ───────────────────────────────────────────────
def _ensure_schema():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_quota_usage (
                api_key_value  TEXT NOT NULL,
                date_key       TEXT NOT NULL,
                api_calls      INTEGER DEFAULT 0,
                scans_done     INTEGER DEFAULT 0,
                blocked_scans  INTEGER DEFAULT 0,
                updated_at     TEXT NOT NULL,
                PRIMARY KEY (api_key_value, date_key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_quota_date
            ON api_quota_usage(date_key)
        """)
        conn.commit()
    except Exception as e:
        _log.warning(f"_ensure_schema 失败: {e}")
    finally:
        conn.close()

_ensure_schema()


# ── 工具 ───────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


# ── 核心 API ───────────────────────────────────────────────────

def get_usage(api_key_value: str, date_key: str | None = None) -> dict:
    """获取某 API Key 某日的 quota 使用情况"""
    date_key = date_key or _today()
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM api_quota_usage WHERE api_key_value=? AND date_key=?",
            (api_key_value, date_key),
        ).fetchone()
        return dict(row) if row else {
            "api_key_value": api_key_value,
            "date_key": date_key,
            "api_calls": 0,
            "scans_done": 0,
            "blocked_scans": 0,
            "updated_at": None,
        }
    finally:
        conn.close()


def get_all_usage(date_key: str | None = None) -> list[dict]:
    """获取所有 API Key 今日的使用情况"""
    date_key = date_key or _today()
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM api_quota_usage WHERE date_key=? ORDER BY api_calls DESC",
            (date_key,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def incr(api_key_value: str, calls: int = 1, scans: int = 0) -> None:
    """增加 API 调用计数（当日）"""
    today = _today()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.execute("""
            INSERT INTO api_quota_usage
                (api_key_value, date_key, api_calls, scans_done, blocked_scans, updated_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(api_key_value, date_key) DO UPDATE SET
                api_calls = api_calls + excluded.api_calls,
                scans_done = scans_done + excluded.scans_done,
                updated_at = excluded.updated_at
        """, (api_key_value, today, calls, scans, now))
        conn.commit()
    except Exception as e:
        _log.warning(f"incr 失败: {e}")
    finally:
        conn.close()


def incr_blocked(api_key_value: str) -> None:
    """增加被阻止的扫描次数"""
    today = _today()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.execute("""
            INSERT INTO api_quota_usage
                (api_key_value, date_key, api_calls, scans_done, blocked_scans, updated_at)
            VALUES (?, ?, 0, 0, 1, ?)
            ON CONFLICT(api_key_value, date_key) DO UPDATE SET
                blocked_scans = blocked_scans + 1,
                updated_at = excluded.updated_at
        """, (api_key_value, today, now))
        conn.commit()
    except Exception as e:
        _log.warning(f"incr_blocked 失败: {e}")
    finally:
        conn.close()


def check_budget(api_key_value: str, budget: int) -> tuple[bool, dict]:
    """
    检查是否允许扫描
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
        # 先查 api_keys 表（per-key 配额）
        ak = _db.get_api_key_by_value(api_key)
        if ak:
            return ak.get("daily_quota", 8000)
        # 兜底：全局配置
        cfg = _db.load_config()
        return cfg.get("quota_budget_per_day", 8000)
    except Exception:
        return 8000  # 默认 8000


def _mask_key(key: str) -> str:
    """返回 API Key 掩码版本（首4+末4字符）"""
    if len(key) <= 12:
        return key[:4] + "••••••"
    return key[:4] + "••••••••" + key[-4:]


def send_alert(api_key_value: str, usage: dict, budget: int, webhook_url: str | None) -> None:
    """发送 quota 耗尽报警"""
    if not webhook_url:
        return
    import json
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
        }
    }
    try:
        import urllib.request
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(msg, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info(f"quota 报警已发送: {resp.status}")
    except Exception as e:
        _log.warning(f"发送 quota 报警失败: {e}")

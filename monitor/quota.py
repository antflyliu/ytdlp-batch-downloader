"""
monitor.quota — YouTube API Quota 追踪模块
按 API Key + 日期追踪配额单位（Quota units，非裸 HTTP 次数），支持预算上限和报警。
api_quota_usage.api_calls 列存的是累计 units（如 search.list 计 100）。
"""
import logging
import os
import sys
import sqlite3
import time
from datetime import datetime
from typing import Literal

# ── 路径（与 db.py 保持一致）────────────────────────────────────
from utils.paths import get_pkg_dir, get_exe_dir, get_data_dir, get_db_path

_PKG_DIR = get_pkg_dir()
_EXE_DIR = get_exe_dir()
_DATA_DIR = get_data_dir()
_DB_PATH = get_db_path()
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

# 读配置用于配额「统计日」：incr 热路径避免每次磁盘 IO，save_config 后应 invalidate
_config_cache_for_quota: dict | None = None
_config_cache_mono: float = 0.0
_CONFIG_CACHE_TTL_SEC = 5.0
_invalid_quota_tz_logged: set[str] = set()


def invalidate_config_cache() -> None:
    """配置变更后调用，使配额统计日使用最新 quota_usage_timezone。"""
    global _config_cache_for_quota, _config_cache_mono
    _config_cache_for_quota = None
    _config_cache_mono = 0.0


def _load_config_for_quota() -> dict:
    global _config_cache_for_quota, _config_cache_mono
    now = time.monotonic()
    if (
        _config_cache_for_quota is not None
        and (now - _config_cache_mono) < _CONFIG_CACHE_TTL_SEC
    ):
        return _config_cache_for_quota
    try:
        import monitor.db as _db

        _config_cache_for_quota = _db.load_config()
    except Exception:
        _config_cache_for_quota = {}
    _config_cache_mono = now
    return _config_cache_for_quota


def validate_quota_usage_timezone(raw: str | None) -> tuple[bool, str | None]:
    """
    校验配置中的配额统计时区。
    返回 (是否合法, 错误说明)；合法时第二项为 None。
    空/local/localtime 表示本地时区，合法。
    """
    if raw is None:
        return True, None
    s = str(raw).strip()
    if s in ("", "local", "localtime"):
        return True, None
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(s)
    except Exception:
        return (
            False,
            f"无效的 quota_usage_timezone: {raw!r}（请使用 IANA 名称，例如 America/Los_Angeles）",
        )
    return True, None


# ── 工具 ───────────────────────────────────────────────────────

def _quota_date_key() -> str:
    """统计用日历日。默认本地时区；可在配置中设 quota_usage_timezone=America/Los_Angeles 与 Google 控制台对齐。"""
    cfg = _load_config_for_quota()
    tz_name = (cfg or {}).get("quota_usage_timezone") or "local"
    if tz_name in ("", "local", "localtime"):
        return datetime.now().astimezone().strftime("%Y-%m-%d")
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        if tz_name not in _invalid_quota_tz_logged:
            _invalid_quota_tz_logged.add(tz_name)
            _log.warning("quota_usage_timezone 无效，回退本地时区: %s", tz_name)
        return datetime.now().astimezone().strftime("%Y-%m-%d")


def get_quota_date_key() -> str:
    """供调度器等模块获取当前配额统计日（与 incr/check 使用同一规则）。"""
    return _quota_date_key()


# ── 核心 API ───────────────────────────────────────────────────

def get_usage(api_key_value: str, date_key: str | None = None) -> dict:
    """获取某 API Key 某日的 quota 使用情况"""
    date_key = date_key or _quota_date_key()
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
    date_key = date_key or _quota_date_key()
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
    today = _quota_date_key()
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
    today = _quota_date_key()
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


def build_quota_alert_payload(
    platform: str,
    api_key_value: str,
    usage: dict,
    budget: int,
) -> dict:
    """
    按通知平台构造 Quota 告警 JSON 体（与 notifier 各机器人协议一致）。
    platform: feishu | dingtalk | wecom
    """
    percent = int(usage["api_calls"] / budget * 100) if budget > 0 else 100
    text = (
        f"[预警] YouTube API Quota\n\n"
        f"API Key: `{_mask_key(api_key_value)}`\n"
        f"今日已用配额单位: {usage['api_calls']} / {budget} ({percent}%)\n"
        f"（units，非 HTTP 次数；search.list≈100 units/次）\n"
        f"扫描次数: {usage['scans_done']} 次\n"
        f"已阻止: {usage['blocked_scans']} 次\n"
        f"时间: {usage.get('updated_at', 'N/A')}"
    )
    if platform == "dingtalk":
        return {"msgtype": "text", "text": {"content": text}}
    if platform == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    if platform == "telegram":
        return {"text": text, "parse_mode": "MarkdownV2"}
    # feishu 及未知平台：飞书 webhook v2 文本
    return {"msg_type": "text", "content": {"text": text}}


def send_alert(
    api_key_value: str,
    usage: dict,
    budget: int,
    webhook_url: str | None,
    *,
    platform: str = "feishu",
    dingtalk_sign_secret: str | None = None,
    telegram_chat_id: str | None = None,
) -> None:
    """发送 Quota 预警/耗尽告警。消息体按 platform 区分；钉钉 URL 支持加签。"""
    if not webhook_url:
        return
    import json

    from monitor import notifier as _notifier

    post_url = webhook_url
    if platform == "dingtalk":
        post_url = _notifier.finalize_dingtalk_webhook_url(webhook_url, dingtalk_sign_secret)
    elif platform == "telegram":
        # webhook_url 在 Telegram 场景下是 Bot Token，需构造完整 API URL
        post_url = f"https://api.telegram.org/bot{webhook_url}/sendMessage"

    msg = build_quota_alert_payload(platform, api_key_value, usage, budget)
    # Telegram：注入 chat_id
    if platform == "telegram" and telegram_chat_id:
        msg = {**msg, "chat_id": telegram_chat_id}
    try:
        import urllib.request
        req = urllib.request.Request(
            post_url,
            data=json.dumps(msg, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info(f"quota 报警已发送: {resp.status}")
    except Exception as e:
        _log.warning(f"发送 quota 报警失败: {e}")


def send_scan_error_alert(
    account_name: str,
    channel_url: str,
    error_message: str,
    webhook_url: str | None,
    *,
    platform: str = "feishu",
    dingtalk_sign_secret: str | None = None,
    telegram_chat_id: str | None = None,
) -> None:
    """扫描失败时发送纯文本告警（与 Quota 告警共用 Webhook 投递方式）。

    正文含账户名、频道 URL、错误摘要（最多 2000 字）；若 Webhook 经第三方或不可信网络，请自行评估暴露面。
    """
    if not webhook_url:
        return
    import json
    from datetime import datetime as _dt

    from monitor import notifier as _notifier

    post_url = webhook_url
    if platform == "dingtalk":
        post_url = _notifier.finalize_dingtalk_webhook_url(webhook_url, dingtalk_sign_secret)
    elif platform == "telegram":
        # webhook_url 在 Telegram 场景下是 Bot Token，需构造完整 API URL
        post_url = f"https://api.telegram.org/bot{webhook_url}/sendMessage"

    now = _dt.now().astimezone().isoformat(timespec="seconds")
    text = (
        f"[异常] 频道扫描失败\n\n"
        f"账户: {account_name}\n"
        f"频道: {channel_url}\n"
        f"错误: {error_message[:2000]}\n"
        f"时间: {now}"
    )
    if platform == "dingtalk":
        msg = {"msgtype": "text", "text": {"content": text}}
    elif platform == "wecom":
        msg = {"msgtype": "text", "text": {"content": text}}
    elif platform == "telegram":
        msg = {"text": text, "parse_mode": "MarkdownV2"}
    else:
        msg = {"msg_type": "text", "content": {"text": text}}

    try:
        import urllib.request
        req_body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        if platform == "telegram" and telegram_chat_id:
            req_body = json.dumps({**msg, "chat_id": telegram_chat_id}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            post_url,
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info(f"扫描失败告警已发送: {resp.status}")
    except Exception as e:
        _log.warning(f"发送扫描失败告警失败: {e}")


def send_channel_meta_mismatch_alert(
    channel_url: str,
    channel_id: str,
    cached_uploads_playlist_id: str | None,
    live_uploads_playlist_id: str | None,
) -> None:
    """
    频道元数据缓存中的 uploads_playlist_id 与线上一致性校验不一致时告警。
    使用全局 Webhook（飞书 → 钉钉 → 企微 优先顺序）。

    正文含频道 URL、channel_id、列表 ID；Webhook 渠道请按需限制访问。
    """
    try:
        import monitor.db as _db
        cfg = _db.load_config()
    except Exception:
        return
    if not cfg.get("notify_on_channel_meta_mismatch", True):
        return

    webhook_url = None
    platform = "feishu"
    dingtalk_sign_secret = None
    if cfg.get("global_feishu_url"):
        webhook_url = cfg.get("global_feishu_url")
        platform = "feishu"
    elif cfg.get("global_dingtalk_url"):
        webhook_url = cfg.get("global_dingtalk_url")
        platform = "dingtalk"
        dingtalk_sign_secret = cfg.get("global_dingtalk_sign_secret") or None
    elif cfg.get("global_wecom_url"):
        webhook_url = cfg.get("global_wecom_url")
        platform = "wecom"
    elif cfg.get("global_telegram_token"):
        webhook_url = cfg.get("global_telegram_token")
        platform = "telegram"

    if not webhook_url:
        _log.warning("channel_meta 不一致告警：未配置全局 Webhook，跳过")
        return

    import json
    from datetime import datetime as _dt

    from monitor import notifier as _notifier

    post_url = webhook_url
    if platform == "dingtalk":
        post_url = _notifier.finalize_dingtalk_webhook_url(webhook_url, dingtalk_sign_secret)
    elif platform == "telegram":
        # webhook_url 在 Telegram 场景下是 Bot Token，需构造完整 API URL
        post_url = f"https://api.telegram.org/bot{webhook_url}/sendMessage"

    # Telegram：注入 chat_id
    chat_id = None
    if platform == "telegram":
        chat_id = cfg.get("global_telegram_chat_id")

    now = _dt.now().astimezone().isoformat(timespec="seconds")
    text = (
        "[告警] 频道元数据 uploads 列表不一致\n\n"
        f"频道 URL: {channel_url}\n"
        f"channel_id: {channel_id}\n"
        f"缓存 uploads_playlist_id: {cached_uploads_playlist_id!r}\n"
        f"线上一致结果: {live_uploads_playlist_id!r}\n"
        "已触发重新拉取并写回 SQLite。\n"
        f"时间: {now}"
    )
    if platform == "dingtalk":
        msg = {"msgtype": "text", "text": {"content": text}}
    elif platform == "wecom":
        msg = {"msgtype": "text", "text": {"content": text}}
    elif platform == "telegram":
        msg = {"text": text, "parse_mode": "MarkdownV2"}
    else:
        msg = {"msg_type": "text", "content": {"text": text}}

    try:
        import urllib.request
        req_headers = {"Content-Type": "application/json"}
        req_body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        if platform == "telegram" and chat_id:
            # Telegram：chat_id 作为 query 参数，body 中也有一份
            req_body = json.dumps({**msg, "chat_id": chat_id}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            post_url,
            data=req_body,
            headers=req_headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info(f"channel_meta 不一致告警已发送: {resp.status}")
    except Exception as e:
        _log.warning(f"发送 channel_meta 不一致告警失败: {e}")

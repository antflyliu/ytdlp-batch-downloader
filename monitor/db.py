"""
monitor.db — Monitor 数据库初始化与访问助手

内部使用 SQLAlchemy Core 实现跨数据库方言兼容
（SQLite / PostgreSQL / MySQL），对外 API 保持 dict 风格不变。
"""
import json
import os
import sys
from datetime import datetime

import logging_config

_log = logging_config.get_logger("monitor.db")

from sqlalchemy import select, func, and_, case, text, inspect

from monitor.database import (
    get_connection,
    get_engine,
    get_dialect_name,
    create_all_tables,
    make_insert_ignore,
    make_upsert,
    t_api_keys,
    t_monitor_accounts,
    t_monitor_events,
    t_monitor_videos,
    t_app_state,
    t_schema_migrations,
    DEFAULT_DB_PATH,
)

# 哨兵值：区分 update_account 中「参数未传入」和「显式传 None 清空字段」
_UNSET = type(
    "_Unset", (), {"__repr__": lambda s: "<UNSET>", "__bool__": lambda s: False}
)()

# ── PyInstaller 兼容路径 ──────────────────────────────────────
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _PKG_DIR

_DATA_DIR = os.path.dirname(DEFAULT_DB_PATH)
_CONFIG_PATH = os.path.join(_EXE_DIR, "config.json")

_GLOBAL_WEBHOOK_KEYS = (
    "global_feishu_url",
    "global_dingtalk_url",
    "global_wecom_url",
)


# ══════════════════════════════════════════════════════════════════════
# 配置文件 I/O（非数据库，文件级操作，不受方言影响）
# ══════════════════════════════════════════════════════════════════════


def _write_config(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _encrypt_config_webhooks(cfg: dict) -> dict:
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _encrypt_webhook(cfg.get(key)) or ""
    return cfg


def _decrypt_config_webhooks(cfg: dict) -> dict:
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _decrypt_webhook(cfg.get(key)) or ""
    return cfg


def _config_default() -> dict:
    """默认的全局配置"""
    return {
        "global_feishu_url": "",
        "global_dingtalk_url": "",
        "global_wecom_url": "",
        "default_fetch_mode": "playlist",
        "default_fetch_limit": 5,
        "default_scan_interval": 5,
        "quota_budget_per_day": 8000,
        "download_cookies_file": "",
        "download_output_path": "",
        "default_sub_langs": "zh-Hans,en",
        "default_api_key_id": None,
    }


def get_db_path() -> str:
    return DEFAULT_DB_PATH


def get_config_path() -> str:
    """返回 config.json 路径（优先 exe 同目录下，用户可写）"""
    return _CONFIG_PATH


def load_config() -> dict:
    """加载全局配置（支持 PyInstaller exe 和源码两种模式）"""
    source_path = None
    raw_cfg = None
    if os.path.exists(_CONFIG_PATH):
        source_path = _CONFIG_PATH
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw_cfg = json.load(f)
    else:
        pkg_cfg = os.path.join(_PKG_DIR, "config.json")
        if os.path.exists(pkg_cfg):
            source_path = pkg_cfg
            with open(pkg_cfg, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
    if raw_cfg is None:
        return _config_default()

    raw_cfg = {**_config_default(), **raw_cfg}
    encrypted_cfg = _encrypt_config_webhooks(raw_cfg)
    if source_path and encrypted_cfg != raw_cfg:
        _write_config(source_path, encrypted_cfg)
    return _decrypt_config_webhooks(raw_cfg)


def save_config(cfg: dict) -> None:
    """保存全局配置，Webhook URL 落盘时加密。"""
    _write_config(_CONFIG_PATH, _encrypt_config_webhooks(cfg))


# ══════════════════════════════════════════════════════════════════════
# 数据库初始化与迁移（将被 Alembic 替代）
# ══════════════════════════════════════════════════════════════════════


def init_db() -> None:
    """初始化数据库，创建表（如不存在）+ 执行手动迁移。"""
    create_all_tables()
    with get_connection() as conn:
        _migrate_monitor_accounts(conn)
    # 兼容：确保 quota 表存在（cache.py/quota.py 的模块级创建在 SQLite
    # 场景下是冗余但无害的；非 SQLite 场景靠 create_all_tables() 覆盖）
    if get_dialect_name() == "sqlite":
        import monitor.quota as _quota
        _quota._ensure_schema()


def _migrate_monitor_accounts(conn) -> None:
    """对老数据库迁移补列（基于 schema_migrations 版本追踪，幂等）。

    这些迁移将在 Alembic 接管后移除。
    """
    insp = inspect(conn)
    today = _today_str()

    applied: set[str] = set()
    if insp.has_table("schema_migrations"):
        rows = conn.execute(select(t_schema_migrations.c.version)).all()
        applied = {r[0] for r in rows}

    record_stmt = make_insert_ignore(t_schema_migrations, index_elements=["version"])

    # v1: api_key_id 列
    if "v1_api_key_id" not in applied:
        cols = {c["name"] for c in insp.get_columns("monitor_accounts")}
        if "api_key_id" not in cols:
            conn.execute(
                text("ALTER TABLE monitor_accounts ADD COLUMN api_key_id INTEGER DEFAULT NULL")
            )
            _migrate_legacy_api_keys(conn)
        conn.execute(record_stmt, {"version": "v1_api_key_id", "applied_at": today})

    # v2: feishu 扩展列
    if "v2_feishu_ext" not in applied:
        cols = {c["name"] for c in insp.get_columns("monitor_accounts")}
        for col, ddl in [
            ("feishu_message_mode", "TEXT NOT NULL DEFAULT 'card_json'"),
            ("feishu_template_id", "TEXT"),
            ("feishu_scan_template_id", "TEXT"),
        ]:
            if col not in cols:
                conn.execute(text(f"ALTER TABLE monitor_accounts ADD COLUMN {col} {ddl}"))
        conn.execute(record_stmt, {"version": "v2_feishu_ext", "applied_at": today})

    # v3: api_quota_usage.api_key_env → api_key_value 列重命名
    if "v3_quota_col_rename" not in applied:
        if insp.has_table("api_quota_usage"):
            cols = {c["name"] for c in insp.get_columns("api_quota_usage")}
            if "api_key_env" in cols and "api_key_value" not in cols:
                conn.execute(
                    text("ALTER TABLE api_quota_usage RENAME COLUMN api_key_env TO api_key_value")
                )
        conn.execute(record_stmt, {"version": "v3_quota_col_rename", "applied_at": today})

    # v4: webhook_url 加密（明文 → enc:... 格式）
    if "v4_webhook_encrypt" not in applied:
        ma = t_monitor_accounts
        rows = conn.execute(
            select(ma.c.id, ma.c.webhook_url).where(
                and_(
                    ma.c.webhook_url.isnot(None),
                    ma.c.webhook_url != "",
                    ~ma.c.webhook_url.startswith("enc:"),
                )
            )
        ).all()
        for acct_id, url in rows:
            if url and not url.startswith("enc:"):
                encrypted = _encrypt_webhook(url)
                conn.execute(
                    ma.update().where(ma.c.id == acct_id).values(webhook_url=encrypted)
                )
        conn.execute(record_stmt, {"version": "v4_webhook_encrypt", "applied_at": today})

    # v5: 添加分页覆盖索引
    if "v5_video_pagination_index" not in applied:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_videos_account_published "
                "ON monitor_videos(account_id, published_at DESC)"
            )
        )
        conn.execute(record_stmt, {"version": "v5_video_pagination_index", "applied_at": today})


def _migrate_legacy_api_keys(conn) -> None:
    """从已有的 monitor_accounts.api_key_env 环境变量名迁移 Key 到 api_keys 表"""
    ma = t_monitor_accounts
    rows = conn.execute(
        select(ma.c.api_key_env).where(ma.c.api_key_env.isnot(None)).distinct()
    ).all()
    stmt = make_insert_ignore(t_api_keys, index_elements=["key_value"])
    for (env_name,) in rows:
        key_value = os.environ.get(env_name, "")
        if key_value:
            try:
                conn.execute(stmt, {
                    "key_value": key_value,
                    "name": env_name,
                    "daily_quota": 10000,
                    "quota_used": 0,
                    "quota_reset_at": _today_str(),
                    "is_active": 1,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })
            except Exception as exc:
                _log.warning("Migration: 迁移 api_key_env=%s 失败: %s", env_name, exc)


# ══════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════


def now_iso() -> str:
    """当前本地时间的 ISO 8601 字符串（含时区偏移，如 +08:00）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today_str() -> str:
    """当前本地日期字符串 (YYYY-MM-DD)。"""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════
# api_keys CRUD
# ══════════════════════════════════════════════════════════════════════


def list_api_keys() -> list[dict]:
    """列出所有 API Key（含今日配额使用情况）"""
    today = _today_str()
    ak = t_api_keys
    from monitor.database import t_api_quota_usage as aqu

    stmt = (
        select(
            ak.c.id,
            ak.c.key_value,
            ak.c.name,
            ak.c.daily_quota,
            func.coalesce(aqu.c.api_calls, 0).label("quota_used"),
            ak.c.quota_reset_at,
            ak.c.is_active,
            ak.c.created_at,
            ak.c.updated_at,
            aqu.c.scans_done,
            aqu.c.blocked_scans,
        )
        .outerjoin(
            aqu,
            and_(
                aqu.c.api_key_value == ak.c.key_value,
                aqu.c.date_key == today,
            ),
        )
        .order_by(ak.c.id)
    )
    with get_connection() as conn:
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]


def get_api_key(key_id: int) -> dict | None:
    """获取单个 API Key"""
    with get_connection() as conn:
        row = conn.execute(
            select(t_api_keys).where(t_api_keys.c.id == key_id)
        ).mappings().fetchone()
        return dict(row) if row else None


def get_api_key_by_value(key_value: str) -> dict | None:
    """通过 Key 值查找"""
    with get_connection() as conn:
        row = conn.execute(
            select(t_api_keys).where(t_api_keys.c.key_value == key_value)
        ).mappings().fetchone()
        return dict(row) if row else None


def add_api_key(
    key_value: str,
    name: str,
    daily_quota: int = 10000,
) -> int:
    """新增 API Key，返回新记录 ID"""
    today = _today_str()
    with get_connection() as conn:
        result = conn.execute(
            t_api_keys.insert().values(
                key_value=key_value,
                name=name,
                daily_quota=daily_quota,
                quota_used=0,
                quota_reset_at=today,
                is_active=1,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        return result.inserted_primary_key[0]


def update_api_key(
    key_id: int,
    name: str | None = None,
    key_value: str | None = None,
    daily_quota: int | None = None,
    is_active: bool | None = None,
) -> None:
    """更新 API Key"""
    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if key_value:
        updates["key_value"] = key_value
    if daily_quota is not None:
        updates["daily_quota"] = daily_quota
    if is_active is not None:
        updates["is_active"] = int(is_active)
    updates["updated_at"] = now_iso()
    with get_connection() as conn:
        conn.execute(
            t_api_keys.update().where(t_api_keys.c.id == key_id).values(**updates)
        )


def delete_api_key(key_id: int) -> None:
    """删除 API Key（关联的账户 api_key_id 会被 SET NULL）"""
    with get_connection() as conn:
        conn.execute(t_api_keys.delete().where(t_api_keys.c.id == key_id))


def incr_api_key_quota(key_value: str, calls: int = 1, scans: int = 0) -> None:
    """增加 API Key 的配额使用"""
    import monitor.quota as _quota
    _quota.incr(key_value, calls=calls, scans=scans)


# ══════════════════════════════════════════════════════════════════════
# monitor_accounts CRUD
# ══════════════════════════════════════════════════════════════════════


def list_accounts(enabled_only: bool = False) -> list[dict]:
    ma = t_monitor_accounts
    stmt = select(ma).order_by(ma.c.id)
    if enabled_only:
        stmt = stmt.where(ma.c.enabled == 1)
    with get_connection() as conn:
        rows = conn.execute(stmt).mappings().all()
        return [_decrypt_account_webhook(dict(r)) for r in rows]


def _decrypt_account_webhook(account: dict) -> dict:
    """解密账户的 webhook_url"""
    if account and account.get("webhook_url"):
        account = dict(account)
        account["webhook_url"] = _decrypt_webhook(account["webhook_url"])
    return account


def get_account(account_id: int) -> dict | None:
    ma = t_monitor_accounts
    with get_connection() as conn:
        row = conn.execute(
            select(ma).where(ma.c.id == account_id)
        ).mappings().fetchone()
        return _decrypt_account_webhook(dict(row)) if row else None


def add_account(
    name: str,
    channel_url: str,
    api_key_env: str,
    fetch_mode: str = "playlist",
    fetch_limit: int = 5,
    scan_interval: int = 5,
    notify_enabled: bool = True,
    notify_platform: str = "feishu",
    webhook_url: str | None = None,
    feishu_message_mode: str = "card_json",
    feishu_template_id: str | None = None,
    feishu_scan_template_id: str | None = None,
    api_key_id: int | None = None,
) -> int:
    with get_connection() as conn:
        result = conn.execute(
            t_monitor_accounts.insert().values(
                name=name,
                channel_url=channel_url,
                api_key_env=api_key_env,
                fetch_mode=fetch_mode,
                fetch_limit=fetch_limit,
                scan_interval=scan_interval,
                enabled=1,
                notify_enabled=int(notify_enabled),
                notify_platform=notify_platform,
                webhook_url=_encrypt_webhook(webhook_url),
                feishu_message_mode=feishu_message_mode,
                feishu_template_id=feishu_template_id,
                feishu_scan_template_id=feishu_scan_template_id,
                api_key_id=api_key_id,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        return result.inserted_primary_key[0]


def update_account(
    account_id: int,
    name: str | None = None,
    channel_url: str | None = None,
    api_key_env: str | None = None,
    fetch_mode: str | None = None,
    fetch_limit: int | None = None,
    scan_interval: int | None = None,
    enabled: bool | None = None,
    notify_enabled: bool | None = None,
    notify_platform: str | None = None,
    webhook_url=_UNSET,
    feishu_message_mode: str | None = None,
    feishu_template_id=_UNSET,
    feishu_scan_template_id=_UNSET,
    api_key_id=_UNSET,
) -> None:
    """更新账户字段。

    对于可空字段（webhook_url / feishu_template_id / feishu_scan_template_id / api_key_id），
    使用 _UNSET 表示「不修改」，传 None 表示「清空为 NULL」。
    """
    updates: dict = {}
    if name is not None:
        updates["name"] = name
    if channel_url is not None:
        updates["channel_url"] = channel_url
    if api_key_env is not None:
        updates["api_key_env"] = api_key_env
    if fetch_mode is not None:
        updates["fetch_mode"] = fetch_mode
    if fetch_limit is not None:
        updates["fetch_limit"] = fetch_limit
    if scan_interval is not None:
        updates["scan_interval"] = scan_interval
    if enabled is not None:
        updates["enabled"] = int(enabled)
    if notify_enabled is not None:
        updates["notify_enabled"] = int(notify_enabled)
    if notify_platform is not None:
        updates["notify_platform"] = notify_platform
    if webhook_url is not _UNSET:
        updates["webhook_url"] = _encrypt_webhook(webhook_url)
    if feishu_message_mode is not None:
        updates["feishu_message_mode"] = feishu_message_mode
    if feishu_template_id is not _UNSET:
        updates["feishu_template_id"] = feishu_template_id
    if feishu_scan_template_id is not _UNSET:
        updates["feishu_scan_template_id"] = feishu_scan_template_id
    if api_key_id is not _UNSET:
        updates["api_key_id"] = api_key_id
    updates["updated_at"] = now_iso()

    ma = t_monitor_accounts
    with get_connection() as conn:
        conn.execute(ma.update().where(ma.c.id == account_id).values(**updates))


def delete_account(account_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            t_monitor_accounts.delete().where(t_monitor_accounts.c.id == account_id)
        )


# ══════════════════════════════════════════════════════════════════════
# monitor_events CRUD
# ══════════════════════════════════════════════════════════════════════


def create_event(account_id: int, account_name: str) -> int:
    with get_connection() as conn:
        result = conn.execute(
            t_monitor_events.insert().values(
                account_id=account_id,
                account_name=account_name,
                scan_started_at=now_iso(),
                status="running",
                total_videos=0,
                new_videos=0,
            )
        )
        return result.inserted_primary_key[0]


def finish_event(
    event_id: int,
    status: str,
    total_videos: int,
    new_videos: int,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    me = t_monitor_events
    with get_connection() as conn:
        conn.execute(
            me.update()
            .where(me.c.id == event_id)
            .values(
                scan_ended_at=now_iso(),
                status=status,
                total_videos=total_videos,
                new_videos=new_videos,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        )


# ══════════════════════════════════════════════════════════════════════
# monitor_videos CRUD
# ══════════════════════════════════════════════════════════════════════


def insert_videos(
    videos: list[dict],
    account_id: int,
    event_id: int,
) -> int:
    """批量插入视频，返回实际插入数量（UNIQUE 冲突的会被忽略）"""
    if not videos:
        return 0
    now = now_iso()
    stmt = make_insert_ignore(t_monitor_videos, index_elements=["video_id"])
    data = [
        {
            "video_id": v["video_id"],
            "account_id": account_id,
            "event_id": event_id,
            "channel_id": v.get("channel_id"),
            "channel_handle": v.get("channel_handle"),
            "title": v["title"],
            "description": v.get("description", ""),
            "url": v["url"],
            "published_at": v.get("published_at", ""),
            "upload_date": v.get("upload_date"),
            "duration_sec": v.get("duration_sec"),
            "view_count": v.get("view_count"),
            "like_count": v.get("like_count"),
            "comment_count": v.get("comment_count"),
            "thumbnail_url": v.get("thumbnail_url"),
            "fetched_at": v.get("fetched_at", now),
            "notify_status": "pending",
            "created_at": now,
        }
        for v in videos
    ]
    with get_connection() as conn:
        result = conn.execute(stmt, data)
        return result.rowcount


def get_new_video_ids(new_videos: list[dict]) -> set[str]:
    """从新获取的视频列表中，找出不在 monitor_videos 表中的 video_id"""
    if not new_videos:
        return set()
    vid_list = [v["video_id"] for v in new_videos]
    mv = t_monitor_videos
    with get_connection() as conn:
        existing = {
            r[0]
            for r in conn.execute(
                select(mv.c.video_id).where(mv.c.video_id.in_(vid_list))
            ).all()
        }
    return {vid for vid in vid_list if vid not in existing}


def mark_notify_sent(video_ids: list[str], sent_at: str | None = None) -> None:
    if not video_ids:
        return
    sent_at = sent_at or now_iso()
    mv = t_monitor_videos
    with get_connection() as conn:
        conn.execute(
            mv.update()
            .where(mv.c.video_id.in_(video_ids))
            .values(notify_status="sent", notify_sent_at=sent_at)
        )


def mark_notify_failed(video_ids: list[str], error: str) -> None:
    if not video_ids:
        return
    mv = t_monitor_videos
    with get_connection() as conn:
        conn.execute(
            mv.update()
            .where(mv.c.video_id.in_(video_ids))
            .values(notify_status="failed", notify_error=error)
        )


# ══════════════════════════════════════════════════════════════════════
# 统计查询
# ══════════════════════════════════════════════════════════════════════


def get_account_stats() -> list[dict]:
    """返回每个账户的统计：总扫描次数、新视频数、最后扫描时间"""
    ma = t_monitor_accounts
    me = t_monitor_events
    stmt = (
        select(
            ma.c.id,
            ma.c.name,
            ma.c.channel_url,
            ma.c.enabled,
            ma.c.scan_interval,
            ma.c.fetch_limit,
            ma.c.fetch_mode,
            ma.c.notify_enabled,
            func.count(me.c.id).label("total_scans"),
            func.coalesce(func.sum(me.c.new_videos), 0).label("total_new_videos"),
            func.max(me.c.scan_started_at).label("last_scan_at"),
            func.max(case((me.c.status == "running", 1), else_=0)).label("is_running"),
        )
        .outerjoin(me, ma.c.id == me.c.account_id)
        .group_by(
            ma.c.id, ma.c.name, ma.c.channel_url, ma.c.enabled,
            ma.c.scan_interval, ma.c.fetch_limit, ma.c.fetch_mode,
            ma.c.notify_enabled,
        )
        .order_by(ma.c.id)
    )
    with get_connection() as conn:
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]


def get_recent_events(limit: int = 50) -> list[dict]:
    """返回最近的扫描事件"""
    me = t_monitor_events
    ma = t_monitor_accounts
    stmt = (
        select(
            me.c.id,
            me.c.account_id,
            ma.c.name.label("account_name"),
            ma.c.channel_url,
            me.c.scan_started_at,
            me.c.scan_ended_at,
            me.c.status,
            me.c.total_videos,
            me.c.new_videos,
            me.c.error_message,
            me.c.duration_ms,
        )
        .join(ma, me.c.account_id == ma.c.id)
        .order_by(me.c.scan_started_at.desc())
        .limit(limit)
    )
    with get_connection() as conn:
        rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]


def get_pending_notify_videos(event_id: int) -> list[dict]:
    """获取某个事件中待通知的视频"""
    mv = t_monitor_videos
    with get_connection() as conn:
        rows = conn.execute(
            select(mv)
            .where(and_(mv.c.event_id == event_id, mv.c.notify_status == "pending"))
            .order_by(mv.c.published_at.desc())
        ).mappings().all()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════
# 视频查询
# ══════════════════════════════════════════════════════════════════════


def get_account_videos(
    account_id: int,
    title_kw: str | None = None,
    url_kw: str | None = None,
    sort_by: str = "published_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """分页查询账户视频列表，支持搜索和排序

    :return: (videos, total_count)
    """
    mv = t_monitor_videos
    ALLOWED_SORT = {
        "published_at": mv.c.published_at,
        "view_count": mv.c.view_count,
        "like_count": mv.c.like_count,
        "comment_count": mv.c.comment_count,
    }
    order_col = ALLOWED_SORT.get(sort_by, mv.c.published_at)

    conditions = [mv.c.account_id == account_id]
    if title_kw:
        conditions.append(mv.c.title.contains(title_kw, autoescape=True))
    if url_kw:
        conditions.append(mv.c.url.contains(url_kw, autoescape=True))

    where = and_(*conditions)
    order = order_col.desc() if sort_dir == "desc" else order_col.asc()

    with get_connection() as conn:
        total = conn.execute(
            select(func.count()).select_from(mv).where(where)
        ).scalar()

        offset = (page - 1) * page_size
        rows = conn.execute(
            select(
                mv.c.id, mv.c.video_id, mv.c.title, mv.c.description, mv.c.url,
                mv.c.published_at, mv.c.upload_date, mv.c.duration_sec,
                mv.c.view_count, mv.c.like_count, mv.c.comment_count,
                mv.c.notify_status, mv.c.download_status, mv.c.download_at,
                mv.c.download_path, mv.c.fetched_at,
            )
            .where(where)
            .order_by(order)
            .limit(page_size)
            .offset(offset)
        ).mappings().all()
        return [dict(r) for r in rows], total


def update_videos_download_status(
    video_ids: list[int],
    status: str,
    download_at: str | None = None,
    download_path: str | None = None,
    download_error: str | None = None,
) -> int:
    """批量更新视频下载状态"""
    if not video_ids:
        return 0
    updates: dict = {"download_status": status}
    if download_at:
        updates["download_at"] = download_at
    if download_path:
        updates["download_path"] = download_path
    if download_error:
        updates["download_error"] = download_error
    mv = t_monitor_videos
    with get_connection() as conn:
        result = conn.execute(
            mv.update().where(mv.c.id.in_(video_ids)).values(**updates)
        )
        return result.rowcount


def get_videos_by_ids(video_ids: list[int]) -> list[dict]:
    """根据 monitor_videos.id 列表查询视频记录（含 url, title 等）"""
    if not video_ids:
        return []
    mv = t_monitor_videos
    with get_connection() as conn:
        rows = conn.execute(
            select(mv.c.id, mv.c.video_id, mv.c.title, mv.c.url, mv.c.download_status)
            .where(mv.c.id.in_(video_ids))
        ).mappings().all()
        return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════
# 调度状态（存 DB，不用内存变量，避免进程重启丢失）
# ══════════════════════════════════════════════════════════════════════


def get_scheduler_state() -> dict:
    """返回调度器的运行状态"""
    with get_connection() as conn:
        row = conn.execute(
            select(t_app_state.c.value).where(t_app_state.c.key == "scheduler_state")
        ).fetchone()
        if row:
            return json.loads(row[0])
        return {"running": False, "started_at": None}


def set_scheduler_state(state: dict) -> None:
    stmt = make_upsert(
        t_app_state,
        index_elements=["key"],
        update_columns=["value"],
    )
    with get_connection() as conn:
        conn.execute(stmt, {"key": "scheduler_state", "value": json.dumps(state)})


# ══════════════════════════════════════════════════════════════════════
# API Token 管理（REST API 认证）
# ══════════════════════════════════════════════════════════════════════


def get_api_token() -> str:
    """获取 REST API 访问令牌。若 app_state 中无 token 则自动生成并保存。"""
    ensure_app_state_table()
    with get_connection() as conn:
        row = conn.execute(
            select(t_app_state.c.value).where(t_app_state.c.key == "api_token")
        ).fetchone()
        if row:
            return row[0]
    import secrets
    token = secrets.token_hex(20)
    set_api_token(token)
    return token


def set_api_token(token: str) -> None:
    """保存 REST API 访问令牌到 app_state"""
    ensure_app_state_table()
    stmt = make_upsert(
        t_app_state,
        index_elements=["key"],
        update_columns=["value"],
    )
    with get_connection() as conn:
        conn.execute(stmt, {"key": "api_token", "value": token})


# ══════════════════════════════════════════════════════════════════════
# Webhook URL 加密
# ══════════════════════════════════════════════════════════════════════


def _get_webhook_enc_key() -> bytes:
    """获取 Webhook URL 加密密钥（从 app_state 读取，不存在则自动生成）。"""
    from cryptography.fernet import Fernet

    ensure_app_state_table()
    with get_connection() as conn:
        row = conn.execute(
            select(t_app_state.c.value).where(t_app_state.c.key == "webhook_enc_key")
        ).fetchone()
        if row:
            return row[0].encode("utf-8")

    key_str = Fernet.generate_key().decode("utf-8")
    stmt = make_upsert(
        t_app_state,
        index_elements=["key"],
        update_columns=["value"],
    )
    with get_connection() as conn:
        conn.execute(stmt, {"key": "webhook_enc_key", "value": key_str})
    return key_str.encode("utf-8")


def _encrypt_webhook(url: str | None) -> str | None:
    """加密 Webhook URL，明文为空或已加密则原样返回"""
    if not url:
        return None
    if url.startswith("enc:"):
        return url
    from cryptography.fernet import Fernet

    key = _get_webhook_enc_key()
    f = Fernet(key)
    encrypted = f.encrypt(url.encode("utf-8"))
    return "enc:" + encrypted.decode("utf-8")


def _decrypt_webhook(encrypted: str | None) -> str | None:
    """解密 Webhook URL，非加密值或解密失败则原样返回"""
    if not encrypted:
        return None
    if not encrypted.startswith("enc:"):
        return encrypted
    try:
        from cryptography.fernet import Fernet

        key = _get_webhook_enc_key()
        f = Fernet(key)
        return f.decrypt(encrypted[4:].encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted


def ensure_app_state_table() -> None:
    """兼容旧代码：app_state 表已由 create_all_tables() 创建，此函数无操作"""


# ══════════════════════════════════════════════════════════════════════
# 数据库备份（仅 SQLite，保留最近 7 份）
# ══════════════════════════════════════════════════════════════════════


def backup_db() -> str | None:
    """备份 SQLite 数据库到 data/backup/ 目录，保留最近 7 份。
    非 SQLite 后端返回 None。
    """
    if get_dialect_name() != "sqlite":
        _log.warning("backup_db 仅支持 SQLite 后端")
        return None

    import sqlite3

    db_path = DEFAULT_DB_PATH
    if not os.path.exists(db_path):
        return None

    backup_dir = os.path.join(_DATA_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"monitor_{ts}.db")

    try:
        conn_backup = sqlite3.connect(backup_path)
        conn_src = sqlite3.connect(db_path)
        conn_backup.execute("PRAGMA journal_mode=WAL")
        for line in conn_src.iterdump():
            stripped = line.strip()
            if stripped.startswith("CREATE TABLE api_keys") or stripped.startswith(
                "INSERT INTO api_keys"
            ):
                continue
            try:
                conn_backup.execute(line)
            except Exception:
                pass
        conn_backup.commit()
        conn_backup.close()
        conn_src.close()

        existing = sorted(
            f
            for f in os.listdir(backup_dir)
            if f.startswith("monitor_") and f.endswith(".db")
        )
        for old in existing[:-7]:
            os.remove(os.path.join(backup_dir, old))

        return backup_path
    except Exception:
        return None

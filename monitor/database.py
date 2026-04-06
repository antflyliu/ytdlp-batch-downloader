"""
monitor.database — 统一数据库引擎、表定义与跨方言辅助函数

本模块是 monitor 子系统的唯一数据库入口，支持：
  - SQLite（默认，兼容 PyInstaller）
  - PostgreSQL（通过 psycopg 驱动）
  - MySQL（通过 pymysql 驱动）

通过环境变量 MONITOR_DATABASE_URL 切换后端，默认回退到本地 SQLite。
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine as _sa_create_engine,
    event,
    text,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

_log = logging.getLogger("monitor.database")

# ── PyInstaller 兼容路径 ────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _PKG_DIR = os.path.join(sys._MEIPASS, "monitor")
    _EXE_DIR = os.path.dirname(sys.executable)
else:
    _PKG_DIR = os.path.dirname(os.path.abspath(__file__))
    _EXE_DIR = _PKG_DIR

_DATA_DIR = os.path.join(_EXE_DIR, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

DEFAULT_DB_PATH = os.path.join(_DATA_DIR, "monitor.db")


# ══════════════════════════════════════════════════════════════════════
# 表元数据定义（9 张用户表 + 1 张迁移版本表）
# ══════════════════════════════════════════════════════════════════════

metadata = MetaData()

# ── api_keys ──────────────────────────────────────────────────────────

t_api_keys = Table(
    "api_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key_value", String(256), nullable=False, unique=True),
    Column("name", String(256), nullable=False),
    Column("daily_quota", Integer, nullable=False, server_default=text("10000")),
    Column("quota_used", Integer, nullable=False, server_default=text("0")),
    Column("quota_reset_at", String(16), nullable=False),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    sqlite_autoincrement=True,
)
Index("idx_api_keys_active", t_api_keys.c.is_active)

# ── monitor_accounts ─────────────────────────────────────────────────

t_monitor_accounts = Table(
    "monitor_accounts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(256), nullable=False),
    Column("channel_url", String(512), nullable=False),
    Column(
        "api_key_id",
        Integer,
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("api_key_env", String(256), nullable=False),
    Column("fetch_mode", String(32), nullable=False, server_default="playlist"),
    Column("fetch_limit", Integer, nullable=False, server_default=text("5")),
    Column("scan_interval", Integer, nullable=False, server_default=text("5")),
    Column("enabled", Integer, nullable=False, server_default=text("1")),
    Column("notify_enabled", Integer, nullable=False, server_default=text("1")),
    Column("notify_platform", String(32), nullable=False, server_default="feishu"),
    Column("webhook_url", Text, nullable=True),
    Column("feishu_message_mode", String(32), nullable=False, server_default="card_json"),
    Column("feishu_template_id", String(128), nullable=True),
    Column("feishu_scan_template_id", String(128), nullable=True),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    sqlite_autoincrement=True,
)
Index("idx_accounts_channel_url", t_monitor_accounts.c.channel_url, unique=True)

# ── monitor_events ───────────────────────────────────────────────────

t_monitor_events = Table(
    "monitor_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "account_id",
        Integer,
        ForeignKey("monitor_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("account_name", String(256), nullable=False),
    Column("scan_started_at", String(64), nullable=False),
    Column("scan_ended_at", String(64), nullable=True),
    Column("status", String(32), nullable=False, server_default="running"),
    Column("total_videos", Integer, nullable=False, server_default=text("0")),
    Column("new_videos", Integer, nullable=False, server_default=text("0")),
    Column("error_message", Text, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    sqlite_autoincrement=True,
)
Index("idx_events_account_id", t_monitor_events.c.account_id)
Index("idx_events_started", t_monitor_events.c.scan_started_at.desc())

# ── monitor_videos ───────────────────────────────────────────────────

t_monitor_videos = Table(
    "monitor_videos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("video_id", String(64), nullable=False, unique=True),
    Column(
        "account_id",
        Integer,
        ForeignKey("monitor_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "event_id",
        Integer,
        ForeignKey("monitor_events.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("channel_id", String(64), nullable=True),
    Column("channel_handle", String(256), nullable=True),
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("url", Text, nullable=False),
    Column("published_at", String(64), nullable=False),
    Column("upload_date", String(16), nullable=True),
    Column("duration_sec", Integer, nullable=True),
    Column("view_count", Integer, nullable=True),
    Column("like_count", Integer, nullable=True),
    Column("comment_count", Integer, nullable=True),
    Column("thumbnail_url", Text, nullable=True),
    Column("fetched_at", String(64), nullable=False),
    Column("notify_status", String(32), nullable=False, server_default="pending"),
    Column("notify_sent_at", String(64), nullable=True),
    Column("notify_error", Text, nullable=True),
    Column("download_status", String(32), nullable=False, server_default="pending"),
    Column("download_at", String(64), nullable=True),
    Column("download_path", Text, nullable=True),
    Column("download_error", Text, nullable=True),
    Column("created_at", String(64), nullable=False),
    sqlite_autoincrement=True,
)
Index("idx_monitor_videos_account_id", t_monitor_videos.c.account_id)
Index("idx_monitor_videos_event_id", t_monitor_videos.c.event_id)
Index("idx_monitor_videos_published", t_monitor_videos.c.published_at.desc())
Index("idx_monitor_videos_notify", t_monitor_videos.c.notify_status)

# ── app_state ────────────────────────────────────────────────────────

t_app_state = Table(
    "app_state",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
)

# ── monitor_notify_logs ──────────────────────────────────────────────

t_monitor_notify_logs = Table(
    "monitor_notify_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "event_id",
        Integer,
        ForeignKey("monitor_events.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("account_id", Integer, nullable=False),
    Column("account_name", String(256), nullable=False),
    Column("video_count", Integer, nullable=False),
    Column("platform", String(32), nullable=False),
    Column("webhook_url", Text, nullable=False),
    Column("http_status", Integer, nullable=True),
    Column("response_text", Text, nullable=True),
    Column("sent_at", String(64), nullable=False),
    Column("error_message", Text, nullable=True),
    sqlite_autoincrement=True,
)
Index("idx_notify_logs_event_id", t_monitor_notify_logs.c.event_id)
Index("idx_notify_logs_sent_at", t_monitor_notify_logs.c.sent_at.desc())

# ── channel_meta_cache ───────────────────────────────────────────────

t_channel_meta_cache = Table(
    "channel_meta_cache",
    metadata,
    Column("handle", String(256), primary_key=True),
    Column("channel_id", String(64), nullable=False),
    Column("channel_name", String(256), nullable=True),
    Column("uploads_playlist_id", String(64), nullable=True),
    Column("subscriber_count", String(32), nullable=True),
    Column("video_count", String(32), nullable=True),
    Column("description", Text, nullable=True),
    Column("cached_at", String(64), nullable=False),
)
Index("idx_channel_cache_channel_id", t_channel_meta_cache.c.channel_id)

# ── api_quota_usage ──────────────────────────────────────────────────

t_api_quota_usage = Table(
    "api_quota_usage",
    metadata,
    Column("api_key_value", String(256), nullable=False, primary_key=True),
    Column("date_key", String(16), nullable=False, primary_key=True),
    Column("api_calls", Integer, server_default=text("0")),
    Column("scans_done", Integer, server_default=text("0")),
    Column("blocked_scans", Integer, server_default=text("0")),
    Column("updated_at", String(64), nullable=False),
)
Index("idx_quota_date", t_api_quota_usage.c.date_key)

# ── schema_migrations ────────────────────────────────────────────────

t_schema_migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", String(64), primary_key=True),
    Column("applied_at", String(64), nullable=False),
)


# ══════════════════════════════════════════════════════════════════════
# Engine 单例
# ══════════════════════════════════════════════════════════════════════

_engine: Engine | None = None


def _build_url() -> str:
    """从环境变量构建数据库 URL，默认回退到本地 SQLite。"""
    url = os.environ.get("MONITOR_DATABASE_URL", "").strip()
    if url:
        return url
    return f"sqlite:///{DEFAULT_DB_PATH.replace(os.sep, '/')}"


def _parse_dialect(url: str) -> str:
    """从 URL 提取方言名 (sqlite / postgresql / mysql)。"""
    return url.split("://")[0].split("+")[0]


def get_engine() -> Engine:
    """返回（并惰性创建）模块级 Engine 单例。

    - SQLite: NullPool + connect 事件设置 PRAGMA
    - PostgreSQL: QueuePool (5+10) + pool_pre_ping
    - MySQL: QueuePool (5+10) + pool_recycle 3600s
    """
    global _engine
    if _engine is not None:
        return _engine

    url = _build_url()
    dialect = _parse_dialect(url)
    echo = os.environ.get("MONITOR_DB_ECHO", "").lower() in ("1", "true", "yes")

    kwargs: dict[str, Any] = {"echo": echo}

    if dialect == "sqlite":
        is_memory = url in ("sqlite://", "sqlite:///:memory:")
        kwargs["poolclass"] = StaticPool if is_memory else NullPool
        kwargs["connect_args"] = {"check_same_thread": False}
    elif dialect == "postgresql":
        kwargs["poolclass"] = QueuePool
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_pre_ping"] = True
    elif dialect in ("mysql", "mariadb"):
        kwargs["poolclass"] = QueuePool
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 10
        kwargs["pool_recycle"] = 3600
        kwargs["pool_pre_ping"] = True

    _engine = _sa_create_engine(url, **kwargs)

    if dialect == "sqlite":

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _log.info("Database engine created: dialect=%s echo=%s", dialect, echo)
    return _engine


def reset_engine() -> None:
    """销毁并重置 Engine 单例（主要用于测试）。"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_dialect_name() -> str:
    """返回当前方言名: 'sqlite' / 'postgresql' / 'mysql'。"""
    return get_engine().dialect.name


# ══════════════════════════════════════════════════════════════════════
# 连接上下文管理器
# ══════════════════════════════════════════════════════════════════════


@contextmanager
def get_connection():
    """Yield 一个 SQLAlchemy Connection，自动 commit / rollback。

    用法::

        with get_connection() as conn:
            result = conn.execute(select(t_api_keys))
            rows = result.mappings().all()
    """
    with get_engine().connect() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ══════════════════════════════════════════════════════════════════════
# 表初始化
# ══════════════════════════════════════════════════════════════════════


def create_all_tables() -> None:
    """CREATE TABLE IF NOT EXISTS — 适用于全新数据库。

    已有数据库应使用 Alembic 迁移，此函数作为兜底或测试用。
    """
    metadata.create_all(get_engine())
    _log.info("All tables ensured via metadata.create_all()")


# ══════════════════════════════════════════════════════════════════════
# 跨方言 UPSERT 辅助
# ══════════════════════════════════════════════════════════════════════


def dialect_insert(table: Table):
    """返回支持 on_conflict_do_nothing / on_conflict_do_update 的方言 Insert。

    - SQLite / PostgreSQL: 通过各自方言的 ``insert()``
    - MySQL / MariaDB: 通过 ``sqlalchemy.dialects.mysql.insert()``
    - 其他: 通用 ``sqlalchemy.insert()``（不支持 upsert）
    """
    name = get_dialect_name()
    if name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert

        return insert(table)
    elif name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        return insert(table)
    elif name in ("mysql", "mariadb"):
        from sqlalchemy.dialects.mysql import insert

        return insert(table)
    from sqlalchemy import insert

    return insert(table)


def make_insert_ignore(table: Table, *, index_elements: list[str] | None = None):
    """构建 INSERT ... ON CONFLICT DO NOTHING (SQLite/PG) 或 INSERT IGNORE (MySQL)。

    Args:
        table: 目标表
        index_elements: 冲突检测的列名列表（SQLite/PG 必须；MySQL 忽略此参数，
                         自动基于 UNIQUE 约束检测冲突）
    """
    stmt = dialect_insert(table)
    name = get_dialect_name()

    if name in ("sqlite", "postgresql"):
        if index_elements:
            return stmt.on_conflict_do_nothing(index_elements=index_elements)
        return stmt.on_conflict_do_nothing()
    elif name in ("mysql", "mariadb"):
        return stmt.prefix_with("IGNORE")
    return stmt


def make_upsert(
    table: Table,
    *,
    index_elements: list[str],
    update_columns: list[str],
):
    """构建 INSERT ... ON CONFLICT DO UPDATE (SQLite/PG) 或
    INSERT ... ON DUPLICATE KEY UPDATE (MySQL)。

    Args:
        table: 目标表
        index_elements: 冲突目标列名（SQLite/PG 用于 ON CONFLICT(...)；
                         MySQL 忽略此参数）
        update_columns: 冲突时需要更新的列名列表
    """
    stmt = dialect_insert(table)
    name = get_dialect_name()

    if name in ("sqlite", "postgresql"):
        set_ = {col: getattr(stmt.excluded, col) for col in update_columns}
        return stmt.on_conflict_do_update(index_elements=index_elements, set_=set_)
    elif name in ("mysql", "mariadb"):
        set_ = {col: getattr(stmt.inserted, col) for col in update_columns}
        return stmt.on_duplicate_key_update(**set_)
    return stmt

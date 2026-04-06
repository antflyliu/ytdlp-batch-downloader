#!/usr/bin/env python3
"""
SQLite → PostgreSQL / MySQL 数据迁移脚本。

将现有 SQLite 数据库中的全部数据按照外键依赖顺序迁移到目标数据库。
目标数据库的表结构由 Alembic 迁移或 create_all_tables() 预先创建。

用法:
    # 迁移到 PostgreSQL
    python scripts/migrate_data.py \
        --source sqlite:///monitor/data/monitor.db \
        --target postgresql+psycopg://user:pass@localhost:5432/monitor

    # 迁移到 MySQL
    python scripts/migrate_data.py \
        --source sqlite:///monitor/data/monitor.db \
        --target mysql+pymysql://user:pass@localhost:3306/monitor

    # 仅预览，不实际写入
    python scripts/migrate_data.py \
        --source sqlite:///monitor/data/monitor.db \
        --target postgresql+psycopg://user:pass@localhost:5432/monitor \
        --dry-run

    # 自定义批次大小
    python scripts/migrate_data.py \
        --source sqlite:///monitor/data/monitor.db \
        --target postgresql+psycopg://user:pass@localhost:5432/monitor \
        --batch-size 500
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.pool import NullPool

from monitor.database import metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("migrate_data")

ORDERED_TABLES = [
    "app_state",
    "api_keys",
    "api_quota_usage",
    "channel_meta_cache",
    "schema_migrations",
    "monitor_accounts",
    "monitor_events",
    "monitor_videos",
    "monitor_notify_logs",
]


def _count_rows(conn, table_name: str) -> int:
    result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.scalar() or 0


def _get_table(name: str):
    """通过名称获取 MetaData 中的 Table 对象。"""
    return metadata.tables[name]


def migrate(
    source_url: str,
    target_url: str,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> dict:
    """执行数据迁移。

    Args:
        source_url: 源数据库 URL (通常是 SQLite)
        target_url: 目标数据库 URL (PostgreSQL / MySQL)
        batch_size: 每批插入的行数
        dry_run: 仅统计不写入

    Returns:
        迁移统计信息 {table_name: row_count, ...}
    """
    src_engine = create_engine(source_url, poolclass=NullPool)
    tgt_engine = create_engine(target_url, poolclass=NullPool)

    src_dialect = src_engine.dialect.name
    tgt_dialect = tgt_engine.dialect.name
    _log.info("源数据库: %s (%s)", source_url.split("@")[-1] if "@" in source_url else source_url, src_dialect)
    _log.info("目标数据库: %s (%s)", target_url.split("@")[-1] if "@" in target_url else target_url, tgt_dialect)

    src_inspector = inspect(src_engine)
    src_tables = set(src_inspector.get_table_names())

    tgt_inspector = inspect(tgt_engine)
    tgt_tables = set(tgt_inspector.get_table_names())

    _log.info("创建目标表结构 (如果缺失) ...")
    metadata.create_all(tgt_engine)

    tgt_inspector = inspect(tgt_engine)
    tgt_tables = set(tgt_inspector.get_table_names())

    stats: dict[str, int] = {}
    total_start = time.time()

    for table_name in ORDERED_TABLES:
        if table_name not in src_tables:
            _log.info("  [跳过] %s — 源数据库中不存在", table_name)
            stats[table_name] = 0
            continue

        if table_name not in tgt_tables:
            _log.warning("  [跳过] %s — 目标数据库中不存在", table_name)
            stats[table_name] = 0
            continue

        table_obj = _get_table(table_name)

        with src_engine.connect() as src_conn:
            total = _count_rows(src_conn, table_name)

        if total == 0:
            _log.info("  [跳过] %s — 无数据", table_name)
            stats[table_name] = 0
            continue

        with tgt_engine.connect() as tgt_conn:
            existing = _count_rows(tgt_conn, table_name)

        if existing > 0:
            _log.warning(
                "  [警告] %s — 目标已有 %d 行数据，跳过（若需覆盖请先清空目标表）",
                table_name, existing,
            )
            stats[table_name] = 0
            continue

        _log.info("  [迁移] %s — %d 行 ...", table_name, total)

        if dry_run:
            stats[table_name] = total
            continue

        table_start = time.time()
        migrated = 0

        with src_engine.connect() as src_conn:
            result = src_conn.execute(select(table_obj))
            columns = list(result.keys())

            batch: list[dict] = []
            for row in result:
                row_dict = dict(zip(columns, row))
                batch.append(row_dict)

                if len(batch) >= batch_size:
                    with tgt_engine.connect() as tgt_conn:
                        tgt_conn.execute(table_obj.insert(), batch)
                        tgt_conn.commit()
                    migrated += len(batch)
                    _log.info("    %s: %d / %d", table_name, migrated, total)
                    batch = []

            if batch:
                with tgt_engine.connect() as tgt_conn:
                    tgt_conn.execute(table_obj.insert(), batch)
                    tgt_conn.commit()
                migrated += len(batch)

        elapsed = time.time() - table_start
        _log.info("    %s: 完成 %d 行 (%.1fs)", table_name, migrated, elapsed)
        stats[table_name] = migrated

    if tgt_dialect == "postgresql":
        _log.info("重置 PostgreSQL 序列 ...")
        _reset_pg_sequences(tgt_engine)

    total_elapsed = time.time() - total_start
    total_rows = sum(stats.values())
    _log.info("=" * 60)
    _log.info(
        "迁移%s: 共 %d 行, 耗时 %.1fs",
        "预览" if dry_run else "完成",
        total_rows,
        total_elapsed,
    )
    for name, count in stats.items():
        if count > 0:
            _log.info("  %s: %d 行", name, count)

    src_engine.dispose()
    tgt_engine.dispose()
    return stats


def _reset_pg_sequences(engine):
    """在 PostgreSQL 上重置 SERIAL 序列为 MAX(id) + 1。"""
    tables_with_serial = [
        ("api_keys", "id"),
        ("monitor_accounts", "id"),
        ("monitor_events", "id"),
        ("monitor_videos", "id"),
        ("monitor_notify_logs", "id"),
    ]
    with engine.connect() as conn:
        for table_name, col_name in tables_with_serial:
            seq_name = f"{table_name}_{col_name}_seq"
            try:
                conn.execute(text(
                    f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({col_name}) FROM {table_name}), 0) + 1, false)"
                ))
            except Exception as e:
                _log.warning("  重置序列 %s 失败: %s", seq_name, e)
        conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description="SQLite → PostgreSQL / MySQL 数据迁移",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        required=True,
        help="源数据库 URL, 例: sqlite:///monitor/data/monitor.db",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="目标数据库 URL, 例: postgresql+psycopg://user:pass@localhost/monitor",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每批插入行数 (默认: 1000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览不写入",
    )
    args = parser.parse_args()

    migrate(
        source_url=args.source,
        target_url=args.target,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

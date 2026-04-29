"""Create a safe copy of a monitor SQLite DB and rehearse init_db() upgrades on it.

Usage:
    python scripts/rehearse_monitor_db_upgrade.py
    python scripts/rehearse_monitor_db_upgrade.py --source-db monitor/data/monitor.db --json
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db  # noqa: E402


EXPECTED_TABLES = {
    "api_quota_usage",
    "channel_meta_cache",
    "schema_migrations",
    "alembic_version",
    "dynamic_proxy_providers",
    "download_decision_logs",
    "provider_scheduler_runs",
    "web_batch_tasks",
}

EXPECTED_MONITOR_ACCOUNT_COLUMNS = {
    "download_proxy_mode",
    "dingtalk_sign_secret",
}

EXPECTED_PROVIDER_COLUMNS = {
    "refresh_interval_minutes",
}

EXPECTED_WEB_BATCH_COLUMNS = {
    "task_id",
    "source_name",
    "status",
    "results_json",
    "cancel_requested",
    "cancel_message",
}

EXPECTED_INDEXES = {
    "idx_web_batch_tasks_created_at",
    "idx_web_batch_tasks_status",
    "idx_provider_scheduler_runs_started_at",
    "idx_provider_scheduler_runs_provider_id",
    "idx_download_decision_account",
}

EXPECTED_MIGRATIONS = {
    "v7_dynamic_proxy",
    "v8_dynamic_proxy_candidates",
    "v9_provider_refresh_interval",
    "v10_provider_scheduler_runs",
    "v11_web_batch_tasks",
    "v12_monitor_accounts_dingtalk_sign_secret",
}


def _copy_database_with_backup_api(source_db: Path, target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_db) as source_conn:
        with sqlite3.connect(target_db) as target_conn:
            source_conn.backup(target_conn)


def _rowset(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> set[str]:
    return {row[0] for row in conn.execute(sql, params).fetchall()}


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def rehearse_upgrade(source_db: Path) -> dict:
    if not source_db.exists():
        raise FileNotFoundError(f"数据库不存在: {source_db}")
    if source_db.stat().st_size <= 0:
        raise ValueError(f"数据库为空文件: {source_db}")

    workdir = Path(tempfile.mkdtemp(prefix="monitor-db-upgrade-rehearsal-"))
    rehearsal_db = workdir / "monitor.db"
    rehearsal_config = workdir / "config.json"
    _copy_database_with_backup_api(source_db, rehearsal_db)

    db = importlib.reload(monitor_db)
    with mock.patch.object(db, "_DATA_DIR", str(workdir)):
        with mock.patch.object(db, "_DB_PATH", str(rehearsal_db)):
            with mock.patch.object(db, "_CONFIG_PATH", str(rehearsal_config)):
                with mock.patch.object(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql")):
                    db.init_db()
                    with db.get_connection() as conn:
                        tables = _rowset(
                            conn, "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                        indexes = _rowset(
                            conn, "SELECT name FROM sqlite_master WHERE type='index'"
                        )
                        migrations = _rowset(
                            conn, "SELECT version FROM schema_migrations"
                        )
                        monitor_account_columns = _table_columns(conn, "monitor_accounts")
                        provider_columns = _table_columns(conn, "dynamic_proxy_providers")
                        web_batch_columns = _table_columns(conn, "web_batch_tasks")
                        stale_web_batch_count = conn.execute(
                            "SELECT COUNT(*) FROM web_batch_tasks WHERE status IN ('running', 'cancelling')"
                        ).fetchone()[0]
                        task_counts = {
                            row[0]: row[1]
                            for row in conn.execute(
                                "SELECT status, COUNT(*) FROM web_batch_tasks GROUP BY status"
                            ).fetchall()
                        }

    return {
        "source_db": str(source_db),
        "rehearsal_db": str(rehearsal_db),
        "missing_tables": sorted(EXPECTED_TABLES - tables),
        "missing_monitor_account_columns": sorted(
            EXPECTED_MONITOR_ACCOUNT_COLUMNS - monitor_account_columns
        ),
        "missing_provider_columns": sorted(
            EXPECTED_PROVIDER_COLUMNS - provider_columns
        ),
        "missing_web_batch_columns": sorted(
            EXPECTED_WEB_BATCH_COLUMNS - web_batch_columns
        ),
        "missing_indexes": sorted(EXPECTED_INDEXES - indexes),
        "missing_migrations": sorted(EXPECTED_MIGRATIONS - migrations),
        "stale_web_batch_count_after_rehearsal": stale_web_batch_count,
        "web_batch_task_counts": task_counts,
        "ok": not any([
            EXPECTED_TABLES - tables,
            EXPECTED_MONITOR_ACCOUNT_COLUMNS - monitor_account_columns,
            EXPECTED_PROVIDER_COLUMNS - provider_columns,
            EXPECTED_WEB_BATCH_COLUMNS - web_batch_columns,
            EXPECTED_INDEXES - indexes,
            EXPECTED_MIGRATIONS - migrations,
            stale_web_batch_count,
        ]),
        "workdir": str(workdir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对 monitor SQLite 数据库做离线升级演练（在副本上调用 init_db）。"
    )
    parser.add_argument(
        "--source-db",
        default=str(ROOT / "monitor" / "data" / "monitor.db"),
        help="源数据库路径，默认 monitor/data/monitor.db",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 结果",
    )
    parser.add_argument(
        "--keep-copy",
        action="store_true",
        help="保留演练副本目录；默认脚本结束后删除",
    )
    args = parser.parse_args()

    result = rehearse_upgrade(Path(args.source_db).resolve())

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Monitor DB upgrade rehearsal")
        print(f"source_db: {result['source_db']}")
        print(f"rehearsal_db: {result['rehearsal_db']}")
        print(f"ok: {result['ok']}")
        print(f"missing_tables: {result['missing_tables']}")
        print(
            "missing_monitor_account_columns: "
            f"{result['missing_monitor_account_columns']}"
        )
        print(f"missing_provider_columns: {result['missing_provider_columns']}")
        print(f"missing_web_batch_columns: {result['missing_web_batch_columns']}")
        print(f"missing_indexes: {result['missing_indexes']}")
        print(f"missing_migrations: {result['missing_migrations']}")
        print(
            "stale_web_batch_count_after_rehearsal: "
            f"{result['stale_web_batch_count_after_rehearsal']}"
        )
        print(f"web_batch_task_counts: {result['web_batch_task_counts']}")
        print(f"workdir: {result['workdir']}")

    if args.keep_copy:
        return 0 if result["ok"] else 1

    shutil.rmtree(result["workdir"], ignore_errors=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

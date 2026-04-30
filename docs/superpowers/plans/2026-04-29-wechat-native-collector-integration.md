# WeChat Native Collector Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-party WeChat Official Account article collector while keeping the existing third-party `wechat-article-exporter` API collector available and unchanged.

**Architecture:** Introduce a provider-based collection package under `monitor/wechat_collect/`: the current exporter API becomes one provider, and a new native WeChat MP provider owns login sessions, cookie/token storage, account search, article list retrieval, and article download. The backend persists native sessions, discovered accounts/articles, and collection tasks in SQLite; the Vue app adds a separate sidebar workspace for native collection and links successful outputs into the existing AI article and WeChat publishing flows.

**Tech Stack:** Python 3.12, existing `requests`/stdlib HTTP stack, SQLite via `monitor.db`, existing encrypted config helpers, Vue 3 + TypeScript + Naive UI, current proxy router and dynamic proxy candidate system. No new runtime dependencies in P0.

---

## Scope

This plan implements the P0/P1 foundation:

- Keep existing `/api/wechat-collect/*` and `monitor/wechat_collector.py` behavior as the third-party exporter API path.
- Add a new native collector under `/api/wechat-native/*`.
- Add a separate left sidebar entry, tentatively `公众号原生采集`, so users can choose between third-party collection and self-controlled collection.
- Use local扫码登录 to acquire and persist WeChat MP `token` + cookies.
- Support native account search, article URL -> account lookup, article list pagination, and HTML/Markdown/Text/JSON article export.
- Persist native tasks in SQLite so restarts do not erase history.
- Reuse the existing proxy pool/dynamic proxy model where safe.
- Provide one-click follow-up actions from native collection results into AI article creation and WeChat publish workflows.

Out of P0 scope, but designed for extension:

- High-fidelity resource packaging with all CSS/images embedded.
- PDF/docx export parity with upstream.
- Reading count, like count, comments, and comment replies via mobile credentials.
- Paid article full-content access.

Those should become separate plans after the native collector is stable.

## File Structure

Create:

- `monitor/wechat_collect/__init__.py`  
  Public package exports only.

- `monitor/wechat_collect/errors.py`  
  Typed exception classes for login, session, upstream, parsing, and task failures.

- `monitor/wechat_collect/models.py`  
  Dataclasses and literal status/type constants shared by providers, tasks, and API serializers.

- `monitor/wechat_collect/session_store.py`  
  SQLite-backed encrypted storage for native WeChat MP sessions. Responsible for token/cookie encryption, expiry, status transitions, and safe response shaping.

- `monitor/wechat_collect/native_login.py`  
  In-memory pending QR login manager plus persisted-login finalization. Responsible for `startlogin`, QR image fetch, scan polling, and `bizlogin?action=login`.

- `monitor/wechat_collect/native_client.py`  
  Authenticated WeChat MP HTTP client. Responsible for `searchbiz`, `appmsgpublish`, `/cgi-bin/home`, logout, and response normalization.

- `monitor/wechat_collect/html_export.py`  
  Article HTML fetch and lightweight extraction/export. P0 keeps HTML faithful enough for archival and produces best-effort text/Markdown without adding dependencies.

- `monitor/wechat_collect/providers.py`  
  Provider protocol plus `ExporterApiProvider` and `NativeMpProvider`.

- `monitor/wechat_collect/tasks.py`  
  Persistent collection task service and background runner. Replaces in-memory state for native tasks only.

- `monitor/wechat_collect/serializers.py`  
  API-safe response mappers for sessions, tasks, accounts, and article previews.

- `monitor/db/queries/wechat_collect.py`  
  Focused SQLite CRUD for native sessions/accounts/articles/tasks. Imported by `monitor/wechat_collect/*`; not flattened into `monitor.db`.

- `frontend-vue/src/api/wechatNativeCollect.ts`  
  TypeScript API client for `/api/wechat-native/*`.

- `frontend-vue/src/views/WechatNativeCollect.vue`  
  Native collector workspace using existing warm card/table/task patterns.

- `tests/test_wechat_native_schema.py`
- `tests/test_wechat_native_session_store.py`
- `tests/test_wechat_native_login_flow.py`
- `tests/test_wechat_native_client.py`
- `tests/test_wechat_native_tasks.py`
- `tests/test_wechat_native_api_contract.py`
- `tests/test_wechat_native_frontend_contract.py`

Modify:

- `monitor/schema.sql`  
  Add native collector tables and indexes for fresh bootstrap.

- `monitor/db.py`  
  Add idempotent migration `v19_wechat_native_collect`. Keep the actual CRUD in `monitor/db/queries/wechat_collect.py`.

- `monitor/wechat_collector.py`  
  Keep existing public API behavior. Optionally convert to a compatibility facade only after tests prove no route contract changed.

- `server/__main__.py`  
  Add `/api/wechat-native/*` GET/POST routes. Preserve `/api/wechat-collect/*`.

- `config/settings.py`  
  Add native collector defaults and native session secret keys if needed.

- `frontend-vue/src/components/layout/AppSider.vue`  
  Add new sidebar item `wechatNativeCollect`.

- `frontend-vue/src/components/layout/AppHeader.vue`  
  Add route title mapping.

- `frontend-vue/src/router/index.ts`  
  Add `/wechat-native-collect`.

- `frontend-vue/src/locales/zh.json`
- `frontend-vue/src/locales/en.json`  
  Add all visible labels, statuses, errors, and actions.

- `frontend-vue/src/views/WechatCollect.vue`  
  Add a small label/description clarifying this page is the third-party exporter API path, without changing behavior.

- `frontend-vue/src/views/AiCreation.vue`  
  Accept prefill query params from native collection result links when available.

---

## API Contract

Native endpoints:

- `GET /api/wechat-native/config`
- `GET /api/wechat-native/sessions`
- `POST /api/wechat-native/login/start`
- `GET /api/wechat-native/login/{login_id}/qrcode`
- `GET /api/wechat-native/login/{login_id}/scan`
- `POST /api/wechat-native/login/{login_id}/confirm`
- `POST /api/wechat-native/sessions/{session_id}/check`
- `POST /api/wechat-native/sessions/{session_id}/logout`
- `POST /api/wechat-native/accounts/search`
- `POST /api/wechat-native/accounts/by-url`
- `POST /api/wechat-native/articles/preview`
- `POST /api/wechat-native/tasks/start`
- `GET /api/wechat-native/tasks`
- `GET /api/wechat-native/tasks/{task_id}`
- `POST /api/wechat-native/tasks/{task_id}/cancel`

Security contract:

- `auth_key`, MP `token`, and raw cookies are internal backend credentials and must never appear in URLs, browser query strings, task payloads returned to the frontend, or logs.
- Frontend/API callers use an opaque `session_id`. Backend code resolves `session_id` to encrypted token/cookie rows inside `NativeSessionStore`.
- Session-bound operations use POST bodies for request parameters. GET routes are limited to public metadata, QR images, and task/status reads.

Existing third-party endpoints stay unchanged:

- `/api/wechat-collect/config`
- `/api/wechat-collect/auth/check`
- `/api/wechat-collect/preview`
- `/api/wechat-collect/start`
- `/api/wechat-collect/tasks`
- `/api/wechat-collect/tasks/{task_id}`
- `/api/wechat-collect/tasks/{task_id}/cancel`

---

### Task 1: Lock Existing Third-Party Collector Behavior

**Files:**
- Modify: `tests/test_wechat_collect_integration.py`
- Test: `tests/test_wechat_collect_integration.py`

- [ ] **Step 1: Add a regression test that explicitly names the provider as exporter API**

Append this test to `tests/test_wechat_collect_integration.py`:

```python
def test_existing_wechat_collect_route_remains_exporter_api_provider():
    server = SERVER_MAIN.read_text(encoding="utf-8")
    collector = (ROOT / "monitor" / "wechat_collector.py").read_text(encoding="utf-8")

    assert '"/api/wechat-collect/start"' in server
    assert "WechatExporterClient" in collector
    assert "DEFAULT_EXPORTER_BASE_URL" in collector
    assert "/api/public/v1/download" in collector
    assert "/api/public/v1/article" in collector
```

- [ ] **Step 2: Run the current collector contract tests**

Run:

```powershell
python -m pytest tests/test_wechat_collect_integration.py -q
```

Expected: all tests pass before any refactor.

- [ ] **Step 3: Commit**

Use a Lore-style message:

```bash
git add tests/test_wechat_collect_integration.py
git commit -m "Protect the existing exporter-backed WeChat collector

The native collector will live beside the current exporter API integration,
so the old route contract is locked before any provider refactor.

Constraint: Existing third-party collection must remain available
Confidence: high
Scope-risk: narrow
Tested: python -m pytest tests/test_wechat_collect_integration.py -q"
```

---

### Task 2: Add Native Collector Schema and Queries

**Files:**
- Modify: `monitor/schema.sql`
- Modify: `monitor/db.py`
- Create: `monitor/db/queries/wechat_collect.py`
- Test: `tests/test_wechat_native_schema.py`

- [ ] **Step 1: Write schema tests**

Create `tests/test_wechat_native_schema.py`:

```python
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def _patch_monitor_db_paths(monkeypatch, db_path: Path, data_dir: Path, schema_path: Path) -> None:
    import monitor.db as db
    import monitor.db.connection as db_connection

    # monitor.db is loaded through a compatibility package while newer query
    # modules import monitor.db.connection directly. Patch both namespaces so
    # tests never touch the real data/monitor.db.
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def test_wechat_native_tables_exist_after_init(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"

    _patch_monitor_db_paths(monkeypatch, db_path, data_dir, schema_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    try:
        tables = _tables(conn)
        assert "wechat_collect_sessions" in tables
        assert "wechat_collect_accounts" in tables
        assert "wechat_collect_articles" in tables
        assert "wechat_collect_tasks" in tables
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert "idx_wechat_collect_tasks_created_at" in indexes
        assert "idx_wechat_collect_articles_fakeid_update" in indexes
    finally:
        conn.close()


def test_wechat_collect_query_module_round_trips_session(monkeypatch, tmp_path):
    import monitor.db as db

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"

    _patch_monitor_db_paths(monkeypatch, db_path, data_dir, schema_path)
    db.init_db()

    queries = importlib.import_module("monitor.db.queries.wechat_collect")
    queries.upsert_session(
        session_id="sess-1",
        token_enc="enc-token",
        cookie_json_enc="enc-cookie",
        nickname="测试号",
        avatar="https://example.test/a.png",
        expires_at="2030-01-01T00:00:00+08:00",
        status="active",
    )

    session = queries.get_session("sess-1")
    assert session is not None
    assert session["session_id"] == "sess-1"
    assert session["nickname"] == "测试号"
    assert session["status"] == "active"
```

Reuse the same `_patch_monitor_db_paths` helper in every later native collector test file that initializes SQLite or calls `monitor.db.queries.wechat_collect`.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_wechat_native_schema.py -q
```

Expected: fails because the tables and query module do not exist.

- [ ] **Step 3: Add schema to `monitor/schema.sql`**

Add these tables near the existing WeChat publish schema block:

```sql
CREATE TABLE IF NOT EXISTS wechat_collect_sessions (
    session_id      TEXT PRIMARY KEY,
    token_enc       TEXT NOT NULL,
    cookie_json_enc TEXT NOT NULL,
    nickname        TEXT,
    avatar          TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    expires_at      TEXT NOT NULL,
    last_checked_at TEXT,
    last_error      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wechat_collect_sessions_status
ON wechat_collect_sessions(status, expires_at);

CREATE TABLE IF NOT EXISTS wechat_collect_accounts (
    fakeid         TEXT PRIMARY KEY,
    nickname       TEXT,
    alias          TEXT,
    round_head_img TEXT,
    service_type   INTEGER,
    signature      TEXT,
    verify_status  INTEGER,
    raw_json       TEXT NOT NULL DEFAULT '{}',
    last_synced_at TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wechat_collect_articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fakeid        TEXT NOT NULL,
    aid           TEXT,
    title         TEXT,
    link          TEXT NOT NULL UNIQUE,
    digest        TEXT,
    cover         TEXT,
    author_name   TEXT,
    update_time   INTEGER,
    create_time   INTEGER,
    raw_json      TEXT NOT NULL DEFAULT '{}',
    local_path    TEXT,
    export_format TEXT,
    status        TEXT NOT NULL DEFAULT 'listed',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (fakeid) REFERENCES wechat_collect_accounts(fakeid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wechat_collect_articles_fakeid_update
ON wechat_collect_articles(fakeid, update_time DESC);

CREATE TABLE IF NOT EXISTS wechat_collect_tasks (
    task_id          TEXT PRIMARY KEY,
    provider         TEXT NOT NULL DEFAULT 'native',
    session_id       TEXT,
    source_mode      TEXT NOT NULL,
    fakeid           TEXT,
    article_url      TEXT,
    account_name     TEXT,
    urls_json        TEXT NOT NULL DEFAULT '[]',
    keyword          TEXT,
    export_format    TEXT NOT NULL DEFAULT 'markdown',
    output_dir       TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    total            INTEGER NOT NULL DEFAULT 0,
    completed        INTEGER NOT NULL DEFAULT 0,
    success          INTEGER NOT NULL DEFAULT 0,
    failed           INTEGER NOT NULL DEFAULT 0,
    current          TEXT,
    result_json      TEXT NOT NULL DEFAULT '[]',
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    finished_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_created_at
ON wechat_collect_tasks(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_status
ON wechat_collect_tasks(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wechat_collect_tasks_provider
ON wechat_collect_tasks(provider, created_at DESC);
```

- [ ] **Step 4: Add migration `v19_wechat_native_collect` in `monitor/db.py`**

Add the same `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements inside `_migrate_monitor_accounts(conn)` after `v18_wechat_publish_tasks`, then mark:

```python
conn.execute(
    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
    ("v19_wechat_native_collect", today),
)
```

- [ ] **Step 5: Create `monitor/db/queries/wechat_collect.py`**

Create the module with this public surface:

```python
from __future__ import annotations

import json

from monitor.db.connection import get_connection
from monitor.db.db_core import now_iso


def _json_dumps(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(value: str, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def upsert_session(
    *,
    session_id: str,
    token_enc: str,
    cookie_json_enc: str,
    nickname: str = "",
    avatar: str = "",
    expires_at: str,
    status: str = "active",
) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_sessions
               (session_id, token_enc, cookie_json_enc, nickname, avatar, status,
                expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 token_enc=excluded.token_enc,
                 cookie_json_enc=excluded.cookie_json_enc,
                 nickname=excluded.nickname,
                 avatar=excluded.avatar,
                 status=excluded.status,
                 expires_at=excluded.expires_at,
                 updated_at=excluded.updated_at""",
            (session_id, token_enc, cookie_json_enc, nickname, avatar, status, expires_at, now, now),
        )


def get_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_collect_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT session_id, nickname, avatar, status, expires_at,
                      last_checked_at, last_error, created_at, updated_at
               FROM wechat_collect_sessions
               ORDER BY updated_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def update_session_status(session_id: str, *, status: str, last_error: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE wechat_collect_sessions
               SET status=?, last_error=?, last_checked_at=?, updated_at=?
               WHERE session_id=?""",
            (status, last_error, now_iso(), now_iso(), session_id),
        )


def upsert_account(account: dict) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_accounts
               (fakeid, nickname, alias, round_head_img, service_type, signature,
                verify_status, raw_json, last_synced_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(fakeid) DO UPDATE SET
                 nickname=excluded.nickname,
                 alias=excluded.alias,
                 round_head_img=excluded.round_head_img,
                 service_type=excluded.service_type,
                 signature=excluded.signature,
                 verify_status=excluded.verify_status,
                 raw_json=excluded.raw_json,
                 last_synced_at=excluded.last_synced_at,
                 updated_at=excluded.updated_at""",
            (
                account.get("fakeid"),
                account.get("nickname"),
                account.get("alias"),
                account.get("round_head_img"),
                account.get("service_type"),
                account.get("signature"),
                account.get("verify_status"),
                _json_dumps(account),
                now,
                now,
                now,
            ),
        )


def upsert_article(fakeid: str, article: dict, *, local_path: str = "", export_format: str = "", status: str = "listed") -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_articles
               (fakeid, aid, title, link, digest, cover, author_name, update_time,
                create_time, raw_json, local_path, export_format, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(link) DO UPDATE SET
                 fakeid=excluded.fakeid,
                 aid=excluded.aid,
                 title=excluded.title,
                 digest=excluded.digest,
                 cover=excluded.cover,
                 author_name=excluded.author_name,
                 update_time=excluded.update_time,
                 create_time=excluded.create_time,
                 raw_json=excluded.raw_json,
                 local_path=COALESCE(NULLIF(excluded.local_path, ''), wechat_collect_articles.local_path),
                 export_format=COALESCE(NULLIF(excluded.export_format, ''), wechat_collect_articles.export_format),
                 status=excluded.status,
                 updated_at=excluded.updated_at""",
            (
                fakeid,
                article.get("aid"),
                article.get("title"),
                article.get("link") or article.get("url"),
                article.get("digest"),
                article.get("cover") or article.get("cover_img"),
                article.get("author_name"),
                article.get("update_time"),
                article.get("create_time"),
                _json_dumps(article),
                local_path,
                export_format,
                status,
                now,
                now,
            ),
        )
```

Then add task CRUD functions in the same file:

```python
def create_task(payload: dict, *, task_id: str, output_dir: str) -> None:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO wechat_collect_tasks
               (task_id, provider, session_id, source_mode, fakeid, article_url,
                account_name, urls_json, keyword, export_format, output_dir,
                status, current, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                task_id,
                payload.get("provider") or "native",
                payload.get("session_id"),
                payload.get("source_mode") or "url",
                payload.get("fakeid"),
                payload.get("article_url"),
                payload.get("account_name"),
                _json_dumps(payload.get("urls") or []),
                payload.get("keyword"),
                payload.get("format") or "markdown",
                output_dir,
                "等待启动",
                now,
                now,
            ),
        )


def get_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wechat_collect_tasks WHERE task_id=?",
            (task_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["urls"] = _json_loads(item.pop("urls_json", "[]"), [])
    item["results"] = _json_loads(item.pop("result_json", "[]"), [])
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    return item


def list_tasks(*, provider: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    where = []
    params = []
    if provider:
        where.append("provider=?")
        params.append(provider)
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT * FROM wechat_collect_tasks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["urls"] = _json_loads(item.pop("urls_json", "[]"), [])
        item["results"] = _json_loads(item.pop("result_json", "[]"), [])
        item["cancel_requested"] = bool(item.get("cancel_requested"))
        result.append(item)
    return result
```

Add update helpers:

```python
def update_task(task_id: str, **fields) -> None:
    allowed = {
        "status", "total", "completed", "success", "failed", "current",
        "error", "cancel_requested", "finished_at",
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "cancel_requested":
            value = int(bool(value))
        assignments.append(f"{key}=?")
        values.append(value)
    if not assignments:
        return
    assignments.append("updated_at=?")
    values.append(now_iso())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE wechat_collect_tasks SET {', '.join(assignments)} WHERE task_id=?",
            values,
        )


def append_task_result(task_id: str, result: dict) -> None:
    task = get_task(task_id)
    if not task:
        return
    results = list(task.get("results") or [])
    results.append(result)
    success = sum(1 for item in results if item.get("status") == "success")
    failed = len(results) - success
    with get_connection() as conn:
        conn.execute(
            """UPDATE wechat_collect_tasks
               SET result_json=?, completed=?, success=?, failed=?, current=?, updated_at=?
               WHERE task_id=?""",
            (
                _json_dumps(results),
                len(results),
                success,
                failed,
                result.get("title") or result.get("url") or task.get("current"),
                now_iso(),
                task_id,
            ),
        )


def request_cancel(task_id: str) -> bool:
    task = get_task(task_id)
    if not task or task.get("status") not in {"pending", "running"}:
        return False
    update_task(task_id, cancel_requested=True, current="正在取消")
    return True
```

- [ ] **Step 6: Run schema tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_schema.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add monitor/schema.sql monitor/db.py monitor/db/queries/wechat_collect.py tests/test_wechat_native_schema.py
git commit -m "Prepare persistent storage for native WeChat collection

Native collection needs durable sessions and task history because QR login,
article pagination, and batch downloads can outlive a browser view.

Constraint: Keep monitor.db top-level stable; put focused CRUD under queries
Rejected: Store native tasks in memory | restart would erase long-running history
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_schema.py -q"
```

---

### Task 3: Add Shared Native Collector Models and Errors

**Files:**
- Create: `monitor/wechat_collect/__init__.py`
- Create: `monitor/wechat_collect/errors.py`
- Create: `monitor/wechat_collect/models.py`
- Test: `tests/test_wechat_native_client.py`

- [ ] **Step 1: Write tests for model normalization**

Create the first part of `tests/test_wechat_native_client.py`:

```python
from __future__ import annotations

from monitor.wechat_collect.models import normalize_article_preview, normalize_account_preview


def test_normalize_account_preview_keeps_safe_fields_only():
    raw = {
        "fakeid": "MzTest==",
        "nickname": "测试公众号",
        "alias": "test_alias",
        "round_head_img": "https://example.test/head.png",
        "signature": "hello",
        "secret": "must-not-leak",
    }

    preview = normalize_account_preview(raw)

    assert preview == {
        "fakeid": "MzTest==",
        "nickname": "测试公众号",
        "alias": "test_alias",
        "round_head_img": "https://example.test/head.png",
        "service_type": None,
        "signature": "hello",
        "verify_status": None,
    }


def test_normalize_article_preview_accepts_wechat_article_shape():
    raw = {
        "aid": "224_1",
        "title": "标题",
        "link": "https://mp.weixin.qq.com/s/test",
        "cover": "https://example.test/cover.jpg",
        "author_name": "作者",
        "update_time": 1777210218,
        "create_time": 1777210000,
        "digest": "摘要",
    }

    preview = normalize_article_preview(raw)

    assert preview["aid"] == "224_1"
    assert preview["title"] == "标题"
    assert preview["link"] == "https://mp.weixin.qq.com/s/test"
    assert preview["update_time"] == 1777210218
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: fails because `monitor.wechat_collect` does not exist.

- [ ] **Step 3: Add errors**

Create `monitor/wechat_collect/errors.py`:

```python
from __future__ import annotations


class WechatNativeError(RuntimeError):
    """Base class for native WeChat collector failures."""


class WechatLoginError(WechatNativeError):
    """Raised when QR login cannot start, poll, or finalize."""


class WechatSessionError(WechatNativeError):
    """Raised when a persisted native session is missing or expired."""


class WechatUpstreamError(WechatNativeError):
    """Raised when mp.weixin.qq.com returns a non-success response."""


class WechatArticleError(WechatNativeError):
    """Raised when article HTML cannot be fetched, parsed, or exported."""


class WechatTaskError(WechatNativeError):
    """Raised when a collection task cannot be created or completed."""
```

- [ ] **Step 4: Add models**

Create `monitor/wechat_collect/models.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


ProviderName = Literal["exporter_api", "native"]
TaskStatus = Literal["pending", "running", "done", "error", "cancelled"]
SourceMode = Literal["url", "fakeid", "urls"]

SUPPORTED_EXPORT_FORMATS = {
    "html": "html",
    "markdown": "md",
    "text": "txt",
    "json": "json",
}

MP_ARTICLE_URL_RE = re.compile(r"^https://mp\.weixin\.qq\.com/s[/\?]", re.IGNORECASE)


@dataclass
class NativeSession:
    session_id: str
    token: str
    cookies: list[dict[str, str]] = field(default_factory=list)
    nickname: str = ""
    avatar: str = ""
    status: str = "active"
    expires_at: str = ""


@dataclass
class ArticleDownload:
    body: bytes
    content_type: str
    title: str = ""
    metadata: dict = field(default_factory=dict)


def is_valid_mp_article_url(value: str) -> bool:
    return MP_ARTICLE_URL_RE.match((value or "").strip()) is not None


def normalize_account_preview(raw: dict) -> dict:
    return {
        "fakeid": raw.get("fakeid") or "",
        "nickname": raw.get("nickname") or "",
        "alias": raw.get("alias") or "",
        "round_head_img": raw.get("round_head_img") or "",
        "service_type": raw.get("service_type"),
        "signature": raw.get("signature") or "",
        "verify_status": raw.get("verify_status"),
    }


def normalize_article_preview(raw: dict) -> dict:
    return {
        "aid": raw.get("aid") or "",
        "title": raw.get("title") or "",
        "link": raw.get("link") or raw.get("url") or "",
        "cover": raw.get("cover") or raw.get("cover_img") or "",
        "digest": raw.get("digest") or "",
        "author_name": raw.get("author_name") or "",
        "update_time": raw.get("update_time") or raw.get("create_time") or 0,
        "create_time": raw.get("create_time") or 0,
    }
```

- [ ] **Step 5: Add package exports**

Create `monitor/wechat_collect/__init__.py`:

```python
from monitor.wechat_collect.errors import (
    WechatArticleError,
    WechatLoginError,
    WechatNativeError,
    WechatSessionError,
    WechatTaskError,
    WechatUpstreamError,
)
from monitor.wechat_collect.models import (
    ArticleDownload,
    NativeSession,
    SUPPORTED_EXPORT_FORMATS,
    is_valid_mp_article_url,
    normalize_account_preview,
    normalize_article_preview,
)

__all__ = [
    "ArticleDownload",
    "NativeSession",
    "SUPPORTED_EXPORT_FORMATS",
    "WechatArticleError",
    "WechatLoginError",
    "WechatNativeError",
    "WechatSessionError",
    "WechatTaskError",
    "WechatUpstreamError",
    "is_valid_mp_article_url",
    "normalize_account_preview",
    "normalize_article_preview",
]
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add monitor/wechat_collect tests/test_wechat_native_client.py
git commit -m "Define native WeChat collector domain models

The native provider needs typed boundaries before login, session storage,
and task orchestration are added.

Constraint: Keep provider code independent from HTTP route handlers
Confidence: high
Scope-risk: narrow
Tested: python -m pytest tests/test_wechat_native_client.py -q"
```

---

### Task 4: Implement Encrypted Native Session Store

**Files:**
- Create: `monitor/wechat_collect/session_store.py`
- Modify: `tests/test_wechat_native_session_store.py`

- [ ] **Step 1: Write session-store tests**

Create `tests/test_wechat_native_session_store.py`:

```python
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path


def _init_temp_db(monkeypatch, tmp_path):
    import monitor.db as db
    import monitor.db.connection as db_connection

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()
    return db_path


def test_session_store_encrypts_token_and_cookies(monkeypatch, tmp_path):
    db_path = _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )

    session = store.get_session(session_id)
    assert session.token == "token-123"
    assert session.cookies[0]["value"] == "cookie-secret"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT token_enc, cookie_json_enc FROM wechat_collect_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] != "token-123"
    assert "cookie-secret" not in row[1]


def test_session_store_public_list_masks_secrets(monkeypatch, tmp_path):
    _init_temp_db(monkeypatch, tmp_path)

    store_mod = importlib.import_module("monitor.wechat_collect.session_store")
    store = store_mod.NativeSessionStore()
    session_id = store.save_session(
        token="token-123",
        cookies=[{"name": "sessionid", "value": "cookie-secret"}],
        nickname="测试号",
        avatar="",
    )

    public = store.list_public_sessions()

    assert public[0]["session_id"] == session_id
    assert "auth_key" not in public[0]
    encoded = json.dumps(public, ensure_ascii=False)
    assert "token-123" not in encoded
    assert "cookie-secret" not in encoded
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_session_store.py -q
```

Expected: fails because the store module does not exist.

- [ ] **Step 3: Implement `NativeSessionStore`**

Create `monitor/wechat_collect/session_store.py`:

```python
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from config.encryption import _decrypt_config_value, _encrypt_config_value
from monitor.db.queries import wechat_collect as queries
from monitor.wechat_collect.errors import WechatSessionError
from monitor.wechat_collect.models import NativeSession


def _now() -> datetime:
    return datetime.now().astimezone()


def _expires_at(days: int = 4) -> str:
    return (_now() + timedelta(days=days)).isoformat(timespec="seconds")


class NativeSessionStore:
    def save_session(
        self,
        *,
        token: str,
        cookies: list[dict[str, str]],
        nickname: str = "",
        avatar: str = "",
        session_id: str | None = None,
    ) -> str:
        if not token:
            raise WechatSessionError("token 不能为空")
        if not cookies:
            raise WechatSessionError("cookies 不能为空")
        session_id = session_id or f"wcs_{secrets.token_hex(16)}"
        queries.upsert_session(
            session_id=session_id,
            token_enc=_encrypt_config_value(token),
            cookie_json_enc=_encrypt_config_value(json.dumps(cookies, ensure_ascii=False)),
            nickname=nickname,
            avatar=avatar,
            expires_at=_expires_at(),
            status="active",
        )
        return session_id

    def get_session(self, session_id: str) -> NativeSession:
        row = queries.get_session(session_id)
        if not row:
            raise WechatSessionError("登录会话不存在")
        if row.get("status") != "active":
            raise WechatSessionError("登录会话不可用，请重新扫码")
        expires_raw = row.get("expires_at") or ""
        try:
            expires = datetime.fromisoformat(expires_raw)
        except Exception as exc:
            raise WechatSessionError("登录会话过期时间无效") from exc
        if expires <= _now():
            queries.update_session_status(session_id, status="expired", last_error="登录会话已过期")
            raise WechatSessionError("登录会话已过期，请重新扫码")
        token = _decrypt_config_value(row.get("token_enc") or "")
        cookie_json = _decrypt_config_value(row.get("cookie_json_enc") or "[]")
        cookies = json.loads(cookie_json or "[]")
        return NativeSession(
            session_id=session_id,
            token=token,
            cookies=cookies,
            nickname=row.get("nickname") or "",
            avatar=row.get("avatar") or "",
            status=row.get("status") or "active",
            expires_at=expires_raw,
        )

    def list_public_sessions(self) -> list[dict]:
        return queries.list_sessions()

    def mark_error(self, session_id: str, message: str) -> None:
        queries.update_session_status(session_id, status="error", last_error=message)

    def mark_logged_out(self, session_id: str) -> None:
        queries.update_session_status(session_id, status="logged_out", last_error="")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_session_store.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/session_store.py tests/test_wechat_native_session_store.py
git commit -m "Persist native WeChat sessions with encrypted credentials

Native collection depends on WeChat MP token and cookies, so credentials are
stored encrypted and only public session metadata leaves the backend.

Constraint: Token and cookie values must never appear in API responses
Rejected: Browser-only session storage | batch tasks need backend access
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_session_store.py -q"
```

---

### Task 5: Implement Native QR Login Manager

**Files:**
- Create: `monitor/wechat_collect/native_login.py`
- Test: `tests/test_wechat_native_login_flow.py`

- [ ] **Step 1: Write login-flow tests with fake transport**

Create `tests/test_wechat_native_login_flow.py`:

```python
from __future__ import annotations

import json

from monitor.wechat_collect.native_login import NativeLoginManager


class FakeResponse:
    def __init__(self, payload=None, content=b"", headers=None, status_code=200):
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code
        self.text = json.dumps(payload or {}, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.cookies = {"uuid": "uuid-cookie", "bizuin": "biz-cookie"}

    def post(self, url, params=None, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, params, data))
        if params and params.get("action") == "startlogin":
            return FakeResponse({"base_resp": {"ret": 0, "err_msg": "ok"}})
        if params and params.get("action") == "login":
            return FakeResponse({"base_resp": {"ret": 0}, "redirect_url": "/cgi-bin/home?t=home/index&token=token-123"})
        raise AssertionError((url, params, data))

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, None))
        if params and params.get("action") == "getqrcode":
            return FakeResponse(content=b"png-bytes", headers={"Content-Type": "image/png"})
        if params and params.get("action") == "ask":
            return FakeResponse({"base_resp": {"ret": 0}, "status": 1, "acct_size": 1})
        if "cgi-bin/home" in url:
            html = 'wx.cgiData.nick_name = "测试号"; wx.cgiData.head_img = "https://example.test/head.png";'
            return FakeResponse(content=html.encode("utf-8"))
        raise AssertionError((url, params))


def test_native_login_manager_completes_qr_login(monkeypatch, tmp_path):
    import monitor.db as db
    import monitor.db.connection as db_connection
    from pathlib import Path

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()

    manager = NativeLoginManager(session_factory=FakeSession)

    started = manager.start_login()
    qrcode = manager.get_qrcode(started["login_id"])
    scan = manager.poll_scan(started["login_id"])
    confirmed = manager.confirm_login(started["login_id"])

    assert qrcode.body == b"png-bytes"
    assert scan["status"] == 1
    assert confirmed["session_id"]
    assert confirmed["nickname"] == "测试号"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_login_flow.py -q
```

Expected: fails because `native_login.py` does not exist.

- [ ] **Step 3: Implement `NativeLoginManager`**

Create `monitor/wechat_collect/native_login.py`:

```python
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

import requests

from monitor.wechat_collect.errors import WechatLoginError
from monitor.wechat_collect.session_store import NativeSessionStore

MP_BASE = "https://mp.weixin.qq.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)


@dataclass
class BinaryPayload:
    body: bytes
    content_type: str


class NativeLoginManager:
    def __init__(self, *, session_factory=None, store: NativeSessionStore | None = None):
        self._session_factory = session_factory or requests.Session
        self._store = store or NativeSessionStore()
        self._pending: dict[str, requests.Session] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": USER_AGENT,
        }

    def start_login(self) -> dict:
        login_id = secrets.token_hex(12)
        sid = f"{int(time.time() * 1000)}{secrets.randbelow(100)}"
        session = self._session_factory()
        body = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": 3,
            "sessionid": sid,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        resp = session.post(
            f"{MP_BASE}/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data=body,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        base_resp = payload.get("base_resp") or {}
        if int(base_resp.get("ret", -1)) != 0:
            raise WechatLoginError(str(base_resp.get("err_msg") or "创建登录会话失败"))
        self._pending[login_id] = session
        return {"login_id": login_id, "status": "pending"}

    def _pending_session(self, login_id: str):
        session = self._pending.get(login_id)
        if not session:
            raise WechatLoginError("登录会话不存在或已过期")
        return session

    def get_qrcode(self, login_id: str) -> BinaryPayload:
        session = self._pending_session(login_id)
        resp = session.get(
            f"{MP_BASE}/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": int(time.time() * 1000)},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return BinaryPayload(
            body=resp.content,
            content_type=resp.headers.get("Content-Type", "image/png"),
        )

    def poll_scan(self, login_id: str) -> dict:
        session = self._pending_session(login_id)
        resp = session.get(
            f"{MP_BASE}/cgi-bin/scanloginqrcode",
            params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if int((payload.get("base_resp") or {}).get("ret", 0)) != 0:
            raise WechatLoginError(str((payload.get("base_resp") or {}).get("err_msg") or "扫码状态查询失败"))
        return payload

    def confirm_login(self, login_id: str) -> dict:
        session = self._pending_session(login_id)
        resp = session.post(
            f"{MP_BASE}/cgi-bin/bizlogin",
            params={"action": "login"},
            data={
                "userlang": "zh_CN",
                "redirect_url": "",
                "cookie_forbidden": 0,
                "cookie_cleaned": 0,
                "plugin_used": 0,
                "login_type": 3,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        redirect_url = str(payload.get("redirect_url") or "")
        token = self._extract_token(redirect_url)
        if not token:
            raise WechatLoginError("登录成功响应缺少 token")
        nickname, avatar = self._fetch_login_profile(session, token)
        cookies = [
            {"name": cookie.name, "value": cookie.value, "domain": cookie.domain or "", "path": cookie.path or "/"}
            for cookie in session.cookies
            if cookie.value
        ]
        session_id = self._store.save_session(
            token=token,
            cookies=cookies,
            nickname=nickname,
            avatar=avatar,
        )
        self._pending.pop(login_id, None)
        return {"session_id": session_id, "nickname": nickname, "avatar": avatar, "expires_days": 4}

    @staticmethod
    def _extract_token(redirect_url: str) -> str:
        parsed = urlparse(f"http://localhost{redirect_url}" if redirect_url.startswith("/") else redirect_url)
        values = parse_qs(parsed.query).get("token") or []
        return values[0] if values else ""

    def _fetch_login_profile(self, session, token: str) -> tuple[str, str]:
        resp = session.get(
            f"{MP_BASE}/cgi-bin/home",
            params={"t": "home/index", "token": token, "lang": "zh_CN"},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        html = resp.content.decode("utf-8", errors="ignore")
        nick_match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"([^"]+)"', html)
        head_match = re.search(r'wx\.cgiData\.head_img\s*=\s*"([^"]+)"', html)
        return (
            nick_match.group(1) if nick_match else "",
            head_match.group(1) if head_match else "",
        )
```

- [ ] **Step 4: Run login tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_login_flow.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/native_login.py tests/test_wechat_native_login_flow.py
git commit -m "Add native WeChat QR login flow

The native collector needs to own login state locally instead of relying on
wechat-article-exporter auth keys.

Constraint: Login order mirrors upstream MP flow startlogin -> qrcode -> scan -> login
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_login_flow.py -q"
```

---

### Task 6: Implement Native WeChat MP Client

**Files:**
- Create: `monitor/wechat_collect/native_client.py`
- Modify: `tests/test_wechat_native_client.py`

- [ ] **Step 1: Add tests for search and article-list parsing**

Append to `tests/test_wechat_native_client.py`:

```python
import json

from monitor.wechat_collect.models import NativeSession
from monitor.wechat_collect.native_client import NativeMpClient


class FakeMpResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeMpSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if "searchbiz" in url:
            return FakeMpResponse(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "list": [{"fakeid": "fakeid-1", "nickname": "测试号"}],
                    "total": 1,
                }
            )
        if "appmsgpublish" in url:
            return FakeMpResponse(
                {
                    "base_resp": {"ret": 0, "err_msg": "ok"},
                    "publish_page": json.dumps(
                        {
                            "total_count": 1,
                            "publish_list": [
                                {
                                    "publish_info": json.dumps(
                                        {
                                            "appmsgex": [
                                                {
                                                    "aid": "224_1",
                                                    "title": "文章",
                                                    "link": "https://mp.weixin.qq.com/s/test",
                                                    "update_time": 1777210218,
                                                }
                                            ]
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        raise AssertionError((url, params))


def test_native_mp_client_searches_accounts_and_lists_articles():
    native_session = NativeSession(
        session_id="sess",
        token="token-123",
        cookies=[{"name": "bizuin", "value": "cookie-value", "domain": "", "path": "/"}],
    )
    fake_http = FakeMpSession()
    client = NativeMpClient(native_session, http_session=fake_http)

    accounts = client.search_accounts("测试")
    articles = client.list_articles("fakeid-1", max_articles=1, page_size=5)

    assert accounts[0]["fakeid"] == "fakeid-1"
    assert articles[0]["title"] == "文章"
    assert fake_http.calls[0][1]["token"] == "token-123"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: fails because `NativeMpClient` does not exist.

- [ ] **Step 3: Implement `NativeMpClient`**

Create `monitor/wechat_collect/native_client.py`:

```python
from __future__ import annotations

import json
from http.cookiejar import Cookie

import requests

from monitor.wechat_collect.errors import WechatUpstreamError
from monitor.wechat_collect.models import NativeSession, normalize_account_preview, normalize_article_preview

MP_BASE = "https://mp.weixin.qq.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)


class NativeMpClient:
    def __init__(self, session: NativeSession, *, http_session=None, timeout: int = 30):
        self.session = session
        self.http = http_session or requests.Session()
        self.timeout = timeout
        self._apply_cookies()

    def _headers(self) -> dict[str, str]:
        return {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        }

    def _apply_cookies(self) -> None:
        if not hasattr(self.http, "cookies"):
            return
        for item in self.session.cookies:
            name = item.get("name") or ""
            value = item.get("value") or ""
            if not name or not value:
                continue
            path = item.get("path") or "/"
            domain = (item.get("domain") or "").strip()
            if domain:
                self.http.cookies.set(name, value, domain=domain, path=path)
            else:
                # requests raises AttributeError when domain=None is passed.
                self.http.cookies.set(name, value, path=path)

    @staticmethod
    def _check_base_resp(payload: dict, operation: str) -> None:
        base_resp = payload.get("base_resp") or {}
        ret = int(base_resp.get("ret", 0) or 0)
        if ret == 0:
            return
        if ret == 200003:
            raise WechatUpstreamError("登录会话已过期，请重新扫码登录")
        raise WechatUpstreamError(f"{operation}失败: {ret}:{base_resp.get('err_msg') or payload}")

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        keyword = (keyword or "").strip()
        if not keyword:
            raise WechatUpstreamError("搜索关键字不能为空")
        resp = self.http.get(
            f"{MP_BASE}/cgi-bin/searchbiz",
            params={
                "action": "search_biz",
                "begin": max(0, int(begin or 0)),
                "count": max(1, min(int(size or 5), 20)),
                "query": keyword,
                "token": self.session.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._check_base_resp(payload, "搜索公众号")
        return [normalize_account_preview(item) for item in payload.get("list") or []]

    def list_articles(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        max_articles: int = 50,
        page_size: int = 20,
        progress=None,
    ) -> list[dict]:
        fakeid = (fakeid or "").strip()
        if not fakeid:
            raise WechatUpstreamError("fakeid 不能为空")
        max_articles = max(1, min(int(max_articles or 50), 1000))
        page_size = max(1, min(int(page_size or 20), 20))
        begin = 0
        articles: list[dict] = []
        seen_links: set[str] = set()
        while len(articles) < max_articles:
            if progress:
                progress(f"正在获取文章列表 offset={begin}")
            payload = self._fetch_article_page(fakeid, begin=begin, size=page_size, keyword=keyword)
            page_articles = payload.get("articles") or []
            if not page_articles:
                break
            for raw in page_articles:
                preview = normalize_article_preview(raw)
                link = preview.get("link") or ""
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                articles.append({**raw, **preview})
                if len(articles) >= max_articles:
                    break
            if len(page_articles) < page_size:
                break
            begin += page_size
        return articles

    def _fetch_article_page(self, fakeid: str, *, begin: int, size: int, keyword: str) -> dict:
        is_searching = bool(keyword)
        resp = self.http.get(
            f"{MP_BASE}/cgi-bin/appmsgpublish",
            params={
                "sub": "search" if is_searching else "list",
                "search_field": "7" if is_searching else "null",
                "begin": begin,
                "count": size,
                "query": keyword or "",
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
                "token": self.session.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._check_base_resp(payload, "获取文章列表")
        publish_page = json.loads(payload.get("publish_page") or "{}")
        publish_list = [
            item for item in publish_page.get("publish_list") or []
            if item.get("publish_info")
        ]
        articles = []
        for item in publish_list:
            publish_info = json.loads(item.get("publish_info") or "{}")
            articles.extend(publish_info.get("appmsgex") or [])
        return {"base_resp": payload.get("base_resp"), "articles": articles, "total_count": publish_page.get("total_count", 0)}
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/native_client.py tests/test_wechat_native_client.py
git commit -m "Add native WeChat MP account and article client

The native collector can now use locally stored MP sessions to search accounts
and fetch article history without calling the hosted exporter API.

Constraint: Match WeChat backend request parameters used by upstream exporter
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_client.py -q"
```

---

### Task 7: Add Native Article Download and Export

**Files:**
- Create: `monitor/wechat_collect/html_export.py`
- Test: `tests/test_wechat_native_client.py`

- [ ] **Step 1: Add tests for article export**

Append to `tests/test_wechat_native_client.py`:

```python
from monitor.wechat_collect.html_export import export_article_html


def test_export_article_html_outputs_html_text_markdown_and_json():
    raw_html = """
    <html><body>
      <div id="js_article">
        <h1 id="activity-name">标题</h1>
        <div id="js_content" style="visibility:hidden">
          <p>第一段</p><p><img data-src="https://example.test/a.jpg"></p>
        </div>
      </div>
      <script>window.secret = 1;</script>
    </body></html>
    """

    html_result = export_article_html(raw_html, "html")
    text_result = export_article_html(raw_html, "text")
    markdown_result = export_article_html(raw_html, "markdown")
    json_result = export_article_html(raw_html, "json")

    assert b"js_content" in html_result.body
    assert b"script" not in html_result.body.lower()
    assert "第一段" in text_result.body.decode("utf-8")
    assert "第一段" in markdown_result.body.decode("utf-8")
    assert json_result.metadata["title"] == "标题"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py::test_export_article_html_outputs_html_text_markdown_and_json -q
```

Expected: fails because `html_export.py` does not exist.

- [ ] **Step 3: Implement lightweight exporter**

Create `monitor/wechat_collect/html_export.py`:

```python
from __future__ import annotations

import html
import json
import re

import requests

from monitor.wechat_collect.errors import WechatArticleError
from monitor.wechat_collect.models import ArticleDownload, SUPPORTED_EXPORT_FORMATS, is_valid_mp_article_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)


def _strip_scripts(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", "", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", "", value, flags=re.I)
    return value


def _extract_title(value: str) -> str:
    for pattern in (
        r'<h1[^>]+id=["\']activity-name["\'][^>]*>([\s\S]*?)</h1>',
        r"<title[^>]*>([\s\S]*?)</title>",
    ):
        match = re.search(pattern, value, flags=re.I)
        if match:
            return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return ""


def _extract_js_article(value: str) -> str:
    match = re.search(r'<div[^>]+id=["\']js_article["\'][^>]*>([\s\S]*?)</div>\s*</body>', value, flags=re.I)
    if match:
        return match.group(0)
    content_match = re.search(r'<div[^>]+id=["\']js_content["\'][^>]*>([\s\S]*?)</div>', value, flags=re.I)
    return content_match.group(0) if content_match else value


def _normalize_images(value: str) -> str:
    return re.sub(
        r'(<img\b[^>]*?)\sdata-src=(["\'])([^"\']+)\2',
        lambda m: f'{m.group(1)} src="{html.escape(m.group(3), quote=True)}"',
        value,
        flags=re.I,
    )


def _text_from_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _markdown_from_html(value: str) -> str:
    text = _text_from_html(value)
    title = _extract_title(value)
    if title and not text.startswith(title):
        return f"# {title}\n\n{text}".strip()
    return text


def export_article_html(raw_html: str, export_format: str) -> ArticleDownload:
    fmt = (export_format or "html").strip().lower()
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise WechatArticleError(f"不支持的导出格式: {export_format}")
    cleaned = _normalize_images(_strip_scripts(raw_html))
    article_html = _extract_js_article(cleaned)
    title = _extract_title(cleaned)
    if fmt == "html":
        body = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="referrer" content="no-referrer">'
            '<style>body{max-width:667px;margin:0 auto;padding:20px;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.6}img{max-width:100%}</style>'
            "</head><body>"
            + article_html
            + "</body></html>"
        ).encode("utf-8")
        return ArticleDownload(body=body, content_type="text/html; charset=utf-8", title=title, metadata={"title": title})
    if fmt == "text":
        return ArticleDownload(body=_text_from_html(article_html).encode("utf-8"), content_type="text/plain; charset=utf-8", title=title, metadata={"title": title})
    if fmt == "markdown":
        return ArticleDownload(body=_markdown_from_html(article_html).encode("utf-8"), content_type="text/markdown; charset=utf-8", title=title, metadata={"title": title})
    payload = {"title": title, "text": _text_from_html(article_html), "html": article_html}
    return ArticleDownload(
        body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json; charset=utf-8",
        title=title,
        metadata=payload,
    )


def download_article(url: str, export_format: str, *, http_session=None, timeout: int = 30) -> ArticleDownload:
    if not is_valid_mp_article_url(url):
        raise WechatArticleError("文章链接不合法")
    http = http_session or requests.Session()
    resp = http.get(
        url,
        headers={"Referer": "https://mp.weixin.qq.com/", "Origin": "https://mp.weixin.qq.com", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return export_article_html(resp.text, export_format)
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/html_export.py tests/test_wechat_native_client.py
git commit -m "Add lightweight native WeChat article export

P0 native collection archives article HTML and best-effort text/markdown/json
without introducing a browser or extra parsing dependency.

Constraint: No new runtime dependency for P0
Rejected: Puppeteer/Playwright for first release | adds deployment weight before core collection is proven
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_client.py -q"
```

---

### Task 8: Add Provider Interface and Native Provider

**Files:**
- Create: `monitor/wechat_collect/providers.py`
- Test: `tests/test_wechat_native_client.py`

- [ ] **Step 1: Add provider tests**

Append to `tests/test_wechat_native_client.py`:

```python
from monitor.wechat_collect.providers import NativeMpProvider


def test_native_provider_uses_session_store_and_client(monkeypatch):
    native_session = NativeSession(
        session_id="sess",
        token="token-123",
        cookies=[{"name": "bizuin", "value": "cookie-value", "domain": "", "path": "/"}],
    )

    class Store:
        def get_session(self, session_id):
            assert session_id == "sess"
            return native_session

    fake_http = FakeMpSession()
    provider = NativeMpProvider(session_id="sess", store=Store(), http_session=fake_http)

    accounts = provider.search_accounts("测试")
    articles = provider.list_articles("fakeid-1", max_articles=1)

    assert accounts[0]["nickname"] == "测试号"
    assert articles[0]["link"] == "https://mp.weixin.qq.com/s/test"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py::test_native_provider_uses_session_store_and_client -q
```

Expected: fails because provider does not exist.

- [ ] **Step 3: Implement providers**

Create `monitor/wechat_collect/providers.py`:

```python
from __future__ import annotations

from typing import Protocol

from monitor.wechat_collect.html_export import download_article
from monitor.wechat_collect.native_client import NativeMpClient
from monitor.wechat_collect.session_store import NativeSessionStore


class CollectionProvider(Protocol):
    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        raise NotImplementedError

    def account_by_article_url(self, article_url: str) -> dict:
        raise NotImplementedError

    def list_articles(self, fakeid: str, *, keyword: str = "", max_articles: int = 50, page_size: int = 20, progress=None) -> list[dict]:
        raise NotImplementedError

    def download_article(self, article_url: str, export_format: str):
        raise NotImplementedError


class NativeMpProvider:
    def __init__(self, *, session_id: str, store: NativeSessionStore | None = None, http_session=None):
        self.session_id = session_id
        self.store = store or NativeSessionStore()
        self.session = self.store.get_session(session_id)
        self.client = NativeMpClient(self.session, http_session=http_session)
        self.http_session = http_session

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        return self.client.search_accounts(keyword, begin=begin, size=size)

    def account_by_article_url(self, article_url: str) -> dict:
        from monitor.wechat_collect.html_export import download_article as fetch_article

        downloaded = fetch_article(article_url, "html", http_session=self.http_session)
        name = downloaded.metadata.get("title") or ""
        if not name:
            raise ValueError("无法从文章链接识别公众号名称")
        matches = self.search_accounts(name, size=20)
        exact = [item for item in matches if item.get("nickname") == name]
        return (exact or matches)[0] if matches else {"fakeid": "", "nickname": name}

    def list_articles(self, fakeid: str, *, keyword: str = "", max_articles: int = 50, page_size: int = 20, progress=None) -> list[dict]:
        return self.client.list_articles(
            fakeid,
            keyword=keyword,
            max_articles=max_articles,
            page_size=page_size,
            progress=progress,
        )

    def download_article(self, article_url: str, export_format: str):
        return download_article(article_url, export_format, http_session=self.http_session)
```

Add the exporter adapter only if the current code is being refactored:

```python
class ExporterApiProvider:
    def __init__(self, client):
        self.client = client

    def search_accounts(self, keyword: str, *, begin: int = 0, size: int = 5) -> list[dict]:
        raise NotImplementedError("现有 exporter API P0 不提供本地搜索入口")

    def account_by_article_url(self, article_url: str) -> dict:
        return self.client.account_by_article_url(article_url)

    def list_articles(self, fakeid: str, *, keyword: str = "", max_articles: int = 50, page_size: int = 5, progress=None) -> list[dict]:
        return self.client.list_articles(
            fakeid,
            keyword=keyword,
            max_articles=max_articles,
            page_size=page_size,
            progress=progress,
        )

    def download_article(self, article_url: str, export_format: str):
        body, content_type = self.client.download_article(article_url, export_format)
        from monitor.wechat_collect.models import ArticleDownload

        return ArticleDownload(body=body, content_type=content_type)
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/providers.py tests/test_wechat_native_client.py
git commit -m "Add provider boundary for native WeChat collection

Provider boundaries keep the current exporter API path and the new native MP
path from leaking implementation details into routes or UI code.

Constraint: Existing exporter-backed collector remains side-by-side
Confidence: high
Scope-risk: narrow
Tested: python -m pytest tests/test_wechat_native_client.py -q"
```

---

### Task 9: Implement Persistent Native Collection Tasks

**Files:**
- Create: `monitor/wechat_collect/tasks.py`
- Test: `tests/test_wechat_native_tasks.py`

- [ ] **Step 1: Write task tests**

Create `tests/test_wechat_native_tasks.py`:

```python
from __future__ import annotations

from pathlib import Path

from monitor.wechat_collect.models import ArticleDownload
from monitor.wechat_collect.tasks import NativeCollectionTaskService


class FakeProvider:
    def account_by_article_url(self, article_url):
        return {"fakeid": "fakeid-1", "nickname": "测试号"}

    def list_articles(self, fakeid, *, keyword="", max_articles=50, page_size=20, progress=None):
        return [
            {
                "aid": "224_1",
                "title": "第一篇",
                "link": "https://mp.weixin.qq.com/s/first",
                "update_time": 1777210218,
            }
        ]

    def download_article(self, article_url, export_format):
        return ArticleDownload(
            body=b"# first",
            content_type="text/markdown; charset=utf-8",
            title="第一篇",
            metadata={"title": "第一篇"},
        )


def test_native_collection_task_persists_results(monkeypatch, tmp_path):
    import monitor.db as db
    import monitor.db.connection as db_connection

    db_path = tmp_path / "monitor.db"
    data_dir = tmp_path / "data"
    schema_path = Path(__file__).resolve().parents[1] / "monitor" / "schema.sql"
    monkeypatch.setattr(db, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(schema_path), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(db_path), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_SCHEMA_PATH", str(schema_path), raising=False)
    db.init_db()

    service = NativeCollectionTaskService(provider_factory=lambda payload: FakeProvider())
    task_id = service.create_task(
        {
            "provider": "native",
            "session_id": "sess",
            "source_mode": "url",
            "article_url": "https://mp.weixin.qq.com/s/source",
            "format": "markdown",
            "max_articles": 1,
            "delay_seconds": 0,
        },
        output_dir=str(tmp_path / "out"),
    )

    service.run_task(task_id)
    task = service.get_task(task_id)

    assert task["status"] == "done"
    assert task["success"] == 1
    assert Path(task["results"][0]["path"]).is_file()
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_tasks.py -q
```

Expected: fails because task service does not exist.

- [ ] **Step 3: Implement `NativeCollectionTaskService`**

Create `monitor/wechat_collect/tasks.py`:

```python
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from monitor.db.queries import wechat_collect as queries
from monitor.wechat_collect.errors import WechatTaskError
from monitor.wechat_collect.models import SUPPORTED_EXPORT_FORMATS
from monitor.wechat_collect.providers import NativeMpProvider

FILENAME_SAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def sanitize_filename(value: str, *, fallback: str = "article", max_length: int = 90) -> str:
    safe = FILENAME_SAFE_RE.sub("_", (value or "").strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    if not safe:
        safe = fallback
    return safe[:max_length].rstrip(" .") or fallback


def resolve_output_dir(requested: str | None, configured_root: str) -> str:
    root = Path(configured_root).expanduser().resolve()
    target = Path(requested).expanduser().resolve() if requested else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WechatTaskError("输出路径必须位于配置的公众号采集目录下") from exc
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


class NativeCollectionTaskService:
    def __init__(self, *, provider_factory=None):
        self.provider_factory = provider_factory or self._default_provider_factory

    def _default_provider_factory(self, payload: dict):
        return NativeMpProvider(session_id=payload.get("session_id") or "")

    def create_task(self, payload: dict, *, output_dir: str) -> str:
        task_id = f"wcn_{uuid.uuid4().hex[:12]}"
        queries.create_task(payload, task_id=task_id, output_dir=output_dir)
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        return queries.get_task(task_id)

    def list_tasks(self) -> list[dict]:
        return queries.list_tasks(provider="native")

    def request_cancel(self, task_id: str) -> bool:
        return queries.request_cancel(task_id)

    def start_background(self, task_id: str) -> None:
        thread = threading.Thread(target=self.run_task, args=(task_id,), name=f"wechat-native-{task_id}", daemon=True)
        thread.start()

    def run_task(self, task_id: str) -> None:
        task = queries.get_task(task_id)
        if not task:
            return
        queries.update_task(task_id, status="running", current="正在启动")
        try:
            payload = {
                "provider": "native",
                "session_id": task.get("session_id"),
                "source_mode": task.get("source_mode"),
                "fakeid": task.get("fakeid"),
                "article_url": task.get("article_url"),
                "account_name": task.get("account_name"),
                "urls": task.get("urls") or [],
                "keyword": task.get("keyword") or "",
                "format": task.get("export_format") or "markdown",
            }
            provider = self.provider_factory(payload)
            articles, account = self._resolve_articles(provider, task)
            queries.update_task(task_id, total=len(articles), current=f"已获取 {len(articles)} 篇文章")
            if not articles:
                raise WechatTaskError("没有获取到可导出的文章")
            self._download_articles(task_id, provider, task, articles)
            latest = queries.get_task(task_id)
            if latest and latest.get("cancel_requested"):
                queries.update_task(task_id, status="cancelled", finished_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            else:
                queries.update_task(task_id, status="done", current="采集完成", finished_at=datetime.now().astimezone().isoformat(timespec="seconds"))
        except Exception as exc:
            queries.update_task(task_id, status="error", error=str(exc), current="采集失败", finished_at=datetime.now().astimezone().isoformat(timespec="seconds"))

    def _resolve_articles(self, provider, task: dict) -> tuple[list[dict], dict]:
        urls = task.get("urls") or []
        max_articles = max(1, min(int(task.get("max_articles") or 50), 1000)) if task.get("max_articles") else 1000
        if urls:
            return [
                {"title": f"article-{idx}", "link": url, "update_time": int(time.time())}
                for idx, url in enumerate(urls[:max_articles], start=1)
            ], {}
        fakeid = task.get("fakeid") or ""
        account = {}
        if not fakeid:
            account = provider.account_by_article_url(task.get("article_url") or "")
            fakeid = account.get("fakeid") or ""
        articles = provider.list_articles(
            fakeid,
            keyword=task.get("keyword") or "",
            max_articles=max_articles,
            page_size=20,
            progress=lambda current: queries.update_task(task["task_id"], current=current),
        )
        if account:
            queries.upsert_account(account)
        for article in articles:
            queries.upsert_article(fakeid, article)
        return articles, account

    def _download_articles(self, task_id: str, provider, task: dict, articles: list[dict]) -> None:
        fmt = task.get("export_format") or "markdown"
        extension = SUPPORTED_EXPORT_FORMATS[fmt]
        output_dir = Path(task.get("output_dir") or os.getcwd())
        used: set[str] = set()
        delay_seconds = max(0.0, min(float(task.get("delay_seconds") or 0.0), 30.0))
        for idx, article in enumerate(articles, start=1):
            latest = queries.get_task(task_id)
            if latest and latest.get("cancel_requested"):
                return
            url = article.get("link") or article.get("url") or ""
            title = article.get("title") or f"article-{idx}"
            update_time = int(article.get("update_time") or article.get("create_time") or time.time())
            date_part = datetime.fromtimestamp(update_time).strftime("%Y%m%d")
            base = sanitize_filename(f"{date_part}-{title}", fallback=f"article-{idx}")
            filename = f"{base}.{extension}"
            suffix = 2
            while filename.lower() in used:
                filename = f"{base}-{suffix}.{extension}"
                suffix += 1
            used.add(filename.lower())
            out_path = output_dir / filename
            try:
                queries.update_task(task_id, current=f"正在导出 {idx}/{len(articles)}: {title}")
                downloaded = provider.download_article(url, fmt)
                out_path.write_bytes(downloaded.body)
                queries.append_task_result(
                    task_id,
                    {
                        "status": "success",
                        "title": downloaded.title or title,
                        "url": url,
                        "path": str(out_path),
                        "content_type": downloaded.content_type,
                    },
                )
            except Exception as exc:
                queries.append_task_result(
                    task_id,
                    {"status": "failed", "title": title, "url": url, "error": str(exc)},
                )
            if delay_seconds and idx < len(articles):
                time.sleep(delay_seconds)
```

- [ ] **Step 4: Run task tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_tasks.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_collect/tasks.py tests/test_wechat_native_tasks.py
git commit -m "Persist native WeChat collection tasks

Native collection now has restart-safe task history and file outputs, while
the existing exporter collector keeps its current in-memory implementation.

Constraint: Native task history must survive server restarts
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_tasks.py -q"
```

---

### Task 10: Add Backend API Routes

**Files:**
- Modify: `server/__main__.py`
- Create: `tests/test_wechat_native_api_contract.py`

- [ ] **Step 1: Write static API contract tests**

Create `tests/test_wechat_native_api_contract.py`:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"


def test_wechat_native_routes_are_wired():
    server = SERVER_MAIN.read_text(encoding="utf-8")

    for snippet in [
        '"/api/wechat-native/config"',
        '"/api/wechat-native/login/start"',
        '"/api/wechat-native/login/"',
        '"/api/wechat-native/sessions"',
        '"/api/wechat-native/accounts/search"',
        '"/api/wechat-native/accounts/by-url"',
        '"/api/wechat-native/articles/preview"',
        '"/api/wechat-native/tasks/start"',
        '"/api/wechat-native/tasks"',
    ]:
        assert snippet in server


def test_wechat_native_imports_do_not_replace_exporter_routes():
    server = SERVER_MAIN.read_text(encoding="utf-8")

    assert "monitor.wechat_collector" in server
    assert '"/api/wechat-collect/start"' in server
    assert "monitor.wechat_collect.native_login" in server
    assert "monitor.wechat_collect.tasks" in server
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_api_contract.py -q
```

Expected: fails because routes are not wired.

- [ ] **Step 3: Add imports and managers in `server/__main__.py`**

Near the existing WeChat imports, add:

```python
from monitor.wechat_collect.native_login import NativeLoginManager
from monitor.wechat_collect.session_store import NativeSessionStore
from monitor.wechat_collect.tasks import NativeCollectionTaskService, resolve_output_dir
from monitor.wechat_collect.providers import NativeMpProvider
```

Near `_wechat_collect_mgr`, add:

```python
_wechat_native_login_mgr = NativeLoginManager()
_wechat_native_session_store = NativeSessionStore()
_wechat_native_task_service = NativeCollectionTaskService()
```

- [ ] **Step 4: Add GET route dispatch**

In the GET routing section, add:

```python
elif path == "/api/wechat-native/config":
    self._api_wechat_native_config()
elif path == "/api/wechat-native/sessions":
    self._api_wechat_native_sessions()
elif path.startswith("/api/wechat-native/login/") and path.endswith("/qrcode"):
    login_id = path.split("/")[-2]
    self._api_wechat_native_login_qrcode(login_id)
elif path.startswith("/api/wechat-native/login/") and path.endswith("/scan"):
    login_id = path.split("/")[-2]
    self._api_wechat_native_login_scan(login_id)
elif path == "/api/wechat-native/tasks":
    self._api_wechat_native_tasks_list()
elif path.startswith("/api/wechat-native/tasks/"):
    task_id = path.rsplit("/", 1)[-1]
    self._api_wechat_native_task_status(task_id)
```

- [ ] **Step 5: Add POST route dispatch**

In the POST routing section, add:

```python
elif path == "/api/wechat-native/login/start":
    self._api_wechat_native_login_start()
elif path.startswith("/api/wechat-native/login/") and path.endswith("/confirm"):
    login_id = path.split("/")[-2]
    self._api_wechat_native_login_confirm(login_id)
elif path.startswith("/api/wechat-native/sessions/") and path.endswith("/check"):
    session_id = path.split("/")[-2]
    self._api_wechat_native_session_check(session_id)
elif path.startswith("/api/wechat-native/sessions/") and path.endswith("/logout"):
    session_id = path.split("/")[-2]
    self._api_wechat_native_session_logout(session_id)
elif path == "/api/wechat-native/accounts/search":
    self._api_wechat_native_accounts_search(body)
elif path == "/api/wechat-native/accounts/by-url":
    self._api_wechat_native_account_by_url(body)
elif path == "/api/wechat-native/articles/preview":
    self._api_wechat_native_preview(body)
elif path == "/api/wechat-native/tasks/start":
    self._api_wechat_native_start(body)
elif path.startswith("/api/wechat-native/tasks/") and path.endswith("/cancel"):
    task_id = path.split("/")[-2]
    self._api_wechat_native_cancel(task_id)
```

- [ ] **Step 6: Add handler methods**

Add methods near the existing `_api_wechat_collect_*` methods:

```python
def _api_wechat_native_config(self):
    cfg = _db.load_config()
    self._send_json({
        "wechat_collection_output_dir": cfg.get("wechat_collection_output_dir") or "",
        "wechat_collection_default_format": cfg.get("wechat_collection_default_format") or "markdown",
        "wechat_collection_delay_seconds": cfg.get("wechat_collection_delay_seconds", 1.0),
        "wechat_collection_max_articles": cfg.get("wechat_collection_max_articles", 50),
    })

def _api_wechat_native_sessions(self):
    self._send_json({"sessions": _wechat_native_session_store.list_public_sessions()})

def _api_wechat_native_login_start(self):
    try:
        self._send_json(_wechat_native_login_mgr.start_login())
    except Exception as exc:
        self._send_json({"error": str(exc)}, 500)

def _api_wechat_native_login_qrcode(self, login_id: str):
    try:
        payload = _wechat_native_login_mgr.get_qrcode(login_id)
        self.send_response(200)
        self.send_header("Content-Type", payload.content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload.body)
    except Exception as exc:
        self._send_json({"error": str(exc)}, 404)

def _api_wechat_native_login_scan(self, login_id: str):
    try:
        self._send_json(_wechat_native_login_mgr.poll_scan(login_id))
    except Exception as exc:
        self._send_json({"error": str(exc)}, 404)

def _api_wechat_native_login_confirm(self, login_id: str):
    try:
        self._send_json(_wechat_native_login_mgr.confirm_login(login_id))
    except Exception as exc:
        self._send_json({"error": str(exc)}, 400)
```

Add session/account/task methods:

```python
def _api_wechat_native_session_check(self, session_id: str):
    try:
        session = _wechat_native_session_store.get_session(session_id)
        provider = NativeMpProvider(session_id=session.session_id, store=_wechat_native_session_store)
        self._send_json({"ok": True, "nickname": session.nickname, "expires_at": session.expires_at})
    except Exception as exc:
        self._send_json({"ok": False, "error": str(exc)}, 401)

def _api_wechat_native_session_logout(self, session_id: str):
    _wechat_native_session_store.mark_logged_out(session_id)
    self._send_json({"ok": True})

def _api_wechat_native_accounts_search(self, body: dict):
    session_id = str((body or {}).get("session_id") or "")
    keyword = str((body or {}).get("keyword") or "")
    begin = int((body or {}).get("begin") or 0)
    size = int((body or {}).get("size") or 5)
    try:
        provider = NativeMpProvider(session_id=session_id, store=_wechat_native_session_store)
        self._send_json({"accounts": provider.search_accounts(keyword, begin=begin, size=size)})
    except Exception as exc:
        self._send_json({"error": str(exc)}, 400)

def _api_wechat_native_account_by_url(self, body: dict):
    try:
        provider = NativeMpProvider(session_id=str(body.get("session_id") or ""), store=_wechat_native_session_store)
        account = provider.account_by_article_url(str(body.get("article_url") or ""))
        self._send_json({"account": account})
    except Exception as exc:
        self._send_json({"error": str(exc)}, 400)
```

Add preview/start/list/status/cancel:

```python
def _api_wechat_native_preview(self, body: dict):
    try:
        provider = NativeMpProvider(session_id=str(body.get("session_id") or ""), store=_wechat_native_session_store)
        fakeid = str(body.get("fakeid") or "").strip()
        account = {}
        if not fakeid:
            account = provider.account_by_article_url(str(body.get("article_url") or ""))
            fakeid = str(account.get("fakeid") or "")
        articles = provider.list_articles(
            fakeid,
            keyword=str(body.get("keyword") or ""),
            max_articles=min(int(body.get("limit") or 20), 20),
            page_size=20,
        )
        self._send_json({"account": account, "articles": articles, "total": len(articles)})
    except Exception as exc:
        self._send_json({"error": str(exc)}, 400)

def _api_wechat_native_start(self, body: dict):
    cfg = _db.load_config()
    data_dir = str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))
    configured_root = cfg.get("wechat_collection_output_dir") or _wechat_collector.default_collection_output_dir(data_dir)
    try:
        output_dir = resolve_output_dir(body.get("output_dir"), configured_root)
        payload = dict(body or {})
        payload["provider"] = "native"
        payload.setdefault("source_mode", "urls" if payload.get("urls") else "fakeid" if payload.get("fakeid") else "url")
        payload.setdefault("format", cfg.get("wechat_collection_default_format") or "markdown")
        payload.setdefault("delay_seconds", cfg.get("wechat_collection_delay_seconds", 1.0))
        payload.setdefault("max_articles", cfg.get("wechat_collection_max_articles", 50))
        task_id = _wechat_native_task_service.create_task(payload, output_dir=output_dir)
        _wechat_native_task_service.start_background(task_id)
        self._send_json({"task_id": task_id, "status": "pending"})
    except Exception as exc:
        self._send_json({"error": str(exc)}, 400)

def _api_wechat_native_tasks_list(self):
    self._send_json({"tasks": _wechat_native_task_service.list_tasks()})

def _api_wechat_native_task_status(self, task_id: str):
    task = _wechat_native_task_service.get_task(task_id)
    if not task:
        self._send_json({"error": "task not found"}, 404)
        return
    self._send_json(task)

def _api_wechat_native_cancel(self, task_id: str):
    if not _wechat_native_task_service.request_cancel(task_id):
        self._send_json({"error": "task not running"}, 409)
        return
    self._send_json({"ok": True})
```

- [ ] **Step 7: Run backend contract tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_api_contract.py tests/test_wechat_collect_integration.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add server/__main__.py tests/test_wechat_native_api_contract.py
git commit -m "Expose native WeChat collection API routes

The native collector is now reachable through a separate API namespace while
the exporter-backed namespace remains intact.

Constraint: Do not change existing /api/wechat-collect behavior
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_api_contract.py tests/test_wechat_collect_integration.py -q"
```

---

### Task 11: Add Frontend API Client and Route Wiring

**Files:**
- Create: `frontend-vue/src/api/wechatNativeCollect.ts`
- Create: `tests/test_wechat_native_frontend_contract.py`
- Modify: `frontend-vue/src/router/index.ts`
- Modify: `frontend-vue/src/components/layout/AppSider.vue`
- Modify: `frontend-vue/src/components/layout/AppHeader.vue`
- Modify: `frontend-vue/src/locales/zh.json`
- Modify: `frontend-vue/src/locales/en.json`

- [ ] **Step 1: Write frontend static contract test**

Create `tests/test_wechat_native_frontend_contract.py`:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_wechat_frontend_route_and_nav_are_wired():
    router = (ROOT / "frontend-vue" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
    sider = (ROOT / "frontend-vue" / "src" / "components" / "layout" / "AppSider.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend-vue" / "src" / "api" / "wechatNativeCollect.ts").read_text(encoding="utf-8")
    zh = (ROOT / "frontend-vue" / "src" / "locales" / "zh.json").read_text(encoding="utf-8")
    en = (ROOT / "frontend-vue" / "src" / "locales" / "en.json").read_text(encoding="utf-8")

    assert "/wechat-native-collect" in router
    assert "WechatNativeCollect.vue" in router
    assert "wechatNativeCollect" in sider
    assert "/api/wechat-native/login/start" in api
    assert "/api/wechat-native/tasks/start" in api
    assert '"wechatNativeCollect"' in zh
    assert '"wechatNativeCollect"' in en
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_frontend_contract.py -q
```

Expected: fails because frontend files are not wired.

- [ ] **Step 3: Create frontend API client**

Create `frontend-vue/src/api/wechatNativeCollect.ts`:

```ts
import request from '@/api/request'

export type WechatNativeFormat = 'html' | 'markdown' | 'text' | 'json'

export interface WechatNativeSession {
  session_id: string
  nickname: string
  avatar: string
  status: string
  expires_at: string
  last_error?: string
}

export interface WechatNativeStartPayload {
  session_id: string
  source_mode?: 'url' | 'fakeid' | 'urls'
  article_url?: string
  fakeid?: string
  account_name?: string
  urls?: string[]
  keyword?: string
  format?: WechatNativeFormat
  output_dir?: string
  max_articles?: number
  delay_seconds?: number
}

export interface WechatNativeTask {
  task_id: string
  provider: 'native' | string
  status: string
  total: number
  completed: number
  success: number
  failed: number
  current?: string
  output_dir?: string
  error?: string
  results?: Array<Record<string, any>>
  created_at?: string
  finished_at?: string
}

export default {
  getConfig() {
    return request.get('/api/wechat-native/config')
  },
  listSessions() {
    return request.get<{ sessions: WechatNativeSession[] }>('/api/wechat-native/sessions')
  },
  startLogin() {
    return request.post<{ login_id: string; status: string }>('/api/wechat-native/login/start', {})
  },
  getQrCodeUrl(loginId: string) {
    return `/api/wechat-native/login/${loginId}/qrcode`
  },
  pollScan(loginId: string) {
    return request.get(`/api/wechat-native/login/${loginId}/scan`)
  },
  confirmLogin(loginId: string) {
    return request.post(`/api/wechat-native/login/${loginId}/confirm`, {})
  },
  searchAccounts(sessionId: string, keyword: string, begin = 0, size = 5) {
    return request.post('/api/wechat-native/accounts/search', {
      session_id: sessionId,
      keyword,
      begin,
      size,
    })
  },
  preview(payload: WechatNativeStartPayload & { limit?: number }) {
    return request.post('/api/wechat-native/articles/preview', payload)
  },
  start(payload: WechatNativeStartPayload) {
    return request.post<{ task_id: string; status: string }>('/api/wechat-native/tasks/start', payload)
  },
  listTasks() {
    return request.get<{ tasks: WechatNativeTask[] }>('/api/wechat-native/tasks')
  },
  getTask(taskId: string) {
    return request.get<WechatNativeTask>(`/api/wechat-native/tasks/${taskId}`)
  },
  cancelTask(taskId: string) {
    return request.post(`/api/wechat-native/tasks/${taskId}/cancel`, {})
  },
}
```

- [ ] **Step 4: Add route**

In `frontend-vue/src/router/index.ts`, add:

```ts
{
  path: '/wechat-native-collect',
  name: 'wechatNativeCollect',
  meta: { keepAlive: false },
  component: () => import('@/views/WechatNativeCollect.vue'),
},
```

- [ ] **Step 5: Add sidebar item**

In `AppSider.vue`, add an icon constant:

```ts
const wechatNativeCollectIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 8a7 7 0 0 1 7-5c4 0 7 2.8 7 6.2 0 3.1-2.8 5.7-6.5 6.1L7 20l1.2-4.1A6.8 6.8 0 0 1 4 8z"/><path d="M9 8h6"/><path d="M9 12h4"/><path d="M19 11c1.3 1 2 2.4 2 4 0 1.6-.8 3-2.1 4l.6 2-2.3-1.4c-.7.2-1.4.4-2.2.4"/></svg>`
```

Add to `navItems` after the current `wechatCollect` item:

```ts
{ key: 'wechatNativeCollect', path: '/wechat-native-collect', icon: wechatNativeCollectIcon },
```

Add to `explicitNavLabels`:

```ts
wechatNativeCollect: 'nav.wechatNativeCollect',
```

- [ ] **Step 6: Add header mapping**

In `frontend-vue/src/components/layout/AppHeader.vue`, add:

```ts
'/wechat-native-collect': 'nav.wechatNativeCollect',
```

Use the existing object style in the file, keeping commas valid.

- [ ] **Step 7: Add locale keys**

In `frontend-vue/src/locales/zh.json`, add:

```json
"wechatNativeCollect": "公众号原生采集"
```

under `nav`, and add top-level:

```json
"wechatNative": {
  "title": "公众号原生采集",
  "desc": "使用本地扫码登录和自有会话拉取公众号文章，第三方导出接口仍保留在原采集页。",
  "login": "扫码登录",
  "refresh": "刷新",
  "sessions": "登录会话",
  "sourceTitle": "采集来源",
  "previewTitle": "文章预览",
  "tasksTitle": "采集任务",
  "start": "开始采集",
  "preview": "预览",
  "cancel": "取消",
  "session": "登录会话",
  "articleUrl": "文章链接",
  "fakeid": "公众号 fakeid",
  "urls": "文章链接列表",
  "keyword": "关键词",
  "format": "导出格式",
  "outputDir": "输出目录",
  "maxArticles": "最大文章数",
  "delaySeconds": "间隔秒数",
  "status": {
    "pending": "等待中",
    "running": "运行中",
    "done": "完成",
    "error": "失败",
    "cancelled": "已取消"
  }
}
```

In `frontend-vue/src/locales/en.json`, add matching keys:

```json
"wechatNativeCollect": "WeChat Native Collect"
```

under `nav`, and:

```json
"wechatNative": {
  "title": "WeChat Native Collect",
  "desc": "Collect Official Account articles with local QR login and self-owned sessions. The third-party exporter path remains available on the original collect page.",
  "login": "QR Login",
  "refresh": "Refresh",
  "sessions": "Sessions",
  "sourceTitle": "Source",
  "previewTitle": "Preview",
  "tasksTitle": "Tasks",
  "start": "Start",
  "preview": "Preview",
  "cancel": "Cancel",
  "session": "Session",
  "articleUrl": "Article URL",
  "fakeid": "Official Account fakeid",
  "urls": "Article URLs",
  "keyword": "Keyword",
  "format": "Format",
  "outputDir": "Output Directory",
  "maxArticles": "Max Articles",
  "delaySeconds": "Delay Seconds",
  "status": {
    "pending": "Pending",
    "running": "Running",
    "done": "Done",
    "error": "Error",
    "cancelled": "Cancelled"
  }
}
```

- [ ] **Step 8: Run contract test**

Run:

```powershell
python -m pytest tests/test_wechat_native_frontend_contract.py -q
```

Expected: pass after the view file is added in the next task. It may still fail at this step because `WechatNativeCollect.vue` is not created yet.

- [ ] **Step 9: Commit route/API wiring**

Commit after Task 12 if the static test still needs the view file.

---

### Task 12: Build Native Collector Vue Page

**Files:**
- Create: `frontend-vue/src/views/WechatNativeCollect.vue`
- Modify: `frontend-vue/src/views/WechatCollect.vue`
- Test: `tests/test_wechat_native_frontend_contract.py`

- [ ] **Step 1: Create `WechatNativeCollect.vue`**

Build the page with the same visual structure as `WechatCollect.vue`: page header, source card, preview card, task card. Use this script contract:

```ts
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NTag,
  useMessage,
} from 'naive-ui'
import wechatNativeApi, {
  type WechatNativeSession,
  type WechatNativeTask,
} from '@/api/wechatNativeCollect'

type SourceMode = 'url' | 'fakeid' | 'urls'

const { t } = useI18n()
const message = useMessage()
const sourceMode = ref<SourceMode>('url')
const sessions = ref<WechatNativeSession[]>([])
const selectedSessionId = ref('')
const tasks = ref<WechatNativeTask[]>([])
const selectedTaskId = ref('')
const selectedTask = ref<WechatNativeTask | null>(null)
const loginId = ref('')
const qrCodeUrl = ref('')
const loginMessage = ref('')
const previewArticles = ref<Array<Record<string, any>>>([])
const previewAccount = ref<Record<string, any>>({})
const loading = ref(false)
const loginPolling = ref<number | null>(null)
const taskPolling = ref<number | null>(null)

const form = reactive({
  article_url: '',
  fakeid: '',
  account_name: '',
  urlsText: '',
  keyword: '',
  format: 'markdown',
  output_dir: '',
  max_articles: 50,
  delay_seconds: 1,
})

const formatOptions = computed(() => [
  { label: 'Markdown', value: 'markdown' },
  { label: 'HTML', value: 'html' },
  { label: 'Text', value: 'text' },
  { label: 'JSON', value: 'json' },
])

const sessionOptions = computed(() => sessions.value.map((item) => ({
  label: `${item.nickname || item.session_id} · ${item.status}`,
  value: item.session_id,
})))

const parsedUrls = computed(() => form.urlsText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))
```

Use these core methods:

```ts
function basePayload() {
  return {
    session_id: selectedSessionId.value,
    source_mode: sourceMode.value,
    article_url: sourceMode.value === 'url' ? form.article_url.trim() : undefined,
    fakeid: sourceMode.value === 'fakeid' ? form.fakeid.trim() : undefined,
    account_name: sourceMode.value === 'fakeid' ? form.account_name.trim() : undefined,
    urls: sourceMode.value === 'urls' ? parsedUrls.value : undefined,
    keyword: form.keyword.trim() || undefined,
    format: form.format as any,
    output_dir: form.output_dir.trim() || undefined,
    max_articles: form.max_articles || undefined,
    delay_seconds: form.delay_seconds ?? undefined,
  }
}

async function loadSessions() {
  const res = await wechatNativeApi.listSessions()
  sessions.value = Array.isArray(res.data?.sessions) ? res.data.sessions : []
  if (!selectedSessionId.value && sessions.value.length) {
    selectedSessionId.value = sessions.value[0].session_id
  }
}

async function startLogin() {
  const res = await wechatNativeApi.startLogin()
  loginId.value = String(res.data.login_id || '')
  qrCodeUrl.value = wechatNativeApi.getQrCodeUrl(loginId.value)
  loginMessage.value = ''
  startLoginPolling()
}

function startLoginPolling() {
  stopLoginPolling()
  loginPolling.value = window.setInterval(async () => {
    if (!loginId.value) return
    const res = await wechatNativeApi.pollScan(loginId.value)
    const status = Number((res.data as any)?.status || 0)
    if (status === 1) {
      loginMessage.value = '已确认，正在登录'
      const confirmed = await wechatNativeApi.confirmLogin(loginId.value)
      selectedSessionId.value = String((confirmed.data as any)?.session_id || '')
      stopLoginPolling()
      qrCodeUrl.value = ''
      await loadSessions()
    } else if (status === 4 || status === 6) {
      loginMessage.value = '扫码成功，等待确认'
    }
  }, 2000)
}

function stopLoginPolling() {
  if (loginPolling.value !== null) {
    window.clearInterval(loginPolling.value)
    loginPolling.value = null
  }
}
```

Use these collection methods:

```ts
async function preview() {
  if (!selectedSessionId.value) {
    message.error(t('wechatNative.session'))
    return
  }
  const res = await wechatNativeApi.preview({ ...basePayload(), limit: Math.min(form.max_articles || 20, 20) })
  previewAccount.value = (res.data as any)?.account || {}
  previewArticles.value = Array.isArray((res.data as any)?.articles) ? (res.data as any).articles : []
}

async function startTask() {
  const res = await wechatNativeApi.start(basePayload())
  const taskId = String(res.data?.task_id || '')
  await loadTasks()
  if (taskId) {
    await selectTask(taskId)
  }
}

async function loadTasks() {
  const res = await wechatNativeApi.listTasks()
  tasks.value = Array.isArray(res.data?.tasks) ? res.data.tasks : []
}

async function selectTask(taskId: string) {
  selectedTaskId.value = taskId
  const res = await wechatNativeApi.getTask(taskId)
  selectedTask.value = res.data
  ensureTaskPolling()
}

function ensureTaskPolling() {
  stopTaskPolling()
  if (selectedTask.value?.status !== 'running') return
  taskPolling.value = window.setInterval(async () => {
    if (!selectedTaskId.value) return
    const res = await wechatNativeApi.getTask(selectedTaskId.value)
    selectedTask.value = res.data
    if (res.data.status !== 'running') {
      stopTaskPolling()
      await loadTasks()
    }
  }, 2500)
}

function stopTaskPolling() {
  if (taskPolling.value !== null) {
    window.clearInterval(taskPolling.value)
    taskPolling.value = null
  }
}
```

The template should mirror `WechatCollect.vue` but include:

- session selector at top of source form
- QR login button and QR image panel
- source mode segmented control
- preview account + article list
- task list/detail with progress and cancel
- action links on successful result rows:
  - open file path if file endpoint exists later
  - copy path is not needed; display path text is enough
  - future AI link can be added after Task 14

- [ ] **Step 2: Clarify old collector page**

In `frontend-vue/src/views/WechatCollect.vue`, change only the page description text via i18n if needed. Do not change form behavior.

Add locale text:

```json
"thirdPartyDesc": "通过 wechat-article-exporter 兼容接口采集，适合继续使用已有第三方或自托管 exporter 服务。"
```

Use it in the page description if the current key is too generic.

- [ ] **Step 3: Run static frontend tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_frontend_contract.py -q
```

Expected: pass.

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd frontend-vue
npm run build
cd ..
```

Expected: Vite build completes without TypeScript/template errors.

- [ ] **Step 5: Commit frontend route/page**

```bash
git add frontend-vue/src/api/wechatNativeCollect.ts frontend-vue/src/views/WechatNativeCollect.vue frontend-vue/src/router/index.ts frontend-vue/src/components/layout/AppSider.vue frontend-vue/src/components/layout/AppHeader.vue frontend-vue/src/locales/zh.json frontend-vue/src/locales/en.json frontend-vue/src/views/WechatCollect.vue tests/test_wechat_native_frontend_contract.py
git commit -m "Add native WeChat collection workspace

Users can now distinguish the retained exporter API collector from the new
self-controlled native collection path in the sidebar and UI.

Constraint: Keep the visual language aligned with existing Naive UI pages
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_frontend_contract.py -q; npm run build"
```

---

### Task 13: Add Proxy Policy for Native WeChat Requests

**Files:**
- Create: `monitor/wechat_collect/proxy_policy.py`
- Modify: `monitor/wechat_collect/native_login.py`
- Modify: `monitor/wechat_collect/native_client.py`
- Modify: `monitor/wechat_collect/html_export.py`
- Test: `tests/test_wechat_native_tasks.py`

- [ ] **Step 1: Add proxy policy tests**

Append to `tests/test_wechat_native_tasks.py`:

```python
def test_native_proxy_policy_disallows_free_proxy_with_login_cookies(monkeypatch):
    from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan

    class Route:
        proxy = "http://free.example.test:8080"
        proxy_pool = None
        resolved_proxy_source = "system_free"
        provider_tier = "free"
        reason = "free"
        warnings = []
        masked_proxy_endpoint = "http://free.example.test:8080"

    def fake_resolve(account, is_auto_download=False, cookies_file_present=False, user_forced_direct=False):
        return Route()

    monkeypatch.setattr("monitor.wechat_collect.proxy_policy.proxy_router.resolve_proxy_download", fake_resolve)

    plan = resolve_native_proxy_plan({"download_proxy_mode": "system_only"}, cookies_present=True)

    assert plan.proxies == []
    assert plan.source == "direct"
    assert "Cookie" in " ".join(plan.warnings)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_tasks.py::test_native_proxy_policy_disallows_free_proxy_with_login_cookies -q
```

Expected: fails because `proxy_policy.py` does not exist.

- [ ] **Step 3: Implement policy module**

Create `monitor/wechat_collect/proxy_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

import monitor.proxy.router as proxy_router


@dataclass
class NativeProxyPlan:
    proxies: list[str] = field(default_factory=list)
    source: str = "direct"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def requests_proxies(self) -> dict[str, str] | None:
        if not self.proxies:
            return None
        proxy = self.proxies[0]
        return {"http": proxy, "https": proxy}


def resolve_native_proxy_plan(account: dict | None = None, *, cookies_present: bool = False) -> NativeProxyPlan:
    account = dict(account or {})
    account.setdefault("download_proxy_mode", "system_only")
    route = proxy_router.resolve_proxy_download(
        account,
        is_auto_download=False,
        cookies_file_present=cookies_present,
        user_forced_direct=False,
    )
    tier = getattr(route, "provider_tier", "") or ""
    source = getattr(route, "resolved_proxy_source", "") or "direct"
    if cookies_present and tier == "free":
        return NativeProxyPlan(
            proxies=[],
            source="direct",
            reason="Cookie 请求禁止使用免费代理，退回直连",
            warnings=["Cookie 请求禁止使用免费动态代理"],
        )
    proxies = list(getattr(route, "proxy_pool", None) or [])
    proxy = getattr(route, "proxy", None)
    if proxy:
        proxies.insert(0, proxy)
    return NativeProxyPlan(
        proxies=[item for item in proxies if item],
        source=source,
        reason=getattr(route, "reason", "") or "",
        warnings=list(getattr(route, "warnings", []) or []),
    )
```

- [ ] **Step 4: Thread proxy plan into native HTTP calls**

In `native_login.py`, accept `proxies` in constructor:

```python
def __init__(self, *, session_factory=None, store: NativeSessionStore | None = None, proxy_plan=None):
    self._session_factory = session_factory or requests.Session
    self._store = store or NativeSessionStore()
    self._proxy_plan = proxy_plan
    self._pending = {}
```

For each `session.get` / `session.post`, pass:

```python
proxies=self._proxy_plan.requests_proxies if self._proxy_plan else None
```

In `native_client.py`, accept `proxy_plan=None` and pass `proxies=...` for WeChat backend calls.

In `html_export.py`, accept `proxies: dict[str, str] | None = None` in `download_article` and pass it to `http.get`.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_wechat_native_tasks.py tests/test_wechat_native_login_flow.py tests/test_wechat_native_client.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add monitor/wechat_collect/proxy_policy.py monitor/wechat_collect/native_login.py monitor/wechat_collect/native_client.py monitor/wechat_collect/html_export.py tests/test_wechat_native_tasks.py
git commit -m "Route native WeChat traffic through existing proxy policy

Native collection reuses the current proxy router but avoids sending login
cookies through free dynamic proxies.

Constraint: WeChat login cookies are sensitive and IP-sticky
Rejected: Independent native proxy configuration | duplicates the existing router and pool model
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_tasks.py tests/test_wechat_native_login_flow.py tests/test_wechat_native_client.py -q"
```

---

### Task 14: Link Native Results to AI Creation Without Reusing Video Inputs

**Files:**
- Modify: `frontend-vue/src/views/WechatNativeCollect.vue`
- Modify: `frontend-vue/src/views/AiCreation.vue`
- Modify: `frontend-vue/src/api/aiContent.ts`
- Modify: `server/__main__.py`
- Modify: `scripts/article_generator.py`
- Modify: `monitor/schema.sql` and `monitor/db.py` only if the article task table needs new input columns on the current branch
- Test: `tests/test_ai_content_api_contract.py`
- Test: `tests/test_wechat_native_frontend_contract.py`

- [ ] **Step 1: Add contract tests that prevent WeChat articles from entering the video pipeline**

Append to `tests/test_wechat_native_frontend_contract.py`:

```python
def test_native_wechat_result_links_to_ai_creation():
    native_view = (ROOT / "frontend-vue" / "src" / "views" / "WechatNativeCollect.vue").read_text(encoding="utf-8")
    ai_view = (ROOT / "frontend-vue" / "src" / "views" / "AiCreation.vue").read_text(encoding="utf-8")

    assert "openAiCreation" in native_view
    assert "sourceType" in native_view
    assert "wechatArticle" in native_view
    assert "articlePath" in native_view
    assert "getQueryString('sourceType')" in ai_view or "getQueryString(\"sourceType\")" in ai_view
    assert "getQueryString('articlePath')" in ai_view or "getQueryString(\"articlePath\")" in ai_view
    assert "videoUrl: String(item.url" not in native_view
```

Append to `tests/test_ai_content_api_contract.py`:

```python
def test_article_generate_accepts_wechat_article_source_without_video_url():
    server = SERVER_MAIN.read_text(encoding="utf-8")
    generator = (ROOT / "scripts" / "article_generator.py").read_text(encoding="utf-8")

    assert "source_type" in server
    assert "wechat_article" in server
    assert "article_source_path" in server or "article_text" in server
    assert "wechat_article" in generator
    assert "yt_dlp" in generator
```

The test intentionally keeps `yt_dlp` present for video tasks but requires a separate `wechat_article` branch.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest tests/test_wechat_native_frontend_contract.py::test_native_wechat_result_links_to_ai_creation -q
python -m pytest tests/test_ai_content_api_contract.py::test_article_generate_accepts_wechat_article_source_without_video_url -q
```

Expected: fails until the WeChat article input branch and UI links are added.

- [ ] **Step 3: Extend the AI article API payload for non-video article sources**

In `frontend-vue/src/api/aiContent.ts`, extend `ArticleTaskCreatePayload`:

```ts
export interface ArticleTaskCreatePayload {
  source_type?: 'video' | 'wechat_article'
  monitor_video_id?: number
  video_id?: string
  video_url?: string
  video_title?: string
  article_source_path?: string
  article_text?: string
  source_url?: string
  source_title?: string
  target_lang?: string
  auto_translate?: boolean
}
```

- [ ] **Step 4: Add backend handling for `source_type='wechat_article'`**

In `server/__main__.py`, update `_api_article_generate` before the current video validation:

```python
source_type = str(body.get("source_type") or "video").strip() or "video"
if source_type == "wechat_article":
    article_source_path = str(body.get("article_source_path") or "").strip()
    article_text = str(body.get("article_text") or "").strip()
    if not article_source_path and not article_text:
        self._send_json({"error": "article_source_path 或 article_text 至少提供一个"}, 400)
        return
    if article_source_path:
        cfg = _db.load_config()
        data_dir = str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))
        configured_root = cfg.get("wechat_collection_output_dir") or _wechat_collector.default_collection_output_dir(data_dir)
        try:
            resolved_path = _normalize_fs_path(article_source_path)
            allowed_root = _normalize_fs_path(configured_root)
            if not _is_path_within(resolved_path, allowed_root):
                raise ValueError("文章路径必须位于公众号采集输出目录下")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
```

Then persist enough input metadata for `scripts/article_generator.py` to load either `article_source_path` or `article_text`. If the existing `article_tasks` schema lacks columns, add a narrow migration with `source_type`, `article_source_path`, `article_text`, `source_url`, and `source_title`.

- [ ] **Step 5: Add a WeChat article branch in `scripts/article_generator.py`**

Before the current subtitle/audio workflow, branch by task source:

```python
if task.get("source_type") == "wechat_article":
    article_text = task.get("article_text") or ""
    article_source_path = task.get("article_source_path") or ""
    if not article_text and article_source_path:
        article_text = Path(article_source_path).read_text(encoding="utf-8", errors="ignore")
    if not article_text.strip():
        raise RuntimeError("公众号文章内容为空，无法生成 AI 文章")
    transcript = article_text
    transcript_source = "wechat_article"
    video_url = task.get("source_url") or ""
    video_title = task.get("source_title") or task.get("video_title") or ""
else:
    # Existing video-to-article subtitle/audio/Whisper workflow remains unchanged.
```

This keeps native WeChat collection decoupled from `yt-dlp` and Whisper while still reusing the downstream outline/draft/publish pipeline.

- [ ] **Step 6: Add AI action in native result rows**

In `WechatNativeCollect.vue`, add:

```ts
import { useRouter } from 'vue-router'

const router = useRouter()

function openAiCreation(item: Record<string, any>) {
  router.push({
    path: '/ai-creation',
    query: {
      tab: 'article',
      sourceType: 'wechatArticle',
      articlePath: String(item.path || ''),
      articleUrl: String(item.url || ''),
      articleTitle: String(item.title || ''),
    },
  })
}
```

In each successful result row, add:

```vue
<NButton
  v-if="item.status === 'success'"
  text
  type="primary"
  size="small"
  @click="openAiCreation(item)"
>
  {{ t('aiCreation.articleTab') }}
</NButton>
```

- [ ] **Step 7: Make AI Creation prefill the new WeChat article source**

In `AiCreation.vue`, add fields to the article form and route prefill:

```ts
const sourceType = getQueryString('sourceType')
if (sourceType === 'wechatArticle') {
  articleForm.source_type = 'wechat_article'
  articleForm.article_source_path = getQueryString('articlePath')
  articleForm.source_url = getQueryString('articleUrl')
  articleForm.source_title = getQueryString('articleTitle')
  articleForm.video_url = ''
  articleForm.video_title = getQueryString('articleTitle')
  currentTab.value = 'article'
}
```

Update `clearArticlePrefill()` to remove `sourceType`, `articlePath`, `articleUrl`, and `articleTitle`.

- [ ] **Step 8: Run tests and frontend build**

Run:

```powershell
python -m pytest tests/test_wechat_native_frontend_contract.py -q
python -m pytest tests/test_ai_content_api_contract.py -q
cd frontend-vue
npm run build
cd ..
```

Expected: tests and build pass.

- [ ] **Step 9: Commit**

```bash
git add frontend-vue/src/views/WechatNativeCollect.vue frontend-vue/src/views/AiCreation.vue frontend-vue/src/api/aiContent.ts server/__main__.py scripts/article_generator.py monitor/schema.sql monitor/db.py tests/test_wechat_native_frontend_contract.py tests/test_ai_content_api_contract.py
git commit -m "Connect native WeChat articles to AI article creation

Collected WeChat article files can now become AI article inputs without being
misclassified as source videos.

Constraint: The existing video-to-article pipeline still depends on yt-dlp and Whisper
Rejected: Passing mp.weixin.qq.com links as videoUrl | routes WeChat articles into video media extraction
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_wechat_native_frontend_contract.py tests/test_ai_content_api_contract.py -q; npm run build"
```

---

### Task 15: End-to-End Verification and Documentation

**Files:**
- Create: `docs/wechat-native-collector.md`
- Modify: `README.md` if feature list needs a short mention

- [ ] **Step 1: Write native collector docs**

Create `docs/wechat-native-collector.md`:

```markdown
# WeChat Native Collector

The native collector is a first-party alternative to the exporter API collector.
It keeps the existing third-party collector available while adding local QR
login, local session storage, article list fetching, and local article export.

## Modes

- Exporter API collector: `/wechat-collect`, backed by `wechat_exporter_base_url`
- Native collector: `/wechat-native-collect`, backed by local WeChat MP login

## Native Login

The login flow mirrors WeChat MP:

1. Start a login session.
2. Display the QR code.
3. Poll scan status.
4. Confirm login after the user approves.
5. Store token and cookies encrypted in SQLite.

## Operational Guidance

- Use low concurrency and a non-zero delay for batch collection.
- Prefer sticky paid or trusted local proxies for login/session traffic.
- Avoid free proxies for any Cookie-bearing request.
- Re-login when a session is marked expired or error.

## Limitations

- P0 exports HTML, Markdown, Text, and JSON with lightweight parsing.
- High-fidelity resource packaging, PDF/docx, reading metrics, and comments are future extensions.
- Paid article full-content access may require additional credentials.
```

- [ ] **Step 2: Run backend unit tests**

Run:

```powershell
python -m pytest tests/test_wechat_collect_integration.py tests/test_wechat_native_schema.py tests/test_wechat_native_session_store.py tests/test_wechat_native_login_flow.py tests/test_wechat_native_client.py tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py -q
```

Expected: all pass.

- [ ] **Step 3: Run broader relevant tests**

Run:

```powershell
python -m pytest tests/test_sensitive_secret_masking.py tests/test_ai_content_api_contract.py tests/test_wechat_publish_invalid_ip_guidance.py -q
```

Expected: pass. These guard config masking, AI linkage assumptions, and WeChat publish behavior.

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd frontend-vue
npm run build
cd ..
```

Expected: build succeeds.

- [ ] **Step 5: Manual smoke test**

Run the local server using the repository's usual command. If no single command is documented for the current branch, use the same entrypoint already used for the Vue monitor server.

Manual checks:

- Open the app.
- Verify both sidebar entries exist:
  - `公众号采集` for exporter API collection.
  - `公众号原生采集` for native collection.
- On native page, start QR login and confirm:
  - QR image loads.
  - Scan status changes after scanning.
  - Confirm returns a session row.
- Preview by fakeid or article URL.
- Start a 1-article Markdown task with `delay_seconds=0`.
- Poll task until `done`.
- Confirm output file exists under `wechat_collection_output_dir`.
- Use the AI creation action from a successful result.
- Confirm old `/wechat-collect` page still loads and old tests still pass.

- [ ] **Step 6: Commit docs and verification updates**

```bash
git add docs/wechat-native-collector.md README.md
git commit -m "Document native WeChat collector operations

The native collector introduces local login and session ownership, so operators
need clear guidance on modes, proxy safety, and current limitations.

Constraint: Existing exporter API collector remains documented as a separate mode
Confidence: high
Scope-risk: narrow
Tested: python -m pytest tests/test_wechat_collect_integration.py tests/test_wechat_native_schema.py tests/test_wechat_native_session_store.py tests/test_wechat_native_login_flow.py tests/test_wechat_native_client.py tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py -q; npm run build"
```

---

## Final Verification Checklist

- [ ] Existing exporter API collector routes still pass `tests/test_wechat_collect_integration.py`.
- [ ] Native schema exists on fresh DB and migration path.
- [ ] Native token/cookie values are encrypted at rest and absent from API responses.
- [ ] Native QR login flow works with a fake transport and manually with real WeChat MP.
- [ ] Native article search/list/download works with fake transport and manually with a small real collection.
- [ ] Native tasks persist to SQLite and survive UI refresh.
- [ ] Cancel works for running native tasks.
- [ ] Output path is restricted under `wechat_collection_output_dir`.
- [ ] Free dynamic proxies are not used for Cookie-bearing native traffic.
- [ ] Frontend build succeeds.
- [ ] UI has separate, clearly labeled exporter API and native collection entries.
- [ ] Native results can hand off to AI Creation.

## Rollout Notes

- Roll out behind separate navigation; do not replace existing collection.
- Treat native collection as beta until real-world login/session expiry behavior is observed.
- Default `max_articles` should remain modest, ideally `50`, and default delay should remain at least `1` second.
- Use logs that mask proxy endpoints and never log token/cookie values.
- If WeChat returns session-expired codes, mark the native session `expired` and surface a re-login action.

## Follow-Up Plans

Create separate implementation plans for:

1. High-fidelity HTML packaging with local resources and original layout preservation.
2. PDF/docx export using a deliberate browser/rendering strategy.
3. Reading/like/comment/comment-reply collection using mobile credentials.
4. Native collection analytics and retry dashboard.

## Self-Review

Spec coverage:

- Existing third-party interface retained: Tasks 1, 10, 12, 15.
- New left sidebar function: Tasks 11 and 12.
- Native implementation from scratch: Tasks 2 through 10.
- Upstream dependencies considered: login/token/cookie in Tasks 4-6, proxy in Task 13, article pull/download in Tasks 6-9.
- Current project integration: persistent DB in Task 2, proxy router in Task 13, AI handoff in Task 14, WeChat publish remains available through existing AI page.
- UI consistency: Tasks 11 and 12.
- High cohesion/low coupling: provider boundary in Task 8 and package split throughout.

Placeholder scan:

- No step requires an unspecified dependency.
- Optional advanced features are explicitly separated into follow-up plans.
- Every code-writing task includes concrete files and runnable verification.

Type consistency:

- `session_id`, `task_id`, `source_mode`, `export_format`, `results`, and route paths are consistent across backend, tests, and frontend API client.

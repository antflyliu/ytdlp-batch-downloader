from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import secrets
from typing import Any
from urllib.parse import urlparse

from config.encryption import _decrypt_config_value, _encrypt_config_value
import monitor.db.connection as db_connection
from monitor.db.connection import get_connection
from monitor.db.db_core import _UNSET, now_iso
from monitor.email_collect.platforms import DEFAULT_CONTENT_TARGETS
from monitor.email_collect.security import validate_mail_endpoint

SECRET_COLUMNS = {
    "gmail_client_secret": "gmail_client_secret_enc",
    "gmail_refresh_token": "gmail_refresh_token_enc",
    "imap_password": "imap_password_enc",
    "smtp_password": "smtp_password_enc",
    "outlook_email_api_key": "outlook_email_api_key_enc",
}
DEFAULT_TARGETS = DEFAULT_CONTENT_TARGETS
OUTLOOK_EMAIL_DEFAULT_BASE_URL = "http://127.0.0.1:5000"
CONTENT_VARIANT_STATUSES = {"draft", "ready", "exported", "published"}
DEFAULT_GMAIL_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
LEGACY_GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _utc_stamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_account_email(provider: str, email_address: Any) -> str:
    email = str(email_address or "").strip()
    return email.lower() if str(provider or "").strip().lower() == "gmail" else email


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(value: str | None, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _normalize_scopes(value: Any, default: tuple[str, ...] = DEFAULT_GMAIL_OAUTH_SCOPES) -> list[str]:
    if value in (None, ""):
        raw_items: list[Any] = list(default)
    elif isinstance(value, str):
        raw_items = [item for chunk in value.split(",") for item in chunk.split()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = list(default)
    scopes: list[str] = []
    for item in raw_items:
        scope = str(item or "").strip()
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes or list(default)


def _hash_oauth_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            display_name TEXT NOT NULL,
            email_address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            gmail_client_id TEXT,
            gmail_client_secret_enc TEXT,
            gmail_refresh_token_enc TEXT,
            gmail_scope_json TEXT NOT NULL DEFAULT '[]',
            imap_host TEXT,
            imap_port INTEGER NOT NULL DEFAULT 993,
            imap_security TEXT NOT NULL DEFAULT 'ssl',
            imap_username TEXT,
            imap_password_enc TEXT,
            smtp_host TEXT,
            smtp_port INTEGER NOT NULL DEFAULT 465,
            smtp_security TEXT NOT NULL DEFAULT 'ssl',
            smtp_username TEXT,
            smtp_password_enc TEXT,
            outlook_email_base_url TEXT,
            outlook_email_api_key_enc TEXT,
            outlook_email_remote_email TEXT,
            outlook_email_folder TEXT NOT NULL DEFAULT 'all',
            outlook_email_subject_contains TEXT,
            outlook_email_from_contains TEXT,
            outlook_email_keyword TEXT,
            sync_mode TEXT NOT NULL DEFAULT 'poll',
            poll_interval_seconds INTEGER NOT NULL DEFAULT 300,
            include_spam_trash INTEGER NOT NULL DEFAULT 0,
            max_messages_per_sync INTEGER NOT NULL DEFAULT 20,
            last_sync_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    _ensure_email_account_outlook_columns(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_accounts_provider ON email_accounts(provider, status)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_accounts_email_provider ON email_accounts(provider, email_address)")
    _dedupe_gmail_account_email_case(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_accounts_gmail_email_nocase "
        "ON email_accounts(email_address COLLATE NOCASE) WHERE provider='gmail'"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_mailboxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            provider_mailbox_id TEXT NOT NULL DEFAULT 'INBOX',
            display_name TEXT NOT NULL DEFAULT 'INBOX',
            enabled INTEGER NOT NULL DEFAULT 1,
            query TEXT,
            last_seen_uid TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_mailboxes_account ON email_mailboxes(account_id, enabled)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_email_mailboxes_account_provider "
        "ON email_mailboxes(account_id, provider_mailbox_id)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_watch_state (
            account_id INTEGER PRIMARY KEY,
            gmail_history_id TEXT,
            gmail_watch_expiration TEXT,
            pubsub_topic TEXT,
            pubsub_subscription TEXT,
            last_full_sync_at TEXT,
            last_incremental_sync_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_oauth_states (
            state_hash TEXT PRIMARY KEY,
            account_id INTEGER,
            provider TEXT NOT NULL DEFAULT 'gmail',
            requested_scopes_json TEXT NOT NULL DEFAULT '[]',
            redirect_uri TEXT NOT NULL,
            return_to TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
        )"""
    )
    _ensure_oauth_state_optional_account(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_oauth_states_account "
        "ON email_oauth_states(account_id, consumed_at, expires_at)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            mailbox_id INTEGER,
            provider TEXT NOT NULL,
            provider_message_id TEXT NOT NULL,
            provider_thread_id TEXT,
            rfc_message_id TEXT,
            subject TEXT,
            from_addr TEXT,
            to_addr TEXT,
            cc_addr TEXT,
            received_at TEXT,
            sent_at TEXT,
            snippet TEXT,
            body_text TEXT,
            body_markdown_path TEXT,
            raw_mime_path TEXT,
            html_body_path TEXT,
            body_hash TEXT,
            dedupe_key TEXT,
            classification_json TEXT NOT NULL DEFAULT '{}',
            cleaning_report_json TEXT NOT NULL DEFAULT '{}',
            processing_status TEXT NOT NULL DEFAULT 'new',
            source_url TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (mailbox_id) REFERENCES email_mailboxes(id) ON DELETE SET NULL
        )"""
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_provider ON email_messages(account_id, provider, provider_message_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_messages_dedupe ON email_messages(account_id, dedupe_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_messages_received ON email_messages(received_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_messages_status ON email_messages(processing_status, received_at DESC)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            filename TEXT,
            content_type TEXT,
            size INTEGER DEFAULT 0,
            content_id TEXT,
            disposition TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (message_id) REFERENCES email_messages(id) ON DELETE CASCADE
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_attachments_message ON email_attachments(message_id)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_processing_tasks (
            task_id TEXT PRIMARY KEY,
            message_id INTEGER,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            current_stage TEXT,
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (message_id) REFERENCES email_messages(id) ON DELETE SET NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_processing_tasks_message ON email_processing_tasks(message_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_processing_tasks_status ON email_processing_tasks(status, created_at DESC)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS content_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            output_contract_json TEXT NOT NULL DEFAULT '{}',
            prompt_profile_json TEXT NOT NULL DEFAULT '{}',
            publish_mode TEXT NOT NULL DEFAULT 'export',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_targets_enabled ON content_targets(enabled, platform)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS content_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            article_task_id TEXT,
            target_id INTEGER,
            platform TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            body_path TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            quality_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (target_id) REFERENCES content_targets(id) ON DELETE SET NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_variants_source ON content_variants(source_type, source_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_variants_platform ON content_variants(platform, status)")
    _dedupe_content_variants_identity(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_content_variants_identity "
        "ON content_variants(source_type, source_id, platform)"
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS content_publication_tasks (
            task_id TEXT PRIMARY KEY,
            variant_id INTEGER,
            platform TEXT NOT NULL,
            publish_mode TEXT NOT NULL DEFAULT 'export',
            status TEXT NOT NULL DEFAULT 'pending',
            external_id TEXT,
            external_url TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (variant_id) REFERENCES content_variants(id) ON DELETE SET NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_publication_tasks_variant ON content_publication_tasks(variant_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_publication_tasks_status ON content_publication_tasks(status, created_at DESC)")
    _ensure_article_email_column(conn)
    _seed_content_targets(conn)


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _ensure_email_account_outlook_columns(conn) -> None:
    if not _table_exists(conn, "email_accounts"):
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(email_accounts)").fetchall()}
    for column, ddl in [
        ("outlook_email_base_url", "TEXT"),
        ("outlook_email_api_key_enc", "TEXT"),
        ("outlook_email_remote_email", "TEXT"),
        ("outlook_email_folder", "TEXT NOT NULL DEFAULT 'all'"),
        ("outlook_email_subject_contains", "TEXT"),
        ("outlook_email_from_contains", "TEXT"),
        ("outlook_email_keyword", "TEXT"),
    ]:
        if column not in columns:
            conn.execute(f"ALTER TABLE email_accounts ADD COLUMN {column} {ddl}")


def _ensure_oauth_state_optional_account(conn) -> None:
    if not _table_exists(conn, "email_oauth_states"):
        return
    columns = conn.execute("PRAGMA table_info(email_oauth_states)").fetchall()
    account_col = next((row for row in columns if row[1] == "account_id"), None)
    if not account_col or int(account_col[3] or 0) == 0:
        return
    legacy_table = "email_oauth_states_legacy_notnull"
    conn.execute("DROP TABLE IF EXISTS email_oauth_states_legacy_notnull")
    conn.execute("ALTER TABLE email_oauth_states RENAME TO email_oauth_states_legacy_notnull")
    conn.execute(
        """CREATE TABLE email_oauth_states (
            state_hash TEXT PRIMARY KEY,
            account_id INTEGER,
            provider TEXT NOT NULL DEFAULT 'gmail',
            requested_scopes_json TEXT NOT NULL DEFAULT '[]',
            redirect_uri TEXT NOT NULL,
            return_to TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            FOREIGN KEY (account_id) REFERENCES email_accounts(id) ON DELETE CASCADE
        )"""
    )
    conn.execute(
        """INSERT INTO email_oauth_states
           (state_hash, account_id, provider, requested_scopes_json, redirect_uri,
            return_to, created_at, expires_at, consumed_at)
           SELECT state_hash, account_id, provider, requested_scopes_json, redirect_uri,
                  return_to, created_at, expires_at, consumed_at
           FROM email_oauth_states_legacy_notnull"""
    )
    conn.execute(f"DROP TABLE {legacy_table}")


def _dedupe_gmail_account_email_case(conn) -> None:
    if not _table_exists(conn, "email_accounts"):
        return
    groups = conn.execute(
        """SELECT lower(email_address) AS normalized_email, COUNT(*) AS row_count
           FROM email_accounts
           WHERE provider='gmail'
           GROUP BY lower(email_address)
           HAVING row_count > 1"""
    ).fetchall()
    for group in groups:
        normalized_email = str(group[0] or "").strip().lower()
        if not normalized_email:
            continue
        rows = conn.execute(
            """SELECT id FROM email_accounts
               WHERE provider='gmail' AND lower(email_address)=?
               ORDER BY
                 CASE WHEN gmail_refresh_token_enc IS NOT NULL AND gmail_refresh_token_enc <> '' THEN 0 ELSE 1 END,
                 updated_at DESC,
                 id DESC""",
            (normalized_email,),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep_id = int(rows[0][0])
        stale_ids = [int(row[0]) for row in rows[1:]]
        placeholders = ",".join("?" for _ in stale_ids)

        if _table_exists(conn, "email_mailboxes"):
            keep_mailbox_ids = {
                str(row[0] or "")
                for row in conn.execute(
                    "SELECT provider_mailbox_id FROM email_mailboxes WHERE account_id=?",
                    (keep_id,),
                ).fetchall()
            }
            stale_mailboxes = conn.execute(
                f"""SELECT id, provider_mailbox_id FROM email_mailboxes
                    WHERE account_id IN ({placeholders})
                    ORDER BY updated_at DESC, id DESC""",
                stale_ids,
            ).fetchall()
            duplicate_ids = []
            seen_mailbox_ids = set(keep_mailbox_ids)
            for mailbox in stale_mailboxes:
                provider_mailbox_id = str(mailbox[1] or "")
                if provider_mailbox_id in seen_mailbox_ids:
                    duplicate_ids.append(int(mailbox[0]))
                else:
                    seen_mailbox_ids.add(provider_mailbox_id)
            if duplicate_ids:
                duplicate_placeholders = ",".join("?" for _ in duplicate_ids)
                conn.execute(
                    f"DELETE FROM email_mailboxes WHERE id IN ({duplicate_placeholders})",
                    duplicate_ids,
                )
            conn.execute(
                f"UPDATE email_mailboxes SET account_id=? WHERE account_id IN ({placeholders})",
                [keep_id, *stale_ids],
            )

        if _table_exists(conn, "email_watch_state"):
            keep_watch = conn.execute(
                "SELECT 1 FROM email_watch_state WHERE account_id=?",
                (keep_id,),
            ).fetchone()
            if keep_watch:
                conn.execute(
                    f"DELETE FROM email_watch_state WHERE account_id IN ({placeholders})",
                    stale_ids,
                )
            else:
                watch_rows = conn.execute(
                    f"""SELECT account_id FROM email_watch_state
                        WHERE account_id IN ({placeholders})
                        ORDER BY updated_at DESC, account_id DESC""",
                    stale_ids,
                ).fetchall()
                if watch_rows:
                    promoted_id = int(watch_rows[0][0])
                    conn.execute(
                        "UPDATE email_watch_state SET account_id=? WHERE account_id=?",
                        (keep_id, promoted_id),
                    )
                    remaining_ids = [stale_id for stale_id in stale_ids if stale_id != promoted_id]
                    if remaining_ids:
                        remaining_placeholders = ",".join("?" for _ in remaining_ids)
                        conn.execute(
                            f"DELETE FROM email_watch_state WHERE account_id IN ({remaining_placeholders})",
                            remaining_ids,
                        )

        if _table_exists(conn, "email_messages"):
            conn.execute(
                f"UPDATE OR IGNORE email_messages SET account_id=? WHERE account_id IN ({placeholders})",
                [keep_id, *stale_ids],
            )
        if _table_exists(conn, "email_oauth_states"):
            conn.execute(
                f"UPDATE email_oauth_states SET account_id=? WHERE account_id IN ({placeholders})",
                [keep_id, *stale_ids],
            )
        conn.execute(
            "UPDATE email_accounts SET email_address=?, updated_at=? WHERE id=?",
            (normalized_email, now_iso(), keep_id),
        )
        conn.execute(f"DELETE FROM email_accounts WHERE id IN ({placeholders})", stale_ids)

    conn.execute(
        "UPDATE email_accounts SET email_address=lower(email_address) WHERE provider='gmail'"
    )


def _dedupe_content_variants_identity(conn) -> None:
    if not _table_exists(conn, "content_variants"):
        return
    groups = conn.execute(
        """SELECT source_type, source_id, platform, COUNT(*) AS row_count
           FROM content_variants
           GROUP BY source_type, source_id, platform
           HAVING row_count > 1"""
    ).fetchall()
    publication_table_exists = _table_exists(conn, "content_publication_tasks")
    for group in groups:
        rows = conn.execute(
            """SELECT id FROM content_variants
               WHERE source_type=? AND source_id=? AND platform=?
               ORDER BY updated_at DESC, created_at DESC, id DESC""",
            (group[0], group[1], group[2]),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep_id = int(rows[0][0])
        stale_ids = [int(row[0]) for row in rows[1:]]
        placeholders = ",".join("?" for _ in stale_ids)
        if publication_table_exists:
            conn.execute(
                f"UPDATE content_publication_tasks SET variant_id=? WHERE variant_id IN ({placeholders})",
                [keep_id, *stale_ids],
            )
        conn.execute(f"DELETE FROM content_variants WHERE id IN ({placeholders})", stale_ids)


def _ensure_article_email_column(conn) -> None:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "article_tasks" not in tables:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(article_tasks)").fetchall()}
    if "email_message_id" not in cols:
        conn.execute("ALTER TABLE article_tasks ADD COLUMN email_message_id INTEGER DEFAULT NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_article_tasks_email_message "
        "ON article_tasks(email_message_id, created_at DESC)"
    )


def _seed_content_targets(conn) -> None:
    now = now_iso()
    for platform, display_name, publish_mode, contract, prompt_profile in DEFAULT_TARGETS:
        conn.execute(
            """INSERT INTO content_targets
               (platform, display_name, enabled, output_contract_json, prompt_profile_json,
                publish_mode, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?)
               ON CONFLICT(platform) DO NOTHING""",
            (platform, display_name, _json_dumps(contract), _json_dumps(prompt_profile), publish_mode, now, now),
        )
        row = conn.execute(
            "SELECT output_contract_json, prompt_profile_json FROM content_targets WHERE platform=?",
            (platform,),
        ).fetchone()
        if not row:
            continue
        existing_contract = _json_loads(row["output_contract_json"], {})
        existing_profile = _json_loads(row["prompt_profile_json"], {})
        merged_contract = _merge_missing_defaults(existing_contract, contract)
        merged_profile = _merge_missing_defaults(existing_profile, prompt_profile)
        if merged_contract != existing_contract or merged_profile != existing_profile:
            conn.execute(
                """UPDATE content_targets
                   SET output_contract_json=?, prompt_profile_json=?, updated_at=?
                   WHERE platform=?""",
                (_json_dumps(merged_contract), _json_dumps(merged_profile), now, platform),
            )


def _merge_missing_defaults(existing: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    result = dict(existing) if isinstance(existing, dict) else {}
    for key, value in defaults.items():
        if key not in result:
            result[key] = value
    return result


def _encrypt_secret(value: Any) -> str | None:
    text = str(value or "").strip()
    return _encrypt_config_value(text) if text else None


def _decrypt_secret(value: Any) -> str:
    text = str(value or "")
    return _decrypt_config_value(text) if text else ""


def _normalize_account(row, *, include_secrets: bool = False) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["include_spam_trash"] = bool(item.get("include_spam_trash"))
    item["gmail_scope"] = _normalize_scopes(_json_loads(item.pop("gmail_scope_json", "[]"), []), ())
    for public_name, column in SECRET_COLUMNS.items():
        encrypted = item.pop(column, None)
        item[f"has_{public_name}"] = bool(encrypted)
        if include_secrets:
            item[public_name] = _decrypt_secret(encrypted)
    return item


def create_oauth_state(
    *,
    account_id: int | None = None,
    scopes: list[str] | tuple[str, ...],
    redirect_uri: str,
    return_to: str = "",
    ttl_seconds: int = 600,
) -> str:
    state = secrets.token_urlsafe(32)
    now_dt = datetime.now(timezone.utc)
    expires_dt = now_dt + timedelta(seconds=max(60, int(ttl_seconds or 600)))
    now = _utc_stamp(now_dt)
    expires_at = _utc_stamp(expires_dt)
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM email_oauth_states WHERE consumed_at IS NOT NULL OR expires_at < ?",
            (now,),
        )
        conn.execute(
            """INSERT INTO email_oauth_states
               (state_hash, account_id, provider, requested_scopes_json, redirect_uri,
                return_to, created_at, expires_at, consumed_at)
               VALUES (?, ?, 'gmail', ?, ?, ?, ?, ?, NULL)""",
            (
                _hash_oauth_state(state),
                int(account_id) if account_id else None,
                _json_dumps(_normalize_scopes(scopes)),
                str(redirect_uri or ""),
                str(return_to or ""),
                now,
                expires_at,
            ),
        )
    return state


def consume_oauth_state(state: str) -> dict | None:
    now = _utc_stamp()
    state_hash = _hash_oauth_state(str(state or ""))
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE email_oauth_states
               SET consumed_at=?
               WHERE state_hash=?
                 AND consumed_at IS NULL
                 AND expires_at >= ?""",
            (now, state_hash, now),
        )
        if cursor.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM email_oauth_states WHERE state_hash=?",
            (state_hash,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
    item["requested_scopes"] = _normalize_scopes(
        _json_loads(item.pop("requested_scopes_json", "[]"), [])
    )
    return item


def _normalize_message(row, *, include_body: bool = False) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["classification"] = _json_loads(item.pop("classification_json", "{}"), {})
    item["cleaning_report"] = _json_loads(item.pop("cleaning_report_json", "{}"), {})
    if not include_body:
        item.pop("body_text", None)
    return item


def _variant_body_root() -> Path:
    return Path(str(db_connection._DATA_DIR)) / "email-content-variants"


def _read_variant_body(body_path: str | None) -> str:
    if not body_path:
        return ""
    try:
        root = _variant_body_root().resolve()
        candidate = Path(str(body_path)).resolve()
        candidate.relative_to(root)
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""
    return ""


def _normalize_target(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    item["output_contract"] = _json_loads(item.pop("output_contract_json", "{}"), {})
    item["prompt_profile"] = _json_loads(item.pop("prompt_profile_json", "{}"), {})
    return item


def _normalize_variant(row, *, include_body: bool = False) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _json_loads(item.pop("metadata_json", "{}"), {})
    item["quality"] = _json_loads(item.pop("quality_json", "{}"), {})
    if include_body:
        item["body"] = _read_variant_body(item.get("body_path"))
    return item


def _endpoint_changed(existing: dict | None, values: dict[str, Any], fields: tuple[str, ...]) -> bool:
    if not existing:
        return False
    return any((existing.get(field) or None) != (values.get(field) or None) for field in fields)


def _requires_secret_reentry(
    *,
    existing: dict | None,
    values: dict[str, Any],
    payload: dict[str, Any],
    service: str,
) -> bool:
    secret_name = f"{service}_password"
    if not existing or not existing.get(secret_name):
        return False
    fields = (
        f"{service}_host",
        f"{service}_port",
        f"{service}_security",
        f"{service}_username",
    )
    if not _endpoint_changed(existing, values, fields):
        return False
    submitted = payload.get(secret_name, _UNSET)
    return submitted is _UNSET or str(submitted or "").strip() in {"", "***"}


def _validate_endpoint_update(existing: dict | None, values: dict[str, Any], payload: dict[str, Any]) -> None:
    validate_mail_endpoint(values.get("imap_host"), values.get("imap_port"), values.get("imap_security"), service="imap")
    validate_mail_endpoint(values.get("smtp_host"), values.get("smtp_port"), values.get("smtp_security"), service="smtp")
    for service in ("imap", "smtp"):
        if _requires_secret_reentry(existing=existing, values=values, payload=payload, service=service):
            raise ValueError(f"{service}_password must be re-entered after endpoint changes")


def _validate_outlook_email_update(existing: dict | None, values: dict[str, Any], payload: dict[str, Any]) -> None:
    if values.get("provider") != "outlook_email":
        return
    base_url = str(values.get("outlook_email_base_url") or "").strip()
    if not base_url:
        raise ValueError("outlook_email_base_url is required")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("outlook_email_base_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("outlook_email_base_url must not include credentials")
    remote_email = str(values.get("outlook_email_remote_email") or values.get("email_address") or "").strip()
    if not remote_email:
        raise ValueError("outlook_email_remote_email is required")
    folder = str(values.get("outlook_email_folder") or "all").strip().lower()
    if folder not in {"inbox", "junkemail", "deleteditems", "all"}:
        raise ValueError("outlook_email_folder must be inbox, junkemail, deleteditems, or all")
    submitted = payload.get("outlook_email_api_key", _UNSET) if payload else _UNSET
    if existing and submitted in (_UNSET, "***") and existing.get("outlook_email_api_key"):
        return
    if not str(payload.get("outlook_email_api_key") or "").strip():
        raise ValueError("outlook_email_api_key is required")


def _infer_email_provider(data: dict[str, Any]) -> str:
    explicit = str(data.get("provider") or "").strip().lower()
    if explicit:
        return explicit
    gmail_fields = ("gmail_client_id", "gmail_client_secret", "gmail_refresh_token", "gmail_scope")
    if any(data.get(field) for field in gmail_fields):
        return "gmail"
    imap_fields = ("imap_host", "imap_username", "imap_password", "smtp_host", "smtp_username", "smtp_password")
    if any(data.get(field) for field in imap_fields):
        return "imap"
    return "outlook_email"


def save_email_account(payload: dict[str, Any], *, account_id: int | None = None, preserve_masked: bool = True) -> int:
    now = now_iso()
    existing = get_email_account(account_id, include_secrets=True) if account_id else None
    if account_id and not existing:
        raise ValueError("email account not found")
    data = dict(existing or {})
    data.update(payload or {})
    provider = _infer_email_provider(data)
    display_name = str(data.get("display_name") or data.get("email_address") or "").strip()
    email_address = str(data.get("email_address") or "").strip()
    if not display_name:
        raise ValueError("display_name is required")
    if provider not in {"gmail", "imap", "outlook_email"}:
        raise ValueError("provider must be gmail, imap, or outlook_email")
    if not email_address:
        raise ValueError("email_address is required")
    email_address = _normalize_account_email(provider, email_address)
    values = {
        "provider": provider,
        "display_name": display_name,
        "email_address": email_address,
        "status": str(data.get("status") or "active"),
        "gmail_client_id": str(data.get("gmail_client_id") or "").strip() or None,
        "gmail_scope_json": _json_dumps(_normalize_scopes(data.get("gmail_scope"), ())),
        "imap_host": str(data.get("imap_host") or "").strip() or None,
        "imap_port": int(data.get("imap_port") or 993),
        "imap_security": str(data.get("imap_security") or "ssl").strip().lower(),
        "imap_username": str(data.get("imap_username") or "").strip() or None,
        "smtp_host": str(data.get("smtp_host") or "").strip() or None,
        "smtp_port": int(data.get("smtp_port") or 465),
        "smtp_security": str(data.get("smtp_security") or "ssl").strip().lower(),
        "smtp_username": str(data.get("smtp_username") or "").strip() or None,
        "outlook_email_base_url": (
            str(data.get("outlook_email_base_url") or (OUTLOOK_EMAIL_DEFAULT_BASE_URL if provider == "outlook_email" else ""))
            .strip()
            .rstrip("/")
            or None
        ),
        "outlook_email_remote_email": (
            str(data.get("outlook_email_remote_email") or email_address or "").strip() or None
        ),
        "outlook_email_folder": str(data.get("outlook_email_folder") or "all").strip().lower(),
        "outlook_email_subject_contains": str(data.get("outlook_email_subject_contains") or "").strip() or None,
        "outlook_email_from_contains": str(data.get("outlook_email_from_contains") or "").strip() or None,
        "outlook_email_keyword": str(data.get("outlook_email_keyword") or "").strip() or None,
        "sync_mode": str(data.get("sync_mode") or "poll").strip().lower(),
        "poll_interval_seconds": int(data.get("poll_interval_seconds") or 300),
        "include_spam_trash": int(bool(data.get("include_spam_trash"))),
        "max_messages_per_sync": int(data.get("max_messages_per_sync") or 20),
    }
    if values["sync_mode"] != "poll":
        raise ValueError("sync_mode must be poll until watch sync is implemented")
    _validate_endpoint_update(existing, values, payload or {})
    _validate_outlook_email_update(existing, values, payload or {})
    secret_values = {}
    for public_name, column in SECRET_COLUMNS.items():
        submitted = payload.get(public_name, _UNSET) if payload else _UNSET
        if preserve_masked and submitted == "***" and existing:
            secret_values[column] = _encrypt_secret(existing.get(public_name))
        elif submitted is _UNSET and existing:
            secret_values[column] = _encrypt_secret(existing.get(public_name))
        else:
            secret_values[column] = _encrypt_secret(data.get(public_name))
    with get_connection() as conn:
        if account_id:
            conn.execute(
                """UPDATE email_accounts SET
                   provider=?, display_name=?, email_address=?, status=?,
                   gmail_client_id=?, gmail_client_secret_enc=?, gmail_refresh_token_enc=?,
                   gmail_scope_json=?, imap_host=?, imap_port=?, imap_security=?,
                   imap_username=?, imap_password_enc=?, smtp_host=?, smtp_port=?,
                   smtp_security=?, smtp_username=?, smtp_password_enc=?,
                   outlook_email_base_url=?, outlook_email_api_key_enc=?,
                   outlook_email_remote_email=?, outlook_email_folder=?,
                   outlook_email_subject_contains=?, outlook_email_from_contains=?,
                   outlook_email_keyword=?, sync_mode=?,
                   poll_interval_seconds=?, include_spam_trash=?, max_messages_per_sync=?,
                   updated_at=?
                   WHERE id=?""",
                (
                    values["provider"],
                    values["display_name"],
                    values["email_address"],
                    values["status"],
                    values["gmail_client_id"],
                    secret_values["gmail_client_secret_enc"],
                    secret_values["gmail_refresh_token_enc"],
                    values["gmail_scope_json"],
                    values["imap_host"],
                    values["imap_port"],
                    values["imap_security"],
                    values["imap_username"],
                    secret_values["imap_password_enc"],
                    values["smtp_host"],
                    values["smtp_port"],
                    values["smtp_security"],
                    values["smtp_username"],
                    secret_values["smtp_password_enc"],
                    values["outlook_email_base_url"],
                    secret_values["outlook_email_api_key_enc"],
                    values["outlook_email_remote_email"],
                    values["outlook_email_folder"],
                    values["outlook_email_subject_contains"],
                    values["outlook_email_from_contains"],
                    values["outlook_email_keyword"],
                    values["sync_mode"],
                    values["poll_interval_seconds"],
                    values["include_spam_trash"],
                    values["max_messages_per_sync"],
                    now,
                    account_id,
                ),
            )
            saved_id = int(account_id)
        else:
            cursor = conn.execute(
                """INSERT INTO email_accounts
                   (provider, display_name, email_address, status, gmail_client_id,
                    gmail_client_secret_enc, gmail_refresh_token_enc, gmail_scope_json,
                    imap_host, imap_port, imap_security, imap_username, imap_password_enc,
                    smtp_host, smtp_port, smtp_security, smtp_username, smtp_password_enc,
                    outlook_email_base_url, outlook_email_api_key_enc,
                    outlook_email_remote_email, outlook_email_folder,
                    outlook_email_subject_contains, outlook_email_from_contains,
                    outlook_email_keyword,
                    sync_mode, poll_interval_seconds, include_spam_trash, max_messages_per_sync,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["provider"],
                    values["display_name"],
                    values["email_address"],
                    values["status"],
                    values["gmail_client_id"],
                    secret_values["gmail_client_secret_enc"],
                    secret_values["gmail_refresh_token_enc"],
                    values["gmail_scope_json"],
                    values["imap_host"],
                    values["imap_port"],
                    values["imap_security"],
                    values["imap_username"],
                    secret_values["imap_password_enc"],
                    values["smtp_host"],
                    values["smtp_port"],
                    values["smtp_security"],
                    values["smtp_username"],
                    secret_values["smtp_password_enc"],
                    values["outlook_email_base_url"],
                    secret_values["outlook_email_api_key_enc"],
                    values["outlook_email_remote_email"],
                    values["outlook_email_folder"],
                    values["outlook_email_subject_contains"],
                    values["outlook_email_from_contains"],
                    values["outlook_email_keyword"],
                    values["sync_mode"],
                    values["poll_interval_seconds"],
                    values["include_spam_trash"],
                    values["max_messages_per_sync"],
                    now,
                    now,
                ),
            )
            saved_id = int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO email_mailboxes
               (account_id, provider_mailbox_id, display_name, enabled, query, created_at, updated_at)
               VALUES (?, 'INBOX', 'INBOX', 1, NULL, ?, ?)
               ON CONFLICT(account_id, provider_mailbox_id) DO NOTHING""",
            (saved_id, now, now),
        )
    return saved_id


def list_email_accounts() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM email_accounts ORDER BY updated_at DESC").fetchall()
    return [_normalize_account(row) for row in rows]


def get_email_account(account_id: int | None, *, include_secrets: bool = False) -> dict | None:
    if not account_id:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_accounts WHERE id = ?", (account_id,)).fetchone()
    return _normalize_account(row, include_secrets=include_secrets)


def get_email_account_by_provider_email(
    provider: str,
    email_address: str,
    *,
    include_secrets: bool = False,
) -> dict | None:
    normalized_provider = str(provider or "").strip().lower()
    normalized_email = str(email_address or "").strip().lower()
    if not normalized_provider or not normalized_email:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM email_accounts
               WHERE provider = ? AND lower(email_address) = ?
               ORDER BY updated_at DESC, id DESC
               LIMIT 1""",
            (normalized_provider, normalized_email),
        ).fetchone()
    return _normalize_account(row, include_secrets=include_secrets)


def delete_email_account(account_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM email_accounts WHERE id = ?", (account_id,))
        return bool(cursor.rowcount)


def update_email_account_status(account_id: int, status: str, last_error: str = "") -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE email_accounts SET status=?, last_error=?, updated_at=? WHERE id=?",
            (status, last_error, now_iso(), account_id),
        )
        return bool(cursor.rowcount)


def update_gmail_oauth_credentials(
    account_id: int,
    *,
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    scopes: list[str] | tuple[str, ...] | str | None,
    email_address: str | None = None,
) -> bool:
    now = now_iso()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM email_accounts WHERE id=? AND provider='gmail'",
            (account_id,),
        ).fetchone()
        if not row:
            return False
        current = _normalize_account(row, include_secrets=True) or {}
        next_refresh = refresh_token or current.get("gmail_refresh_token") or ""
        next_client_secret = client_secret or current.get("gmail_client_secret") or ""
        cursor = conn.execute(
            """UPDATE email_accounts
               SET email_address=?,
                   gmail_client_id=?,
                   gmail_client_secret_enc=?,
                   gmail_refresh_token_enc=?,
                   gmail_scope_json=?,
                   last_error=NULL,
                   updated_at=?
            WHERE id=?""",
            (
                _normalize_account_email("gmail", email_address or current.get("email_address")),
                str(client_id or current.get("gmail_client_id") or "").strip() or None,
                _encrypt_secret(next_client_secret),
                _encrypt_secret(next_refresh),
                _json_dumps(_normalize_scopes(scopes if scopes is not None else current.get("gmail_scope"), ())),
                now,
                account_id,
            ),
        )
        return bool(cursor.rowcount)


def mark_email_account_sync(account_id: int, *, error: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE email_accounts SET last_sync_at=?, last_error=?, updated_at=? WHERE id=?",
            (now_iso(), error, now_iso(), account_id),
        )


def upsert_email_message(message: dict[str, Any], attachments: list[dict[str, Any]] | None = None) -> int:
    now = now_iso()
    dedupe_key = message.get("dedupe_key") or f"{message.get('provider')}:{message.get('provider_message_id')}"
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO email_messages
               (account_id, mailbox_id, provider, provider_message_id, provider_thread_id,
                rfc_message_id, subject, from_addr, to_addr, cc_addr, received_at, sent_at,
                snippet, body_text, body_markdown_path, raw_mime_path, html_body_path,
                body_hash, dedupe_key, classification_json, cleaning_report_json,
                processing_status, source_url, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id, provider, provider_message_id) DO UPDATE SET
                 provider_thread_id=excluded.provider_thread_id,
                 rfc_message_id=excluded.rfc_message_id,
                 subject=excluded.subject,
                 from_addr=excluded.from_addr,
                 to_addr=excluded.to_addr,
                 cc_addr=excluded.cc_addr,
                 received_at=excluded.received_at,
                 sent_at=excluded.sent_at,
                 snippet=excluded.snippet,
                 body_text=excluded.body_text,
                 body_markdown_path=excluded.body_markdown_path,
                 raw_mime_path=COALESCE(NULLIF(excluded.raw_mime_path, ''), raw_mime_path),
                 html_body_path=COALESCE(NULLIF(excluded.html_body_path, ''), html_body_path),
                 body_hash=excluded.body_hash,
                 dedupe_key=excluded.dedupe_key,
                 classification_json=excluded.classification_json,
                 cleaning_report_json=excluded.cleaning_report_json,
                 processing_status=CASE
                   WHEN email_messages.processing_status IN ('generated', 'ignored')
                    AND excluded.processing_status IN ('classified', 'ignored')
                   THEN email_messages.processing_status
                   ELSE excluded.processing_status
                 END,
                 source_url=excluded.source_url,
                 error=excluded.error,
                 updated_at=excluded.updated_at""",
            (
                message.get("account_id"),
                message.get("mailbox_id"),
                message.get("provider"),
                message.get("provider_message_id"),
                message.get("provider_thread_id"),
                message.get("rfc_message_id"),
                message.get("subject"),
                message.get("from_addr"),
                message.get("to_addr"),
                message.get("cc_addr"),
                message.get("received_at"),
                message.get("sent_at"),
                message.get("snippet"),
                message.get("body_text"),
                message.get("body_markdown_path"),
                message.get("raw_mime_path"),
                message.get("html_body_path"),
                message.get("body_hash"),
                dedupe_key,
                _json_dumps(message.get("classification")),
                _json_dumps(message.get("cleaning_report")),
                message.get("processing_status") or "classified",
                message.get("source_url"),
                message.get("error"),
                now,
                now,
            ),
        )
        row = conn.execute(
            """SELECT id FROM email_messages
               WHERE account_id=? AND provider=? AND provider_message_id=?""",
            (message.get("account_id"), message.get("provider"), message.get("provider_message_id")),
        ).fetchone()
        if not row:
            raise RuntimeError("email message upsert succeeded but row lookup failed")
        message_id = int(row[0])
        if attachments is not None:
            conn.execute("DELETE FROM email_attachments WHERE message_id=?", (message_id,))
            for item in attachments:
                conn.execute(
                    """INSERT INTO email_attachments
                       (message_id, filename, content_type, size, content_id, disposition, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        item.get("filename"),
                        item.get("content_type"),
                        int(item.get("size") or 0),
                        item.get("content_id"),
                        item.get("disposition"),
                        now,
                    ),
                )
        return message_id


def list_email_messages(
    *,
    account_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where = []
    params: list[Any] = []
    if account_id:
        where.append("account_id = ?")
        params.append(account_id)
    if status:
        where.append("processing_status = ?")
        params.append(status)
    if q:
        where.append("(subject LIKE ? OR from_addr LIKE ? OR snippet LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    where_sql = " AND ".join(where) if where else "1=1"
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM email_messages WHERE {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM email_messages
                WHERE {where_sql}
                ORDER BY COALESCE(received_at, created_at) DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
    return [_normalize_message(row) for row in rows], int(total)


def get_email_message(message_id: int, *, include_body: bool = True) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_messages WHERE id = ?", (message_id,)).fetchone()
        message = _normalize_message(row, include_body=include_body)
        if not message:
            return None
        attachments = conn.execute(
            "SELECT id, filename, content_type, size, content_id, disposition FROM email_attachments WHERE message_id=?",
            (message_id,),
        ).fetchall()
    message["attachments"] = [dict(item) for item in attachments]
    return message


def update_email_message(message_id: int, **fields) -> bool:
    mapping = {
        "body_text": fields.get("body_text", _UNSET),
        "snippet": fields.get("snippet", _UNSET),
        "body_hash": fields.get("body_hash", _UNSET),
        "classification_json": _json_dumps(fields["classification"]) if "classification" in fields else _UNSET,
        "cleaning_report_json": _json_dumps(fields["cleaning_report"]) if "cleaning_report" in fields else _UNSET,
        "processing_status": fields.get("processing_status", _UNSET),
        "source_url": fields.get("source_url", _UNSET),
        "error": fields.get("error", _UNSET),
    }
    set_parts = []
    values = []
    for column, value in mapping.items():
        if value is not _UNSET:
            set_parts.append(f"{column}=?")
            values.append(value)
    if not set_parts:
        return False
    set_parts.append("updated_at=?")
    values.append(now_iso())
    values.append(message_id)
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE email_messages SET {', '.join(set_parts)} WHERE id=?", values)
        return bool(cursor.rowcount)


def list_content_targets(*, enabled_only: bool = False) -> list[dict]:
    where = "WHERE enabled = 1" if enabled_only else ""
    with get_connection() as conn:
        rows = conn.execute(f"SELECT * FROM content_targets {where} ORDER BY id ASC").fetchall()
    return [_normalize_target(row) for row in rows]


def get_content_target(target_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM content_targets WHERE id=?", (target_id,)).fetchone()
    return _normalize_target(row)


def update_content_target(target_id: int, payload: dict[str, Any]) -> dict | None:
    existing = get_content_target(target_id)
    if not existing:
        return None
    publish_mode = str(payload.get("publish_mode", existing.get("publish_mode") or "export")).strip().lower()
    if publish_mode not in {"export", "draft", "direct"}:
        raise ValueError("publish_mode must be export, draft, or direct")
    display_name = str(payload.get("display_name", existing.get("display_name") or "")).strip()
    if not display_name:
        raise ValueError("display_name is required")
    output_contract = payload.get("output_contract", existing.get("output_contract") or {})
    prompt_profile = payload.get("prompt_profile", existing.get("prompt_profile") or {})
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE content_targets SET
               display_name=?, enabled=?, output_contract_json=?, prompt_profile_json=?,
               publish_mode=?, updated_at=?
               WHERE id=?""",
            (
                display_name,
                int(bool(payload.get("enabled", existing.get("enabled", True)))),
                _json_dumps(output_contract),
                _json_dumps(prompt_profile),
                publish_mode,
                now,
                target_id,
            ),
        )
    return get_content_target(target_id)


def create_content_variant(
    *,
    source_type: str,
    source_id: str,
    article_task_id: str | None,
    target_id: int | None,
    platform: str,
    title: str,
    summary: str,
    body_path: str,
    metadata: dict[str, Any],
    quality: dict[str, Any],
    status: str = "draft",
) -> int:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO content_variants
               (source_type, source_id, article_task_id, target_id, platform, title, summary,
                body_path, metadata_json, quality_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_type, source_id, platform) DO UPDATE SET
                 article_task_id=excluded.article_task_id,
                 target_id=excluded.target_id,
                 title=excluded.title,
                 summary=excluded.summary,
                 body_path=excluded.body_path,
                 metadata_json=excluded.metadata_json,
                 quality_json=excluded.quality_json,
                 status=excluded.status,
                 updated_at=excluded.updated_at""",
            (
                source_type,
                source_id,
                article_task_id,
                target_id,
                platform,
                title,
                summary,
                body_path,
                _json_dumps(metadata),
                _json_dumps(quality),
                status,
                now,
                now,
            ),
        )
        row = conn.execute(
            """SELECT id FROM content_variants
               WHERE source_type=? AND source_id=? AND platform=?""",
            (source_type, source_id, platform),
        ).fetchone()
        if row:
            return int(row[0])
        raise RuntimeError("content variant insert succeeded but row lookup failed")


def list_content_variants(
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    platform: str | None = None,
    include_body: bool = False,
) -> list[dict]:
    where = []
    params: list[Any] = []
    if source_type:
        where.append("source_type=?")
        params.append(source_type)
    if source_id:
        where.append("source_id=?")
        params.append(source_id)
    if platform:
        where.append("platform=?")
        params.append(platform)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM content_variants {where_sql} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_normalize_variant(row, include_body=include_body) for row in rows]


def get_content_variant(variant_id: int, *, include_body: bool = False) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM content_variants WHERE id=?", (variant_id,)).fetchone()
    return _normalize_variant(row, include_body=include_body)


def _content_variant_update_values(existing: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    status = str(payload.get("status", existing.get("status") or "draft")).strip().lower()
    if status not in CONTENT_VARIANT_STATUSES:
        raise ValueError("status must be draft, ready, exported, or published")
    return {
        "title": str(payload.get("title", existing.get("title") or "") or "").strip(),
        "summary": str(payload.get("summary", existing.get("summary") or "") or "").strip(),
        "metadata": payload.get("metadata", existing.get("metadata") or {}),
        "quality": payload.get("quality", existing.get("quality") or {}),
        "body_path": payload.get("body_path", existing.get("body_path")),
        "status": status,
    }


def validate_content_variant_update_payload(existing: dict[str, Any], payload: dict[str, Any]) -> None:
    _content_variant_update_values(existing, payload)


def update_content_variant(variant_id: int, payload: dict[str, Any]) -> dict | None:
    existing = get_content_variant(variant_id)
    if not existing:
        return None
    values = _content_variant_update_values(existing, payload)
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """UPDATE content_variants SET
               title=?, summary=?, body_path=?, metadata_json=?, quality_json=?,
               status=?, updated_at=?
               WHERE id=?""",
            (
                values["title"],
                values["summary"],
                str(values["body_path"] or "") or None,
                _json_dumps(values["metadata"]),
                _json_dumps(values["quality"]),
                values["status"],
                now,
                variant_id,
            ),
        )
    return get_content_variant(variant_id, include_body=True)

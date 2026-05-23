from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
import socket
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

import monitor.db as monitor_db
import monitor.db.connection as db_connection
from monitor.db.queries import email_collect as email_queries
from monitor.email_collect.errors import EmailProviderError
from monitor.email_collect.models import ParsedEmailMessage
from monitor.email_collect.outlook_email_client import OutlookEmailClient
from monitor.email_collect.service import EmailCollectService


@pytest.fixture()
def service_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(monitor_db, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(monitor_db, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)
    monkeypatch.setattr(db_connection, "_DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(db_connection, "_DB_PATH", str(data_dir / "monitor.db"), raising=False)

    with monitor_db.get_connection() as conn:
        email_queries.ensure_schema(conn)

    service = EmailCollectService()
    return service, data_dir


def _create_account() -> dict[str, object]:
    return {
        "provider": "gmail",
        "display_name": "AI Feed",
        "email_address": "feed@example.com",
        "gmail_client_id": "client-id",
        "gmail_client_secret": "secret-1",
        "gmail_refresh_token": "refresh-1",
        "sync_mode": "poll",
        "poll_interval_seconds": 300,
    }


def _create_message(account_id: int) -> dict[str, object]:
    body_text = (
        "This release includes benchmark details and API migration notes for developers. "
        "It also covers the dataset setup, evaluation methodology, rollout risks, "
        "and code examples that the engineering team can reuse in downstream guides."
    )
    return {
        "account_id": account_id,
        "provider": "gmail",
        "provider_message_id": "gmail-msg-1",
        "provider_thread_id": "thread-1",
        "rfc_message_id": "<msg-1@example.com>",
        "subject": "Research release update",
        "from_addr": "Feed <feed@example.com>",
        "to_addr": "Reader <reader@example.com>",
        "received_at": "2026-05-01T10:00:00+08:00",
        "sent_at": "2026-05-01T10:00:00+08:00",
        "snippet": "Initial snippet",
        "body_text": body_text,
        "body_hash": "hash-1",
        "classification": {
            "primary_type": "research",
            "secondary_types": ["ai"],
            "language": "en",
            "value_score": 8,
            "action": "generate_variants",
            "recommended_targets": ["wechat", "zhihu"],
            "risk_flags": ["needs_fact_check"],
            "reason": "seed",
        },
        "cleaning_report": {"removed_quoted_chain": False},
        "processing_status": "classified",
        "source_url": "https://mail.google.com/mail/u/0/#all/gmail-msg-1",
    }


def test_email_account_contract_masks_secrets_in_list_and_preserves_masked_update(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())

    listed = service.list_accounts()
    secret_view = service.get_account(account_id, include_secrets=True)

    service.save_account(
        {
            "provider": "gmail",
            "display_name": "AI Feed Updated",
            "email_address": "feed@example.com",
            "gmail_client_secret": "***",
            "gmail_refresh_token": "***",
        },
        account_id=account_id,
    )
    updated = service.get_account(account_id, include_secrets=True)

    assert listed[0]["id"] == account_id
    assert listed[0]["has_gmail_client_secret"] is True
    assert listed[0]["has_gmail_refresh_token"] is True
    assert "gmail_client_secret" not in listed[0]
    assert "gmail_refresh_token" not in listed[0]
    assert secret_view["gmail_client_secret"] == "secret-1"
    assert secret_view["gmail_refresh_token"] == "refresh-1"
    assert updated["display_name"] == "AI Feed Updated"
    assert updated["gmail_client_secret"] == "secret-1"
    assert updated["gmail_refresh_token"] == "refresh-1"


def test_outlook_email_account_contract_masks_api_key_and_preserves_masked_update(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(
        {
            "provider": "outlook_email",
            "display_name": "External Inbox",
            "email_address": "reader@example.com",
            "outlook_email_base_url": "http://127.0.0.1:5000",
            "outlook_email_api_key": "external-key-1",
            "outlook_email_remote_email": "reader@example.com",
            "outlook_email_folder": "all",
            "outlook_email_subject_contains": "release",
        }
    )

    listed = service.list_accounts()[0]
    secret_view = service.get_account(account_id, include_secrets=True)
    service.save_account(
        {
            "provider": "outlook_email",
            "display_name": "External Inbox Updated",
            "email_address": "reader@example.com",
            "outlook_email_base_url": "http://127.0.0.1:5000",
            "outlook_email_api_key": "***",
            "outlook_email_remote_email": "reader@example.com",
            "outlook_email_folder": "inbox",
        },
        account_id=account_id,
    )
    updated = service.get_account(account_id, include_secrets=True)

    assert listed["provider"] == "outlook_email"
    assert listed["has_outlook_email_api_key"] is True
    assert "outlook_email_api_key" not in listed
    assert secret_view["outlook_email_api_key"] == "external-key-1"
    assert updated["display_name"] == "External Inbox Updated"
    assert updated["outlook_email_api_key"] == "external-key-1"
    assert updated["outlook_email_folder"] == "inbox"


class _FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class _FakeOpener:
    def __init__(self, bodies: list[str]):
        self.bodies = list(bodies)
        self.calls = []

    def open(self, request, timeout=0):
        self.calls.append((request, timeout))
        return _FakeResponse(self.bodies.pop(0))


def test_outlook_email_client_maps_external_messages_to_parsed_email():
    client = OutlookEmailClient(
        {
            "email_address": "reader@example.com",
            "outlook_email_base_url": "http://127.0.0.1:5000/",
            "outlook_email_api_key": "external-key",
            "outlook_email_remote_email": "alias@example.com",
            "outlook_email_folder": "all",
            "outlook_email_subject_contains": "release",
            "outlook_email_from_contains": "news",
            "outlook_email_keyword": "benchmark",
        }
    )
    client._opener = _FakeOpener(
        [
            """{"success": true, "requested_email": "alias@example.com", "resolved_email": "reader@example.com", "method": "Graph API", "emails": [{"id": "msg-1", "subject": "Release notes", "from": "News <news@example.com>", "date": "2026-05-01T10:00:00Z", "body_preview": "Benchmark summary", "folder": "inbox"}]}""",
        ]
    )

    messages = list(client.fetch_recent(max_messages=5))
    request, timeout = client._opener.calls[0]

    assert len(messages) == 1
    assert messages[0].provider == "outlook_email"
    assert messages[0].provider_message_id == "msg-1"
    assert messages[0].subject == "Release notes"
    assert messages[0].from_addr == "News <news@example.com>"
    assert messages[0].body_text == "Benchmark summary"
    assert "/api/external/emails" in request.full_url
    assert "email=alias%40example.com" in request.full_url
    assert "folder=all" in request.full_url
    assert dict(request.header_items())["X-api-key"] == "external-key"
    assert timeout == 45


def test_outlook_email_sync_routes_through_client_and_persists_messages(service_env, monkeypatch):
    service, _data_dir = service_env
    account_id = service.save_account(
        {
            "provider": "outlook_email",
            "display_name": "External Inbox",
            "email_address": "reader@example.com",
            "outlook_email_base_url": "http://127.0.0.1:5000",
            "outlook_email_api_key": "external-key-1",
            "outlook_email_remote_email": "reader@example.com",
            "outlook_email_folder": "all",
            "max_messages_per_sync": 7,
        }
    )
    calls = []

    class FakeOutlookEmailClient:
        def __init__(self, account):
            self.account = account

        def fetch_recent(self, *, max_messages=10):
            calls.append((self.account["provider"], max_messages))
            return [
                ParsedEmailMessage(
                    provider="outlook_email",
                    provider_message_id="outlook-msg-1",
                    subject="Developer platform release",
                    from_addr="Digest <digest@example.com>",
                    received_at="2026-05-01T10:00:00Z",
                    snippet="API migration and benchmark details",
                    body_text=(
                        "This update includes API migration notes, benchmark details, "
                        "developer examples, and rollout risks for teams."
                    ),
                )
            ]

    monkeypatch.setattr("monitor.email_collect.service.OutlookEmailClient", FakeOutlookEmailClient)

    result = service.sync_account(account_id)
    items, total = service.list_messages(account_id=account_id, status=None, q=None, limit=10, offset=0)

    assert result["ok"] is True
    assert result["synced_count"] == 1
    assert calls == [("outlook_email", 7)]
    assert total == 1
    assert items[0]["provider"] == "outlook_email"
    assert items[0]["provider_message_id"] == "outlook-msg-1"


def test_gmail_oauth_status_reports_config_and_account_authorization(service_env, monkeypatch):
    service, _data_dir = service_env

    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )

    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
        }
    )
    before = service.gmail_oauth_status(base_url="http://localhost:8765", account_id=account_id)

    assert before["configured"] is True
    assert before["redirect_uri"] == "http://localhost:8765/api/email/auth/gmail/callback"
    assert before["authorized"] is False
    assert before["read_authorized"] is False
    assert before["send_authorized"] is False

    assert email_queries.update_gmail_oauth_credentials(
        account_id,
        client_id="global-client-id",
        client_secret="global-client-secret",
        refresh_token="refresh-token",
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        email_address="feed@example.com",
    )
    after = service.gmail_oauth_status(base_url="http://localhost:8765", account_id=account_id)

    assert after["authorized"] is True
    assert after["read_authorized"] is True
    assert after["send_authorized"] is True
    assert after["has_refresh_token"] is True


def test_start_gmail_oauth_builds_one_click_url_with_receive_and_send_scopes(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
        }
    )

    result = service.start_gmail_oauth(account_id, base_url="http://localhost:8765", return_to="/#/email-pipeline")
    parsed = urlparse(result["authorization_url"])
    params = parse_qs(parsed.query)
    scopes = set(params["scope"][0].split())

    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["global-client-id"]
    assert params["redirect_uri"] == ["http://localhost:8765/api/email/auth/gmail/callback"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["include_granted_scopes"] == ["true"]
    assert "state" in params
    assert {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    } <= scopes


def test_start_gmail_oauth_allows_productized_flow_without_existing_account(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )

    result = service.start_gmail_oauth(base_url="http://localhost:8765", return_to="/#/email-pipeline")
    parsed = urlparse(result["authorization_url"])
    params = parse_qs(parsed.query)
    scopes = set(params["scope"][0].split())

    assert result["ok"] is True
    assert "account_id" not in result
    assert "login_hint" not in params
    assert params["client_id"] == ["global-client-id"]
    assert params["redirect_uri"] == ["http://localhost:8765/api/email/auth/gmail/callback"]
    assert {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    } <= scopes


def test_finish_gmail_oauth_stores_receive_and_send_refresh_token(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
        }
    )
    started = service.start_gmail_oauth(account_id, base_url="http://localhost:8765", return_to="/#/email-pipeline")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    def fake_exchange(**_kwargs):
        return {
            "refresh_token": "refresh-from-google",
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        }

    monkeypatch.setattr("monitor.email_collect.service.exchange_gmail_oauth_code", fake_exchange)
    monkeypatch.setattr(
        "monitor.email_collect.service.GmailClient.test_connection",
        lambda self: {"ok": True, "emailAddress": "feed@example.com", "messagesTotal": 8},
    )

    result = service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")
    stored = service.get_account(account_id, include_secrets=True)

    assert result["ok"] is True
    assert result["account_id"] == account_id
    assert stored["gmail_client_id"] == "global-client-id"
    assert stored["gmail_client_secret"] == "global-client-secret"
    assert stored["gmail_refresh_token"] == "refresh-from-google"
    assert {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    } <= set(stored["gmail_scope"])


def test_finish_gmail_oauth_creates_account_for_productized_flow(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    started = service.start_gmail_oauth(base_url="http://localhost:8765", return_to="/#/email-pipeline")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        "monitor.email_collect.service.exchange_gmail_oauth_code",
        lambda **_kwargs: {
            "refresh_token": "refresh-from-google",
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        },
    )
    monkeypatch.setattr(
        "monitor.email_collect.service.GmailClient.test_connection",
        lambda self: {"ok": True, "emailAddress": "new-gmail@example.com", "messagesTotal": 12},
    )

    result = service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")
    stored = service.get_account(result["account_id"], include_secrets=True)

    assert result["ok"] is True
    assert result["created"] is True
    assert stored["provider"] == "gmail"
    assert stored["email_address"] == "new-gmail@example.com"
    assert stored["gmail_client_id"] == "global-client-id"
    assert stored["gmail_client_secret"] == "global-client-secret"
    assert stored["gmail_refresh_token"] == "refresh-from-google"
    assert {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    } <= set(stored["gmail_scope"])


def test_finish_gmail_oauth_updates_existing_account_by_profile_email(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    existing_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Existing Gmail",
            "email_address": "new-gmail@example.com",
            "gmail_refresh_token": "old-refresh",
        }
    )
    started = service.start_gmail_oauth(base_url="http://localhost:8765", return_to="/#/email-pipeline")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        "monitor.email_collect.service.exchange_gmail_oauth_code",
        lambda **_kwargs: {
            "refresh_token": "new-refresh",
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        },
    )
    monkeypatch.setattr(
        "monitor.email_collect.service.GmailClient.test_connection",
        lambda self: {"ok": True, "emailAddress": "new-gmail@example.com", "messagesTotal": 12},
    )

    result = service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")
    stored = service.get_account(existing_id, include_secrets=True)

    assert result["ok"] is True
    assert result["created"] is False
    assert result["account_id"] == existing_id
    assert stored["gmail_client_id"] == "global-client-id"
    assert stored["gmail_client_secret"] == "global-client-secret"
    assert stored["gmail_refresh_token"] == "new-refresh"


def test_finish_gmail_oauth_rejects_incomplete_granted_scopes(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
        }
    )
    started = service.start_gmail_oauth(account_id, base_url="http://localhost:8765")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        "monitor.email_collect.service.exchange_gmail_oauth_code",
        lambda **_kwargs: {
            "refresh_token": "refresh-from-google",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        },
    )

    with pytest.raises(Exception) as excinfo:
        service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")

    stored = service.get_account(account_id, include_secrets=True)
    assert "granted scopes are incomplete" in str(excinfo.value)
    assert stored["has_gmail_refresh_token"] is False


def test_finish_gmail_oauth_rejects_extra_granted_scopes(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
        }
    )
    started = service.start_gmail_oauth(account_id, base_url="http://localhost:8765")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        "monitor.email_collect.service.exchange_gmail_oauth_code",
        lambda **_kwargs: {
            "refresh_token": "refresh-from-google",
            "scope": (
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/gmail.send "
                "https://www.googleapis.com/auth/gmail.modify"
            ),
        },
    )

    with pytest.raises(Exception) as excinfo:
        service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")

    stored = service.get_account(account_id, include_secrets=True)
    assert "Unsupported Gmail OAuth scope granted" in str(excinfo.value)
    assert stored["has_gmail_refresh_token"] is False


def test_finish_gmail_oauth_rejects_missing_refresh_token_when_stored_scopes_are_readonly(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        },
    )
    account_id = service.save_account(
        {
            "provider": "gmail",
            "display_name": "Gmail Feed",
            "email_address": "feed@example.com",
            "gmail_refresh_token": "old-readonly-refresh",
            "gmail_scope": ["https://www.googleapis.com/auth/gmail.readonly"],
        }
    )
    started = service.start_gmail_oauth(account_id, base_url="http://localhost:8765")
    state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        "monitor.email_collect.service.exchange_gmail_oauth_code",
        lambda **_kwargs: {
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        },
    )
    monkeypatch.setattr(
        "monitor.email_collect.service.GmailClient.test_connection",
        lambda self: {"ok": True, "emailAddress": "feed@example.com", "messagesTotal": 1},
    )

    with pytest.raises(Exception) as excinfo:
        service.finish_gmail_oauth(state=state, code="oauth-code", base_url="http://localhost:8765")

    stored = service.get_account(account_id, include_secrets=True)
    assert "refresh token" in str(excinfo.value)
    assert stored["gmail_refresh_token"] == "old-readonly-refresh"
    assert stored["gmail_scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_start_gmail_oauth_rejects_unsupported_or_incomplete_scope_config(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify",
        },
    )

    with pytest.raises(Exception) as excinfo:
        service.start_gmail_oauth(base_url="http://localhost:8765")

    assert "Unsupported Gmail OAuth scope" in str(excinfo.value)

    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "gmail_oauth_client_id": "global-client-id",
            "gmail_oauth_client_secret": "global-client-secret",
            "gmail_oauth_redirect_uri": "",
            "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly",
        },
    )

    with pytest.raises(Exception) as excinfo:
        service.start_gmail_oauth(base_url="http://localhost:8765")

    assert "receive and send" in str(excinfo.value)


def test_consume_oauth_state_uses_atomic_update_before_read(monkeypatch):
    executed: list[str] = []

    class FakeCursor:
        rowcount = 1

        def __init__(self, row=None):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConnection:
        def execute(self, sql, params=()):
            normalized_sql = " ".join(str(sql).split()).lower()
            executed.append(normalized_sql)
            if normalized_sql.startswith("update email_oauth_states"):
                return FakeCursor()
            if normalized_sql.startswith("select * from email_oauth_states"):
                return FakeCursor(
                    {
                        "state_hash": "hash",
                        "account_id": None,
                        "provider": "gmail",
                        "requested_scopes_json": '["https://www.googleapis.com/auth/gmail.readonly"]',
                        "redirect_uri": "http://localhost/callback",
                        "return_to": "",
                        "created_at": "2026-05-01T00:00:00Z",
                        "expires_at": "2026-05-01T00:10:00Z",
                        "consumed_at": "2026-05-01T00:01:00Z",
                    }
                )
            raise AssertionError(f"unexpected SQL: {sql}")

    @contextmanager
    def fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(email_queries, "get_connection", fake_get_connection)

    item = email_queries.consume_oauth_state("oauth-state")

    assert item is not None
    assert executed[0].startswith("update email_oauth_states")
    assert "consumed_at is null" in executed[0]
    assert "expires_at >= ?" in executed[0]


def test_gmail_api_send_requires_send_scope_before_network_call(service_env):
    service, _data_dir = service_env
    payload = _create_account()
    payload["gmail_scope"] = ["https://www.googleapis.com/auth/gmail.readonly"]
    account_id = service.save_account(payload)

    with pytest.raises(Exception) as excinfo:
        service.send_gmail_message(
            account_id,
            {
                "to": "reader@example.com",
                "subject": "Hello",
                "body": "Body",
            },
        )

    assert "send scope" in str(excinfo.value)


def test_imap_endpoint_change_requires_secret_reentry_and_blocks_private_hosts(service_env, monkeypatch):
    service, _data_dir = service_env

    def public_dns(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", int(port)))]

    monkeypatch.setattr("monitor.email_collect.security.socket.getaddrinfo", public_dns)

    account_id = service.save_account(
        {
            "provider": "imap",
            "display_name": "IMAP Feed",
            "email_address": "imap@example.com",
            "imap_host": "mail.example.com",
            "imap_port": 993,
            "imap_security": "ssl",
            "imap_username": "imap@example.com",
            "imap_password": "old-password",
        }
    )

    with pytest.raises(Exception) as excinfo:
        service.save_account(
            {
                "provider": "imap",
                "display_name": "IMAP Feed",
                "email_address": "imap@example.com",
                "imap_host": "mail2.example.com",
                "imap_port": 993,
                "imap_security": "ssl",
                "imap_username": "imap@example.com",
            },
            account_id=account_id,
        )

    assert "imap_password must be re-entered" in str(excinfo.value)

    service.save_account(
        {
            "provider": "imap",
            "display_name": "IMAP Feed",
            "email_address": "imap@example.com",
            "imap_host": "mail2.example.com",
            "imap_port": 993,
            "imap_security": "ssl",
            "imap_username": "imap@example.com",
            "imap_password": "new-password",
        },
        account_id=account_id,
    )

    with pytest.raises(Exception) as excinfo:
        service.save_account(
            {
                "provider": "imap",
                "display_name": "IMAP Feed",
                "email_address": "imap@example.com",
                "imap_host": "127.0.0.1",
                "imap_port": 993,
                "imap_security": "ssl",
                "imap_username": "imap@example.com",
                "imap_password": "new-password",
            },
            account_id=account_id,
        )

    assert "blocked address" in str(excinfo.value) or "not allowed" in str(excinfo.value)


def test_imap_smtp_security_mode_rejects_plaintext_none(service_env, monkeypatch):
    service, _data_dir = service_env

    def public_dns(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", int(port)))]

    monkeypatch.setattr("monitor.email_collect.security.socket.getaddrinfo", public_dns)

    with pytest.raises(Exception) as excinfo:
        service.save_account(
            {
                "provider": "imap",
                "display_name": "IMAP Feed",
                "email_address": "imap@example.com",
                "imap_host": "mail.example.com",
                "imap_port": 143,
                "imap_security": "none",
                "imap_username": "imap@example.com",
                "imap_password": "password",
            }
        )

    assert "security must be ssl or starttls" in str(excinfo.value)


def test_account_update_requires_existing_id_and_poll_sync_mode(service_env):
    service, _data_dir = service_env

    with pytest.raises(Exception) as missing_exc:
        service.save_account(_create_account(), account_id=999)

    assert "email account not found" in str(missing_exc.value)

    payload = _create_account()
    payload["sync_mode"] = "watch"
    with pytest.raises(Exception) as sync_exc:
        service.save_account(payload)

    assert "sync_mode must be poll" in str(sync_exc.value)


def test_message_contract_supports_listing_detail_reclean_classify_and_ignore(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(
        _create_message(account_id),
        [
            {
                "filename": "release.txt",
                "content_type": "text/plain",
                "size": 12,
                "content_id": "cid-release",
                "disposition": "attachment",
            }
        ],
    )

    rows, total = service.list_messages(account_id=account_id, status="classified", q="release", limit=10, offset=0)
    detail = service.get_message(message_id, include_body=True)
    recleaned = service.reclean_message(message_id)
    reclassified = service.classify_message(message_id)
    ignored = service.mark_ignored(message_id)
    final_detail = service.get_message(message_id, include_body=True)

    assert total == 1
    assert len(rows) == 1
    assert rows[0]["id"] == message_id
    assert "body_text" not in rows[0]
    assert rows[0]["classification"]["primary_type"] == "research"
    assert detail["body_text"].startswith("This release includes")
    assert detail["attachments"][0]["filename"] == "release.txt"
    assert recleaned["processing_status"] == "cleaned"
    assert recleaned["cleaning_report"]["is_empty_or_ignored"] is False
    assert reclassified["processing_status"] == "classified"
    assert reclassified["classification"]["action"] == "generate_variants"
    assert ignored is True
    assert final_detail["processing_status"] == "ignored"


def test_persisted_message_runs_content_analysis_and_payload_prefers_analysis_text(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    account = service.get_account(account_id, include_secrets=True)

    message_id = service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="gmail",
            provider_message_id="gmail-analysis-1",
            subject="Developer API migration guide",
            from_addr="Engineering <eng@example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            html_body=(
                "<p>This developer guide explains the API migration methodology, "
                "release risk, and model evaluation.</p>"
                '<a href="https://example.com/migration?utm_source=email">Full migration guide</a>'
            ),
        ),
    )

    detail = service.get_message(message_id, include_body=True)
    payload = service.prepare_article_payload(message_id)

    assert detail["processing_status"] == "classified"
    assert detail["classification"]["rule_version"] == "email-content-analysis-v1"
    assert "developer_practice" in detail["classification"]["tags"]
    assert detail["classification"]["translation"]["required"] is True
    assert detail["classification"]["links"]["kept_count"] == 1
    assert detail["classification"]["links"]["items"][0]["url"] == "https://example.com/migration"
    assert "【中文处理稿】" in payload["article_text"]
    assert "https://example.com/migration" in payload["article_text"]


def test_persisted_message_uses_configurable_email_analysis_rules(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "email_analysis_rules": {
                "marketing_keywords": ["vendor blast"],
                "marketing_sender_domains": ["ads."],
            }
        },
    )
    account_id = service.save_account(_create_account())
    account = service.get_account(account_id, include_secrets=True)

    message_id = service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="gmail",
            provider_message_id="gmail-configurable-analysis",
            subject="Vendor blast for paid plan",
            from_addr="Ads <noreply@ads.example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            body_text="This vendor blast promotes a paid plan bundle.",
        ),
    )

    detail = service.get_message(message_id, include_body=True)

    assert detail["processing_status"] == "ignored"
    assert detail["classification"]["primary_type"] == "marketing"
    assert detail["classification"]["filter"]["configurable"] is True
    assert "keyword:vendor blast" in detail["classification"]["filter"]["matched_rules"]


def test_reclean_message_clears_stale_analysis_text_before_payload_generation(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message = _create_message(account_id)
    message["provider_message_id"] = "gmail-msg-reclean-analysis"
    message["body_text"] = "This release includes benchmark details.\n\nUnsubscribe"
    message["classification"] = {
        "primary_type": "research",
        "recommended_targets": ["wechat"],
        "analysis_text": "OLD STALE CONTENT THAT MUST NOT BE USED",
    }
    message_id = email_queries.upsert_email_message(message)

    recleaned = service.reclean_message(message_id)
    payload = service.prepare_article_payload(message_id)

    assert recleaned["classification"]["analysis_stale"] is True
    assert "analysis_text" not in recleaned["classification"]
    assert "OLD STALE CONTENT" not in payload["article_text"]
    assert "This release includes benchmark details" in payload["article_text"]


def test_reprocess_message_can_expand_links_with_injected_fetcher(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message = _create_message(account_id)
    message["provider_message_id"] = "gmail-msg-link-expansion"
    message["body_text"] = (
        "This research report links to https://example.com/report for benchmark methodology "
        "and dataset details that should enrich the article source."
    )
    message_id = email_queries.upsert_email_message(message)

    reprocessed = service.reprocess_message(
        message_id,
        expand_links=True,
        link_fetcher=lambda _url: {
            "title": "Expanded report",
            "html": "<title>Expanded report</title><p>The linked page adds evaluation methodology and risk notes.</p>",
        },
    )
    payload = service.prepare_article_payload(message_id)

    link = reprocessed["classification"]["links"]["items"][0]
    assert reprocessed["processing_status"] == "classified"
    assert link["enrichment_status"] == "ok"
    assert "evaluation methodology" in link["enrichment"]["excerpt"]
    assert "【链接补充材料】" in payload["article_text"]
    assert "Expanded report" in payload["article_text"]


def test_reprocess_message_preserves_html_only_links_from_persisted_source(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    account = service.get_account(account_id, include_secrets=True)

    message_id = service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="gmail",
            provider_message_id="gmail-html-only-link",
            subject="Research benchmark report",
            from_addr="Research <research@example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            html_body=(
                "<p>This research benchmark email links to the full report.</p>"
                '<a href="https://example.com/report?utm_source=email">Read the report</a>'
            ),
        ),
    )
    detail = service.get_message(message_id, include_body=True)

    reprocessed = service.reprocess_message(
        message_id,
        expand_links=True,
        link_fetcher=lambda _url: {
            "title": "HTML only report",
            "html": "<p>The linked page adds benchmark evaluation details.</p>",
        },
    )

    link = reprocessed["classification"]["links"]["items"][0]
    assert detail["html_body_path"]
    assert Path(detail["html_body_path"]).is_file()
    assert "https://example.com/report" not in detail["body_text"]
    assert link["url"] == "https://example.com/report"
    assert link["enrichment_status"] == "ok"
    assert "benchmark evaluation" in link["enrichment"]["excerpt"]


def test_duplicate_sync_does_not_clear_persisted_html_source_for_reprocess(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    account = service.get_account(account_id, include_secrets=True)

    message_id = service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="gmail",
            provider_message_id="gmail-html-path-preserve",
            subject="Research benchmark report",
            from_addr="Research <research@example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            html_body=(
                "<p>This research benchmark email links to the full report.</p>"
                '<a href="https://example.com/report?utm_source=email">Read the report</a>'
            ),
        ),
    )
    first_detail = service.get_message(message_id, include_body=True)

    service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="gmail",
            provider_message_id="gmail-html-path-preserve",
            subject="Research benchmark report",
            from_addr="Research <research@example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            body_text="This duplicate sync has no HTML source.",
        ),
    )
    second_detail = service.get_message(message_id, include_body=True)
    reprocessed = service.reprocess_message(
        message_id,
        expand_links=True,
        link_fetcher=lambda _url: {"text": "The preserved link still enriches the message."},
    )

    assert second_detail["html_body_path"] == first_detail["html_body_path"]
    assert Path(second_detail["html_body_path"]).is_file()
    assert reprocessed["classification"]["links"]["items"][0]["url"] == "https://example.com/report"


def test_generate_variants_uses_configured_platform_sensitive_words(service_env, monkeypatch):
    service, _data_dir = service_env
    monkeypatch.setattr(
        monitor_db,
        "load_config",
        lambda: {
            "email_analysis_rules": {
                "platform_sensitive_words": {
                    "wechat": {
                        "禁词": "合规表述",
                    }
                }
            }
        },
    )
    account_id = service.save_account(_create_account())
    message = _create_message(account_id)
    message["provider_message_id"] = "gmail-configured-platform-filter"
    message["subject"] = "新闻报道"
    message["body_text"] = "这是一篇新闻报道，包含平台禁词，需要在公众号变体中过滤。"
    message["classification"] = {
        "primary_type": "news",
        "secondary_types": ["industry_news"],
        "language": "zh",
        "value_score": 8,
        "action": "generate_variants",
        "recommended_targets": ["wechat"],
        "risk_flags": ["platform_sensitive_review"],
        "reason": "seed",
    }
    message_id = email_queries.upsert_email_message(message)

    variant_id = service.generate_variants(message_id, article_task_id="article-email-rules", platforms=["wechat"])[0]["id"]
    detail = service.get_variant(variant_id, include_body=True)

    assert "禁词" not in detail["body"]
    assert "合规表述" in detail["body"]
    assert detail["metadata"]["platform_compliance"]["changed"] is True
    assert detail["metadata"]["platform_compliance"]["matched_terms"] == [
        {"term": "禁词", "replacement": "合规表述"}
    ]


def test_content_variants_contract_lists_targets_and_optionally_reads_body(service_env):
    service, data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))

    created = service.generate_variants(message_id, article_task_id="article-email-1", platforms=["wechat", "zhihu"])
    targets = service.list_targets()
    listed = service.list_variants(
        source_type="email_message",
        source_id=str(message_id),
        platform=None,
        include_body=True,
    )

    assert {item["platform"] for item in created} == {"wechat", "zhihu"}
    assert {item["platform"] for item in targets} >= {"wechat", "zhihu", "x"}
    assert {item["source_type"] for item in listed} == {"email_message"}
    assert {item["article_task_id"] for item in listed} == {"article-email-1"}
    assert {item["platform"] for item in listed} == {"wechat", "zhihu"}
    assert all(item["status"] == "draft" for item in listed)
    assert all(item["body"] for item in listed)
    assert all(Path(item["body_path"]).is_file() for item in listed)
    assert (data_dir / "email-content-variants").is_dir()


def test_imap_persisted_message_uses_valid_local_api_source_url(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    account = service.get_account(account_id, include_secrets=True)
    account["provider"] = "imap"

    message_id = service.persist_parsed_message(
        account,
        ParsedEmailMessage(
            provider="imap",
            provider_message_id="imap-msg-1",
            subject="IMAP note",
            from_addr="Feed <feed@example.com>",
            received_at="2026-05-01T10:00:00+08:00",
            sent_at="2026-05-01T10:00:00+08:00",
            body_text=(
                "This IMAP message contains enough operational detail to be classified "
                "and used by the article generation pipeline."
            ),
        ),
    )
    detail = service.get_message(message_id)
    payload = service.prepare_article_payload(message_id)

    assert detail["source_url"] == f"/api/email/messages/{message_id}"
    assert payload["source_url"] == f"/api/email/messages/{message_id}"


def test_generate_variants_is_idempotent_per_message_platform(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))

    first = service.generate_variants(message_id, article_task_id="article-email-1", platforms=["wechat"])
    second = service.generate_variants(message_id, article_task_id="article-email-2", platforms=["wechat"])
    listed = service.list_variants(
        source_type="email_message",
        source_id=str(message_id),
        platform="wechat",
        include_body=True,
    )

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert len(listed) == 1
    assert listed[0]["id"] == first[0]["id"]
    assert listed[0]["article_task_id"] == "article-email-1"
    assert listed[0]["body_path"] == first[0]["body_path"] == second[0]["body_path"]


def test_regenerate_variants_preserves_reviewed_manual_edits_by_default(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))
    variant_id = service.generate_variants(message_id, article_task_id="article-email-1", platforms=["wechat"])[0]["id"]

    service.update_variant(
        variant_id,
        {
            "title": "Reviewed title",
            "summary": "Reviewed summary",
            "body": "MANUAL EDIT",
            "status": "ready",
        },
    )
    regenerated = service.generate_variants(message_id, article_task_id="article-email-2", platforms=["wechat"])
    detail = service.get_variant(variant_id, include_body=True)

    assert regenerated[0]["id"] == variant_id
    assert detail["article_task_id"] == "article-email-1"
    assert detail["status"] == "ready"
    assert detail["title"] == "Reviewed title"
    assert detail["body"] == "MANUAL EDIT"


def test_content_target_and_variant_update_export_contract(service_env):
    service, data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))
    variant_id = service.generate_variants(message_id, article_task_id="article-email-2", platforms=["wechat"])[0]["id"]
    target_id = next(item["id"] for item in service.list_targets() if item["platform"] == "wechat")

    updated_target = service.update_target(
        target_id,
        {
            "display_name": "微信公众号草稿",
            "enabled": True,
            "publish_mode": "draft",
            "output_contract": {"max_chars": 5000},
            "prompt_profile": {"tone": "editorial"},
        },
    )
    updated_variant = service.update_variant(
        variant_id,
        {
            "title": "Edited title",
            "summary": "Edited summary",
            "body": "Edited body for export.",
            "body_path": str(data_dir / "outside.md"),
            "status": "ready",
        },
    )
    markdown_export = service.export_variant(variant_id, export_format="markdown")
    json_export = service.export_variant(variant_id, export_format="json")

    variant_path = Path(updated_variant["body_path"]).resolve()
    assert updated_target["display_name"] == "微信公众号草稿"
    assert updated_target["publish_mode"] == "draft"
    assert updated_target["output_contract"]["max_chars"] == 5000
    assert updated_variant["title"] == "Edited title"
    assert updated_variant["status"] == "ready"
    assert updated_variant["body"] == "Edited body for export."
    assert variant_path.is_file()
    assert (data_dir / "email-content-variants").resolve() in variant_path.parents
    assert markdown_export["filename"].endswith(".md")
    assert "# Edited title" in markdown_export["content"]
    assert "Edited body for export." in markdown_export["content"]
    assert json_export["filename"].endswith(".json")
    assert '"title": "Edited title"' in json_export["content"]


def test_rejected_variant_update_does_not_mutate_body_file(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))
    variant_id = service.generate_variants(message_id, article_task_id="article-email-3", platforms=["wechat"])[0]["id"]
    before = service.get_variant(variant_id, include_body=True)
    body_path = Path(before["body_path"])
    original_body = body_path.read_text(encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        service.update_variant(
            variant_id,
            {
                "body": "MUTATED BODY",
                "status": "bad-status",
            },
        )

    after = service.get_variant(variant_id, include_body=True)
    assert "status must be draft" in str(excinfo.value)
    assert after["status"] == before["status"]
    assert after["body"] == before["body"]
    assert body_path.read_text(encoding="utf-8") == original_body


def test_failed_sync_persists_safe_last_error(service_env, monkeypatch):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())

    def fail_fetch_recent(self, max_messages):
        raise EmailProviderError("IMAP connection failed: imap.internal.example:993 timeout")

    monkeypatch.setattr("monitor.email_collect.service.GmailClient.fetch_recent", fail_fetch_recent)

    with pytest.raises(EmailProviderError) as excinfo:
        service.sync_account(account_id)

    account = service.get_account(account_id)
    assert "imap.internal.example" not in str(excinfo.value)
    assert "imap.internal.example" not in account["last_error"]
    assert account["last_error"] == "邮箱服务连接失败，请检查配置或稍后重试"


def test_prepare_article_payload_returns_email_message_source_contract(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message_id = email_queries.upsert_email_message(_create_message(account_id))

    payload = service.prepare_article_payload(message_id, target_lang="en")

    assert payload["source_type"] == "email_message"
    assert payload["email_message_id"] == message_id
    assert "This release includes benchmark details" in payload["article_text"]
    assert payload["source_title"] == "Research release update"
    assert payload["target_lang"] == "en"


def test_prepare_article_payload_rejects_empty_message_body(service_env):
    service, _data_dir = service_env
    account_id = service.save_account(_create_account())
    message = _create_message(account_id)
    message["provider_message_id"] = "gmail-msg-empty"
    message["body_text"] = ""
    message["snippet"] = ""
    message_id = email_queries.upsert_email_message(message)

    with pytest.raises(Exception) as excinfo:
        service.prepare_article_payload(message_id)

    assert str(excinfo.value) == "email message body is empty"

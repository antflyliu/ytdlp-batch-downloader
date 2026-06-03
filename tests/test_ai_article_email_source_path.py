from __future__ import annotations

import sys
from pathlib import Path

import monitor.db as monitor_db
import monitor.db.connection as db_connection
import pytest
from monitor.db.queries import email_collect as email_queries
from monitor.email_collect.service import EmailCollectService

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    return service


def _create_account(service: EmailCollectService) -> int:
    return service.save_account(
        {
            "provider": "gmail",
            "display_name": "AI Feed",
            "email_address": "feed@example.com",
            "gmail_client_id": "client-id",
            "gmail_client_secret": "secret-1",
            "gmail_refresh_token": "refresh-1",
        }
    )


def test_prepare_article_payload_uses_email_message_source_metadata(service_env):
    service = service_env
    account_id = _create_account(service)
    message_id = email_queries.upsert_email_message(
        {
            "account_id": account_id,
            "provider": "gmail",
            "provider_message_id": "gmail-msg-17",
            "subject": "AI Weekly",
            "from_addr": "Feed <feed@example.com>",
            "received_at": "2026-05-01T10:00:00+08:00",
            "sent_at": "2026-05-01T10:00:00+08:00",
            "snippet": "Email body for article generation.",
            "body_text": (
                "Email body for article generation. It contains enough product details, "
                "release context, and implementation notes to stay above the ignore threshold."
            ),
            "body_hash": "hash-17",
            "classification": {"action": "generate_variants"},
            "cleaning_report": {"removed_quoted_chain": False},
            "processing_status": "classified",
            "source_url": "https://mail.google.com/mail/u/0/#all/gmail-msg-17",
        }
    )

    payload = service.prepare_article_payload(message_id, target_lang="zh-Hans")

    assert payload == {
        "monitor_video_id": None,
        "video_id": None,
        "video_url": None,
        "video_title": "AI Weekly",
        "source_type": "email_message",
        "email_message_id": message_id,
        "article_text": (
            "Email body for article generation. It contains enough product details, "
            "release context, and implementation notes to stay above the ignore threshold."
        ),
        "source_url": "https://mail.google.com/mail/u/0/#all/gmail-msg-17",
        "source_title": "AI Weekly",
        "target_lang": "zh-Hans",
    }


def test_prepare_article_payload_uses_fallback_title_and_source_url_when_message_metadata_missing(service_env):
    service = service_env
    account_id = _create_account(service)
    message_id = email_queries.upsert_email_message(
        {
            "account_id": account_id,
            "provider": "imap",
            "provider_message_id": "imap-msg-18",
            "subject": "",
            "from_addr": "Feed <feed@example.com>",
            "received_at": "2026-05-01T10:00:00+08:00",
            "sent_at": "2026-05-01T10:00:00+08:00",
            "snippet": "Long enough body.",
            "body_text": (
                "This message omits title metadata but still contains enough body text "
                "to produce an article payload for downstream generation."
            ),
            "body_hash": "hash-18",
            "classification": {"action": "generate_variants"},
            "cleaning_report": {"removed_quoted_chain": False},
            "processing_status": "classified",
            "source_url": "",
        }
    )

    payload = service.prepare_article_payload(message_id)

    assert payload["video_title"] == f"Email {message_id}"
    assert payload["source_title"] == f"Email {message_id}"
    assert payload["source_url"] == f"/api/email/messages/{message_id}"

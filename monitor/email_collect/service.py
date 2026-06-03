from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import monitor.db as db
import logging_config
from monitor.db.queries import email_collect as queries

from .cleaner import clean_parsed_email, clean_text
from .errors import EmailAccountValidationError, EmailProviderError
from .gmail_client import (
    DEFAULT_GMAIL_SCOPES,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    GmailClient,
    build_gmail_authorization_url,
    exchange_gmail_oauth_code,
    normalize_gmail_scopes,
)
from .imap_client import ImapClient
from .outlook_email_client import OutlookEmailClient
from .processor import LinkFetcher, analyze_email_content
from .smtp_client import test_smtp_connection
from .variants import build_platform_variant

SAFE_PROVIDER_ERROR_MESSAGE = "邮箱服务连接失败，请检查配置或稍后重试"
_log = logging_config.get_logger("monitor.email_collect.service")
GMAIL_OAUTH_CALLBACK_PATH = "/api/email/auth/gmail/callback"
GMAIL_OAUTH_SUCCESS_PAGE = "/#/email-pipeline?gmail_auth=success"
GMAIL_OAUTH_FAILURE_PAGE = "/#/email-pipeline?gmail_auth=failed"
REQUIRED_GMAIL_OAUTH_SCOPES = {GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE}


class EmailCollectService:
    def list_accounts(self) -> list[dict]:
        return queries.list_email_accounts()

    def get_account(self, account_id: int, *, include_secrets: bool = False) -> dict | None:
        return queries.get_email_account(account_id, include_secrets=include_secrets)

    def save_account(self, payload: dict[str, Any], *, account_id: int | None = None) -> int:
        try:
            return queries.save_email_account(payload, account_id=account_id)
        except ValueError as exc:
            raise EmailAccountValidationError(str(exc)) from exc

    def gmail_oauth_status(self, *, base_url: str = "", account_id: int | None = None) -> dict[str, Any]:
        cfg = db.load_config()
        client_id, client_secret = self._gmail_oauth_client(cfg)
        redirect_uri = self._gmail_redirect_uri(cfg, base_url)
        scopes = self._gmail_oauth_scopes(cfg)
        status: dict[str, Any] = {
            "configured": bool(client_id and client_secret),
            "client_id_configured": bool(client_id),
            "client_secret_configured": bool(client_secret),
            "redirect_uri": redirect_uri,
            "scopes": scopes,
        }
        if account_id is not None:
            account = self._require_account(account_id)
            account_scopes = normalize_gmail_scopes(account.get("gmail_scope"), ())
            account_scope_set = set(account_scopes)
            has_refresh_token = bool(account.get("has_gmail_refresh_token"))
            status.update(
                {
                    "account_id": account_id,
                    "email_address": account.get("email_address") or "",
                    "has_refresh_token": has_refresh_token,
                    "account_scopes": account_scopes,
                    "read_authorized": has_refresh_token and GMAIL_READONLY_SCOPE in account_scope_set,
                    "send_authorized": has_refresh_token and GMAIL_SEND_SCOPE in account_scope_set,
                    "authorized": has_refresh_token
                    and GMAIL_READONLY_SCOPE in account_scope_set
                    and GMAIL_SEND_SCOPE in account_scope_set,
                }
            )
        return status

    def start_gmail_oauth(
        self,
        account_id: int | None = None,
        *,
        base_url: str,
        return_to: str = "",
    ) -> dict[str, Any]:
        account = self._require_account(account_id, include_secrets=True) if account_id else None
        if account and account.get("provider") != "gmail":
            raise EmailAccountValidationError("Gmail OAuth can only be started for Gmail accounts")
        cfg = db.load_config()
        client_id, client_secret = self._gmail_oauth_client(cfg, fallback_account=account)
        if not client_id or not client_secret:
            raise EmailAccountValidationError("Gmail OAuth client is not configured")
        scopes = self._gmail_oauth_scopes(cfg)
        redirect_uri = self._gmail_redirect_uri(cfg, base_url)
        state = queries.create_oauth_state(
            account_id=account_id,
            scopes=scopes,
            redirect_uri=redirect_uri,
            return_to=return_to,
        )
        auth_url = build_gmail_authorization_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scopes=scopes,
            login_hint=(account or {}).get("email_address") or "",
        )
        result: dict[str, Any] = {
            "ok": True,
            "authorization_url": auth_url,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
        }
        if account_id:
            result["account_id"] = account_id
        return result

    def finish_gmail_oauth(
        self,
        *,
        state: str,
        code: str,
        error: str = "",
        base_url: str = "",
    ) -> dict[str, Any]:
        if error:
            raise EmailAccountValidationError("Gmail OAuth authorization was denied")
        if not state or not code:
            raise EmailAccountValidationError("Gmail OAuth callback missing state or code")
        oauth_state = queries.consume_oauth_state(state)
        if not oauth_state:
            raise EmailAccountValidationError("Gmail OAuth state is invalid or expired")
        raw_account_id = oauth_state.get("account_id")
        account_id = int(raw_account_id) if raw_account_id not in (None, "") else None
        account = self._require_account(account_id, include_secrets=True) if account_id else None
        cfg = db.load_config()
        client_id, client_secret = self._gmail_oauth_client(cfg, fallback_account=account)
        redirect_uri = str(oauth_state.get("redirect_uri") or self._gmail_redirect_uri(cfg, base_url))
        if not client_id or not client_secret:
            raise EmailAccountValidationError("Gmail OAuth client is not configured")
        try:
            token_data = exchange_gmail_oauth_code(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                code=code,
            )
        except EmailProviderError:
            raise
        granted_scopes = normalize_gmail_scopes(token_data.get("scope") or oauth_state.get("requested_scopes"))
        if set(granted_scopes) - REQUIRED_GMAIL_OAUTH_SCOPES:
            raise EmailAccountValidationError("Unsupported Gmail OAuth scope granted")
        required = set(normalize_gmail_scopes(oauth_state.get("requested_scopes")))
        if not required.issubset(set(granted_scopes)):
            raise EmailAccountValidationError("Gmail OAuth granted scopes are incomplete")
        exchange_refresh_token = str(token_data.get("refresh_token") or "").strip()
        stored_refresh_token = str((account or {}).get("gmail_refresh_token") or "").strip()
        stored_scope_set = set(normalize_gmail_scopes((account or {}).get("gmail_scope"), ())) if account else set()
        if exchange_refresh_token:
            refresh_token = exchange_refresh_token
        elif account and stored_refresh_token and required.issubset(stored_scope_set):
            refresh_token = stored_refresh_token
        else:
            raise EmailAccountValidationError("Gmail OAuth did not return a refresh token; reconnect with consent")
        next_account = self._gmail_oauth_probe_account(
            account,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            scopes=granted_scopes,
        )
        profile = GmailClient(next_account).test_connection()
        profile_email = str(profile.get("emailAddress") or "").strip().lower()
        if not profile_email:
            raise EmailAccountValidationError("Gmail OAuth profile did not return an email address")
        created = False
        if account:
            account_email = str(account.get("email_address") or "").strip().lower()
            if account_email and profile_email != account_email:
                raise EmailAccountValidationError("Gmail OAuth account does not match the configured email address")
            saved_account_id = int(account["id"])
            if not queries.update_gmail_oauth_credentials(
                saved_account_id,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                scopes=granted_scopes,
                email_address=profile.get("emailAddress") or account.get("email_address"),
            ):
                raise EmailAccountValidationError("email account not found")
        else:
            existing = queries.get_email_account_by_provider_email(
                "gmail",
                profile_email,
                include_secrets=True,
            )
            if existing:
                saved_account_id = int(existing["id"])
                if not queries.update_gmail_oauth_credentials(
                    saved_account_id,
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=refresh_token,
                    scopes=granted_scopes,
                    email_address=profile.get("emailAddress") or existing.get("email_address"),
                ):
                    raise EmailAccountValidationError("email account not found")
            else:
                saved_account_id = queries.save_email_account(
                    {
                        "provider": "gmail",
                        "display_name": self._gmail_account_display_name(profile_email),
                        "email_address": profile.get("emailAddress") or profile_email,
                        "status": "active",
                        "gmail_client_id": client_id,
                        "gmail_client_secret": client_secret,
                        "gmail_refresh_token": refresh_token,
                        "gmail_scope": granted_scopes,
                        "sync_mode": "poll",
                        "poll_interval_seconds": 300,
                        "include_spam_trash": False,
                        "max_messages_per_sync": 20,
                    }
                )
                created = True
        return {
            "ok": True,
            "account_id": saved_account_id,
            "created": created,
            "email_address": profile.get("emailAddress") or profile_email,
            "scopes": granted_scopes,
            "return_to": oauth_state.get("return_to") or "",
        }

    def delete_account(self, account_id: int) -> bool:
        return queries.delete_email_account(account_id)

    def set_account_status(self, account_id: int, status: str) -> bool:
        return queries.update_email_account_status(account_id, status)

    def test_account(self, account_id: int) -> dict[str, Any]:
        account = self._require_account(account_id, include_secrets=True)
        results: dict[str, Any] = {"account_id": account_id, "provider": account.get("provider")}
        if account.get("provider") == "gmail":
            gmail = GmailClient(account)
            results["gmail"] = gmail.test_connection()
            results["gmail_send"] = gmail.test_send_capability()
        elif account.get("provider") == "outlook_email":
            results["outlook_email"] = OutlookEmailClient(account).test_connection()
        else:
            results["imap"] = ImapClient(account).test_connection()
            results["smtp"] = test_smtp_connection(account)
        return {"ok": True, "results": results}

    def send_gmail_message(self, account_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._require_account(account_id, include_secrets=True)
        if account.get("provider") != "gmail":
            raise EmailAccountValidationError("Gmail API sending is only available for Gmail accounts")
        to_addr = str((payload or {}).get("to") or "").strip()
        subject = str((payload or {}).get("subject") or "").strip()
        body_text = str((payload or {}).get("body") or (payload or {}).get("body_text") or "").strip()
        if not to_addr or not subject or not body_text:
            raise EmailAccountValidationError("to, subject and body are required")
        if GMAIL_SEND_SCOPE not in set(normalize_gmail_scopes(account.get("gmail_scope"), ())):
            raise EmailAccountValidationError("Gmail send scope is not authorized; reconnect Gmail")
        try:
            result = GmailClient(account).send_message(to=to_addr, subject=subject, body_text=body_text)
            return {"ok": True, "provider": "gmail", "message": result}
        except EmailProviderError:
            raise
        except Exception as exc:
            raise EmailProviderError(SAFE_PROVIDER_ERROR_MESSAGE) from exc

    def sync_account(self, account_id: int, *, max_messages: int | None = None) -> dict[str, Any]:
        account = self._require_account(account_id, include_secrets=True)
        max_items = max_messages or int(account.get("max_messages_per_sync") or 20)
        try:
            if account.get("provider") == "gmail":
                parsed_messages = GmailClient(account).fetch_recent(max_messages=max_items)
            elif account.get("provider") == "outlook_email":
                parsed_messages = OutlookEmailClient(account).fetch_recent(max_messages=max_items)
            else:
                parsed_messages = ImapClient(account).fetch_recent(max_messages=max_items)
            upserted: list[int] = []
            for parsed in parsed_messages:
                upserted.append(self.persist_parsed_message(account, parsed))
            queries.mark_email_account_sync(account_id)
            return {"ok": True, "account_id": account_id, "message_ids": upserted, "synced_count": len(upserted)}
        except Exception as exc:
            _log.warning("Email sync failed for account %s: %s", account_id, exc, exc_info=True)
            queries.mark_email_account_sync(account_id, error=SAFE_PROVIDER_ERROR_MESSAGE)
            if isinstance(exc, EmailProviderError):
                raise EmailProviderError(SAFE_PROVIDER_ERROR_MESSAGE) from exc
            raise EmailProviderError(SAFE_PROVIDER_ERROR_MESSAGE) from exc

    def persist_parsed_message(self, account: dict[str, Any], parsed) -> int:
        cleaned = clean_parsed_email(parsed)
        analysis = self._analyze_cleaned_message(
            subject=parsed.subject,
            body_text=cleaned.body_text,
            from_addr=parsed.from_addr,
            html_body=parsed.html_body,
        )
        classification = analysis["classification"]
        cleaning_report = self._merge_cleaning_report(cleaned.report, analysis.get("cleaning_report") or {})
        provider = parsed.provider or account.get("provider")
        provider_message_id = parsed.provider_message_id or parsed.rfc_message_id or cleaned.body_hash
        source_paths = self._persist_message_sources(
            account_id=account.get("id"),
            provider=provider,
            provider_message_id=provider_message_id,
            html_body=parsed.html_body,
            raw_mime=parsed.raw_mime,
        )
        message_id = queries.upsert_email_message(
            {
                "account_id": account.get("id"),
                "provider": provider,
                "provider_message_id": provider_message_id,
                "provider_thread_id": parsed.provider_thread_id,
                "rfc_message_id": parsed.rfc_message_id,
                "subject": parsed.subject,
                "from_addr": parsed.from_addr,
                "to_addr": parsed.to_addr,
                "cc_addr": parsed.cc_addr,
                "received_at": parsed.received_at,
                "sent_at": parsed.sent_at,
                "snippet": cleaned.snippet or parsed.snippet,
                "body_text": cleaned.body_text,
                "html_body_path": source_paths.get("html_body_path"),
                "raw_mime_path": source_paths.get("raw_mime_path"),
                "body_hash": cleaned.body_hash,
                "dedupe_key": f"{provider}:{provider_message_id}",
                "classification": classification,
                "cleaning_report": cleaning_report,
                "processing_status": "ignored" if classification.get("action") == "ignore" else "classified",
                "source_url": self._source_url(provider, provider_message_id),
            },
            [
                {
                    "filename": item.filename,
                    "content_type": item.content_type,
                    "size": item.size,
                    "content_id": item.content_id,
                    "disposition": item.disposition,
                }
                for item in parsed.attachments
            ],
        )
        if provider != "gmail":
            queries.update_email_message(message_id, source_url=self._local_message_url(message_id))
        return message_id

    def list_messages(self, *, account_id: int | None, status: str | None, q: str | None, limit: int, offset: int):
        return queries.list_email_messages(account_id=account_id, status=status, q=q, limit=limit, offset=offset)

    def get_message(self, message_id: int, *, include_body: bool = True) -> dict | None:
        return queries.get_email_message(message_id, include_body=include_body)

    def reclean_message(self, message_id: int) -> dict[str, Any]:
        message = self._require_message(message_id)
        cleaned = clean_text(message.get("body_text") or "")
        classification = self._classification_after_reclean(message.get("classification") or {})
        queries.update_email_message(
            message_id,
            body_text=cleaned.body_text,
            snippet=cleaned.snippet,
            body_hash=cleaned.body_hash,
            cleaning_report=cleaned.report,
            classification=classification,
            processing_status="cleaned",
        )
        return self._require_message(message_id)

    def classify_message(self, message_id: int) -> dict[str, Any]:
        return self.reprocess_message(message_id, expand_links=False)

    def reprocess_message(
        self,
        message_id: int,
        *,
        expand_links: bool = False,
        link_fetcher: LinkFetcher | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        message = self._require_message(message_id)
        cleaned = clean_text(message.get("body_text") or "")
        html_body = self._read_message_source_text(message.get("html_body_path"))
        analysis = self._analyze_cleaned_message(
            subject=message.get("subject") or "",
            body_text=cleaned.body_text,
            from_addr=message.get("from_addr") or "",
            html_body=html_body,
            expand_links=expand_links,
            link_fetcher=link_fetcher,
            max_depth=max_depth,
        )
        classification = analysis["classification"]
        cleaning_report = self._merge_cleaning_report(cleaned.report, analysis.get("cleaning_report") or {})
        queries.update_email_message(
            message_id,
            body_text=cleaned.body_text,
            snippet=cleaned.snippet,
            body_hash=cleaned.body_hash,
            cleaning_report=cleaning_report,
            classification=classification,
            processing_status="ignored" if classification.get("action") == "ignore" else "classified",
        )
        return self._require_message(message_id)

    def mark_ignored(self, message_id: int) -> bool:
        return queries.update_email_message(message_id, processing_status="ignored")

    def prepare_article_payload(self, message_id: int, *, target_lang: str = "zh-Hans") -> dict[str, Any]:
        message = self._require_message(message_id)
        body = self._message_analysis_text(message)
        if not body:
            raise EmailAccountValidationError("email message body is empty")
        return {
            "monitor_video_id": None,
            "video_id": None,
            "video_url": None,
            "video_title": message.get("subject") or f"Email {message_id}",
            "source_type": "email_message",
            "email_message_id": message_id,
            "article_text": body,
            "source_url": message.get("source_url") or self._local_message_url(message_id),
            "source_title": message.get("subject") or f"Email {message_id}",
            "target_lang": target_lang,
        }

    def generate_variants(
        self,
        message_id: int,
        *,
        article_task_id: str | None = None,
        platforms: list[str] | None = None,
        replace_existing: bool = False,
    ) -> list[dict[str, Any]]:
        message = self._require_message(message_id)
        targets = queries.list_content_targets(enabled_only=True)
        wanted = set(platforms or (message.get("classification") or {}).get("recommended_targets") or [])
        if not wanted:
            wanted = {target["platform"] for target in targets}
        output_root = self._variant_output_root()
        output_root.mkdir(parents=True, exist_ok=True)
        created: list[dict[str, Any]] = []
        for target in targets:
            platform = target["platform"]
            if platform not in wanted:
                continue
            existing = queries.list_content_variants(
                source_type="email_message",
                source_id=str(message_id),
                platform=platform,
                include_body=True,
            )
            if existing and not replace_existing:
                created.append(existing[0])
                continue
            variant = build_platform_variant(
                platform=platform,
                source_title=message.get("subject") or "",
                body_text=self._message_analysis_text(message),
                classification=message.get("classification") or {},
                analysis_rules=self._email_analysis_rules(),
            )
            body_path = output_root / f"email_{message_id}_{platform}.md"
            body_path.write_text(variant["body"], encoding="utf-8")
            variant_id = queries.create_content_variant(
                source_type="email_message",
                source_id=str(message_id),
                article_task_id=article_task_id,
                target_id=target.get("id"),
                platform=platform,
                title=variant["title"],
                summary=variant["summary"],
                body_path=str(body_path),
                metadata=variant["metadata"],
                quality=variant["quality"],
            )
            variant["id"] = variant_id
            variant["body_path"] = str(body_path)
            created.append(variant)
        queries.update_email_message(message_id, processing_status="generated")
        return created

    def list_targets(self) -> list[dict]:
        return queries.list_content_targets()

    def update_target(self, target_id: int, payload: dict[str, Any]) -> dict:
        try:
            target = queries.update_content_target(target_id, payload or {})
        except ValueError as exc:
            raise EmailAccountValidationError(str(exc)) from exc
        if not target:
            raise EmailAccountValidationError("content target not found")
        return target

    def list_variants(self, *, source_type: str | None, source_id: str | None, platform: str | None, include_body: bool):
        return queries.list_content_variants(
            source_type=source_type,
            source_id=source_id,
            platform=platform,
            include_body=include_body,
        )

    def get_variant(self, variant_id: int, *, include_body: bool = True) -> dict | None:
        return queries.get_content_variant(variant_id, include_body=include_body)

    def update_variant(self, variant_id: int, payload: dict[str, Any]) -> dict:
        existing = queries.get_content_variant(variant_id, include_body=True)
        if not existing:
            raise EmailAccountValidationError("content variant not found")
        update_payload = dict(payload or {})
        update_payload.pop("body_path", None)
        body_text = None
        body_path = None
        previous_body = None
        previous_existed = False
        body_written = False
        if "body" in update_payload:
            body_text = str(update_payload.pop("body") or "")
            body_path = self._safe_variant_body_path(existing, variant_id)
            update_payload["body_path"] = str(body_path)
        try:
            queries.validate_content_variant_update_payload(existing, update_payload)
            if body_path is not None:
                previous_existed = body_path.exists()
                previous_body = body_path.read_text(encoding="utf-8") if previous_existed else None
                body_path.write_text(body_text or "", encoding="utf-8")
                body_written = True
            updated = queries.update_content_variant(variant_id, update_payload)
        except ValueError as exc:
            if body_written:
                self._restore_variant_body(body_path, previous_body, previous_existed)
            raise EmailAccountValidationError(str(exc)) from exc
        except Exception:
            if body_written:
                self._restore_variant_body(body_path, previous_body, previous_existed)
            raise
        if not updated:
            if body_written:
                self._restore_variant_body(body_path, previous_body, previous_existed)
            raise EmailAccountValidationError("content variant not found")
        return updated

    def export_variant(self, variant_id: int, *, export_format: str = "markdown") -> dict[str, Any]:
        variant = queries.get_content_variant(variant_id, include_body=True)
        if not variant:
            raise EmailAccountValidationError("content variant not found")
        fmt = (export_format or "markdown").strip().lower()
        if fmt == "json":
            content = json.dumps(variant, ensure_ascii=False, indent=2)
            filename = f"email_variant_{variant_id}.json"
        else:
            content = self._variant_markdown(variant)
            filename = f"email_variant_{variant_id}.md"
        return {
            "ok": True,
            "id": variant_id,
            "format": "json" if fmt == "json" else "markdown",
            "filename": filename,
            "content": content,
        }

    def _analyze_cleaned_message(
        self,
        *,
        subject: str,
        body_text: str,
        from_addr: str,
        html_body: str = "",
        expand_links: bool = False,
        link_fetcher: LinkFetcher | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        return analyze_email_content(
            subject=subject,
            body_text=body_text,
            from_addr=from_addr,
            html_body=html_body,
            rules=self._email_analysis_rules(),
            expand_links=expand_links,
            link_fetcher=link_fetcher,
            max_depth=max_depth,
        )

    @staticmethod
    def _email_analysis_rules() -> dict[str, Any]:
        rules = (db.load_config() or {}).get("email_analysis_rules")
        return rules if isinstance(rules, dict) else {}

    @staticmethod
    def _merge_cleaning_report(base: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        report = dict(base or {})
        report["analysis"] = analysis or {}
        return report

    @staticmethod
    def _message_analysis_text(message: dict[str, Any]) -> str:
        classification = message.get("classification") or {}
        analysis_text = str(classification.get("analysis_text") or "").strip()
        return analysis_text or str(message.get("body_text") or "").strip()

    @staticmethod
    def _classification_after_reclean(classification: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(classification or {})
        cleaned.pop("analysis_text", None)
        cleaned["analysis_stale"] = True
        return cleaned

    def _persist_message_sources(
        self,
        *,
        account_id: Any,
        provider: Any,
        provider_message_id: Any,
        html_body: str = "",
        raw_mime: bytes | None = None,
    ) -> dict[str, str]:
        root = self._message_source_root()
        paths: dict[str, str] = {}
        stem = self._message_source_stem(account_id, provider, provider_message_id)
        if html_body:
            root.mkdir(parents=True, exist_ok=True)
            html_path = root / f"{stem}.html"
            html_path.write_text(html_body, encoding="utf-8")
            paths["html_body_path"] = str(html_path)
        if raw_mime:
            root.mkdir(parents=True, exist_ok=True)
            raw_path = root / f"{stem}.eml"
            raw_path.write_bytes(raw_mime)
            paths["raw_mime_path"] = str(raw_path)
        return paths

    @staticmethod
    def _message_source_stem(account_id: Any, provider: Any, provider_message_id: Any) -> str:
        key = f"{account_id or ''}:{provider or ''}:{provider_message_id or ''}"
        return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:32]

    @staticmethod
    def _message_source_root() -> Path:
        return Path(str(db._DATA_DIR)) / "email-message-sources"

    def _read_message_source_text(self, path: str | None) -> str:
        if not path:
            return ""
        try:
            root = self._message_source_root().resolve()
            candidate = Path(str(path)).resolve()
            candidate.relative_to(root)
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return ""
        return ""

    def _require_account(self, account_id: int, *, include_secrets: bool = False) -> dict:
        account = queries.get_email_account(account_id, include_secrets=include_secrets)
        if not account:
            raise EmailAccountValidationError("email account not found")
        return account

    def _gmail_oauth_client(
        self,
        cfg: dict[str, Any],
        *,
        fallback_account: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        client_id = str(cfg.get("gmail_oauth_client_id") or "").strip()
        client_secret = str(cfg.get("gmail_oauth_client_secret") or "").strip()
        if fallback_account:
            client_id = client_id or str(fallback_account.get("gmail_client_id") or "").strip()
            client_secret = client_secret or str(fallback_account.get("gmail_client_secret") or "").strip()
        return client_id, client_secret

    def _gmail_oauth_scopes(self, cfg: dict[str, Any]) -> list[str]:
        scopes = normalize_gmail_scopes(cfg.get("gmail_oauth_scopes") or DEFAULT_GMAIL_SCOPES)
        scope_set = set(scopes)
        unsupported = scope_set - REQUIRED_GMAIL_OAUTH_SCOPES
        if unsupported:
            raise EmailAccountValidationError("Unsupported Gmail OAuth scope requested")
        if not REQUIRED_GMAIL_OAUTH_SCOPES.issubset(scope_set):
            raise EmailAccountValidationError("Gmail OAuth scopes must include receive and send")
        return scopes

    def _gmail_redirect_uri(self, cfg: dict[str, Any], base_url: str) -> str:
        configured = str(cfg.get("gmail_oauth_redirect_uri") or "").strip()
        if configured:
            return configured
        root = self._safe_base_url(base_url)
        return f"{root}{GMAIL_OAUTH_CALLBACK_PATH}"

    @staticmethod
    def _gmail_oauth_probe_account(
        account: dict[str, Any] | None,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        scopes: list[str],
    ) -> dict[str, Any]:
        next_account = dict(account or {})
        next_account.update(
            {
                "provider": "gmail",
                "email_address": next_account.get("email_address") or "me",
                "gmail_client_id": client_id,
                "gmail_client_secret": client_secret,
                "gmail_refresh_token": refresh_token,
                "gmail_scope": scopes,
            }
        )
        return next_account

    @staticmethod
    def _gmail_account_display_name(email_address: str) -> str:
        local_part = str(email_address or "").split("@", 1)[0].strip()
        return local_part or str(email_address or "Gmail").strip() or "Gmail"

    @staticmethod
    def _safe_base_url(base_url: str) -> str:
        parsed = urlparse(str(base_url or ""))
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return "http://127.0.0.1:5000"

    def _require_message(self, message_id: int) -> dict:
        message = queries.get_email_message(message_id, include_body=True)
        if not message:
            raise EmailAccountValidationError("email message not found")
        return message

    @staticmethod
    def _source_url(provider: str, provider_message_id: str) -> str:
        if provider == "gmail" and provider_message_id:
            return f"https://mail.google.com/mail/u/0/#all/{provider_message_id}"
        return ""

    @staticmethod
    def _local_message_url(message_id: int) -> str:
        return f"/api/email/messages/{message_id}"

    @staticmethod
    def _variant_output_root() -> Path:
        data_dir = Path(str(getattr(db, "_DATA_DIR", "data")))
        return data_dir / "email-content-variants"

    def _safe_variant_body_path(self, variant: dict[str, Any], variant_id: int) -> Path:
        root = self._variant_output_root()
        root.mkdir(parents=True, exist_ok=True)
        candidate = Path(str(variant.get("body_path") or ""))
        try:
            resolved_root = root.resolve()
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_root)
            return resolved_candidate
        except (OSError, ValueError):
            platform = str(variant.get("platform") or "content").replace("/", "_").replace("\\", "_")
            return root / f"email_variant_{variant_id}_{platform}.md"

    @staticmethod
    def _restore_variant_body(body_path: Path | None, previous_body: str | None, previous_existed: bool) -> None:
        if body_path is None:
            return
        try:
            if previous_existed:
                body_path.write_text(previous_body or "", encoding="utf-8")
            elif body_path.exists():
                body_path.unlink()
        except OSError:
            pass

    @staticmethod
    def _variant_markdown(variant: dict[str, Any]) -> str:
        title = str(variant.get("title") or "").strip()
        summary = str(variant.get("summary") or "").strip()
        body = str(variant.get("body") or "").strip()
        parts = []
        if title:
            parts.append(f"# {title}")
        if summary:
            parts.append(summary)
        if body:
            parts.append(body)
        return "\n\n".join(parts).strip()

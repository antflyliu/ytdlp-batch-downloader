"""
server/__main__.py — YouTube 视频监控 Web 服务入口
可通过 `python -m server` 或 `python server/__main__.py` 启动
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
import webbrowser
import html
from datetime import datetime
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

# ── 项目路径注入（parent.parent = project root）────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import monitor.db as _db
from config.encryption import _decrypt_config_value
from monitor.video_paths import resolve_downloaded_video_path
import monitor.scheduler as _scheduler
import monitor.provider_scheduler as _provider_scheduler
import monitor.cache as _cache
import monitor.quota as _quota
import monitor.wechat_collector as _wechat_collector
from monitor.db.queries import wechat_collect as _wechat_collect_queries
from monitor.wechat_collect.errors import (
    WechatNativeError,
    WechatSessionError,
    WechatUpstreamError,
    safe_error_message,
)
from monitor.wechat_collect.models import is_valid_mp_article_url, normalize_mp_article_url
from monitor.wechat_collect.native_login import NativeLoginManager
from monitor.wechat_collect.providers import NativeMpProvider
from monitor.wechat_collect.proxy_policy import resolve_native_proxy_plan
from monitor.wechat_collect.serializers import public_account_preview, public_article_preview
from monitor.wechat_collect.session_store import NativeSessionStore
from monitor.wechat_collect.tasks import NativeCollectionTaskService, resolve_output_dir
from monitor.email_collect import EmailCollectService
from monitor.email_collect.errors import EmailAccountValidationError, EmailProviderError
from monitor.email_collect.processor import (
    RULE_SCHEMA_VERSION as EMAIL_ANALYSIS_RULE_SCHEMA_VERSION,
    RULE_VERSION as EMAIL_ANALYSIS_RULE_VERSION,
    coerce_email_analysis_rules_payload,
    email_analysis_rules_schema,
    merge_email_analysis_rules,
    validate_email_analysis_rules,
)
from monitor.email_collect.service import GMAIL_OAUTH_FAILURE_PAGE, GMAIL_OAUTH_SUCCESS_PAGE
from monitor.rss_collect import RssCatalogService, RssCollectService
from monitor.weread_exporter import WeReadExportTaskService, default_output_root
from go_proxy_manager import get_proxy_manager
import logging_config
from utils.paths import get_static_dir as _get_static_dir
from Youtube_Downloader import BatchDownloadCancelled, batch_download, build_aria2_opts
from monitor.dynamic_provider_resolver import (
    log_download_decision,
    resolve_for_manual_download,
    resolve_for_web_batch_download,
)
from monitor.voice import env as voice_env
from monitor.voice.tasks import VoiceTaskManager
from monitor.http_multipart import MultipartParseError, read_single_file_part

_log = logging_config.get_logger("monitor_server")
_voice_task_mgr = VoiceTaskManager()

# ── 速率限制器（每 IP 每分钟 N 次请求；本机回环默认豁免）──
from server.middleware.rate_limit import (
    RATE_LIMIT_WINDOW as _RATE_LIMIT_WINDOW,
    RATE_LIMIT_MAX as _RATE_LIMIT_MAX,
    _rate_limiter,
    _rate_limiter_lock,
)

_WEB_BATCH_ACCOUNT_NAME = "Web 批量下载"
_MASKED_SECRET_VALUE = "***"
_CONFIG_RESPONSE_SECRET_KEYS = {
    "global_dingtalk_sign_secret",
    "global_telegram_token",
    "llm_api_key",
    "whisper_api_key",
    "comfyui_api_key",
    "runninghub_api_key",
    "minimax_api_key",
    "openai_api_key",
    "gemini_api_key",
    "openai_speech_api_key",
    "azure_speech_api_key",
    "minimax_speech_api_key",
    "voxcpm_api_key",
    "vibevoice_tts_api_key",
    "vibevoice_asr_api_key",
    "gmail_oauth_client_secret",
    "wechat_app_secret",
    "wechat_exporter_auth_key",
}
_MAX_RSS_OPML_BODY_BYTES = 10_000_000
_ACCOUNT_RESPONSE_SECRET_KEYS = {
    "dingtalk_sign_secret",
    "telegram_bot_token",
}


def _mask_present_secret(value):
    return _MASKED_SECRET_VALUE if value else ""


def _mask_config_for_response(cfg: dict) -> dict:
    safe = dict(cfg or {})
    for key in _CONFIG_RESPONSE_SECRET_KEYS:
        if key in safe:
            safe[key] = _mask_present_secret(safe.get(key))
    return safe


def _preserve_masked_config_values(new_cfg: dict, old_cfg: dict) -> dict:
    merged = dict(new_cfg or {})
    old = old_cfg or {}
    for key in _CONFIG_RESPONSE_SECRET_KEYS:
        if merged.get(key) == _MASKED_SECRET_VALUE:
            merged[key] = old.get(key, "")
    return merged


_LLM_SECRET_REQUIRED_PROVIDERS = {"qwen", "openai", "anthropic", "groq"}


def _llm_endpoint_identity(cfg: dict) -> str:
    provider = str((cfg or {}).get("llm_provider") or "qwen").strip().lower() or "qwen"
    base_url = str((cfg or {}).get("llm_base_url") or "").strip()
    if not base_url:
        return f"{provider}:default"
    parsed = urlparse(base_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path.rstrip("/")
        return f"{provider}:{parsed.scheme}://{host}:{port}{path}"
    return f"{provider}:{base_url}"


def _validate_llm_endpoint_secret_reentry(body: dict, new_cfg: dict, old_cfg: dict) -> tuple[bool, str | None]:
    if not any(key in body for key in ("llm_provider", "llm_base_url")):
        return True, None
    provider = str((new_cfg or {}).get("llm_provider") or "qwen").strip().lower() or "qwen"
    if provider not in _LLM_SECRET_REQUIRED_PROVIDERS:
        return True, None
    if not (old_cfg or {}).get("llm_api_key"):
        return True, None
    if _llm_endpoint_identity(new_cfg) == _llm_endpoint_identity(old_cfg):
        return True, None
    submitted_secret = body.get("llm_api_key", _db._UNSET)
    if submitted_secret is _db._UNSET or submitted_secret == _MASKED_SECRET_VALUE:
        return False, "llm_provider 或 llm_base_url 变更后必须重新输入 llm_api_key"
    return True, None


def _validate_voice_flow_defaults_config(value) -> tuple[bool, str | None]:
    from monitor.voice.capabilities import (
        AZURE_SPEECH,
        EDGE_TTS,
        LOCAL_HTTP_TTS,
        MINIMAX_SPEECH,
        OPENAI_SPEECH,
        SILENT,
        SPEECH_SYNTHESIS,
        TRANSCRIPTION,
        VIBEVOICE_ASR,
        VIBEVOICE_REALTIME,
        VIBEVOICE_TTS,
        VIBEVOICE_VLLM_ASR,
        VOXCPM_HTTP,
        VOXCPM_OPENAI_SPEECH,
        WHISPER_API,
        WHISPER_LOCAL,
        normalize_provider_id,
    )

    if value in (None, ""):
        return True, None
    if isinstance(value, dict):
        parsed = value
    elif not isinstance(value, str):
        return False, "voice_flow_defaults_json 必须是 JSON 对象"
    else:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return False, "voice_flow_defaults_json 必须是合法 JSON 对象"
        if not isinstance(parsed, dict):
            return False, "voice_flow_defaults_json 必须是 JSON 对象"

    valid_capabilities = {SPEECH_SYNTHESIS, TRANSCRIPTION}
    valid_providers = {
        SILENT,
        EDGE_TTS,
        LOCAL_HTTP_TTS,
        OPENAI_SPEECH,
        AZURE_SPEECH,
        MINIMAX_SPEECH,
        VOXCPM_HTTP,
        VOXCPM_OPENAI_SPEECH,
        VIBEVOICE_TTS,
        VIBEVOICE_REALTIME,
        WHISPER_LOCAL,
        WHISPER_API,
        VIBEVOICE_ASR,
        VIBEVOICE_VLLM_ASR,
    }
    for key, provider_value in parsed.items():
        key_text = str(key or "").strip()
        if "." not in key_text:
            return False, f"voice_flow_defaults_json 包含无效 flow.capability: {key_text}"
        flow, capability = key_text.rsplit(".", 1)
        if not flow or capability not in valid_capabilities:
            return False, f"voice_flow_defaults_json 包含不支持的 capability: {key_text}"
        provider_id = normalize_provider_id(str(provider_value or ""))
        if not provider_id or provider_id not in valid_providers:
            return False, f"voice_flow_defaults_json 包含不支持的 provider: {provider_value}"
    return True, None


_VOICE_ENDPOINT_SECRET_PAIRS = (
    (("openai_speech_base_url",), "openai_speech_api_key"),
    (("azure_speech_endpoint", "azure_speech_region"), "azure_speech_api_key"),
    (("minimax_speech_base_url",), "minimax_speech_api_key"),
    (("voxcpm_base_url",), "voxcpm_api_key"),
    (("vibevoice_tts_base_url",), "vibevoice_tts_api_key"),
    (("vibevoice_asr_base_url",), "vibevoice_asr_api_key"),
)


def _validate_voice_endpoint_secret_reentry(body: dict, new_cfg: dict, old_cfg: dict) -> tuple[bool, str | None]:
    for endpoint_keys, secret_key in _VOICE_ENDPOINT_SECRET_PAIRS:
        if not any(key in body for key in endpoint_keys):
            continue
        old_identity = _voice_endpoint_identity(old_cfg, endpoint_keys)
        new_identity = _voice_endpoint_identity(new_cfg, endpoint_keys)
        if old_identity == new_identity or not new_identity or not old_cfg.get(secret_key):
            continue
        submitted_secret = body.get(secret_key, _db._UNSET)
        if submitted_secret is _db._UNSET or submitted_secret == _MASKED_SECRET_VALUE:
            return False, f"{endpoint_keys[0]} 变更后必须重新输入 {secret_key}"
    return True, None


def _validate_voice_endpoint_urls_config(body: dict, cfg: dict) -> tuple[bool, str | None]:
    for endpoint_keys, _secret_key in _VOICE_ENDPOINT_SECRET_PAIRS:
        if not any(key in body for key in endpoint_keys):
            continue
        identity = _voice_endpoint_identity(cfg, endpoint_keys)
        raw_values = [str(cfg.get(key) or "").strip() for key in endpoint_keys if cfg.get(key)]
        if raw_values and identity == "invalid":
            return False, f"{endpoint_keys[0]} 必须是 http/https URL"
    return True, None


def _voice_endpoint_identity(cfg: dict, endpoint_keys: tuple[str, ...]) -> str:
    if endpoint_keys == ("azure_speech_endpoint", "azure_speech_region"):
        raw = str(cfg.get("azure_speech_endpoint") or "").strip()
        if not raw:
            region = str(cfg.get("azure_speech_region") or "").strip()
            raw = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1" if region else ""
    else:
        raw = str(cfg.get(endpoint_keys[0]) or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid"
    host = (parsed.hostname or "").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{host}:{port}"


def _mask_account_for_response(account: dict) -> dict:
    safe = dict(account or {})
    for key in _ACCOUNT_RESPONSE_SECRET_KEYS:
        safe[key] = _mask_present_secret(safe.get(key))
    return safe


def _resolve_masked_account_secret(account_id: int, field: str, submitted):
    if submitted != _MASKED_SECRET_VALUE:
        return submitted or None
    account = _db.get_account(account_id) or {}
    return account.get(field) or None


def _email_analysis_rules_history_path() -> Path:
    return Path(str(_db._DATA_DIR)) / "email-analysis-rules-history.json"


def _load_email_analysis_rules_history() -> list[dict]:
    path = _email_analysis_rules_history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_email_analysis_rules_history(history: list[dict]) -> None:
    path = _email_analysis_rules_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _email_analysis_rules_version_id(rules: dict, created_at: str) -> str:
    payload = json.dumps(
        {
            "schema_version": EMAIL_ANALYSIS_RULE_SCHEMA_VERSION,
            "rule_version": EMAIL_ANALYSIS_RULE_VERSION,
            "created_at": created_at,
            "rules": rules,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _append_email_analysis_rules_history(
    rules: dict,
    *,
    note: str = "",
    source: str = "settings-center",
) -> dict:
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    record = {
        "version_id": _email_analysis_rules_version_id(rules, created_at),
        "created_at": created_at,
        "schema_version": EMAIL_ANALYSIS_RULE_SCHEMA_VERSION,
        "rule_version": EMAIL_ANALYSIS_RULE_VERSION,
        "source": source,
        "note": str(note or "").strip()[:300],
        "rules": rules,
    }
    history = _load_email_analysis_rules_history()
    history.insert(0, record)
    _write_email_analysis_rules_history(history[:50])
    return record


def _resolve_optional_account_secret(account_id: int, field: str, body: dict):
    if field not in body:
        return _db._UNSET
    return _resolve_masked_account_secret(account_id, field, body.get(field))


def _optional_nullable_body_value(body: dict, field: str):
    if field not in body:
        return _db._UNSET
    return body.get(field) or None


def _get_client_ip() -> str:
    """从请求中提取真实 IP（支持 X-Forwarded-For）"""
    return ""  # placeholder, overridden in handler


# ── 下载任务管理器 ────────────────────────────────────────────
class _DownloadTaskManager:
    """
    线程安全的后台下载任务管理器。
    每个任务跟踪进度、状态和每个视频的下载结果。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict] = {}

    def create_task(
        self,
        video_records: list[dict],
        output_path: str,
        *,
        task_kind: str = "generic",
        source_name: str | None = None,
        persist_task: bool = False,
    ) -> str:
        """创建下载任务，返回 task_id"""
        task_id = uuid.uuid4().hex[:12]
        task = {
            "task_id": task_id,
            "task_kind": task_kind,
            "source_name": source_name,
            "persist_task": persist_task,
            "status": "running",
            "total": len(video_records),
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current_video": "",
            "results": [],
            "output_path": output_path,
            "cancel_requested": False,
            "cancel_message": None,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "finished_at": None,
        }
        with self._lock:
            self._cleanup_old_locked()
            self._tasks[task_id] = task
            self._persist_task_locked(task)
        return task_id

    def update_progress(self, task_id: str, completed: int, status_text: str):
        with self._lock:
            t = self._tasks.get(task_id)
            if t and t.get("status") != "cancelled":
                t["completed"] = completed
                t["current_video"] = status_text
                self._persist_task_locked(t)

    def finish_task(self, task_id: str, results: list[dict]):
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                if t.get("status") == "cancelled":
                    return
                t["status"] = "done"
                t["results"] = results
                t["completed"] = t["total"]
                t["success"] = sum(
                    1 for r in results if (r.get("状态") or r.get("status")) == "成功"
                )
                t["failed"] = sum(
                    1 for r in results if (r.get("状态") or r.get("status")) == "失败"
                )
                t["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                self._persist_task_locked(t)

    def fail_task(self, task_id: str, error: str):
        with self._lock:
            t = self._tasks.get(task_id)
            if t:
                if t.get("status") == "cancelled":
                    return
                t["status"] = "error"
                t["error"] = error
                t["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                self._persist_task_locked(t)

    def request_cancel(self, task_id: str, message: str = "正在取消下载任务…") -> dict | None:
        with self._lock:
            self._cleanup_old_locked()
            t = self._tasks.get(task_id)
            if not t:
                return None
            if t["status"] in ("done", "error", "cancelled"):
                return dict(t)
            t["cancel_requested"] = True
            t["cancel_message"] = message
            t["status"] = "cancelling"
            t["current_video"] = message
            self._persist_task_locked(t)
            return dict(t)

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            self._cleanup_old_locked()
            t = self._tasks.get(task_id)
            return bool(t and t.get("cancel_requested"))

    def cancel_task(self, task_id: str, results: list[dict] | None = None, message: str = "下载任务已取消"):
        with self._lock:
            self._cleanup_old_locked()
            t = self._tasks.get(task_id)
            if not t:
                return
            normalized_results = results if results is not None else t.get("results", [])
            t["status"] = "cancelled"
            t["cancel_requested"] = True
            t["cancel_message"] = message
            t["current_video"] = message
            t["results"] = normalized_results
            t["success"] = sum(
                1 for r in normalized_results if (r.get("状态") or r.get("status")) == "成功"
            )
            t["failed"] = sum(
                1 for r in normalized_results if (r.get("状态") or r.get("status")) == "失败"
            )
            t["completed"] = min(
                t["total"],
                max(int(t.get("completed", 0)), len(normalized_results)),
            )
            t["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._persist_task_locked(t)

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            self._cleanup_old_locked()
            t = self._tasks.get(task_id)
            return dict(t) if t else None

    def list_tasks(self) -> list:
        """返回所有任务列表。"""
        with self._lock:
            self._cleanup_old_locked()
            tasks = [dict(t) for t in self._tasks.values()]
            return sorted(tasks, key=lambda item: item.get("created_at") or "", reverse=True)

    def cleanup_old(self, max_age_sec: int = 3600):
        """清理超过 max_age_sec 的已完成任务"""
        with self._lock:
            self._cleanup_old_locked(max_age_sec=max_age_sec)

    def _cleanup_old_locked(self, max_age_sec: int = 3600):
        now = datetime.now().astimezone()
        to_del = []
        for tid, t in self._tasks.items():
            if t["status"] in ("done", "error", "cancelled") and t.get("finished_at"):
                try:
                    fin = datetime.fromisoformat(t["finished_at"])
                    if (now - fin).total_seconds() > max_age_sec:
                        to_del.append(tid)
                except Exception:
                    pass
        for tid in to_del:
            del self._tasks[tid]

    def _persist_task_locked(self, task: dict):
        if task.get("persist_task") and task.get("task_kind") == "web_batch":
            _db.save_web_batch_task(task)


_task_mgr = _DownloadTaskManager()
_wechat_collect_mgr = _wechat_collector.WechatCollectionTaskManager()
_wechat_native_session_store = NativeSessionStore()
_wechat_native_login_mgr = NativeLoginManager(
    store=_wechat_native_session_store,
    proxy_plan_factory=lambda: resolve_native_proxy_plan(cookies_present=True),
)
_wechat_native_task_service = NativeCollectionTaskService()
_email_collect_service = EmailCollectService()
_rss_collect_service = RssCollectService()
_rss_catalog_service = RssCatalogService()
_weread_export_service = WeReadExportTaskService()

class _BatchUploadStore:
    """缓存 Web 批量下载上传解析结果，避免前端持有完整 URL 集。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._uploads: dict[str, dict] = {}

    def create_upload(self, filename: str, urls: list[str]) -> str:
        upload_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._cleanup_old_locked()
            self._uploads[upload_id] = {
                "upload_id": upload_id,
                "filename": filename,
                "urls": list(urls),
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        return upload_id

    def get_upload(self, upload_id: str) -> dict | None:
        with self._lock:
            self._cleanup_old_locked()
            item = self._uploads.get(upload_id)
            return {
                "upload_id": item["upload_id"],
                "filename": item["filename"],
                "urls": list(item["urls"]),
                "created_at": item["created_at"],
            } if item else None

    def _cleanup_old_locked(self, max_age_sec: int = 3600):
        now = datetime.now().astimezone()
        expired: list[str] = []
        for upload_id, item in self._uploads.items():
            created_at = item.get("created_at")
            if not created_at:
                continue
            try:
                created = datetime.fromisoformat(created_at)
            except Exception:
                continue
            if (now - created).total_seconds() > max_age_sec:
                expired.append(upload_id)
        for upload_id in expired:
            self._uploads.pop(upload_id, None)


# _task_mgr and _batch_upload_mgr are real instances (restored after failed __getattribute__ approach)
_batch_upload_mgr = _BatchUploadStore()

# ── PyInstaller 兼容路径 ───────────────────────────────────────
# Delegates to utils.paths.get_static_dir() which handles both frozen (PyInstaller)
# and dev environments, pointing to project_root/monitor_web/.
# Subdirectories served:
#   /static/css/*.css      → monitor_web/static/css/
#   /templates/*.html      → monitor_web/templates/  (loaded by client-side fetch())
#   /js/**/*.js            → monitor_web/js/
#   /                      → monitor_web/index.html
_STATIC_DIR = _get_static_dir()
_INDEX_HTML = _STATIC_DIR / "index.html"


_YOUTUBE_URL_RE = re.compile(
    r"^https://(www\.)?(youtube\.com|youtu\.be)/"
)
_YOUTUBE_HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,100}$")
_YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,40}$")


def _normalize_fs_path(path: str) -> str:
    """规范化文件系统路径，兼容 Windows 大小写与符号链接。"""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _is_path_within(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath([candidate, root]) == root
    except ValueError:
        return False


def _clean_background_error(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _run_article_task_safely(task_id: str, cfg: dict | None = None) -> None:
    """Run an article task in a background thread and persist startup failures."""
    try:
        from scripts.article_generator import run_article_task

        run_article_task(task_id, cfg=cfg)
    except Exception as exc:
        message = _clean_background_error(exc) or "文章生成任务异常退出"
        _log.exception("[AI Article] task=%s 后台线程异常退出", task_id)
        try:
            _db.update_article_task(
                task_id,
                status="error",
                current_stage="error",
                error=message,
                finished_at=_db.now_iso(),
            )
        except Exception:
            _log.exception("[AI Article] task=%s 后台异常状态写入失败", task_id)


def _wechat_native_artifact_id_from_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw.split("?", 1)[0]
    prefix = "/api/wechat-native/artifacts/"
    if not path.startswith(prefix):
        return ""
    return unquote(path[len(prefix):]).strip()


def _resolve_download_output_path(requested_path: str, cfg: dict) -> str:
    cfg_output_path = cfg.get("download_output_path", "") or ""
    output_path = (requested_path or "").strip() or str(cfg_output_path).strip()
    if not output_path:
        output_path = os.path.join(_PROJECT_ROOT, "videos")

    abs_output = _normalize_fs_path(output_path)
    abs_root = _normalize_fs_path(_PROJECT_ROOT)
    cfg_path = str(cfg.get("download_output_path", "") or "")
    cfg_abs = _normalize_fs_path(cfg_path) if cfg_path else ""
    allowed_roots = [abs_root]
    if cfg_abs and cfg_abs not in allowed_roots:
        allowed_roots.append(cfg_abs)

    if not any(_is_path_within(abs_output, root) for root in allowed_roots):
        raise ValueError("输出路径必须在允许范围内")

    os.makedirs(abs_output, exist_ok=True)
    return abs_output


def _resolve_cookies_file(requested_path: str | None, cfg: dict) -> str | None:
    cfg_cookies = str(cfg.get("download_cookies_file", "") or "")
    cookies_file = (requested_path or "").strip() or cfg_cookies or None
    if cookies_file and not os.path.isfile(cookies_file):
        _log.warning(f"Cookie 文件不存在，将跳过 Cookie: {cookies_file}")
        return None
    return cookies_file


def _route_to_download_targets(route) -> tuple[str | None, list[str] | None]:
    resolved_proxy: str | None = None
    resolved_proxy_pool: list[str] | None = None
    if route.resolved_proxy_source == "direct":
        return None, None
    if route.resolved_proxy_source == "account_static":
        return route.proxy, None
    if route.resolved_proxy_source in ("system_paid", "system_free"):
        if route.proxy_pool:
            resolved_proxy_pool = route.proxy_pool
        else:
            resolved_proxy = route.proxy
    return resolved_proxy, resolved_proxy_pool


def _normalize_batch_result(result: dict) -> dict:
    return {
        "url": result.get("url") or result.get("URL") or "",
        "status": result.get("status") or result.get("状态") or "",
        "info": result.get("info") or result.get("信息") or "",
    }


def _serialize_batch_task(task: dict, *, include_results: bool) -> dict:
    payload = {
        "task_id": task.get("task_id"),
        "source_name": task.get("source_name"),
        "status": task.get("status"),
        "total": task.get("total", 0),
        "completed": task.get("completed", 0),
        "success": task.get("success", 0),
        "failed": task.get("failed", 0),
        "current_video": task.get("current_video", ""),
        "output_path": task.get("output_path"),
        "error": task.get("error"),
        "cancel_requested": bool(task.get("cancel_requested")),
        "cancel_message": task.get("cancel_message"),
        "created_at": task.get("created_at"),
        "finished_at": task.get("finished_at"),
    }
    if include_results:
        payload["results"] = [
            _normalize_batch_result(result)
            for result in task.get("results", []) or []
        ]
    return payload


def _is_valid_youtube_url(url: str) -> bool:
    """验证频道输入是否合法：支持 @handle、UC 频道 ID 或完整 YouTube URL（防 javascript: 等伪协议注入）"""
    if not url:
        return False
    value = url.strip()
    return (
        _YOUTUBE_URL_RE.match(value) is not None
        or _YOUTUBE_HANDLE_RE.match(value) is not None
        or _YOUTUBE_CHANNEL_ID_RE.match(value) is not None
    )


class MonitorHandler(SimpleHTTPRequestHandler):
    """REST API + 静态文件服务器"""

    # ── 工具方法 ─────────────────────────────────────────────

    # localhost origin 白名单（CORS L-3）
    _LOCALHOST_ORIGIN_RE = re.compile(
        r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    )

    def _allowed_origin(self) -> str | None:
        """返回允许的 CORS origin，若请求 origin 不在白名单则返回 None"""
        origin = self.headers.get("Origin", "")
        if self._LOCALHOST_ORIGIN_RE.match(origin):
            return origin
        return None

    def _reject_disallowed_write_origin(self) -> bool:
        """Reject browser cross-site writes; non-browser/same-origin requests have no Origin."""
        origin = self.headers.get("Origin", "")
        if not origin or self._allowed_origin() == origin:
            return False
        self._send_json({"error": "不允许的请求来源"}, 403)
        return True

    def _reject_invalid_json_content_type(self, path: str) -> bool:
        if path not in {"/api/config", "/api/voice/env/check", "/api/voice/smoke-test"}:
            return False
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            content_length = 0
        if content_length <= 0:
            return False
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json" or content_type.endswith("+json"):
            return False
        self._send_json({"error": "Content-Type 必须是 application/json"}, 415)
        return True

    def _rate_limit_client_ip(self) -> str:
        """客户端 IP（优先 X-Forwarded-For 首段）。"""
        from server.middleware.rate_limit import get_client_ip_from_headers
        return get_client_ip_from_headers(self.headers, self.client_address)

    def _rate_limit_exempt_loopback(self, ip: str) -> bool:
        """本机访问不做全局限流（单用户监控台易与轮询叠加导致误伤 429）。"""
        from server.middleware.rate_limit import is_loopback_ip
        return is_loopback_ip(ip)

    def _check_rate_limit(self) -> bool:
        """
        速率限制：每 IP 每分钟最多 _RATE_LIMIT_MAX 次请求。
        返回 True 表示通过，False 表示触发限流（已发送 429）。
        """
        from server.middleware.rate_limit import check_rate_limit
        ip = self._rate_limit_client_ip()
        is_allowed, retry_after = check_rate_limit(
            ip,
            window=_RATE_LIMIT_WINDOW,
            max_requests=_RATE_LIMIT_MAX,
            rate_limiter=_rate_limiter,
            rate_limiter_lock=_rate_limiter_lock,
        )
        if is_allowed:
            return True
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Retry-After", str(retry_after or _RATE_LIMIT_WINDOW))
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(
            json.dumps({"error": "请求过于频繁，请稍后再试"}, ensure_ascii=False).encode("utf-8")
        )
        return False

    def _path_skips_rate_limit(self, path: str) -> bool:
        """不参与全局限流的路径（高频只读轮询；仅 do_GET 调用）。"""
        from server.middleware.rate_limit import path_skips_rate_limit
        return path_skips_rate_limit(path)

    def _send_json(self, data, status=200):
        """发送 JSON 响应（含 CORS headers）"""
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except (ConnectionAbortedError, BrokenPipeError):
            _log.warning("Connection lost while sending JSON response to %s", self.client_address)

    def _read_json(self):
        """读取并解析 JSON 请求体，失败返回 None"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(content_length))
        except Exception:
            return None

    def _path_only(self):
        """去掉查询字符串，只保留路径"""
        return self.path.split("?")[0]

    def _request_base_url(self) -> str:
        """Build the externally visible base URL used for OAuth redirect URIs."""
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        if proto not in {"http", "https"}:
            proto = "https" if self.headers.get("X-Forwarded-Ssl", "").lower() == "on" else "http"
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",", 1)[0].strip()
        if not host:
            host = f"127.0.0.1:{getattr(self.server, 'server_port', 5000)}"
        host = re.sub(r"[^A-Za-z0-9.\-:\[\]]", "", host)
        return f"{proto}://{host}"

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()

    def _require_auth(self):
        """Monitor HTTP API 为完全开放模式，不校验 Bearer / api_token（仅依赖本机监听与网络隔离）。"""
        return True

    def _mask_key(self, key_value: str) -> str:
        """返回 API Key 的掩码版本（首4+末4字符）"""
        if len(key_value) <= 12:
            return key_value[:4] + "••••••"
        return key_value[:4] + "••••••••" + key_value[-4:]

    def _strip_conditional_headers_for_static(self) -> None:
        """
        去掉条件请求头，避免 SimpleHTTPRequestHandler 对未改文件返回 304。
        304 非错误，但易被误认为异常；本地监控台也希望刷新后立刻加载最新 JS/CSS。
        """
        if not hasattr(self, "headers"):
            return
        # HTTPMessage 无 dict.pop；用 del（忽略缺失）
        for h in ("If-Modified-Since", "If-None-Match"):
            try:
                del self.headers[h]
            except KeyError:
                pass

    def _should_send_no_cache_static(self, path: str) -> bool:
        """对 HTML/JS/CSS 等静态资源建议不缓存，与 _strip_conditional_headers_for_static 配合。"""
        if path.startswith("/api/"):
            return False
        return (
            path in ("/", "")
            or path.endswith(".html")
            or path.startswith("/js/")
            or path.startswith("/css/")
        )

    def end_headers(self):
        """静态 HTML/JS/CSS 附加 Cache-Control，减少浏览器强缓存导致旧脚本。"""
        try:
            path = self.path.split("?")[0]
            if self._should_send_no_cache_static(path):
                self.send_header(
                    "Cache-Control", "no-store, max-age=0, must-revalidate"
                )
        except Exception:
            pass
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        """与 BaseHTTPRequestHandler 一致，但在 HTML 错误页上附加 CORS（便于跨端口调试时控制台可读）。"""
        try:
            shortmsg, longmsg = self.responses[code]
        except KeyError:
            shortmsg, longmsg = "???", "???"
        if message is None:
            message = shortmsg
        if explain is None:
            explain = longmsg
        self.log_error("code %d, message %s", code, message)
        self.send_response(code, message)
        self.send_header("Connection", "close")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        body = None
        if code >= 200 and code not in (
            HTTPStatus.NO_CONTENT,
            HTTPStatus.RESET_CONTENT,
            HTTPStatus.NOT_MODIFIED,
        ):
            content = self.error_message_format % {
                "code": code,
                "message": html.escape(message, quote=False),
                "explain": html.escape(explain, quote=False),
            }
            body = content.encode("UTF-8", "replace")
            self.send_header("Content-Type", self.error_content_type)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
            except (ConnectionAbortedError, BrokenPipeError):
                pass

    def _mask_proxy_url(self, url: str) -> str:
        """返回代理 URL 的掩码版本（隐藏认证信息）"""
        if not url:
            return url
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)
            if parsed.username:
                netloc = f"***@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        except Exception:
            pass
        if '@' in url:
            scheme, rest = url.split('://', 1)
            return f"{scheme}://***@{rest.split('@', 1)[1]}"
        return url

    # ── HTTP 方法 ────────────────────────────────────────────

    def do_GET(self):
        path = self._path_only()
        if not path.startswith("/api/"):
            self._strip_conditional_headers_for_static()
            # ── Vue SPA fallback — all non-API routes return from frontend-vue/dist ──
            vue_dist = os.path.join(_PROJECT_ROOT, 'frontend-vue', 'dist')
            if path == '/':
                # Serve Vue index.html
                try:
                    index_path = os.path.join(vue_dist, 'index.html')
                    with open(index_path, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except (FileNotFoundError, IOError):
                    pass  # fallback to super() below
            elif not path.startswith('/api/'):
                # Try Vue dist first, fallback to super() if not found
                vue_file = os.path.normpath(os.path.join(vue_dist, path.lstrip('/')))
                vue_dist_norm = os.path.normpath(vue_dist)
                # Security: prevent path traversal outside vue_dist
                if os.path.commonpath([vue_file, vue_dist_norm]) != vue_dist_norm:
                    self.send_response(403)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"Forbidden")
                    return
                if os.path.isfile(vue_file):
                    try:
                        with open(vue_file, 'rb') as f:
                            content = f.read()
                        self.send_response(200)
                        # Infer Content-Type from extension
                        import pathlib
                        suffix = pathlib.Path(path).suffix.lower()
                        ctype_map = {
                            '.js': 'application/javascript',
                            '.mjs': 'application/javascript',
                            '.css': 'text/css',
                            '.html': 'text/html',
                            '.json': 'application/json',
                            '.png': 'image/png',
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.svg': 'image/svg+xml',
                            '.ico': 'image/x-icon',
                            '.woff': 'font/woff',
                            '.woff2': 'font/woff2',
                            '.ttf': 'font/ttf',
                        }
                        ctype = ctype_map.get(suffix, 'application/octet-stream')
                        self.send_header("Content-type", ctype)
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    except (FileNotFoundError, IOError):
                        pass  # fallback to super() below
                elif not Path(path).suffix:
                    query = urlparse(self.path).query
                    location = f"/#{quote(path, safe='/%')}"
                    if query:
                        location = f"{location}?{query}"
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", location)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            try:
                super().do_GET()
            except (ConnectionAbortedError, BrokenPipeError):
                _log.warning("静态响应期间客户端中断连接: %s", path)
            return
        if path == "/api/status":
            self._api_status()
            return
        if path == "/api/email/auth/gmail/callback":
            self._api_email_gmail_oauth_callback()
            return
        if not self._require_auth():
            return
        if not self._path_skips_rate_limit(path) and not self._check_rate_limit():
            return
        if path.startswith("/api/video-stream"):
            self._api_video_stream()
            return
        if path == "/api/accounts":
            self._api_accounts()
            return
        elif path == "/api/events":
            self._api_events()
        elif path == "/api/stats":
            self._api_stats()
        elif path == "/api/config":
            self._api_config()
        elif path == "/api/voice/providers":
            self._api_voice_providers()
        elif path == "/api/voice/env":
            self._api_voice_env()
        elif path == "/api/voice/tasks":
            self._api_voice_tasks_list()
        elif path == "/api/voice/file":
            self._api_voice_file()
        elif path.startswith("/api/voice/tasks/") and self.command == "GET":
            task_id = path.rsplit("/", 1)[-1]
            self._api_voice_task_get(task_id)
        elif path == "/api/wechat/config":
            self._api_wechat_config()
            return
        elif path == "/api/wechat-collect/config":
            self._api_wechat_collect_config()
            return
        elif path == "/api/wechat-native/config":
            self._api_wechat_native_config()
            return
        elif path == "/api/weread-exporter/config":
            self._api_weread_exporter_config()
            return
        elif path == "/api/weread-exporter/tasks":
            self._api_weread_exporter_tasks_list()
            return
        elif path.startswith("/api/weread-exporter/artifacts/"):
            artifact_id = unquote(path.split("/api/weread-exporter/artifacts/", 1)[1])
            self._api_weread_exporter_artifact(artifact_id)
            return
        elif path.startswith("/api/weread-exporter/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            self._api_weread_exporter_task_status(task_id)
            return
        elif path == "/api/wechat-native/sessions":
            self._api_wechat_native_sessions()
            return
        elif path.startswith("/api/wechat-native/login/") and path.endswith("/qrcode"):
            login_id = path.split("/")[-2]
            self._api_wechat_native_login_qrcode(login_id)
            return
        elif path.startswith("/api/wechat-native/login/") and path.endswith("/scan"):
            login_id = path.split("/")[-2]
            self._api_wechat_native_login_scan(login_id)
            return
        elif path == "/api/wechat-native/tasks":
            self._api_wechat_native_tasks_list()
            return
        elif path.startswith("/api/wechat-native/artifacts/"):
            artifact_id = unquote(path.split("/api/wechat-native/artifacts/", 1)[1])
            self._api_wechat_native_artifact(artifact_id)
            return
        elif path.startswith("/api/wechat-native/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            self._api_wechat_native_task_status(task_id)
            return
        elif path == "/api/wechat-collect/tasks":
            self._api_wechat_collect_tasks_list()
            return
        elif path.startswith("/api/wechat-collect/tasks/"):
            task_id = path.split("/")[-1]
            self._api_wechat_collect_task_status(task_id)
            return
        elif path.startswith("/api/wechat/tasks/"):
            task_id = path.split("/")[-1]
            self._api_wechat_task_status(task_id)
        elif path == "/api/email/auth/gmail/status":
            self._api_email_gmail_oauth_status()
        elif path == "/api/email/accounts":
            self._api_email_accounts()
        elif path == "/api/email/analysis-rules":
            self._api_email_analysis_rules()
        elif path == "/api/email/analysis-rules/export":
            self._api_email_analysis_rules_export()
        elif path == "/api/email/messages":
            self._api_email_messages()
        elif path.startswith("/api/email/messages/"):
            self._api_email_message_get(path)
        elif path == "/api/content/targets":
            self._api_content_targets()
        elif path == "/api/content/variants":
            self._api_content_variants()
        elif path.startswith("/api/content/variants/"):
            variant_id = path.rsplit("/", 1)[-1]
            self._api_content_variant_get(variant_id)
        elif path == "/api/rss/feeds":
            self._api_rss_feeds()
        elif path == "/api/rss/catalog":
            self._api_rss_catalog()
        elif path == "/api/rss/catalog/sources":
            self._api_rss_catalog_sources()
        elif path == "/api/rss/items":
            self._api_rss_items()
        elif path == "/api/rss/opml/export":
            self._api_rss_opml_export()
        elif path == "/api/article/list":
            self._api_article_list()
        elif path == "/api/article/file":
            self._api_article_file()
        elif path.startswith("/api/article/") and self.command == "GET":
            task_id = path.split("/")[-1]
            self._api_article_get(task_id)
        elif path == "/api/video-generate/templates":
            self._api_video_gen_templates()
        elif path == "/api/video-generate/file":
            self._api_video_gen_file()
        elif path == "/api/video-generate/list":
            self._api_video_gen_list()
        elif path.startswith("/api/video-generate/") and self.command == "GET":
            task_id = path.split("/")[-1]
            self._api_video_gen_get(task_id)
        elif path == "/api/token":
            self._api_token_info()
        elif path == "/api/cache":
            self._api_cache_list()
        elif path == "/api/quota":
            self._api_quota()
        elif path == "/api/api-keys":
            self._api_api_keys_list()
        elif path == "/api/proxy-pools":
            self._api_proxy_pools_list()
        elif path == "/api/dynamic-providers":
            self._api_dynamic_providers_list()
        elif path == "/api/provider-scheduler/status":
            self._api_provider_scheduler_status()
        elif path == "/api/provider-scheduler/logs":
            self._api_provider_scheduler_logs()
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/candidates/preview"):
            pid = path.split("/")[-3]
            if pid.isdigit():
                self._api_dynamic_provider_candidates_preview(int(pid))
            else:
                self._send_json({"error": "无效的提供方 ID"}, 400)
        elif path == "/api/routing-preview":
            self._api_routing_preview()
        elif path == "/api/clips":
            self._api_clip_list()
        elif path.startswith("/api/clips/") and self.command == "GET":
            task_id = path.split("/")[-1]
            if task_id.isdigit():
                self._api_clip_get(int(task_id))
            else:
                self._send_json({"error": "无效的任务 ID"}, 400)
        elif path.startswith("/api/api-keys/"):
            parts = path.split("/")
            action = parts[-1]
            if action == "add":
                self._api_api_key_add(self._read_json() or {})
            elif action.isdigit():
                self._api_api_key_update(int(action), self._read_json() or {})
        elif path.startswith("/api/download-tasks/"):
            task_id = path.split("/")[-1]
            self._api_download_task_status(task_id)
        elif path.startswith("/api/accounts/") and "/videos" in path:
            acc_id = path.split("/")[3]
            self._api_account_videos(acc_id)
        elif path == "/api/batch/tasks":
            self._api_batch_tasks_list()
        elif path.startswith("/api/batch/tasks/") and path.endswith("/restart"):
            self._send_json({"error": "请使用 POST /api/batch/tasks/:id/restart"}, 405)
        elif path.startswith("/api/batch/tasks/") and path.endswith("/cancel"):
            self._send_json({"error": "请使用 POST /api/batch/tasks/:id/cancel"}, 405)
        elif path.startswith("/api/batch/tasks/"):
            task_id = path.split("/")[-1]
            self._api_batch_task_status(task_id)
        # ── Go 代理转发路由 (GET) ────────────────────────────────
        elif path == "/api/proxy/status":
            self._api_proxy_status()
        elif path == "/api/proxy/config":
            self._api_proxy_config_get()
        elif path == "/api/res-events":
            self._api_res_events_stream()
        elif path == "/api/res/preview":
            self._api_res_preview()
        elif path == "/api/res/preview/encrypted":
            self._api_res_preview_encrypted()
        else:
            super().do_GET()

    def do_HEAD(self):
        path = self._path_only()
        if not path.startswith("/api/"):
            self._strip_conditional_headers_for_static()
            super().do_HEAD()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
            return
        self.send_error(404, "未知 API")

    def do_POST(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
            return
        path = self._path_only()
        if self._reject_disallowed_write_origin():
            return
        if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
            if path == "/api/batch/upload":
                self._handle_multipart_upload()
                return
            self._send_json({"error": "未知 multipart API"}, 404)
            return
        if self._reject_invalid_json_content_type(path):
            return
        if path in ("/api/rss/opml/import", "/api/rss/catalog/sources", "/api/rss/catalog/sources/file"):
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                content_length = 0
            if content_length > _MAX_RSS_OPML_BODY_BYTES:
                self._send_json({"error": "OPML 内容过大"}, 413)
                return
        body = self._read_json()
        if body is None:
            self._send_json({"error": "invalid json body"}, 400)
            return
        if path == "/api/scheduler/start":
            self._api_scheduler_start(body)
        elif path == "/api/scheduler/stop":
            self._api_scheduler_stop()
        elif path == "/api/scheduler/reload":
            self._api_scheduler_reload()
        elif path == "/api/provider-scheduler/start":
            self._api_provider_scheduler_start()
        elif path == "/api/provider-scheduler/stop":
            self._api_provider_scheduler_stop()
        elif path == "/api/provider-scheduler/reload":
            self._api_provider_scheduler_reload()
        elif path == "/api/provider-scheduler/run-once":
            self._api_provider_scheduler_run_once()
        elif path == "/api/accounts":
            self._api_account_add(body)
        elif path == "/api/accounts/scan":
            self._api_account_scan(body)
        elif path.startswith("/api/accounts/") and path.endswith("/update"):
            acc_id = path.split("/")[-2]
            self._api_account_update(acc_id, body)
        elif path.startswith("/api/accounts/") and "/videos/batch-download" in path:
            acc_id = path.split("/")[3]
            self._api_account_videos_batch_download(acc_id, body)
        elif path == "/api/config":
            self._api_config_save(body)
        elif path == "/api/voice/env/check":
            self._api_voice_env_check(body)
        elif path == "/api/voice/smoke-test":
            self._api_voice_smoke_test(body)
        elif path == "/api/voice/synthesis/tasks":
            self._api_voice_synthesis_task_create(body)
        elif path.startswith("/api/voice/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_voice_task_cancel(task_id)
        elif path == "/api/wechat/draft":
            self._api_wechat_draft(body)
        elif path == "/api/wechat/publish":
            self._api_wechat_publish(body)
        elif path == "/api/wechat-collect/auth/check":
            self._api_wechat_collect_auth_check(body)
        elif path == "/api/wechat-collect/preview":
            self._api_wechat_collect_preview(body)
        elif path == "/api/wechat-collect/start":
            self._api_wechat_collect_start(body)
        elif path.startswith("/api/wechat-collect/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_wechat_collect_cancel(task_id)
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
        elif path == "/api/wechat-native/articles/cache":
            self._api_wechat_native_cached_articles(body)
        elif path == "/api/wechat-native/tasks/start":
            self._api_wechat_native_start(body)
        elif path.startswith("/api/wechat-native/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_wechat_native_cancel(task_id)
        elif path == "/api/weread-exporter/tasks/start":
            self._api_weread_exporter_start(body)
        elif path == "/api/weread-exporter/chrome/start":
            self._api_weread_exporter_chrome_start(body)
        elif path.startswith("/api/weread-exporter/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_weread_exporter_cancel(task_id)
        elif path == "/api/email/auth/gmail/start":
            self._api_email_gmail_oauth_start(body)
        elif path == "/api/email/gmail/send":
            self._api_email_gmail_send(body)
        elif path == "/api/email/accounts":
            self._api_email_account_create(body)
        elif path == "/api/email/analysis-rules/validate":
            self._api_email_analysis_rules_validate(body)
        elif path == "/api/email/analysis-rules/import":
            self._api_email_analysis_rules_import(body)
        elif path == "/api/email/analysis-rules/restore":
            self._api_email_analysis_rules_restore(body)
        elif path == "/api/email/analysis-rules":
            self._api_email_analysis_rules_save(body)
        elif path.startswith("/api/email/accounts/") and path.endswith("/update"):
            account_id = path.split("/")[-2]
            self._api_email_account_update(account_id, body)
        elif path.startswith("/api/email/accounts/") and path.endswith("/delete"):
            account_id = path.split("/")[-2]
            self._api_email_account_delete(account_id)
        elif path.startswith("/api/email/accounts/") and path.endswith("/test"):
            account_id = path.split("/")[-2]
            self._api_email_account_test(account_id)
        elif path.startswith("/api/email/accounts/") and path.endswith("/sync"):
            account_id = path.split("/")[-2]
            self._api_email_account_sync(account_id, body)
        elif path.startswith("/api/email/accounts/") and path.endswith("/pause"):
            account_id = path.split("/")[-2]
            self._api_email_account_status(account_id, "paused")
        elif path.startswith("/api/email/accounts/") and path.endswith("/resume"):
            account_id = path.split("/")[-2]
            self._api_email_account_status(account_id, "active")
        elif path == "/api/email/messages/batch-generate":
            self._api_email_messages_batch_generate(body)
        elif path.startswith("/api/email/messages/") and path.endswith("/clean"):
            message_id = path.split("/")[-2]
            self._api_email_message_clean(message_id)
        elif path.startswith("/api/email/messages/") and path.endswith("/classify"):
            message_id = path.split("/")[-2]
            self._api_email_message_classify(message_id)
        elif path.startswith("/api/email/messages/") and path.endswith("/reprocess"):
            message_id = path.split("/")[-2]
            self._api_email_message_reprocess(message_id, body)
        elif path.startswith("/api/email/messages/") and path.endswith("/ignore"):
            message_id = path.split("/")[-2]
            self._api_email_message_ignore(message_id)
        elif path.startswith("/api/email/messages/") and path.endswith("/generate"):
            message_id = path.split("/")[-2]
            self._api_email_message_generate(message_id, body)
        elif path.startswith("/api/email/messages/") and path.endswith("/variants"):
            message_id = path.split("/")[-2]
            self._api_email_message_variants(message_id, body)
        elif path.startswith("/api/content/targets/") and path.endswith("/update"):
            target_id = path.split("/")[-2]
            self._api_content_target_update(target_id, body)
        elif path.startswith("/api/content/variants/") and path.endswith("/update"):
            variant_id = path.split("/")[-2]
            self._api_content_variant_update(variant_id, body)
        elif path.startswith("/api/content/variants/") and path.endswith("/export"):
            variant_id = path.split("/")[-2]
            self._api_content_variant_export(variant_id, body)
        elif path.startswith("/api/content/variants/") and path.endswith("/wechat-draft"):
            variant_id = path.split("/")[-2]
            self._api_content_variant_wechat_draft(variant_id)
        elif path == "/api/rss/feeds":
            self._api_rss_feed_save(body)
        elif path.startswith("/api/rss/feeds/") and path.endswith("/refresh"):
            feed_id = path.split("/")[-2]
            self._api_rss_feed_refresh(feed_id, body)
        elif path == "/api/rss/opml/import":
            self._api_rss_opml_import(body)
        elif path == "/api/rss/catalog/sync":
            self._api_rss_catalog_sync()
        elif path == "/api/rss/catalog/import":
            self._api_rss_catalog_import(body)
        elif path == "/api/rss/catalog/sources":
            self._api_rss_catalog_source_add(body)
        elif path == "/api/rss/catalog/sources/file":
            self._api_rss_catalog_source_add_file()
        elif path.startswith("/api/rss/catalog/sources/") and path.endswith("/sync"):
            raw = path.split("/")[-2]
            source_key = unquote(raw)
            self._api_rss_catalog_source_sync(source_key)
        elif path.startswith("/api/rss/items/") and path.endswith("/generate"):
            item_id = path.split("/")[-2]
            self._api_rss_item_generate(item_id, body)
        elif path == "/api/article/generate":
            self._api_article_generate(body)
        elif path.startswith("/api/article/") and path.endswith("/rerun"):
            task_id = path.split("/")[-2]
            self._api_article_rerun(task_id)
        elif path.startswith("/api/article/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_article_cancel(task_id)
        elif path == "/api/video-generate":
            self._api_video_gen_create(body)
        elif path.startswith("/api/video-generate/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_video_gen_cancel(task_id)
        elif path == "/api/api-keys":
            self._api_api_key_add(body)
        elif path.startswith("/api/api-keys/") and path.endswith("/update"):
            key_id_str = path.split("/")[-2]
            if key_id_str.isdigit():
                self._api_api_key_update(int(key_id_str), body)
        elif path.startswith("/api/api-keys/"):
            pass
        elif path == "/api/cache/refresh":
            self._api_cache_refresh(body)
        elif path == "/api/cache/clear":
            self._api_cache_clear()
        elif path == "/api/proxy-pools":
            self._api_proxy_pool_add(body)
        elif path == "/api/dynamic-providers":
            self._api_dynamic_provider_add(body)
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/update"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_update(int(pid), body)
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/health-check"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_health_check(int(pid))
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/refresh"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_dynamic_provider_refresh(int(pid))
        elif path.startswith("/api/dynamic-providers/") and path.endswith("/cooldown/clear"):
            pid = path.split("/")[-3]
            if pid.isdigit():
                self._api_dynamic_provider_cooldown_clear(int(pid))
        elif path == "/api/system/shutdown":
            self._api_system_shutdown()
        elif path.startswith("/api/proxy-pools/") and path.endswith("/update"):
            pid = path.split("/")[-2]
            if pid.isdigit():
                self._api_proxy_pool_update(int(pid), body)
        elif path == "/api/batch/upload":
            self._handle_multipart_upload()
        elif path == "/api/batch/start":
            self._api_batch_download_start(body)
        elif path.startswith("/api/batch/tasks/") and path.endswith("/restart"):
            task_id = path.split("/")[-2]
            self._api_batch_task_restart(task_id)
        elif path.startswith("/api/batch/tasks/") and path.endswith("/cancel"):
            task_id = path.split("/")[-2]
            self._api_batch_task_cancel(task_id)
        elif path == "/api/clips":
            self._api_clip_create(body)
        elif path == "/api/videos/retry":
            self._api_videos_retry(body)
        # ── Go 代理转发路由 (POST) ────────────────────────────────
        elif path == "/api/proxy/enable":
            self._api_proxy_enable()
        elif path == "/api/proxy/disable":
            self._api_proxy_disable()
        elif path == "/api/proxy/config":
            self._api_proxy_config_update(body)
        elif path == "/api/proxy/download":
            self._api_proxy_download(body)
        elif path == "/api/proxy/system-proxy":
            self._api_proxy_system_proxy(body)
        elif path == "/api/proxy/cert/install":
            self._api_proxy_cert_install()
        # ── 资源嗅探 API ──────────────────────────────────────
        elif path == "/api/res/clear":
            self._api_res_clear()
        elif path == "/api/res/delete":
            self._api_res_delete(body)
        elif path == "/api/res/set-type":
            self._api_res_set_type(body)
        elif path == "/api/res/download":
            self._api_res_download(body)
        elif path == "/api/res/cancel":
            self._api_res_cancel(body)
        elif path == "/api/res/decode":
            self._api_res_decode(body)
        elif path == "/api/res/export":
            self._api_res_export(body)
        elif path == "/api/res/open-folder":
            self._api_res_open_folder(body)
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_DELETE(self):
        if self.command == "OPTIONS":
            self.send_response(200)
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        if not self._require_auth():
            return
        if not self._check_rate_limit():
            return
        path = self._path_only()
        if path.startswith("/api/accounts/"):
            acc_id = path.split("/")[-1]
            self._api_account_delete(acc_id)
        elif path.startswith("/api/email/accounts/"):
            account_id = path.split("/")[-1]
            self._api_email_account_delete(account_id)
        elif path.startswith("/api/rss/feeds/"):
            feed_id = path.split("/")[-1]
            self._api_rss_feed_delete(feed_id)
        elif path.startswith("/api/rss/catalog/sources/"):
            raw = path.split("/")[-1]
            source_key = unquote(raw)
            self._api_rss_catalog_source_delete(source_key)
        elif path.startswith("/api/api-keys/"):
            key_id = path.split("/")[-1]
            if key_id.isdigit():
                self._api_api_key_delete(int(key_id))
        elif path.startswith("/api/cache/"):
            handle = path.split("/api/cache/", 1)[-1]
            self._api_cache_delete(handle)
        elif path.startswith("/api/proxy-pools/"):
            pid = path.split("/")[-1]
            if pid.isdigit():
                self._api_proxy_pool_delete(int(pid))
        elif path.startswith("/api/dynamic-providers/"):
            pid = path.split("/")[-1]
            if pid.isdigit():
                self._api_dynamic_provider_delete(int(pid))
        else:
            self._send_json({"error": "未知 API"}, 404)

    def do_OPTIONS(self):
        if self.headers.get("Origin") and not self._allowed_origin():
            self._send_json({"error": "不允许的请求来源"}, 403)
            return
        self.send_response(200)
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ── REST API ────────────────────────────────────────────

    def _api_video_stream(self):
        """GET /api/video-stream?path=<filepath> — 流式播放本地视频文件（绕过浏览器 file:// 限制）

        无需认证：服务端已对路径做安全检查（禁止 .. 遍历，只能访问 videos/ 目录下文件），
        路径含不可猜测的 clip ID，且视频文件本身非敏感数据。
        """
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        raw_path = params.get("path", [None])[0]
        if not raw_path:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"path parameter is required")
            return

        # 安全检查：禁止路径遍历
        if ".." in raw_path or raw_path.startswith("/"):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden path")
            return

        # 将相对路径拼到项目根目录下的 videos/
        # raw_path 可能是 "videos/clips/..." 或 "clips/..."，统一处理
        if raw_path.startswith("videos" + os.sep) or raw_path.startswith("videos/"):
            # 前端已传完整相对路径（含 videos/ 前缀），直接用
            safe_path = os.path.normpath(os.path.join(_PROJECT_ROOT, raw_path))
        else:
            # 旧格式或仅有 clips/... 部分，补上 videos/ 前缀
            safe_path = os.path.normpath(os.path.join(_PROJECT_ROOT, "videos", raw_path))
        if not safe_path.startswith(os.path.normpath(_PROJECT_ROOT)):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden path")
            return

        if not os.path.isfile(safe_path):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f"file not found: {safe_path}".encode())
            return

        import mimetypes
        mime, _ = mimetypes.guess_type(safe_path)
        if not mime or mime == "application/octet-stream":
            ext = os.path.splitext(safe_path)[1].lower()
            mime_map = {
                ".mp4": "video/mp4",
                ".avi": "video/x-msvideo",
                ".flv": "video/x-flv",
                ".mpeg": "video/mpeg",
                ".mkv": "video/x-matroska",
                ".webm": "video/webm",
                ".mov": "video/quicktime",
            }
            mime = mime_map.get(ext, "video/mp4")

        file_size = os.path.getsize(safe_path)
        range_header = self.headers.get("Range")

        if range_header:
            # 支持 Range 请求（拖动播放）
            import re
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else file_size - 1
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(safe_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk_size = min(1024 * 1024, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return

        # 全文件下载/播放
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(safe_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _api_status(self):
        is_running = _scheduler.is_running()
        next_runs = _scheduler.get_next_run_times() if is_running else []
        self._send_json({"running": is_running, "next_runs": next_runs})

    def _api_system_shutdown(self):
        """POST /api/system/shutdown — 安全关闭当前 Web UI 进程（完全开放模式下任意客户端可调用）"""
        self._send_json({"ok": True, "message": "server shutting down"})
        threading.Thread(target=self.server.shutdown, daemon=True, name="monitor-server-shutdown").start()

    def _api_accounts(self):
        accounts = _db.list_accounts()
        accounts = [_mask_account_for_response(a) for a in accounts]
        result = [{
            "id": a["id"],
            "name": a["name"],
            "channel_url": a["channel_url"],
            "api_key_env": a["api_key_env"],
            "api_key_id": a.get("api_key_id"),
            "fetch_mode": a["fetch_mode"],
            "fetch_limit": a["fetch_limit"],
            "scan_interval": a["scan_interval"],
            "enabled": bool(a["enabled"]),
            "notify_enabled": bool(a["notify_enabled"]),
            "notify_platform": a["notify_platform"],
            "webhook_url": a["webhook_url"] or "",
            "telegram_bot_token": a.get("telegram_bot_token") or "",
            "dingtalk_sign_secret": a.get("dingtalk_sign_secret") or "",
            "feishu_message_mode": a.get("feishu_message_mode", "card_json"),
            "feishu_template_id": a.get("feishu_template_id") or "",
            "feishu_scan_template_id": a.get("feishu_scan_template_id") or "",
            "proxy_pool_id": a.get("proxy_pool_id"),
            "proxy_enabled": bool(a.get("proxy_enabled", 0)),
            "download_proxy_mode": a.get("download_proxy_mode", "auto"),
        } for a in accounts]
        self._send_json(result)

    def _api_events(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        limit = int(params.get("limit", ["20"])[0])
        events = _db.get_recent_events(limit)
        result = [{
            "id": e["id"],
            "account_name": e["account_name"],
            "channel_url": e["channel_url"],
            "status": e["status"],
            "total_videos": e["total_videos"],
            "new_videos": e["new_videos"],
            "error_message": e["error_message"] or "",
            "duration_ms": e["duration_ms"],
            "scan_started_at": e["scan_started_at"],
            "scan_ended_at": e["scan_ended_at"] or "",
        } for e in events]
        self._send_json(result)

    def _api_stats(self):
        rows = _db.get_account_stats()
        result = [{
            "id": r["id"],
            "name": r["name"],
            "channel_url": r["channel_url"],
            "total_scans": r["total_scans"],
            "total_new_videos": r["total_new_videos"],
            "last_scan_at": r["last_scan_at"] or "",
            "is_running": bool(r["is_running"]),
        } for r in rows]
        self._send_json(result)

    def _api_config(self):
        self._send_json(_mask_config_for_response(_db.load_config()))

    def _api_voice_providers(self):
        params = parse_qs(urlparse(self.path).query)
        capability = (params.get("capability") or [""])[0] or None
        flow = (params.get("flow") or [""])[0] or None
        self._send_json(
            voice_env.voice_provider_payload(
                _db.load_config(),
                capability=capability,
                flow=flow,
            )
        )

    def _api_voice_env(self):
        self._send_json(voice_env.check_voice_environment(_db.load_config(), include_remote=False))

    def _api_voice_env_check(self, body: dict):
        body = body or {}
        self._send_json(
            voice_env.check_voice_environment(
                _db.load_config(),
                include_remote=voice_env.coerce_bool(body.get("include_remote")),
                timeout_seconds=body.get("timeout_seconds", 3),
            )
        )

    def _api_voice_smoke_test(self, body: dict):
        cfg = _db.load_config()
        try:
            result = voice_env.run_voice_smoke_test(body or {}, cfg)
        except Exception as exc:
            result = {"ok": False, "error": voice_env.sanitize_error_text(str(exc), cfg)}
        if not result.get("ok") and result.get("error"):
            result = dict(result)
            result["error"] = voice_env.sanitize_error_text(str(result.get("error") or ""), cfg)
        self._send_json(result, 200 if result.get("ok") else 400)

    def _api_voice_synthesis_task_create(self, body: dict):
        cfg = _db.load_config()
        try:
            task_id = _voice_task_mgr.create_synthesis_task(body or {}, cfg)
        except Exception as exc:
            self._send_json({"error": voice_env.sanitize_error_text(str(exc), cfg)}, 400)
            return
        _voice_task_mgr.start_background(task_id, cfg)
        self._send_json({"ok": True, "task_id": task_id}, 202)

    def _api_voice_tasks_list(self):
        status, limit, offset = self._ai_task_query_params()
        params = parse_qs(urlparse(self.path).query)
        kind = (params.get("kind") or [""])[0] or None
        tasks, total = _db.list_voice_tasks(kind=kind, status=status, limit=limit, offset=offset)
        self._send_json({"tasks": tasks, "total": total, "limit": limit, "offset": offset})

    def _api_voice_task_get(self, task_id: str):
        task = _db.get_voice_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(task)

    def _api_voice_task_cancel(self, task_id: str):
        task = _db.request_cancel_voice_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json({"ok": True, "task": task})

    def _api_voice_file(self):
        params = parse_qs(urlparse(self.path).query)
        raw_path = (params.get("path") or [""])[0]
        if not raw_path:
            self._send_json({"error": "path 必填"}, 400)
            return
        cfg = _db.load_config()
        root = Path(cfg.get("voice_output_dir") or "data/voice").expanduser().resolve()
        requested = Path(raw_path).expanduser()
        if not requested.is_absolute():
            requested = (Path(_PROJECT_ROOT) / requested).resolve()
        else:
            requested = requested.resolve()
        try:
            requested.relative_to(root)
        except ValueError:
            self._send_json({"error": "无效的输出路径"}, 400)
            return
        if not requested.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        mime, _ = mimetypes.guess_type(str(requested))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(requested.stat().st_size))
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        with requested.open("rb") as file_obj:
            shutil.copyfileobj(file_obj, self.wfile)

    def _api_wechat_config(self):
        """GET /api/wechat/config — return WeChat publish config without secret."""
        cfg = _db.load_config()
        safe = {
            "wechat_app_id": cfg.get("wechat_app_id") or "",
            "wechat_default_author": cfg.get("wechat_default_author") or "",
            "wechat_default_theme": cfg.get("wechat_default_theme") or "default",
            "wechat_default_color": cfg.get("wechat_default_color") or "blue",
            "wechat_markdown_renderer": cfg.get("wechat_markdown_renderer") or "auto",
            "wechat_baoyu_markdown_to_html_script": cfg.get("wechat_baoyu_markdown_to_html_script") or "",
            "wechat_publish_monthly_limit": self._wechat_publish_monthly_limit(cfg),
            "publish_quota": self._wechat_publish_quota_status(cfg),
            "wechat_need_open_comment": bool(cfg.get("wechat_need_open_comment", True)),
            "wechat_only_fans_can_comment": bool(cfg.get("wechat_only_fans_can_comment", False)),
            "configured": bool(cfg.get("wechat_app_id") and cfg.get("wechat_app_secret")),
        }
        self._send_json(safe)

    @staticmethod
    def _wechat_publish_monthly_limit(cfg: dict) -> int:
        try:
            limit = int((cfg or {}).get("wechat_publish_monthly_limit", 4))
        except (TypeError, ValueError):
            limit = 4
        return max(0, min(limit, 999))

    @classmethod
    def _wechat_publish_quota_status(cls, cfg: dict) -> dict:
        usage = _db.get_wechat_publish_monthly_usage()
        limit = cls._wechat_publish_monthly_limit(cfg)
        try:
            used = int(usage.get("used") or 0)
        except (TypeError, ValueError):
            used = 0
        try:
            active = int(usage.get("active") or 0)
        except (TypeError, ValueError):
            active = 0

        unlimited = limit == 0
        remaining = None if unlimited else max(limit - used - active, 0)
        return {
            "month": usage.get("month") or _db.now_iso()[:7],
            "limit": limit,
            "used": used,
            "active": active,
            "remaining": remaining,
            "unlimited": unlimited,
            "exhausted": False if unlimited else remaining == 0,
        }

    def _api_wechat_collect_config(self):
        """GET /api/wechat-collect/config — return WeChat collection config safely."""
        cfg = _db.load_config()
        safe = {
            "wechat_exporter_base_url": cfg.get("wechat_exporter_base_url") or _wechat_collector.DEFAULT_EXPORTER_BASE_URL,
            "wechat_collection_output_dir": cfg.get("wechat_collection_output_dir") or "",
            "wechat_collection_default_format": cfg.get("wechat_collection_default_format") or "markdown",
            "wechat_collection_delay_seconds": cfg.get("wechat_collection_delay_seconds", 1.0),
            "wechat_collection_max_articles": cfg.get("wechat_collection_max_articles", 50),
            "configured": bool(cfg.get("wechat_exporter_auth_key")),
        }
        self._send_json(safe)

    @staticmethod
    def _wechat_collect_client(cfg: dict, body: dict | None = None) -> _wechat_collector.WechatExporterClient:
        body = body or {}
        auth_key = str(body.get("auth_key") or "").strip()
        if not auth_key or auth_key == _MASKED_SECRET_VALUE:
            auth_key = str(cfg.get("wechat_exporter_auth_key") or "").strip()
        base_url = str(body.get("base_url") or cfg.get("wechat_exporter_base_url") or "")
        return _wechat_collector.WechatExporterClient(
            base_url=base_url,
            auth_key=auth_key,
            timeout=30,
        )

    @staticmethod
    def _wechat_collect_article_preview(article: dict) -> dict:
        return {
            "title": article.get("title") or "",
            "author_name": article.get("author_name") or "",
            "link": article.get("link") or article.get("url") or "",
            "cover": article.get("cover") or article.get("cover_img") or "",
            "digest": article.get("digest") or "",
            "update_time": article.get("update_time") or article.get("create_time") or 0,
            "aid": article.get("aid") or "",
        }

    def _api_wechat_collect_auth_check(self, body: dict):
        cfg = _db.load_config()
        try:
            result = self._wechat_collect_client(cfg, body).verify_auth_key()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        self._send_json({"ok": True, "result": result})

    def _api_wechat_collect_preview(self, body: dict):
        cfg = _db.load_config()
        try:
            client = self._wechat_collect_client(cfg, body)
            account = {}
            fakeid = str((body or {}).get("fakeid") or "").strip()
            if not fakeid:
                account = client.account_by_article_url(str((body or {}).get("article_url") or ""))
                fakeid = str(account.get("fakeid") or "").strip()
            else:
                account = {"fakeid": fakeid, "nickname": str((body or {}).get("account_name") or fakeid)}
            limit = max(1, min(int((body or {}).get("limit", 10) or 10), 50))
            articles = client.list_articles(
                fakeid,
                keyword=str((body or {}).get("keyword") or "").strip(),
                max_articles=limit,
                page_size=min(limit, 20),
            )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return
        self._send_json({
            "ok": True,
            "account": {
                "fakeid": account.get("fakeid") or fakeid,
                "nickname": account.get("nickname") or account.get("alias") or "",
                "alias": account.get("alias") or "",
                "round_head_img": account.get("round_head_img") or "",
                "signature": account.get("signature") or "",
            },
            "articles": [self._wechat_collect_article_preview(item) for item in articles],
            "total": len(articles),
        })

    def _api_wechat_collect_start(self, body: dict):
        body = body or {}
        if not body.get("urls") and not body.get("fakeid") and not body.get("article_url"):
            self._send_json({"error": "article_url、fakeid 或 urls 至少提供一个"}, 400)
            return

        cfg = _db.load_config()
        data_dir = str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))
        configured_root = str(
            cfg.get("wechat_collection_output_dir")
            or _wechat_collector.default_collection_output_dir(data_dir)
        )
        try:
            output_dir = _wechat_collector.resolve_collection_output_dir(
                body.get("output_dir") or body.get("output_path") or "",
                configured_root,
            )
            client = self._wechat_collect_client(cfg, body)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        payload = dict(body)
        payload.pop("auth_key", None)
        payload.setdefault("format", cfg.get("wechat_collection_default_format") or "markdown")
        payload.setdefault("delay_seconds", cfg.get("wechat_collection_delay_seconds", 1.0))
        payload.setdefault("max_articles", cfg.get("wechat_collection_max_articles", 50))

        task_id = _wechat_collect_mgr.create_task(payload, output_dir)

        def _task():
            try:
                _wechat_collector.run_collection(
                    task_id=task_id,
                    task_manager=_wechat_collect_mgr,
                    client=client,
                    output_dir=output_dir,
                    payload=payload,
                )
            except Exception as exc:
                _wechat_collect_mgr.finish(task_id, error=str(exc))

        threading.Thread(target=_task, name=f"wechat-collect-{task_id}", daemon=True).start()
        self._send_json({"ok": True, "task_id": task_id, "status": "running"}, 202)

    def _api_wechat_collect_tasks_list(self):
        self._send_json({"tasks": _wechat_collect_mgr.list_tasks()})

    def _api_wechat_collect_task_status(self, task_id: str):
        task = _wechat_collect_mgr.get_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(task)

    def _api_wechat_collect_cancel(self, task_id: str):
        if not _wechat_collect_mgr.request_cancel(task_id):
            self._send_json({"error": "任务不存在或不可取消"}, 404)
            return
        self._send_json({"ok": True, "task_id": task_id, "status": "cancelling"})

    def _weread_data_dir(self) -> str:
        return str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))

    def _api_weread_exporter_config(self):
        self._send_json(_weread_export_service.config(data_dir=self._weread_data_dir()))

    def _api_weread_exporter_start(self, body: dict):
        body = body or {}
        try:
            task_id = _weread_export_service.create_task(body, data_dir=self._weread_data_dir())
            _weread_export_service.start_background(task_id)
            self._send_json({"ok": True, "task_id": task_id, "status": "pending"}, 202)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)

    def _api_weread_exporter_chrome_start(self, body: dict):
        body = body or {}
        try:
            result = _weread_export_service.start_chrome_cdp(
                data_dir=self._weread_data_dir(),
                endpoint=str(body.get("chrome_cdp_endpoint") or "").strip() or None,
                profile_dir=str(body.get("chrome_cdp_profile_dir") or "").strip() or None,
                initial_url=str(body.get("initial_url") or "https://weread.qq.com/web/shelf"),
            )
            self._send_json(result, 200 if result.get("available") else 202)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)

    def _api_weread_exporter_tasks_list(self):
        self._send_json({"tasks": _weread_export_service.list_tasks()})

    def _api_weread_exporter_task_status(self, task_id: str):
        task = _weread_export_service.get_task(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return
        self._send_json(task)

    def _api_weread_exporter_cancel(self, task_id: str):
        if not _weread_export_service.request_cancel(task_id):
            self._send_json({"error": "task not running"}, 409)
            return
        self._send_json({"ok": True})

    def _api_weread_exporter_artifact(self, artifact_id: str):
        try:
            resolved = Path(_weread_export_service.resolve_artifact_path(artifact_id)).expanduser().resolve()
            allowed_root = Path(default_output_root(self._weread_data_dir())).expanduser().resolve()
            resolved.relative_to(allowed_root)
        except ValueError:
            self._send_json({"error": "无效的微信读书导出结果路径"}, 400)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        if not resolved.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        ctype = mimetypes.guess_type(str(resolved))[0] or {
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".txt": "text/plain",
            ".json": "application/json",
        }.get(resolved.suffix.lower(), "application/octet-stream")
        if ctype.startswith("text/") and "charset=" not in ctype:
            ctype = f"{ctype}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(resolved.stat().st_size))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(resolved.name, safe='')}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        with resolved.open("rb") as file_obj:
            self.wfile.write(file_obj.read())

    def _api_wechat_native_config(self):
        """GET /api/wechat-native/config — return native collection defaults safely."""
        cfg = _db.load_config()
        self._send_json({
            "wechat_collection_output_dir": cfg.get("wechat_collection_output_dir") or "",
            "wechat_collection_default_format": cfg.get("wechat_collection_default_format") or "markdown",
            "wechat_collection_delay_seconds": cfg.get("wechat_collection_delay_seconds", 1.0),
            "wechat_collection_max_articles": cfg.get("wechat_collection_max_articles", 50),
        })

    def _api_wechat_native_sessions(self):
        self._send_json({"sessions": _wechat_native_session_store.list_public_sessions()})

    def _send_wechat_native_error(self, exc: Exception, default_status: int = 400):
        session_expired = isinstance(exc, WechatUpstreamError) and exc.session_expired
        if isinstance(exc, WechatSessionError) or session_expired:
            status = 401
        elif isinstance(exc, WechatNativeError):
            status = default_status
        else:
            status = 500 if default_status >= 500 else default_status
        payload = {"error": safe_error_message(exc)}
        if isinstance(exc, WechatUpstreamError):
            if exc.code is not None:
                payload["code"] = exc.code
            if exc.session_expired:
                payload["session_expired"] = True
        self._send_json(payload, status)

    def _wechat_native_proxy_context(self, body: dict | None = None) -> dict:
        body = body or {}
        context: dict[str, str] = {}
        fakeid = str(body.get("fakeid") or "").strip()
        account_name = str(body.get("account_name") or body.get("nickname") or "").strip()
        if fakeid:
            context["fakeid"] = fakeid
        if account_name:
            context["nickname"] = account_name
        return context

    def _wechat_native_provider(self, session_id: str, proxy_context: dict | None = None):
        proxy_plan = resolve_native_proxy_plan(self._wechat_native_proxy_context(proxy_context), cookies_present=True)
        return NativeMpProvider(
            session_id=session_id,
            store=_wechat_native_session_store,
            proxy_plan=proxy_plan,
        )

    def _api_wechat_native_login_start(self):
        try:
            self._send_json(_wechat_native_login_mgr.start_login())
        except Exception as exc:
            self._send_wechat_native_error(exc, 500)

    def _api_wechat_native_login_qrcode(self, login_id: str):
        try:
            payload = _wechat_native_login_mgr.get_qrcode(login_id)
            self.send_response(200)
            self.send_header("Content-Type", payload.content_type)
            self.send_header("Cache-Control", "no-store")
            origin = self._allowed_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.end_headers()
            self.wfile.write(payload.body)
        except Exception as exc:
            self._send_wechat_native_error(exc, 404)

    def _api_wechat_native_login_scan(self, login_id: str):
        try:
            self._send_json(_wechat_native_login_mgr.poll_scan(login_id))
        except Exception as exc:
            self._send_wechat_native_error(exc, 404)

    def _api_wechat_native_login_confirm(self, login_id: str):
        try:
            self._send_json(_wechat_native_login_mgr.confirm_login(login_id))
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _api_wechat_native_session_check(self, session_id: str):
        try:
            provider = self._wechat_native_provider(session_id)
            self._send_json(provider.check_session())
        except Exception as exc:
            self._send_wechat_native_error(exc, 401)

    def _api_wechat_native_session_logout(self, session_id: str):
        try:
            provider = self._wechat_native_provider(session_id)
            self._send_json(provider.logout())
        except Exception as exc:
            self._send_wechat_native_error(exc, 500)

    def _api_wechat_native_accounts_search(self, body: dict):
        body = body or {}
        session_id = str(body.get("session_id") or "")
        keyword = str(body.get("keyword") or "")
        try:
            begin = int(body.get("begin") or 0)
            size = int(body.get("size") or 5)
            provider = self._wechat_native_provider(session_id, body)
            self._send_json({"accounts": provider.search_accounts(keyword, begin=begin, size=size)})
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _api_wechat_native_account_by_url(self, body: dict):
        body = body or {}
        try:
            provider = self._wechat_native_provider(str(body.get("session_id") or ""), body)
            account = provider.account_by_article_url(str(body.get("article_url") or ""))
            self._send_json({"account": account})
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _wechat_native_cached_article_payload(
        self,
        fakeid: str,
        *,
        keyword: str = "",
        begin: int = 0,
        page_size: int = 20,
    ) -> dict:
        page = _wechat_collect_queries.list_article_page(
            fakeid,
            keyword=keyword,
            begin=begin,
            page_size=page_size,
        )
        return {
            "account": public_account_preview(_wechat_collect_queries.get_account(fakeid) or {"fakeid": fakeid}),
            "articles": [public_article_preview(article) for article in page["articles"]],
            "total": len(page["articles"]),
            "total_count": page["total_count"],
            "begin": page["begin"],
            "page_size": page["page_size"],
            "next_begin": page["next_begin"],
            "has_more": page["has_more"],
            "source": "local_cache",
        }

    def _wechat_native_store_account(self, fakeid: str, account: dict | None) -> dict:
        existing = _wechat_collect_queries.get_account(fakeid) or {}
        payload = public_account_preview(existing)
        incoming = public_account_preview(account or {})
        for key, value in incoming.items():
            if value is not None and value != "":
                payload[key] = value
        payload["fakeid"] = fakeid
        _wechat_collect_queries.upsert_account(payload)
        return public_account_preview(_wechat_collect_queries.get_account(fakeid) or payload)

    def _wechat_native_store_articles(self, fakeid: str, articles: list[dict]) -> None:
        for article in articles:
            link = str(article.get("link") or article.get("url") or "").strip()
            if not link:
                continue
            _wechat_collect_queries.upsert_article(fakeid, article)

    def _api_wechat_native_preview(self, body: dict):
        body = body or {}
        try:
            fakeid = str(body.get("fakeid") or "").strip()
            article_url = str(body.get("article_url") or "").strip()
            account = {}
            if not fakeid and article_url:
                if not is_valid_mp_article_url(article_url):
                    raise ValueError("文章链接不合法")
            provider = self._wechat_native_provider(str(body.get("session_id") or ""), body)
            begin = max(0, int(body.get("begin") or 0))
            page_size = max(1, min(int(body.get("page_size") or body.get("limit") or 20), 100))
            max_articles = max(1, min(int(body.get("max_articles") or 50), 1000))
            if not fakeid and article_url:
                account = provider.account_by_article_url(article_url)
                fakeid = str(account.get("fakeid") or "").strip()
                if not fakeid:
                    raise ValueError("无法解析公众号 fakeid，请手动搜索公众号")
            elif fakeid:
                body_account = body.get("account") if isinstance(body.get("account"), dict) else {}
                if str(body_account.get("fakeid") or "").strip() == fakeid:
                    account = dict(body_account)
                if body.get("account_name"):
                    account = {
                        **account,
                        "fakeid": fakeid,
                        "nickname": str(body.get("account_name") or ""),
                    }
            if not fakeid:
                raise ValueError("fakeid 不能为空")
            articles = provider.list_articles(
                fakeid,
                keyword=str(body.get("keyword") or ""),
                max_articles=max_articles,
                page_size=20,
                begin=0,
            )
            stored_account = self._wechat_native_store_account(fakeid, account or {"fakeid": fakeid})
            self._wechat_native_store_articles(fakeid, articles)
            payload = self._wechat_native_cached_article_payload(
                fakeid,
                keyword=str(body.get("keyword") or ""),
                begin=begin,
                page_size=page_size,
            )
            payload["account"] = stored_account
            payload["source"] = "upstream_refresh"
            self._send_json(payload)
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _api_wechat_native_cached_articles(self, body: dict):
        body = body or {}
        try:
            fakeid = str(body.get("fakeid") or "").strip()
            if not fakeid:
                raise ValueError("fakeid 不能为空")
            begin = max(0, int(body.get("begin") or 0))
            page_size = max(1, min(int(body.get("page_size") or body.get("limit") or 20), 100))
            self._send_json(self._wechat_native_cached_article_payload(
                fakeid,
                keyword=str(body.get("keyword") or ""),
                begin=begin,
                page_size=page_size,
            ))
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _api_wechat_native_start(self, body: dict):
        body = body or {}
        if not body.get("session_id"):
            self._send_json({"error": "session_id 不能为空"}, 400)
            return
        raw_urls = body.get("urls") or []
        if raw_urls:
            if not isinstance(raw_urls, list):
                self._send_json({"error": "urls 必须是文章链接数组"}, 400)
                return
            urls = []
            invalid_url = ""
            for item in raw_urls:
                if isinstance(item, dict):
                    raw_url = str(item.get("link") or item.get("url") or "").strip()
                    if not raw_url:
                        continue
                    url = normalize_mp_article_url(raw_url)
                    if not url:
                        invalid_url = raw_url
                        break
                    urls.append(public_article_preview({**item, "link": url, "url": url}))
                else:
                    raw_url = str(item).strip()
                    if not raw_url:
                        continue
                    url = normalize_mp_article_url(raw_url)
                    if not url:
                        invalid_url = raw_url
                        break
                    urls.append(url)
            if invalid_url:
                self._send_json({"error": "文章链接不合法"}, 400)
                return
            body = dict(body)
            body["urls"] = urls
        article_url = str(body.get("article_url") or "").strip()
        if article_url:
            normalized_article_url = normalize_mp_article_url(article_url)
            if not normalized_article_url:
                self._send_json({"error": "文章链接不合法"}, 400)
                return
            body = dict(body)
            body["article_url"] = normalized_article_url
        if not body.get("urls") and not body.get("fakeid") and not body.get("article_url"):
            self._send_json({"error": "article_url、fakeid 或 urls 至少提供一个"}, 400)
            return
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
            self._send_json({"ok": True, "task_id": task_id, "status": "pending"}, 202)
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)

    def _api_wechat_native_tasks_list(self):
        self._send_json({"tasks": _wechat_native_task_service.list_tasks()})

    def _api_wechat_native_task_status(self, task_id: str):
        task = _wechat_native_task_service.get_task(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return
        self._send_json(task)

    def _api_wechat_native_artifact(self, artifact_id: str):
        try:
            resolved = Path(_wechat_native_task_service.resolve_artifact_path(artifact_id)).expanduser().resolve()
            cfg = _db.load_config()
            data_dir = str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))
            configured_root = (
                cfg.get("wechat_collection_output_dir")
                or _wechat_collector.default_collection_output_dir(data_dir)
            )
            allowed_root = Path(configured_root).expanduser().resolve()
            resolved.relative_to(allowed_root)
        except ValueError:
            self._send_json({"error": "无效的公众号采集结果路径"}, 400)
            return
        except Exception as exc:
            self._send_wechat_native_error(exc, 400)
            return
        if not resolved.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        ctype = mimetypes.guess_type(str(resolved))[0]
        if not ctype:
            ctype = {
                ".md": "text/markdown",
                ".markdown": "text/markdown",
                ".txt": "text/plain",
                ".json": "application/json",
                ".html": "text/html",
            }.get(resolved.suffix.lower(), "application/octet-stream")
        if ctype.startswith("text/") and "charset=" not in ctype:
            ctype = f"{ctype}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(resolved.stat().st_size))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(resolved.name, safe='')}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        with resolved.open("rb") as f:
            self.wfile.write(f.read())

    def _api_wechat_native_cancel(self, task_id: str):
        if not _wechat_native_task_service.request_cancel(task_id):
            self._send_json({"error": "task not running"}, 409)
            return
        self._send_json({"ok": True})

    def _api_token_info(self):
        """GET /api/token — 历史兼容；Monitor API 已不做 token 鉴权。"""
        self._send_json({"token": "", "monitor_api_auth": "disabled"})

    def _api_config_save(self, body):
        old_cfg = _db.load_config()
        cfg = dict(old_cfg)
        for key in [
            "global_feishu_url", "global_dingtalk_url", "global_dingtalk_sign_secret", "global_wecom_url",
            "global_telegram_token", "global_telegram_chat_id",
            "quota_budget_per_day", "download_cookies_file", "download_output_path",
            "enable_aria2", "default_sub_langs", "default_api_key_id",
            "system_dynamic_proxy_enabled", "apply_dynamic_proxy_to_new_accounts",
            "apply_dynamic_proxy_to_existing_accounts", "manual_download_route_policy",
            "auto_download_route_policy", "allow_free_proxy",
            "allow_free_proxy_for_auto_download", "allow_free_proxy_with_cookies",
            "manual_direct_fallback", "auto_direct_fallback",
            "default_proxy_country_codes", "default_proxy_protocol_order",
            "default_session_mode", "default_sticky_minutes",
            "candidate_prefetch_count", "candidate_validate_count",
            "validated_pool_ttl_seconds", "provider_cooldown_seconds",
            "proxy_probe_timeout_seconds", "mask_proxy_in_logs",
            # 监控运维（长期运行）
            "channel_meta_max_age_days", "notify_on_scan_error",
            "scan_error_notify_cooldown_seconds", "quota_usage_timezone",
            "scan_jitter_seconds", "quota_alert_thresholds",
            "channel_meta_health_check_enabled", "channel_meta_health_check_interval_hours",
            "notify_on_channel_meta_mismatch",
            # AI 视频切片配置
            "llm_provider", "llm_api_key", "llm_model", "llm_base_url",
            "llm_min_score", "llm_category",
            "clip_embed_thumbnail", "clip_embed_subtitle", "clip_adapt_aspect_ratio",
            "clip_thumbnail_quality",
            "auto_clip_enabled", "auto_clip_notify_enabled",
            # AI 文章与视频生成配置
            "whisper_provider", "whisper_base_url", "whisper_api_key", "whisper_model", "whisper_compute_type",
            "whisper_device", "whisper_chunk_seconds", "whisper_language",
            "article_output_dir", "article_default_target_lang", "article_target_lang",
            "article_subtitle_languages", "article_subtitle_proxy", "article_subtitle_proxy_mode", "article_subtitle_proxy_pool_id", "article_tools_path", "article_author",
            "article_wechat_prompt_role", "article_wechat_prompt_reader_persona",
            "article_wechat_prompt_style", "article_wechat_prompt_max_chars",
            "article_llm_optimize_model", "article_llm_summary_model", "article_llm_translate_model",
            "article_optimize_model", "article_summary_model", "article_translate_model",
            "comfyui_url", "comfyui_api_key", "runninghub_url", "runninghub_api_key",
            "tts_provider", "local_tts_url", "video_gen_output_dir",
            "voice_provider", "voice_fallback_order", "voice_flow_defaults_json",
            "voice_output_dir", "voice_require_disclosure",
            "voice_allow_reference_clone", "voice_allow_prompt_transcript_clone",
            "voice_max_text_chars", "transcription_provider",
            "openai_speech_base_url", "openai_speech_api_key",
            "openai_speech_model", "openai_speech_voice",
            "azure_speech_region", "azure_speech_endpoint", "azure_speech_api_key",
            "azure_speech_voice", "azure_speech_output_format",
            "minimax_speech_base_url", "minimax_speech_api_key",
            "minimax_speech_model", "minimax_speech_voice",
            "voxcpm_base_url", "voxcpm_api_key", "voxcpm_model",
            "voxcpm_default_voice", "voxcpm_default_control_instruction",
            "vibevoice_tts_base_url", "vibevoice_tts_api_key",
            "vibevoice_tts_model", "vibevoice_tts_voice",
            "vibevoice_asr_base_url", "vibevoice_asr_api_key", "vibevoice_asr_model",
            "video_gen_default_template", "video_gen_default_scene_count",
            "default_template", "default_scene_count", "video_gen_prompt_prefix",
            "image_generation_provider", "image_generation_fallback_order",
            "image_generation_timeout_seconds",
            "minimax_api_key", "minimax_base_url", "minimax_image_model",
            "openai_api_key", "openai_base_url", "openai_image_model",
            "openai_image_size", "openai_image_quality",
            "gemini_api_key", "gemini_base_url", "gemini_image_model",
            "gmail_oauth_client_id", "gmail_oauth_client_secret", "gmail_oauth_redirect_uri",
            "gmail_oauth_scopes",
            "email_analysis_rules",
            # 微信公众号发布配置
            "wechat_app_id", "wechat_app_secret", "wechat_default_author",
            "wechat_default_theme", "wechat_default_color",
            "wechat_markdown_renderer", "wechat_baoyu_markdown_to_html_script",
            "wechat_need_open_comment", "wechat_only_fans_can_comment",
            # 微信公众号采集配置
            "wechat_exporter_base_url", "wechat_exporter_auth_key",
            "wechat_collection_output_dir", "wechat_collection_default_format",
            "wechat_collection_delay_seconds", "wechat_collection_max_articles",
            # 代理嗅探
            "proxy_sniffer_enabled", "proxy_sniffer_port",
        ]:
            if key in body:
                cfg[key] = body[key]
        cfg = _preserve_masked_config_values(cfg, old_cfg)
        ok_llm_secret, llm_secret_error = _validate_llm_endpoint_secret_reentry(body, cfg, old_cfg)
        if not ok_llm_secret:
            self._send_json({"error": llm_secret_error}, 400)
            return
        ok_voice_endpoint_url, voice_endpoint_url_error = _validate_voice_endpoint_urls_config(body, cfg)
        if not ok_voice_endpoint_url:
            self._send_json({"error": voice_endpoint_url_error}, 400)
            return
        ok_voice_secret, voice_secret_error = _validate_voice_endpoint_secret_reentry(body, cfg, old_cfg)
        if not ok_voice_secret:
            self._send_json({"error": voice_secret_error}, 400)
            return
        saved_email_analysis_version = None
        if "email_analysis_rules" in body:
            rule_validation = validate_email_analysis_rules(cfg.get("email_analysis_rules"))
            if not rule_validation["ok"]:
                self._send_json(
                    {
                        "error": "邮件分析规则校验失败",
                        "code": "email_analysis_rules_invalid",
                        "details": rule_validation["errors"],
                    },
                    400,
                )
                return
            cfg["email_analysis_rules"] = rule_validation["rules"]
        # 配额预警阈值：规范为升序唯一整数列表
        if "quota_alert_thresholds" in body and body["quota_alert_thresholds"] is not None:
            raw = body["quota_alert_thresholds"]
            if isinstance(raw, str):
                parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
                thr = []
                for p in parts:
                    try:
                        thr.append(int(p))
                    except ValueError:
                        pass
            elif isinstance(raw, list):
                thr = []
                for x in raw:
                    try:
                        thr.append(int(x))
                    except (TypeError, ValueError):
                        pass
            else:
                thr = []
            thr = sorted({t for t in thr if 1 <= t <= 100})
            cfg["quota_alert_thresholds"] = thr if thr else [80, 90, 100]
        default_key_id = cfg.get("default_api_key_id")
        if default_key_id:
            # default_api_key_id is encrypted at rest but remains an api_keys.id at runtime.
            if isinstance(default_key_id, str):
                default_key_id = _decrypt_config_value(default_key_id)
            try:
                default_key_id = int(default_key_id)
            except (ValueError, TypeError):
                self._send_json({"error": f"无效的 default_api_key_id: {default_key_id}"}, 400)
                return
            ak = _db.get_api_key(default_key_id)
            if not ak:
                self._send_json({"error": f"指定的默认 API Key (id={default_key_id}) 不存在"}, 400)
                return
        if "quota_usage_timezone" in body:
            import monitor.quota as _quota_m

            ok_tz, err_tz = _quota_m.validate_quota_usage_timezone(
                body.get("quota_usage_timezone")
            )
            if not ok_tz:
                self._send_json({"error": err_tz}, 400)
                return
        if "voice_flow_defaults_json" in body:
            ok_voice_defaults, voice_defaults_error = _validate_voice_flow_defaults_config(
                cfg.get("voice_flow_defaults_json")
            )
            if not ok_voice_defaults:
                self._send_json({"error": voice_defaults_error}, 400)
                return
        if any(
            key in body
            for key in (
                "wechat_markdown_renderer",
                "wechat_baoyu_markdown_to_html_script",
            )
        ):
            from config.validation import validate_wechat_renderer_config

            renderer_errors = validate_wechat_renderer_config(cfg)
            if renderer_errors:
                self._send_json({"error": renderer_errors[0], "details": renderer_errors}, 400)
                return
        try:
            _db.save_config(cfg)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        if "email_analysis_rules" in body:
            saved_email_analysis_version = _append_email_analysis_rules_history(
                cfg.get("email_analysis_rules") or {},
                note="Saved through global config API",
                source="config-api",
            )
        _scheduler.set_global_feishu_url(cfg.get("global_feishu_url") or None)
        _scheduler.set_global_dingtalk_url(cfg.get("global_dingtalk_url") or None)
        _scheduler.set_global_dingtalk_sign_secret(cfg.get("global_dingtalk_sign_secret") or None)
        _scheduler.set_global_wecom_url(cfg.get("global_wecom_url") or None)
        _scheduler.set_global_telegram_chat_id(cfg.get("global_telegram_chat_id") or None)
        _scheduler.set_global_telegram_token(cfg.get("global_telegram_token") or None)
        _scheduler._invalidate_config_cache()
        response = {"ok": True}
        if saved_email_analysis_version:
            response["email_analysis_rules_version"] = saved_email_analysis_version
        self._send_json(response)

    # ── Email Monitor + Content Pipeline ─────────────────────────

    def _send_email_error(self, exc: Exception, default_status: int = 400) -> None:
        if isinstance(exc, EmailProviderError):
            _log.warning("Email provider request failed: %s", exc, exc_info=True)
            self._send_json(
                {"error": "邮箱服务连接失败，请检查配置或稍后重试", "code": "email_provider_error"},
                502,
            )
            return
        status = default_status
        if not isinstance(exc, EmailAccountValidationError):
            _log.warning("Email pipeline request failed: %s", exc, exc_info=True)
            self._send_json({"error": "邮件流水线请求失败", "code": "email_request_error"}, status)
            return
        self._send_json({"error": str(exc), "code": "email_validation_error"}, status)

    def _email_analysis_rules_state(self) -> dict:
        cfg = _db.load_config()
        current_rules = cfg.get("email_analysis_rules") or {}
        validation = validate_email_analysis_rules(current_rules)
        normalized_rules = validation["rules"] if validation["ok"] else {}
        return {
            "rules": current_rules if isinstance(current_rules, dict) else {},
            "raw_rules": current_rules,
            "normalized_rules": normalized_rules,
            "effective_rules": merge_email_analysis_rules(normalized_rules),
            "validation": validation,
            "schema": email_analysis_rules_schema(),
            "history": _load_email_analysis_rules_history(),
        }

    def _save_email_analysis_rules_payload(
        self,
        payload,
        *,
        note: str = "",
        source: str = "settings-center",
    ) -> tuple[dict | None, dict, Exception | None]:
        validation = coerce_email_analysis_rules_payload(payload)
        if not validation["ok"]:
            return None, validation, None
        cfg = _db.load_config()
        cfg["email_analysis_rules"] = validation["rules"]
        try:
            _db.save_config(cfg)
        except ValueError as exc:
            return None, validation, exc
        _scheduler._invalidate_config_cache()
        history_warning = None
        try:
            version = _append_email_analysis_rules_history(
                validation["rules"],
                note=note,
                source=source,
            )
            history = _load_email_analysis_rules_history()
        except Exception as exc:
            _log.warning("Email analysis rules were saved but history write failed: %s", exc, exc_info=True)
            version = None
            history = _load_email_analysis_rules_history()
            history_warning = {
                "code": "email_analysis_rules_history_write_failed",
                "message": "规则已保存，但版本记录写入失败",
            }
        result = {
            "ok": True,
            "rules": validation["rules"],
            "raw_rules": validation["rules"],
            "normalized_rules": validation["rules"],
            "effective_rules": merge_email_analysis_rules(validation["rules"]),
            "schema": email_analysis_rules_schema(),
            "version": version,
            "history": history,
        }
        if history_warning:
            result["warning"] = history_warning
        return result, validation, None

    def _api_email_analysis_rules(self):
        try:
            self._send_json(self._email_analysis_rules_state())
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_email_analysis_rules_validate(self, body: dict):
        payload = (body or {}).get("rules", body or {})
        validation = coerce_email_analysis_rules_payload(payload)
        self._send_json(
            {
                **validation,
                "effective_rules": merge_email_analysis_rules(validation["rules"] if validation["ok"] else {}),
                "schema": email_analysis_rules_schema(),
            }
        )

    def _api_email_analysis_rules_save(self, body: dict):
        result, validation, error = self._save_email_analysis_rules_payload(
            (body or {}).get("rules", body or {}),
            note=(body or {}).get("note") or "",
            source="settings-center",
        )
        if error is not None:
            self._send_json(
                {
                    "error": str(error),
                    "code": "email_analysis_rules_save_failed",
                },
                400,
            )
            return
        if result is None:
            self._send_json(
                {
                    "error": "邮件分析规则校验失败",
                    "code": "email_analysis_rules_invalid",
                    "details": validation["errors"],
                },
                400,
            )
            return
        self._send_json(result)

    def _api_email_analysis_rules_import(self, body: dict):
        payload = (body or {}).get("payload", body or {})
        result, validation, error = self._save_email_analysis_rules_payload(
            payload,
            note=(body or {}).get("note") or "Imported from JSON",
            source="import",
        )
        if error is not None:
            self._send_json(
                {
                    "error": str(error),
                    "code": "email_analysis_rules_save_failed",
                },
                400,
            )
            return
        if result is None:
            self._send_json(
                {
                    "error": "导入的邮件分析规则校验失败",
                    "code": "email_analysis_rules_invalid",
                    "details": validation["errors"],
                },
                400,
            )
            return
        self._send_json(result)

    def _api_email_analysis_rules_export(self):
        state = self._email_analysis_rules_state()
        if not state["validation"]["ok"]:
            self._send_json(
                {
                    "error": "当前邮件分析规则存在校验错误，无法导出",
                    "code": "email_analysis_rules_invalid",
                    "details": state["validation"]["errors"],
                },
                409,
            )
            return
        self._send_json(
            {
                "schema_version": EMAIL_ANALYSIS_RULE_SCHEMA_VERSION,
                "rule_version": EMAIL_ANALYSIS_RULE_VERSION,
                "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "rules": state["normalized_rules"],
            }
        )

    def _api_email_analysis_rules_restore(self, body: dict):
        version_id = str((body or {}).get("version_id") or "").strip()
        if not version_id:
            self._send_json({"error": "version_id 不能为空"}, 400)
            return
        history = _load_email_analysis_rules_history()
        record = next((item for item in history if item.get("version_id") == version_id), None)
        if not record:
            self._send_json({"error": "版本记录不存在"}, 404)
            return
        result, validation, error = self._save_email_analysis_rules_payload(
            record.get("rules") or {},
            note=(body or {}).get("note") or f"Restored from {version_id}",
            source="restore",
        )
        if error is not None:
            self._send_json(
                {
                    "error": str(error),
                    "code": "email_analysis_rules_save_failed",
                },
                400,
            )
            return
        if result is None:
            self._send_json(
                {
                    "error": "历史版本规则校验失败",
                    "code": "email_analysis_rules_invalid",
                    "details": validation["errors"],
                },
                400,
            )
            return
        self._send_json(result)

    @staticmethod
    def _positive_int(value, *, default: int | None = None) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _string_list_body(value) -> list[str] | None:
        if value in (None, ""):
            return None
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    def _api_email_accounts(self):
        try:
            self._send_json({"accounts": _email_collect_service.list_accounts()})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_email_gmail_oauth_status(self):
        params = parse_qs(urlparse(self.path).query)
        raw_account_id = params.get("account_id", [None])[0]
        account_id = self._positive_int(raw_account_id) if raw_account_id not in (None, "") else None
        if raw_account_id not in (None, "") and account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        try:
            self._send_json(_email_collect_service.gmail_oauth_status(
                base_url=self._request_base_url(),
                account_id=account_id,
            ))
        except Exception as exc:
            self._send_email_error(exc, 404 if isinstance(exc, EmailAccountValidationError) else 500)

    def _api_email_gmail_oauth_start(self, body: dict):
        raw_account_id = (body or {}).get("account_id")
        account_id = self._positive_int(raw_account_id) if raw_account_id not in (None, "") else None
        if raw_account_id not in (None, "") and account_id is None:
            self._send_json({"error": "account_id 必须是正整数"}, 400)
            return
        try:
            result = _email_collect_service.start_gmail_oauth(
                account_id,
                base_url=str((body or {}).get("base_url") or self._request_base_url()),
                return_to=str((body or {}).get("return_to") or ""),
            )
            self._send_json(result)
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_gmail_oauth_callback(self):
        params = parse_qs(urlparse(self.path).query)
        try:
            result = _email_collect_service.finish_gmail_oauth(
                state=params.get("state", [""])[0],
                code=params.get("code", [""])[0],
                error=params.get("error", [""])[0],
                base_url=self._request_base_url(),
            )
            account_id = quote(str(result.get("account_id") or ""))
            redirect_url = f"{GMAIL_OAUTH_SUCCESS_PAGE}&account_id={account_id}"
            self._redirect(redirect_url)
        except Exception as exc:
            _log.warning("Gmail OAuth callback failed: %s", exc, exc_info=True)
            reason = quote("oauth_failed")
            redirect_url = f"{GMAIL_OAUTH_FAILURE_PAGE}&reason={reason}"
            self._redirect(redirect_url)

    def _api_email_gmail_send(self, body: dict):
        account_id = self._positive_int((body or {}).get("account_id"))
        if account_id is None:
            self._send_json({"error": "account_id 必填且必须是数字"}, 400)
            return
        try:
            self._send_json(_email_collect_service.send_gmail_message(account_id, body or {}), 202)
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_create(self, body: dict):
        try:
            account_id = _email_collect_service.save_account(body or {})
            self._send_json(
                {"ok": True, "id": account_id, "account": _email_collect_service.get_account(account_id)},
                201,
            )
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_update(self, account_id_raw: str, body: dict):
        account_id = self._positive_int(account_id_raw)
        if account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        try:
            saved_id = _email_collect_service.save_account(body or {}, account_id=account_id)
            self._send_json({"ok": True, "id": saved_id, "account": _email_collect_service.get_account(saved_id)})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_delete(self, account_id_raw: str):
        account_id = self._positive_int(account_id_raw)
        if account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        try:
            if not _email_collect_service.delete_account(account_id):
                self._send_json({"error": "邮件账号不存在"}, 404)
                return
            self._send_json({"ok": True})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_test(self, account_id_raw: str):
        account_id = self._positive_int(account_id_raw)
        if account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        try:
            self._send_json(_email_collect_service.test_account(account_id))
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_sync(self, account_id_raw: str, body: dict):
        account_id = self._positive_int(account_id_raw)
        if account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        max_messages = self._positive_int((body or {}).get("max_messages"))
        try:
            self._send_json(_email_collect_service.sync_account(account_id, max_messages=max_messages))
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_account_status(self, account_id_raw: str, status: str):
        account_id = self._positive_int(account_id_raw)
        if account_id is None:
            self._send_json({"error": "无效的邮件账号 ID"}, 400)
            return
        try:
            if not _email_collect_service.set_account_status(account_id, status):
                self._send_json({"error": "邮件账号不存在"}, 404)
                return
            self._send_json({"ok": True, "account": _email_collect_service.get_account(account_id)})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_messages(self):
        params = parse_qs(urlparse(self.path).query)
        account_id = self._positive_int(params.get("account_id", [None])[0])
        status = (params.get("status", [""])[0] or "").strip() or None
        q = (params.get("q", [""])[0] or "").strip() or None
        limit = min(max(self._positive_int(params.get("limit", ["50"])[0], default=50) or 50, 1), 200)
        offset = max(self._positive_int(params.get("offset", ["0"])[0], default=0) or 0, 0)
        try:
            messages, total = _email_collect_service.list_messages(
                account_id=account_id,
                status=status,
                q=q,
                limit=limit,
                offset=offset,
            )
            self._send_json({"messages": messages, "total": total, "limit": limit, "offset": offset})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_email_message_get(self, path: str):
        message_id = self._positive_int(path.rsplit("/", 1)[-1])
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        try:
            message = _email_collect_service.get_message(message_id, include_body=True)
            if not message:
                self._send_json({"error": "邮件不存在"}, 404)
                return
            self._send_json({"message": message})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_email_message_clean(self, message_id_raw: str):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        try:
            self._send_json({"ok": True, "message": _email_collect_service.reclean_message(message_id)})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_message_classify(self, message_id_raw: str):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        try:
            self._send_json({"ok": True, "message": _email_collect_service.classify_message(message_id)})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_message_reprocess(self, message_id_raw: str, body: dict):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        max_depth = self._positive_int((body or {}).get("max_depth"), default=1)
        try:
            self._send_json(
                {
                    "ok": True,
                    "message": _email_collect_service.reprocess_message(
                        message_id,
                        expand_links=self._coerce_bool((body or {}).get("expand_links")),
                        max_depth=max_depth,
                    ),
                }
            )
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_message_ignore(self, message_id_raw: str):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        try:
            if not _email_collect_service.mark_ignored(message_id):
                self._send_json({"error": "邮件不存在"}, 404)
                return
            self._send_json({"ok": True})
        except Exception as exc:
            self._send_email_error(exc)

    def _create_email_article_task(self, message_id: int, body: dict, cfg: dict) -> str:
        target_lang = (
            (body or {}).get("target_lang")
            or cfg.get("article_default_target_lang")
            or cfg.get("article_target_lang")
            or "zh-Hans"
        )
        payload = _email_collect_service.prepare_article_payload(message_id, target_lang=target_lang)
        task_id = _db.create_article_task(
            monitor_video_id=None,
            video_id=None,
            video_url=None,
            video_title=payload.get("video_title"),
            source_type="email_message",
            article_source_path=payload.get("article_source_path"),
            article_text=payload.get("article_text"),
            source_url=payload.get("source_url"),
            source_title=payload.get("source_title"),
            email_message_id=message_id,
            target_lang=payload.get("target_lang") or target_lang,
            auto_translate=bool((body or {}).get("auto_translate", True)),
        )
        threading.Thread(
            target=_run_article_task_safely,
            args=(task_id, cfg),
            name=f"article-task-{task_id}",
            daemon=True,
        ).start()
        return task_id

    def _api_email_message_generate(self, message_id_raw: str, body: dict):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        cfg = _db.load_config()
        try:
            task_id = self._create_email_article_task(message_id, body or {}, cfg)
            variants = []
            if (body or {}).get("create_variants", True):
                variants = _email_collect_service.generate_variants(
                    message_id,
                    article_task_id=task_id,
                    platforms=self._string_list_body((body or {}).get("platforms")),
                    replace_existing=self._coerce_bool((body or {}).get("replace_existing")),
                )
            self._send_json({"ok": True, "task_id": task_id, "variants": variants}, 202)
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_message_variants(self, message_id_raw: str, body: dict):
        message_id = self._positive_int(message_id_raw)
        if message_id is None:
            self._send_json({"error": "无效的邮件 ID"}, 400)
            return
        try:
            variants = _email_collect_service.generate_variants(
                message_id,
                article_task_id=str((body or {}).get("article_task_id") or "") or None,
                platforms=self._string_list_body((body or {}).get("platforms")),
                replace_existing=self._coerce_bool((body or {}).get("replace_existing")),
            )
            self._send_json({"ok": True, "variants": variants}, 201)
        except Exception as exc:
            self._send_email_error(exc)

    def _api_email_messages_batch_generate(self, body: dict):
        message_ids = (body or {}).get("message_ids") or []
        if not isinstance(message_ids, list):
            self._send_json({"error": "message_ids must be a list"}, 400)
            return
        parsed_ids = [self._positive_int(item) for item in message_ids]
        parsed_ids = [item for item in parsed_ids if item is not None]
        if not parsed_ids:
            self._send_json({"error": "message_ids is required"}, 400)
            return
        cfg = _db.load_config()
        platforms = self._string_list_body((body or {}).get("platforms"))
        try:
            results = []
            for message_id in parsed_ids:
                task_id = self._create_email_article_task(message_id, body or {}, cfg)
                variants = _email_collect_service.generate_variants(
                    message_id,
                    article_task_id=task_id,
                    platforms=platforms,
                    replace_existing=self._coerce_bool((body or {}).get("replace_existing")),
                )
                results.append({"message_id": message_id, "task_id": task_id, "variants": variants})
            self._send_json({"ok": True, "results": results}, 202)
        except Exception as exc:
            self._send_email_error(exc)

    def _api_content_targets(self):
        try:
            self._send_json({"targets": _email_collect_service.list_targets()})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_content_target_update(self, target_id_raw: str, body: dict):
        target_id = self._positive_int(target_id_raw)
        if target_id is None:
            self._send_json({"error": "无效的内容目标 ID"}, 400)
            return
        try:
            self._send_json({"ok": True, "target": _email_collect_service.update_target(target_id, body or {})})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_content_variants(self):
        params = parse_qs(urlparse(self.path).query)
        include_body = (params.get("include_body", ["0"])[0] or "").lower() in {"1", "true", "yes"}
        try:
            variants = _email_collect_service.list_variants(
                source_type=(params.get("source_type", [""])[0] or "").strip() or None,
                source_id=(params.get("source_id", [""])[0] or "").strip() or None,
                platform=(params.get("platform", [""])[0] or "").strip() or None,
                include_body=include_body,
            )
            self._send_json({"variants": variants})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_content_variant_get(self, variant_id_raw: str):
        variant_id = self._positive_int(variant_id_raw)
        if variant_id is None:
            self._send_json({"error": "无效的内容变体 ID"}, 400)
            return
        try:
            variant = _email_collect_service.get_variant(variant_id, include_body=True)
            if not variant:
                self._send_json({"error": "内容变体不存在"}, 404)
                return
            self._send_json({"variant": variant})
        except Exception as exc:
            self._send_email_error(exc, 500)

    def _api_content_variant_update(self, variant_id_raw: str, body: dict):
        variant_id = self._positive_int(variant_id_raw)
        if variant_id is None:
            self._send_json({"error": "无效的内容变体 ID"}, 400)
            return
        try:
            self._send_json({"ok": True, "variant": _email_collect_service.update_variant(variant_id, body or {})})
        except Exception as exc:
            self._send_email_error(exc)

    def _api_content_variant_export(self, variant_id_raw: str, body: dict):
        variant_id = self._positive_int(variant_id_raw)
        if variant_id is None:
            self._send_json({"error": "无效的内容变体 ID"}, 400)
            return
        try:
            export_format = str((body or {}).get("format") or "markdown")
            self._send_json(_email_collect_service.export_variant(variant_id, export_format=export_format))
        except Exception as exc:
            self._send_email_error(exc)

    def _api_content_variant_wechat_draft(self, variant_id_raw: str):
        variant_id = self._positive_int(variant_id_raw)
        if variant_id is None:
            self._send_json({"error": "无效的内容变体 ID"}, 400)
            return
        try:
            variant = _email_collect_service.get_variant(variant_id, include_body=True)
            if not variant:
                self._send_json({"error": "内容变体不存在"}, 404)
                return
            self._handle_wechat_publish(
                {
                    "article_task_id": str(variant.get("article_task_id") or ""),
                    "content": str(variant.get("body") or ""),
                    "title": str(variant.get("title") or ""),
                    "digest": str(variant.get("summary") or ""),
                },
                publish_mode="draft",
            )
        except Exception as exc:
            self._send_email_error(exc)

    # ── RSS Content Sources ──────────────────────────────────────

    def _api_rss_error(self, exc: Exception, status: int = 400) -> None:
        self._send_json({"error": str(exc)}, status)

    def _api_rss_feeds(self):
        try:
            self._send_json({"feeds": _rss_collect_service.list_feeds()})
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_feed_save(self, body: dict):
        try:
            feed = _rss_collect_service.save_feed(body or {})
            self._send_json({"ok": True, "feed": feed})
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_catalog(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        raw_limit = params.get("limit", [None])[0]
        limit = self._positive_int(raw_limit, default=500) if raw_limit not in (None, "") else 500
        if raw_limit not in (None, "") and self._positive_int(raw_limit) is None:
            self._send_json({"error": "limit 必须是正整数"}, 400)
            return
        raw_offset = params.get("offset", [None])[0]
        if raw_offset in (None, ""):
            offset = 0
        else:
            try:
                offset = int(raw_offset)
            except (TypeError, ValueError):
                self._send_json({"error": "offset 必须是非负整数"}, 400)
                return
            if offset < 0:
                self._send_json({"error": "offset 必须是非负整数"}, 400)
                return
        try:
            self._send_json(
                _rss_catalog_service.list_catalog(
                    source_key=(params.get("source_key", [""])[0] or "").strip() or None,
                    entry_type=(params.get("entry_type", [""])[0] or "").strip() or None,
                    category=(params.get("category", [""])[0] or "").strip() or None,
                    query=(params.get("q", [""])[0] or "").strip(),
                    available_only=(params.get("available", [""])[0] or "").lower() in {"1", "true", "yes"},
                    limit=limit,
                    offset=offset,
                )
            )
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_feed_delete(self, feed_id: str):
        parsed_id = self._positive_int(feed_id)
        if parsed_id is None:
            self._send_json({"error": "feed_id 必须是数字"}, 400)
            return
        if not _rss_collect_service.delete_feed(parsed_id):
            self._send_json({"error": "RSS 订阅源不存在"}, 404)
            return
        self._send_json({"ok": True})

    def _api_rss_items(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        raw_feed_id = params.get("feed_id", [None])[0]
        feed_id = self._positive_int(raw_feed_id) if raw_feed_id not in (None, "") else None
        if raw_feed_id not in (None, "") and feed_id is None:
            self._send_json({"error": "feed_id 必须是数字"}, 400)
            return
        raw_limit = params.get("limit", [None])[0]
        limit = self._positive_int(raw_limit, default=50) if raw_limit not in (None, "") else 50
        if raw_limit not in (None, "") and self._positive_int(raw_limit) is None:
            self._send_json({"error": "limit 必须是正整数"}, 400)
            return
        raw_offset = params.get("offset", [None])[0]
        if raw_offset in (None, ""):
            offset = 0
        else:
            try:
                offset = int(raw_offset)
            except (TypeError, ValueError):
                self._send_json({"error": "offset 必须是非负整数"}, 400)
                return
            if offset < 0:
                self._send_json({"error": "offset 必须是非负整数"}, 400)
                return
        try:
            items = _rss_collect_service.list_items(feed_id=feed_id, limit=limit, offset=offset)
            self._send_json({"items": items, "limit": limit, "offset": offset})
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_feed_refresh(self, feed_id: str, body: dict):
        parsed_id = self._positive_int(feed_id)
        if parsed_id is None:
            self._send_json({"error": "feed_id 必须是数字"}, 400)
            return
        max_items = self._positive_int((body or {}).get("max_items"), default=50) or 50
        try:
            self._send_json(_rss_collect_service.refresh_feed(parsed_id, max_items=max_items))
        except LookupError as exc:
            self._api_rss_error(exc, 404)
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_opml_import(self, body: dict):
        xml_text = str((body or {}).get("opml") or (body or {}).get("xml") or "")
        if not xml_text.strip():
            self._send_json({"error": "opml 内容不能为空"}, 400)
            return
        try:
            self._send_json(_rss_collect_service.import_opml(xml_text))
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_opml_export(self):
        try:
            self._send_json({"opml": _rss_collect_service.export_opml()})
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_catalog_sync(self):
        try:
            self._send_json(_rss_catalog_service.sync_catalog())
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_catalog_import(self, body: dict):
        raw_ids = (body or {}).get("entry_ids") or (body or {}).get("ids") or []
        if not isinstance(raw_ids, list):
            self._send_json({"error": "entry_ids 必须是数组"}, 400)
            return
        entry_ids: list[int] = []
        for raw_id in raw_ids:
            parsed_id = self._positive_int(raw_id)
            if parsed_id is None:
                self._send_json({"error": "entry_ids 必须都是正整数"}, 400)
                return
            entry_ids.append(parsed_id)
        if not entry_ids:
            self._send_json({"error": "请选择要导入的订阅源"}, 400)
            return
        interval = self._positive_int((body or {}).get("fetch_interval_minutes"), default=60) or 60
        try:
            self._send_json(_rss_catalog_service.import_catalog_entries(entry_ids, fetch_interval_minutes=interval))
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_catalog_sources(self):
        try:
            self._send_json({"sources": _rss_catalog_service.list_sources()})
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_catalog_source_add(self, body: dict):
        name = str((body or {}).get("name") or "").strip()
        feeds_url = str((body or {}).get("feeds_url") or "").strip()
        opml_content = str((body or {}).get("opml_content") or "").strip()
        if not name or (not feeds_url and not opml_content):
            self._send_json({"error": "name ?? feeds_url ? opml_content ??"}, 400)
            return
        homepage_url = str((body or {}).get("homepage_url") or "").strip()
        status_url = str((body or {}).get("status_url") or "").strip()
        try:
            source = _rss_catalog_service.add_source(
                name=name, feeds_url=feeds_url,
                homepage_url=homepage_url, status_url=status_url,
                opml_content=opml_content,
            )
            self._send_json({"ok": True, "source": source})
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_catalog_source_add_file(self) -> None:
        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len > _MAX_RSS_OPML_BODY_BYTES:
            self._send_json({"error": "OPML ??????"}, 413)
            return
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            raw = self.rfile.read(content_len)
            boundary = content_type.split("boundary=", 1)[-1].strip()
            if not boundary:
                self._send_json({"error": "?? multipart boundary"}, 400)
                return
            name_val = ""
            opml_text = ""
            for part in raw.split(b"--" + boundary.encode()):
                if not part.strip() or part.strip() == b"--":
                    continue
                if b"Content-Disposition" not in part:
                    continue
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                headers_part = part[:header_end].decode("utf-8", errors="replace")
                body_part = part[header_end + 4:].rstrip(b"\r\n- ")
                if 'name="name"' in headers_part:
                    name_val = body_part.decode("utf-8", errors="replace").strip()
                elif 'name="opml_file"' in headers_part or 'name="file"' in headers_part:
                    opml_text = body_part.decode("utf-8", errors="replace").strip()
            if not name_val or not opml_text:
                self._send_json({"error": "name ? opml_file ??"}, 400)
                return
            self._send_json(
                _rss_catalog_service.add_source(name=name_val, opml_content=opml_text)
            )
        elif "application/json" in content_type or "text/plain" in content_type:
            raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
            import json as _json
            try:
                data = _json.loads(raw)
            except Exception:
                data = {}
            name_val = str(data.get("name") or "").strip()
            opml_text = str(data.get("opml_content") or data.get("opml") or "").strip()
            if not name_val or not opml_text:
                self._send_json({"error": "name ? opml_content ??"}, 400)
                return
            self._send_json(
                _rss_catalog_service.add_source(name=name_val, opml_content=opml_text)
            )
        else:
            self._send_json({"error": "???? Content-Type"}, 400)

    def _api_rss_catalog_source_delete(self, source_key: str):
        try:
            if not _rss_catalog_service.delete_source(source_key):
                self._send_json({"error": "?????????"}, 404)
                return
            self._send_json({"ok": True})
        except Exception as exc:
            self._api_rss_error(exc, 500)

    def _api_rss_catalog_source_sync(self, source_key: str):
        try:
            self._send_json(_rss_catalog_service.sync_source(source_key))
        except LookupError as exc:
            self._api_rss_error(exc, 404)
        except Exception as exc:
            self._api_rss_error(exc)

    def _api_rss_item_generate(self, item_id: str, body: dict):
        parsed_id = self._positive_int(item_id)
        if parsed_id is None:
            self._send_json({"error": "rss_item_id 必须是数字"}, 400)
            return
        cfg = _db.load_config()
        target_lang = (
            (body or {}).get("target_lang")
            or cfg.get("article_default_target_lang")
            or cfg.get("article_target_lang")
            or "zh-Hans"
        )
        try:
            payload = _rss_collect_service.prepare_article_payload(parsed_id, target_lang=target_lang)
            task_id = _db.create_article_task(
                monitor_video_id=None,
                video_id=None,
                video_url=None,
                video_title=payload["source_title"],
                source_type="rss_item",
                article_source_path=payload.get("article_source_path"),
                article_text=payload["article_text"],
                source_url=payload["source_url"],
                source_title=payload["source_title"],
                rss_item_id=parsed_id,
                target_lang=payload["target_lang"],
                auto_translate=bool((body or {}).get("auto_translate", True)),
            )
            _rss_collect_service.mark_item_article_task(parsed_id, task_id)
        except LookupError as exc:
            self._api_rss_error(exc, 404)
            return
        except Exception as exc:
            self._api_rss_error(exc)
            return

        threading.Thread(
            target=_run_article_task_safely,
            args=(task_id, cfg),
            name=f"article-task-{task_id}",
            daemon=True,
        ).start()
        self._send_json({"ok": True, "task_id": task_id}, 202)

    # ── AI Article + Video Generation Tasks ───────────────────────

    def _ai_task_query_params(self) -> tuple[str | None, int, int]:
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        status = (params.get("status", [""])[0] or "").strip() or None
        try:
            limit = min(max(int(params.get("limit", ["50"])[0]), 1), 200)
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(int(params.get("offset", ["0"])[0]), 0)
        except (TypeError, ValueError):
            offset = 0
        return status, limit, offset

    def _api_article_generate(self, body: dict):
        """POST /api/article/generate — create an article task and run it in background."""
        body = body or {}
        cfg = _db.load_config()
        source_type = str(body.get("source_type") or "video").strip() or "video"
        if source_type == "wechatArticle":
            source_type = "wechat_article"
        if source_type == "emailMessage":
            source_type = "email_message"
        if source_type == "rssItem":
            source_type = "rss_item"
        if source_type not in {"video", "wechat_article", "email_message", "rss_item"}:
            self._send_json({"error": "source_type 不支持"}, 400)
            return

        if source_type == "rss_item":
            rss_item_id = self._positive_int(body.get("rss_item_id") or body.get("item_id"))
            if rss_item_id is None:
                self._send_json({"error": "rss_item_id 必须是数字"}, 400)
                return
            target_lang = (
                body.get("target_lang")
                or cfg.get("article_default_target_lang")
                or cfg.get("article_target_lang")
                or "zh-Hans"
            )
            try:
                payload = _rss_collect_service.prepare_article_payload(rss_item_id, target_lang=target_lang)
                task_id = _db.create_article_task(
                    monitor_video_id=None,
                    video_id=None,
                    video_url=None,
                    video_title=payload["source_title"],
                    source_type="rss_item",
                    article_source_path=payload.get("article_source_path"),
                    article_text=payload["article_text"],
                    source_url=payload["source_url"],
                    source_title=payload["source_title"],
                    rss_item_id=rss_item_id,
                    target_lang=payload["target_lang"],
                    auto_translate=bool(body.get("auto_translate", True)),
                )
                _rss_collect_service.mark_item_article_task(rss_item_id, task_id)
            except Exception as exc:
                self._api_rss_error(exc)
                return
            threading.Thread(
                target=_run_article_task_safely,
                args=(task_id, cfg),
                name=f"article-task-{task_id}",
                daemon=True,
            ).start()
            self._send_json({"ok": True, "task_id": task_id}, 202)
            return

        if source_type == "email_message":
            message_id = self._positive_int(body.get("email_message_id") or body.get("message_id"))
            if message_id is None:
                self._send_json({"error": "email_message_id 必须是数字"}, 400)
                return
            try:
                task_id = self._create_email_article_task(message_id, body, cfg)
            except Exception as exc:
                self._send_email_error(exc)
                return
            self._send_json({"ok": True, "task_id": task_id}, 202)
            return

        article_source_path = ""
        article_text = ""
        source_url = ""
        source_title = ""
        if source_type == "wechat_article":
            wechat_artifact_id = str(body.get("wechat_artifact_id") or "").strip()
            article_source_path = str(body.get("article_source_path") or "").strip()
            article_text = str(body.get("article_text") or "").strip()
            source_url = str(body.get("source_url") or "").strip()
            source_title = str(body.get("source_title") or body.get("video_title") or "").strip()
            if wechat_artifact_id:
                try:
                    article_source_path = _wechat_native_task_service.resolve_artifact_path(wechat_artifact_id)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
            elif article_source_path:
                artifact_alias = _wechat_native_artifact_id_from_url(article_source_path)
                if artifact_alias:
                    try:
                        article_source_path = _wechat_native_task_service.resolve_artifact_path(artifact_alias)
                    except Exception as exc:
                        self._send_json({"error": str(exc)}, 400)
                        return
            if not article_source_path and not article_text:
                self._send_json({"error": "wechat_artifact_id、article_source_path 或 article_text 至少提供一个"}, 400)
                return
            if article_source_path:
                data_dir = str(getattr(_db, "_DATA_DIR", os.path.join(_PROJECT_ROOT, "data")))
                configured_root = (
                    cfg.get("wechat_collection_output_dir")
                    or _wechat_collector.default_collection_output_dir(data_dir)
                )
                try:
                    resolved_path = _normalize_fs_path(article_source_path)
                    allowed_root = _normalize_fs_path(configured_root)
                    if not _is_path_within(resolved_path, allowed_root):
                        raise ValueError("文章路径必须位于公众号采集输出目录下")
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, 400)
                    return
            target_lang = (
                body.get("target_lang")
                or cfg.get("article_default_target_lang")
                or cfg.get("article_target_lang")
                or "zh-Hans"
            )
            task_id = _db.create_article_task(
                monitor_video_id=None,
                video_id=None,
                video_url=None,
                video_title=source_title,
                source_type="wechat_article",
                article_source_path=article_source_path,
                article_text=article_text,
                source_url=source_url,
                source_title=source_title,
                target_lang=target_lang,
                auto_translate=bool(body.get("auto_translate", True)),
            )

            threading.Thread(
                target=_run_article_task_safely,
                args=(task_id, cfg),
                name=f"article-task-{task_id}",
                daemon=True,
            ).start()
            self._send_json({"ok": True, "task_id": task_id}, 202)
            return

        monitor_video_id = body.get("monitor_video_id")
        if monitor_video_id in ("", None) and isinstance(body.get("video_id"), int):
            monitor_video_id = body.get("video_id")
        video = None
        if monitor_video_id not in ("", None):
            try:
                monitor_video_id = int(monitor_video_id)
            except (TypeError, ValueError):
                self._send_json({"error": "monitor_video_id 必须是数字"}, 400)
                return
            video = _db.get_monitor_video(monitor_video_id)
            if not video:
                self._send_json({"error": "视频不存在"}, 404)
                return

        video_id = body.get("video_id")
        if isinstance(video_id, int):
            video_id = (video or {}).get("video_id")
        video_url = body.get("video_url") or (video or {}).get("url")
        video_title = body.get("video_title") or (video or {}).get("title")
        if not monitor_video_id and not (video_url or video_id):
            self._send_json({"error": "monitor_video_id、video_url 或 video_id 至少提供一个"}, 400)
            return

        target_lang = (
            body.get("target_lang")
            or cfg.get("article_default_target_lang")
            or cfg.get("article_target_lang")
            or "zh-Hans"
        )
        task_id = _db.create_article_task(
            monitor_video_id=monitor_video_id,
            video_id=video_id,
            video_url=video_url,
            video_title=video_title,
            source_type="video",
            target_lang=target_lang,
            auto_translate=bool(body.get("auto_translate", True)),
        )

        threading.Thread(
            target=_run_article_task_safely,
            args=(task_id, cfg),
            name=f"article-task-{task_id}",
            daemon=True,
        ).start()
        self._send_json({"ok": True, "task_id": task_id}, 202)

    def _api_article_list(self):
        status, limit, offset = self._ai_task_query_params()
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        monitor_video_id = params.get("monitor_video_id", [None])[0] or params.get("video_id", [None])[0]
        source_type = (params.get("source_type", [""])[0] or "").strip() or None
        email_message_id = params.get("email_message_id", [None])[0] or params.get("message_id", [None])[0]
        rss_item_id = params.get("rss_item_id", [None])[0] or params.get("item_id", [None])[0]
        try:
            monitor_video_id_int = int(monitor_video_id) if monitor_video_id else None
        except (TypeError, ValueError):
            self._send_json({"error": "monitor_video_id 必须是数字"}, 400)
            return
        try:
            email_message_id_int = int(email_message_id) if email_message_id else None
        except (TypeError, ValueError):
            self._send_json({"error": "email_message_id 必须是数字"}, 400)
            return
        try:
            rss_item_id_int = int(rss_item_id) if rss_item_id else None
        except (TypeError, ValueError):
            self._send_json({"error": "rss_item_id 必须是数字"}, 400)
            return
        tasks, total = _db.list_article_tasks(
            status=status,
            monitor_video_id=monitor_video_id_int,
            source_type=source_type,
            email_message_id=email_message_id_int,
            rss_item_id=rss_item_id_int,
            limit=limit,
            offset=offset,
        )
        self._send_json({"tasks": tasks, "total": total, "limit": limit, "offset": offset})

    @staticmethod
    def _resolve_article_output_root(value: str | None) -> Path:
        root = Path(value or "output/articles").expanduser()
        if not root.is_absolute():
            root = Path(_PROJECT_ROOT) / root
        return root.resolve()

    @staticmethod
    def _resolve_article_artifact_path(raw_path: str) -> Path:
        requested = Path(raw_path).expanduser()
        if not requested.is_absolute():
            requested = Path(_PROJECT_ROOT) / requested
        return requested.resolve()

    @staticmethod
    def _article_output_files(task: dict) -> list[dict]:
        output_dir = str((task or {}).get("output_dir") or "").strip()
        if not output_dir:
            return []
        root = Path(output_dir).expanduser()
        if not root.is_absolute():
            root = Path(_PROJECT_ROOT) / root
        if not root.is_dir():
            return []
        files = []
        for path in root.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                }
            )
        files.sort(key=lambda item: item["updated_at"], reverse=True)
        return files

    def _with_article_output_files(self, task: dict) -> dict:
        enriched = dict(task)
        output_files = self._article_output_files(enriched)
        enriched["output_files"] = output_files
        enriched["latest_output_file"] = output_files[0] if output_files else None
        return enriched

    def _api_article_get(self, task_id: str):
        task = _db.get_article_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(self._with_article_output_files(task))

    def _api_article_file(self):
        """GET /api/article/file?path=... — serve article task artifacts safely."""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        raw_path = params.get("path", [None])[0]
        if not raw_path:
            self._send_json({"error": "path 必填"}, 400)
            return
        cfg = _db.load_config()
        roots = [
            self._resolve_article_output_root(str(cfg.get("article_output_dir") or "output/articles")),
        ]
        requested = self._resolve_article_artifact_path(raw_path)
        allowed = False
        for root in roots:
            try:
                requested.relative_to(root)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            self._send_json({"error": "无效的输出路径"}, 400)
            return
        if not requested.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        ctype = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset=" not in ctype:
            ctype = f"{ctype}; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(requested.stat().st_size))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(requested.name, safe='')}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        with requested.open("rb") as f:
            self.wfile.write(f.read())

    def _api_article_cancel(self, task_id: str):
        """POST /api/article/{task_id}/cancel — request cooperative cancellation."""
        task = _db.get_article_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        if task.get("status") in {"done", "error", "cancelled", "interrupted"}:
            self._send_json({"error": "终态任务不能取消", "task": task}, 409)
            return
        task = _db.request_cancel_article_task(task_id)
        self._send_json({"ok": True, "task": task})

    def _api_article_rerun(self, task_id: str):
        """POST /api/article/{task_id}/rerun — clone an article task and run it again."""
        task = _db.get_article_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        if str(task.get("status") or "") not in {"done", "error", "cancelled", "interrupted"}:
            self._send_json({"error": "任务仍在运行，不能重新执行", "task": task}, 409)
            return
        cfg = _db.load_config()
        try:
            new_task_id = _db.create_article_task(
                monitor_video_id=task.get("monitor_video_id"),
                video_id=task.get("video_id"),
                video_url=task.get("video_url"),
                video_title=task.get("video_title"),
                source_type=task.get("source_type") or "video",
                article_source_path=task.get("article_source_path"),
                article_text=task.get("article_text"),
                source_url=task.get("source_url"),
                source_title=task.get("source_title"),
                email_message_id=task.get("email_message_id"),
                rss_item_id=task.get("rss_item_id"),
                target_lang=task.get("target_lang") or cfg.get("article_default_target_lang") or "zh-Hans",
                auto_translate=bool(task.get("auto_translate", True)),
            )
        except Exception as exc:
            self._send_json({"error": f"重新执行任务创建失败: {exc}"}, 400)
            return
        threading.Thread(
            target=_run_article_task_safely,
            args=(new_task_id, cfg),
            name=f"article-task-{new_task_id}",
            daemon=True,
        ).start()
        self._send_json({"ok": True, "task_id": new_task_id, "source_task_id": task_id}, 202)

    def _api_video_gen_create(self, body: dict):
        """POST /api/video-generate — create a Pixelle-style generation task."""
        body = body or {}
        cfg = _db.load_config()
        mode = str(body.get("mode") or "generate").strip()
        if mode not in {"generate", "fixed"}:
            self._send_json({"error": "mode 只能是 generate 或 fixed"}, 400)
            return
        topic = str(body.get("topic") or "").strip()
        script_text = str(body.get("script") or body.get("script_text") or "").strip()
        if mode == "fixed" and not script_text:
            self._send_json({"error": "fixed 模式必须提供 script"}, 400)
            return
        if mode == "generate" and not topic:
            self._send_json({"error": "generate 模式必须提供 topic"}, 400)
            return
        try:
            scene_count = int(
                body.get("n_scenes")
                or body.get("scene_count")
                or cfg.get("video_gen_default_scene_count")
                or cfg.get("default_scene_count")
                or 5
            )
        except (TypeError, ValueError):
            self._send_json({"error": "n_scenes 必须是数字"}, 400)
            return
        if scene_count < 1 or scene_count > 12:
            self._send_json({"error": "n_scenes 必须在 1 到 12 之间"}, 400)
            return
        bgm_volume = body.get("bgm_volume")
        if bgm_volume not in ("", None):
            try:
                bgm_volume = float(bgm_volume)
            except (TypeError, ValueError):
                self._send_json({"error": "bgm_volume 必须是数字"}, 400)
                return
            if bgm_volume < 0 or bgm_volume > 1:
                self._send_json({"error": "bgm_volume 必须在 0 到 1 之间"}, 400)
                return
        else:
            bgm_volume = None
        template_key = (
            body.get("template")
            or body.get("template_key")
            or cfg.get("video_gen_default_template")
            or cfg.get("default_template")
        )
        try:
            from scripts.video_gen_pipeline import normalize_template_key

            template_key = normalize_template_key(template_key)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        task_id = _db.create_video_gen_task(
            mode=mode,
            topic=topic,
            script_text=script_text,
            template_key=template_key,
            scene_count=scene_count,
            prompt_prefix=str(body.get("prompt_prefix") or "").strip() or None,
            image_workflow=str(body.get("image_workflow") or "").strip() or None,
            tts_workflow=str(body.get("tts_workflow") or "").strip() or None,
            bgm_volume=bgm_volume,
        )

        def _run():
            from scripts.video_gen_pipeline import run_video_gen_task

            run_video_gen_task(task_id, cfg=cfg)

        threading.Thread(target=_run, name=f"video-gen-task-{task_id}", daemon=True).start()
        self._send_json({"ok": True, "task_id": task_id}, 202)

    def _api_video_gen_list(self):
        status, limit, offset = self._ai_task_query_params()
        tasks, total = _db.list_video_gen_tasks(status=status, limit=limit, offset=offset)
        self._send_json({"tasks": tasks, "total": total, "limit": limit, "offset": offset})

    def _api_video_gen_get(self, task_id: str):
        task = _db.get_video_gen_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(task)

    def _api_video_gen_cancel(self, task_id: str):
        """POST /api/video-generate/{task_id}/cancel — request cooperative cancellation."""
        task = _db.get_video_gen_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        if task.get("status") in {"done", "error", "cancelled", "interrupted"}:
            self._send_json({"error": "终态任务不能取消", "task": task}, 409)
            return
        task = _db.request_cancel_video_gen_task(task_id)
        self._send_json({"ok": True, "task": task})

    def _api_video_gen_templates(self):
        from scripts.video_gen_pipeline import list_pixelle_templates

        self._send_json({"templates": list_pixelle_templates()})

    def _api_video_gen_file(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        raw_path = params.get("path", [None])[0]
        if not raw_path:
            self._send_json({"error": "path 必填"}, 400)
            return
        cfg = _db.load_config()
        roots = [
            Path(cfg.get("video_gen_output_dir") or "output/video-gen"),
            Path(cfg.get("article_output_dir") or "output/articles"),
        ]
        requested = Path(raw_path).expanduser().resolve()
        allowed = False
        for root in roots:
            try:
                requested.relative_to(root.expanduser().resolve())
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            self._send_json({"error": "无效的输出路径"}, 400)
            return
        if not requested.is_file():
            self._send_json({"error": "文件不存在"}, 404)
            return
        ctype = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(requested.stat().st_size))
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        with requested.open("rb") as f:
            self.wfile.write(f.read())

    # ── WeChat Official Account Publishing ─────────────────────

    def _api_wechat_draft(self, body: dict):
        """POST /api/wechat/draft — create a WeChat draft only."""
        self._handle_wechat_publish(body or {}, publish_mode="draft")

    def _api_wechat_publish(self, body: dict):
        """POST /api/wechat/publish — create a draft and submit freepublish."""
        self._handle_wechat_publish(body or {}, publish_mode="publish")

    def _handle_wechat_publish(self, body: dict, publish_mode: str):
        from config.validation import validate_wechat_config
        from monitor import wechat_publisher as wp

        cfg = _db.load_config()
        validation_errors = validate_wechat_config(cfg)
        if validation_errors:
            self._send_json({"error": validation_errors[0], "details": validation_errors}, 400)
            return

        article_task_id = (body.get("article_task_id") or "").strip() or None
        article_task = _db.get_article_task(article_task_id) if article_task_id else None
        if article_task_id and not article_task:
            self._send_json({"error": "关联的文章任务不存在"}, 404)
            return

        body_draft_path = str(body.get("draft_path") or "").strip()
        task_draft_path = str((article_task or {}).get("draft_path") or "").strip()
        article_result = (article_task or {}).get("result") if isinstance(article_task, dict) else {}
        if not isinstance(article_result, dict):
            article_result = {}
        publish_markdown_path = str(article_result.get("article_publish_markdown_path") or "").strip()
        draft_path = body_draft_path or task_draft_path
        if publish_markdown_path and (
            not body_draft_path
            or self._paths_refer_to_same_file(body_draft_path, task_draft_path)
        ):
            draft_path = publish_markdown_path
        content = str(body.get("content") or "").strip()
        body_title = str(body.get("title") or "").strip()
        task_title = str((article_task or {}).get("video_title") or "").strip()
        title = body_title or task_title
        author = str(body.get("author") or "").strip()
        digest = str(body.get("digest") or "").strip()
        theme = str(body.get("theme") or cfg.get("wechat_default_theme") or "default").strip()
        color = str(body.get("color") or cfg.get("wechat_default_color") or "blue").strip()
        renderer = str(body.get("renderer") or cfg.get("wechat_markdown_renderer") or "auto").strip()
        baoyu_script = str(cfg.get("wechat_baoyu_markdown_to_html_script") or "").strip()
        cover_image = (body.get("cover_image") or "").strip() or None
        base_dir = None
        draft_file = None
        render_result = None
        if draft_path:
            try:
                draft_file = self._resolve_article_output_path(draft_path, cfg)
                base_dir = draft_file.parent
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return

        if not content and draft_file:
            if not draft_file.is_file():
                self._send_json({"error": f"draft 文件不存在: {draft_file}"}, 400)
                return
            try:
                render_result = wp.render_md_to_html_for_wechat(
                    draft_file,
                    theme=theme,
                    color=color,
                    renderer=renderer,
                    baoyu_script=baoyu_script,
                )
            except Exception as exc:
                self._send_json({"error": f"微信文章排版失败: {exc}"}, 400)
                return
            title = body_title or render_result.title or title
            author = author or render_result.author or ""
            digest = digest or render_result.digest or ""
            content = render_result.content
        elif not content:
            self._send_json({"error": "content 或 draft_path 至少需要一个"}, 400)
            return

        title = wp.normalize_wechat_title(title)
        author = author or str(cfg.get("wechat_default_author") or "").strip()
        digest = digest or wp._digest_from_html(content)
        article_errors = wp.validate_wechat_article_payload(
            title=title,
            content=content,
            author=author,
            digest=digest,
        )
        if article_errors:
            self._send_json({"error": article_errors[0], "details": article_errors}, 400)
            return

        need_open_comment = self._coerce_bool(
            body.get("need_open_comment", cfg.get("wechat_need_open_comment", True))
        )
        only_fans_can_comment = self._coerce_bool(
            body.get("only_fans_can_comment", cfg.get("wechat_only_fans_can_comment", False))
        )

        task_id = _db.create_wechat_publish_task(
            draft_path=draft_path,
            title=title,
            article_task_id=article_task_id,
            author=author,
            theme=theme,
            color=color,
            need_open_comment=need_open_comment,
            only_fans_can_comment=only_fans_can_comment,
            cover_image=cover_image,
            html_content=content,
            publish_mode=publish_mode,
        )

        article_output_root = self._resolve_article_output_root(str(cfg.get("article_output_dir") or "output/articles"))

        def _publish_task():
            try:
                _db.update_wechat_publish_task(task_id, status="running")
                publisher = wp.WechatPublisher(
                    app_id=cfg.get("wechat_app_id"),
                    app_secret=cfg.get("wechat_app_secret"),
                    data_dir=str(article_output_root),
                )
                kwargs = {
                    "title": title,
                    "content": content,
                    "author": author,
                    "digest": digest,
                    "cover_image": cover_image,
                    "need_open_comment": need_open_comment,
                    "only_fans_can_comment": only_fans_can_comment,
                    "base_dir": base_dir,
                }
                if publish_mode == "publish":
                    result = publisher.publish_now(**kwargs)
                else:
                    result = publisher.save_to_draft(**kwargs)
                if result.success:
                    _db.update_wechat_publish_task(
                        task_id,
                        status="done",
                        wx_article_id=result.wx_article_id,
                        wx_url=result.wx_url,
                        finished_at=_db.now_iso(),
                    )
                else:
                    _db.update_wechat_publish_task(
                        task_id,
                        status="error",
                        error=result.error or "微信公众号发布失败",
                        finished_at=_db.now_iso(),
                    )
            except Exception as exc:
                _log.exception("WeChat publish task failed: %s", task_id)
                _db.update_wechat_publish_task(
                    task_id,
                    status="error",
                    error=str(exc),
                    finished_at=_db.now_iso(),
                )

        threading.Thread(target=_publish_task, name=f"wechat-publish-{task_id}", daemon=True).start()
        response = {"task_id": task_id, "status": "pending"}
        if render_result:
            response["renderer"] = render_result.renderer
            response["html_path"] = render_result.html_path
            response["warnings"] = render_result.warnings
        self._send_json(response, 202)

    @staticmethod
    def _paths_refer_to_same_file(left: str, right: str) -> bool:
        if not left or not right:
            return False
        try:
            return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
        except Exception:
            left_norm = left.replace("\\", "/").rstrip("/").lower()
            right_norm = right.replace("\\", "/").rstrip("/").lower()
            return left_norm == right_norm

    @staticmethod
    def _resolve_article_output_path(raw_path: str, cfg: dict) -> Path:
        requested = MonitorHandler._resolve_article_artifact_path(raw_path)
        roots = [
            MonitorHandler._resolve_article_output_root(str(cfg.get("article_output_dir") or "output/articles")),
        ]
        for root in roots:
            try:
                requested.relative_to(root)
                return requested
            except ValueError:
                continue
        raise ValueError("无效的输出路径")

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off"}
        return bool(value)

    def _api_wechat_task_status(self, task_id: str):
        """GET /api/wechat/tasks/{task_id}."""
        task = _db.get_wechat_publish_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        safe = {
            "task_id": task.get("task_id"),
            "article_task_id": task.get("article_task_id"),
            "title": task.get("title"),
            "author": task.get("author"),
            "theme": task.get("theme"),
            "color": task.get("color"),
            "publish_mode": task.get("publish_mode"),
            "status": task.get("status"),
            "wx_article_id": task.get("wx_article_id"),
            "wx_url": task.get("wx_url"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "finished_at": task.get("finished_at"),
        }
        self._send_json(safe)

    # ── Clip Tasks ────────────────────────────────────────────

    def _api_clip_create(self, body: dict):
        """POST /api/clips — 创建并立即启动一个切片任务"""
        video_id = body.get("video_id")
        if not video_id:
            self._send_json({"error": "video_id 必填"}, 400)
            return

        # 查询视频信息
        video = _db.get_monitor_video(video_id)
        if not video:
            self._send_json({"error": "视频不存在"}, 404)
            return

        if not video.get("download_path"):
            self._send_json({"error": "视频文件未下载，请先下载"}, 400)
            return

        video_path = resolve_downloaded_video_path(video)
        if not video_path or not os.path.isfile(video_path):
            self._send_json(
                {"error": "无法解析已下载视频路径（若为历史数据仅保存了输出目录，请重新下载该视频以写入具体文件路径）"},
                400,
            )
            return

        # 查找同目录下的字幕文件
        # yt-dlp 字幕命名: video.mp4 -> video.en.vtt / video.zh-Hans.srt 等（追加语言代码）
        # 也可能是转换后: video.srt / video.vtt（FFmpegSubtitlesConvertor）
        video_dir = os.path.dirname(video_path)
        video_stem = os.path.splitext(os.path.basename(video_path))[0]
        sub_path = None

        # 优先精确匹配：同名字幕（无语言代码，convert_subs 结果）
        for ext in (".srt", ".vtt"):
            candidate = os.path.join(video_dir, video_stem + ext)
            if os.path.exists(candidate):
                sub_path = candidate
                break

        # 其次模糊匹配：video.*.srt / video.*.vtt（带语言代码）
        if not sub_path:
            for candidate in os.listdir(video_dir):
                if candidate.startswith(video_stem + ".") and candidate.rsplit(".", 1)[-1] in ("srt", "vtt"):
                    sub_path = os.path.join(video_dir, candidate)
                    break

        # 最后尝试 output 目录下同名字幕
        if not sub_path:
            output_dir = os.path.join(video_dir, "output")
            if os.path.isdir(output_dir):
                for candidate in os.listdir(output_dir):
                    if candidate.startswith(video_stem + ".") and candidate.rsplit(".", 1)[-1] in ("srt", "vtt"):
                        sub_path = os.path.join(output_dir, candidate)
                        break

        if not sub_path:
            self._send_json({
                "error": f"未找到字幕文件（支持 .srt 和 .vtt），请确保同目录有字幕文件：\n"
                         f"视频：{os.path.basename(video_path)}\n"
                         f"字幕命名示例：{video_stem}.en.vtt 或 {video_stem}.srt"
            }, 400)
            return
        srt_path = sub_path

        account = _db.get_account(video.get("account_id"))
        account_name = account.get("name", "未知账户") if account else "未知账户"

        # 构建输出目录
        clip_output_dir = os.path.join(
            os.path.dirname(video_path), "clips", os.path.splitext(os.path.basename(video_path))[0]
        )
        os.makedirs(clip_output_dir, exist_ok=True)

        # 读取 LLM 配置（优先用请求体，其次全局配置）
        cfg = _db.load_config()
        llm_provider = body.get("llm_provider") or cfg.get("llm_provider", "qwen")
        llm_model = body.get("llm_model") or cfg.get("llm_model")
        min_score = float(body.get("min_score", 7.0))
        category = body.get("category", "knowledge")

        # 创建任务记录
        task_id = _db.create_clip_task(
            video_id=video.get("video_id") or 0,
            monitor_video_id=video_id,
            account_id=video.get("account_id") or 0,
            account_name=account_name,
            video_title=video.get("title", "未知标题"),
            video_path=video_path,
            srt_path=srt_path,
            output_dir=clip_output_dir,
            llm_provider=llm_provider,
            llm_model=llm_model,
            min_score=min_score,
            category=category,
        )

        # 异步启动 ClipPipeline
        _db.update_clip_task(task_id, status="running", started_at=datetime.now().isoformat())
        from scripts.clip_pipeline import ClipPipeline
        from scripts.llm_client import create_llm_client
        import threading

        def _run_clip():
            try:
                llm_client = create_llm_client(
                    provider=llm_provider,
                    model=llm_model,
                    api_key=cfg.get("llm_api_key"),
                    base_url=cfg.get("llm_base_url"),
                )
                pipeline = ClipPipeline(
                    llm_client=llm_client,
                    output_dir=clip_output_dir,
                    min_score=min_score,
                )
                ctx = pipeline.run(video_path=video_path, srt_path=srt_path)
                _db.update_clip_task(
                    task_id,
                    status="done",
                    finished_at=datetime.now().isoformat(),
                    clip_count=len(ctx.generated_clips),
                    collection_count=len(ctx.generated_collections),
                )
            except Exception as e:
                _db.update_clip_task(
                    task_id,
                    status="error",
                    finished_at=datetime.now().isoformat(),
                    error=str(e),
                )

        t = threading.Thread(target=_run_clip, name=f"clip-task-{task_id}", daemon=True)
        t.start()

        self._send_json({"ok": True, "task_id": task_id})

    def _api_clip_list(self):
        """GET /api/clips — 查询切片任务列表"""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)
        account_id = params.get("account_id", [None])[0]
        monitor_video_id = params.get("video_id", [None])[0]
        status = params.get("status", [None])[0]
        limit = int(params.get("limit", ["50"])[0])
        offset = int(params.get("offset", ["0"])[0])

        tasks, total = _db.list_clip_tasks(
            account_id=int(account_id) if account_id else None,
            monitor_video_id=int(monitor_video_id) if monitor_video_id else None,
            status=status or None,
            limit=min(limit, 200),
            offset=offset,
        )
        self._send_json({"tasks": tasks, "total": total, "limit": limit, "offset": offset})

    def _api_clip_get(self, task_id: int):
        """GET /api/clips/<id> — 获取单个任务详情"""
        task = _db.get_clip_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(task)

    def _api_videos_retry(self, body: dict):
        """POST /api/videos/retry — 重试失败视频"""
        video_ids = body.get("video_ids", [])
        account_id = body.get("account_id")

        # 输入验证
        if not isinstance(video_ids, list) or not video_ids:
            self._send_json({"error": "video_ids 必须是非空列表"}, 400)
            return
        if not isinstance(account_id, int) or account_id <= 0:
            self._send_json({"error": "account_id 必须是整数"}, 400)
            return

        # 验证账户存在
        account = _db.get_account(account_id)
        if not account:
            self._send_json({"error": "账户不存在"}, 404)
            return

        # 重试：将 failed 视频重置为 pending
        from monitor.db.queries.videos import reset_videos_for_retry
        reset_videos_for_retry(video_ids, account_id)
        self._send_json({"ok": True, "retried": len(video_ids)})

    def _api_scheduler_start(self, body: dict):
        auto_dl = bool(body.get("auto_download", False))
        ok, already_running = _scheduler.start(auto_download=auto_dl)
        self._send_json({"ok": ok, "already_running": already_running})

    def _api_scheduler_stop(self):
        ok = _scheduler.stop()
        self._send_json({"ok": ok})

    def _api_scheduler_reload(self):
        n = _scheduler.reload_jobs()
        self._send_json({"ok": True, "active_jobs": n})

    def _api_provider_scheduler_status(self):
        running = _provider_scheduler.is_running()
        next_runs = _provider_scheduler.get_next_run_times() if running else []
        self._send_json({"running": running, "next_runs": next_runs})

    def _api_provider_scheduler_logs(self):
        self._send_json(_db.list_provider_scheduler_runs())

    def _api_provider_scheduler_start(self):
        ok = _provider_scheduler.start()
        self._send_json({"ok": ok})

    def _api_provider_scheduler_stop(self):
        ok = _provider_scheduler.stop()
        self._send_json({"ok": ok})

    def _api_provider_scheduler_reload(self):
        n = _provider_scheduler.reload_jobs()
        self._send_json({"ok": True, "active_jobs": n})

    def _api_provider_scheduler_run_once(self):
        result = _provider_scheduler.run_once()
        self._send_json(result)

    def _api_account_add(self, body):
        try:
            if not body.get("name", "").strip():
                self._send_json({"error": "账户名称不能为空"}, 400)
                return
            channel_url = body.get("channel_url", "").strip()
            if not channel_url:
                self._send_json({"error": "频道 URL 不能为空"}, 400)
                return
            if not _is_valid_youtube_url(channel_url):
                self._send_json({"error": "频道 URL 必须为合法的 YouTube URL、@handle 或 UC 频道 ID"}, 400)
                return

            account_id = body.get("id")
            api_key_id_val = body.get("api_key_id")
            api_key_id_param = None
            if api_key_id_val is not None:
                api_key_id_param = int(api_key_id_val) if api_key_id_val else None

            proxy_pool_id_val = body.get("proxy_pool_id")
            proxy_pool_id_param = None
            if proxy_pool_id_val is not None:
                proxy_pool_id_param = int(proxy_pool_id_val) if proxy_pool_id_val else None

            if account_id:
                account_id = int(account_id)
                api_key_id_update = api_key_id_param if "api_key_id" in body else _db._UNSET
                proxy_pool_id_update = (
                    proxy_pool_id_param if "proxy_pool_id" in body else _db._UNSET
                )
                _db.update_account(
                    account_id=account_id,
                    name=body.get("name", "").strip(),
                    channel_url=channel_url,
                    api_key_env=body.get("api_key_env"),
                    fetch_mode=body.get("fetch_mode"),
                    fetch_limit=int(body["fetch_limit"]) if str(body.get("fetch_limit", "")).isdigit() else None,
                    scan_interval=int(body["scan_interval"]) if str(body.get("scan_interval", "")).isdigit() else None,
                    enabled=bool(body.get("enabled")) if "enabled" in body else None,
                    notify_enabled=bool(body.get("notify_enabled")) if "notify_enabled" in body else None,
                    notify_platform=body.get("notify_platform"),
                    webhook_url=_optional_nullable_body_value(body, "webhook_url"),
                    telegram_bot_token=_resolve_optional_account_secret(
                        account_id, "telegram_bot_token", body
                    ),
                    dingtalk_sign_secret=_resolve_optional_account_secret(
                        account_id, "dingtalk_sign_secret", body
                    ),
                    feishu_message_mode=body.get("feishu_message_mode"),
                    feishu_template_id=_optional_nullable_body_value(body, "feishu_template_id"),
                    feishu_scan_template_id=_optional_nullable_body_value(body, "feishu_scan_template_id"),
                    api_key_id=api_key_id_update,
                    proxy_pool_id=proxy_pool_id_update,
                    proxy_enabled=bool(body.get("proxy_enabled")) if "proxy_enabled" in body else None,
                    download_proxy_mode=(
                        body.get("download_proxy_mode")
                        if "download_proxy_mode" in body
                        else _db._UNSET
                    ),
                )
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self._send_json({"ok": True, "id": account_id})
            else:
                account_id = _db.add_account(
                    name=body.get("name", "").strip(),
                    channel_url=channel_url,
                    api_key_env=body.get("api_key_env", "YOUTUBE_Data_API_V3"),
                    fetch_mode=body.get("fetch_mode", "playlist"),
                    fetch_limit=int(body.get("fetch_limit", 5)),
                    scan_interval=int(body.get("scan_interval", 5)),
                    notify_enabled=bool(body.get("notify_enabled", True)),
                    notify_platform=body.get("notify_platform", "feishu"),
                    webhook_url=body.get("webhook_url") or None,
                    telegram_bot_token=body.get("telegram_bot_token") or None,
                    dingtalk_sign_secret=body.get("dingtalk_sign_secret") or None,
                    feishu_message_mode=body.get("feishu_message_mode", "card_json"),
                    feishu_template_id=body.get("feishu_template_id") or None,
                    feishu_scan_template_id=body.get("feishu_scan_template_id") or None,
                    api_key_id=api_key_id_param,
                    proxy_pool_id=proxy_pool_id_param,
                    proxy_enabled=bool(body.get("proxy_enabled", False)),
                    download_proxy_mode=body.get("download_proxy_mode", "auto"),
                )
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self._send_json({"ok": True, "id": account_id})
        except Exception:
            _log.error("账户操作异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_account_update(self, acc_id, body):
        try:
            account_id = int(acc_id)
        except (TypeError, ValueError):
            self._send_json({"error": "账户 ID 无效"}, 400)
            return
        update_body = dict(body or {})
        update_body["id"] = account_id
        self._api_account_add(update_body)

    def _api_account_scan(self, body):
        acc_id = int(body.get("account_id", 0))
        auto_dl = bool(body.get("auto_download", False))
        queued = _scheduler.trigger_scan_async(acc_id, auto_download=auto_dl)
        self._send_json({"ok": True, "queued": queued, "already_running": not queued})

    def _api_account_delete(self, acc_id):
        try:
            _db.delete_account(int(acc_id))
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("账户删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_cache_list(self):
        self._send_json(_cache.list_all_cache())

    def _api_cache_refresh(self, body):
        handle = body.get("handle", "")
        api_key = body.get("api_key", "")
        if not handle or not api_key:
            self._send_json({"error": "handle 和 api_key 均必填"}, 400)
            return
        result = _cache.refresh_from_api(handle, api_key)
        self._send_json(result, 200 if result["success"] else 500)

    def _api_cache_delete(self, handle):
        ok = _cache.delete_channel_meta(handle)
        self._send_json({"ok": ok})

    def _api_cache_clear(self):
        count = _cache.clear_all_cache()
        self._send_json({"ok": True, "cleared": count})

    def _api_quota(self):
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        rows = _quota.get_all_usage(today)
        all_keys = {k["key_value"]: k for k in _db.list_api_keys()}
        for row in rows:
            raw_key = row.get("api_key_env", "")
            if raw_key:
                row["api_key_env"] = self._mask_key(raw_key)
            ak = all_keys.get(raw_key)
            if ak:
                row["daily_quota"] = ak.get("daily_quota", 8000)
                row["key_name"] = ak.get("name", "")
                row["is_active"] = bool(ak.get("is_active"))
            else:
                row["daily_quota"] = 8000
                row["key_name"] = ""
                row["is_active"] = True
        self._send_json({"items": rows})

    # ── API Key CRUD ─────────────────────────────────────────

    def _api_api_keys_list(self):
        keys = _db.list_api_keys()
        result = [{
            "id": k["id"],
            "name": k["name"],
            "key_value": self._mask_key(k["key_value"]),
            "daily_quota": k["daily_quota"],
            "quota_used": k.get("quota_used") or 0,
            "scans_done": k.get("scans_done") or 0,
            "blocked_scans": k.get("blocked_scans") or 0,
            "is_active": bool(k["is_active"]),
            "created_at": k["created_at"],
        } for k in keys]
        self._send_json(result)

    def _api_api_key_add(self, body):
        try:
            key_value = body.get("key_value", "").strip()
            name = body.get("name", "").strip()
            daily_quota = int(body.get("daily_quota", 10000)) if str(body.get("daily_quota", "")).isdigit() else 10000
            if not key_value or not name:
                self._send_json({"error": "API Key 和名称均不能为空"}, 400)
                return
            key_id = _db.add_api_key(key_value, name, daily_quota)
            self._send_json({"ok": True, "id": key_id})
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                self._send_json({"error": "该 API Key 已存在"}, 400)
            else:
                _log.error("API Key 操作异常", exc_info=True)
                self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_api_key_update(self, key_id: int, body):
        try:
            name = body.get("name")
            key_value = body.get("key_value", "").strip() or None
            daily_quota = int(body["daily_quota"]) if str(body.get("daily_quota", "")).isdigit() else None
            is_active = bool(body.get("is_active")) if "is_active" in body else None
            _db.update_api_key(
                key_id,
                name=name if name else None,
                key_value=key_value,
                daily_quota=daily_quota,
                is_active=is_active,
            )
            self._send_json({"ok": True})
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                self._send_json({"error": "该 API Key 已存在"}, 400)
            else:
                _log.error("API Key 更新异常", exc_info=True)
                self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_api_key_delete(self, key_id: int):
        try:
            accounts = [a for a in _db.list_accounts() if a.get("api_key_id") == key_id]
            affected = [{"id": a["id"], "name": a["name"]} for a in accounts]
            _db.delete_api_key(key_id)
            self._send_json({"ok": True, "affected_accounts": affected})
        except Exception:
            _log.error("API Key 删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    # ── 代理池 CRUD ──────────────────────────────────────────

    def _api_proxy_pools_list(self):
        pools = _db.list_proxy_pools()
        result = [{
            "id": p["id"],
            "name": p["name"],
            "proxy_url": self._mask_proxy_url(p["proxy_url"]),
            "enabled": bool(p["enabled"]),
            "created_at": p["created_at"],
        } for p in pools]
        self._send_json(result)

    def _api_proxy_pool_add(self, body):
        try:
            name = body.get("name", "").strip()
            proxy_url = body.get("proxy_url", "").strip()
            if not name or not proxy_url:
                self._send_json({"error": "名称和代理地址均不能为空"}, 400)
                return
            pool_id = _db.add_proxy_pool(name, proxy_url)
            self._send_json({"ok": True, "id": pool_id})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception:
            _log.error("代理池操作异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_proxy_pool_update(self, pool_id: int, body):
        try:
            name = body.get("name", "").strip() or None
            proxy_url = body.get("proxy_url", "").strip() or None
            enabled = bool(body.get("enabled")) if "enabled" in body else None
            if proxy_url is not None and not proxy_url:
                self._send_json({"error": "代理地址不能为空"}, 400)
                return
            _db.update_proxy_pool(pool_id, name=name, proxy_url=proxy_url, enabled=enabled)
            self._send_json({"ok": True})
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception:
            _log.error("代理池更新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_proxy_pool_delete(self, pool_id: int):
        try:
            accounts = [a for a in _db.list_accounts() if a.get("proxy_pool_id") == pool_id]
            affected = [{"id": a["id"], "name": a["name"]} for a in accounts]
            _db.delete_proxy_pool(pool_id)
            self._send_json({"ok": True, "affected_accounts": affected})
        except Exception:
            _log.error("代理池删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    # ── Dynamic Proxy Provider API ──────────────────────────────

    def _api_dynamic_providers_list(self):
        providers = _db.list_dynamic_proxy_providers()
        result = []
        for p in providers:
            cfg = p.get("config_json", {}) or {}
            preview = dict(cfg)
            for sensitive in ("password", "auth_secret", "api_key", "local_proxy_url"):
                if sensitive in preview:
                    preview[sensitive] = "***"

            cooldown_until = p.get("cooldown_until")
            is_in_cooldown = False
            if cooldown_until:
                try:
                    cooldown_dt = datetime.fromisoformat(cooldown_until)
                    now_dt = datetime.now(cooldown_dt.tzinfo) if cooldown_dt.tzinfo else datetime.now()
                    is_in_cooldown = cooldown_dt > now_dt
                except Exception:
                    is_in_cooldown = False

            status_map = {
                "healthy": "可用",
                "degraded": "降级",
                "auth_error": "认证失败",
                "down": "不可用",
                "not_started": "未启动",
            }
            status_text = "冷却中" if is_in_cooldown else status_map.get(p.get("last_health_status") or "", "未知")

            capabilities = []
            for cap, label in [
                ("supports_cookies", "Cookie 下载可用"),
                ("supports_auto_download", "自动下载可用"),
                ("supports_country_filter", "支持国家筛选"),
                ("supports_sticky_session", "支持粘性会话"),
            ]:
                if p.get(cap):
                    capabilities.append(label)

            masked_preview = None
            adapter = p.get("adapter_type")
            if adapter == "rotating_gateway":
                protocol = cfg.get("protocol", "http")
                gateway_host = cfg.get("gateway_host")
                gateway_port = cfg.get("gateway_port")
                username = cfg.get("username", "")
                if gateway_host and gateway_port:
                    raw_url = f"{protocol}://{username + ':***@' if username else ''}{gateway_host}:{gateway_port}"
                    masked_preview = _db.mask_proxy_url(raw_url)
            elif adapter == "local_gateway":
                local_proxy = cfg.get("local_proxy_url")
                masked_preview = _db.mask_proxy_url(local_proxy) if local_proxy else None

            result.append({
                "id": p["id"],
                "name": p["name"],
                "enabled": bool(p["enabled"]),
                "billing_tier": p.get("billing_tier", "free"),
                "adapter_type": adapter or "public_feed",
                "priority": p.get("priority", 100),
                "refresh_interval_minutes": p.get("refresh_interval_minutes", 0),
                "supports_cookies": bool(p.get("supports_cookies")),
                "supports_auto_download": bool(p.get("supports_auto_download")),
                "supports_country_filter": bool(p.get("supports_country_filter")),
                "supports_sticky_session": bool(p.get("supports_sticky_session")),
                "risk_level": p.get("risk_level", "medium"),
                "notes": p.get("notes") or "",
                "config_json": preview,
                "masked_preview": masked_preview,
                "status_text": status_text,
                "capabilities": capabilities,
                "last_health_status": p.get("last_health_status") or "",
                "last_health_checked_at": p.get("last_health_checked_at") or "",
                "last_error_message": p.get("last_error_message") or "",
                "is_in_cooldown": is_in_cooldown,
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
            })
        self._send_json(result)

    def _api_dynamic_provider_add(self, body: dict):
        try:
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "名称不能为空"}, 400)
                return
            provider_id = _db.add_dynamic_proxy_provider(
                name=name,
                billing_tier=body.get("billing_tier", "free"),
                adapter_type=body.get("adapter_type", "public_feed"),
                config_json=body.get("config_json") or {},
                enabled=bool(body.get("enabled", True)),
                priority=int(body.get("priority", 100)),
                supports_cookies=bool(body.get("supports_cookies", False)),
                supports_auto_download=bool(body.get("supports_auto_download", True)),
                supports_country_filter=bool(body.get("supports_country_filter", False)),
                supports_sticky_session=bool(body.get("supports_sticky_session", False)),
                risk_level=body.get("risk_level", "medium"),
                notes=body.get("notes") or None,
                refresh_interval_minutes=int(body.get("refresh_interval_minutes") or 0),
            )
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True, "id": provider_id})
        except Exception:
            _log.error("动态代理提供方新增异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_update(self, provider_id: int, body: dict):
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            update_kwargs = {}
            for field, key in [
                ("name", "name"), ("enabled", "enabled"), ("billing_tier", "billing_tier"),
                ("adapter_type", "adapter_type"), ("priority", "priority"),
                ("supports_cookies", "supports_cookies"), ("supports_auto_download", "supports_auto_download"),
                ("supports_country_filter", "supports_country_filter"), ("supports_sticky_session", "supports_sticky_session"),
                ("refresh_interval_minutes", "refresh_interval_minutes"), ("risk_level", "risk_level"),
            ]:
                if key in body:
                    val = body[key]
                    update_kwargs[field] = bool(val) if key.startswith("supports_") or key == "enabled" else val
            if "notes" in body:
                update_kwargs["notes"] = body["notes"] or None
            if "config_json" in body:
                update_kwargs["config_json"] = body["config_json"]
            _db.update_dynamic_proxy_provider(provider_id, **update_kwargs)
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("动态代理提供方更新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_delete(self, provider_id: int):
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            _db.delete_dynamic_proxy_provider(provider_id)
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self._send_json({"ok": True})
        except Exception:
            _log.error("动态代理提供方删除异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_health_check(self, provider_id: int):
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return

            from monitor.provider_health import check_provider_health
            result = check_provider_health(provider_id)

            cfg = _db.load_config()
            cooldown_seconds = cfg.get("provider_cooldown_seconds", 600)
            cooldown_until: str | None = None
            if result.status in ("down", "degraded"):
                from datetime import timedelta
                cooldown_until = (
                    datetime.now().astimezone() + timedelta(seconds=cooldown_seconds)
                ).isoformat(timespec="seconds")

            _db.update_dynamic_proxy_provider(
                provider_id,
                last_health_status=result.status,
                last_health_checked_at=_db.now_iso(),
                last_error_message=result.error_message,
                cooldown_until=cooldown_until,
            )

            self._send_json({
                "ok": True,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error_message": result.error_message,
                "response_code": result.response_code,
                "cooldown_until": cooldown_until,
            })
        except Exception:
            _log.error("动态代理健康检查异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_candidates_preview(self, provider_id: int):
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            rows = _db.get_proxy_candidate_by_provider(provider_id, valid_only=False)
            preview = []
            status_counts: dict[str, int] = {}
            latency_values: list[int] = []
            score_values: list[float] = []
            for row in rows[:10]:
                preview.append({
                    "id": row.get("id"),
                    "candidate_key": row.get("candidate_key"),
                    "protocol": row.get("protocol"),
                    "host": row.get("host"),
                    "port": row.get("port"),
                    "masked_proxy_endpoint": row.get("masked_proxy_endpoint"),
                    "last_probe_status": row.get("last_probe_status"),
                    "score": row.get("score", 0.0),
                })
            for row in rows:
                status = row.get("last_probe_status") or "unknown"
                status_counts[status] = status_counts.get(status, 0) + 1
                latency = row.get("latency_ms")
                if isinstance(latency, int):
                    latency_values.append(latency)
                score = row.get("score")
                if isinstance(score, (int, float)):
                    score_values.append(float(score))
            latency_summary = {
                "count": len(latency_values),
                "min_ms": min(latency_values) if latency_values else None,
                "max_ms": max(latency_values) if latency_values else None,
            }
            score_summary = {
                "count": len(score_values),
                "min_score": min(score_values) if score_values else None,
                "max_score": max(score_values) if score_values else None,
            }
            top_candidate = _db.pick_healthy_fastest_top_candidate(rows)
            self._send_json({
                "provider_id": provider_id,
                "provider_name": existing.get("name", ""),
                "preview": preview,
                "total_count": len(rows),
                "status_counts": status_counts,
                "latency_summary": latency_summary,
                "score_summary": score_summary,
                "top_candidate": top_candidate,
            })
        except Exception:
            _log.error("动态代理候选预览异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_refresh(self, provider_id: int):
        try:
            existing = _db.get_dynamic_proxy_provider(provider_id)
            if not existing:
                self._send_json({"error": "提供方不存在"}, 404)
                return
            result = _scheduler.refresh_dynamic_provider(provider_id)
            self._send_json(result)
        except Exception:
            _log.error("动态代理提供方手动刷新异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_dynamic_provider_cooldown_clear(self, provider_id: int):
        try:
            _db.update_dynamic_proxy_provider(
                provider_id,
                cooldown_until=None,
                last_health_status="healthy",
                last_health_checked_at=_db.now_iso(),
                last_error_message=None,
            )
            self._send_json({"ok": True})
        except Exception:
            _log.error("清除代理提供方冷却异常", exc_info=True)
            self._send_json({"error": "操作失败，请查看服务器日志"}, 400)

    def _api_routing_preview(self):
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)

        try:
            raw_account_id = params.get("account_id", [None])[0]
            if raw_account_id in (None, "", "0"):
                raise ValueError("missing")
            account_id = int(raw_account_id)
        except (ValueError, TypeError):
            self._send_json({"error": "account_id 必填且必须为整数"}, 400)
            return

        is_auto_download = params.get("auto", ["0"])[0] in ("1", "true")
        cookies_present = params.get("cookies", ["0"])[0] in ("1", "true")
        user_forced_direct = params.get("direct", ["0"])[0] in ("1", "true")

        account = _db.get_account(account_id)
        if not account:
            self._send_json({"error": "账户不存在"}, 404)
            return

        if user_forced_direct:
            from monitor.proxy_router import ProxyRouteResult
            route = ProxyRouteResult(
                resolved_mode="direct",
                proxy=None,
                proxy_pool=None,
                provider_name=None,
                provider_tier=None,
                resolved_proxy_source="direct",
                reason="用户显式指定直连",
                warnings=[],
                fallback_depth=0,
                masked_proxy_endpoint=None,
                session_mode=None,
                cookies_file_present=cookies_present,
            )
        else:
            from monitor.dynamic_provider_resolver import resolve_for_manual_download, resolve_for_auto_download
            if is_auto_download:
                route = resolve_for_auto_download(account_id)
            else:
                route = resolve_for_manual_download(account_id, cookies_present)

        self._send_json({
            "account_id": account_id,
            "account_name": account.get("name", ""),
            "download_proxy_mode": account.get("download_proxy_mode", "auto"),
            "is_auto_download": is_auto_download,
            "cookies_present": cookies_present,
            "user_forced_direct": user_forced_direct,
            "routing": {
                "resolved_mode": route.resolved_mode,
                "resolved_proxy_source": route.resolved_proxy_source,
                "provider_name": route.provider_name,
                "provider_tier": route.provider_tier,
                "masked_proxy_endpoint": route.masked_proxy_endpoint,
                "session_mode": route.session_mode,
                "fallback_depth": route.fallback_depth,
                "reason": route.reason,
                "warnings": route.warnings,
            },
        })

    def _api_account_videos(self, acc_id: str):
        try:
            acc_id_int = int(acc_id)
        except ValueError:
            self._send_json({"error": "无效账户 ID"}, 400)
            return

        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = parse_qs(qs)

        title_kw = params.get("title_kw", [None])[0] or None
        url_kw   = params.get("url_kw",   [None])[0] or None
        sort_by   = params.get("sort_by",   ["published_at"])[0]
        sort_dir  = params.get("sort_dir",  ["desc"])[0]
        page      = int(params.get("page",  ["1"])[0])
        page_size = int(params.get("page_size", ["20"])[0])
        status    = params.get("status", [None])[0] or None

        if status:
            videos = _db.get_account_videos_filtered(acc_id_int, status)
            total = len(videos)
            self._send_json({
                "videos": videos,
                "total": total,
                "page": 1,
                "page_size": total,
                "pages": 1,
            })
        else:
            videos, total = _db.get_account_videos(
                account_id=acc_id_int,
                title_kw=title_kw,
                url_kw=url_kw,
                sort_by=sort_by,
                sort_dir=sort_dir,
                page=page,
                page_size=min(page_size, 100),
            )
            self._send_json({
                "videos": videos,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            })

    def _api_account_videos_batch_download(self, acc_id: str, body: dict):
        video_ids = body.get("video_ids", [])
        if not isinstance(video_ids, list):
            self._send_json({"error": "video_ids 必须为数组"}, 400)
            return
        for vid in video_ids:
            if not isinstance(vid, int):
                self._send_json({"error": "video_ids 数组元素必须为整数"}, 400)
                return
        if not video_ids:
            self._send_json({"error": "未选择视频"}, 400)
            return

        cfg = _db.load_config()
        try:
            abs_output = _resolve_download_output_path(body.get("output_path", ""), cfg)
        except ValueError as ex:
            self._send_json({"error": str(ex)}, 400)
            return

        video_records = _db.get_videos_by_ids(video_ids)
        if not video_records:
            self._send_json({"error": "未找到视频记录"}, 404)
            return

        urls = [v["url"] for v in video_records if v.get("url")]
        if not urls:
            self._send_json({"error": "视频记录中无有效 URL"}, 400)
            return

        account = _db.get_account(int(acc_id))
        if not account:
            self._send_json({"error": "账户不存在"}, 404)
            return

        user_forced_direct = bool(body.get("direct", False))
        cookies_file = _resolve_cookies_file(body.get("cookies_file"), cfg)
        cookies_present = bool(cookies_file)

        route = resolve_for_manual_download(int(acc_id), cookies_present)

        if user_forced_direct:
            from monitor.proxy_router import ProxyRouteResult
            route = ProxyRouteResult(
                resolved_mode="direct",
                proxy=None,
                proxy_pool=None,
                provider_name=None,
                provider_tier=None,
                resolved_proxy_source="direct",
                reason="用户显式指定直连",
                warnings=[],
                fallback_depth=0,
                masked_proxy_endpoint=None,
                session_mode=None,
                cookies_file_present=cookies_present,
            )

        direct_fallback_after_proxies = bool(cfg.get("manual_direct_fallback", True)) and not user_forced_direct

        log_download_decision(
            route_result=route,
            account_id=int(acc_id),
            account_name=account.get("name", ""),
            video_count=len(urls),
            is_auto_download=False,
        )

        _log.info(
            f"[Manual Download] account={acc_id} route={route.resolved_proxy_source} "
            f"provider={route.provider_name or 'N/A'} reason={route.reason} "
            f"proxy={route.masked_proxy_endpoint or 'direct'}"
        )

        if route.resolved_mode == "failed":
            self._send_json({
                "ok": False,
                "error": route.reason,
                "routing": {
                    "source": route.resolved_proxy_source,
                    "provider": route.provider_name,
                    "masked_endpoint": route.masked_proxy_endpoint,
                    "reason": route.reason,
                    "warnings": route.warnings,
                    "session_mode": route.session_mode,
                },
            }, 400)
            return

        resolved_proxy, resolved_proxy_pool = _route_to_download_targets(route)

        task_id = _task_mgr.create_task(video_records, abs_output)
        _log.info(
            f"创建下载任务: task_id={task_id} 视频数={len(urls)} "
            f"输出={abs_output} 路由={route.resolved_proxy_source}"
        )

        _db.update_videos_download_status(video_ids, "downloading")

        sub_langs = body.get("sub_langs")
        no_subs = body.get("no_subs", True)
        enable_aria2 = bool(cfg.get("enable_aria2", False))
        extra_ydl_opts = build_aria2_opts(None) if enable_aria2 else None

        def _bg_download():
            try:
                def progress_cb(progress, status_text):
                    completed = int(progress * len(urls))
                    _task_mgr.update_progress(task_id, completed, status_text)

                results = batch_download(
                    urls,
                    abs_output,
                    'best',
                    proxy=resolved_proxy,
                    proxy_pool=resolved_proxy_pool,
                    progress_callback=progress_cb,
                    sub_langs=sub_langs if not no_subs else None,
                    no_subs=no_subs,
                    cookies_file=cookies_file,
                    extra_ydl_opts=extra_ydl_opts,
                    direct_fallback_after_proxies_exhausted=direct_fallback_after_proxies,
                    should_cancel=lambda: _task_mgr.is_cancel_requested(task_id),
                )

                _task_mgr.finish_task(task_id, results)

                url_to_vid = {v["url"]: v["id"] for v in video_records}
                now_str = _db.now_iso()
                success_cnt = 0
                fail_cnt = 0
                for r in results:
                    vid = url_to_vid.get(r.get("url"))
                    if not vid:
                        continue
                    if r.get("状态") == "成功":
                        file_path = r.get("video_path") or abs_output
                        _db.update_videos_download_status(
                            [vid], "downloaded",
                            download_at=now_str,
                            download_path=file_path,
                        )
                        success_cnt += 1
                    else:
                        _db.update_videos_download_status(
                            [vid], "failed",
                            download_error="yt-dlp 下载失败",
                        )
                        fail_cnt += 1

                _log.info(f"下载任务完成: task_id={task_id} 成功={success_cnt} 失败={fail_cnt}")

            except BatchDownloadCancelled as ex:
                _task_mgr.cancel_task(task_id, getattr(ex, "results", []), str(ex))
                _db.update_videos_download_status(video_ids, "failed", download_error="下载任务已取消")
            except Exception as e:
                _task_mgr.fail_task(task_id, str(e))
                _db.update_videos_download_status(video_ids, "failed", download_error=str(e))
                _log.error(f"下载任务异常: task_id={task_id} error={e}")

        threading.Thread(target=_bg_download, daemon=True).start()

        self._send_json({
            "ok": True,
            "task_id": task_id,
            "queued": len(urls),
            "total": len(urls),
            "message": f"{len(urls)} 个视频已开始下载",
            "routing": {
                "source": route.resolved_proxy_source,
                "provider": route.provider_name,
                "provider_tier": route.provider_tier,
                "masked_endpoint": route.masked_proxy_endpoint,
                "reason": route.reason,
                "warnings": route.warnings,
                "session_mode": route.session_mode,
            },
        })

    def _api_download_task_status(self, task_id: str):
        task = _task_mgr.get_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json({
            "task_id": task["task_id"],
            "status": task["status"],
            "total": task["total"],
            "completed": task["completed"],
            "success": task["success"],
            "failed": task["failed"],
            "current_video": task.get("current_video", ""),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "finished_at": task.get("finished_at"),
        })

    # ── Batch Download API ─────────────────────────────────────

    def _handle_multipart_upload(self):
        """POST /api/batch/upload — 接收上传的 Excel/CSV/TXT 文件，解析 URL 列表。"""
        try:
            file_part = read_single_file_part(self.rfile, self.headers, field_name="file")
            if file_part is None:
                self._send_json({"ok": False, "error": "未上传文件"}, 400)
                return

            filename = file_part.filename or "upload"
            data = file_part.data
            if not data:
                self._send_json({"ok": False, "error": "文件为空"}, 400)
                return

            suffix = Path(filename).suffix
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, mode="wb"
            ) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                from Youtube_Downloader import read_urls_from_file
                urls = read_urls_from_file(tmp_path)
                if not isinstance(urls, list) or not urls:
                    self._send_json({"ok": False, "error": "文件中未找到有效 URL"}, 400)
                    return
                upload_id = _batch_upload_mgr.create_upload(filename, urls)
                preview = urls[:5]
                self._send_json({
                    "ok": True,
                    "upload_id": upload_id,
                    "filename": filename,
                    "url_count": len(urls),
                    "preview_urls": preview,
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except MultipartParseError as ex:
            self._send_json({"ok": False, "error": str(ex)}, 400)
        except Exception as ex:
            self._send_json({"ok": False, "error": str(ex)}, 500)

    def _api_batch_download_start(self, body: dict):
        upload_id = (body.get("upload_id") or "").strip()
        if not upload_id:
            self._send_json({"error": "upload_id 不能为空"}, 400)
            return
        upload = _batch_upload_mgr.get_upload(upload_id)
        if not upload:
            self._send_json({"error": "上传会话不存在或已过期，请重新上传文件"}, 400)
            return
        urls = upload.get("urls", [])
        if not isinstance(urls, list) or not urls:
            self._send_json({"error": "上传会话中无有效 URL，请重新上传文件"}, 400)
            return
        filename = upload.get("filename") or "upload"

        cfg = _db.load_config()
        try:
            abs_output = _resolve_download_output_path(body.get("output_path", ""), cfg)
        except ValueError as ex:
            self._send_json({"error": str(ex)}, 400)
            return

        cookies_file = _resolve_cookies_file(body.get("cookies_file"), cfg)

        resolution = body.get("resolution", "best")
        no_subs = bool(body.get("no_subs", False))
        sub_langs = body.get("sub_langs", "zh-Hans,en") if not no_subs else None
        user_forced_direct = bool(body.get("direct", False))

        proxy_pool_id_raw = body.get("proxy_pool_id")
        proxy_pool_id: int | None = None
        if proxy_pool_id_raw not in (None, ""):
            try:
                proxy_pool_id = int(proxy_pool_id_raw)
            except (TypeError, ValueError):
                self._send_json({"error": "proxy_pool_id 必须为整数"}, 400)
                return
            if proxy_pool_id <= 0:
                self._send_json({"error": "proxy_pool_id 必须为正整数"}, 400)
                return

        route = resolve_for_web_batch_download(
            proxy_pool_id=proxy_pool_id,
            cookies_file_present=bool(cookies_file),
            user_forced_direct=user_forced_direct,
        )
        if route.resolved_mode == "failed":
            self._send_json({
                "ok": False,
                "error": route.reason,
                "routing": {
                    "source": route.resolved_proxy_source,
                    "provider": route.provider_name,
                    "masked_endpoint": route.masked_proxy_endpoint,
                    "reason": route.reason,
                    "warnings": route.warnings,
                    "session_mode": route.session_mode,
                },
            }, 400)
            return

        log_download_decision(
            route_result=route,
            account_id=None,
            account_name=_WEB_BATCH_ACCOUNT_NAME,
            video_count=len(urls),
            is_auto_download=False,
        )

        _log.info(
            f"[Web Batch Download] upload={upload_id} file={filename} route={route.resolved_proxy_source} "
            f"provider={route.provider_name or 'N/A'} reason={route.reason}"
        )

        resolved_proxy, resolved_proxy_pool = _route_to_download_targets(route)

        enable_aria2 = bool(cfg.get("enable_aria2", False))
        extra_ydl_opts = build_aria2_opts(None) if enable_aria2 else None

        video_records = [{"url": u} for u in urls]
        task_id = _task_mgr.create_task(
            video_records,
            abs_output,
            task_kind="web_batch",
            source_name=filename,
            persist_task=True,
        )
        # 保存 URLs 到任务记录，供重开使用
        task = _task_mgr._tasks.get(task_id)
        if task:
            task["urls"] = urls
            _task_mgr._persist_task_locked(task)
        direct_fallback_after_proxies = bool(cfg.get("manual_direct_fallback", True)) and not (
            user_forced_direct or proxy_pool_id is not None
        )

        def progress_wrapper(progress: float, status: str):
            _task_mgr.update_progress(task_id, int(progress * len(urls)), status)

        def run():
            try:
                results = batch_download(
                    urls,
                    abs_output,
                    resolution,
                    proxy=resolved_proxy,
                    proxy_pool=resolved_proxy_pool,
                    progress_callback=progress_wrapper,
                    sub_langs=sub_langs,
                    no_subs=no_subs,
                    cookies_file=cookies_file,
                    extra_ydl_opts=extra_ydl_opts,
                    direct_fallback_after_proxies_exhausted=direct_fallback_after_proxies,
                    should_cancel=lambda: _task_mgr.is_cancel_requested(task_id),
                )
                _task_mgr.finish_task(task_id, results)
            except BatchDownloadCancelled as ex:
                _task_mgr.cancel_task(task_id, getattr(ex, "results", []), str(ex))
            except Exception as ex:
                _task_mgr.fail_task(task_id, str(ex))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._send_json({
            "ok": True,
            "task_id": task_id,
            "queued": len(urls),
            "upload_id": upload_id,
        })

    def _api_batch_tasks_list(self):
        tasks = _db.list_web_batch_tasks(limit=50)
        self._send_json({"tasks": [_serialize_batch_task(task, include_results=False) for task in tasks]})

    def _api_batch_task_status(self, task_id: str):
        task = _task_mgr.get_task(task_id)
        if not task or task.get("task_kind") != "web_batch":
            task = _db.get_web_batch_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        self._send_json(_serialize_batch_task(task, include_results=True))

    def _api_batch_task_cancel(self, task_id: str):
        task = _task_mgr.request_cancel(task_id)
        if not task:
            persisted = _db.get_web_batch_task(task_id)
            if not persisted:
                self._send_json({"error": "任务不存在"}, 404)
                return
            self._send_json({
                "ok": False,
                "error": "任务当前未运行，无法取消",
                "task": _serialize_batch_task(persisted, include_results=False),
            }, 409)
            return
        self._send_json({
            "ok": True,
            "task_id": task_id,
            "status": task.get("status"),
            "cancel_requested": True,
            "message": task.get("cancel_message") or "正在取消下载任务…",
        })

    def _api_batch_task_restart(self, task_id: str):
        """使用已存储的 URLs 重新启动已完成/失败的任务"""
        task = _db.get_web_batch_task(task_id)
        if not task:
            self._send_json({"error": "任务不存在"}, 404)
            return
        if task.get("status") == "running":
            self._send_json({"error": "任务正在运行中，无法重开"}, 400)
            return
        urls = task.get("urls", [])
        if not urls:
            self._send_json({"error": "任务无存储的 URL，请重新上传文件"}, 400)
            return

        filename = task.get("source_name") or "re-download"
        output_path = task.get("output_path") or ""
        cfg = _db.load_config()
        try:
            abs_output = _resolve_download_output_path(output_path, cfg)
        except ValueError as ex:
            self._send_json({"error": str(ex)}, 400)
            return

        route = resolve_for_web_batch_download(
            proxy_pool_id=None,
            cookies_file_present=False,
            user_forced_direct=False,
        )
        resolved_proxy, resolved_proxy_pool = _route_to_download_targets(route)
        enable_aria2 = bool(cfg.get("enable_aria2", False))
        extra_ydl_opts = build_aria2_opts(None) if enable_aria2 else None
        direct_fallback_after_proxies = bool(cfg.get("manual_direct_fallback", True))

        video_records = [{"url": u} for u in urls]
        new_task_id = _task_mgr.create_task(
            video_records,
            abs_output,
            task_kind="web_batch",
            source_name=filename + " (重开)",
            persist_task=True,
        )
        new_task = _task_mgr._tasks.get(new_task_id)
        if new_task:
            new_task["urls"] = urls
            _task_mgr._persist_task_locked(new_task)

        def progress_wrapper(progress: float, status: str):
            _task_mgr.update_progress(new_task_id, int(progress * len(urls)), status)

        def run():
            try:
                results = batch_download(
                    urls,
                    abs_output,
                    "best",
                    proxy=resolved_proxy,
                    proxy_pool=resolved_proxy_pool,
                    progress_callback=progress_wrapper,
                    sub_langs=None,
                    no_subs=True,
                    cookies_file=None,
                    extra_ydl_opts=extra_ydl_opts,
                    direct_fallback_after_proxies_exhausted=direct_fallback_after_proxies,
                    should_cancel=lambda: _task_mgr.is_cancel_requested(new_task_id),
                )
                _task_mgr.finish_task(new_task_id, results)
            except BatchDownloadCancelled as ex:
                _task_mgr.cancel_task(new_task_id, getattr(ex, "results", []), str(ex))
            except Exception as ex:
                _task_mgr.fail_task(new_task_id, str(ex))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._send_json({
            "ok": True,
            "task_id": new_task_id,
            "queued": len(urls),
        })

    # ── Go 代理 API 转发 ────────────────────────────────────────

    def _api_proxy_enable(self):
        """POST /api/proxy/enable — 启动 Go 子进程。"""
        mgr = get_proxy_manager()
        if mgr.is_running:
            self._send_json({"ok": True, "message": "already running"})
            return
        try:
            mgr.start()
            self._send_json({"ok": True})
        except RuntimeError as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _api_proxy_disable(self):
        """POST /api/proxy/disable — 停止 Go 子进程，同时清除系统代理。"""
        import urllib.request
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"ok": True, "message": "not running"})
            return
        # 先清除系统代理（Windows 注册表），避免进程退出后残留
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{mgr.proxy_port}/api/proxy-unset",
                data=b"",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass  # Go 进程可能已卡死，忽略 unset 错误
        mgr.stop()
        self._send_json({"ok": True})

    def _api_proxy_status(self):
        """GET /api/proxy/status — 获取代理运行状态。"""
        import urllib.request
        # 从 config 读取端口，与 go_proxy_manager.get_proxy_manager() 保持一致
        try:
            from config.settings import load_config
            cfg = load_config()
            proxy_port = int(cfg.get("proxy_sniffer_port") or 8899)
        except Exception:
            proxy_port = 8899
        # 直接通过健康检查确认 Go 服务是否在响应
        # 不依赖 subprocess wrapper，因为 Go 可能被外部启动
        running = False
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{proxy_port}/health", timeout=2
            )
            running = True
        except Exception:
            pass
        self._send_json({
            "running": running,
            "port": proxy_port,
        })

    def _api_proxy_config_get(self):
        """GET /api/proxy/config — 获取 Go 侧配置。"""
        import urllib.request
        import json as _json
        mgr = get_proxy_manager()
        try:
            with urllib.request.urlopen(
                f"{mgr.api_base}/api/get-config", timeout=5
            ) as r:
                self._send_json(_json.loads(r.read()))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_proxy_config_update(self, body):
        """POST /api/proxy/config — 更新 Go 侧配置。"""
        import urllib.request
        import json as _json
        mgr = get_proxy_manager()
        try:
            body_bytes = _json.dumps(body or {}).encode("utf-8")
            req = urllib.request.Request(
                f"{mgr.api_base}/api/set-config",
                data=body_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                self._send_json(_json.loads(r.read()))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_proxy_download(self, body):
        """POST /api/proxy/download — 触发下载任务。"""
        import urllib.request
        import json as _json
        mgr = get_proxy_manager()
        try:
            payload = {
                "url": (body or {}).get("url", ""),
                "output_path": (body or {}).get("output_path", ""),
            }
            body_bytes = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{mgr.api_base}/api/download",
                data=body_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                self._send_json(_json.loads(r.read()))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_proxy_system_proxy(self, body):
        """POST /api/proxy/system-proxy — 设置/取消系统代理。"""
        import urllib.request
        import json as _json
        mgr = get_proxy_manager()
        action = (body or {}).get("action", "")
        subpath = "proxy-open" if action == "open" else "proxy-unset" if action == "unset" else ""
        if not subpath:
            self._send_json({"error": "invalid action"}, 400)
            return
        # 未运行时先启动
        if not mgr.is_running:
            try:
                mgr.start()
            except Exception as e:
                self._send_json({"error": f"启动代理失败: {e}"}, 500)
                return
        try:
            # POST 请求必须传 data=b''，否则 urlopen 发送的是 GET
            req = urllib.request.Request(
                f"{mgr.api_base}/api/{subpath}",
                data=b"",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                self._send_json(_json.loads(r.read()))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_proxy_cert_install(self):
        """POST /api/proxy/cert/install — 安装 CA 证书。"""
        import urllib.request
        import json as _json
        mgr = get_proxy_manager()
        try:
            req = urllib.request.Request(
                f"{mgr.api_base}/api/install",
                data=b"",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                self._send_json(_json.loads(r.read()))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    # ── 资源嗅探 API ──────────────────────────────────────────

    def _api_res_clear(self):
        """POST /api/res/clear — 清空资源列表。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        try:
            self._send_json(mgr.clear_resources())
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_delete(self, body):
        """POST /api/res/delete — 删除指定资源。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        signs = (body or {}).get("sign", []) if body else []
        try:
            self._send_json(mgr.delete_resources(signs))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_set_type(self, body):
        """POST /api/res/set-type — 设置资源类型过滤。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        types = (body or {}).get("type", "") if body else ""
        try:
            self._send_json(mgr.set_resource_type(types))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_download(self, body):
        """POST /api/res/download — 下载资源（含解密）。

        有 DecodeKey（微信加密视频）→ Go 代理下载（支持解密）。
        无 DecodeKey（B站等通用视频）→ yt-dlp 批量下载。
        """
        import urllib.request
        import json as _json

        body = body or {}
        decode_key = body.get("DecodeKey", "")

        if decode_key:
            # 微信加密视频 → 走 Go 代理解密下载
            mgr = get_proxy_manager()
            if not mgr.is_running:
                self._send_json({"error": "proxy not running"}, 503)
                return
            try:
                url = f"{mgr.api_base}/api/download"
                payload = _json.dumps(body).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._send_json(_json.loads(r.read()))
            except Exception as e:
                self._send_json({"error": str(e)}, 502)
            return

        # ── 通用视频 → yt-dlp 下载 ────────────────────────────────
        video_url = body.get("Url", "").strip()
        if not video_url:
            self._send_json({"error": "url is required"}, 400)
            return

        # 解析输出目录：优先用 SavePath，否则用配置
        cfg = _db.load_config()
        requested_output = body.get("SavePath", "") or ""
        try:
            output_path = _resolve_download_output_path(requested_output, cfg)
        except ValueError as ex:
            self._send_json({"error": str(ex)}, 400)
            return

        # Bilibili CDN segment URL 立即过期，从 OtherData["referer"] 直接提取 BVID，
        # 构造视频页面 URL 供 yt-dlp 使用（yt-dlp 可自动重试并获取最新 CDN URL）
        download_url = video_url
        _referer = body.get("OtherData", {}).get("referer", "")
        if "bilivideo.com" in video_url or ".bili" in video_url.lower():
            if _referer:
                # BVID = "BV" + 10 alphanumeric chars (total 12)
                bvid_match = re.search(r'/video/(BV[a-zA-Z0-9]{10})', _referer)
                if bvid_match:
                    page_url = "https://www.bilibili.com/video/" + bvid_match.group(1)
                    download_url = page_url
                    _log.info(f"[res-download] Bilibili CDN URL detected, using page URL: {page_url}")

        # 后台线程执行 yt-dlp 下载，避免阻塞 HTTP 请求
        def _bg_yt_dlp():
            try:
                batch_download(
                    [download_url],
                    output_path,
                    resolution="best",
                    extra_ydl_opts=build_aria2_opts(None),
                )
            except Exception:
                pass

        threading.Thread(target=_bg_yt_dlp, daemon=True).start()
        self._send_json({"code": 1, "message": "下载任务已提交"})

    def _api_res_cancel(self, body):
        """POST /api/res/cancel — 取消下载。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        task_id = (body or {}).get("id", "") if body else ""
        try:
            self._send_json(mgr.cancel_download(task_id))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_decode(self, body):
        """POST /api/res/decode — 解密微信加密文件。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        media_info = (body or {}).get("MediaInfo", {}) if body else {}
        filename = (body or {}).get("Filename", "") if body else ""
        decode_str = (body or {}).get("DecodeStr", "") if body else ""
        try:
            self._send_json(mgr.wx_file_decode(media_info, filename, decode_str))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_export(self, body):
        """POST /api/res/export — 批量导出资源列表。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        content = (body or {}).get("content", "") if body else ""
        try:
            self._send_json(mgr.batch_export(content))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_open_folder(self, body):
        """POST /api/res/open-folder — 打开下载目录。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            self._send_json({"error": "proxy not running"}, 503)
            return
        file_path = (body or {}).get("filePath", "") if body else ""
        try:
            self._send_json(mgr.open_folder(file_path))
        except Exception as e:
            self._send_json({"error": str(e)}, 502)

    def _api_res_events_stream(self):
        """GET /api/res-events — SSE 流式推送资源事件。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()

        _log.info("[SSE] Client connected to /api/res-events")
        mgr = get_proxy_manager()
        import json as _json
        try:
            while True:
                event = mgr.get_event(timeout=30.0)
                if event is not None:
                    # _log.debug("[SSE] dispatching event: %s", str(event))
                    data = _json.dumps(event).encode("utf-8")
                    self.wfile.write(b"data: ")
                    self.wfile.write(data)
                    self.wfile.write(b"\n\n")
                    self.wfile.flush()
                else:
                    # 心跳（保持连接活跃）
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, OSError) as e:
            _log.info("[SSE] Client disconnected: %s", e)

    def _api_res_preview(self):
        """GET /api/res/preview?url=... — 代理原始媒体 URL 用于预览。"""
        mgr = get_proxy_manager()
        if not mgr.is_running:
            _log.warning("[preview] proxy not running")
            self.send_error(503, "proxy not running")
            return
        from urllib.parse import unquote, parse_qs, urlparse, quote
        raw_url = unquote(parse_qs(urlparse(self.path).query).get("url", [""])[0])
        if not raw_url:
            self.send_error(400, "missing url parameter")
            return
        upstream_url = f"{mgr.api_base}/api/preview?url={quote(raw_url, safe='')}"

        try:
            import urllib.request as _ur
            # 透传关键认证头（Bilibili 等需要）
            req = _ur.Request(upstream_url, method="GET")
            for h in ("Range", "Referer", "User-Agent", "Cookie", "Origin"):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)
            with _ur.urlopen(req, timeout=30) as resp:
                # 透传响应头（Content-Type, Content-Length, Accept-Ranges 等）
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection", "keep-alive"):
                        self.send_header(k, v)
                self.end_headers()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception as e:
            _log.warning("[preview] failed to proxy %s: %s", raw_url[:80], e)
            try:
                self.send_error(502, repr(e))
            except Exception:
                pass

    def _api_res_preview_encrypted(self):
        """GET /api/res/preview/encrypted?url=...&decodeKey=... — 下载并解密加密媒体。

        工作流：
        1. 通过 Go 的 /api/preview 代理下载加密文件到内存
        2. 用 Node.js 运行 isaac_keygen.js 生成 ISAAC-64 密钥流
        3. 在 Python 侧对前 131072 字节做 XOR 解密
        4. 将解密后的数据流式返回给浏览器
        """
        mgr = get_proxy_manager()
        if not mgr.is_running:
            _log.warning("[preview:enc] proxy not running")
            self.send_error(503, "proxy not running")
            return
        from urllib.parse import unquote, parse_qs, urlparse, quote
        params = parse_qs(urlparse(self.path).query)
        raw_url = unquote(params.get("url", [""])[0])
        decode_key = unquote(params.get("decodeKey", [""])[0])
        if not raw_url:
            self.send_error(400, "missing url parameter")
            return
        if not decode_key:
            self.send_error(400, "missing decodeKey parameter")
            return

        # Step 1: Generate ISAAC-64 keystream via Node.js subprocess
        import subprocess
        _keygen_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "monitor_web", "js", "isaac_keygen.js",
        )
        try:
            keygen_result = subprocess.run(
                ["node", _keygen_script, decode_key],
                capture_output=True, timeout=15,
            )
            if keygen_result.returncode != 0:
                _log.warning("[preview:enc] keygen failed: %s", keygen_result.stderr)
                self.send_error(500, "ISAAC keygen failed")
                return
            import base64
            keystream = base64.b64decode(keygen_result.stdout.strip())
            if len(keystream) < 1024:
                _log.warning("[preview:enc] keygen returned too few bytes: %d", len(keystream))
                self.send_error(500, "ISAAC keygen returned too few bytes")
                return
        except FileNotFoundError:
            _log.error("[preview:enc] Node.js not found")
            self.send_error(500, "Node.js not found")
            return
        except subprocess.TimeoutExpired:
            _log.error("[preview:enc] keygen timed out")
            self.send_error(500, "ISAAC keygen timed out")
            return
        except Exception as e:
            _log.error("[preview:enc] keygen error: %s", e)
            self.send_error(500, "ISAAC keygen error")
            return

        # Step 2: Download encrypted file via Go's plain /api/preview proxy
        try:
            import urllib.request as _ur
            proxy_url = f"{mgr.api_base}/api/preview?url={quote(raw_url, safe='')}"
            req = _ur.Request(proxy_url, method="GET")
            for h in ("Referer", "User-Agent", "Cookie", "Origin"):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)

            with _ur.urlopen(req, timeout=60) as resp:
                encrypted_data = resp.read()
        except Exception as e:
            _log.warning("[preview:enc] download failed: %s", e)
            try:
                self.send_error(502, "Failed to download encrypted file")
            except Exception:
                pass
            return

        # Step 3: XOR decrypt the first len(keystream) bytes
        data_arr = bytearray(encrypted_data)
        ks_len = len(keystream)
        decrypt_len = min(ks_len, len(data_arr))
        for i in range(decrypt_len):
            data_arr[i] ^= keystream[i]

        # Step 4: Stream decrypted data to browser
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data_arr)))
        self.send_header("Content-Disposition", "inline")
        self.send_header("Accept-Ranges", "none")
        origin = self._allowed_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        try:
            self.wfile.write(bytes(data_arr))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    # ── 静态文件服务覆盖 ──────────────────────────────────────

    def translate_path(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        from urllib.parse import urlparse, unquote
        rel = unquote(urlparse(path).path).lstrip("/")
        candidate = (_STATIC_DIR / rel).resolve()
        static_root = _STATIC_DIR.resolve()
        if candidate != static_root and static_root not in candidate.parents:
            return str(static_root / "index.html")
        return str(candidate)


def serve(port: int = 5000):
    os.makedirs(_STATIC_DIR, exist_ok=True)
    if not _INDEX_HTML.exists():
        _log.error(f"index.html not found at {_STATIC_DIR}")
        _INDEX_HTML.write_text("<html><body><h1>UI not found</h1></body></html>", encoding="utf-8")
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
        """支持并发的 HTTPServer（每请求一个线程）"""
        daemon_threads = True
    server = ThreadedHTTPServer(("127.0.0.1", port), MonitorHandler)
    print(f"\n🌐 监控 Web UI: http://127.0.0.1:{port}")
    print("   按 Ctrl+C 停止\n")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="YouTube Monitor Web Server")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _db.init_db()
    _db.ensure_app_state_table()

    # Restore interrupted article tasks from previous server restart
    running_tasks, total = _db.list_article_tasks(status="running")
    if running_tasks:
        for task in running_tasks:
            _db.update_article_task(
                task["id"],
                status="interrupted",
                error="服务重启导致任务中断",
            )
        _log.info(f"[startup] {len(running_tasks)} 个 running 任务已标记为 interrupted")
    weread_interrupted = _weread_export_service.mark_incomplete_tasks_interrupted()
    if weread_interrupted:
        _log.info("[startup] %s 个微信读书导出任务已标记为 interrupted", weread_interrupted)

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    serve(args.port)


if __name__ == "__main__":
    main()



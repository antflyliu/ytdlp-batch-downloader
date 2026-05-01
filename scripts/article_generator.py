"""Article generation workflow for monitored or downloaded videos.

The P0 workflow is intentionally polling-friendly: each stage persists progress
to SQLite and writes large artifacts to a task output directory.
"""
from __future__ import annotations

import gc
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse, urlunparse

import requests

import logging_config
import monitor.db as db
import monitor.proxy.router as proxy_router
from monitor.video_paths import resolve_downloaded_video_path
from scripts.llm_client import PROMPT_INPUT_PLACEHOLDER, create_llm_client

_log = logging_config.get_logger("article_generator")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SUBTITLE_EXTENSIONS = (".srt", ".vtt", ".txt")
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_LLM_THINKING_BLOCK_RE = re.compile(r"<(think|thinking)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_LEADING_LLM_THINKING_RE = re.compile(r"^\s*<(?:think|thinking)\b", re.IGNORECASE)
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S")
_NETWORK_ERROR_KEYWORDS = (
    "429",
    "Too Many Requests",
    "500",
    "502",
    "503",
    "504",
    "ConnectionError",
    "Connection refused",
    "timed out",
    "timeout",
    "HTTP Error",
    "Temporary failure",
    "Unable to download",
    "WinError",
    "Remote end closed connection",
    "EOF",
    "proxy",
    "Proxy",
    "socks",
    "SOCKS",
)
_MISSING_SUBTITLE_KEYWORDS = (
    "was not able to extract",
    "There are no subtitles",
    "No subtitles",
    "No automatic captions",
    "This video has no subtitles",
)
_DEFAULT_WECHAT_PROMPT_ROLE = "资深科技自媒体作者"
_DEFAULT_WECHAT_PROMPT_READER = "关注 AI、效率工具和内容创作的中文读者"
_DEFAULT_WECHAT_PROMPT_STYLE = "信息密度高、短段落、有明确小标题，保留必要的列表、表格和代码块"
_ARTICLE_PROMPT_PIPELINE_VERSION = "wechat-style-score-v1"
_LOCAL_WHISPER_AUTO_COMPUTE_TYPES = ("int8", "int8_float32", "float32")
_LOCAL_WHISPER_EXPLICIT_FALLBACK_COMPUTE_TYPES = ("float32", "int8", "int8_float32")
_LOCAL_WHISPER_CUDA_LOW_VRAM_COMPUTE_TYPES = ("int8", "int8_float32")
_LOCAL_WHISPER_CUDA_COMPUTE_TYPES = ("int8", "int8_float32", "float32")
_DEFAULT_LOCAL_WHISPER_CHUNK_SECONDS = 45
_MIN_LOCAL_WHISPER_CHUNK_SECONDS = 30
_MAX_LOCAL_WHISPER_CHUNK_SECONDS = 60
_LOW_VRAM_GPU_TOTAL_MB = 3072
_LOW_VRAM_GPU_FREE_MB = 1536
_LOCAL_WHISPER_COMPUTE_ALIASES = {
    "fp16": "float16",
    "half": "float16",
    "fp32": "float32",
    "float": "float32",
    "flout32": "float32",
    "int8_float": "int8_float32",
}
_LOCAL_WHISPER_DEVICE_ALIASES = {
    "": "auto",
    "default": "auto",
    "gpu": "cuda",
    "nvidia": "cuda",
}
_LOCAL_WHISPER_LANGUAGE_ALIASES = {
    "": None,
    "auto": None,
    "default": None,
    "zh_cn": "zh",
    "zh-cn": "zh",
    "zh_hans": "zh",
    "zh-hans": "zh",
    "zh_tw": "zh",
    "zh-tw": "zh",
    "zh_hant": "zh",
    "zh-hant": "zh",
    "chinese": "zh",
}
_LOCAL_WHISPER_TRANSCRIBE_OPTIONS = {
    "beam_size": 1,
    "best_of": 1,
    "condition_on_previous_text": False,
}


@dataclass
class SubtitleProxyPlan:
    proxies: list[str] = field(default_factory=list)
    source: str = "direct"
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    masked_endpoints: list[str] = field(default_factory=list)
    direct_fallback: bool = False

    def summary(self) -> str:
        if self.masked_endpoints:
            return "，".join(self.masked_endpoints)
        if self.source == "direct":
            return "直连/系统代理"
        return "未解析到代理"


def _clean_error_message(value: Any) -> str:
    text = _ANSI_ESCAPE_RE.sub("", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _strip_llm_thinking_blocks(value: Any) -> str:
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _LLM_THINKING_BLOCK_RE.sub("\n", text)
    if _LEADING_LLM_THINKING_RE.search(text):
        heading = _MARKDOWN_HEADING_RE.search(text)
        text = text[heading.start() :] if heading else ""
    text = re.sub(r"</?(?:think|thinking)\b[^>]*>", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _is_network_subtitle_error(value: str) -> bool:
    return any(keyword in value for keyword in _NETWORK_ERROR_KEYWORDS)


def _is_missing_subtitle_error(value: str) -> bool:
    return any(keyword in value for keyword in _MISSING_SUBTITLE_KEYWORDS)


def _coerce_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_fs_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def _is_path_within(candidate: str, root: str) -> bool:
    try:
        return os.path.commonpath([candidate, root]) == root
    except ValueError:
        return False


def _resolve_project_path(value: Any, default: str) -> Path:
    path = Path(str(value or default)).expanduser()
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path.resolve()


def _default_wechat_collection_output_dir() -> str:
    try:
        import monitor.wechat_collector as wechat_collector

        data_dir = str(getattr(db, "_DATA_DIR", "data"))
        return str(wechat_collector.default_collection_output_dir(data_dir) or "")
    except Exception:
        return ""


def _wechat_collection_output_root(cfg: dict[str, Any]) -> str:
    configured = str((cfg or {}).get("wechat_collection_output_dir") or "").strip()
    return configured or _default_wechat_collection_output_dir()


def _read_wechat_article_source(article_source_path: str, cfg: dict[str, Any]) -> str:
    source = Path(article_source_path).expanduser()
    if not source.is_file():
        raise RuntimeError("公众号文章源文件不存在")
    root = _wechat_collection_output_root(cfg)
    if root:
        resolved_path = _normalize_fs_path(str(source))
        allowed_root = _normalize_fs_path(root)
        if not _is_path_within(resolved_path, allowed_root):
            raise RuntimeError("文章路径必须位于公众号采集输出目录下")
    return source.read_text(encoding="utf-8", errors="ignore")


def _mask_proxy_url(proxy: str | None) -> str:
    if not proxy:
        return "直连/系统代理"
    try:
        parsed = urlparse(proxy)
        if not parsed.scheme or not parsed.netloc:
            return proxy[:80]
        host = parsed.hostname or "***"
        port = ""
        try:
            if parsed.port is not None:
                port = f":{parsed.port}"
        except ValueError:
            port = ""
        auth = "****:****@" if parsed.username or parsed.password else ""
        return f"{parsed.scheme}://{auth}{host}{port}"
    except Exception:
        return str(proxy)[:80]


def _proxy_with_scheme(proxy: str, scheme: str) -> str:
    parsed = urlparse(proxy)
    if not parsed.netloc:
        return proxy
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _is_loopback_proxy(proxy: str) -> bool:
    try:
        host = (urlparse(proxy).hostname or "").lower()
    except Exception:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _normalize_proxy_candidates(proxies: list[str | None]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        if not candidate:
            return
        proxy = str(candidate).strip()
        if not proxy:
            return
        if "://" not in proxy:
            proxy = f"http://{proxy}"
        if proxy in seen:
            return
        seen.add(proxy)
        normalized.append(proxy)

    for proxy in proxies:
        add(proxy)
        if not proxy:
            continue
        value = str(proxy).strip()
        if "://" not in value:
            value = f"http://{value}"
        parsed = urlparse(value)
        if _is_loopback_proxy(value) and parsed.scheme in {"http", "https", "socks", "socks5"}:
            # v2rayN mixed ports accept HTTP and SOCKS on the same local port.
            # Trying both makes the route robust when the saved pool protocol is wrong.
            add(_proxy_with_scheme(value, "socks5" if parsed.scheme in {"http", "https"} else "http"))
    return normalized


def _plan_from_static_proxies(
    proxies: list[str | None],
    *,
    source: str,
    reason: str,
    warnings: list[str] | None = None,
    direct_fallback: bool = False,
) -> SubtitleProxyPlan:
    normalized = _normalize_proxy_candidates(proxies)
    return SubtitleProxyPlan(
        proxies=normalized,
        source=source if normalized else "failed",
        reason=reason,
        warnings=warnings or [],
        masked_endpoints=[_mask_proxy_url(proxy) for proxy in normalized],
        direct_fallback=direct_fallback,
    )


def _plan_from_route(route: Any, *, direct_fallback: bool = False) -> SubtitleProxyPlan:
    proxies = list(route.proxy_pool or [])
    if route.proxy:
        proxies.insert(0, route.proxy)
    normalized = _normalize_proxy_candidates(proxies)
    source = getattr(route, "resolved_proxy_source", "") or ("direct" if not normalized else "unknown")
    return SubtitleProxyPlan(
        proxies=normalized,
        source=source,
        reason=getattr(route, "reason", "") or "",
        warnings=list(getattr(route, "warnings", []) or []),
        masked_endpoints=[_mask_proxy_url(proxy) for proxy in normalized]
        or ([getattr(route, "masked_proxy_endpoint", "")] if getattr(route, "masked_proxy_endpoint", None) else []),
        direct_fallback=direct_fallback,
    )


def _pool_proxy(pool_id: int | None) -> str:
    if not pool_id:
        return ""
    pool = db.get_proxy_pool(pool_id)
    if pool and pool.get("enabled"):
        return str(pool.get("proxy_url") or "").strip()
    return ""


def _legacy_article_proxy(cfg: dict[str, Any]) -> str:
    return str(
        cfg.get("article_subtitle_proxy")
        or cfg.get("download_subtitle_proxy")
        or cfg.get("subtitle_proxy")
        or cfg.get("global_proxy")
        or ""
    ).strip()


def _resolve_article_subtitle_proxy_plan(
    cfg: dict[str, Any] | None,
    *,
    account: dict[str, Any] | None = None,
    cookies_file_present: bool = False,
) -> SubtitleProxyPlan:
    """
    Resolve subtitle download proxy based on article_subtitle_proxy_mode setting.

    Modes:
      - auto:        configured article pool -> source video account -> legacy proxy -> system dynamic proxy
      - system_only: only system dynamic proxy
      - direct_only: no proxy (direct connection)
      - account_only: only configured/source-account static proxy
    """
    if not cfg:
        _log.warning("[字幕代理] cfg为空，使用直连/系统代理")
        return SubtitleProxyPlan(source="direct", reason="cfg为空，使用直连/系统代理", direct_fallback=True)

    mode = str(cfg.get("article_subtitle_proxy_mode") or "auto").strip() or "auto"
    pool_id = _coerce_positive_int(cfg.get("article_subtitle_proxy_pool_id"))
    legacy_proxy = _legacy_article_proxy(cfg)
    _log.info(
        "[字幕代理] mode=%s, pool_id=%s, account_id=%s, cookie=%s",
        mode,
        pool_id,
        (account or {}).get("id"),
        cookies_file_present,
    )

    if mode == "direct_only":
        return SubtitleProxyPlan(source="direct", reason="直连模式", direct_fallback=True)

    if mode == "account_only":
        pool_proxy = _pool_proxy(pool_id)
        if pool_proxy:
            return _plan_from_static_proxies(
                [pool_proxy],
                source="account_static",
                reason=f"使用文章字幕固定代理池 #{pool_id}",
            )
        if account:
            route_account = dict(account)
            route_account["download_proxy_mode"] = "account_only"
            route = proxy_router.resolve_proxy_download(
                route_account,
                is_auto_download=False,
                cookies_file_present=cookies_file_present,
                user_forced_direct=False,
            )
            plan = _plan_from_route(route)
            if plan.proxies:
                return plan
        if legacy_proxy:
            return _plan_from_static_proxies(
                [legacy_proxy],
                source="account_static",
                reason="使用 article_subtitle_proxy 固定代理",
            )
        return SubtitleProxyPlan(
            source="failed",
            reason="account_only 模式未配置可用代理池或账号代理",
        )

    if mode == "system_only":
        route_account = dict(account or {})
        route_account["proxy_enabled"] = False
        route_account["download_proxy_mode"] = "system_only"
        result = proxy_router.resolve_proxy_download(
            route_account,
            is_auto_download=False,
            cookies_file_present=cookies_file_present,
            user_forced_direct=False,
        )
        return _plan_from_route(result, direct_fallback=result.resolved_proxy_source == "direct")

    # auto
    pool_proxy = _pool_proxy(pool_id)
    if pool_proxy:
        return _plan_from_static_proxies(
            [pool_proxy],
            source="account_static",
            reason=f"自动模式优先使用文章字幕代理池 #{pool_id}",
            direct_fallback=False,
        )

    account_direct_plan: SubtitleProxyPlan | None = None
    if account:
        route = proxy_router.resolve_proxy_download(
            dict(account),
            is_auto_download=False,
            cookies_file_present=cookies_file_present,
            user_forced_direct=False,
        )
        plan = _plan_from_route(route, direct_fallback=False)
        if plan.proxies:
            return plan
        if plan.source == "direct":
            account_direct_plan = plan

    if legacy_proxy:
        return _plan_from_static_proxies(
            [legacy_proxy],
            source="legacy",
            reason="自动模式使用 article_subtitle_proxy 兼容配置",
            direct_fallback=False,
        )

    if account_direct_plan:
        return account_direct_plan

    route_account = {"proxy_enabled": False, "download_proxy_mode": "system_only"}
    result = proxy_router.resolve_proxy_download(
        route_account,
        is_auto_download=False,
        cookies_file_present=cookies_file_present,
        user_forced_direct=False,
    )
    return _plan_from_route(result, direct_fallback=result.resolved_proxy_source == "direct")


class ArticleTaskCancelled(Exception):
    """Raised when cooperative cancellation is requested."""


def _safe_name(value: str | None, fallback: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value or "").strip("._")
    return text[:80] or fallback


def _write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _generated_file_url(path: str | Path) -> str:
    return f"/api/article/file?path={quote(str(Path(path).resolve()), safe='')}"


def _strip_subtitle_markup(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper() == "WEBVTT":
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{\\.*?\}", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _find_local_subtitle(video_path: str | None) -> Path | None:
    if not video_path:
        return None
    path = Path(video_path)
    if not path.exists():
        return None
    candidates = [path.with_suffix(ext) for ext in _SUBTITLE_EXTENSIONS]
    candidates.extend(path.parent.glob(f"{path.stem}.*.srt"))
    candidates.extend(path.parent.glob(f"{path.stem}.*.vtt"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class SubtitleDownloadError(Exception):
    """Raised when subtitle download fails due to network/rate-limit (not missing)."""


class SourceMediaDownloadError(Exception):
    """Raised when fallback media download for Whisper fails."""


def _subtitle_language_candidates(languages: str) -> list[str]:
    candidates: list[str] = []
    for part in (languages or "").split(","):
        lang = part.strip()
        if lang and lang not in candidates:
            candidates.append(lang)
    for fallback in ("en", "zh-Hans", "zh-Hant", "zh", "ja", "ko"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _resolve_cookiefile_for_ytdlp(cfg: dict[str, Any] | None, output_dir: Path) -> tuple[str | None, str | None]:
    cookie_path = str((cfg or {}).get("article_cookies_file") or (cfg or {}).get("download_cookies_file") or "").strip()
    if not cookie_path:
        return None, None
    path = Path(cookie_path)
    if not path.is_file():
        return None, None
    if path.suffix.lower() != ".json":
        return str(path), None
    try:
        import export_cookies

        tmp_cookie, _count, _missing = export_cookies.convert_json_to_temp_netscape(str(path))
        return tmp_cookie, tmp_cookie
    except Exception:
        try:
            converted = output_dir / "cookies_netscape.txt"
            if export_cookies.convert_json_to_netscape(str(path), str(converted)):
                return str(converted), None
        except Exception:
            return None, None
    return None, None


def _proxy_attempts_from_plan(plan: SubtitleProxyPlan) -> list[tuple[str, str | None]]:
    attempts: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for proxy in plan.proxies:
        if proxy in seen:
            continue
        seen.add(proxy)
        attempts.append((_mask_proxy_url(proxy), proxy))
    if not attempts or plan.direct_fallback:
        attempts.append(("直连/系统代理", None))
    return attempts


def _cleanup_temp_cookie(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def _find_probe_subtitle(output_dir: Path, prefix: str) -> str | None:
    for ext in _SUBTITLE_EXTENSIONS:
        for candidate in output_dir.glob(f"{prefix}*.{ext.lstrip('.')}"):
            if candidate.is_file():
                text = _strip_subtitle_markup(candidate.read_text(encoding="utf-8", errors="ignore"))
                if text.strip():
                    return text
    return None


def _download_subtitles(
    video_url: str,
    output_dir: Path,
    languages: str,
    cfg: dict[str, Any] | None = None,
    *,
    account: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    try:
        import yt_dlp
    except Exception:
        return None, {"reason": "yt-dlp 未安装，跳过字幕下载"}

    cookiefile, temp_cookie = _resolve_cookiefile_for_ytdlp(cfg, output_dir)
    plan = _resolve_article_subtitle_proxy_plan(
        cfg,
        account=account,
        cookies_file_present=bool(cookiefile),
    )
    attempts = _proxy_attempts_from_plan(plan)
    lang_list = _subtitle_language_candidates(languages)
    network_errors: list[str] = []
    tried: list[str] = []

    base_opts: dict[str, Any] = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt/srt/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 45,
        "extractor_retries": 3,
        "fragment_retries": 3,
    }
    if cookiefile:
        base_opts["cookiefile"] = cookiefile

    try:
        for attempt_index, (proxy_label, proxy) in enumerate(attempts, start=1):
            proxy_hit_network_error = False
            for lang in lang_list:
                safe_lang = re.sub(r"[^A-Za-z0-9_-]+", "_", lang)
                prefix = f"subtitle_probe_{attempt_index}_{safe_lang}"
                opts = dict(base_opts)
                opts.update(
                    {
                        "subtitleslangs": [lang],
                        "outtmpl": str(output_dir / f"{prefix}.%(ext)s"),
                    }
                )
                if proxy:
                    opts["proxy"] = proxy
                tried.append(f"{proxy_label}/{lang}")
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([video_url])
                    text = _find_probe_subtitle(output_dir, prefix)
                    if text:
                        return text, {
                            "language": lang,
                            "proxy": proxy_label,
                            "proxy_plan": plan.summary(),
                            "cookies": bool(cookiefile),
                            "attempts": tried,
                        }
                except yt_dlp.utils.DownloadError as exc:
                    err = _clean_error_message(exc)
                    if _is_missing_subtitle_error(err):
                        continue
                    if _is_network_subtitle_error(err):
                        network_errors.append(f"{proxy_label}/{lang}: {err}")
                        proxy_hit_network_error = True
                        break
                    raise SubtitleDownloadError(f"字幕下载失败: {err}") from exc
                except Exception as exc:
                    err = _clean_error_message(exc)
                    if _is_network_subtitle_error(err):
                        network_errors.append(f"{proxy_label}/{lang}: {err}")
                        proxy_hit_network_error = True
                        break
                    raise SubtitleDownloadError(f"字幕下载异常: {err}") from exc
            if proxy_hit_network_error:
                continue
    finally:
        _cleanup_temp_cookie(temp_cookie)

    details = {
        "proxy_plan": plan.summary(),
        "cookies": bool(cookiefile),
        "attempts": tried,
    }
    if network_errors:
        last_error = network_errors[-1]
        tried_text = "；".join(tried[-6:])
        raise SubtitleDownloadError(f"字幕下载网络错误: {last_error}；已尝试: {tried_text}")
    return None, details


def _find_downloaded_media(output_dir: Path, prefix: str) -> Path | None:
    candidates = sorted(
        [path for path in output_dir.glob(f"{prefix}.*") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _download_audio_for_whisper(
    video_url: str,
    output_dir: Path,
    cfg: dict[str, Any] | None = None,
    *,
    account: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> str | None:
    try:
        import yt_dlp  # noqa: F401  -- lazy import, avoids top-level dep
    except Exception as exc:
        raise SourceMediaDownloadError("yt-dlp 未安装，无法下载音频用于 Whisper") from exc

    cookiefile, temp_cookie = _resolve_cookiefile_for_ytdlp(cfg, output_dir)
    plan = _resolve_article_subtitle_proxy_plan(
        cfg,
        account=account,
        cookies_file_present=bool(cookiefile),
    )
    attempts = _proxy_attempts_from_plan(plan)
    errors: list[str] = []
    base_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "whisper_source.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 60,
        "extractor_retries": 3,
        "fragment_retries": 3,
    }
    if cookiefile:
        base_opts["cookiefile"] = cookiefile

    try:
        for proxy_label, proxy in attempts:
            if progress:
                progress(f"正在下载 Whisper 音频（代理：{proxy_label}）")
            opts = dict(base_opts)
            if proxy:
                opts["proxy"] = proxy
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([video_url])
                media = _find_downloaded_media(output_dir, "whisper_source")
                if media:
                    if progress:
                        progress(f"Whisper 音频下载完成：{media.name}（{media.stat().st_size} bytes）")
                    return str(media)
            except Exception as exc:
                message = _clean_error_message(exc)
                errors.append(f"{proxy_label}: {message}")
                if progress:
                    progress(f"Whisper 音频下载失败（代理：{proxy_label}）：{message[:180]}")
                continue
    finally:
        _cleanup_temp_cookie(temp_cookie)

    if errors:
        raise SourceMediaDownloadError("Whisper 音频下载失败: " + "；".join(errors[-3:]))
    return None


def _resolve_local_whisper_model_path(model_input: str) -> str:
    """Resolve a faster-whisper model name or HuggingFace cache root to a loadable path."""
    value = str(model_input or "base").strip() or "base"
    model_path = Path(value)
    if (model_path / "model.bin").is_file():
        return str(model_path)

    snapshots_dir = model_path / "snapshots"
    if snapshots_dir.is_dir():
        snapshots = sorted(
            (
                snap_dir
                for snap_dir in snapshots_dir.iterdir()
                if snap_dir.is_dir() and (snap_dir / "model.bin").is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if snapshots:
            return str(snapshots[0])

    if model_path.exists():
        return str(model_path)

    return value


def _normalize_local_whisper_compute_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return _LOCAL_WHISPER_COMPUTE_ALIASES.get(text, text)


def _normalize_local_whisper_device(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return _LOCAL_WHISPER_DEVICE_ALIASES.get(text, text or "auto")


def _normalize_local_whisper_language(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("_", "-")
    return _LOCAL_WHISPER_LANGUAGE_ALIASES.get(text, text) or None


def _local_whisper_compute_candidates(cfg: dict[str, Any] | None) -> list[str]:
    configured = str((cfg or {}).get("whisper_compute_type") or "").strip()
    raw_candidates = re.split(r"[,;|\s]+", configured) if configured else ["auto"]
    candidates: list[str] = []
    has_explicit_compute = any(
        _normalize_local_whisper_compute_type(raw) not in {"", "auto", "default"}
        for raw in raw_candidates
    )

    def add(candidate: Any) -> None:
        compute = _normalize_local_whisper_compute_type(candidate)
        if not compute:
            return
        if compute in {"auto", "default"}:
            for fallback in _LOCAL_WHISPER_AUTO_COMPUTE_TYPES:
                add(fallback)
            return
        if compute not in candidates:
            candidates.append(compute)

    for raw in raw_candidates:
        add(raw)
    if configured and has_explicit_compute:
        # Keep an explicit user preference first, but still provide safe CPU
        # fallbacks for machines where CTranslate2 rejects the preferred type.
        for fallback in _LOCAL_WHISPER_EXPLICIT_FALLBACK_COMPUTE_TYPES:
            add(fallback)
    return candidates or list(_LOCAL_WHISPER_AUTO_COMPUTE_TYPES)


def _local_whisper_cuda_device_count() -> int:
    try:
        import ctranslate2

        return max(0, int(ctranslate2.get_cuda_device_count()))
    except Exception:
        return 0


def _local_whisper_cuda_available() -> bool:
    return _local_whisper_cuda_device_count() > 0


def _local_whisper_supported_compute_types(device: str) -> set[str]:
    try:
        import ctranslate2

        return {
            _normalize_local_whisper_compute_type(compute)
            for compute in ctranslate2.get_supported_compute_types(device)
        }
    except Exception:
        if device == "cpu":
            return set(_LOCAL_WHISPER_AUTO_COMPUTE_TYPES)
        return set()


def _local_whisper_gpu_memory_mb() -> tuple[int | None, int | None]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return (None, None)
    try:
        completed = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return (None, None)
    if completed.returncode != 0:
        return (None, None)
    first_line = (completed.stdout or "").strip().splitlines()
    if not first_line:
        return (None, None)
    values = [part.strip() for part in first_line[0].split(",")]
    if len(values) < 2:
        return (None, None)
    try:
        return (int(values[0]), int(values[1]))
    except ValueError:
        return (None, None)


def _local_whisper_low_vram_gpu(total_mb: int | None, free_mb: int | None) -> bool:
    return bool(
        (total_mb is not None and total_mb <= _LOW_VRAM_GPU_TOTAL_MB)
        or (free_mb is not None and free_mb <= _LOW_VRAM_GPU_FREE_MB)
    )


def _local_whisper_cuda_compute_candidates(
    cfg: dict[str, Any] | None,
    *,
    low_vram_gpu: bool,
) -> list[str]:
    configured_device = _normalize_local_whisper_device((cfg or {}).get("whisper_device"))
    configured_compute = _normalize_local_whisper_compute_type((cfg or {}).get("whisper_compute_type"))
    requested = _local_whisper_compute_candidates(cfg)
    preferred = (
        list(_LOCAL_WHISPER_CUDA_LOW_VRAM_COMPUTE_TYPES)
        if low_vram_gpu
        else list(_LOCAL_WHISPER_CUDA_COMPUTE_TYPES)
    )

    candidates: list[str] = []

    def add(compute: str) -> None:
        if compute and compute not in candidates:
            candidates.append(compute)

    if low_vram_gpu:
        if configured_compute in _LOCAL_WHISPER_CUDA_LOW_VRAM_COMPUTE_TYPES:
            add(configured_compute)
        for compute in preferred:
            add(compute)
        if configured_device == "cuda" and configured_compute == "float32":
            add("float32")
    else:
        for compute in requested:
            add(compute)
        for compute in preferred:
            add(compute)
    return candidates


def _local_whisper_cpu_compute_candidates(
    cfg: dict[str, Any] | None,
    *,
    low_vram_gpu: bool,
) -> list[str]:
    requested = _local_whisper_compute_candidates(cfg)
    configured_device = _normalize_local_whisper_device((cfg or {}).get("whisper_device"))
    configured_compute = _normalize_local_whisper_compute_type((cfg or {}).get("whisper_compute_type"))
    if not low_vram_gpu or configured_device == "cpu":
        return requested

    candidates: list[str] = []

    def add(compute: str) -> None:
        if compute and compute not in candidates:
            candidates.append(compute)

    if configured_compute in _LOCAL_WHISPER_CUDA_LOW_VRAM_COMPUTE_TYPES:
        add(configured_compute)
    for compute in _LOCAL_WHISPER_CUDA_LOW_VRAM_COMPUTE_TYPES:
        add(compute)
    for compute in requested:
        if compute != "float32":
            add(compute)
    add("float32")
    return candidates


def _local_whisper_candidate_plan(
    cfg: dict[str, Any] | None,
    *,
    cuda_available: bool | None = None,
    cuda_supported_compute_types: set[str] | None = None,
    cpu_supported_compute_types: set[str] | None = None,
    gpu_total_mb: int | None = None,
    gpu_free_mb: int | None = None,
) -> list[tuple[str, str]]:
    device_preference = _normalize_local_whisper_device((cfg or {}).get("whisper_device"))
    cuda_available = _local_whisper_cuda_available() if cuda_available is None else cuda_available
    cuda_supported = (
        _local_whisper_supported_compute_types("cuda")
        if cuda_supported_compute_types is None and cuda_available
        else (cuda_supported_compute_types or set())
    )
    cpu_supported = (
        _local_whisper_supported_compute_types("cpu")
        if cpu_supported_compute_types is None
        else cpu_supported_compute_types
    )
    if not cpu_supported:
        cpu_supported = set(_LOCAL_WHISPER_AUTO_COMPUTE_TYPES)

    if gpu_total_mb is None and gpu_free_mb is None and cuda_available:
        gpu_total_mb, gpu_free_mb = _local_whisper_gpu_memory_mb()
    low_vram_gpu = _local_whisper_low_vram_gpu(gpu_total_mb, gpu_free_mb)

    plan: list[tuple[str, str]] = []

    def add(device: str, compute: str, supported: set[str]) -> None:
        if compute not in supported:
            return
        candidate = (compute, device)
        if candidate not in plan:
            plan.append(candidate)

    if device_preference in {"auto", "cuda"} and cuda_available:
        for compute in _local_whisper_cuda_compute_candidates(cfg, low_vram_gpu=low_vram_gpu):
            add("cuda", compute, cuda_supported)

    if device_preference != "cuda" or not plan:
        for compute in _local_whisper_cpu_compute_candidates(cfg, low_vram_gpu=low_vram_gpu):
            add("cpu", compute, cpu_supported)
    elif device_preference == "cuda":
        # CUDA is preferred but not strict: keep CPU fallbacks so driver/OOM
        # failures do not make the whole article task fail.
        for compute in _local_whisper_cpu_compute_candidates(cfg, low_vram_gpu=low_vram_gpu):
            add("cpu", compute, cpu_supported)

    return plan


def _local_whisper_chunk_seconds(
    cfg: dict[str, Any] | None,
    *,
    low_vram_gpu: bool = False,
) -> int:
    configured = _coerce_positive_int((cfg or {}).get("whisper_chunk_seconds"))
    seconds = configured or (
        _MIN_LOCAL_WHISPER_CHUNK_SECONDS if low_vram_gpu else _DEFAULT_LOCAL_WHISPER_CHUNK_SECONDS
    )
    return max(
        _MIN_LOCAL_WHISPER_CHUNK_SECONDS,
        min(_MAX_LOCAL_WHISPER_CHUNK_SECONDS, seconds),
    )


def _probe_media_duration_seconds(media_path: str | Path) -> float | None:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except FileNotFoundError:
        _log.warning("[Whisper] ffprobe 未找到，无法探测音频时长: %s", media_path)
        return None
    except Exception as exc:
        _log.warning("[Whisper] ffprobe 探测音频时长失败: %s", _clean_error_message(exc))
        return None
    if completed.returncode != 0:
        _log.warning(
            "[Whisper] ffprobe 探测音频时长失败 rc=%s stderr=%s",
            completed.returncode,
            _clean_error_message(completed.stderr)[-300:],
        )
        return None
    try:
        duration = float(str(completed.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _split_audio_for_whisper(
    media_path: str | Path,
    output_dir: str | Path,
    chunk_seconds: int,
) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    chunk_pattern = output_path / "chunk_%04d.wav"
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(media_path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "segment",
                "-segment_time",
                str(chunk_seconds),
                "-reset_timestamps",
                "1",
                "-segment_format",
                "wav",
                str(chunk_pattern),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg 未找到，无法按分片方式执行本地 Whisper") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg 音频分片超时") from exc
    if completed.returncode != 0:
        message = _clean_error_message(completed.stderr)[-500:] or "未知错误"
        raise RuntimeError(f"ffmpeg 音频分片失败：{message}")
    chunks = sorted(output_path.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("ffmpeg 音频分片完成但未生成任何片段")
    return chunks


def _local_whisper_transcribe(
    model: Any,
    source: str | Path,
    *,
    language: str | None,
) -> Any:
    options: dict[str, Any] = {
        "language": language,
        **_LOCAL_WHISPER_TRANSCRIBE_OPTIONS,
    }
    transcribe = model.transcribe
    try:
        signature = inspect.signature(transcribe)
    except (TypeError, ValueError):
        kwargs = options
    else:
        parameters = signature.parameters
        accepts_kwargs = any(param.kind == param.VAR_KEYWORD for param in parameters.values())
        kwargs = options if accepts_kwargs else {key: value for key, value in options.items() if key in parameters}
    return transcribe(str(source), **kwargs)


def _local_whisper(
    video_path: str | None,
    cfg: dict[str, Any],
    *,
    progress: Callable[[str], None] | None = None,
) -> str | None:
    """Run Whisper transcription locally using faster-whisper from HuggingFace cache."""
    if not video_path or not Path(video_path).is_file():
        return None
    _log.info("[Whisper] 开始本地转写 video_path=%s", video_path)
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        message = _clean_error_message(exc)
        if progress:
            progress(f"faster-whisper 未安装或导入失败：{message[:180]}")
        _log.warning("[Whisper] faster-whisper 未安装或导入失败: %s", message)
        return None

    source_path = Path(video_path)
    model_path = _resolve_local_whisper_model_path(
        str(cfg.get("whisper_model") or "base").strip()
    )
    language = _normalize_local_whisper_language(cfg.get("whisper_language"))

    _log.info("[Whisper] 使用本地模型: %s", model_path)
    if language:
        _log.info("[Whisper] 使用指定源语言: %s", language)

    cuda_available = _local_whisper_cuda_available()
    gpu_total_mb, gpu_free_mb = _local_whisper_gpu_memory_mb() if cuda_available else (None, None)
    low_vram_gpu = _local_whisper_low_vram_gpu(gpu_total_mb, gpu_free_mb)
    candidate_plan = _local_whisper_candidate_plan(
        cfg,
        cuda_available=cuda_available,
        gpu_total_mb=gpu_total_mb,
        gpu_free_mb=gpu_free_mb,
    )
    uses_cuda = any(device == "cuda" for _compute, device in candidate_plan)
    chunk_seconds = _local_whisper_chunk_seconds(cfg, low_vram_gpu=uses_cuda and low_vram_gpu)
    if cuda_available:
        memory_label = (
            f"total={gpu_total_mb}MB free={gpu_free_mb}MB"
            if gpu_total_mb is not None and gpu_free_mb is not None
            else "memory=unknown"
        )
        _log.info("[Whisper] CUDA 可用 %s low_vram=%s", memory_label, low_vram_gpu)
        if progress:
            progress(f"检测到 CUDA，GPU 显存 {memory_label}，low_vram={str(low_vram_gpu).lower()}")
    else:
        _log.info("[Whisper] CUDA 不可用，使用 CPU 候选")
    if not candidate_plan:
        message = "本地 Whisper 无可用 compute_type/device 候选"
        if progress:
            progress(message)
        _log.error("[Whisper] %s", message)
        return None

    duration = _probe_media_duration_seconds(source_path)
    chunk_temp_dir: tempfile.TemporaryDirectory | None = None
    sources = [source_path]
    using_chunks = False
    if duration is not None:
        _log.info("[Whisper] 探测到音频时长 %.3fs，分片阈值 %ss", duration, chunk_seconds)
        if progress:
            progress(f"已探测音频时长约 {int(duration)}s，Whisper 分片阈值 {chunk_seconds}s")
    else:
        _log.warning("[Whisper] 未能探测音频时长，将按分片方式尝试转写: %s", source_path)
        if progress:
            progress(f"未能探测音频时长，将尝试按 {chunk_seconds}s 分片用于 Whisper")

    should_split = duration is None or duration > chunk_seconds
    if should_split:
        try:
            if progress:
                if duration is None:
                    progress(f"正在按 {chunk_seconds}s 分片用于 Whisper")
                else:
                    progress(f"音频时长约 {int(duration)}s，正在按 {chunk_seconds}s 分片用于 Whisper")
            chunk_temp_dir = tempfile.TemporaryDirectory(
                prefix=".whisper_chunks_",
                dir=str(source_path.parent),
            )
            sources = _split_audio_for_whisper(source_path, chunk_temp_dir.name, chunk_seconds)
            using_chunks = True
            duration_label = f"{duration:.3f}s" if duration is not None else "unknown"
            _log.info(
                "[Whisper] 音频分片完成 duration=%s chunk_seconds=%s chunks=%d",
                duration_label,
                chunk_seconds,
                len(sources),
            )
            if progress:
                progress(f"Whisper 音频分片完成：{len(sources)} 段，每段最多约 {chunk_seconds}s")
        except Exception as exc:
            message = _clean_error_message(exc)
            if progress:
                progress(f"本地 Whisper 音频分片失败，已停止整文件转写以保护资源：{message[:180]}")
            _log.warning("[Whisper] 音频分片失败，已停止整文件转写以保护资源: %s", message)
            if chunk_temp_dir is not None:
                chunk_temp_dir.cleanup()
                chunk_temp_dir = None
            return None

    _log.info(
        "[Whisper] compute_type/device 候选: %s",
        " -> ".join(f"{compute}/{device}" for compute, device in candidate_plan),
    )
    if progress:
        progress(
            "本地 Whisper 候选："
            + " -> ".join(f"{compute}({device})" for compute, device in candidate_plan)
        )
    failures: list[str] = []
    try:
        for index, (compute, device) in enumerate(candidate_plan, start=1):
            model = None
            try:
                if progress:
                    progress(
                        f"正在尝试本地 Whisper device={device} "
                        f"compute_type={compute}（{index}/{len(candidate_plan)}）"
                    )
                _log.info("[Whisper] 尝试 device=%s compute_type=%s", device, compute)
                model = WhisperModel(
                    model_size_or_path=model_path,
                    device=device,
                    compute_type=compute,
                )
                transcript_parts: list[str] = []
                for source_index, source in enumerate(sources, start=1):
                    source_offset = (source_index - 1) * chunk_seconds if using_chunks else 0
                    if progress and using_chunks:
                        chunk_end = source_index * chunk_seconds
                        if duration is not None:
                            chunk_end = min(chunk_end, duration)
                        progress(
                            f"本地 Whisper device={device} compute_type={compute} 正在转写分片 "
                            f"{source_index}/{len(sources)}（约 {source_offset}-{int(chunk_end)}s）"
                        )
                    segments, _ = _local_whisper_transcribe(model, source, language=language)
                    for segment_count, seg in enumerate(segments, start=1):
                        text = str(getattr(seg, "text", "") or "").strip()
                        if text:
                            transcript_parts.append(text)
                        if progress and segment_count % 8 == 0:
                            segment_end = getattr(seg, "end", None)
                            if isinstance(segment_end, (int, float)):
                                progress(
                                    f"本地 Whisper device={device} compute_type={compute} 转写中："
                                    f"已处理约 {int(source_offset + segment_end)}s"
                                )
                            elif using_chunks:
                                progress(
                                    f"本地 Whisper device={device} compute_type={compute} 转写中："
                                    f"分片 {source_index}/{len(sources)} 已生成 {segment_count} 段"
                                )
                            else:
                                progress(
                                    f"本地 Whisper device={device} "
                                    f"compute_type={compute} 转写中：已生成 {segment_count} 段"
                                )
                transcript = " ".join(transcript_parts).strip()
                _log.info(
                    "[Whisper] 本地转写完成 video_path=%s chunks=%d length=%d",
                    video_path,
                    len(sources) if using_chunks else 1,
                    len(transcript),
                )
                if progress:
                    if using_chunks:
                        progress(
                            f"本地 Whisper device={device} compute_type={compute} "
                            f"分片转写完成（{len(sources)} 段）"
                        )
                    else:
                        progress(f"本地 Whisper device={device} compute_type={compute} 转写完成")
                return transcript or None
            except Exception as e:
                message = _clean_error_message(e)
                failures.append(f"{compute}({device}): {message}")
                if index < len(candidate_plan):
                    next_compute, next_device = candidate_plan[index]
                    if progress:
                        progress(
                            f"本地 Whisper device={device} compute_type={compute} 失败，"
                            f"正在重试 {next_device}/{next_compute}：{message[:180]}"
                        )
                    _log.warning(
                        "[Whisper] device=%s compute_type=%s 失败，继续尝试下一个候选: %s",
                        device,
                        compute,
                        message,
                    )
                else:
                    if progress:
                        progress(
                            f"本地 Whisper device={device} compute_type={compute} "
                            f"失败，已无更多候选：{message[:180]}"
                        )
                    _log.warning(
                        "[Whisper] device=%s compute_type=%s 失败，已无更多候选: %s",
                        device,
                        compute,
                        message,
                    )
            finally:
                if model is not None:
                    del model
                    gc.collect()
        if failures:
            attempted = ", ".join(f"{compute}({device})" for compute, device in candidate_plan)
            if progress:
                progress(
                    f"本地 Whisper 转写失败，已尝试 {attempted}；最后错误：{failures[-1][:180]}"
                )
            _log.error(
                "[Whisper] 本地转写失败，已尝试 %s；最后错误: %s",
                attempted,
                failures[-1],
            )
        return None
    finally:
        if chunk_temp_dir is not None:
            chunk_temp_dir.cleanup()


def _remote_whisper(video_path: str | None, cfg: dict[str, Any]) -> str | None:
    base_url = str(cfg.get("whisper_base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError(
            "需要配置 whisper_base_url 才能使用远程 Whisper API，"
            "请切换到本地 Whisper 或配置 base_url"
        )
    if not video_path or not Path(video_path).is_file():
        return None
    _log.info("[Whisper] 开始远程转写 video_path=%s", video_path)
    headers = {}
    api_key = cfg.get("whisper_api_key") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with open(video_path, "rb") as file_obj:
            response = requests.post(
                f"{base_url}/v1/audio/transcriptions",
                headers=headers,
                data={"model": cfg.get("whisper_model") or "base"},
                files={"file": file_obj},
                timeout=300,
            )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text") or payload.get("transcript") or response.text
        _log.info("[Whisper] 远程转写完成 video_path=%s length=%d", video_path, len(text))
        return text
    except Exception as exc:
        _log.error("[Whisper] 远程转写失败: %s", exc)
        raise


def _llm_or_fallback(
    cfg: dict[str, Any],
    prompt: str,
    text: str,
    *,
    model_key: str,
    fallback_prefix: str,
    temperature: float = 0.3,
) -> str:
    has_llm_surface = _has_llm_surface(cfg)
    model = cfg.get(model_key) or cfg.get("llm_model")
    if has_llm_surface:
        try:
            client = create_llm_client(
                provider=cfg.get("llm_provider") or "qwen",
                model=model,
                api_key=cfg.get("llm_api_key"),
                base_url=cfg.get("llm_base_url"),
            )
            result = client.call_with_retry(
                prompt,
                text,
                max_retries=2,
                temperature=temperature,
                timeout=180,
                raise_last_error=True,
            )
            if result and result.strip():
                cleaned = _strip_llm_thinking_blocks(result)
                if cleaned:
                    return cleaned
        except Exception as exc:
            raise RuntimeError(f"LLM 处理失败: {exc}") from exc
        raise RuntimeError(
            "LLM 处理失败: 服务未返回内容或仅返回不可发布内容"
            f"（{_llm_backend_context(cfg, model)}）。"
            "请检查模型名称、Base URL/API Key、服务商内容过滤或接口返回格式。"
        )
    return f"{fallback_prefix}\n\n{text}".strip()


def _has_llm_surface(cfg: dict[str, Any] | None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("llm_base_url") or cfg.get("llm_api_key") or os.environ.get("LLM_API_KEY"))


def _safe_llm_base_url(base_url: Any) -> str:
    text = str(base_url or "").strip()
    if not text:
        return "default"
    if "://" not in text:
        return text.split("?", 1)[0].split("#", 1)[0] or "<configured>"
    parsed = urlparse(text)
    netloc = parsed.hostname or parsed.netloc
    if parsed.port and parsed.hostname:
        netloc = f"{parsed.hostname}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")) or "<configured>"


def _llm_backend_context(cfg: dict[str, Any], model: Any) -> str:
    provider = str((cfg or {}).get("llm_provider") or "qwen").strip() or "qwen"
    model_name = str(model or (cfg or {}).get("llm_model") or "default").strip() or "default"
    return f"provider={provider}, model={model_name}, base_url={_safe_llm_base_url((cfg or {}).get('llm_base_url'))}"


@dataclass
class WechatArticlePromptEngine:
    role: str = _DEFAULT_WECHAT_PROMPT_ROLE
    reader_persona: str = _DEFAULT_WECHAT_PROMPT_READER
    style: str = _DEFAULT_WECHAT_PROMPT_STYLE
    max_chars: int = 6000

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "WechatArticlePromptEngine":
        try:
            max_chars = int(cfg.get("article_wechat_prompt_max_chars") or 6000)
        except (TypeError, ValueError):
            max_chars = 6000
        return cls(
            role=str(cfg.get("article_wechat_prompt_role") or _DEFAULT_WECHAT_PROMPT_ROLE).strip()
            or _DEFAULT_WECHAT_PROMPT_ROLE,
            reader_persona=(
                str(cfg.get("article_wechat_prompt_reader_persona") or _DEFAULT_WECHAT_PROMPT_READER).strip()
                or _DEFAULT_WECHAT_PROMPT_READER
            ),
            style=str(cfg.get("article_wechat_prompt_style") or _DEFAULT_WECHAT_PROMPT_STYLE).strip()
            or _DEFAULT_WECHAT_PROMPT_STYLE,
            max_chars=min(max(max_chars, 1200), 20_000),
        )

    def _common_contract(self) -> str:
        return (
            f"你是{self.role}，正在为微信公众号读者写作。\n"
            f"读者画像：{self.reader_persona}。\n"
            f"风格要求：{self.style}。\n"
            "输出必须是 Markdown，不要输出 HTML、<script>、<style> 或外链脚本。\n"
            "段落要短，使用清晰的二级/三级标题；必要时保留列表、表格、引用和代码块。\n"
            "不要编造事实、数据、来源或人物观点；原文不确定的信息要保守表述。\n"
            "最终正文要适配微信公众号：标题建议不超过 32 个中文字符，摘要不超过 128 个字符，"
            f"正文建议控制在 {self.max_chars} 字以内。\n"
        )

    def build_optimize_prompt(self) -> str:
        return (
            self._common_contract()
            + "任务：将输入整理为可继续加工的中文公众号文章素材，修正明显错别字和断句，保留全部关键信息。\n"
            + "请输出结构化 Markdown 正文，不要附加解释。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )

    def build_summary_prompt(self) -> str:
        return (
            self._common_contract()
            + "任务：基于全文生成公众号发布前可用的摘要素材。\n"
            + "请包含：1）一句话摘要；2）3-6 个关键要点；3）推荐章节结构；4）适合文末的互动引导。\n"
            + "不要输出营销夸张语，不要复述无信息量的寒暄。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )

    def build_style_analysis_prompt(self, source_type: str) -> str:
        source_label = "公众号文章" if source_type == "wechat_article" else "视频字幕/转写"
        return (
            self._common_contract()
            + f"任务：分析输入的{source_label}，产出可复用的二次创作风格画像。\n"
            + "只分析公开可复用的结构、节奏、信息密度、论证方式和表达策略；"
            + "不要模仿具体作者身份，不要复制原文句子，不要续写。\n"
            + "如果来源是视频，请同时识别口语化噪声、重复信息和适合图文重组的主题线索。\n"
            + "请按以下 Markdown 小节输出：\n"
            + "## 风格画像\n## 结构模式\n## 可复用写作策略\n## 需要规避的问题\n\n"
            + f"<source_type>{source_type}</source_type>\n"
            + f"<source_material>\n{PROMPT_INPUT_PLACEHOLDER}\n</source_material>"
        )

    def build_rewrite_prompt(self, target_lang: str) -> str:
        return (
            self._common_contract()
            + f"任务：基于输入中的素材、摘要策略和风格画像，二次创作为 {target_lang} 的可发布微信公众号正文。\n"
            + "二次创作方法：\n"
            + "1. 事实锚定：只使用输入中存在的信息，不补造来源、数据或人物观点。\n"
            + "2. 结构再组织：将口播或采集稿重排为标题、开场钩子、主体论证、要点总结和文末互动。\n"
            + "3. 风格迁移：只迁移节奏、段落密度、论证路径和标题策略，不照抄原文表达。\n"
            + "4. 微信适配：短段落、清晰小标题、保留有价值的列表/表格/代码/引用，避免夸张营销腔。\n"
            + "请直接输出 Markdown 正文，不要输出分析过程。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )

    def build_translate_prompt(self, target_lang: str) -> str:
        return (
            self._common_contract()
            + f"任务：将输入整理/翻译为 {target_lang} 的微信公众号正文。\n"
            + "保持信息完整和逻辑顺序，保留有价值的列表、表格、术语、代码块和引用。\n"
            + "请直接输出可发布的 Markdown 正文。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )

    def build_evaluation_prompt(self, target_lang: str) -> str:
        return (
            self._common_contract()
            + f"任务：评估候选稿是否适合发布为 {target_lang} 的微信公众号文章。\n"
            + "请只输出 JSON，不要输出 Markdown 或解释文字。评分为 0-10 分，可保留一位小数。\n"
            + "评分维度：事实忠实度 30%，读者价值 25%，风格画像落实 20%，微信发布适配 15%，表达清晰度 10%。\n"
            + "JSON 结构："
            + '{"score": 8.5, "rationale": "一句话理由", '
            + '"strengths": ["优点"], "risks": ["风险"], '
            + '"revision_instructions": "如果低于阈值，给出可执行修订指令"}'
            + "\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )

    def build_revision_prompt(self, target_lang: str) -> str:
        return (
            self._common_contract()
            + f"任务：根据质量评估意见修订候选稿，产出 {target_lang} 的最终微信公众号 Markdown 正文。\n"
            + "必须保留已验证事实，不新增未在素材中出现的案例、数据、引用或人物观点。\n"
            + "优先修复：事实遗漏、结构松散、风格画像未落实、微信公众号可读性差、标题/摘要不合规。\n"
            + "请直接输出修订后的 Markdown 正文，不要输出解释。\n\n"
            + PROMPT_INPUT_PLACEHOLDER
        )


def _yaml_scalar(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _markdown_plain_text(value: str) -> str:
    text = _strip_llm_thinking_blocks(value)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_>#|~`-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _article_quality_threshold(cfg: dict[str, Any] | None) -> float:
    cfg = cfg or {}
    for key in ("article_llm_min_score", "article_quality_min_score", "llm_min_score"):
        value = cfg.get(key)
        if value in (None, ""):
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        return min(max(score, 0.0), 10.0)
    return 7.0


def _json_object_from_text(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    else:
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            text = text[first : last + 1]
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_article_score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            return None
        value = match.group(0)
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 10 and score <= 100:
        score = score / 10
    return round(min(max(score, 0.0), 10.0), 1)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _parse_article_quality_evaluation(response: str, threshold: float) -> dict[str, Any]:
    payload = _json_object_from_text(response)
    score_value = None
    if payload:
        score_value = payload.get("score")
        if score_value in (None, ""):
            score_value = payload.get("overall_score")
        if score_value in (None, ""):
            score_value = payload.get("total_score")
    score = _normalize_article_score(score_value)
    rationale = str(payload.get("rationale") or payload.get("reason") or "").strip() if payload else ""
    if not payload:
        rationale = "LLM 未返回可解析的 JSON 评分。"
    return {
        "score": score,
        "threshold": threshold,
        "passes_threshold": bool(score is not None and score >= threshold),
        "rationale": rationale,
        "strengths": _string_list(payload.get("strengths") if payload else None),
        "risks": _string_list(payload.get("risks") if payload else None),
        "revision_instructions": str(payload.get("revision_instructions") or "").strip() if payload else "",
        "raw": response,
    }


def _fallback_style_profile(source_type: str, material: str) -> str:
    source_label = "公众号文章" if source_type == "wechat_article" else "视频字幕/转写"
    plain = _markdown_plain_text(material)
    paragraph_count = len([part for part in re.split(r"\n\s*\n", material or "") if part.strip()])
    return (
        "## 风格画像\n"
        f"- 来源类型：{source_label}\n"
        f"- 素材长度：约 {len(plain)} 个字符，段落/片段约 {paragraph_count} 个。\n"
        "- 画像来源：未配置 LLM，使用规则兜底画像。\n\n"
        "## 结构模式\n"
        "- 优先保留原始事实顺序，再整理为清晰小标题和短段落。\n\n"
        "## 可复用写作策略\n"
        "- 保留关键信息、术语、列表、表格、代码块和引用。\n"
        "- 将口语化或采集噪声压缩为面向读者的问题、判断和行动建议。\n\n"
        "## 需要规避的问题\n"
        "- 不复制原文句子，不补造输入中没有的来源、数据或人物观点。\n"
    )


def _article_generation_payload(
    *,
    source_type: str,
    title: str,
    optimized: str,
    summary: str,
    style_profile: str,
    body: str | None = None,
    evaluation: dict[str, Any] | None = None,
) -> str:
    parts = [
        f"<source_type>{source_type}</source_type>",
        f"<title>{title}</title>",
        f"<style_profile>\n{style_profile}\n</style_profile>",
        f"<summary_strategy>\n{summary}\n</summary_strategy>",
        f"<source_material>\n{optimized}\n</source_material>",
    ]
    if body is not None:
        parts.append(f"<candidate_article>\n{body}\n</candidate_article>")
    if evaluation is not None:
        parts.append(
            "<quality_evaluation>\n"
            + json.dumps(evaluation, ensure_ascii=False, indent=2)
            + "\n</quality_evaluation>"
        )
    return "\n\n".join(parts)


class ArticleGenerationPipeline:
    def __init__(self, task_id: str, cfg: dict[str, Any] | None = None):
        self.task_id = task_id
        self.cfg = cfg or db.load_config()
        self.stages: dict[str, dict[str, Any]] = {}

    def _stage(self, key: str, status: str, message: str = "") -> None:
        self.stages[key] = {"status": status, "message": message}
        db.update_article_task(self.task_id, current_stage=key, stages=self.stages)
        _log.info("[文章生成] task=%s stage=%s status=%s message=%s", self.task_id, key, status, message)

    def _check_cancelled(self) -> None:
        task = db.get_article_task(self.task_id)
        if task and task.get("cancel_requested"):
            raise ArticleTaskCancelled("文章生成任务已取消")

    def run(self) -> dict[str, Any]:
        task = db.get_article_task(self.task_id)
        if not task:
            raise ValueError(f"article task not found: {self.task_id}")
        if task.get("cancel_requested"):
            db.update_article_task(
                self.task_id,
                status="cancelled",
                error=None,
                finished_at=db.now_iso(),
            )
            return db.get_article_task(self.task_id) or {}

        output_root = _resolve_project_path(self.cfg.get("article_output_dir"), "output/articles")
        output_dir = output_root / self.task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        db.update_article_task(self.task_id, status="running", output_dir=str(output_dir))

        try:
            source_type = str(task.get("source_type") or "video").strip() or "video"
            subtitle_details: dict[str, Any] = {}
            subtitle_failure_message = ""
            transcript = None
            transcript_source = ""
            video_path: str | None = None

            if source_type == "wechat_article":
                self._stage("subtitles", "running", "正在读取公众号文章")
                article_text = str(task.get("article_text") or "")
                article_source_path = str(task.get("article_source_path") or "").strip()
                if not article_text and article_source_path:
                    article_text = _read_wechat_article_source(article_source_path, self.cfg)
                if not article_text.strip():
                    raise RuntimeError("公众号文章内容为空，无法生成 AI 文章")
                transcript = article_text
                transcript_source = "wechat_article"
                subtitle_details = {
                    "path": article_source_path,
                    "source_url": task.get("source_url") or "",
                }
                video_url = task.get("source_url") or ""
                video_title = task.get("source_title") or task.get("video_title") or self.task_id
            else:
                monitor_video = (
                    db.get_monitor_video(int(task["monitor_video_id"]))
                    if task.get("monitor_video_id")
                    else None
                )
                account = None
                if monitor_video and monitor_video.get("account_id"):
                    try:
                        account = db.get_account(int(monitor_video["account_id"]))
                    except Exception:
                        account = None
                video_path = resolve_downloaded_video_path(monitor_video) if monitor_video else None
                video_url = task.get("video_url") or (monitor_video or {}).get("url")
                if not video_url and task.get("video_id"):
                    video_id_snapshot = str(task.get("video_id") or "").strip()
                    if video_id_snapshot.startswith(("http://", "https://")):
                        video_url = video_id_snapshot
                    elif len(video_id_snapshot) == 11 and video_id_snapshot.replace("-", "").isalnum():
                        # Heuristic: 11-char alphanumeric with hyphens is typical YouTube video ID
                        video_url = f"https://www.youtube.com/watch?v={video_id_snapshot}"
                    # else: video_url stays None — subtitle download will be skipped via local path
                video_title = (
                    task.get("video_title")
                    or (monitor_video or {}).get("title")
                    or task.get("video_id")
                    or self.task_id
                )

                self._stage("subtitles", "running", "正在提取字幕")
                subtitle_path = _find_local_subtitle(video_path)
                if subtitle_path:
                    transcript = _strip_subtitle_markup(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
                    transcript_source = "local_subtitle"
                    subtitle_details = {"path": str(subtitle_path)}
                if not transcript and video_url:
                    try:
                        transcript, subtitle_details = _download_subtitles(
                            video_url,
                            output_dir,
                            str(self.cfg.get("article_subtitle_languages") or ""),
                            self.cfg,
                            account=account,
                        )
                        if transcript:
                            transcript_source = "remote_subtitle"
                    except SubtitleDownloadError as exc:
                        subtitle_failure_message = _clean_error_message(exc)
                        self._stage("subtitles", "done", f"字幕下载失败，已切换 Whisper：{subtitle_failure_message[:180]}")
                self._check_cancelled()

                if not transcript:
                    if not video_path and video_url:
                        self._stage("source_media", "running", "字幕不可用，正在下载音频用于 Whisper")
                        try:
                            video_path = _download_audio_for_whisper(
                                video_url,
                                output_dir,
                                self.cfg,
                                account=account,
                                progress=lambda msg: self._stage("source_media", "running", msg),
                            )
                        except SourceMediaDownloadError as exc:
                            message = _clean_error_message(exc)
                            self._stage("source_media", "error", message[:220])
                            if subtitle_failure_message:
                                raise RuntimeError(f"{subtitle_failure_message}；{message}") from exc
                            raise RuntimeError(message) from exc
                        if video_path:
                            self._stage("source_media", "done", "音频下载完成，准备 Whisper 转写")
                        else:
                            self._stage("source_media", "error", "没有可用于 Whisper 的本地视频或音频")
                            raise RuntimeError("未找到可下载字幕，且无法获取本地视频或音频用于 Whisper")
                    if not video_path:
                        if subtitle_failure_message:
                            raise RuntimeError(
                                f"{subtitle_failure_message}；当前任务没有本地视频或音频，无法切换 Whisper"
                            )
                        raise RuntimeError("未找到可用字幕，且当前任务没有本地视频或音频，无法切换 Whisper")
                    whisper_provider = str(self.cfg.get("whisper_provider") or "api").strip().lower()
                    if whisper_provider == "local":
                        self._stage("whisper", "running", "正在使用本地 Whisper 模型转写")
                        transcript = _local_whisper(
                            video_path,
                            self.cfg,
                            progress=lambda msg: self._stage("whisper", "running", msg),
                        )
                        if transcript:
                            self._stage("whisper", "done", "本地 Whisper 转写完成")
                            transcript_source = "local_whisper"
                        else:
                            whisper_message = str(self.stages.get("whisper", {}).get("message") or "").strip()
                            self._stage("whisper", "error", whisper_message or "本地 Whisper 转写失败")
                    else:
                        self._stage("whisper", "running", "正在使用远程 Whisper API 转写")
                        transcript = _remote_whisper(video_path, self.cfg)
                        if transcript:
                            self._stage("whisper", "done", "远程 Whisper 转写完成")
                            transcript_source = "remote_whisper"
                        else:
                            self._stage("whisper", "error", "远程 Whisper 转写失败")
                    if not transcript:
                        raise RuntimeError("无法获取字幕或转写文本，请配置字幕来源或 Whisper 服务")
            transcript_path = _write_text(output_dir / "transcript.txt", transcript)
            db.update_article_task(
                self.task_id,
                transcript_path=transcript_path,
                source_lang=subtitle_details.get("language") if subtitle_details else None,
            )
            if transcript_source == "remote_subtitle":
                proxy_label = subtitle_details.get("proxy") or subtitle_details.get("proxy_plan") or "直连/系统代理"
                cookie_label = "已启用 Cookie" if subtitle_details.get("cookies") else "未使用 Cookie"
                self._stage(
                    "subtitles",
                    "done",
                    f"字幕下载完成（{subtitle_details.get('language') or 'auto'}；代理：{proxy_label}；{cookie_label}）",
                )
            elif transcript_source == "local_subtitle":
                self._stage("subtitles", "done", "已读取本地字幕文件")
            elif transcript_source == "wechat_article":
                self._stage("subtitles", "done", "已读取公众号文章正文")
            elif subtitle_failure_message:
                self._stage("subtitles", "done", "字幕下载失败，已切换 Whisper 生成文本")
            else:
                self._stage("subtitles", "done", "未找到可用字幕，已使用 Whisper 生成文本")

            self._check_cancelled()
            prompt_engine = WechatArticlePromptEngine.from_config(self.cfg)
            self._stage("optimize", "running", "正在优化转写文本")
            optimized = _llm_or_fallback(
                self.cfg,
                prompt_engine.build_optimize_prompt(),
                transcript,
                model_key="article_llm_optimize_model",
                fallback_prefix="以下为原始转写整理稿：",
            )
            optimized_path = _write_text(output_dir / "optimized.txt", optimized)
            db.update_article_task(self.task_id, optimized_path=optimized_path)
            self._stage("optimize", "done", "转写文本已优化")

            self._check_cancelled()
            self._stage("style_analysis", "running", "正在分析来源风格")
            if _has_llm_surface(self.cfg):
                try:
                    style_profile = _llm_or_fallback(
                        self.cfg,
                        prompt_engine.build_style_analysis_prompt(source_type),
                        transcript,
                        model_key="article_llm_summary_model",
                        fallback_prefix="来源风格画像：",
                        temperature=0.1,
                    )
                    self._stage("style_analysis", "done", "来源风格画像已生成")
                except Exception as exc:
                    style_profile = _fallback_style_profile(source_type, transcript)
                    self._stage("style_analysis", "done", f"风格分析失败，已使用规则兜底：{_clean_error_message(exc)[:180]}")
            else:
                style_profile = _fallback_style_profile(source_type, transcript)
                self._stage("style_analysis", "done", "未配置 LLM，已使用规则风格画像")
            style_profile_path = _write_text(output_dir / "style_profile.txt", style_profile)

            self._check_cancelled()
            self._stage("summary", "running", "正在生成摘要")
            summary = _llm_or_fallback(
                self.cfg,
                prompt_engine.build_summary_prompt(),
                optimized,
                model_key="article_llm_summary_model",
                fallback_prefix="摘要：",
            )
            summary_path = _write_text(output_dir / "summary.txt", summary)
            db.update_article_task(self.task_id, summary_path=summary_path)
            self._stage("summary", "done", "摘要已生成")

            translated = ""
            target_lang = task.get("target_lang") or self.cfg.get("article_default_target_lang") or "zh-Hans"
            if task.get("auto_translate"):
                self._check_cancelled()
                if _has_llm_surface(self.cfg):
                    self._stage("translate", "running", "正在按目标语言生成正文")
                    translated = _llm_or_fallback(
                        self.cfg,
                        prompt_engine.build_rewrite_prompt(target_lang),
                        _article_generation_payload(
                            source_type=source_type,
                            title=video_title,
                            optimized=optimized,
                            summary=summary,
                            style_profile=style_profile,
                        ),
                        model_key="article_llm_translate_model",
                        fallback_prefix=f"目标语言 {target_lang} 正文：",
                        temperature=0.1,
                    )
                    translated_path = _write_text(output_dir / "translated.txt", translated)
                    db.update_article_task(self.task_id, translated_path=translated_path)
                    self._stage("translate", "done", "正文已生成")
                else:
                    self._stage("translate", "done", "未配置 LLM，保留整理稿作为正文")

            self._check_cancelled()
            body = translated or optimized
            quality_threshold = _article_quality_threshold(self.cfg)
            quality_record: dict[str, Any] = {
                "pipeline_version": _ARTICLE_PROMPT_PIPELINE_VERSION,
                "threshold": quality_threshold,
                "selected": "initial",
                "selection_status": "not_evaluated",
                "selected_passes_threshold": None,
                "initial": None,
                "revision": None,
            }
            quality_evaluation_path = ""
            revision_path = ""
            revision_applied = False
            if _has_llm_surface(self.cfg):
                self._stage("quality_review", "running", "正在评估文章质量")
                try:
                    initial_evaluation_text = _llm_or_fallback(
                        self.cfg,
                        prompt_engine.build_evaluation_prompt(target_lang),
                        _article_generation_payload(
                            source_type=source_type,
                            title=video_title,
                            optimized=optimized,
                            summary=summary,
                            style_profile=style_profile,
                            body=body,
                        ),
                        model_key="article_llm_evaluate_model",
                        fallback_prefix="质量评分：",
                        temperature=0.0,
                    )
                    initial_evaluation = _parse_article_quality_evaluation(
                        initial_evaluation_text,
                        quality_threshold,
                    )
                    quality_record["initial"] = initial_evaluation
                    initial_score = initial_evaluation.get("score")
                    if initial_score is None:
                        quality_record["selection_status"] = "initial_score_unparsed"
                        quality_record["selected_passes_threshold"] = False
                    else:
                        initial_passed = initial_score >= quality_threshold
                        quality_record["selection_status"] = (
                            "initial_passed_threshold" if initial_passed else "initial_below_threshold"
                        )
                        quality_record["selected_passes_threshold"] = initial_passed
                    self._stage(
                        "quality_review",
                        "done",
                        f"文章质量评分：{initial_evaluation.get('score') if initial_evaluation.get('score') is not None else '未解析'}/10",
                    )
                    if initial_score is not None and initial_score < quality_threshold:
                        self._check_cancelled()
                        self._stage("revision", "running", f"评分低于 {quality_threshold:g}，正在修订正文")
                        revised_body = _llm_or_fallback(
                            self.cfg,
                            prompt_engine.build_revision_prompt(target_lang),
                            _article_generation_payload(
                                source_type=source_type,
                                title=video_title,
                                optimized=optimized,
                                summary=summary,
                                style_profile=style_profile,
                                body=body,
                                evaluation=initial_evaluation,
                            ),
                            model_key="article_llm_translate_model",
                            fallback_prefix=f"目标语言 {target_lang} 修订正文：",
                            temperature=0.1,
                        )
                        revision_path = _write_text(output_dir / "revision.md", revised_body)
                        revision_evaluation_text = _llm_or_fallback(
                            self.cfg,
                            prompt_engine.build_evaluation_prompt(target_lang),
                            _article_generation_payload(
                                source_type=source_type,
                                title=video_title,
                                optimized=optimized,
                                summary=summary,
                                style_profile=style_profile,
                                body=revised_body,
                            ),
                            model_key="article_llm_evaluate_model",
                            fallback_prefix="质量评分：",
                            temperature=0.0,
                        )
                        revision_evaluation = _parse_article_quality_evaluation(
                            revision_evaluation_text,
                            quality_threshold,
                        )
                        quality_record["revision"] = revision_evaluation
                        revision_score = revision_evaluation.get("score")
                        if revision_score is not None and revision_score >= initial_score:
                            body = revised_body
                            quality_record["selected"] = "revision"
                            revision_applied = True
                            revision_passed = revision_score >= quality_threshold
                            quality_record["selection_status"] = (
                                "revision_passed_threshold"
                                if revision_passed
                                else "revision_improved_but_below_threshold"
                            )
                            quality_record["selected_passes_threshold"] = revision_passed
                            stage_message = (
                                f"已采用修订稿，复评 {revision_score}/10"
                                if revision_passed
                                else f"已采用更优修订稿，复评 {revision_score}/10，仍低于阈值 {quality_threshold:g}"
                            )
                            self._stage(
                                "revision",
                                "done",
                                stage_message,
                            )
                        else:
                            quality_record["selection_status"] = "initial_retained_after_revision"
                            quality_record["selected_passes_threshold"] = False
                            self._stage("revision", "done", "修订稿评分未提升，保留初稿")
                    quality_evaluation_path = _write_text(
                        output_dir / "article_evaluation.json",
                        json.dumps(quality_record, ensure_ascii=False, indent=2),
                    )
                except Exception as exc:
                    quality_record["error"] = _clean_error_message(exc)
                    quality_evaluation_path = _write_text(
                        output_dir / "article_evaluation.json",
                        json.dumps(quality_record, ensure_ascii=False, indent=2),
                    )
                    self._stage("quality_review", "done", f"质量评估失败，已记录错误并跳过修订：{_clean_error_message(exc)[:180]}")
            else:
                quality_record["skipped"] = "未配置 LLM，跳过自动评分。"
                quality_evaluation_path = _write_text(
                    output_dir / "article_evaluation.json",
                    json.dumps(quality_record, ensure_ascii=False, indent=2),
                )
                self._stage("quality_review", "done", "未配置 LLM，跳过自动评分")

            # 自动生成配图（如已配置图片生成服务）
            _generated_image_paths: list[str] = []
            image_provider = str(self.cfg.get("image_generation_provider") or "").strip()
            if image_provider and len(body.strip()) >= 300:
                self._stage("illustration", "running", "正在生成配图")
                try:
                    from scripts.article_image_generator import generate_illustrations
                    body, _generated_image_paths = generate_illustrations(
                        body,
                        video_title,
                        output_dir,
                        self.cfg,
                        source_type=source_type,
                        video_path=video_path,
                    )
                    if _generated_image_paths:
                        self._stage("illustration", "done", f"已插入 {len(_generated_image_paths)} 张配图")
                    else:
                        self._stage("illustration", "done", "未生成配图")
                except Exception as exc:
                    self._stage("illustration", "error", f"配图生成异常: {exc}")

            self._check_cancelled()
            final_body_path = _write_text(output_dir / "final_body.md", body)
            selected_quality = quality_record.get(str(quality_record.get("selected") or "initial"))
            if not isinstance(selected_quality, dict):
                selected_quality = {}

            self._stage("publish_optimize", "running", "正在生成发布标题、摘要和正文")
            from scripts.article_publish_optimizer import build_publish_markdown, optimize_for_publish

            publish_optimization = optimize_for_publish(
                body=body,
                seed_title=str(video_title or self.task_id),
                seed_summary=summary,
                cfg=self.cfg,
                image_paths=_generated_image_paths,
            )
            title_candidates_path = _write_text(
                output_dir / "title_candidates.json",
                json.dumps(
                    [candidate.to_dict() for candidate in publish_optimization.title_candidates],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            aigc_report_path = _write_text(
                output_dir / "zhuque_detection_report.json",
                json.dumps(publish_optimization.aigc_report, ensure_ascii=False, indent=2),
            )
            author = self.cfg.get("article_author") or self.cfg.get("wechat_default_author") or ""
            publish_markdown = build_publish_markdown(
                publish_optimization.title,
                str(author),
                publish_optimization.summary,
                publish_optimization.body,
            )
            publish_path = _write_text(output_dir / "wechat_publish.md", publish_markdown)
            self._stage("publish_optimize", "done", f"发布稿已生成：{publish_optimization.title}")

            self._stage("draft", "running", "正在写入 draft.md")
            draft = self._build_draft(video_title, summary, body)
            draft_path = _write_text(output_dir / "draft.md", draft)
            result = self._build_result(
                draft_path,
                output_dir,
                render_path=publish_path,
                transcript_source=transcript_source,
                subtitle_details=subtitle_details,
                article_metadata={
                    "article_prompt_pipeline_version": _ARTICLE_PROMPT_PIPELINE_VERSION,
                    "article_style_profile_path": style_profile_path,
                    "article_evaluation_path": quality_evaluation_path,
                    "article_final_body_path": final_body_path,
                    "article_quality_threshold": quality_threshold,
                    "article_quality_score": selected_quality.get("score"),
                    "article_quality_rationale": selected_quality.get("rationale") or "",
                    "article_quality_passed": quality_record.get("selected_passes_threshold"),
                    "article_quality_selection_status": quality_record.get("selection_status") or "",
                    "article_revision_applied": revision_applied,
                    "article_revision_path": revision_path,
                    "article_publish_markdown_path": publish_path,
                    "article_publish_title": publish_optimization.title,
                    "article_publish_summary": publish_optimization.summary,
                    "article_title_candidates_path": title_candidates_path,
                    "article_aigc_detection_report_path": aigc_report_path,
                    "article_aigc_detection_status": publish_optimization.aigc_report.get("status"),
                },
            )
            if _generated_image_paths:
                result["image_paths"] = _generated_image_paths
            self._stage("draft", "done", "draft.md 已生成")
            db.update_article_task(self.task_id, draft_path=draft_path, result=result)

            # 自动发布到微信公众号（如已配置）
            wechat_app_id = str(self.cfg.get("wechat_app_id") or "").strip()
            wechat_app_secret = str(self.cfg.get("wechat_app_secret") or "").strip()
            if wechat_app_id and wechat_app_secret:
                self._stage("wechat", "running", "正在发布到微信公众号")
                try:
                    from monitor.wechat_publisher import (
                        WechatPublisher,
                        render_md_to_html_for_wechat,
                        validate_wechat_article_payload,
                    )

                    publisher = WechatPublisher(
                        app_id=wechat_app_id,
                        app_secret=wechat_app_secret,
                        data_dir=str(output_root),
                    )
                    render_result = render_md_to_html_for_wechat(
                        publish_path,
                        theme=str(self.cfg.get("wechat_default_theme") or "default"),
                        color=str(self.cfg.get("wechat_default_color") or "blue"),
                        renderer=str(self.cfg.get("wechat_markdown_renderer") or "auto"),
                        baoyu_script=str(self.cfg.get("wechat_baoyu_markdown_to_html_script") or ""),
                        enable_ai_cover=bool(self.cfg.get("wechat_baoyu_ai_cover")),
                        enable_layout_modules=bool(self.cfg.get("wechat_baoyu_layout_modules")),
                    )
                    author_for_wx = (
                        render_result.author
                        or str(self.cfg.get("wechat_default_author") or "").strip()
                        or None
                    )
                    validation_errors = validate_wechat_article_payload(
                        title=render_result.title,
                        content=render_result.content,
                        author=author_for_wx,
                        digest=render_result.digest,
                    )
                    if validation_errors:
                        raise RuntimeError("微信文章校验失败: " + "；".join(validation_errors))
                    # AI 封面优先于显式封面
                    effective_cover = (
                        getattr(render_result, "cover_image_path", None)
                        or str(self.cfg.get("wechat_cover_image") or "").strip()
                        or None
                    )
                    wx_result = publisher.save_to_draft(
                        title=render_result.title,
                        content=render_result.content,
                        author=author_for_wx,
                        cover_image=effective_cover,
                        digest=render_result.digest,
                        need_open_comment=bool(self.cfg.get("wechat_need_open_comment", True)),
                        only_fans_can_comment=bool(self.cfg.get("wechat_only_fans_can_comment", False)),
                        base_dir=output_dir,
                    )
                    if wx_result.success:
                        self._stage("wechat", "done", f"已发布到微信公众号，media_id={wx_result.wx_article_id}")
                        result["wx_article_id"] = wx_result.wx_article_id
                        result["wx_url"] = wx_result.wx_url
                    else:
                        self._stage("wechat", "error", f"发布失败: {wx_result.error}")
                        result["wx_error"] = wx_result.error
                    db.update_article_task(self.task_id, result=result)
                except Exception as exc:
                    self._stage("wechat", "error", f"发布异常: {exc}")

            db.update_article_task(
                self.task_id,
                status="done",
                current_stage="done",
                draft_path=draft_path,
                stages=self.stages,
                result=result,
                finished_at=db.now_iso(),
            )
            return db.get_article_task(self.task_id) or {}
        except ArticleTaskCancelled as exc:
            db.update_article_task(
                self.task_id,
                status="cancelled",
                error=str(exc),
                cancel_requested=False,
                finished_at=db.now_iso(),
            )
            return db.get_article_task(self.task_id) or {}
        except Exception as exc:
            db.update_article_task(
                self.task_id,
                status="error",
                error=_clean_error_message(exc),
                finished_at=db.now_iso(),
            )
            return db.get_article_task(self.task_id) or {}

    def _build_draft(self, title: str, summary: str, body: str) -> str:
        author = self.cfg.get("article_author") or self.cfg.get("wechat_default_author") or ""
        clean_summary = _strip_llm_thinking_blocks(summary)
        clean_body = _strip_llm_thinking_blocks(body)
        digest = _markdown_plain_text(clean_summary)[:128]
        meta = {
            "type": "article",
            "title": title,
            "author": author,
            "task_id": self.task_id,
        }
        frontmatter = (
            "---\n"
            f"title: {_yaml_scalar(title)}\n"
            f"author: {_yaml_scalar(author)}\n"
            f"summary: {_yaml_scalar(digest)}\n"
            "---\n\n"
        )
        return (
            frontmatter
            +
            f"类型：文章\n选题：{title}\n生成时间：{db.now_iso()}\n\n"
            "```json\n"
            + json.dumps(meta, ensure_ascii=False, indent=2)
            + "\n```\n\n"
            f"## 摘要\n\n{clean_summary}\n\n---\n\n{clean_body}\n"
        )

    def _build_result(
        self,
        draft_path: str,
        output_dir: Path,
        *,
        render_path: str | None = None,
        transcript_source: str = "",
        subtitle_details: dict[str, Any] | None = None,
        article_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tools_path = str(self.cfg.get("article_tools_path") or "").strip()
        result = {
            "draft_path": draft_path,
            "draft_url": _generated_file_url(draft_path),
            "output_dir": str(output_dir),
            "transcript_source": transcript_source,
            "subtitle_details": subtitle_details or {},
            "quick_links": {},
        }
        if article_metadata:
            result.update(article_metadata)
        if tools_path:
            encoded = Path(render_path or draft_path).as_posix()
            result["quick_links"] = {
                "cover": f"{tools_path.rstrip('/')}/cover.html?open={encoded}",
                "wechat": f"{tools_path.rstrip('/')}/md-to-wechat.html?open={encoded}",
                "x": f"{tools_path.rstrip('/')}/md-to-x.html?open={encoded}",
            }
        try:
            from monitor.wechat_publisher import render_md_to_html_for_wechat

            render_result = render_md_to_html_for_wechat(
                render_path or draft_path,
                theme=str(self.cfg.get("wechat_default_theme") or "default"),
                color=str(self.cfg.get("wechat_default_color") or "blue"),
                renderer=str(self.cfg.get("wechat_markdown_renderer") or "auto"),
                baoyu_script=str(self.cfg.get("wechat_baoyu_markdown_to_html_script") or ""),
                enable_ai_cover=bool(self.cfg.get("wechat_baoyu_ai_cover")),
                enable_layout_modules=bool(self.cfg.get("wechat_baoyu_layout_modules")),
            )
            result["wechat_renderer"] = render_result.renderer
            result["wechat_html_path"] = render_result.html_path
            if render_result.html_path:
                result["wechat_html_url"] = _generated_file_url(render_result.html_path)
            result["wechat_digest"] = render_result.digest or ""
            if render_result.warnings:
                result["wechat_render_warnings"] = render_result.warnings
        except Exception as exc:
            result["wechat_render_error"] = _clean_error_message(exc)
        return result


def run_article_task(task_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return ArticleGenerationPipeline(task_id, cfg=cfg).run()

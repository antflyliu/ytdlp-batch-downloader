"""
config/settings.py — Application configuration management

Extracts config I/O logic from monitor/db.py.
Uses utils.paths for PyInstaller-compatible path resolution.
"""
from __future__ import annotations

import json
import os

from utils.paths import get_config_path, get_data_dir, get_pkg_dir

# ── Constants ──────────────────────────────────────────────────

DEFAULT_PROXY_PROTOCOL_ORDER = ("http", "https", "socks5", "socks4")

_GLOBAL_WEBHOOK_KEYS = (
    "global_feishu_url",
    "global_dingtalk_url",
    "global_dingtalk_sign_secret",
    "global_wecom_url",
    "global_telegram_token",
)

_SECRET_CONFIG_KEYS = (
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
    "wechat_api_proxy_token",
    "wechat_exporter_auth_key",
    "sph_cookie",  # 微信视频号 SPH 解析 cookie
)


# ── Helpers ────────────────────────────────────────────────────

def _write_config(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── Default config ──────────────────────────────────────────────

def _config_default() -> dict:
    """默认的全局配置"""
    data_dir = get_data_dir()
    article_output_dir = os.path.join(data_dir, "ai-articles")
    video_output_dir = os.path.join(data_dir, "video-gen")
    voice_output_dir = os.path.join(data_dir, "voice")
    default_template = "1080x1920/image_default.html"
    return {
        "global_feishu_url": "",
        "global_dingtalk_url": "",
        "global_dingtalk_sign_secret": "",
        "global_wecom_url": "",
        "global_telegram_token": "",
        "global_telegram_chat_id": "",
        "default_fetch_mode": "playlist",
        "default_fetch_limit": 5,
        "default_scan_interval": 5,
        "quota_budget_per_day": 8000,
        # ── 监控运维（见 docs/monitor-ops-optimization-backlog）────────────────
        "channel_meta_max_age_days": 30,
        "notify_on_scan_error": False,
        "scan_error_notify_cooldown_seconds": 300,
        "quota_usage_timezone": "local",
        "scan_jitter_seconds": 0,
        "quota_alert_thresholds": [80, 90, 100],
        "channel_meta_health_check_enabled": True,
        "channel_meta_health_check_interval_hours": 24,
        "notify_on_channel_meta_mismatch": True,
        "download_cookies_file": "",
        "download_output_path": "",
        "default_sub_langs": "zh-Hans,en",
        "default_api_key_id": None,
        # ── 系统默认动态代理配置 ──────────────────────────────
        "system_dynamic_proxy_enabled": False,
        "apply_dynamic_proxy_to_new_accounts": True,
        "apply_dynamic_proxy_to_existing_accounts": False,
        "manual_download_route_policy": "balanced",
        "auto_download_route_policy": "strict",
        "allow_free_proxy": True,
        "allow_free_proxy_for_auto_download": False,
        "allow_free_proxy_with_cookies": False,
        "manual_direct_fallback": True,
        "auto_direct_fallback": False,
        "default_proxy_country_codes": [],
        "default_proxy_protocol_order": list(DEFAULT_PROXY_PROTOCOL_ORDER),
        "default_session_mode": "sticky",
        "default_sticky_minutes": 10,
        "candidate_prefetch_count": 5,
        "candidate_validate_count": 3,
        "validated_pool_ttl_seconds": 300,
        "provider_cooldown_seconds": 600,
        "proxy_probe_timeout_seconds": 8,
        "mask_proxy_in_logs": True,
        # ── AI 视频切片配置 ──────────────────────────────
        "llm_provider": "qwen",
        "llm_api_key": "",
        "llm_model": "",
        "llm_base_url": "",
        "llm_min_score": 7.0,
        "llm_category": "knowledge",
        # ── 视频切片增强配置 ─────────────────────────────────
        "clip_embed_thumbnail": True,       # 生成封面图
        "clip_embed_subtitle": True,       # 软字幕封装（mkv）
        "clip_adapt_aspect_ratio": True,   # 长宽比自适应（原片9:16输出9:16）
        "clip_thumbnail_quality": 2,       # JPEG 压缩质量（1=最高，31=最低）
        # ── 自动切片配置 ─────────────────────────────────────
        "auto_clip_enabled": False,          # 下载完成后自动触发 AI 切片
        "auto_clip_notify_enabled": False,    # 切片完成后发送通知
        # ── AI 文章生成配置 ─────────────────────────────────────
        "whisper_provider": "api",   # "api" = remote API, "local" = faster-whisper
        "whisper_base_url": "",
        "whisper_api_key": "",
        "whisper_model": "base",
        "whisper_compute_type": "auto",
        "whisper_device": "auto",
        "whisper_chunk_seconds": 30,
        "whisper_language": "auto",
        "article_output_dir": article_output_dir,
        "article_default_target_lang": "zh-Hans",
        "article_target_lang": "zh-Hans",
        "article_subtitle_languages": "en,zh-Hans,zh-Hant,zh,ja,ko",
        "article_subtitle_proxy": "",
        "article_subtitle_proxy_mode": "auto",
        "article_subtitle_proxy_pool_id": None,
        "article_tools_path": "",
        "article_author": "",
        "gmail_oauth_client_id": "",
        "gmail_oauth_client_secret": "",
        "gmail_oauth_redirect_uri": "",
        "gmail_oauth_scopes": "https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send",
        "email_analysis_rules": {},
        "article_wechat_prompt_role": "资深科技自媒体作者",
        "article_wechat_prompt_reader_persona": "关注 AI、效率工具和内容创作的中文读者",
        "article_wechat_prompt_style": "信息密度高、短段落、有明确小标题，保留必要的列表、表格和代码块",
        "article_wechat_prompt_max_chars": 6000,
        "article_llm_optimize_model": "",
        "article_llm_summary_model": "",
        "article_llm_translate_model": "",
        "article_optimize_model": "",
        "article_summary_model": "",
        "article_translate_model": "",
        # ── AI 视频生成配置 ─────────────────────────────────────
        "comfyui_url": "",
        "comfyui_api_key": "",
        "runninghub_url": "",
        "runninghub_api_key": "",
        "tts_provider": "local",
        "local_tts_url": "",
        "video_gen_output_dir": video_output_dir,
        # ── AI 语音 Provider 配置 ─────────────────────────────────
        "voice_provider": "edge_tts",
        "voice_fallback_order": "edge_tts,local_http_tts,silent",
        "voice_flow_defaults_json": "{}",
        "voice_output_dir": voice_output_dir,
        "voice_require_disclosure": True,
        "voice_allow_reference_clone": False,
        "voice_allow_prompt_transcript_clone": False,
        "voice_max_text_chars": 5000,
        "transcription_provider": "whisper_api",
        "openai_speech_base_url": "https://api.openai.com/v1",
        "openai_speech_api_key": "",
        "openai_speech_model": "gpt-4o-mini-tts",
        "openai_speech_voice": "alloy",
        "azure_speech_region": "",
        "azure_speech_endpoint": "",
        "azure_speech_api_key": "",
        "azure_speech_voice": "",
        "azure_speech_output_format": "riff-24khz-16bit-mono-pcm",
        "minimax_speech_base_url": "https://api.minimax.io",
        "minimax_speech_api_key": "",
        "minimax_speech_model": "speech-2.8-hd",
        "minimax_speech_voice": "",
        "voxcpm_base_url": "",
        "voxcpm_api_key": "",
        "voxcpm_model": "openbmb/VoxCPM2",
        "voxcpm_default_voice": "default",
        "voxcpm_default_control_instruction": "",
        "vibevoice_tts_base_url": "",
        "vibevoice_tts_api_key": "",
        "vibevoice_tts_model": "microsoft/VibeVoice-Realtime-0.5B",
        "vibevoice_tts_voice": "Carter",
        "vibevoice_asr_base_url": "",
        "vibevoice_asr_api_key": "",
        "vibevoice_asr_model": "microsoft/VibeVoice-ASR",
        "video_gen_default_template": default_template,
        "video_gen_default_scene_count": 5,
        "default_template": default_template,
        "default_scene_count": 5,
        "video_gen_prompt_prefix": "clean editorial illustration",
        # ── AI 图片生成配置 ─────────────────────────────────────
        "image_generation_provider": "minimax",
        "image_generation_fallback_order": "minimax,openai,gemini,local",
        "image_generation_timeout_seconds": 300,
        "minimax_api_key": "",
        "minimax_base_url": "https://api.minimaxi.com",
        "minimax_image_model": "image-01",
        "openai_api_key": "",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_image_model": "gpt-image-2",
        "openai_image_size": "1536x1024",
        "openai_image_quality": "medium",
        "gemini_api_key": "",
        "gemini_base_url": "https://generativelanguage.googleapis.com",
        "gemini_image_model": "imagen-4.0-generate-001",
        # ── 微信公众号发布配置 ─────────────────────────────────────
        "wechat_app_id": "",
        "wechat_app_secret": "",
        "wechat_api_proxy_url": "",
        "wechat_api_proxy_token": "",
        "wechat_default_author": "",
        "wechat_default_theme": "default",
        "wechat_default_color": "blue",
        "wechat_markdown_renderer": "auto",
        "wechat_baoyu_markdown_to_html_script": "",
        "wechat_baoyu_ai_cover": False,
        "wechat_baoyu_layout_modules": False,
        "wechat_baoyu_timeout": 120,
        "wechat_publish_monthly_limit": 4,
        "wechat_need_open_comment": True,
        "wechat_only_fans_can_comment": False,
        # ── 微信公众号采集配置 ─────────────────────────────────────
        "wechat_exporter_base_url": "https://down.mptext.top",
        "wechat_exporter_auth_key": "",
        "wechat_collection_output_dir": os.path.join(data_dir, "wechat-articles"),
        "wechat_collection_default_format": "markdown",
        "wechat_collection_delay_seconds": 1.0,
        "wechat_collection_max_articles": 50,
        # ── 资源嗅探 ──────────────────────────────────────────
        "proxy_sniffer_enabled": False,      # 默认关闭，手动在配置中心开启
        "proxy_sniffer_port": 8899,          # Go 子进程监听端口
        # ── 微信视频号 SPH 解析 ─────────────────────────────
        "sph_cookie": "",                          # 加密存储，hy_source/web; hy_user/...; hy_token/...
        "sph_cookie_updated_at": "",                # ISO8601，前端展示用
        "sph_cookie_source": "manual",              # "manual" / "playwright"
        "sph_cookie_auto_refresh": False,           # 是否启用 Playwright 自动刷新
    }


# ── Public API ─────────────────────────────────────────────────

def load_config() -> dict:
    """加载全局配置（支持 PyInstaller exe 和源码两种模式）"""
    _cfg_path = get_config_path()
    _pkg_dir = get_pkg_dir()

    source_path = None
    raw_cfg = None
    if os.path.exists(_cfg_path):
        source_path = _cfg_path
        with open(_cfg_path, "r", encoding="utf-8") as f:
            raw_cfg = json.load(f)
    else:
        pkg_cfg = os.path.join(_pkg_dir, "config.json")
        if os.path.exists(pkg_cfg):
            source_path = pkg_cfg
            with open(pkg_cfg, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
    if raw_cfg is None:
        return _config_default()

    raw_cfg = {**_config_default(), **raw_cfg}
    encrypted_cfg = _encrypt_config_references(
        _encrypt_config_secrets(_encrypt_config_webhooks(raw_cfg))
    )
    if source_path and encrypted_cfg != raw_cfg:
        _write_config(source_path, encrypted_cfg)
    return _decrypt_config_references(
        _decrypt_config_secrets(_decrypt_config_webhooks(encrypted_cfg))
    )


def save_config(cfg: dict) -> None:
    """保存全局配置，Webhook URL 落盘时加密。"""
    from config.validation import normalize_dingtalk_sign_secret

    _cfg_path = get_config_path()

    cfg = {**_config_default(), **(cfg or {})}
    cfg["global_dingtalk_sign_secret"] = (
        normalize_dingtalk_sign_secret(cfg.get("global_dingtalk_sign_secret")) or ""
    )
    _write_config(
        _cfg_path,
        _encrypt_config_references(_encrypt_config_secrets(_encrypt_config_webhooks(cfg))),
    )
    try:
        import monitor.quota as _quota

        _quota.invalidate_config_cache()
    except Exception:
        pass


# ── SPH cookie helpers ───────────────────────────────────────────

def get_sph_cookie() -> str:
    """返回当前解密后的 sph_cookie 值（运行时解密，不读盘）。"""
    return load_config().get("sph_cookie") or ""


def set_sph_cookie(value: str, *, source: str = "manual") -> None:
    """持久化 sph_cookie 到 config.json（加密存储）。"""
    import datetime

    cfg = {**load_config()}
    cfg["sph_cookie"] = value or ""
    cfg["sph_cookie_updated_at"] = datetime.datetime.now().isoformat()
    cfg["sph_cookie_source"] = source
    save_config(cfg)


# ── Internal helpers (used by save_config / load_config) ────────

def _encrypt_config_webhooks(cfg: dict) -> dict:
    """加密全局 webhook 配置字段"""
    from config.encryption import _encrypt_webhook as _enc
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _enc(cfg.get(key)) or ""
    return cfg


def _decrypt_config_webhooks(cfg: dict) -> dict:
    """解密全局 webhook 配置字段"""
    from config.encryption import _decrypt_webhook as _dec
    cfg = {**_config_default(), **cfg}
    for key in _GLOBAL_WEBHOOK_KEYS:
        cfg[key] = _dec(cfg.get(key)) or ""
    return cfg


def _encrypt_config_secrets(cfg: dict) -> dict:
    """Encrypt API-key style config secrets at rest."""
    from config.encryption import _encrypt_config_value

    cfg = {**_config_default(), **cfg}
    for key in _SECRET_CONFIG_KEYS:
        value = cfg.get(key)
        if isinstance(value, str) and value and not value.startswith("enc:"):
            cfg[key] = _encrypt_config_value(value)
    return cfg


def _decrypt_config_secrets(cfg: dict) -> dict:
    """Decrypt API-key style config secrets for runtime use."""
    from config.encryption import _decrypt_config_value

    cfg = {**_config_default(), **cfg}
    for key in _SECRET_CONFIG_KEYS:
        value = cfg.get(key)
        if isinstance(value, str) and value.startswith("enc:"):
            cfg[key] = _decrypt_config_value(value)
    return cfg


def _encrypt_config_references(cfg: dict) -> dict:
    """Encrypt sensitive-looking config references while keeping runtime semantics."""
    from config.encryption import _encrypt_config_value

    cfg = {**_config_default(), **cfg}
    default_api_key_id = cfg.get("default_api_key_id")
    if default_api_key_id not in (None, ""):
        cfg["default_api_key_id"] = _encrypt_config_value(str(default_api_key_id))
    return cfg


def _decrypt_config_references(cfg: dict) -> dict:
    """Decrypt config references that are stored encrypted at rest."""
    from config.encryption import _decrypt_config_value

    cfg = {**_config_default(), **cfg}
    default_api_key_id = cfg.get("default_api_key_id")
    if isinstance(default_api_key_id, str) and default_api_key_id.startswith("enc:"):
        cfg["default_api_key_id"] = _decrypt_config_value(default_api_key_id)
    return cfg

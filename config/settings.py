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


# ── Helpers ────────────────────────────────────────────────────

def _write_config(path: str, cfg: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── Default config ──────────────────────────────────────────────

def _config_default() -> dict:
    """默认的全局配置"""
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
        # ── 资源嗅探 ──────────────────────────────────────────
        "proxy_sniffer_enabled": False,      # 默认关闭，手动在配置中心开启
        "proxy_sniffer_port": 8899,          # Go 子进程监听端口
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
    runtime_cfg = _normalize_plain_config_ids(_decrypt_config_webhooks(raw_cfg))
    encrypted_cfg = _encrypt_config_webhooks(runtime_cfg)
    if source_path and encrypted_cfg != raw_cfg:
        _write_config(source_path, encrypted_cfg)
    return runtime_cfg


def save_config(cfg: dict) -> None:
    """保存全局配置，Webhook URL 落盘时加密。"""
    from config.validation import normalize_dingtalk_sign_secret

    _cfg_path = get_config_path()

    cfg = {**_config_default(), **(cfg or {})}
    cfg["global_dingtalk_sign_secret"] = (
        normalize_dingtalk_sign_secret(cfg.get("global_dingtalk_sign_secret")) or ""
    )
    _write_config(_cfg_path, _encrypt_config_webhooks(cfg))
    try:
        import monitor.quota as _quota

        _quota.invalidate_config_cache()
    except Exception:
        pass


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


def _normalize_plain_config_ids(cfg: dict) -> dict:
    """Normalize non-secret id fields that older builds may have encrypted."""
    from config.encryption import _decrypt_config_value

    cfg = {**_config_default(), **cfg}
    default_api_key_id = cfg.get("default_api_key_id")
    if isinstance(default_api_key_id, str) and default_api_key_id.startswith("enc:"):
        cfg["default_api_key_id"] = _decrypt_config_value(default_api_key_id)
    return cfg

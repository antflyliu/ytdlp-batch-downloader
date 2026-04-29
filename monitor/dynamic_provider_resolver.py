"""
monitor/dynamic_provider_resolver.py — Dynamic Provider Resolution for Download

Adapts proxy_router results for use with Youtube_Downloader.batch_download().
Handles both manual and auto download contexts.
"""
from __future__ import annotations

import logging_config
import monitor.db as _db
from monitor.proxy_router import (
    resolve_download_proxy,
    ProxyRouteResult,
    resolve_proxy_download,
)

_log = logging_config.get_logger("dynamic_provider_resolver")


def resolve_for_manual_download(account_id: int, cookies_file_present: bool = False) -> ProxyRouteResult:
    """
    Resolve proxy for manual download (triggered by user from Web UI).

    Args:
        account_id:          The monitor account ID
        cookies_file_present: True if a cookies file will be used for this download

    Returns:
        ProxyRouteResult with resolved proxy info
    """
    return resolve_download_proxy(
        account_id=account_id,
        is_auto_download=False,
        cookies_file_present=cookies_file_present,
        user_forced_direct=False,
    )


def resolve_for_auto_download(account_id: int) -> ProxyRouteResult:
    """
    Resolve proxy for auto download (triggered by scheduler).

    Auto download has stricter constraints:
    - Does not use cookies by default
    - Disallows free proxy by default (configurable)
    - Does not silently fallback to direct by default

    Args:
        account_id: The monitor account ID

    Returns:
        ProxyRouteResult with resolved proxy info
    """
    return resolve_download_proxy(
        account_id=account_id,
        is_auto_download=True,
        cookies_file_present=False,
        user_forced_direct=False,
    )


def resolve_for_web_batch_download(
    proxy_pool_id: int | None = None,
    cookies_file_present: bool = False,
    user_forced_direct: bool = False,
) -> ProxyRouteResult:
    """
    Resolve proxy for Web UI batch download without requiring a monitor account.

    Args:
        proxy_pool_id: Optional fixed proxy pool selected by the user.
        cookies_file_present: True if a cookies file will be used for this download.
        user_forced_direct: True if the caller explicitly requested direct download.
    """
    pseudo_account = {
        "id": None,
        "name": "Web 批量下载",
        "download_proxy_mode": "account_only" if proxy_pool_id else "auto",
        "proxy_enabled": bool(proxy_pool_id),
        "proxy_pool_id": proxy_pool_id,
        # created_at 留空，按“新账户”规则走系统动态代理开关
        "created_at": None,
    }
    return resolve_proxy_download(
        pseudo_account,
        is_auto_download=False,
        cookies_file_present=cookies_file_present,
        user_forced_direct=user_forced_direct,
    )


def log_download_decision(
    route_result: ProxyRouteResult,
    account_id: int | None,
    account_name: str,
    video_count: int,
    is_auto_download: bool,
) -> None:
    """
    Log the download routing decision to the download_decision_logs table.

    Creates the table if it doesn't exist (via migration).

    Args:
        route_result:  The ProxyRouteResult from resolve_for_manual_download or resolve_for_auto_download
        account_id:    The monitor account ID
        account_name:  The account display name
        video_count:   Number of videos being downloaded
        is_auto_download: True if this is an auto download
    """
    try:
        _db.log_download_decision(
            account_id=account_id,
            account_name=account_name,
            video_count=video_count,
            is_auto_download=is_auto_download,
            cookies_present=route_result.cookies_file_present,
            resolved_proxy_source=route_result.resolved_proxy_source,
            resolved_provider_name=route_result.provider_name,
            resolved_provider_tier=route_result.provider_tier,
            resolved_country=None,
            resolved_session_mode=route_result.session_mode,
            fallback_depth=route_result.fallback_depth,
            masked_proxy_endpoint=route_result.masked_proxy_endpoint,
            decision_reason=route_result.reason,
            warnings=",".join(route_result.warnings) if route_result.warnings else None,
        )
    except Exception as e:
        _log.warning(f"记录下载决策日志失败: {e}")

"""
经代理的候选节点轻量探测：在线程池中执行与 provider_health 相同的 urllib HEAD 探测，
供 CandidateProbeValidator 在 refresh 时写入真实的 last_probe_status。
"""
from __future__ import annotations

import asyncio
import logging

from monitor.proxy_validator import ProbeResult, ProxyValidator, _redact_error_message
from monitor.provider_health import ProbeResult as ProviderProbeResult
from monitor.provider_health import probe_proxy_url

_log = logging.getLogger(__name__)

_ALLOWED_CV = frozenset({"healthy", "degraded", "down", "auth_error", "unknown", "level2_skipped"})


def _provider_to_candidate_probe(ph: ProviderProbeResult) -> ProbeResult:
    """将网关探测结果转为候选探测用的 ProbeResult（字段子集）。"""
    lat = ph.latency_ms
    if lat is not None and lat < 0:
        lat = None
    status = ph.status
    if status not in _ALLOWED_CV:
        status = "down"
    return ProbeResult(status=status, latency_ms=lat, error_message=ph.error_message)


class UrllibCandidateTransport:
    """使用 provider_health.probe_proxy_url（同步）+ asyncio.to_thread 避免阻塞事件循环。"""

    async def probe_lightweight(self, candidate, timeout=8) -> ProbeResult:
        pv = ProxyValidator()
        level0 = pv.validate_level0(
            host=getattr(candidate, "host", ""),
            port=getattr(candidate, "port", 0),
            protocol=getattr(candidate, "protocol", "http"),
        )
        if level0.rejected:
            return ProbeResult(
                status="down",
                latency_ms=None,
                error_message=level0.reason or "校验未通过",
            )
        proxy_url = getattr(candidate, "proxy_url", None) or ""
        if not proxy_url.strip():
            return ProbeResult(status="down", latency_ms=None, error_message="缺少 proxy_url")
        scheme = (getattr(candidate, "protocol", None) or "http").lower()
        try:
            ph = await asyncio.to_thread(
                probe_proxy_url,
                proxy_url,
                scheme,
                float(timeout),
            )
        except Exception as exc:
            _log.debug("candidate probe thread failed: %s", exc, exc_info=True)
            return ProbeResult(
                status="down",
                latency_ms=None,
                error_message=_redact_error_message(str(exc)),
            )
        return _provider_to_candidate_probe(ph)

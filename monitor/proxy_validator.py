from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass
class ProbeResult:
    status: str
    latency_ms: int | None = None
    error_message: str | None = None
    rejected: bool = False
    reason: str | None = None


def _redact_error_message(message: str | None) -> str | None:
    if not message:
        return message

    redacted = message
    for token in message.split():
        prefix = ""
        suffix = ""
        core = token
        while core and core[0] in "([{'\"":
            prefix += core[0]
            core = core[1:]
        while core and core[-1] in ")]}'\".,;:":
            suffix = core[-1] + suffix
            core = core[:-1]
        try:
            parts = urlsplit(core)
        except Exception:
            continue
        if not parts.scheme or not parts.netloc:
            continue
        if parts.username is None and parts.password is None:
            continue
        host = parts.hostname or "***"
        port = f":{parts.port}" if parts.port else ""
        safe_core = urlunsplit((parts.scheme, f"***:****@{host}{port}", parts.path, parts.query, parts.fragment))
        redacted = redacted.replace(token, f"{prefix}{safe_core}{suffix}")

    return redacted


class CandidateProbeValidator:
    def __init__(self, transport=None):
        self._transport = transport

    async def probe_lightweight(self, candidate, timeout=8) -> ProbeResult:
        if self._transport is None:
            return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="未配置 transport")
        try:
            return await self._transport.probe_lightweight(candidate, timeout=timeout)
        except TimeoutError:
            return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="探测超时")
        except Exception as exc:
            return ProbeResult(status="down", latency_ms=None, error_message=_redact_error_message(str(exc)))

    async def probe_for_auto_download(self, candidate, should_probe=True, target="https://www.youtube.com", timeout=15) -> ProbeResult:
        if not should_probe:
            return ProbeResult(status="level2_skipped", reason="not_needed")
        if self._transport is None:
            return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="未配置 transport")
        lightweight = await self.probe_lightweight(candidate, timeout=timeout)
        if lightweight.status != "healthy":
            return lightweight
        try:
            return await self._transport.probe_target(candidate, target=target, timeout=timeout)
        except TimeoutError:
            return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="探测超时")
        except Exception as exc:
            return ProbeResult(status="down", latency_ms=None, error_message=_redact_error_message(str(exc)))


class ProxyValidator:
    def validate_level0(self, host, port, protocol, **fields) -> ProbeResult:
        try:
            port_num = int(port)
        except (TypeError, ValueError):
            return ProbeResult(status="down", rejected=True, reason="端口非法")

        if port_num < 1 or port_num > 65535:
            return ProbeResult(status="down", rejected=True, reason="端口非法")

        if protocol not in ("http", "https", "socks4", "socks5"):
            return ProbeResult(status="down", rejected=True, reason="协议非法")

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return ProbeResult(status="unknown", rejected=False, reason=None)

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return ProbeResult(status="down", rejected=True, reason="私网/保留地址")

        return ProbeResult(status="unknown", rejected=False, reason=None)

    async def _probe_level1(self, protocol, host, port, timeout=8) -> ProbeResult:
        return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="未实现探测")

    async def validate_level1(self, protocol, host, port, timeout=8) -> ProbeResult:
        level0 = self.validate_level0(host=host, port=port, protocol=protocol)
        if level0.rejected:
            return level0
        try:
            return await self._probe_level1(protocol, host, port, timeout=timeout)
        except TimeoutError:
            return ProbeResult(status="down", latency_ms=timeout * 1000, error_message="探测超时")
        except Exception as exc:
            return ProbeResult(status="down", latency_ms=None, error_message=str(exc))

    async def _probe_level2(self, protocol, host, port, target="https://www.youtube.com", timeout=15) -> ProbeResult:
        return await self.validate_level1(protocol, host, port, timeout=timeout)

    async def validate_level2(self, protocol, host, port, target="https://www.youtube.com", timeout=15, skip_reason=None) -> ProbeResult:
        level0 = self.validate_level0(host=host, port=port, protocol=protocol)
        if level0.rejected:
            return level0
        if skip_reason:
            return ProbeResult(status="level2_skipped", rejected=False, reason=skip_reason)
        return await self._probe_level2(protocol, host, port, target=target, timeout=timeout)

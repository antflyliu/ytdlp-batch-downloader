from pathlib import Path
import asyncio
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _candidate(**overrides):
    from monitor.proxy_router import CanonicalProxyCandidate

    defaults = {
        "candidate_key": "cand-1",
        "provider_id": 1,
        "provider_name": "ProviderA",
        "protocol": "http",
        "host": "8.8.8.8",
        "port": 8080,
        "proxy_url": "http://8.8.8.8:8080",
    }
    defaults.update(overrides)
    return CanonicalProxyCandidate(**defaults)


def test_probe_lightweight_returns_healthy_when_connect_and_head_succeed():
    from monitor.proxy_validator import CandidateProbeValidator, ProbeResult

    class FakeTransport:
        async def probe_lightweight(self, candidate, timeout=8):
            return ProbeResult(status="healthy", latency_ms=42, error_message=None)

    validator = CandidateProbeValidator(transport=FakeTransport())
    result = asyncio.run(validator.probe_lightweight(_candidate(), timeout=5))

    assert result.status == "healthy"
    assert result.latency_ms == 42
    assert result.error_message is None


def test_probe_lightweight_redacts_arbitrary_credentials_in_error_message():
    from monitor.proxy_validator import CandidateProbeValidator

    class FakeTransport:
        async def probe_lightweight(self, candidate, timeout=8):
            raise RuntimeError(f"connect failed for {candidate.proxy_url}")

    candidate = _candidate(
        username="bob",
        proxy_url="http://bob:hunter2@8.8.8.8:8080",
    )
    validator = CandidateProbeValidator(transport=FakeTransport())
    result = asyncio.run(validator.probe_lightweight(candidate, timeout=5))

    assert result.status == "down"
    assert "hunter2" not in (result.error_message or "")
    assert "bob:hunter2" not in (result.error_message or "")


def test_probe_lightweight_redacts_credentials_when_url_is_wrapped_in_punctuation():
    from monitor.proxy_validator import CandidateProbeValidator

    class FakeTransport:
        async def probe_lightweight(self, candidate, timeout=8):
            raise RuntimeError(f"connect failed ({candidate.proxy_url})")

    candidate = _candidate(
        username="carol",
        proxy_url="http://carol:s3cr3t@8.8.8.8:8080",
    )
    validator = CandidateProbeValidator(transport=FakeTransport())
    result = asyncio.run(validator.probe_lightweight(candidate, timeout=5))

    assert result.status == "down"
    assert "s3cr3t" not in (result.error_message or "")
    assert "carol:s3cr3t" not in (result.error_message or "")


def test_probe_for_auto_download_returns_healthy_when_lightweight_and_target_succeed():
    from monitor.proxy_validator import CandidateProbeValidator, ProbeResult

    calls = []

    class FakeTransport:
        async def probe_lightweight(self, candidate, timeout=8):
            calls.append(("lightweight", candidate.host, timeout))
            return ProbeResult(status="healthy", latency_ms=21, error_message=None)

        async def probe_target(self, candidate, target, timeout=15):
            calls.append(("target", target, timeout))
            return ProbeResult(status="healthy", latency_ms=77, error_message=None)

    validator = CandidateProbeValidator(transport=FakeTransport())
    result = asyncio.run(
        validator.probe_for_auto_download(
            _candidate(),
            should_probe=True,
            timeout=10,
        )
    )

    assert result.status == "healthy"
    assert result.latency_ms == 77
    assert result.error_message is None
    assert calls == [
        ("lightweight", "8.8.8.8", 10),
        ("target", "https://www.youtube.com", 10),
    ]


def test_level0_rejects_private_ip():
    from monitor.proxy_validator import ProxyValidator

    validator = ProxyValidator()
    result = validator.validate_level0(host="192.168.1.1", port=8080, protocol="http")

    assert result.rejected is True
    assert "私网" in (result.reason or "")
    assert result.status == "down"


def test_level0_accepts_public_ip():
    from monitor.proxy_validator import ProxyValidator

    result = ProxyValidator().validate_level0(host="8.8.8.8", port=8080, protocol="http")

    assert result.rejected is False
    assert result.status == "unknown"


def test_validate_level1_returns_healthy_with_latency_when_lightweight_probe_succeeds(monkeypatch):
    from monitor.proxy_validator import ProxyValidator, ProbeResult

    calls = []

    async def fake_probe(self, protocol, host, port, timeout=8):
        calls.append((protocol, host, port, timeout))
        return ProbeResult(status="healthy", latency_ms=88, error_message=None)

    validator = ProxyValidator()
    monkeypatch.setattr(validator, "_probe_level1", fake_probe.__get__(validator, ProxyValidator))

    result = asyncio.run(validator.validate_level1("http", "8.8.8.8", 8080, timeout=5))

    assert result.status == "healthy"
    assert result.latency_ms == 88
    assert result.error_message is None
    assert calls == [("http", "8.8.8.8", 8080, 5)]


def test_level2_returns_degraded_when_target_check_fails(monkeypatch):
    from monitor.proxy_validator import ProxyValidator, ProbeResult

    async def fake_probe(self, protocol, host, port, target="https://www.youtube.com", timeout=15):
        return ProbeResult(status="degraded", latency_ms=321, error_message="youtube check failed")

    validator = ProxyValidator()
    monkeypatch.setattr(validator, "_probe_level2", fake_probe.__get__(validator, ProxyValidator))

    result = asyncio.run(
        validator.validate_level2(
            "http",
            "8.8.8.8",
            8080,
            timeout=15,
        )
    )

    assert result.status == "degraded"
    assert result.error_message == "youtube check failed"

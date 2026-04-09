from __future__ import annotations

from monitor.proxy_candidate_pool import ProxyCandidatePool
from monitor.proxy_router import CanonicalProxyCandidate


def _preview_alignment_sort_key(cand: CanonicalProxyCandidate) -> tuple[int, int, float]:
    """与 monitor.db.pick_healthy_fastest_top_candidate / 候选预览「当前最优」排序一致。"""
    lm = cand.latency_ms
    if isinstance(lm, int) and lm >= 0:
        tier = 0
        lat = lm
    else:
        tier = 1
        lat = 0
    sc = float(cand.score) if isinstance(cand.score, (int, float)) else 0.0
    return (tier, lat, -sc)


class ProxySelector:
    """按场景从候选池选路（Task 6 skeleton）"""

    def __init__(self, candidate_pool: ProxyCandidatePool):
        self._pool = candidate_pool

    def select(
        self,
        provider_id: int,
        is_auto_download: bool,
        cookies_present: bool,
        country_codes: list[str] | None = None,
        protocol_order: list[str] | None = None,
        allow_free: bool = True,
        risk_threshold: str = "high",
        max_count: int = 5,
        billing_tier: str | None = None,
    ) -> list[CanonicalProxyCandidate]:
        candidates = self._pool.get_candidates_for_scenario(
            provider_id=provider_id,
            is_auto_download=is_auto_download,
            cookies_present=cookies_present,
            country_codes=country_codes,
            protocol_order=protocol_order,
        )
        filtered = self._filter_hard(
            candidates,
            is_auto_download=is_auto_download,
            cookies_present=cookies_present,
            allow_free=allow_free,
            billing_tier=billing_tier,
            risk_threshold=risk_threshold,
        )
        healthy = [
            c
            for c in filtered
            if str(c.last_probe_status or "").strip().lower() == "healthy"
        ]
        if healthy:
            ranked = sorted(healthy, key=_preview_alignment_sort_key)
        else:
            ranked = sorted(
                filtered,
                key=lambda cand: self._score(
                    cand, country_codes=country_codes, protocol_order=protocol_order
                ),
                reverse=True,
            )
        return ranked[:max_count]

    def _filter_hard(
        self,
        candidates: list[CanonicalProxyCandidate],
        *,
        is_auto_download: bool,
        cookies_present: bool,
        allow_free: bool,
        billing_tier: str | None,
        risk_threshold: str,
    ) -> list[CanonicalProxyCandidate]:
        result = []
        for cand in candidates:
            if cookies_present and not cand.supports_cookies:
                continue
            if is_auto_download and not cand.supports_auto_download:
                continue
            if billing_tier == "free" and not allow_free:
                continue
            if risk_threshold == "high" and cand.risk_level == "high":
                continue
            result.append(cand)
        return result

    def _score(
        self,
        cand: CanonicalProxyCandidate,
        country_codes: list[str] | None = None,
        protocol_order: list[str] | None = None,
    ) -> float:
        protocol_bonus = 0
        if protocol_order:
            ranking = {name: idx for idx, name in enumerate(protocol_order)}
            protocol_bonus = {0: 6, 1: 3}.get(ranking.get(cand.protocol, 99), 0)
        country_bonus = 5 if country_codes and cand.country_code in country_codes else 0
        skipped_penalty = -8 if cand.last_probe_status == "level2_skipped" else 0
        latency_penalty = min(15, (cand.latency_ms or 0) / 200)
        return (
            cand.score
            + (10 if cand.last_probe_status == "healthy" else -5)
            - min(20, cand.consecutive_failures * 4)
            - latency_penalty
            - (10 if cand.risk_level == "high" else 0)
            + protocol_bonus
            + country_bonus
            + skipped_penalty
        )

from __future__ import annotations

import hashlib
import json

from monitor.proxy_router import CanonicalProxyCandidate


class ProxyCandidatePool:
    """SQLite 持久候选池 + 内存热缓存（Task 5 skeleton）"""

    def __init__(self, db_module=None):
        import monitor.db as _db

        self._db = db_module or _db
        self._cache: dict[str, list[CanonicalProxyCandidate]] = {}

    def get_candidates_for_scenario(
        self,
        provider_id: int,
        is_auto_download: bool,
        cookies_present: bool,
        country_codes: list[str] | None = None,
        protocol_order: list[str] | None = None,
        fetch_limit: int = 5000,
    ) -> list[CanonicalProxyCandidate]:
        """
        拉取未过期候选的全集（默认最多 fetch_limit 条），不在此按 score 截断。
        截断仅用于防止异常大表拖内存；下载排序由 ProxySelector 与预览对齐（healthy + latency + score）。
        """
        cache_key = self._cache_key(
            provider_id,
            is_auto_download,
            cookies_present,
            country_codes=country_codes,
            protocol_order=protocol_order,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]

        rows = self._db.get_proxy_candidate_by_provider(
            provider_id, valid_only=True, order_by_score_desc=False
        )
        if fetch_limit > 0 and len(rows) > fetch_limit:
            rows = rows[:fetch_limit]
        candidates = [self._row_to_candidate(row) for row in rows]
        self._cache[cache_key] = candidates
        return candidates

    def save_provider_candidates(
        self,
        provider_id: int,
        candidates: list[CanonicalProxyCandidate],
        ttl_seconds: int | None = None,
    ) -> int:
        saved = 0
        ttl = 300 if ttl_seconds is None else ttl_seconds
        ttl_expires_at = self._db._iso_future(ttl)
        for candidate in candidates:
            self._db.add_proxy_candidate(
                provider_id=provider_id,
                protocol=candidate.protocol,
                host=candidate.host,
                port=candidate.port,
                username=candidate.username,
                auth_type=candidate.auth_type,
                country_code=candidate.country_code,
                region=candidate.region,
                city=candidate.city,
                anonymity=candidate.anonymity,
                risk_level=candidate.risk_level,
                supports_https=candidate.supports_https,
                supports_cookies=candidate.supports_cookies,
                supports_auto_download=candidate.supports_auto_download,
                supports_sticky_session=candidate.supports_sticky_session,
                latency_ms=candidate.latency_ms,
                last_probe_status=candidate.last_probe_status,
                last_probe_at=candidate.last_probe_at,
                score=candidate.score,
                provider_reference_id=candidate.provider_reference_id,
                ttl_expires_at=ttl_expires_at,
                masked_proxy_endpoint=None,
            )
            saved += 1

        self._cache = {}
        return saved

    def _cache_key(
        self,
        provider_id: int,
        is_auto: bool,
        cookies: bool,
        country_codes: list[str] | None = None,
        protocol_order: list[str] | None = None,
    ) -> str:
        raw = json.dumps(
            {
                "provider_id": provider_id,
                "is_auto": bool(is_auto),
                "cookies": bool(cookies),
                "country_codes": country_codes or [],
                "protocol_order": protocol_order or [],
            },
            sort_keys=True,
        )
        return hashlib.md5(raw.encode()).hexdigest()

    def _row_to_candidate(self, row: dict) -> CanonicalProxyCandidate:
        return CanonicalProxyCandidate(
            candidate_key=row["candidate_key"],
            provider_id=row["provider_id"],
            provider_name="",
            protocol=row["protocol"],
            host=row["host"],
            port=row["port"],
            proxy_url=self._db.build_runtime_proxy_url(row),
            username=row.get("username"),
            password_enc=row.get("password_enc"),
            auth_type=row.get("auth_type", "none"),
            country_code=row.get("country_code"),
            region=row.get("region"),
            city=row.get("city"),
            anonymity=row.get("anonymity"),
            risk_level=row.get("risk_level", "medium"),
            supports_https=bool(row.get("supports_https", 1)),
            supports_cookies=bool(row.get("supports_cookies", 0)),
            supports_auto_download=bool(row.get("supports_auto_download", 1)),
            supports_sticky_session=bool(row.get("supports_sticky_session", 0)),
            latency_ms=row.get("latency_ms"),
            last_probe_status=row.get("last_probe_status", "unknown"),
            last_probe_at=row.get("last_probe_at"),
            success_count=row.get("success_count", 0),
            failure_count=row.get("failure_count", 0),
            consecutive_failures=row.get("consecutive_failures", 0),
            score=row.get("score", 0.0),
            provider_reference_id=row.get("provider_reference_id"),
            ttl_expires_at=row.get("ttl_expires_at"),
            last_seen_at=row.get("last_seen_at"),
        )

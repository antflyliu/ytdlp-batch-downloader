from pathlib import Path
import importlib
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db


@pytest.fixture()
def db_module(tmp_path, monkeypatch):
    db = monitor_db
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))

    db.init_db()
    return db


def _candidate(provider_id, host, score=0.0):
    from monitor.proxy_router import CanonicalProxyCandidate

    return CanonicalProxyCandidate(
        candidate_key=f"{provider_id}:http:{host}:8080:",
        provider_id=provider_id,
        provider_name="ProviderA",
        protocol="http",
        host=host,
        port=8080,
        proxy_url=f"http://{host}:8080",
        score=score,
    )


def test_pool_save_and_retrieve(db_module):
    from monitor.proxy_candidate_pool import ProxyCandidatePool

    provider_id = db_module.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db_module)
    cand = _candidate(provider_id, "1.2.3.4", score=5.0)

    saved = pool.save_provider_candidates(provider_id, [cand])
    retrieved = pool.get_candidates_for_scenario(provider_id, is_auto_download=False, cookies_present=False)

    assert saved == 1
    assert len(retrieved) == 1
    assert retrieved[0].host == "1.2.3.4"


def test_pool_deduplicates_same_candidate_key(db_module):
    from monitor.proxy_candidate_pool import ProxyCandidatePool

    provider_id = db_module.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db_module)
    cand = _candidate(provider_id, "1.2.3.4", score=5.0)

    pool.save_provider_candidates(provider_id, [cand])
    pool.save_provider_candidates(provider_id, [cand])
    retrieved = pool.get_candidates_for_scenario(provider_id, is_auto_download=False, cookies_present=False)

    assert len(retrieved) == 1


def test_pool_ttl_expiry_excludes_expired_rows(db_module):
    from monitor.proxy_candidate_pool import ProxyCandidatePool

    provider_id = db_module.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db_module)
    cand = _candidate(provider_id, "1.2.3.4", score=5.0)
    pool.save_provider_candidates(provider_id, [cand], ttl_seconds=-1)

    retrieved = pool.get_candidates_for_scenario(provider_id, is_auto_download=False, cookies_present=False)

    assert retrieved == []


def test_memory_cache_key_changes_by_scenario(db_module):
    from monitor.proxy_candidate_pool import ProxyCandidatePool

    pool = ProxyCandidatePool(db_module=db_module)

    key_base = pool._cache_key(1, False, False)
    key_auto = pool._cache_key(1, True, False)
    key_cookie = pool._cache_key(1, False, True)
    key_country = pool._cache_key(1, False, False, country_codes=["US"])
    key_protocol = pool._cache_key(1, False, False, protocol_order=["http", "https"])

    assert key_base != key_auto
    assert key_base != key_cookie
    assert key_base != key_country
    assert key_base != key_protocol


def test_pool_builds_runtime_proxy_url_for_authenticated_candidate(db_module):
    from monitor.proxy_candidate_pool import ProxyCandidatePool

    provider_id = db_module.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db_module)
    db_module.add_proxy_candidate(
        provider_id=provider_id,
        protocol="http",
        host="9.9.9.9",
        port=9000,
        username="alice",
        password="secret",
        auth_type="basic",
        masked_proxy_endpoint="http://***:****@9.9.9.9:9000",
    )

    retrieved = pool.get_candidates_for_scenario(provider_id, is_auto_download=False, cookies_present=False)

    assert retrieved[0].proxy_url == "http://alice:secret@9.9.9.9:9000"



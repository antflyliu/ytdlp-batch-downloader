from pathlib import Path
import importlib
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor.db as monitor_db


def _candidate(provider_id, host, score=0.0, **overrides):
    from monitor.proxy_router import CanonicalProxyCandidate

    payload = {
        "candidate_key": f"{provider_id}:http:{host}:8080:",
        "provider_id": provider_id,
        "provider_name": "ProviderA",
        "protocol": "http",
        "host": host,
        "port": 8080,
        "proxy_url": f"http://{host}:8080",
        "score": score,
        "supports_cookies": True,
        "supports_auto_download": True,
        "risk_level": "low",
        "last_probe_status": "healthy",
    }
    payload.update(overrides)
    return CanonicalProxyCandidate(**payload)


def test_selector_filters_cookie_unsupported(tmp_path, monkeypatch):
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector

    db = importlib.reload(monitor_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))
    db.init_db()

    provider_id = db.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db)
    pool.save_provider_candidates(provider_id, [_candidate(provider_id, "1.2.3.4", supports_cookies=False)])

    selector = ProxySelector(pool)
    result = selector.select(provider_id=provider_id, is_auto_download=False, cookies_present=True, max_count=3)

    assert result == []


def test_selector_respects_free_proxy_disallow(tmp_path, monkeypatch):
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector

    db = importlib.reload(monitor_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))
    db.init_db()

    provider_id = db.add_dynamic_proxy_provider(name="FreeProvider", billing_tier="free", config_json={})
    pool = ProxyCandidatePool(db_module=db)
    pool.save_provider_candidates(provider_id, [_candidate(provider_id, "1.2.3.4")])

    selector = ProxySelector(pool)
    result = selector.select(
        provider_id=provider_id,
        is_auto_download=True,
        cookies_present=False,
        allow_free=False,
        billing_tier="free",
        max_count=3,
    )

    assert result == []


def test_selector_score_orders_higher_scored_candidates_first(tmp_path, monkeypatch):
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector

    db = importlib.reload(monitor_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))
    db.init_db()

    provider_id = db.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db)
    pool.save_provider_candidates(
        provider_id,
        [
            _candidate(provider_id, "1.2.3.4", score=3.0),
            _candidate(provider_id, "1.2.3.5", score=10.0),
        ],
    )

    selector = ProxySelector(pool)
    result = selector.select(provider_id=provider_id, is_auto_download=False, cookies_present=False, max_count=5)

    assert [item.host for item in result] == ["1.2.3.5", "1.2.3.4"]


def test_selector_applies_top_n_limit(tmp_path, monkeypatch):
    from monitor.proxy_candidate_pool import ProxyCandidatePool
    from monitor.proxy_selector import ProxySelector

    db = importlib.reload(monitor_db)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "_DATA_DIR", str(data_dir))
    monkeypatch.setattr(db, "_DB_PATH", str(data_dir / "monitor.db"))
    monkeypatch.setattr(db, "_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(db, "_SCHEMA_PATH", str(ROOT / "monitor" / "schema.sql"))
    db.init_db()

    provider_id = db.add_dynamic_proxy_provider(name="ProviderA", config_json={})
    pool = ProxyCandidatePool(db_module=db)
    pool.save_provider_candidates(
        provider_id,
        [
            _candidate(provider_id, "1.2.3.4", score=1.0),
            _candidate(provider_id, "1.2.3.5", score=2.0),
            _candidate(provider_id, "1.2.3.6", score=3.0),
        ],
    )

    selector = ProxySelector(pool)
    result = selector.select(provider_id=provider_id, is_auto_download=False, cookies_present=False, max_count=2)

    assert len(result) == 2
    assert [item.host for item in result] == ["1.2.3.6", "1.2.3.5"]

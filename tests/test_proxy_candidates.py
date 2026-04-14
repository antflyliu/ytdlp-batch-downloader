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


def _add_provider(db_module, name="Provider A"):
    return db_module.add_dynamic_proxy_provider(name=name, config_json={})


def _candidate_payload(db_module, provider_id, **overrides):
    payload = {
        "provider_id": provider_id,
        "protocol": "http",
        "host": "10.10.10.10",
        "port": 8080,
        "username": "alice",
        "password": "super-secret",
        "auth_type": "basic",
        "country_code": "US",
        "region": "CA",
        "city": "Los Angeles",
        "anonymity": "elite",
        "risk_level": "low",
        "supports_https": True,
        "supports_cookies": True,
        "supports_auto_download": True,
        "supports_sticky_session": True,
        "latency_ms": 120,
        "last_probe_status": "healthy",
        "last_probe_at": db_module.now_iso(),
        "score": 9.5,
        "provider_reference_id": "upstream-1",
        "ttl_expires_at": db_module._iso_future(300),
    }
    payload.update(overrides)
    return payload


def test_dynamic_proxy_candidates_table_exists_after_init(db_module):
    with db_module.get_connection() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dynamic_proxy_candidates'"
        ).fetchone()
        columns = conn.execute("PRAGMA table_info(dynamic_proxy_candidates)").fetchall()

    assert row is not None
    last_seen_column = next(column for column in columns if column["name"] == "last_seen_at")
    assert last_seen_column["notnull"] == 1


def test_add_and_get_proxy_candidate(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(**_candidate_payload(db_module, provider_id))

    candidate = db_module.get_proxy_candidate(candidate_id)

    assert candidate is not None
    assert candidate["id"] == candidate_id
    assert candidate["provider_id"] == provider_id
    assert candidate["candidate_key"] == f"{provider_id}:http:10.10.10.10:8080:alice"
    assert candidate["masked_proxy_endpoint"] == "http://***:****@10.10.10.10:8080"
    assert db_module.build_runtime_proxy_url(candidate) == "http://alice:super-secret@10.10.10.10:8080"

    candidates = db_module.get_proxy_candidate_by_provider(provider_id)
    assert [item["id"] for item in candidates] == [candidate_id]


def test_get_proxy_candidate_by_provider_returns_valid_candidates_ordered_by_score_desc(db_module):
    provider_id = _add_provider(db_module)
    high_score_id = db_module.add_proxy_candidate(
        **_candidate_payload(db_module, provider_id, host="10.10.10.20", score=12.0)
    )
    low_score_id = db_module.add_proxy_candidate(
        **_candidate_payload(db_module, provider_id, host="10.10.10.21", score=3.0)
    )
    db_module.add_proxy_candidate(
        **_candidate_payload(
            db_module,
            provider_id,
            host="10.10.10.22",
            score=99.0,
            ttl_expires_at=db_module._iso_future(-60),
        )
    )

    candidates = db_module.get_proxy_candidate_by_provider(provider_id)

    assert [item["id"] for item in candidates] == [high_score_id, low_score_id]
def test_build_runtime_proxy_url_helper_signature(db_module):
    proxy_url = db_module._build_runtime_proxy_url(
        "http",
        "10.10.10.10",
        8080,
        username="alice",
        password="super-secret",
    )

    assert proxy_url == "http://alice:super-secret@10.10.10.10:8080"


def test_duplicate_candidate_is_idempotent_and_refreshes_timestamps(db_module):
    provider_id = _add_provider(db_module)
    payload = _candidate_payload(db_module, provider_id)

    first_id = db_module.add_proxy_candidate(**payload)

    with db_module.get_connection() as conn:
        conn.execute(
            "UPDATE dynamic_proxy_candidates SET last_seen_at=?, updated_at=?, ttl_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", first_id),
        )

    second_id = db_module.add_proxy_candidate(
        **_candidate_payload(db_module, provider_id, ttl_expires_at=db_module._iso_future(900))
    )
    candidate = db_module.get_proxy_candidate(first_id)

    assert second_id == first_id
    assert candidate["last_seen_at"] != "2000-01-01T00:00:00+00:00"
    assert candidate["updated_at"] != "2000-01-01T00:00:00+00:00"
    assert candidate["ttl_expires_at"] != "2000-01-01T00:00:00+00:00"


def test_delete_provider_cascades_candidates(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(**_candidate_payload(db_module, provider_id))

    db_module.delete_dynamic_proxy_provider(provider_id)

    assert db_module.get_proxy_candidate(candidate_id) is None


def test_candidate_secret_not_stored_plaintext(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(**_candidate_payload(db_module, provider_id))

    with db_module.get_connection() as conn:
        row = conn.execute(
            "SELECT password_enc FROM dynamic_proxy_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()

    assert row["password_enc"] != "super-secret"
    assert "super-secret" not in row["password_enc"]
    assert row["password_enc"].startswith("enc:")


def test_masked_proxy_endpoint_masks_credentials(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(**_candidate_payload(db_module, provider_id))

    candidate = db_module.get_proxy_candidate(candidate_id)

    assert "alice" not in candidate["masked_proxy_endpoint"]
    assert "super-secret" not in candidate["masked_proxy_endpoint"]
    assert candidate["masked_proxy_endpoint"] == "http://***:****@10.10.10.10:8080"


def test_delete_expired_candidates_removes_only_expired_rows(db_module):
    provider_id = _add_provider(db_module)
    expired_id = db_module.add_proxy_candidate(
        **_candidate_payload(
            db_module,
            provider_id,
            ttl_expires_at=db_module._iso_future(-60),
            score=1.0,
        )
    )
    valid_id = db_module.add_proxy_candidate(
        **_candidate_payload(
            db_module,
            provider_id,
            host="10.10.10.11",
            ttl_expires_at=db_module._iso_future(600),
            score=10.0,
        )
    )

    deleted = db_module.delete_expired_candidates()

    assert deleted == 1
    assert db_module.get_proxy_candidate(expired_id) is None
    assert db_module.get_proxy_candidate(valid_id) is not None


def test_get_proxy_candidate_by_provider_includes_non_expiring_candidates(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(
        **_candidate_payload(
            db_module,
            provider_id,
            host="10.10.10.30",
            ttl_expires_at=None,
            score=7.0,
        )
    )

    candidates = db_module.get_proxy_candidate_by_provider(provider_id)

    assert [item["id"] for item in candidates] == [candidate_id]


def test_add_proxy_candidate_keeps_last_probe_at_null_without_explicit_probe_time(db_module):
    provider_id = _add_provider(db_module)
    candidate_id = db_module.add_proxy_candidate(
        **_candidate_payload(
            db_module,
            provider_id,
            host="10.10.10.31",
            last_probe_status="unknown",
            last_probe_at=None,
        )
    )

    candidate = db_module.get_proxy_candidate(candidate_id)

    assert candidate["last_probe_at"] is None

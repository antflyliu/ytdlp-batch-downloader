from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.__main__ as server_main
from monitor.email_collect.processor import RULE_SCHEMA_VERSION


def _handler():
    sent: list[tuple[dict, int]] = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda payload, status=200: sent.append((payload, status))
    return handler, sent


def _patch_rule_config(monkeypatch, tmp_path, initial_rules: dict | None = None):
    state = {"config": {"email_analysis_rules": initial_rules or {}}}
    invalidations = {"count": 0}

    monkeypatch.setattr(server_main._db, "_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(server_main._db, "load_config", lambda: dict(state["config"]))
    monkeypatch.setattr(server_main._db, "save_config", lambda cfg: state.update({"config": dict(cfg)}))
    monkeypatch.setattr(
        server_main._scheduler,
        "_invalidate_config_cache",
        lambda: invalidations.update({"count": invalidations["count"] + 1}),
    )
    return state, invalidations


def test_email_analysis_rules_validate_save_export_and_restore_contract(monkeypatch, tmp_path):
    state, invalidations = _patch_rule_config(monkeypatch, tmp_path)
    handler, sent = _handler()

    first_rules = {
        "marketing_keywords": ["优惠"],
        "link_enrichment": {"max_links": 4, "timeout_seconds": 5},
    }
    second_rules = {
        "marketing_keywords": ["广告"],
        "platform_sensitive_words": {"wechat": {"禁词": "合规表述"}},
    }

    server_main.MonitorHandler._api_email_analysis_rules_validate(handler, {"rules": first_rules})
    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["schema"]["schema_version"] == RULE_SCHEMA_VERSION

    server_main.MonitorHandler._api_email_analysis_rules_save(
        handler,
        {"rules": first_rules, "note": "initial operator rules"},
    )
    payload, status = sent.pop()
    first_version = payload["version"]["version_id"]
    assert status == 200
    assert payload["ok"] is True
    assert state["config"]["email_analysis_rules"] == first_rules
    assert invalidations["count"] == 1

    server_main.MonitorHandler._api_email_analysis_rules_save(
        handler,
        {"rules": second_rules, "note": "updated operator rules"},
    )
    payload, status = sent.pop()
    assert status == 200
    assert payload["history"][0]["rules"] == second_rules

    server_main.MonitorHandler._api_email_analysis_rules_export(handler)
    payload, status = sent.pop()
    assert status == 200
    assert payload["schema_version"] == RULE_SCHEMA_VERSION
    assert payload["rules"] == second_rules

    server_main.MonitorHandler._api_email_analysis_rules_restore(
        handler,
        {"version_id": first_version, "note": "rollback to initial"},
    )
    payload, status = sent.pop()
    assert status == 200
    assert payload["rules"] == first_rules
    assert state["config"]["email_analysis_rules"] == first_rules
    assert payload["history"][0]["source"] == "restore"


def test_email_analysis_rules_import_accepts_export_payload(monkeypatch, tmp_path):
    state, invalidations = _patch_rule_config(monkeypatch, tmp_path)
    handler, sent = _handler()

    server_main.MonitorHandler._api_email_analysis_rules_import(
        handler,
        {
            "payload": {
                "schema_version": RULE_SCHEMA_VERSION,
                "rules": {"marketing_sender_domains": ["newsletter."]},
            },
            "note": "imported by operator",
        },
    )

    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert state["config"]["email_analysis_rules"] == {"marketing_sender_domains": ["newsletter."]}
    assert invalidations["count"] == 1


def test_email_analysis_rules_save_rejects_invalid_payload(monkeypatch, tmp_path):
    state, invalidations = _patch_rule_config(
        monkeypatch,
        tmp_path,
        initial_rules={"marketing_keywords": ["existing"]},
    )
    handler, sent = _handler()

    server_main.MonitorHandler._api_email_analysis_rules_save(
        handler,
        {"rules": {"link_enrichment": {"max_depth": 99}}},
    )

    payload, status = sent.pop()
    assert status == 400
    assert payload["code"] == "email_analysis_rules_invalid"
    assert "link_enrichment.max_depth: must be between 1 and 3" in payload["details"]
    assert state["config"]["email_analysis_rules"] == {"marketing_keywords": ["existing"]}
    assert invalidations["count"] == 0


def test_email_analysis_rules_state_returns_invalid_raw_rules_for_repair(monkeypatch, tmp_path):
    state, _invalidations = _patch_rule_config(
        monkeypatch,
        tmp_path,
        initial_rules={"unknown_rule": []},
    )
    handler, sent = _handler()

    server_main.MonitorHandler._api_email_analysis_rules(handler)

    payload, status = sent.pop()
    assert status == 200
    assert payload["validation"]["ok"] is False
    assert payload["rules"] == state["config"]["email_analysis_rules"]
    assert payload["raw_rules"] == state["config"]["email_analysis_rules"]
    assert payload["normalized_rules"] == {}


def test_email_analysis_rules_save_returns_json_error_on_config_persistence_failure(monkeypatch, tmp_path):
    state, invalidations = _patch_rule_config(monkeypatch, tmp_path)
    handler, sent = _handler()

    def fail_save(_cfg):
        raise ValueError("disk is read only")

    monkeypatch.setattr(server_main._db, "save_config", fail_save)

    server_main.MonitorHandler._api_email_analysis_rules_save(
        handler,
        {"rules": {"marketing_keywords": ["promo"]}},
    )

    payload, status = sent.pop()
    assert status == 400
    assert payload["code"] == "email_analysis_rules_save_failed"
    assert "disk is read only" in payload["error"]
    assert state["config"]["email_analysis_rules"] == {}
    assert invalidations["count"] == 0


def test_email_analysis_rules_save_surfaces_history_write_warning(monkeypatch, tmp_path):
    state, invalidations = _patch_rule_config(monkeypatch, tmp_path)
    handler, sent = _handler()

    def fail_history(_history):
        raise OSError("history path unavailable")

    monkeypatch.setattr(server_main, "_write_email_analysis_rules_history", fail_history)

    server_main.MonitorHandler._api_email_analysis_rules_save(
        handler,
        {"rules": {"marketing_keywords": ["promo"]}},
    )

    payload, status = sent.pop()
    assert status == 200
    assert payload["ok"] is True
    assert payload["warning"]["code"] == "email_analysis_rules_history_write_failed"
    assert state["config"]["email_analysis_rules"] == {"marketing_keywords": ["promo"]}
    assert invalidations["count"] == 1


def test_config_save_rejects_invalid_email_analysis_rules(monkeypatch, tmp_path):
    state, _invalidations = _patch_rule_config(monkeypatch, tmp_path)
    handler, sent = _handler()

    server_main.MonitorHandler._api_config_save(
        handler,
        {"email_analysis_rules": {"platform_sensitive_words": {"bad-platform": {"x": "y"}}}},
    )

    payload, status = sent.pop()
    assert status == 400
    assert payload["code"] == "email_analysis_rules_invalid"
    assert state["config"]["email_analysis_rules"] == {}

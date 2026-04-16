"""Quota 告警按平台构造合法 Webhook JSON 体。"""
import pytest

from monitor.quota import build_quota_alert_payload


@pytest.fixture
def sample_usage():
    return {
        "api_calls": 800,
        "scans_done": 12,
        "blocked_scans": 2,
        "updated_at": "2026-04-08T12:00:00+08:00",
    }


def test_feishu_payload_uses_msg_type_text(sample_usage):
    p = build_quota_alert_payload("feishu", "AIzaSyDummyKey0123456789", sample_usage, 1000)
    assert p["msg_type"] == "text"
    assert "content" in p
    assert p["content"]["text"]
    assert "预警" in p["content"]["text"]
    assert "800" in p["content"]["text"]


def test_dingtalk_payload_uses_msgtype_text(sample_usage):
    p = build_quota_alert_payload("dingtalk", "k", sample_usage, 1000)
    assert p["msgtype"] == "text"
    assert p["text"]["content"]
    assert "msg_type" not in p


def test_wecom_payload_uses_msgtype_text(sample_usage):
    p = build_quota_alert_payload("wecom", "k", sample_usage, 1000)
    assert p["msgtype"] == "text"
    assert "text" in p and "content" in p["text"]


def test_telegram_payload_uses_text_parse_mode(sample_usage):
    p = build_quota_alert_payload("telegram", "123456789:ABCdefGhIJKlmNoPQRsTUVwxYZ", sample_usage, 1000)
    assert p["parse_mode"] == "MarkdownV2"
    assert "text" in p
    assert "预警" in p["text"]


def test_unknown_platform_defaults_to_feishu_shape(sample_usage):
    p = build_quota_alert_payload("unknown", "k", sample_usage, 1000)
    assert p["msg_type"] == "text"
    assert "content" in p

"""钉钉 Webhook 加签 URL 构造。"""
from unittest.mock import patch

from monitor.notifier import finalize_dingtalk_webhook_url


def test_finalize_dingtalk_webhook_url_no_secret_returns_unchanged():
    url = "https://oapi.dingtalk.com/robot/send?access_token=abc"
    assert finalize_dingtalk_webhook_url(url, None) is url
    assert finalize_dingtalk_webhook_url(url, "") is url
    assert finalize_dingtalk_webhook_url(url, "   ") is url


def test_finalize_dingtalk_webhook_url_appends_timestamp_and_sign():
    url = "https://oapi.dingtalk.com/robot/send?access_token=xyz"
    secret = "testsecret"
    fixed_ms = 1_609_459_200_000
    with patch("monitor.notifier.time.time", return_value=fixed_ms / 1000.0):
        out = finalize_dingtalk_webhook_url(url, secret)
    assert "access_token=xyz" in out
    assert "timestamp=1609459200000" in out
    assert "sign=" in out
    assert out.startswith("https://oapi.dingtalk.com/robot/send?")


def test_finalize_preserves_path_and_replaces_stale_sign_params():
    url = (
        "https://oapi.dingtalk.com/robot/send?access_token=tok"
        "&timestamp=111&sign=old"
    )
    with patch("monitor.notifier.time.time", return_value=1.0):
        out = finalize_dingtalk_webhook_url(url, "s")
    from urllib.parse import parse_qs, urlsplit

    q = parse_qs(urlsplit(out).query)
    assert "timestamp" in q and len(q["timestamp"]) == 1
    assert q["timestamp"][0] == "1000"
    assert "sign" in q and len(q["sign"]) == 1
    assert q["sign"][0] != "old"

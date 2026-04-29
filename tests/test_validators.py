import pytest

from monitor.validators import normalize_dingtalk_sign_secret


def test_normalize_dingtalk_sign_secret_empty():
    assert normalize_dingtalk_sign_secret(None) is None
    assert normalize_dingtalk_sign_secret("") is None
    assert normalize_dingtalk_sign_secret("  \t  ") is None


def test_normalize_dingtalk_sign_secret_valid():
    s = "SEC" + "a" * 20
    assert normalize_dingtalk_sign_secret(s) == s
    assert normalize_dingtalk_sign_secret(f"  {s}  ") == s


def test_normalize_dingtalk_sign_secret_must_start_with_sec():
    with pytest.raises(ValueError, match="SEC"):
        normalize_dingtalk_sign_secret("not-a-secret")


def test_normalize_dingtalk_sign_secret_min_length():
    with pytest.raises(ValueError, match="过短"):
        normalize_dingtalk_sign_secret("SECshort")

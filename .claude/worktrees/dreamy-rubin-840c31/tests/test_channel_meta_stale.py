"""频道元数据缓存 TTL 辅助函数测试。"""
from datetime import datetime, timedelta, timezone

import pytest

from monitor.cache import is_channel_meta_stale


def test_stale_disabled_when_max_age_zero():
    cached = {"cached_at": "2020-01-01T00:00:00+00:00"}
    assert is_channel_meta_stale(cached, 0) is False


def test_stale_when_missing_cached_at():
    assert is_channel_meta_stale({"channel_id": "UCx"}, 7) is True


def test_not_stale_when_within_ttl():
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(days=5)).isoformat(timespec="seconds")
    cached = {"cached_at": raw}
    assert is_channel_meta_stale(cached, 7) is False


def test_stale_when_past_ttl():
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(days=40)).isoformat(timespec="seconds")
    cached = {"cached_at": raw}
    assert is_channel_meta_stale(cached, 30) is True

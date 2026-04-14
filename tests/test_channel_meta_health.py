"""channel_meta uploads 健康检查间隔逻辑测试。"""
from datetime import datetime, timedelta, timezone

from monitor.cache import should_run_uploads_health_check


def test_should_run_when_no_timestamps():
    """无任何时间戳时仍需检查（与迁移前行为一致）。"""
    assert should_run_uploads_health_check({}, 24) is True


def test_migrated_row_without_health_checked_uses_cached_at_interval():
    """旧库仅有 cached_at 时，用其计算间隔（避免每次扫描都探针）。"""
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    cached = {"cached_at": raw}
    assert should_run_uploads_health_check(cached, 24) is False


def test_should_not_run_within_interval():
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    cached = {"health_checked_at": raw}
    assert should_run_uploads_health_check(cached, 24) is False


def test_should_run_after_interval():
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(hours=25)).isoformat(timespec="seconds")
    cached = {"health_checked_at": raw}
    assert should_run_uploads_health_check(cached, 24) is True


def test_non_positive_interval_uses_24h_effective():
    now = datetime.now(timezone.utc)
    raw = (now - timedelta(hours=25)).isoformat(timespec="seconds")
    cached = {"health_checked_at": raw}
    assert should_run_uploads_health_check(cached, 0) is True

"""配额统计时区校验与缓存失效（与 monitor.quota 一致）。"""
import monitor.quota as quota


def test_validate_quota_timezone_accepts_local_and_empty():
    assert quota.validate_quota_usage_timezone(None) == (True, None)
    assert quota.validate_quota_usage_timezone("") == (True, None)
    assert quota.validate_quota_usage_timezone("local") == (True, None)
    assert quota.validate_quota_usage_timezone("America/Los_Angeles") == (True, None)


def test_validate_quota_timezone_rejects_invalid():
    ok, err = quota.validate_quota_usage_timezone("Not/A/RealZone")
    assert ok is False
    assert err is not None and "quota_usage_timezone" in err


def test_invalidate_config_cache_clears_quota_config_buffer():
    quota.invalidate_config_cache()
    # 第二次 _load_config_for_quota 应重新读库（不在这里断言 IO，只确保不抛）
    quota.invalidate_config_cache()

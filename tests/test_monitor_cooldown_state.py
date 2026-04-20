"""tests/test_monitor_cooldown_state.py — Test cooldown state management functions."""
from __future__ import annotations

import sys
import time as real_time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_get_backoff_seconds_returns_correct_values():
    """Exponential backoff: min(60 * retry_count, 180) + jitter(0,10)."""
    import monitor.scheduler as sc

    # retry 0 -> ~0-10s
    bs = sc._get_backoff_seconds(0)
    assert 0 <= bs <= 10, f"retry=0: expected 0-10, got {bs}"

    # retry 1 -> ~60-70s
    bs = sc._get_backoff_seconds(1)
    assert 60 <= bs <= 70, f"retry=1: expected 60-70, got {bs}"

    # retry 2 -> ~120-130s
    bs = sc._get_backoff_seconds(2)
    assert 120 <= bs <= 130, f"retry=2: expected 120-130, got {bs}"

    # retry 3 -> ~180-190s (capped at 180)
    bs = sc._get_backoff_seconds(3)
    assert 180 <= bs <= 190, f"retry=3: expected 180-190, got {bs}"

    # retry 10 -> still capped at 180
    bs = sc._get_backoff_seconds(10)
    assert 180 <= bs <= 190, f"retry=10: expected 180-190, got {bs}"


def test_proxy_cooldown_set_stores_deadline_and_count():
    """_set_proxy_cooldown should store deadline and retry count."""
    import monitor.scheduler as sc

    proxy = "http://test:1234"

    sc._proxy_cooldown_until[proxy] = 0.0
    sc._proxy_retry_count[proxy] = 0

    sc._set_proxy_cooldown(proxy, retry_count=1)

    assert proxy in sc._proxy_cooldown_until
    assert sc._proxy_retry_count[proxy] == 1
    # Deadline should be in the future (real time + backoff)
    assert sc._proxy_cooldown_until[proxy] > real_time.monotonic()


def test_direct_cooldown_set_stores_deadline_and_count():
    """_set_direct_cooldown should store deadline and retry count."""
    import monitor.scheduler as sc

    sc._direct_cooldown_until = 0.0
    sc._direct_retry_count = 0

    sc._set_direct_cooldown(retry_count=2)

    assert sc._direct_retry_count == 2
    assert sc._direct_cooldown_until > real_time.monotonic()


def test_wait_proxy_returns_true_when_no_cooldown_ever_set():
    """Waiting with no cooldown ever set for proxy should return True immediately."""
    import monitor.scheduler as sc

    proxy = "http://never:set"

    sc._proxy_cooldown_until.pop(proxy, None)

    start = real_time.monotonic()
    result = sc._wait_for_proxy_cooldown(proxy)
    elapsed = real_time.monotonic() - start

    assert result is True
    assert elapsed < 0.5  # should be nearly instant


def test_wait_proxy_returns_true_when_cooldown_expired():
    """Waiting when proxy cooldown has already expired should return True immediately."""
    import monitor.scheduler as sc

    proxy = "http://expired:8888"

    sc._proxy_cooldown_until[proxy] = real_time.monotonic() - 10

    start = real_time.monotonic()
    result = sc._wait_for_proxy_cooldown(proxy)
    elapsed = real_time.monotonic() - start

    assert result is True
    assert elapsed < 0.5  # should be nearly instant


def test_wait_proxy_blocks_until_deadline_with_mocked_sleep():
    """Waiting should sleep until deadline, then return True."""
    import monitor.scheduler as sc

    proxy = "http://blocks:7777"

    # Set cooldown to 1 second in the future
    sc._proxy_cooldown_until[proxy] = real_time.monotonic() + 1.0

    sleep_calls = []
    real_sleep = sc.time.sleep

    def fake_sleep(duration):
        sleep_calls.append(duration)
        # Simulate time passing
        sc._proxy_cooldown_until[proxy] = real_time.monotonic() - 0.1

    with patch.object(sc.time, 'sleep', fake_sleep):
        start = real_time.monotonic()
        result = sc._wait_for_proxy_cooldown(proxy)
        elapsed = real_time.monotonic() - start

    assert result is True
    assert len(sleep_calls) == 1
    assert 0.9 <= sleep_calls[0] <= 1.1  # ~1 second sleep


def test_wait_direct_returns_true_when_cooldown_expired():
    """Waiting when direct cooldown has already expired should return True immediately."""
    import monitor.scheduler as sc

    sc._direct_cooldown_until = real_time.monotonic() - 10

    start = real_time.monotonic()
    result = sc._wait_for_direct_cooldown()
    elapsed = real_time.monotonic() - start

    assert result is True
    assert elapsed < 0.5


def test_proxy_cooldown_per_proxy_independent():
    """Cooldown state should be independent per proxy."""
    import monitor.scheduler as sc

    proxy_a = "http://a:1111"
    proxy_b = "http://b:2222"

    sc._proxy_cooldown_until[proxy_a] = 0.0
    sc._proxy_cooldown_until[proxy_b] = 0.0
    sc._proxy_retry_count[proxy_a] = 0
    sc._proxy_retry_count[proxy_b] = 0

    sc._set_proxy_cooldown(proxy_a, retry_count=2)
    sc._set_proxy_cooldown(proxy_b, retry_count=1)

    assert sc._proxy_retry_count[proxy_a] == 2
    assert sc._proxy_retry_count[proxy_b] == 1

    # Higher retry = longer backoff, so a's deadline > b's deadline
    assert sc._proxy_cooldown_until[proxy_a] > sc._proxy_cooldown_until[proxy_b]


def test_account_pools_created_on_demand():
    """_ensure_account_pool creates a new pool for each account_id."""
    import monitor.scheduler as sc

    # Clean up any existing pools
    with sc._account_pools_lock:
        for aid in list(sc._account_pools.keys()):
            pool = sc._account_pools.pop(aid, None)
            if pool:
                pool.shutdown(wait=False)

    pool1 = sc._ensure_account_pool(101)
    pool2 = sc._ensure_account_pool(102)
    pool3 = sc._ensure_account_pool(101)  # same account

    assert pool1 is pool3  # same pool for same account
    assert pool1 is not pool2  # different pool for different account

    with sc._account_pools_lock:
        assert 101 in sc._account_pools
        assert 102 in sc._account_pools


def test_account_pools_shutdown():
    """_shutdown_account_pool removes and shutsuts the pool."""
    import monitor.scheduler as sc

    pool = sc._ensure_account_pool(201)
    assert 201 in sc._account_pools

    sc._shutdown_account_pool(201, wait=False)

    with sc._account_pools_lock:
        assert 201 not in sc._account_pools


def test_auto_download_pool_singleton():
    """_ensure_auto_download_pool returns the same pool on repeated calls."""
    import monitor.scheduler as sc

    pool1 = sc._ensure_auto_download_pool()
    pool2 = sc._ensure_auto_download_pool()
    assert pool1 is pool2

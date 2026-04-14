"""scheduler.start() 在调度器已运行时应返回 (True, True)，供 API 标记 already_running。"""

from unittest.mock import MagicMock

import monitor.scheduler as sch


def test_start_returns_true_when_scheduler_already_running():
    """重复启动应成功，并同步 auto_download 开关。"""
    prev = sch._scheduler
    prev_ad = sch._auto_download_on_scan
    try:
        fake = MagicMock()
        fake.running = True
        sch._scheduler = fake
        sch._auto_download_on_scan = False
        assert sch.start(auto_download=True) == (True, True)
        assert sch._auto_download_on_scan is True
        assert sch.start(auto_download=False) == (True, True)
        assert sch._auto_download_on_scan is False
    finally:
        sch._scheduler = prev
        sch._auto_download_on_scan = prev_ad

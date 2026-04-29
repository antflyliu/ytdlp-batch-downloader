"""
conftest.py — pytest 插件

目的：mock time.sleep 避免测试中的指数退避延迟。
不 mock googleapiclient.discovery，避免影响其他需要真实 API 的测试。
"""
import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def no_sleep():
    """所有测试自动跳过 time.sleep，避免指数退避等待."""
    with patch.object(time, "sleep", lambda s: None):
        yield

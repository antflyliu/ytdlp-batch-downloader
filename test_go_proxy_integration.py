"""
test_go_proxy_integration.py -- Go 代理子进程集成测试

需要先编译 Go 可执行文件：
    cd D:\\WORKSPACE\\video-download-space\\res-downloader
    go build -ldflags="-s -w" -o res-downloader.exe .
"""
import os
import time
import pytest

from go_proxy_manager import GoProxyManager, get_proxy_manager, reset_proxy_manager, _find_executable


@pytest.fixture(autouse=True)
def cleanup():
    """每个测试前后清理。"""
    reset_proxy_manager()
    yield
    reset_proxy_manager()


def test_find_executable():
    """验证可执行文件能被找到。"""
    path = _find_executable()
    assert path is not None, "Go 可执行文件未找到"
    assert os.path.exists(path), f"路径不存在: {path}"


def test_proxy_manager_singleton():
    """验证全局单例（只应有一个 Go 子进程）。"""
    m1 = get_proxy_manager()
    m2 = get_proxy_manager()
    assert m1 is m2, "get_proxy_manager() 应返回同一实例"
    # 单例设计：只应有一个 Go 子进程，proxy_port 仅首次生效
    m3 = get_proxy_manager(proxy_port=8900)
    assert m3 is m1, "单例不应因 port 参数改变而创建新实例"


def test_start_stop():
    """验证启动和停止。"""
    mgr = GoProxyManager(proxy_port=8899)
    assert not mgr.is_running

    mgr.start()
    assert mgr.is_running

    # 健康检查
    import requests
    r = requests.get(f"{mgr.api_base}/health", timeout=5)
    assert r.status_code == 200

    mgr.stop()
    assert not mgr.is_running


def test_get_config():
    """验证获取配置 API。"""
    mgr = GoProxyManager(proxy_port=8899)
    mgr.start()
    try:
        config = mgr.get_config()
        assert isinstance(config, dict)
    finally:
        mgr.stop()


def test_start_stop_multiple():
    """验证多次启动/停止。"""
    mgr = GoProxyManager(proxy_port=8899)
    for i in range(2):
        mgr.start()
        assert mgr.is_running
        mgr.stop()
        assert not mgr.is_running
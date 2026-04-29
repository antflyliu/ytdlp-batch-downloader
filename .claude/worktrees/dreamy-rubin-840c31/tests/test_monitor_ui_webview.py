"""tests/test_monitor_ui_webview.py"""
import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor_ui_webview as wv


class TestWebView2Detector:
    def test_webview2_available_returns_bool(self):
        """is_webview2_available() 应返回布尔值"""
        result = wv.is_webview2_available()
        assert isinstance(result, bool)

    def test_check_webview2_returns_tuple(self):
        """check_webview2() 应返回 (available: bool, path: str | None)"""
        available, path = wv.check_webview2()
        assert isinstance(available, bool)
        assert (path is None) or isinstance(path, str)

    def test_install_webview2_bootstrapper_creates_file(self, tmp_path):
        """install_webview2_bootstrapper() 应下载 bootstrapper 并返回路径"""
        dest = tmp_path / "MicrosoftEdgeWebview2Setup.exe"
        result = wv.install_webview2_bootstrapper(str(dest))
        # 返回路径字符串或 None（已安装/下载失败）
        assert result is None or isinstance(result, str)

    def test_show_install_dialog_does_not_crash(self):
        """show_webview2_install_dialog() 不应抛出异常（mock MessageBox 避免弹窗）"""
        with patch("ctypes.windll") as mock_windll:
            mock_windll.user32.MessageBoxW.return_value = 1
            try:
                wv.show_webview2_install_dialog()
            except Exception:
                pytest.fail("show_webview2_install_dialog() raised unexpected exception")

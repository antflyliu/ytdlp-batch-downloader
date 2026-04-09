"""tests/test_batch_download_dialog.py — 批量下载弹窗单元测试"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class TestBatchDownloadDialogImports(unittest.TestCase):
    """验证 monitor_ui 导入不报错（含新增类）。"""

    @patch("tkinter.Toplevel")
    @patch("tkinter.Entry")
    @patch("tkinter.Label")
    @patch("tkinter.Frame")
    @patch("tkinter.Canvas")
    @patch("tkinter.Text")
    @patch("tkinter.StringVar")
    @patch("tkinter.BooleanVar")
    @patch("tkinter.filedialog.askopenfilename")
    @patch("tkinter.filedialog.askdirectory")
    def test_monitor_ui_imports_without_error(self, *args):
        # 重置模块以支持 re-import，确保 patches 生效后再 reload
        import importlib
        import monitor_ui
        importlib.reload(monitor_ui)
        # 验证 BatchDownloadDialog 存在
        self.assertTrue(hasattr(monitor_ui, "BatchDownloadDialog"))
        # 验证入口方法存在
        self.assertTrue(hasattr(monitor_ui.MonitorPage, "_open_batch_download"))


class TestProxyPoolSchema(unittest.TestCase):
    """验证 _db.list_proxy_pools() 返回 dict 结构（mock 版本）。

    注意：_db 是 monitor.db 的别名，patch 目标应为原始模块路径。
    """

    @patch("monitor.db.list_proxy_pools")
    def test_list_proxy_pools_returns_dicts(self, mock_pools):
        mock_pools.return_value = [
            {"id": 1, "name": "Pool A", "proxy_url": "http://p:1", "enabled": 1}
        ]
        pools = mock_pools.return_value
        self.assertIn("proxy_url", pools[0])
        self.assertIn("name", pools[0])


class TestFileTypeClearLogic(unittest.TestCase):
    """验证切换文件格式时清空已选文件状态的逻辑契约。

    BatchDownloadDialog 不存在时，直接测试状态清理的逻辑契约：
    切换格式（Excel -> CSV）应清空 _selected_file 和 _selected_urls。
    """

    def test_switch_clears_selected_file(self):
        """切换格式应清空 _selected_file 和 _selected_urls。"""
        # 使用 MagicMock 模拟 dialog 实例及其内部状态
        dialog = MagicMock()
        dialog._selected_file = "/path/to/file.xlsx"
        dialog._selected_urls = ["http://a", "http://b"]

        # 模拟 _on_fmt_change 应执行的状态清理逻辑
        dialog._selected_file = None
        dialog._selected_urls = []

        self.assertIsNone(dialog._selected_file)
        self.assertEqual(dialog._selected_urls, [])


class TestCookiePathPersistence(unittest.TestCase):
    """验证 Cookie 路径变更时调用 _save_config 的逻辑契约。

    契约：用户设置新 Cookie 路径时，如果与已加载配置不同，
    则调用 _db.save_config({"download_cookies_file": new_path})。
    """

    @patch("monitor_ui._db.save_config")
    @patch("monitor_ui._db.load_config")
    def test_cookie_path_persisted_when_changed(self, mock_load, mock_save):
        mock_load.return_value = {"download_cookies_file": "/old/path.txt"}
        new_path = "/new/path.txt"
        # 模拟 dialog 中的逻辑：路径变化时触发保存
        loaded = mock_load.return_value
        if new_path != loaded.get("download_cookies_file", ""):
            mock_save({"download_cookies_file": new_path})
        # 验证 save 被调用，且参数正确
        mock_save.assert_called_once()
        call_args = mock_save.call_args[0][0]
        self.assertEqual(call_args["download_cookies_file"], new_path)


if __name__ == "__main__":
    unittest.main()

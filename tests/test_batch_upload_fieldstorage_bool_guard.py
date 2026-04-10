"""tests/test_batch_upload_fieldstorage_bool_guard.py — FieldStorage 布尔判断回归测试"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "monitor_server.py"


def test_multipart_handler_does_not_use_bool_check_on_fieldstorage():
    """FieldStorage 不能进入 bool 上下文，handler 必须用 is None / getattr 判空。"""
    text = SERVER.read_text(encoding="utf-8")
    start = text.index('def _handle_multipart_upload')
    end = text.index('def _api_batch_download_start', start)
    section = text[start:end]
    assert 'if not file_item' not in section
    assert 'if file_item is None' in section or 'if file_item is None or' in section

"""tests/test_batch_upload_fieldstorage_access.py — multipart file field access regression test"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "monitor_server.py"


def test_multipart_handler_uses_fieldstorage_item_not_getfirst_for_file_field():
    """文件字段必须通过 form['file'] 读取 FieldStorage 对象，不能用 getfirst('file')。"""
    text = SERVER.read_text(encoding="utf-8")
    start = text.index('def _handle_multipart_upload')
    end = text.index('def _api_batch_download_start', start)
    section = text[start:end]
    assert 'form["file"]' in section or "form['file']" in section
    assert 'getfirst("file")' not in section

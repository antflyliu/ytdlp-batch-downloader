"""tests/test_batch_upload_multipart_gate.py — multipart 上传入口回归测试"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "monitor_server.py"


def test_multipart_upload_checked_before_json_body_parse():
    """multipart/form-data 必须在 _read_json() 之前分流，否则会误报 invalid json body。"""
    text = SERVER.read_text(encoding="utf-8")
    marker_multipart = 'if self.headers.get("Content-Type", "").startswith("multipart/form-data"):'
    marker_read_json = 'body = self._read_json()'
    assert marker_multipart in text
    assert marker_read_json in text
    assert text.index(marker_multipart) < text.index(marker_read_json)

"""Regression tests for the custom multipart parser integration.

Phase 2 重构后：_handle_multipart_upload 已迁移到 server/__main__.py
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "__main__.py"


def test_multipart_handler_uses_custom_parser_helper():
    text = SERVER.read_text(encoding="utf-8")
    start = text.index('def _handle_multipart_upload')
    end = text.index('def _api_batch_download_start', start)
    section = text[start:end]
    assert 'read_single_file_part(self.rfile, self.headers, field_name="file")' in section
    assert "file_part.data" in section


def test_multipart_handler_no_longer_uses_cgi():
    """Phase 2 重构后：不再导入 cgi，改用 monitor.http_multipart。"""
    text = SERVER.read_text(encoding="utf-8")
    assert 'from monitor.http_multipart import' in text
    assert 'import cgi' not in text

"""Regression tests for the custom multipart parser integration."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "monitor_server.py"


def test_multipart_handler_uses_custom_parser_helper():
    text = SERVER.read_text(encoding="utf-8")
    start = text.index('def _handle_multipart_upload')
    end = text.index('def _api_batch_download_start', start)
    section = text[start:end]
    assert 'read_single_file_part(self.rfile, self.headers, field_name="file")' in section
    assert "file_part.data" in section


def test_multipart_handler_keeps_cgi_backup_as_commented_reference_only():
    text = SERVER.read_text(encoding="utf-8")
    start = text.index('def _handle_multipart_upload')
    end = text.index('def _api_batch_download_start', start)
    section = text[start:end]
    assert '# import cgi' in section
    assert '# form = cgi.FieldStorage(' in section

"""tests/test_batch_download_webui_modal.py — Web UI 批量下载弹窗结构回归测试"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def test_batch_download_modal_uses_modal_overlay_wrapper():
    """批量下载弹窗必须复用现有 modal-overlay 结构，否则 openModal() 不会正确显示。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert '<div class="modal-overlay" id="modalBatchDownload">' in html
    assert '<div class="modal" id="modalBatchDownload"' not in html


def test_batch_download_button_still_exists():
    """头部入口按钮应保留。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'onclick="openBatchDownload()"' in html
    assert '⬇ 批量下载' in html

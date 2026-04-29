"""tests/test_batch_download_webui_modal.py — Web UI 批量下载弹窗结构回归测试

Phase 4 模块化后：
- 弹窗 HTML → templates/modals/modal-batch-download.html
- 入口按钮 → templates/header.html
- 弹窗样式 → static/css/components.css
- JS 逻辑 → index.html
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"
TEMPLATE_FILE = ROOT / "monitor_web" / "templates" / "modals" / "modal-batch-download.html"
HEADER_FILE = ROOT / "monitor_web" / "templates" / "header.html"


def test_batch_download_modal_placeholder_in_index():
    """index.html 应保留模板占位符，供 JS 动态加载。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="tpl-modal-batch-download"' in html


def test_batch_download_modal_extracted_to_template():
    """模态框 HTML 必须提取到模板文件（Phase 4 要求）。"""
    assert TEMPLATE_FILE.exists(), f"模板文件不存在: {TEMPLATE_FILE}"
    content = TEMPLATE_FILE.read_text(encoding="utf-8")
    assert '<div class="modal-overlay" id="modalBatchDownload">' in content
    assert '<div class="modal" id="modalBatchDownload"' not in content


def test_batch_download_button_in_header_template():
    """头部入口按钮在 header.html 模板中。"""
    assert HEADER_FILE.exists()
    content = HEADER_FILE.read_text(encoding="utf-8")
    assert 'onclick="openBatchDownload()"' in content
    assert '批量下载' in content

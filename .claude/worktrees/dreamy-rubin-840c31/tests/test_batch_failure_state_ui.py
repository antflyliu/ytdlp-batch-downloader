"""tests/test_batch_failure_state_ui.py — 批量下载失败终态 UI 回归测试"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def test_batch_failure_state_keeps_start_button_text_for_retry():
    """失败终态不应把主按钮永久改成“✓ 完成”，否则用户无法直接重试。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "btnEl.textContent = '✓ 完成'" not in html


def test_batch_failure_state_does_not_use_success_only_summary_text():
    """失败或部分成功时，汇总文案不能固定使用“下载完成”。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "下载完成 — 成功:" not in html

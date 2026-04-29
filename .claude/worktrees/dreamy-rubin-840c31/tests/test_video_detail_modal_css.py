# -*- coding: utf-8 -*-
"""Regression: 账户列表「详情」依赖 #modalVideoDetail 遮罩层为视口级 fixed + flex。"""

from pathlib import Path


def test_modal_css_video_detail_overlay_is_viewport_layer():
    root = Path(__file__).resolve().parents[1]
    css_path = root / "monitor_web" / "static" / "css" / "modal.css"
    text = css_path.read_text(encoding="utf-8")
    assert "#modalVideoDetail.modal-overlay" in text
    assert "#modalVideoDetail.modal-overlay.show" in text
    start = text.index("#modalVideoDetail.modal-overlay")
    chunk = text[start : start + 900]
    assert "position: fixed" in chunk
    assert "display: flex" in chunk


def test_modal_css_clip_detail_overlay_is_viewport_layer():
    """切片任务详情弹层须与账户弹层同为 fixed + .show 时 flex，否则点击「详情」无可见反应。"""
    root = Path(__file__).resolve().parents[1]
    css_path = root / "monitor_web" / "static" / "css" / "modal.css"
    text = css_path.read_text(encoding="utf-8")
    assert "#modalClipDetail.modal-overlay" in text
    assert "#modalClipDetail.modal-overlay.show" in text
    start = text.index("#modalClipDetail.modal-overlay")
    chunk = text[start : start + 500]
    assert "position: fixed" in chunk
    assert "display: flex" in chunk


def test_modal_css_dyn_provider_drawer_overlay_opens_with_open_modal():
    """动态代理「详情」抽屉须与 openModal 一致：视口 fixed + .show 时 flex（内层 .modal 依赖 .modal--open）。"""
    root = Path(__file__).resolve().parents[1]
    css_path = root / "monitor_web" / "static" / "css" / "modal.css"
    text = css_path.read_text(encoding="utf-8")
    assert "#dynProviderDetailDrawer.modal-overlay" in text
    assert "#dynProviderDetailDrawer.modal-overlay.show" in text
    start = text.index("#dynProviderDetailDrawer.modal-overlay")
    chunk = text[start : start + 900]
    assert "position: fixed" in chunk
    assert "display: flex" in chunk

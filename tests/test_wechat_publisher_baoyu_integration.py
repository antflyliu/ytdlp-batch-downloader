"""Integration tests for baoyu markdown-to-html deep integration."""
from __future__ import annotations


def test_render_result_has_new_fields():
    """Verify WechatArticleRenderResult has all new fields."""
    from monitor.wechat_publisher import WechatArticleRenderResult

    result = WechatArticleRenderResult(
        title="Test",
        content="<p>Test</p>",
        renderer="baoyu-markdown-to-html",
    )
    assert hasattr(result, "cover_image_path")
    assert result.cover_image_path is None
    assert hasattr(result, "layout_modules_used")
    assert result.layout_modules_used == 0
    assert hasattr(result, "reading_time_minutes")
    assert result.reading_time_minutes is None


def test_render_result_new_fields_accept_values():
    """Verify new fields can be set with non-default values."""
    from monitor.wechat_publisher import WechatArticleRenderResult

    result = WechatArticleRenderResult(
        title="Test",
        content="<p>Test</p>",
        renderer="baoyu-markdown-to-html",
        cover_image_path="/path/to/cover.png",
        layout_modules_used=3,
        reading_time_minutes=5.5,
    )
    assert result.cover_image_path == "/path/to/cover.png"
    assert result.layout_modules_used == 3
    assert result.reading_time_minutes == 5.5


def test_local_renderer_code_block():
    """Verify local renderer handles code blocks."""
    from monitor.wechat_publisher import _render_local_markdown
    from pathlib import Path

    md = "```python\nprint('hello')\n```"
    html = _render_local_markdown(md, Path("."))
    assert "hello" in html
    assert "<pre" in html or "<code" in html

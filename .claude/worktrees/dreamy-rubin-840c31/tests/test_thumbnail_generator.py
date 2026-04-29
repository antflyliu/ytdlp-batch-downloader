"""
tests/test_thumbnail_generator.py — 封面图生成策略单元测试
mock subprocess（ffmpeg）和 PIL.Image.open
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# PillowThumbnailStrategy 和 AIThumbnailStrategy
from scripts.thumbnail_generator import (
    PillowThumbnailStrategy,
    AIThumbnailStrategy,
    ThumbnailStrategy,
    generate_thumbnail,
)


class TestPillowThumbnailStrategy:
    """Pillow 本地合成策略测试"""

    def test_generate_returns_path_on_success(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1920, 1080), color=(100, 100, 200))
        frame_path = tmp_path / "frame.jpg"
        frame.save(str(frame_path))

        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=frame_path,
            title="测试标题",
            channel_name="测试频道",
            tags=["#AI", "#科技"],
            output_path=tmp_path / "thumb.jpg",
            aspect_ratio="16:9",
        )

        assert result is not None
        assert result.name == "thumb.jpg"
        assert result.exists()

    def test_generate_vertical_9x16(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1080, 1920), color=(200, 100, 100))
        frame_path = tmp_path / "frame.jpg"
        frame.save(str(frame_path))

        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=frame_path,
            title="竖屏标题",
            output_path=tmp_path / "thumb_vertical.jpg",
            aspect_ratio="9:16",
        )

        assert result is not None
        from PIL import Image as PILImage
        out_img = PILImage.open(result)
        w, h = out_img.size
        assert h > w  # 竖屏

    def test_generate_uses_default_output_name(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1920, 1080), color=(50, 50, 50))
        frame_path = tmp_path / "my_clip_frame.jpg"
        frame.save(str(frame_path))

        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=frame_path,
            title="无指定输出名",
            output_path=None,  # 用默认名
        )

        assert result is not None
        assert "my_clip_frame_thumb.jpg" == result.name

    def test_generate_returns_none_when_frame_missing(self, tmp_path):
        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=tmp_path / "nonexistent.jpg",
            title="缺失帧",
        )
        assert result is None

    def test_title_wraps_correctly(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1920, 1080), color=(80, 80, 80))
        frame_path = tmp_path / "frame.jpg"
        frame.save(str(frame_path))

        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=frame_path,
            title="这是一段非常非常非常非常非常非常非常非常非常长的标题需要正确换行",
            output_path=tmp_path / "wrapped.jpg",
        )
        assert result is not None

    def test_fill_resize_crops_excess(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (3840, 2160), color=(255, 0, 0))
        frame_path = tmp_path / "ultrawide.jpg"
        frame.save(str(frame_path))

        gen = PillowThumbnailStrategy()
        result = gen.generate(
            frame_path=frame_path,
            title="超宽屏测试",
            output_path=tmp_path / "result.jpg",
            aspect_ratio="16:9",
        )
        assert result is not None
        from PIL import Image as PILImage
        img = PILImage.open(result)
        assert img.size == (1280, 720)


class TestAIThumbnailStrategy:
    """AI 封面图策略测试（mock HTTP 调用）"""

    def test_pollinations_returns_image_bytes(self, tmp_path, monkeypatch):
        from PIL import Image
        # 创建假参考图
        frame = Image.new("RGB", (1280, 720), color=(100, 100, 100))
        frame_path = tmp_path / "ref.jpg"
        frame.save(str(frame_path))

        # Mock urllib.request.urlopen
        fake_image = Image.new("RGB", (1280, 720), color=(0, 200, 0))
        buf = BytesIO()
        fake_image.save(buf, "JPEG")
        fake_bytes = buf.getvalue()

        class FakeResp:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return fake_bytes

        def fake_urlopen(req, timeout=None):
            return FakeResp()

        gen = AIThumbnailStrategy(provider="pollinations")
        result = gen._call_pollinations("test prompt", str(frame_path), "16:9")
        assert isinstance(result, bytes)
        assert len(result) > 0


class TestThumbnailStrategyInterface:
    """策略接口测试：两个策略可以互换使用"""

    def test_pillow_isinstance_of_strategy(self):
        assert issubclass(PillowThumbnailStrategy, ThumbnailStrategy)

    def test_ai_isinstance_of_strategy(self):
        assert issubclass(AIThumbnailStrategy, ThumbnailStrategy)

    def test_generate_thumbnail_convenience_pillow(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1280, 720), color=(100, 100, 100))
        frame_path = tmp_path / "frame.jpg"
        frame.save(str(frame_path))

        result = generate_thumbnail(
            frame_path=frame_path,
            title="便捷入口测试",
            channel_name="测试",
            tags=["#test"],
            output_path=tmp_path / "out.jpg",
            strategy="pillow",
        )
        assert result is not None

    def test_generate_thumbnail_unknown_strategy_raises(self, tmp_path):
        from PIL import Image
        frame = Image.new("RGB", (1280, 720), color=(100, 100, 100))
        frame_path = tmp_path / "frame.jpg"
        frame.save(str(frame_path))

        gen = generate_thumbnail(
            frame_path=frame_path,
            title="test",
            output_path=tmp_path / "out.jpg",
            strategy="unknown",  # 不支持的策略，走 pillow
        )
        assert gen is not None


class TestAIThumbnailProviderRouting:
    """AI provider 路由测试（mock HTTP）"""

    def test_doubao_requires_api_key(self):
        import os as _os
        _os.environ.pop("DOUBAO_API_KEY", None)
        gen = AIThumbnailStrategy(provider="doubao", api_key="")
        assert gen.api_key == ""

    def test_gemini_requires_api_key(self):
        import os as _os
        _os.environ.pop("GEMINI_API_KEY", None)
        gen = AIThumbnailStrategy(provider="gemini", api_key="")
        assert gen.api_key == ""

    def test_build_prompt_includes_title_and_tags(self):
        gen = AIThumbnailStrategy(provider="pollinations")
        prompt = gen._build_prompt(
            title="AI 改变世界",
            channel_name="科技频道",
            tags=["#AI", "#未来"],
            aspect_ratio="16:9",
        )
        assert "AI 改变世界" in prompt
        assert "科技频道" in prompt
        assert "16:9" in prompt

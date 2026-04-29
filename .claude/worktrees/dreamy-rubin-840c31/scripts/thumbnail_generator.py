#!/usr/bin/env python3
"""
scripts/thumbnail_generator.py — 封面图生成策略

策略模式，支持两种生成方式：
  1. PillowThumbnailStrategy  — 本地 Pillow 合成（视频帧 + 渐变蒙版 + 居中文字）
  2. AIThumbnailStrategy      — 调用 AI 图片生成接口（Doubao / Gemini / FLUX 等）

使用方式：
    from scripts.thumbnail_generator import PillowThumbnailStrategy

    gen = PillowThumbnailStrategy()
    output = gen.generate(
        frame_path="frame.jpg",
        title="这个 AI 功能太强大了",
        channel_name="科技评测君",
        tags=["#AI", "#科技"],
        output_path="thumb.jpg",
    )

AI 模式：
    from scripts.thumbnail_generator import AIThumbnailStrategy

    gen = AIThumbnailStrategy(provider="doubao", api_key="...")
    output = gen.generate(
        frame_path="frame.jpg",
        title="...",
        channel_name="...",
        tags=["#AI"],
        output_path="thumb.jpg",
        aspect_ratio="16:9",
    )
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 策略接口
# ─────────────────────────────────────────────────────────────────────────────

class ThumbnailStrategy(ABC):
    """封面图生成策略抽象接口"""

    @abstractmethod
    def generate(
        self,
        frame_path: str | Path,
        title: str,
        channel_name: str = "",
        tags: List[str] = None,
        output_path: str | Path | None = None,
        aspect_ratio: str = "16:9",
    ) -> Optional[Path]:
        """
        生成封面图。

        Args:
            frame_path:    视频帧图片路径（JPG/PNG）
            title:        切片标题（核心大字，居中显示）
            channel_name: 频道/频道名（顶部小字）
            tags:         标签列表，如 ["#AI", "#科技"]
            output_path:  输出路径（None 则返回同目录 clip_{id}_thumb.jpg）
            aspect_ratio: 目标比例 "16:9" 或 "9:16"（决定输出分辨率）

        Returns:
            成功返回输出文件 Path，失败返回 None
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Pillow 本地合成策略
# ─────────────────────────────────────────────────────────────────────────────

class PillowThumbnailStrategy(ThumbnailStrategy):
    """
    本地 Pillow 封面图合成。

    布局（16:9 → 1280×720，9:16 → 720×1280）：
      - 视频帧缩放铺满背景
      - 底部 45% 高度叠加深色渐变蒙版（保证文字可读）
      - 顶部居中：频道名（14px，灰色）
      - 中央居中：标题大字（bold，48-72px，白色，多行最多3行）
      - 标题下方：标签 pill 排列（accent 色圆角矩形 + 白色文字）
      - 右下角：高光图标 + 时间戳（可选）

    字体策略（优先级递减）：
      1. 用户指定字体路径（config）
      2. Windows 系统中文字体：C:/Windows/Fonts/ 下查找
      3. 英文/数字回退：Arial / Helvetica
    """

    # 9:16 竖屏分辨率
    RESOLUTION_9_16 = (720, 1280)
    # 16:9 横屏分辨率
    RESOLUTION_16_9 = (1280, 720)

    # 渐变蒙版高度（占图片总高的比例）
    GRADIENT_HEIGHT_RATIO = 0.45

    def __init__(self, font_title_path: str | None = None, font_sub_path: str | None = None):
        """
        Args:
            font_title_path: 标题字体文件路径（支持 .ttf / .otf）
                             Windows 常见中文字体：
                               C:\\Windows\\Fonts\\msyh.ttc  (微软雅黑)
                               C:\\Windows\\Fonts\\simhei.ttf (黑体)
                               C:\\Windows\\Fonts\\simsun.ttc (宋体)
                             留空则自动查找系统字体。
            font_sub_path:   副文字体路径（频道名、标签）
        """
        self.font_title_path = font_title_path
        self.font_sub_path = font_sub_path or font_title_path

    def generate(
        self,
        frame_path: str | Path,
        title: str,
        channel_name: str = "",
        tags: List[str] = None,
        output_path: str | Path | None = None,
        aspect_ratio: str = "16:9",
    ) -> Optional[Path]:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter
        except ImportError:
            logger.error("Pillow 未安装，请运行：pip install Pillow")
            return None

        tags = tags or []
        frame_path = Path(frame_path)

        if not frame_path.exists():
            logger.error(f"视频帧不存在: {frame_path}")
            return None

        # 分辨率
        is_vertical = aspect_ratio == "9:16"
        width, height = (
            self.RESOLUTION_9_16 if is_vertical else self.RESOLUTION_16_9
        )

        # 加载帧并缩放铺满
        try:
            frame = Image.open(frame_path).convert("RGB")
        except Exception as e:
            logger.error(f"无法打开视频帧: {e}")
            return None

        # 把帧缩放覆盖整张图（fill 模式，裁剪多余部分）
        frame_filled = self._fill_resize(frame, width, height)

        # 叠加暗角/模糊（提升文字区域对比度）
        darkened = self._apply_darkening(frame_filled, height, is_vertical)

        # 绘制文字
        draw = ImageDraw.Draw(darkened)
        self._draw_text(draw, width, height, channel_name, title, tags, is_vertical)

        # 保存
        output_path = Path(output_path) if output_path else frame_path.parent / f"{frame_path.stem}_thumb.jpg"
        try:
            darkened.save(str(output_path), "JPEG", quality=92)
            logger.info(f"封面图已生成: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"封面图保存失败: {e}")
            return None

    def _fill_resize(self, img: "Image.Image", target_w: int, target_h: int) -> "Image.Image":
        """把图片缩放至覆盖目标尺寸（裁剪多余部分），返回缩放后的图片"""
        from PIL import Image
        img_w, img_h = img.size
        target_ratio = target_w / target_h
        img_ratio = img_w / img_h

        if img_ratio > target_ratio:
            # 图片更宽 → 以高度为基准缩放，裁剪宽度
            new_h = target_h
            new_w = int(img_ratio * new_h)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - target_w) // 2
            img = img.crop((left, 0, left + target_w, target_h))
        else:
            # 图片更高 → 以宽度为基准缩放，裁剪高度
            new_w = target_w
            new_h = int(new_w / img_ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            top = (new_h - target_h) // 2
            img = img.crop((0, top, target_w, top + target_h))

        return img

    def _apply_darkening(
        self, img: "Image.Image", height: int, is_vertical: bool
    ) -> "Image.Image":
        """
        底部渐变暗化 + 轻微高斯模糊（让文字区域更突出）。
        """
        from PIL import Image as PILImage, ImageDraw, ImageFilter
        gradient_h = int(height * self.GRADIENT_HEIGHT_RATIO)
        overlay = PILImage.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 从 gradient_h 高度开始向下渐变到完全不透明
        for y in range(gradient_h, height):
            # alpha 从 0 线性增长到 200（最大 255）
            alpha = int((y - gradient_h) / (height - gradient_h) * 200)
            draw.line([(0, y), (img.width, y)], fill=(0, 0, 0, alpha))

        # 模糊帧增加质感（轻微）
        blurred = img.filter(ImageFilter.GaussianBlur(radius=2))

        # 叠加渐变
        from PIL import Image as PILImage
        if blurred.mode != "RGBA":
            blurred = blurred.convert("RGBA")
        result = PILImage.alpha_composite(blurred, overlay)
        return result.convert("RGB")

    def _draw_text(
        self,
        draw: "ImageDraw.Draw",
        width: int,
        height: int,
        channel_name: str,
        title: str,
        tags: List[str],
        is_vertical: bool,
    ) -> None:
        """
        在图上绘制文字层。

        竖屏布局与横屏相同，只是坐标系以 height > width 的图片为准。
        """
        from PIL import ImageFont

        # 字体
        font_title = self._load_font(self.font_title_path, self._title_size(is_vertical), bold=True)
        font_sub = self._load_font(self.font_sub_path, self._sub_size(is_vertical), bold=False)
        font_tag = self._load_font(self.font_sub_path, self._tag_size(is_vertical), bold=False)

        cx = width // 2  # 水平中心

        # ── 顶部区域（y = 10% ~ 35%）─────────────────────────────────
        if channel_name:
            sub_text = channel_name[:30]
            sub_bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
            sub_w = sub_bbox[2] - sub_bbox[0]
            sub_h = sub_bbox[3] - sub_bbox[1]
            sub_x = (width - sub_w) // 2
            sub_y = int(height * 0.06)
            draw.text((sub_x, sub_y), sub_text, font=font_sub, fill=(200, 200, 200, 255))

        # ── 中央标题区（y = 35% ~ 75%）────────────────────────────────
        # 计算可用宽度（左右各 8% padding）
        max_text_w = int(width * 0.84)
        max_lines = 3 if not is_vertical else 4

        title_lines = self._wrap_text(title, font_title, max_text_w, max_lines)
        line_h = self._line_height(font_title, is_vertical)
        total_text_h = len(title_lines) * line_h
        # 起始 y：图片 40% 高度位置（渐变区域偏下）
        title_start_y = int(height * 0.40) - int(total_text_h * 0.3)

        for i, line in enumerate(title_lines):
            line_y = title_start_y + i * line_h
            bbox = draw.textbbox((0, 0), line, font=font_title)
            lw = bbox[2] - bbox[0]
            lx = (width - lw) // 2
            # 白色大字，带轻微阴影
            self._draw_text_with_shadow(draw, (lx, line_y), line, font_title)

        # ── 标签区（y = 标题下方 + 10px）──────────────────────────────
        tag_y = title_start_y + len(title_lines) * line_h + int(height * 0.03)

        if tags and tag_y < height * 0.88:
            self._draw_tags(draw, cx, tag_y, tags, font_tag, is_vertical)

    def _draw_text_with_shadow(
        self, draw: "ImageDraw.Draw", pos: tuple, text: str, font
    ) -> None:
        """绘制文字：阴影 + 主文字"""
        # 阴影（向右+向下偏移1像素，黑色半透明）
        shadow_pos = (pos[0] + 1, pos[1] + 1)
        draw.text(shadow_pos, text, font=font, fill=(0, 0, 0))
        draw.text(pos, text, font=font, fill=(255, 255, 255))

    def _draw_tags(
        self,
        draw: "ImageDraw.Draw",
        cx: int,
        tag_y: int,
        tags: List[str],
        font,
        is_vertical: bool,
    ) -> None:
        """绘制标签 pill 排列"""
        # Accent 色：品牌 Terracotta (#c96442) 或项目的品牌色
        pill_color = (201, 100, 66)   # Terracotta RGB
        pill_padding_x = 10
        pill_padding_y = 4
        pill_spacing = 8
        corner_radius = 12

        # 计算每个 pill 的尺寸
        tag_rounded = [t[:20] for t in tags]  # 截断超长标签
        tag_bboxes = []
        for t in tag_rounded:
            bb = draw.textbbox((0, 0), t, font=font)
            tag_w = bb[2] - bb[0] + pill_padding_x * 2
            tag_h = bb[3] - bb[1] + pill_padding_y * 2
            tag_bboxes.append((t, tag_w, tag_h))

        # 如果总宽度超出，按两行排列
        line_h = max(h for _, _, h in tag_bboxes) + pill_spacing
        lines = []
        current_line = []
        current_line_w = 0
        max_line_w = int(cx * 1.8)  # 允许宽度

        for tb in tag_bboxes:
            if current_line_w + tb[1] > max_line_w and current_line:
                lines.append(current_line)
                current_line = [tb]
                current_line_w = tb[1]
            else:
                current_line.append(tb)
                current_line_w += tb[1] + pill_spacing
        if current_line:
            lines.append(current_line)

        # 从 tag_y 开始往下画
        for line_i, line_items in enumerate(lines):
            line_y = tag_y + line_i * line_h
            total_line_w = sum(t[1] for t in line_items) + pill_spacing * (len(line_items) - 1)
            cur_x = cx - total_line_w // 2

            for text, tag_w, tag_h in line_items:
                pill_x0 = cur_x
                pill_y0 = line_y
                pill_x1 = cur_x + tag_w
                pill_y1 = line_y + tag_h

                # 圆角矩形
                self._rounded_rectangle(draw, (pill_x0, pill_y0, pill_x1, pill_y1), corner_radius, pill_color)

                # 文字（居中于 pill）
                tb = draw.textbbox((0, 0), text, font=font)
                tw = tb[2] - tb[0]
                th = tb[3] - tb[1]
                tx = cur_x + (tag_w - tw) // 2
                ty = line_y + (tag_h - th) // 2 - 1
                draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

                cur_x += tag_w + pill_spacing

    def _rounded_rectangle(
        self, draw: "ImageDraw.Draw", coords: tuple, radius: int, fill: tuple
    ) -> None:
        """绘制圆角矩形（高度不足时自动降级为普通矩形）"""
        x0, y0, x1, y1 = coords
        box_h = y1 - y0
        box_w = x1 - x0
        # 高度不够画圆角 → 直接画普通矩形
        if box_h <= radius * 2 or box_w <= radius * 2:
            draw.rectangle([x0, y0, x1, y1], fill=fill)
            return
        draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
        draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
        draw.pieslice([x0, y0, x0 + 2 * radius, y0 + 2 * radius], 180, 270, fill=fill)
        draw.pieslice([x1 - 2 * radius, y0, x1, y0 + 2 * radius], 270, 360, fill=fill)
        draw.pieslice([x0, y1 - 2 * radius, x0 + 2 * radius, y1], 90, 180, fill=fill)
        draw.pieslice([x1 - 2 * radius, y1 - 2 * radius, x1, y1], 0, 90, fill=fill)

    def _wrap_text(self, text: str, font, max_width: int, max_lines: int) -> List[str]:
        """把文字按 max_width 换行，返回行列表"""
        import textwrap
        # 简单按空格/标点换行
        words = text
        lines = []
        current = ""
        for char in words:
            test = current + char
            bbox = font.getbbox(test)
            tw = bbox[2] - bbox[0]
            if tw > max_width and current:
                lines.append(current)
                current = char
                if len(lines) >= max_lines:
                    break
            else:
                current = test
        if current and len(lines) < max_lines:
            lines.append(current)
        # 最后一行的收尾
        if not lines:
            lines = [text[:max_lines * 30]]
        return lines[:max_lines]

    def _line_height(self, font, is_vertical: bool) -> int:
        bbox = font.getbbox("Ay")
        return int((bbox[3] - bbox[1]) * 1.3)

    def _title_size(self, is_vertical: bool) -> int:
        return 56 if not is_vertical else 48

    def _sub_size(self, is_vertical: bool) -> int:
        return 16 if not is_vertical else 14

    def _tag_size(self, is_vertical: bool) -> int:
        return 14 if not is_vertical else 12

    def _load_font(self, font_path: str | None, size: int, bold: bool = False):
        """
        加载字体，失败时回退到默认字体。
        优先级：指定路径 → Windows 中文字体 → 系统默认
        """
        from PIL import ImageFont

        # 尝试用户指定路径
        if font_path:
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                logger.warning(f"指定字体加载失败: {font_path}，尝试系统字体")

        # Windows 系统中文字体候选
        windows_fonts = [
            "C:\\Windows\\Fonts\\msyh.ttc",   # 微软雅黑
            "C:\\Windows\\Fonts\\simhei.ttf",   # 黑体
            "C:\\Windows\\Fonts\\simsun.ttc",  # 宋体
            "C:\\Windows\\Fonts\\consola.ttf", # 等宽
        ]
        for fp in windows_fonts:
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass

        # 回退到默认
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# AI 封面图策略
# ─────────────────────────────────────────────────────────────────────────────

class AIThumbnailStrategy(ThumbnailStrategy):
    """
    调用 AI 图片生成接口制作封面图。

    支持 providers：
      - "doubao"  : 火山引擎 Doubao 图片生成（支持中文）
      - "gemini"  : Google Gemini 2.0 Flash 图片生成
      - "flux"    : FLUX via Replicate
      - "dalle"   : OpenAI DALL-E 3（需 OpenAI API）
      - "pollinations": Pollinations.AI（免费，无需 key）

    工作流：
      1. 先用 PillowThumbnailStrategy 生成帧+蒙版作为参考图
      2. 将参考图 base64 编码，随 prompt 一起发给 AI
      3. AI 参考原图色调/构图，生成带设计封面的新图
    """

    PROVIDER_DEFAULT_MODEL = {
        "doubao": "doubao-seedance-250414",
        "gemini": "gemini-2.0-flash-preview",
        "flux": "black-forest-labs/flux-dev",
        "dalle": "dall-e-3",
        "pollinations": "v2",
    }

    def __init__(
        self,
        provider: str = "pollinations",  # 默认用免费的 pollinations
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 120,
    ):
        self.provider = provider.lower()
        self.api_key = api_key or ""
        self.base_url = base_url
        self.model = model or self.PROVIDER_DEFAULT_MODEL.get(self.provider, "")
        self.timeout = timeout

    def generate(
        self,
        frame_path: str | Path,
        title: str,
        channel_name: str = "",
        tags: List[str] = None,
        output_path: str | Path | None = None,
        aspect_ratio: str = "16:9",
    ) -> Optional[Path]:
        tags = tags or []
        frame_path = Path(frame_path)
        output_path = Path(output_path) if output_path else frame_path.parent / f"{frame_path.stem}_ai_thumb.jpg"

        # Step 1: 生成 Pillow 参考图（构图/色调参考）
        pillow_gen = PillowThumbnailStrategy()
        ref_path = frame_path.parent / f"{frame_path.stem}_ref.jpg"
        ref = pillow_gen.generate(
            frame_path=frame_path,
            title=title,
            channel_name=channel_name,
            tags=tags,
            output_path=ref_path,
            aspect_ratio=aspect_ratio,
        )
        if not ref:
            logger.error("AI 封面生成失败：无法生成参考图")
            return None

        # Step 2: 构建 prompt
        prompt = self._build_prompt(title, channel_name, tags, aspect_ratio)

        # Step 3: 调用 AI 生成
        try:
            image_bytes = self._call_ai(prompt, str(ref), aspect_ratio)
        except Exception as e:
            logger.error(f"AI 封面生成失败: {e}")
            return ref  # 回退到 Pillow 参考图

        # Step 4: 保存 AI 生成图
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(image_bytes)).convert("RGB")
            img.save(str(output_path), "JPEG", quality=92)
            logger.info(f"AI 封面图已生成: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"AI 封面图保存失败: {e}")
            return ref

    def _build_prompt(self, title: str, channel_name: str, tags: List[str], aspect_ratio: str) -> str:
        ratio_desc = "vertical 9:16 (720x1280)" if aspect_ratio == "9:16" else "horizontal 16:9 (1280x720)"
        tag_str = " ".join(tags) if tags else ""

        # 中文 prompt（AI 图片生成器通常支持中文描述）
        parts = [
            f"视频封面设计，{ratio_desc}",
            f"主题：{title}",
        ]
        if channel_name:
            parts.append(f"频道/来源：{channel_name}")
        if tag_str:
            parts.append(f"标签：{tag_str}")
        parts.extend([
            "设计要求：",
            "- 保持原视频帧的色调和氛围",
            "- 底部有深色渐变区域用于放文字",
            "- 标题居中突出显示，简洁有力",
            "- 风格：现代感、科技感、高质量",
            "- 不要水印，不要版权文字",
        ])
        return "\n".join(parts)

    def _call_ai(self, prompt: str, ref_image_path: str, aspect_ratio: str) -> bytes:
        if self.provider == "pollinations":
            return self._call_pollinations(prompt, ref_image_path, aspect_ratio)
        elif self.provider == "doubao":
            return self._call_doubao(prompt, ref_image_path)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, ref_image_path)
        elif self.provider == "dalle":
            return self._call_dalle(prompt, aspect_ratio)
        else:
            raise ValueError(f"不支持的 AI provider: {self.provider}")

    def _call_pollinations(self, prompt: str, ref_image_path: str, aspect_ratio: str) -> bytes:
        """
        Pollinations.AI — 免费无需 key，支持图片+prompt
        通过 URL 参数传递 prompt，返回图片 bytes
        """
        import urllib.request, urllib.parse
        from PIL import Image
        from io import BytesIO

        width, height = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)

        encoded_prompt = urllib.parse.quote(prompt[:500])
        # pollinations 接受 prompt 参数，AI 参考图通过 seed 控制
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width={width}&height={height}&seed=42&nologo=true"
        )
        logger.info(f"调用 Pollinations.AI: {url[:100]}...")

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    def _call_doubao(self, prompt: str, ref_image_path: str) -> bytes:
        """
        火山引擎 Doubao 图片生成
        API 文档: https://www.volcengine.com/docs/AMS/AMS10010
        """
        import requests, base64
        from PIL import Image
        from io import BytesIO

        api_key = self.api_key or os.environ.get("DOUBAO_API_KEY", "")
        if not api_key:
            raise ValueError("Doubao API key 未设置，请设置 DOUBAO_API_KEY 环境变量或传入 api_key")

        # 读取参考图并 base64
        with open(ref_image_path, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()

        endpoint = self.base_url or "https://ark.cn-beijing.volcengineapi.com"
        url = f"{endpoint}/v2/image/generations"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "image_base64": ref_b64,
            "return_url": False,  # 返回 base64
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # 返回图片 bytes
        img_data = data.get("data", {}).get("image_bytes") or data.get("data", {}).get("image_base64")
        if isinstance(img_data, str):
            return base64.b64decode(img_data)
        raise ValueError(f"Doubao 返回格式异常: {data}")

    def _call_gemini(self, prompt: str, ref_image_path: str) -> bytes:
        """
        Google Gemini 2.0 Flash 图片生成
        API: https://ai.google.dev/gemini-api/docs/image-generation
        """
        import requests, base64, json

        api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("Gemini API key 未设置，请设置 GEMINI_API_KEY 环境变量或传入 api_key")

        model = self.model or "gemini-2.0-flash-preview"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        with open(ref_image_path, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": ref_b64}},
                ]
            }],
            "generation_config": {"response_modalities": ["TEXT", "IMAGE"]},
        }

        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # 解析图片 parts
        for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            if "inline_data" in part:
                return base64.b64decode(part["inline_data"]["data"])
        raise ValueError(f"Gemini 返回中没有图片: {data}")

    def _call_dalle(self, prompt: str, aspect_ratio: str) -> bytes:
        """
        OpenAI DALL-E 3
        """
        import requests, base64

        api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OpenAI API key 未设置，请设置 OPENAI_API_KEY 环境变量或传入 api_key")

        style = "natural" if "natural" in prompt.lower() else "vivid"
        size = "1024x1024" if aspect_ratio == "1:1" else ("1024x1792" if aspect_ratio == "9:16" else "1792x1024")

        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model or "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": size,
            "style": style,
            "response_format": "b64_json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return base64.b64decode(data["data"][0]["b64_json"])


# ─────────────────────────────────────────────────────────────────────────────
# 便捷入口
# ─────────────────────────────────────────────────────────────────────────────

def generate_thumbnail(
    frame_path: str | Path,
    title: str,
    channel_name: str = "",
    tags: List[str] = None,
    output_path: str | Path | None = None,
    aspect_ratio: str = "16:9",
    strategy: str = "pillow",   # "pillow" | "ai"
    ai_provider: str = "pollinations",
    ai_api_key: str | None = None,
    ai_base_url: str | None = None,
    font_title_path: str | None = None,
) -> Optional[Path]:
    """
    封面图生成便捷入口。

    Args:
        strategy:     生成策略，"pillow"（本地 Pillow）或 "ai"（AI 图片生成）
        ai_provider:  AI provider（pillow 模式忽略）
        ai_api_key:   AI API key
        ai_base_url:  AI API base URL（用于兼容 OpenAI 兼容接口）
        font_title_path: 标题字体路径

    Returns:
        成功返回封面图 Path，失败返回 None
    """
    if strategy == "ai":
        gen = AIThumbnailStrategy(
            provider=ai_provider,
            api_key=ai_api_key,
            base_url=ai_base_url,
        )
    else:
        gen = PillowThumbnailStrategy(font_title_path=font_title_path)

    return gen.generate(
        frame_path=frame_path,
        title=title,
        channel_name=channel_name,
        tags=tags,
        output_path=output_path,
        aspect_ratio=aspect_ratio,
    )

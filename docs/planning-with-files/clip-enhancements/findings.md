# 研究发现：clip-enhancements

---

## 用户需求确认

| 需求 | 决策 |
|------|------|
| 竖屏 9:16 | ✅ 支持，原片 9:16 输出保持 9:16 |
| 字幕方式 | ✅ 软字幕（mkv 封装），播放器可切换开关 |
| 封面图用途 | ✅ 发帖/分享配图，需输出独立图片文件 |

---

## 封面图生成方案

### 结论：Pillow 合成封面图（策略模式）

**架构**：`ThumbnailStrategy`（抽象基类）→ `PillowThumbnailStrategy` / `AIThumbnailStrategy`

**PillowThumbnailStrategy 布局（1280×720 / 720×1280）**：
```
频道名（小字 16px，灰色，居顶部 6%）← 频道信息层
────────────────────────────────────────────
          【Clip 标题大字】                ← 核心层，白色 48-56px，shadow
          多行自动换行（最多 3-4 行）

  [#AI] [#科技] [#话题]                   ← 标签 pill，Terracotta 色圆角矩形
████████████████████████████████（底部 45% 渐变蒙版）
```
- 字体：微软雅黑 → 黑体 → Arial 回退
- 文字：白色大字 + 1px 黑色阴影
- 蒙版：底部 45% 高度，从透明线性渐变到半透明黑色
- 填充：`fill_resize` 保持构图（以高或宽为基准缩放，裁剪多余）

**AIThumbnailStrategy 工作流**：
1. Pillow 生成构图参考帧（保留原帧色调）
2. 参考帧 base64 编码 + prompt → AI 图片生成器
3. 支持 providers：Doubao（火山引擎）/ Gemini（Google）/ Pollinations（免费）
4. AI 失败时自动回退到 Pillow 原图

**便捷入口**：
```python
from scripts.thumbnail_generator import generate_thumbnail
generate_thumbnail(frame, title, channel, tags,
    strategy="pillow",          # 或 "ai"
    ai_provider="pollinations", # Doubao / Gemini / Pollinations
    ai_api_key="sk-...",
)
```

```bash
# 从切片起始时间 + 0.5s 提取一帧
ffmpeg -y -ss 0.5 -i input.mp4 -frames:v 1 -q:v 2 thumb.jpg
```

- `-y`：覆盖已有文件
- `-ss 0.5`：从第 0.5 秒开始（避免黑帧）
- `-frames:v 1`：只取一帧
- `-q:v 2`：JPEG 质量（1=最高，31=最低，2~5 适合缩略图）

**输出命名**：`clip_{id}_thumb.jpg`，与 clip 同目录

**Pillow 缩放**（可选）：如需统一封面图尺寸
```python
from PIL import Image
img = Image.open('thumb.jpg')
img.resize((640, 360), Image.LANCZOS).save('thumb_small.jpg', quality=90)
```

---

## 字幕软封装方案

### 结论：mkv 封装，ASS 中间格式

**为什么不用硬字幕**：硬字幕烧进视频无法关闭，用户希望能切换字幕开关

**为什么转 ASS**：ASS 支持字体样式（颜色/大小/位置），比 SRT 好看

```bash
# .vtt → .ass 转换（via ffmpeg内置)
ffmpeg -y -i subtitle.vtt subtitle.ass

# 封装进 mkv
ffmpeg -y -i input.mp4 -i subtitle.ass \
  -c:v copy -c:a copy -c:s ass \
  output.mkv
```

**Windows 字体问题**：
- ffmpeg subtitles filter 在 Windows 上需指定 `force_style` 或 `fonts_dir`
- ASS 格式可在文件内嵌字体名，实际播放依赖系统字体
- 建议：直接用 `subtitle.vtt` 不转换，ffmpeg mkv 封装时 `-c:s copy` 直接流复制

```bash
# 最简方案：.vtt → mkv 直接封装（无需转换格式）
ffmpeg -y -i input.mp4 -i subtitle.vtt \
  -c:v copy -c:a copy -c:s copy \
  output.mkv
```

---

## 长宽比自适应方案

### 结论：ffprobe 检测 → scale + pad 黑边填充

#### Step 1: ffprobe 检测比例

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height \
  -of csv=p=0 input.mp4
# 输出: 1920,1080
```

Python 封装：
```python
import subprocess, json
result = subprocess.run([
    'ffprobe', '-v', 'error',
    '-select_streams', 'v:0',
    '-show_entries', 'stream=width,height',
    '-of', 'json', input
], capture_output=True, text=True)
info = json.loads(result.stdout)
w, h = info['streams'][0]['width'], info['streams'][0]['height']
ratio = w / h  # 1.78 = 16:9, 0.56 = 9:16
```

#### Step 2: scale + pad 策略

**目标 9:16（竖屏）**：
```bash
# 原视频宽度 w=1920, h=1080, ratio=1.78
# 目标宽度=1080，高度=1920
# scale 到宽度1080，高度等比=607
# 上下 pad 黑边至1920
-vf "scale=1080:-1,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
```

**目标 16:9（横屏）**：
```bash
# scale 到高度1080，宽度等比=1920
# 左右 pad 黑边至1920（如果原本就是16:9则不需pad）
-vf "scale=-1:1080,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"
```

**判断逻辑**：
```python
ratio = w / h
if abs(ratio - 16/9) < 0.1:
    target = "16:9"
elif abs(ratio - 9/16) < 0.1:
    target = "9:16"
else:
    target = "4:3"  # 或 other，保持原样
```

---

## 实施顺序设计

```
Phase 2 封面图（最独立，不依赖其他）
→ Phase 4 比例自适应（视频处理，与字幕独立）
→ Phase 3 字幕封装（最后做，因为涉及容器转换）
→ Phase 5 集成 + 配置
→ Phase 6 测试
```

**原因**：
- 封面图最独立，提取后不影响后续流程
- 比例自适应需在字幕封装前做（视频需重新编码）
- 字幕封装用 `-c copy` 不重编码视频音频，只需处理字幕流，最轻量放最后

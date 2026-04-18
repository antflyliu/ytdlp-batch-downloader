# 任务计划：clip-enhancements — 视频切片增强功能

## 目标

在 AI 视频切片 Pipeline 基础上，新增三个增强功能：

1. **封面图生成** — 为每个切片自动生成高质量缩略图（用于发帖/分享配图）
2. **字幕软封装** — 将字幕（.vtt）封装进 mkv，支持播放器切换字幕开关
3. **长宽比自适应** — 原片 9:16 → 输出 9:16；原片 16:9 → 输出 16:9（竖屏/横屏自动适配）

---

## 当前阶段

**Phase 6: 测试验证** — 进行中（单元测试完成，集成测试待人工验证）

---

## 需求确认（用户已确认）

- ✅ **竖屏 9:16**：支持，原片 9:16 输出保持 9:16
- ✅ **字幕方式**：软字幕（mkv 封装），播放器可切换开关
- ✅ **封面图用途**：发帖/分享配图，需输出高质量图片文件

---

## Phase 1: 需求分析与技术选型
- [x] 1.1 封面图方案：**ffmpeg** 从切片起始帧提取（无需 moviepy），输出 **JPG**
- [x] 1.2 字幕方案：**软字幕 mkv 封装**（`ffmpeg -c:s ass`），不用硬烧
- [x] 1.3 长宽比方案：**ffprobe 检测** → `scale + pad` 填充黑边，保持原比例
- [x] 1.4 编码方案：切片用 `libx264 -preset fast -crf 23`，合集用 `copy`
- [x] 1.5 与现有 Pipeline 集成方式设计
- **Status:** complete

## Phase 2: 封面图生成
- [x] 2.1 `scripts/thumbnail_generator.py`（新文件）：`ThumbnailStrategy` 抽象接口 + `PillowThumbnailStrategy` + `AIThumbnailStrategy`
- [x] 2.2 Pillow 策略：视频帧 → fill-resize → 底部渐变蒙版 → 居中标题（多行换行）→ 标签 pill → 输出 JPG
- [x] 2.3 AI 策略：先 Pillow 生成参考帧 → 调用 AI 图片生成（Doubao/Gemini/Pollinations）→ 回退到 Pillow 图
- [x] 2.4 策略可替换：`generate_thumbnail(strategy="pillow"|"ai", ai_provider="doubao"|"gemini"|"pollinations")`
- [x] 2.5 单元测试：14 个测试用例全部通过

## Phase 3: 字幕软封装
- [x] 3.1 `.vtt` → `.ass` 格式转换（ASS 支持更多样式标签）
- [x] 3.2 `video_processor.py` 新增 `embed_subtitles_soft(input_video, subtitle_srt, output_mkv)` 函数
- [x] 3.3 `ffmpeg -i input.mp4 -i subtitle.ass -c copy -c:s ass output.mkv`
- [x] 3.4 判断输入字幕是否为 `.vtt`，自动转换后再封装
- [x] 3.5 配置项：`soft_subtitle_enabled`（默认开启）

## Phase 4: 长宽比自适应
- [x] 4.1 `video_processor.py` 新增 `detect_aspect_ratio(video_path)` → `16:9 | 9:16 | 4:3 | other`
- [x] 4.2 `video_processor.py` 新增 `ensure_aspect_ratio(input, target_ratio, output)` 函数
  - `target_ratio`: `"9:16"` 或 `"16:9"`
  - 实现：若已是目标比例 → `copy`；否则 → `scale + pad`（缩放到目标宽度，填充黑边）
- [x] 4.3 竖屏 9:16：scale 宽度至 1080，高度等比 → pad 上下至 1920，黑色填充
- [x] 4.4 横屏 16:9：scale 高度至 1080，宽度等比 → pad 左右至 1920，黑色填充
- [x] 4.5 在 Step6 切片生成后、字幕封装前调用比例适配

## Phase 5: Pipeline 集成
- [x] 5.1 `video_processor.py`：新增 4 个函数（封面/字幕/比例检测/比例适配）
- [x] 5.2 `clip_pipeline.py` Step6：调用增强三件套（封面 → 比例适配 → 字幕封装）
- [x] 5.3 配置项持久化：
  - `config/settings.py`：`clip_embed_thumbnail`、`clip_embed_subtitle`、`clip_adapt_aspect_ratio`（均默认 True），`clip_thumbnail_quality`（默认 2）
  - `monitor/db/migrations.py` v15：`clip_tasks` 表新增 `thumbnail_path`、`subtitles_path`、`aspect_ratio` 字段
- [x] 5.4 GUI 配置界面：前端 modal-config.html 新增 3 个复选框，config.js 读写逻辑

## Phase 6: 测试与验证
- [x] 6.1 单元测试覆盖：`video_processor.py` 4 个新函数全部通过 28 个测试用例
- [ ] 6.2 集成测试：完整 Pipeline 运行（含真实 ffmpeg）
- [ ] 6.3 人工验证：VLC/mpv 播放 mkv 字幕切换

---

## 技术约束

- 运行环境：Windows（ffmpeg 已集成在项目中）
- Python 版本：3.12+
- 依赖：`ffmpeg`（已有）、`pillow`（封面图缩放可选）
- 无需 GPU（优先 CPU 方案）

## 依赖项目

- `scripts/video_processor.py` — 现有 FFmpeg 封装，需新增 4 个函数
- `scripts/clip_pipeline.py` — Step6 视频生成，需调用增强三件套
- `scripts/text_processor.py` — 字幕解析（.vtt → .ass 转换）

## 风险评估

- **中**：ffmpeg subtitles（ASS）在 Windows 上需要字体文件路径，可能需指定 `fonts_dir`
- **低**：9:16 竖屏 YouTube 内容较少，但算法逻辑与横屏对称，可后验

## 实施顺序

```
Phase 2（封面）→ Phase 4（比例）→ Phase 3（字幕）→ Phase 5（集成）→ Phase 6（测试）
```
（字幕放最后是因为 mkv 封装涉及容器转换，放在 Step6 最后一步不影响切片本身生成）

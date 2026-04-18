# 进度记录：clip-enhancements

---

## 2026-04-17

### 任务启动
- 创建 `docs/planning-with-files/clip-enhancements/`（接档 autoclip-integration）
- 更新 `.planning-active` → `clip-enhancements`

### Phase 1 需求确认（用户已确认）

| 需求 | 确认 |
|------|------|
| 竖屏 9:16 | ✅ 支持，保持原比例 |
| 字幕方式 | ✅ 软字幕（mkv 封装，可切换） |
| 封面图用途 | ✅ 发帖/分享配图，输出 JPG 文件 |

### Phase 1 初步研究结论

**封面图**：`ffmpeg -ss 0.5 -i input.mp4 -frames:v 1 -q:v 2 thumb.jpg`，
取 clip 起始+0.5s 一帧，输出 JPG，命名 `clip_{id}_thumb.jpg`

**字幕**：`ffmpeg -c:v copy -c:a copy -c:s copy input.mp4 subtitle.vtt output.mkv`，
.vtt 直接封装进 mkv，无需转换 ASS

**长宽比**：`ffprobe` 检测宽高比判断 9:16 vs 16:9，
scale+pad 填充黑边到目标分辨率

### 已完成工作
- [x] Phase 2：`scripts/thumbnail_generator.py`（新文件）— ThumbnailStrategy 策略接口 + PillowThumbnailStrategy + AIThumbnailStrategy
- [x] Phase 2：封面图 Pillow 布局（渐变蒙版 + 居中标题 + 标签 pill，圆角矩形）
- [x] Phase 2：AI 封面生成（Doubao/Gemini/Pollinations），失败回退到 Pillow
- [x] Phase 4：`VideoProcessor.detect_aspect_ratio()` + `ensure_aspect_ratio()`
- [x] Phase 3：`VideoProcessor.embed_subtitles_soft()`
- [x] Phase 5.1：4 个函数加入 video_processor.py
- [x] Phase 5.2：Step6Video 新增 `_enhance_clips()` + `_find_subtitle()`
- [x] Phase 5.3：config/settings.py 新增 4 个配置项；migrations.py v15 新增 3 个 clip_tasks 字段
- [x] Phase 5.4：modal-config.html 新增 3 个复选框；config.js 读写逻辑
- [x] Phase 6：thumbnail_generator.py 14 个单元测试全部通过

### Phase 6 完成
- [x] 单元测试：video_processor.py 4 个函数 × 14 个新测试用例，全部通过
- [x] 单元测试：thumbnail_generator.py 14 个策略测试全部通过
- [x] 集成测试：真实 ffmpeg 运行（detect/extract/embed/ensure_aspect_ratio/Pillow生成）全部通过
- [ ] 人工验证：VLC/mpv 播放 mkv 字幕切换

---

## 历史（来自 autoclip-integration）

见 `docs/planning-with-files/autoclip-integration/progress.md`

# Pixelle-Video 视频生成功能集成设计方案

**日期**: 2026-04-25
**目标**: 在 ytdlp-batch-downloader 中新增「AI视频生成」功能，实现「主题/文案 → 配图 → 语音 → 视频」的完整工作流

---

## 1. 背景与目标

### 1.1 用户场景

用户希望将一个主题或文案通过 AI 自动生成一段配图短视频（类似 Pixelle-Video 的核心能力），与现有的「视频 → 文章」流程形成互补。

### 1.2 涉及项目

| 项目 | 角色 | 关系 |
|------|------|------|
| ytdlp-batch-downloader | 主项目 | 本项目，新增视频生成功能 |
| Pixelle-Video | 参考实现（Apache 2.0） | 复用 HTML 模板，参考架构设计 |
| article-tools | 独立工具 | 文章生成流程使用 |

### 1.3 设计约束

- **推理卸载**: LLM/配图通过局域网 GPU 机器（LM Studio + ComfyUI/RunningHub）
- **不破坏现有架构**: 改动集中在 `scripts/` + 新增 API 路由 + Vue 页面
- **Apache 2.0 合规**: Pixelle-Video 采用 Apache 2.0 许可，可自由复用其 HTML 模板
- **降级能力**: Edge-TTS 不可用时，降级调用本地 TTS 模型

---

## 2. 系统架构

### 2.1 整体拓扑

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ytdlp-batch-downloader                            │
│                                                                          │
│  ┌──────────────┐    ┌─────────────────────┐    ┌────────────────┐   │
│  │  Vue SPA     │───▶│  Custom HTTP Server  │───▶│  scripts/      │   │
│  │  Frontend    │    │  (SimpleHTTPHandler) │    │  video_gen_*  │   │
│  └──────────────┘    └──────────┬──────────┘    └───────┬────────┘   │
└──────────────────────────────────┼────────────────────────┼─────────────┘
                                   │                        │
                    ┌──────────────┴───────┐               │
                    │   GPU 机器 (局域网)    │               │
                    │                       │               │
                    │  ┌──────────────────┐ │               │
                    │  │  LLM API         │◀┘  脚本/摘要   │
                    │  │  (LM Studio)     │ │               │
                    │  └──────────────────┘ │               │
                    │  ┌──────────────────┐ │               │
                    │  │  ComfyUI API     │◀┘  配图生成   │
                    │  │  (RTX GPU)       │ │               │
                    │  └──────────────────┘ │               │
                    │  ┌──────────────────┐ │               │
                    │  │  Edge-TTS /      │ │  语音合成     │
                    │  │  本地 TTS 模型   │ │               │
                    │  └──────────────────┘ │               │
                    └───────────────────────────────────────┘
```

### 2.2 与文章生成流程的关系

```
                    ┌─────────────────────────────────────┐
                    │         ytdlp-batch-downloader        │
                    │                                       │
   视频下载 ──────▶ │ ──▶ 文章生成流程 ──▶ 公众号排版       │
   (现有)          │                                       │
                   │ ──▶ 视频生成流程（新增）──▶ 短视频    │
                   │     主题/文案 ──▶ 配图 ──▶ 语音 ──▶ 视频 │
                    └─────────────────────────────────────┘
```

两个流程**共享**：
- LLM 推理基础设施（`scripts/llm_client.py`）
- 配置管理（AI Settings）
- SSE 进度推送机制

---

## 3. 功能规格

### 3.1 核心功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 主题转视频 | 输入主题，AI 自动生成完整视频 | P0 |
| 文案转视频 | 输入已有文案，直接生成视频 | P0 |
| 配图生成 | 调用 ComfyUI/RunningHub 生成配图 | P0 |
| TTS 语音 | Edge-TTS 或本地 TTS 模型合成语音 | P0 |
| 视频模板 | 复用 Pixelle-Video HTML 模板 | P0 |
| 进度展示 | SSE 实时推送各阶段进度 | P0 |
| 历史记录 | 保存生成历史，支持重新生成 | P1 |

### 3.2 不包含的功能

| 功能 | 原因 |
|------|------|
| 数字人口播 | 复杂度高，作为后续迭代考虑 |
| 动作迁移 | 与场景不符 |
| 背景音乐 | 简化版本，暂不包含 |

---

## 4. 数据流

```
用户输入「主题」或「文案」
        │
        ▼
POST /api/video-generate { topic, mode, template, ... }
        │
        ├── Step 1: LLM 生成视频脚本
        │         └── 调用 GPU LLM API
        │             输入: 主题 + n_scenes
        │             输出: [{scene, narration, image_prompt}, ...]
        │
        ├── Step 2: AI 生成配图（并行，每张图独立调用）
        │         └── 调用 ComfyUI / RunningHub API
        │             输入: image_prompt
        │             输出: 图片文件路径列表
        │
        ├── Step 3: TTS 合成语音
        │         └── 调用 Edge-TTS 或本地 TTS
        │             输入: narration 列表
        │             输出: 音频文件路径列表
        │
        ├── Step 4: 视频合成
        │         └── FFmpeg 将图片序列 + 音频 + HTML模板 合成视频
        │             输入: 图片列表 + 音频列表 + 模板路径
        │             输出: final.mp4
        │
        └── 返回: video_url + 预览链接
```

---

## 5. API 设计

### 5.1 `POST /api/video-generate`

启动视频生成任务。

**请求**:
```json
{
  "topic": "为什么学习编程很重要",
  "mode": "generate",
  "n_scenes": 5,
  "template": "1080x1920/image_default.html",
  "prompt_prefix": "minimalist illustration",
  "tts_workflow": "edge-tts",
  "image_workflow": "selfhost/flux.json",
  "bgm_volume": 0.3
}
```

**响应** (202 Accepted):
```json
{
  "task_id": "video_gen_xxx_001"
}
```

### 5.2 `GET /api/video-generate/stream/{task_id}`

SSE 流式推送各阶段进度。

**SSE 事件**:
```
event: start
data: {"stage": "generating_script"}

event: progress
data: {"stage": "generating_images", "progress": 20, "current": 1, "total": 5}

event: progress
data: {"stage": "generating_images", "progress": 60, "current": 3, "total": 5}

event: progress
data: {"stage": "synthesizing_speech", "progress": 70}

event: progress
data: {"stage": "synthesizing_video", "progress": 90}

event: done
data: {
  "video_url": "/api/video-generate/files/20250425_video.mp4",
  "duration": 45.2,
  "file_size": 5242880
}

event: error
data: {"stage": "generating_images", "error": "ComfyUI timeout"}
```

### 5.3 `GET /api/video-generate/list` / `GET /api/video-generate/{task_id}`

查询任务列表和详情。

### 5.4 `DELETE /api/video-generate/{task_id}`

取消并删除任务。

### 5.5 `GET /api/video-generate/templates`

获取可用模板列表。

---

## 6. 新增文件清单

| 文件路径 | 职责 | 来源 |
|----------|------|------|
| `scripts/video_gen_script.py` | LLM 生成视频分镜脚本 | 新写 |
| `scripts/video_gen_image.py` | 调用 ComfyUI/RunningHub 生成配图 | 新写 |
| `scripts/video_gen_tts.py` | TTS 合成（Edge-TTS + 本地降级） | 新写 |
| `scripts/video_gen_assembler.py` | FFmpeg 视频合成 | 新写 |
| `scripts/video_gen_pipeline.py` | 主编排器，流程控制 + SSE | 新写 |
| `server/modules/video_gen_api.py` | API 路由模块 | 新写 |
| `templates/pixelle-templates/` | Pixelle-Video HTML 模板 | 复制自 Pixelle-Video |
| `frontend-vue/src/views/VideoGenerator.vue` | 视频生成 UI | 新写 |
| `frontend-vue/src/api/videoGen.ts` | 前端 API 调用 | 新写 |
| `frontend-vue/src/views/SettingsHub.vue` (改) | AI Settings 增加视频生成配置 | 改 |

---

## 7. 数据库扩展

在 `monitor.db` 新增表：

```sql
CREATE TABLE video_gen_tasks (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    mode TEXT DEFAULT 'generate',     -- generate / fixed
    status TEXT DEFAULT 'pending',     -- pending / running / done / error / cancelled
    template TEXT,
    n_scenes INTEGER DEFAULT 5,
    stages TEXT,                       -- JSON: 各阶段状态、耗时
    script_json TEXT,                  -- 生成的脚本分镜
    video_path TEXT,
    duration REAL,
    file_size INTEGER,
    error TEXT,
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT
);
```

---

## 8. 配置项

在 AI Settings 中新增「视频生成」配置区块：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `comfyui_url` | ComfyUI 地址 | `http://192.168.x.x:8188` |
| `comfyui_api_key` | ComfyUI API Key | `""` |
| `runninghub_api_key` | RunningHub API Key | `""` |
| `tts_provider` | TTS 提供者 | `edge-tts` |
| `local_tts_url` | 本地 TTS API 地址 | `http://192.168.x.x:5000` |
| `video_output_dir` | 视频输出目录 | `./output/video-gen` |
| `default_template` | 默认模板 | `1080x1920/image_default.html` |
| `default_n_scenes` | 默认分镜数 | `5` |

---

## 9. HTML 模板（来自 Pixelle-Video）

### 9.1 许可说明

Pixelle-Video 采用 **Apache 2.0** 许可证，允许：
- 商业使用
- 修改
- 分发
- 专利授权

**要求**：
- 保留 License 声明
- 如果修改了代码，必须明确说明

### 9.2 模板目录结构

```
templates/pixelle-templates/
├── 1080x1920/              # 竖屏模板
│   ├── image_default.html
│   ├── image_minimal.html
│   ├── video_default.html
│   └── static_default.html
├── 1920x1080/              # 横屏模板
│   ├── image_default.html
│   └── ...
└── LICENSE                 # Apache 2.0 声明
```

### 9.3 模板工作原理

HTML 模板定义视频画面布局：
- 占位符：`{{IMAGE_0}}`, `{{IMAGE_1}}`, ...（配图位置）
- 文字：`{{TEXT_0}}`, `{{TEXT_1}}`, ...（解说文字）
- 通过 FFmpeg 将静态 HTML 渲染为视频帧

---

## 10. 错误处理策略

| 错误场景 | 处理策略 |
|----------|----------|
| LLM API 超时 | 重试 2 次，间隔 10s，失败则返回错误 |
| ComfyUI 不可达 | 切换到 RunningHub（如果配置了） |
| Edge-TTS 不可用 | 降级调用本地 TTS API |
| 本地 TTS 也失败 | 返回错误：「语音合成失败」 |
| FFmpeg 合成失败 | 返回错误：「视频合成失败」 |
| 用户取消任务 | 清理临时文件，更新状态为 cancelled |

---

## 11. 实施计划

### Phase 1: 核心基础设施
1. 创建 `scripts/video_gen_pipeline.py`（主编排器）
2. 创建 `scripts/video_gen_script.py`（LLM 分镜生成）
3. 复制 Pixelle-Video HTML 模板到 `templates/pixelle-templates/`
4. 新增 `POST /api/video-generate` 路由

### Phase 2: 配图和 TTS
5. 创建 `scripts/video_gen_image.py`（ComfyUI 调用）
6. 创建 `scripts/video_gen_tts.py`（Edge-TTS + 本地降级）
7. 新增配图/TTS 阶段到 SSE 进度

### Phase 3: 视频合成
8. 创建 `scripts/video_gen_assembler.py`（FFmpeg 合成）
9. 完成视频合成阶段 SSE 进度
10. 新增 `GET /api/video-generate/files/{path}` 路由

### Phase 4: 前端集成
11. 创建 `frontend-vue/src/views/VideoGenerator.vue`
12. 创建 `frontend-vue/src/api/videoGen.ts`
13. 侧边栏新增「AI视频生成」菜单入口
14. AI Settings 增加视频生成配置项

### Phase 5: 历史与优化
15. 数据库表 `video_gen_tasks` 集成
16. 历史记录页面
17. 完整 E2E 测试

---

## 12. 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| ComfyUI 与 LM Studio 共用 GPU 机器 | 显存争抢 | 配置并发限制或分开部署 |
| Edge-TTS 需要联网 | 内网环境无法使用 | 实现本地 TTS 降级方案 |
| HTML 模板 FFmpeg 渲染性能 | 长视频渲染慢 | 异步处理 + 进度展示 |

---

## 13. 参考资料

- [Pixelle-Video](https://github.com/AIDC-AI/Pixelle-Video) — 核心参考，Apache 2.0 许可
- [Pixelle-Video API](https://github.com/AIDC-AI/Pixelle-Video/blob/main/api/app.py) — FastAPI 服务入口
- [Pixelle-Video Pipelines](https://github.com/AIDC-AI/Pixelle-Video/blob/main/pixelle_video/pipelines/) — 视频生成流程
- [Edge-TTS](https://github.com/rany2/edge-tts) — 微软 TTS Python SDK
- 现有 `scripts/llm_client.py` — LLM 调用封装参考

# AI 文章生成功能集成设计方案

**日期**: 2026-04-25
**目标**: 在 ytdlp-batch-downloader 中集成 AI-Video-Transcriber + article-tools，实现「视频 → AI字幕/转写 → AI摘要/翻译 → 文章草稿 → 公众号排版」完整工作流

---

## 1. 背景与目标

### 1.1 用户场景

用户下载 YouTube/Bilibili 等平台的视频后，希望将视频内容通过 AI 生成一篇结构化文章，并使用 article-tools 进行封面生成和微信公众号/X 平台的排版。

### 1.2 涉及项目

| 项目 | 角色 | 关系 |
|------|------|------|
| ytdlp-batch-downloader | 主项目（已有视频下载、WhisperX、LLM客户端） | 本项目 |
| AI-Video-Transcriber | 引用源码（subtitle-first + 摘要/翻译 prompt） | 移植核心模块 |
| article-tools | 引用工具（封面生成、公众号/X排版） | 通过 draft.md 松耦合 |

### 1.3 关键设计约束

- **推理卸载**: 所有重型推理（Whisper + LLM）通过局域网调用 GPU 机器上的 LM Studio API
- **不重复造轮子**: Whisper 字幕提取逻辑、LLM 摘要/翻译 prompt 移植自 AI-Video-Transcriber
- **不破坏现有架构**: 主项目后端是自定义 SimpleHTTPRequestHandler（非 FastAPI），改动集中在 scripts/ + 新增 API 路由模块
- **draft.md 作为中间格式**: article-tools 的三个 HTML 文件通过读取 draft.md 自动填充内容

---

## 2. 系统架构

### 2.1 整体拓扑

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ytdlp-batch-downloader                        │
│                                                                     │
│  ┌──────────────┐    ┌─────────────────────┐    ┌───────────────┐ │
│  │  Vue SPA     │───▶│  Custom HTTP Server  │───▶│  scripts/     │ │
│  │  Frontend    │    │  (SimpleHTTPHandler) │    │  article_*    │ │
│  └──────────────┘    └──────────┬──────────┘    └───────┬───────┘ │
└──────────────────────────────────┼────────────────────────┼─────────┘
                                   │                        │
                    ┌──────────────┴───────┐               │
                    │   GPU 机器 (LM Studio) │               │
                    │                       │               │
                    │  ┌──────────────────┐ │               │
                    │  │  Whisper API      │◀───────────────┘
                    │  │  (RTX GPU)        │ │  字幕转写
                    │  └──────────────────┘ │
                    │  ┌──────────────────┐ │
                    │  │  LLM API          │◀┘  AI摘要/翻译
                    │  │  (Qwen/LLaMA)     │ │
                    │  └──────────────────┘ │
                    │  局域网: http://<gpu-ip>:<port>
                    └───────────────────────────────────┘
                                                           │
                        ┌─────────────────────────────────┘
                        ▼
              ┌─────────────────────┐
              │   article-tools      │
              │  (独立静态文件)        │
              │  cover.html         │
              │  md-to-wechat.html   │
              │  md-to-x.html       │
              └─────────────────────┘
```

### 2.2 数据流

```
用户点击「AI生成文章」（视频详情页按钮）
        │
        ▼
POST /api/article/generate { video_id, target_lang, auto_translate }
        │
        ├── Step 1: yt-dlp 探测字幕（不下载视频）
        │         检查 manual_subtitles / automatic_captions
        │         语言优先级: en > zh-Hans > zh-Hant > zh > ja > ko > ...
        │         └── 有字幕 → 解析 VTT/SRT → 原始文本
        │
        ├── Step 2A: 有字幕 → 跳至 Step 3
        └── Step 2B: 无字幕 → 调用 GPU Whisper API
                    POST /v1/audio/transcriptions
                    (需先 yt-dlp 下载音频片段，格式: mono, 16kHz, .m4a)
                    └── 返回带时间戳的转写文本
        │
        ├── Step 3: LLM 优化转写文本（调用 GPU LLM API）
        │         系统 prompt: 纠错、分段、保留全部内容
        │         模型: gpt-3.5-turbo 等效（可配置）
        │         Chunk: ~8000 tokens/段
        │
        ├── Step 4: LLM 生成摘要（调用 GPU LLM API）
        │         输出结构: 关键点 + 章节划分 + 总结 + 结论
        │         模型: gpt-4o 等效（可配置）
        │
        ├── Step 5A: 原文语言 == 目标语言 → 跳至 Step 6
        └── Step 5B: 需要翻译 → 调用 GPU LLM API 翻译全文
                    Chunked by ~4000 chars
                    Model: gpt-4o 等效, temperature=0.1
        │
        ├── Step 6: 写入 draft.md 格式文件
        │         ├── 封面配置 JSON（article-tools 自动读取）
        │         └── 正文（标题 + 摘要 + 优化后的完整正文）
        │
        └── 返回: draft.md 路径 + 快捷入口链接
```

---

## 3. 新增文件清单

| 文件路径 | 职责 | 来源 |
|----------|------|------|
| `scripts/article_generator.py` | 主编排器：subtitle-first + API调用 + 流程控制 + SSE 进度推送 | 新写 |
| `scripts/transcriber_remote.py` | Whisper API 客户端（调用 LM Studio Whisper 端点） | 移植自 AI-Video-Transcriber |
| `scripts/summarizer_article.py` | LLM 摘要/优化/翻译（调用 LM Studio LLM 端点） | 移植自 AI-Video-Transcriber |
| `scripts/video_processor_article.py` | yt-dlp 字幕提取（probe + subtitle download） | 移植自 AI-Video-Transcriber |
| `server/modules/article_api.py` | API 路由模块（注册到 MonitorHandler） | 新写 |
| `frontend-vue/src/views/ArticleGenerator.vue` | 文章生成 UI（进度展示 + 结果） | 新写 |
| `frontend-vue/src/components/VideoDetailModal.vue` (改) | 视频详情 modal 增加「AI生成文章」按钮 | 改 |

---

## 4. API 设计

### 4.1 `POST /api/article/generate`

启动文章生成任务。

**请求**:
```json
{
  "video_id": "abc123",
  "target_lang": "zh-Hans",
  "auto_translate": true
}
```

**响应** (202 Accepted):
```json
{
  "task_id": "article_abc123_001"
}
```

### 4.2 `GET /api/article/stream/{task_id}`

SSE 流式推送各阶段进度（与现有 `/api/res-events` 模式一致）。

**SSE 事件**:
```
event: start
data: {"stage": "fetching_subtitles"}

event: progress
data: {"stage": "transcribing", "progress": 0}

event: progress
data: {"stage": "transcribing", "progress": 45}

event: progress
data: {"stage": "optimizing", "progress": 70}

event: progress
data: {"stage": "summarizing", "progress": 85}

event: progress
data: {"stage": "translating", "progress": 90}

event: done
data: {
  "draft_path": "D:/Downloads/article_abc123.md",
  "article_url": "/article/abc123",
  "quick_links": {
    "cover": "cover.html?open=draft.md",
    "wechat": "md-to-wechat.html?open=draft.md",
    "x": "md-to-x.html?open=draft.md"
  }
}

event: error
data: {"stage": "transcribing", "error": "GPU service timeout"}
```

### 4.3 `GET /api/article/list` / `GET /api/article/{task_id}`

文章任务列表和详情（复用 clip_tasks 的分页查询模式）。

### 4.4 `DELETE /api/article/{task_id}`

取消并删除文章任务。

---

## 5. 数据库扩展

在现有 `monitor.db` 新增表：

```sql
CREATE TABLE article_tasks (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    video_url TEXT,
    video_title TEXT,
    status TEXT,               -- pending / processing / done / error / cancelled
    target_lang TEXT DEFAULT 'zh-Hans',
    auto_translate INTEGER DEFAULT 1,
    stages TEXT,               -- JSON: 各阶段状态、耗时、进度
    draft_path TEXT,
    summary TEXT,              -- AI 生成的摘要正文
    full_text TEXT,            -- 优化后的完整转写文本
    translated_text TEXT,       -- 翻译后的文本
    error TEXT,
    created_at TEXT,
    updated_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id)
);
```

复用 `monitor/db/` 现有的查询模式（`article_tasks.py`）。

---

## 6. LM Studio 推理配置

在现有 AI Settings 面板中新增「推理服务器」配置区块：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `inference_endpoint` | LM Studio API 地址（局域网） | `http://192.168.x.x:1234` |
| `inference_api_key` | API Key（LM Studio 通常为空） | `""` |
| `ssl_verify` | 是否验证 SSL | `true` |
| `whisper_model` | Whisper 模型名 | `base` |
| `llm_optimize_model` | 文本优化用模型 | `qwen2.5-7b-instruct` |
| `llm_summary_model` | 摘要生成用模型 | `qwen2.5-14b-instruct` |
| `llm_translate_model` | 翻译用模型 | `qwen2.5-14b-instruct` |

调用链路：`AiSettings.vue` → `POST /api/config` → `config/settings.py` → `article_generator.py` 读取 → `transcriber_remote.py` / `summarizer_article.py` 使用。

---

## 7. article-tools 对接

### 7.1 改动需求

给 article-tools 的三个 HTML 文件增加 `?open=<path>` 参数支持：

```javascript
// 在各 HTML 文件的 window.onload 中:
const params = new URLSearchParams(window.location.search);
const draftPath = params.get('open');
if (draftPath) {
  fetch(draftPath)
    .then(r => r.text())
    .then(text => parseAndFill(text));
}
```

### 7.2 文件放置

article-tools 的静态文件建议放在项目根目录下（或用户指定路径），通过配置项 `article_tools_path` 指定。前端返回的快捷链接基于此路径生成。

### 7.3 draft.md 格式

```markdown
类型：文章
选题：<视频标题>
生成时间：YYYY-MM-DD

```json
"changes": {
  "background": { "type": "scheme", "index": 6, "name": "智核" },
  "content": {
    "label": "<账号名>",
    "title": "<AI生成的文章标题>",
    "subtitle": "<AI生成的副标题>",
    "author": "<配置的作者名>"
  },
  "typography": { ... }
}
```

正文：<AI 生成的完整文章内容>

---

## 8. 错误处理策略

| 错误场景 | 处理策略 |
|----------|----------|
| GPU 机器不可达（连接超时） | 立即返回 `error` 事件，用户可重试 |
| Whisper API 超时 | 重试 2 次，间隔 5s，失败则提示「GPU Whisper 服务无响应」 |
| LLM API 超时 | 重试 2 次，间隔 10s |
| 视频无字幕且 Whisper 失败 | 返回错误：「无法获取字幕且 GPU 转写失败」 |
| 翻译 API 超时 | 跳过翻译步骤，保留原文，提示用户可手动重试 |
| draft.md 写入失败 | 返回错误，任务状态保持 `pending` |

---

## 9. 实施计划（Phase）

### Phase 1: 核心功能
1. 实现 `video_processor_article.py`（字幕提取）
2. 实现 `transcriber_remote.py`（Whisper API 调用）
3. 实现 `summarizer_article.py`（LLM 摘要/翻译）
4. 实现 `article_generator.py`（主编排器 + SSE）
5. 新增 `POST /api/article/generate` 和 `GET /api/article/stream/{id}` 路由
6. 新增 `article_tasks` 数据库表和查询模块

### Phase 2: 前端集成
7. 新增 `ArticleGenerator.vue` 页面
8. 视频详情 modal 增加「AI生成文章」按钮
9. AI Settings 面板增加推理服务器配置

### Phase 3: article-tools 对接
10. 修改 article-tools HTML 文件支持 `?open=` 参数
11. 配置面板增加 `article_tools_path` 配置项
12. 文章生成完成后返回快捷入口链接

### Phase 4: 测试与优化
13. 字幕提取测试（有字幕视频）
14. Whisper API 测试（无字幕视频）
15. 完整 E2E 测试
16. 性能优化（并发 chunk 处理）

---

## 10. 技术债务与风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LM Studio API 格式与 OpenAI 不完全兼容 | Whisper 端点可能需要调整 | 先用 curl 验证端点可用性 |
| 局域网抖动导致任务中断 | 用户体验差 | 增加任务持久化（SQLite），支持断点续传 |
| article-tools 独立维护可能与 draft.md 格式不兼容 | 需同步更新 | 将 draft.md 格式文档化，article-tools 改动最小化 |
| 长视频转写超时 | LLM chunk 处理复杂 | 分段处理，每段独立重试 |

---

## 11. 参考资料

- [AI-Video-Transcriber](https://github.com/wendy7756/AI-Video-Transcriber) — 源码参考
- [article-tools](https://github.com/eternityspring/article-tools) — 排版工具参考
- 现有 `scripts/whisperx_worker.py` — 本地 Whisper 实现参考
- 现有 `scripts/llm_client.py` — LLM 调用封装参考

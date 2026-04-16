# 研究发现：autoclip 集成可行性分析

## 一、autoclip 项目概览

**GitHub**: `zhouxiaoka/autoclip`
**定位**: 基于 AI 的智能视频切片处理系统
**Stars/Forks**: 0（开源早期项目）
**License**: MIT

### 核心功能流程
```
视频下载 → AI分析 → 时间线提取 → 精彩评分 → 标题生成 → 智能合集 → 视频生成
  Step1      Step2      Step3         Step4        Step5        Step6
```

---

## 二、技术栈对比

### autoclip 技术栈
| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | 异步 Web 框架 |
| 任务队列 | Celery + Redis | 异步任务处理（分布式） |
| 数据库 | SQLite / PostgreSQL | ORM: SQLAlchemy + Alembic |
| 视频下载 | yt-dlp | 与当前项目相同 ✅ |
| AI 分析 | 通义千问（Qwen） | LLM API |
| 字幕处理 | Whisper/bcut-asr | ASR 语音转写 |
| 前端 | React 18 + TypeScript | Ant Design UI |
| 实时通信 | WebSocket | 进度推送 |
| 构建 | Vite | 前端开发服务器 |

### 当前项目技术栈
| 层级 | 技术 | 说明 |
|------|------|------|
| 后端 | Python 标准库 | ThreadingHTTPServer, APScheduler |
| 数据库 | SQLite | monitor/db.py |
| 视频下载 | yt-dlp | ✅ 与 autoclip 相同 |
| 前端 | Tkinter | 批量下载 GUI |
| Web UI | Vanilla JS + HTML | monitor_web/ |
| 通知 | Webhook | 飞书/钉钉/Telegram |

### 关键差异
- autoclip 有完整 **FastAPI + Celery + Redis** 微服务架构
- 当前项目用 **标准库 HTTP Server + APScheduler** 轻量方案
- autoclip 前端是 **React SPA**，当前项目是 **Vanilla JS + HTML**
- autoclip 有 **AI Pipeline**，当前项目无 AI 处理

---

## 三、AI Pipeline 深度分析（最关键部分）

### 6 步 Pipeline 架构

```
step1_outline.py  → 大纲提取（30分钟/块分块 → LLM提取话题大纲）
         ↓
step2_timeline.py → 时间线提取（识别每个话题的 start/end 时间区间）
         ↓
step3_scoring.py  → 精彩评分（LLM批量评估每个片段，final_score 0-10）
         ↓
step4_title.py    → 标题生成（为每个高分片段生成吸引人的标题）
         ↓
step5_clustering.py → 智能合集（AI推荐视频合集，主题聚类）
         ↓
step6_video.py    → 视频生成（ffmpeg 切割 + 拼接生成合集）
```

### 依赖的数据文件
- SRT 字幕文件（由 WhisperX 生成）
- 通义千问 API（qwen-turbo / qwen-plus）

### LLM Prompt 工程
- `prompt/大纲.txt` — 大纲提取 prompt
- `prompt/时间点.txt` — 时间线提取 prompt
- `prompt/标题生成.txt` — 标题生成 prompt
- `prompt/推荐理由.txt` — 精彩评分 prompt
- `prompt/主题聚类.txt` — 合集聚类 prompt
- 分类场景：knowledge, entertainment, speech, opinion, experience, content_review 等

### 评分机制
```python
MIN_SCORE_THRESHOLD = 某个阈值  # 低于此分数的片段被过滤
final_score: float  # LLM 评估的精彩度分数 0-10
recommend_reason: str  # 推荐理由
```

---

## 四、可复用模块分析

### ✅ 可直接复用的（无改造成本）
| 模块 | 说明 | 复用方式 |
|------|------|---------|
| yt-dlp 下载 | autoclip 和当前项目都用 yt-dlp | 直接复用 |
| WhisperX 字幕生成 | 当前项目已有 whisperx_worker.py | 直接复用 |
| SRT 解析 | `TextProcessor.parse_srt()` | 需提取或重写 |
| ffmpeg 视频切割 | `VideoProcessor.batch_extract_clips()` | 需提取或重写 |
| ffmpeg 合集拼接 | `VideoProcessor.create_collections_from_metadata()` | 需提取或重写 |

### ⚠️ 需改造才能复用的
| 模块 | 改造成本 | 说明 |
|------|---------|------|
| FastAPI 后端 | **高** | 当前项目用标准库 HTTP Server，重写不划算 |
| Celery + Redis | **高** | 需要额外基础设施，单机项目不需要 |
| React 前端 | **极高** | Tkinter ↔ React 完全不同架构 |
| LLM 客户端 | **低** | 通义千问 → 可改为 OpenAI / 本地 LLM |

### ❌ 不适合复用的
| 模块 | 原因 |
|------|------|
| Celery 分布式任务 | 单机轻量项目不需要 |
| WebSocket 实时推送 | 当前项目用轮询/通知 |
| PostgreSQL | 当前 SQLite 已够用 |
| Ant Design UI | 当前 Vanilla JS 已够用 |

---

## 五、集成价值评估

### 最值得借鉴的部分（不需要集成，直接学习）

1. **AI Pipeline 设计模式**（最重要）
   - 6 步流水线：outline → timeline → scoring → title → clustering → video
   - 每个步骤独立、幂等、可重跑
   - 中间结果保存到 JSON 文件
   - `min_score_threshold` 过滤低质量片段

2. **Prompt Engineering**
   - 分场景 prompt（knowledge/speech/entertainment）
   - 30 分钟/块的分块策略
   - LLM 批量处理减少 API 调用次数

3. **Celery 异步任务模式**
   - `processing_orchestrator.py` 统一调度
   - `progress_event_service.py` 进度上报
   - 但这需要 Redis，对于当前项目过于重型

### 如果要集成视频切片功能

**方案 A：轻量集成（推荐）**
```
在当前项目中新增:
  scripts/video_clipper.py     # 独立脚本，封装6步Pipeline
  scripts/prompts/             # Prompt 模板文件
复用:
  yt-dlp (已有)
  WhisperX (已有 whisperx_worker.py)
新增:
  LLM 客户端（OpenAI API / 本地 LLM）
```
- 不改变现有架构
- 新功能作为独立增强
- 需用户配置 LLM API Key

**方案 B：服务化集成**
```
将 autoclip 作为独立服务部署，通过 REST API 调用
当前项目 → HTTP → autoclip 服务 → 视频切片
```
- 保持架构解耦
- 需要额外部署资源
- 适合多用户场景

**方案 C：完整替换**
```
将 autoclip 的 FastAPI + Celery + React 完整集成
```
- 改造成本极高
- 失去 tkinter GUI 的优势
- **不推荐**

---

## 五（五）、与当前项目功能对比

### 现有功能矩阵

| 功能 | autoclip | 当前项目 | 差距 |
|------|---------|---------|------|
| 视频下载 | ✅ yt-dlp | ✅ yt-dlp | 持平 |
| 字幕下载 | ✅ yt-dlp | ✅ yt-dlp | 持平 |
| ASR字幕生成 | ✅ Whisper/bcut-asr | ✅ WhisperX | 持平 |
| AI内容分析 | ✅ 6步LLM Pipeline | ❌ 无 | **关键差距** |
| 自动切片 | ✅ ffmpeg切割 | ❌ 无 | **关键差距** |
| 标题生成 | ✅ LLM生成 | ❌ 无 | **关键差距** |
| 智能合集 | ✅ 主题聚类 | ❌ 无 | **关键差距** |
| B站上传 | ✅ 开发中 | ❌ 无 | — |
| 频道监控 | ❌ 无 | ✅ 多账户+配额 | 当前项目优势 |
| Web通知 | ✅ WebSocket | ✅ 飞书/钉钉/TG | 持平 |
| 多格式输出 | ⚠️ 仅视频 | ✅ 音频/字幕可选 | 当前项目优势 |

### 关键发现
- 当前项目**下载 + 监控 + 通知**链路完整，比 autoclip 更成熟
- autoclip 的 **AI 切片**是当前项目最大的功能空白
- 两者底层依赖（yt-dlp / WhisperX / ffmpeg）高度重叠
- 集成不需要引入 FastAPI/Celery，仅需新增 AI Pipeline 脚本

### 集成可行性：⭐⭐（部分可行）

| 维度 | 评分 | 说明 |
|------|------|------|
| 技术匹配 | 3/5 | yt-dlp 和 WhisperX 可复用，但架构差异大 |
| 改造成本 | 2/5 | 完整集成需要大量重构 |
| 价值收益 | 5/5 | AI 切片功能与项目高度契合 |
| 推荐程度 | 4/5 | 轻量集成最可行 |

### 建议：采用方案 A（轻量集成）

**核心思路**：
1. 不改变现有 Tkinter GUI 和标准库 HTTP Server 架构
2. 新增 `scripts/video_clipper.py` — 封装 autoclip 的 6 步 AI Pipeline
3. 复用已有的 `whisperx_worker.py`
4. 新增 LLM 客户端（支持 OpenAI API，用户可自选模型）
5. 在 GUI 中添加「AI 切片」按钮
6. WhisperX 生成字幕 → AI Pipeline 分析 → ffmpeg 切割

**实施优先级**：
1. 先在 README 中添加「AI 视频切片」规划方向
2. 创建 `scripts/video_clipper.py` 独立脚本
3. GUI 中添加调用入口
4. 可选：支持 OpenAI / 通义千问 / 本地 LLM 多后端

---

## 七、详细实施计划（Phase 2 产出）

### 实施范围与目标
**目标**：在不影响现有下载/监控/通知链路的前提下，新增「AI 视频切片」功能。

### 新增文件清单

```
scripts/
  ├── video_clipper.py          # AI 切片核心脚本（CLI + API）
  ├── clip_pipeline.py          # 6 步 Pipeline 编排器
  ├── llm_client.py            # LLM 客户端（OpenAI / Qwen / 本地）
  ├── text_processor.py        # SRT 解析 + 分块
  ├── video_processor.py       # ffmpeg 切割 + 合集拼接
  └── prompts/                  # Prompt 模板目录
      ├── outline.txt           # 大纲提取 prompt
      ├── timeline.txt          # 时间线提取 prompt
      ├── scoring.txt           # 精彩评分 prompt
      ├── title.txt             # 标题生成 prompt
      └── clustering.txt        # 主题聚类 prompt
```

### 复用现有文件

| 现有文件 | 复用方式 |
|---------|---------|
| `scripts/whisperx_worker.py` | 直接复用，获取字幕文件 |
| `Youtube_Downloader.py` | 复用视频下载逻辑 |
| `ytb_api.py` | 复用 YouTube API 调用 |
| `monitor/quota.py` | 复用通知链路 |
| `config/settings.py` | 新增 LLM API Key 配置 |

### 6 步 Pipeline 实现

```
Step1 (outline)    ← 加载 .srt → 分 30 分钟块 → LLM 提取大纲
         ↓ JSON
Step2 (timeline)   ← 每个大纲话题 → LLM 提取 start/end 时间
         ↓ JSON
Step3 (scoring)   ← 每个时间段 → LLM 评分 (0-10) → 过滤低分
         ↓ JSON
Step4 (title)     ← 高分片段 → LLM 生成吸引人标题
         ↓ JSON
Step5 (clustering) ← 所有切片 → LLM 主题聚类 → 推荐合集
         ↓ JSON
Step6 (video)     ← ffmpeg 切割 + 合集拼接 → 输出 clips/
```

### 实施阶段

#### Stage 1：核心脚本（独立可用）
- `scripts/llm_client.py` — 支持 OpenAI GPT-4o / Qwen / 本地 LLM
- `scripts/text_processor.py` — SRT 解析 + 分块
- `scripts/video_processor.py` — ffmpeg 切割封装
- `scripts/clip_pipeline.py` — 6 步编排器
- `scripts/prompts/` — 5 个 Prompt 模板
- `scripts/video_clipper.py` — CLI 入口

#### Stage 2：GUI 集成
- 在 `ytdownload_ui.py` 主窗口添加「AI 切片」按钮
- 在 `monitor_web/` Web UI 添加切片管理页面
- 新增配置文件项：`llm_api_key`, `llm_model`, `llm_provider`

#### Stage 3：高级功能
- 切片后自动上传 B站（参考 autoclip 的 `bilibili_service.py`）
- 监控发现新视频后自动切片
- 切片结果通知（通过现有飞书/钉钉/Telegram）

### LLM 模型支持

| Provider | 模型 | 费用 | 适合场景 |
|---------|------|------|---------|
| OpenAI | GPT-4o / GPT-4o-mini | API计费 | 国际用户 |
| 通义千问 | qwen-plus / qwen-max | API计费 | 国内用户（推荐） |
| 本地 LLM | Ollama (llama3/qwen2) | 免费 | 离线/隐私 |
| Groq | llama-3.1 / mixtral | 低费用 | 低延迟 |

### 配置变更

```python
# config/settings.py 新增
LLM_PROVIDER: str = "openai"       # openai / qwen / ollama
LLM_API_KEY: str = ""               # API Key
LLM_MODEL: str = "gpt-4o"           # 模型名
LLM_BASE_URL: str = ""               # 自定义端点（可选）
MIN_SCORE_THRESHOLD: float = 7.0    # 最低评分阈值
CLIP_CATEGORY: str = "knowledge"    # 默认分类场景
```

---

## 八、依赖变更预估

如采用方案 A，需新增依赖：
```
openai  # 或 qwen-agent / 本地 LLM SDK
pysrt   # SRT 解析
```

无需引入：FastAPI, Celery, Redis, React, Ant Design

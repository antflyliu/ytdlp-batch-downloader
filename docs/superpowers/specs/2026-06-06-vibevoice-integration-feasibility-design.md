# VibeVoice 集成可行性与设计草案

**日期**: 2026-06-06
**状态**: Draft for discussion
**范围**: 只做可行性分析、集成 spec、UI 设计与实施计划；不包含本轮代码修改。

---

## 1. 结论摘要

可以集成 Microsoft VibeVoice，但应按能力拆分、默认走服务化/API 接入，而不是把 VibeVoice 模型直接嵌入当前主进程。

推荐的 MVP 是：

1. **VibeVoice-ASR 作为可选转写后端**：接入现有“字幕优先 -> ASR fallback -> LLM 文章/切片”的链路。优先支持远程 VibeVoice ASR API / vLLM OpenAI-compatible API，本地只做环境探测与说明。
2. **VibeVoice-Realtime-0.5B 作为可选 TTS provider**：先支持外部服务 URL/API 调用；后续再考虑本地 wrapper 服务。它适合短到中等长度的语音生成和 AI 视频生成配音，不适合作为默认大规模生产能力。
3. **VibeVoice-TTS-1.5B 不作为默认能力**：上游文档仍说明其长篇多说话人能力，但官方仓库已下架 TTS 代码和用法，原因是滥用风险。项目内只能把它列为“外部自备兼容服务/研究能力”，不能默认引导用户复原或使用社区 fork。

本机环境结论：

- Python 3.12.1 可用。
- `torch`、`transformers`、`accelerate`、`fastapi`、`uvicorn`、`faster_whisper`、`whisperx` 等已安装。
- `torch` 是 `2.8.0+cpu`，`torch.cuda.is_available()` 为 `false`。
- 机器有 NVIDIA GeForce MX150 2GB，但当前 PyTorch 不使用 CUDA；这块显卡也不足以可靠运行 VibeVoice-ASR-7B 或 VibeVoice-TTS-1.5B。
- Docker CLI 存在，但 Docker daemon 未运行；`vllm` 未安装。
- `ffmpeg`、`ffprobe`、`aria2c` 可用。
- 当前磁盘可用空间约 C: 26.6GB、D: 22.5GB、G: 18.1GB。对 7B/长音频模型缓存偏紧。

因此，本仓库应实现“控制台 + 客户端 + 任务编排 + UI”，把重型推理放到远程 GPU、局域网 GPU 服务、vLLM Docker 服务或用户自备 API。

---

## 2. 上游能力清单

来源均来自 Microsoft 官方 VibeVoice 仓库与文档：

- Repository: https://github.com/microsoft/VibeVoice
- ASR docs: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-asr.md
- vLLM ASR docs: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-vllm-asr.md
- Realtime TTS docs: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-realtime-0.5b.md
- TTS docs: https://github.com/microsoft/VibeVoice/blob/main/docs/vibevoice-tts.md

### 2.1 VibeVoice-ASR-7B

可用价值：

- 最多约 60 分钟长音频单次处理。
- 结构化转写：包含说话人、时间戳、文本内容。
- 支持自定义 hotwords，用于人名、术语、品牌名。
- 支持 50+ 语言和 code-switching。
- 支持 Hugging Face Transformers 接入。
- 支持 vLLM 部署，文档描述了 OpenAI-compatible `/v1/chat/completions` API 与 streaming。
- 支持 LoRA fine-tuning，但这不应进入 MVP。

适合本项目的用途：

- 替换或补充 Whisper/faster-whisper 作为文章生成和视频切片的转写来源。
- 长视频内容提取、播客/访谈类视频的说话人分离、时间轴生成。
- 对现有 `article_tasks` 和 `clip_tasks` 生成更结构化的 transcript metadata。

限制：

- 7B 模型对 GPU/显存要求高，本机不可直接跑。
- vLLM 推荐 Docker + NVIDIA GPU，当前本机 Docker daemon 未运行且 GPU 不合适。
- 输出格式需要 adapter 解析，不能假设和 Whisper API 一样只有 `text` 字段。

### 2.2 VibeVoice-Realtime-0.5B

可用价值：

- 0.5B 参数量，面向部署友好。
- 低延迟实时 TTS，上游文档称首个可听音频约 200ms，实际依赖硬件和网络。
- 支持 streaming text input 和较长文本生成。
- 8k context，约 10 分钟音频生成。
- 单说话人，主要面向英语；部分多语言声音属于实验性质。
- 官方 demo 是 websocket/Colab/脚本形态。

适合本项目的用途：

- AI 视频生成中的本地/远程 TTS provider。
- 文章摘要、脚本、短视频配音预览。
- 将下载/转写后的内容生成语音草稿。

限制：

- 当前官方 Realtime TTS 不是多说话人对话模型。
- 英语以外输出需谨慎，可能不稳定。
- 本机 CPU-only torch 和 2GB GPU 不适合追求实时体验。
- 官方文档仍提示深度伪造、误导性音频等风险，需要 UI 免责声明和默认安全限制。

### 2.3 VibeVoice-TTS-1.5B / Large

可用价值（文档层面）：

- 长篇 multi-speaker TTS，最多约 90 分钟。
- 最多 4 个说话人。
- 英文、中文等多语言能力。
- 可生成播客/对话类音频。

关键限制：

- 官方 README 明确说明 VibeVoice-TTS 代码已从仓库移除，原因是发现了不符合研究意图的使用方式。
- 官方 TTS 文档的“Installation and Usage”处于 disabled 状态。
- 不应在本项目中默认引导用户安装社区 fork、恢复旧代码或做声音克隆。

适合本项目的处理方式：

- 在功能清单中展示为“外部自备兼容服务”。
- 如果用户提供自己的 TTS API，可通过通用 TTS API adapter 调用。
- UI 默认隐藏长篇多说话人 TTS 的本地启动项，只显示风险提示和外部服务配置。

---

## 3. 当前项目集成点

### 3.1 后端

当前服务是 `server/__main__.py` 中的自定义 HTTP handler，不是 FastAPI。新增能力应遵循现有模式：

- 配置读取/保存：`config/settings.py` + `monitor.db.load_config/save_config` + `POST /api/config`
- 路由接入：`server/__main__.py` 的 `do_GET/do_POST` 分发
- 长任务：参考 `_DownloadTaskManager`、article/clip task 的后台线程与 SQLite 状态
- 数据库：`monitor/schema.sql`、`monitor/db.py` 迁移与查询函数
- 安全：沿用 API token、CORS、本地文件路径校验、敏感字段加密

### 3.2 现有 AI/ASR 能力

已经存在：

- `scripts/article_generator.py` 的 subtitle-first 流程。
- 本地 faster-whisper 环境探测、CUDA/CPU fallback、低显存分片逻辑。
- 远程 Whisper-compatible `/v1/audio/transcriptions` 调用。
- AI settings 页面里已有 LLM 和切片配置。
- `scripts/clip_pipeline.py` 依赖字幕和时间线继续执行切片。

因此 VibeVoice-ASR 不应重写整条链路，而应新增为一个 `transcription provider`。

### 3.3 前端

当前前端是 `monitor_web/`：

- Hash route: `monitor_web/static/js/router.js`
- Partial loading: `monitor_web/js/load-partials.js`
- Settings pages: `monitor_web/templates/pages/settings-*.html`
- Config JS: `monitor_web/js/modules/config.js`
- i18n: `monitor_web/static/i18n/zh.json` 和 `en.json`
- Design tokens: `monitor_web/static/css/variables.css`

UI 要保持 `DESIGN.md` 的暖色纸面风格：Parchment 背景、Ivory 卡片、Terracotta CTA、Warm Sand 次级按钮、Serif/Sans 层级、ring shadow、8-12px radius。

---

## 4. 推荐架构

### 4.1 边界原则

VibeVoice 集成应使用“主项目编排 + 外部推理服务”边界。

主项目负责：

- 环境检测
- 配置管理
- 任务创建、状态、日志
- 文件路径安全校验
- 调用远程/本地服务 API
- 把结果交给文章生成、切片、视频生成管线
- UI 交互和任务历史

外部服务负责：

- VibeVoice 模型加载
- GPU 推理
- vLLM ASR server
- Realtime TTS websocket/server
- 模型缓存和依赖隔离

不推荐：

- 在 `server/__main__.py` 进程里直接 import VibeVoice 并加载大模型。
- 把 VibeVoice heavy dependencies 加入主 `requirements.txt`。
- 自动安装 CUDA/vLLM/Docker 镜像。
- 默认启用长篇多说话人 TTS。

### 4.2 模块草案

新增 Python 包：

```text
monitor/vibevoice/
├── __init__.py
├── env.py              # 本地环境探测
├── clients.py          # API/vLLM/Realtime TTS client
├── adapters.py         # ASR/TTS provider adapter
├── tasks.py            # VoiceTaskManager
├── schemas.py          # payload normalize helpers
└── safety.py           # 风险提示、输入限制、metadata
```

新增脚本：

```text
scripts/vibevoice_env.py       # CLI: print JSON env report
scripts/vibevoice_client.py    # CLI: smoke test endpoint / transcribe / tts
```

不把 VibeVoice 源码 vendor 到仓库。

### 4.3 配置项

建议新增独立配置，避免继续扩大 `whisper_*` 的语义混乱：

| Key | 默认值 | 说明 |
| --- | --- | --- |
| `vibevoice_enabled` | `false` | 总开关 |
| `vibevoice_asr_enabled` | `false` | 启用 ASR provider |
| `vibevoice_asr_backend` | `api` | `api` / `vllm_openai` / `local_cli` |
| `vibevoice_asr_base_url` | `""` | 远程 ASR/vLLM 服务地址 |
| `vibevoice_asr_api_key` | `""` | 可选 bearer token，需加密落盘 |
| `vibevoice_asr_model` | `microsoft/VibeVoice-ASR` | 模型名或服务端 served model |
| `vibevoice_asr_hotwords` | `""` | 逗号分隔 hotwords |
| `vibevoice_asr_timeout_seconds` | `1800` | 长音频超时 |
| `vibevoice_tts_enabled` | `false` | 启用 TTS provider |
| `vibevoice_tts_backend` | `api` | `api` / `realtime_ws` / `local_cli` |
| `vibevoice_tts_base_url` | `""` | TTS 服务地址 |
| `vibevoice_tts_api_key` | `""` | 可选 bearer token，需加密落盘 |
| `vibevoice_tts_model` | `microsoft/VibeVoice-Realtime-0.5B` | 模型名 |
| `vibevoice_tts_voice` | `Carter` | 默认声音名 |
| `vibevoice_tts_language` | `en` | 默认语言 |
| `vibevoice_output_dir` | `data/vibevoice` | 任务输出目录 |
| `vibevoice_require_disclosure` | `true` | 生成音频时记录 AI disclosure |
| `vibevoice_allow_longform_tts` | `false` | 默认关闭长篇 TTS |

敏感项需要加入 `config/settings.py` 的 `_SECRET_CONFIG_KEYS`。

### 4.4 API 草案

```http
GET  /api/vibevoice/env
POST /api/vibevoice/env/check
POST /api/vibevoice/asr/tasks
GET  /api/vibevoice/tasks
GET  /api/vibevoice/tasks/{task_id}
POST /api/vibevoice/tasks/{task_id}/cancel
POST /api/vibevoice/tts/tasks
GET  /api/vibevoice/audio/{task_id}
```

ASR task request:

```json
{
  "source": "monitor_video",
  "monitor_video_id": 123,
  "hotwords": ["Microsoft", "VibeVoice"],
  "backend": "vllm_openai"
}
```

TTS task request:

```json
{
  "text": "Hello, this is a short narration draft.",
  "voice": "Carter",
  "language": "en",
  "backend": "realtime_ws"
}
```

Task response:

```json
{
  "task_id": "voice_20260606_001",
  "status": "pending"
}
```

### 4.5 数据库草案

新增 `voice_tasks` 表，避免把独立语音实验塞进 `article_tasks` 或 `clip_tasks`：

```sql
CREATE TABLE IF NOT EXISTS voice_tasks (
    task_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,              -- asr / tts / env_check
    status TEXT NOT NULL,            -- pending / running / done / error / cancelled
    backend TEXT NOT NULL,
    input_source TEXT,
    input_path TEXT,
    monitor_video_id INTEGER,
    output_text_path TEXT,
    output_audio_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
```

Article/clip integration can store `voice_task_id` in `article_tasks.stage_json` first. Only after usage stabilizes should a dedicated FK column be added.

---

## 5. Local Environment Detection

### 5.1 Detection output

`GET /api/vibevoice/env` should return structured JSON:

```json
{
  "python": {"ok": true, "version": "3.12.1"},
  "system": {"platform": "Windows-11"},
  "ffmpeg": {"ok": true, "path": "..."},
  "docker": {"cli": true, "daemon": false},
  "gpu": {
    "nvidia_smi": true,
    "name": "NVIDIA GeForce MX150",
    "memory_total_mb": 2048,
    "memory_free_mb": 1486
  },
  "torch": {
    "installed": true,
    "version": "2.8.0+cpu",
    "cuda_available": false
  },
  "python_packages": {
    "transformers": true,
    "vllm": false,
    "faster_whisper": true
  },
  "disk": {
    "model_cache_recommended": false,
    "free_gb": 22.5
  },
  "recommendation": {
    "local_asr": "not_recommended",
    "remote_asr_api": "recommended",
    "local_realtime_tts": "not_recommended",
    "remote_tts_api": "recommended"
  }
}
```

### 5.2 Detection rules

Recommended labels:

| Capability | Green | Yellow | Red |
| --- | --- | --- | --- |
| VibeVoice-ASR local | CUDA GPU with enough VRAM, VibeVoice installed, model cached | Docker/vLLM ready but model not cached | CPU-only, low VRAM, missing Docker/vLLM |
| VibeVoice-ASR API | Base URL reachable, auth ok, test request ok | URL reachable but model/version unknown | URL missing/unreachable |
| Realtime TTS local | Dedicated GPU/Mac-class tested runtime | CPU/GPU may run but not real-time | CPU-only/low VRAM |
| Realtime TTS API | Service health ok | URL reachable but generation untested | URL missing/unreachable |
| Longform TTS | External compatible service explicitly configured | Docs-only capability | Default local disabled |

The checker must not install packages, pull models, start Docker containers, or download weights.

---

## 6. ASR Integration Design

### 6.1 Provider strategy

Add a generic `TranscriptionProvider` abstraction:

```text
TranscriptionProvider.transcribe(media_path, hotwords, language_hint, progress) -> TranscriptResult
```

Providers:

- `WhisperLocalProvider` wraps current faster-whisper logic.
- `WhisperApiProvider` wraps current `/v1/audio/transcriptions` logic.
- `VibeVoiceApiProvider` handles user-provided VibeVoice-compatible API.
- `VibeVoiceVllmProvider` handles OpenAI-compatible vLLM ASR endpoint.

`TranscriptResult`:

```json
{
  "text": "...",
  "segments": [
    {"speaker": "Speaker 1", "start": 0.0, "end": 12.3, "text": "..."}
  ],
  "language": "en",
  "provider": "vibevoice_vllm",
  "raw_path": "data/vibevoice/tasks/.../raw.json"
}
```

### 6.2 Article pipeline integration

Existing order should remain:

```text
local subtitle
-> remote subtitle via yt-dlp
-> configured ASR provider
-> LLM optimize/summary/rewrite
```

When `vibevoice_asr_enabled=true`, configured ASR provider can become VibeVoice. Whisper remains fallback if configured.

Suggested provider resolution:

```text
if vibevoice_asr_enabled and vibevoice_asr_base_url:
    use VibeVoice ASR API/vLLM
elif whisper_provider == "local":
    use faster-whisper local
else:
    use remote Whisper API
```

Do not remove existing `whisper_provider` behavior in the first implementation.

### 6.3 Clip pipeline integration

For `scripts/clip_pipeline.py`, VibeVoice ASR can improve:

- speaker-aware subtitles
- timeline segmentation
- diarized transcript for clip scoring

MVP should only feed normalized `.srt`/`.txt` artifacts back into the existing pipeline. Native diarization-enhanced scoring can be a later phase.

---

## 7. TTS Integration Design

### 7.1 Provider strategy

Add a generic `TtsProvider` abstraction:

```text
TtsProvider.generate(text, voice, language, output_dir, progress) -> TtsResult
```

Providers:

- `GenericTtsApiProvider`: POST text to user service, receive audio.
- `VibeVoiceRealtimeWsProvider`: connect to websocket wrapper service.
- `VibeVoiceLocalCliProvider`: optional future wrapper around official demo script, disabled by default.

### 7.2 Safety defaults

MVP should:

- Disable voice cloning/custom voice upload.
- Use only built-in speaker names exposed by the configured service.
- Require a visible disclosure checkbox or persistent config `vibevoice_require_disclosure=true`.
- Write `metadata.json` next to generated audio with model/provider/disclosure fields.
- Limit test input length in UI, for example 5,000 chars initially.
- Keep longform multi-speaker TTS disabled unless user explicitly enables an external service.

### 7.3 AI video generation integration

Current config already has:

- `tts_provider`
- `local_tts_url`
- `video_gen_output_dir`

VibeVoice should be added as one possible `tts_provider` value, not a separate competing video generation pipeline.

Suggested values:

```text
tts_provider = local | vibevoice_api | vibevoice_realtime
```

---

## 8. UI Design

### 8.1 Route and placement

Add a new settings page rather than overloading “AI 视频切片”:

- Route: `#/settings-voice`
- Nav/i18n: `nav.settingsVoice`
- Template: `monitor_web/templates/pages/settings-voice.html`
- Module init: `window.init_settings_voice_page`
- Settings hub card: “AI 语音”

Rationale:

- VibeVoice covers ASR and TTS, not only clipping.
- Users need a clear place to run environment checks and test endpoints.
- It avoids making the existing settings-ai page too dense.

### 8.2 Page layout

Keep the current settings page shell:

```text
Page header
  title: AI 语音
  desc: VibeVoice ASR/TTS provider, environment checks, and test tasks
  action: Save settings

Grid single column
  Card 1: Capability status
  Card 2: ASR provider
  Card 3: TTS provider
  Card 4: Smoke test
  Card 5: Recent voice tasks
```

### 8.3 Card details

Capability status:

- Python, ffmpeg, Docker, GPU, torch CUDA, vLLM, endpoint health.
- Status must use text + badge, not color alone.
- “Run check” button triggers `/api/vibevoice/env/check`.

ASR provider:

- Enable VibeVoice ASR checkbox.
- Backend select: API / vLLM OpenAI-compatible / Local CLI (experimental).
- Base URL, API Key, model, hotwords, timeout.
- Test connection button.
- Short note: “当前机器不推荐本地 ASR；建议使用远程 GPU/vLLM 服务。”

TTS provider:

- Enable VibeVoice TTS checkbox.
- Backend select: API / Realtime websocket / Local CLI (experimental).
- Base URL, API Key, model, voice, language.
- Disclosure required toggle, default on.
- Longform/multi-speaker toggle hidden behind advanced section, default off.

Smoke test:

- ASR: select existing monitor video or enter local media path; optional hotwords; start transcription.
- TTS: textarea, voice, language, generate preview.
- Show progress with `aria-live`.

Recent voice tasks:

- Type, backend, status, created time, output links.
- Retry/cancel where applicable.

### 8.4 Visual constraints

Use existing `DESIGN.md` and CSS variables:

- Background: `--bg` Parchment.
- Cards: `--surface` Ivory, `--border` warm border.
- Primary CTA: `--accent` Terracotta.
- Secondary buttons: `--surface3`.
- Radius: `--r-md` / `--r-lg`.
- Typography: existing serif/sans split.
- No new color palette.
- No decorative gradients or marketing hero.
- Avoid emoji-only icons; use text labels or existing SVG pattern for icon buttons.

Accessibility requirements:

- Every input has a label.
- Buttons show loading and disabled state while running.
- Errors use `role="alert"` or `aria-live`.
- Interactive targets should meet 44x44px where practical.
- Keyboard focus states remain visible.
- Status is readable without relying on color.

---

## 9. Security and Risk Controls

Voice generation has higher misuse risk than ordinary subtitle generation. The integration must include guardrails:

- Keep TTS disabled by default.
- Do not support voice cloning/custom voice prompts in MVP.
- Do not auto-generate impersonation-style content.
- Show a persistent disclosure note for generated speech.
- Store generated audio under `data/vibevoice/` or configured output dir, not random user paths.
- Sanitize task paths using existing realpath/allowed-root checks.
- Mask API keys in config responses.
- Never log full API keys or full generated scripts if they may contain sensitive content.
- Record model/provider metadata beside outputs.
- Treat official Microsoft removal of TTS code as a product constraint, not an implementation obstacle to bypass.

---

## 10. Alternatives Considered

### Option A: Local-first direct import

Directly install VibeVoice into the project venv and call model code from `server/__main__.py`.

Rejected for MVP:

- Main process would load heavy models and block/crash the monitor server.
- Dependencies are much larger than the existing app.
- Current machine is CPU-only from PyTorch perspective and has too little VRAM.
- PyInstaller packaging would become fragile.

### Option B: Service/API-first integration

Main project calls a VibeVoice API/vLLM/realtime service. Local environment detection tells the user what is missing.

Recommended:

- Matches current local machine.
- Keeps heavy dependencies optional.
- Works with remote GPU machines.
- Easier to test with mocked HTTP clients.
- Safer rollout.

### Option C: UI-only link-out to VibeVoice demos

Add only links to Colab/Playground and no integration.

Rejected:

- Does not integrate with article/clip/video generation workflows.
- Does not give local task history or config management.

---

## 11. Open Questions for Discussion

1. Is the first priority **ASR for better article/clip transcripts**, or **TTS for video generation voiceover**?
2. Do you have or plan to use a separate GPU machine for VibeVoice? If yes, should the MVP target vLLM ASR first?
3. Should the UI be a standalone “AI 语音” page as recommended, or should it be merged into existing “AI 视频切片” settings?
4. Should generated TTS audio be allowed for automatic publishing, or must it remain manual-review only at first?

---

## 12. Spec Self-review

- Placeholder scan: no unfinished placeholder markers remain.
- Scope check: MVP is intentionally API/service-first and avoids model installation.
- Consistency check: ASR plugs into existing subtitle/Whisper chain; TTS plugs into existing video generation provider shape.
- Risk check: Longform TTS is disabled by default due official removal and misuse risk.
- Ambiguity check: Local model execution is explicitly not part of MVP; environment checker is read-only.

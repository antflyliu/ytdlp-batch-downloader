# VoxCPM 集成可行性与设计草案

**日期**: 2026-06-06  
**状态**: Draft for discussion  
**范围**: 只做可行性分析、功能清单、UI/后端集成 spec 与实施计划；本轮不修改代码。  
**相关上游**: [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM)、[VoxCPM docs](https://voxcpm.readthedocs.io/en/latest/)

---

## 1. 结论摘要

可以集成 VoxCPM，但它应作为 **AI 语音生成 / TTS provider** 接入，而不是作为 ASR 或通用多模态模型接入。

推荐 MVP:

1. **TTS-first**: 将 VoxCPM 接入现有 AI 视频生成配音链路，支持文本转语音、音色描述、参考音频克隆和输出音频管理。
2. **本地优先但服务隔离**: 项目主进程只做环境检测、任务编排、配置、UI 和 API 调用；VoxCPM 模型推理放在外部服务、独立 worker/venv、局域网 GPU 机器或 vLLM-Omni 服务中。
3. **API 兜底**: 支持 OpenAI-compatible `/v1/audio/speech` 用于基础 TTS；支持通用 VoxCPM HTTP 服务用于 reference audio、prompt transcript、CFG、steps、normalize、denoise 等高级能力。
4. **本机直接跑模型仅列为实验路径**: 当前机器 Python 与 ffmpeg 条件可用，但 PyTorch 是 CPU 版，显卡 MX150 2GB 远低于 VoxCPM2 约 8GB VRAM、VoxCPM1.5 约 6GB VRAM、VoxCPM-0.5B 约 5GB VRAM 的官方参考占用。

不建议在 MVP 中做:

- 不把 `voxcpm`、`vllm`、CUDA/Triton 等重型依赖加入主 `requirements.txt`。
- 不在 `server/__main__.py` 进程里直接加载模型。
- 不默认从已下载 YouTube 视频中提取并克隆人物声音。
- 不做 LoRA 微调、批量并发 GPU 服务、模型下载器或 Docker 自动部署。

---

## 2. 当前本地环境检测结论

本轮只做只读探测，没有安装依赖、下载模型或启动服务。

| 项目 | 结果 | 集成含义 |
| --- | --- | --- |
| OS | Windows 11 | 可运行主项目；VoxCPM Windows + torch.compile/Triton 需谨慎 |
| Python | 3.12.1 (`C:\Python312\python.exe`) | 满足 VoxCPM Python 3.10-3.12 要求 |
| ffmpeg / ffprobe | 可用 | 支持音频转码、时长探测、输出后处理 |
| GPU | NVIDIA GeForce MX150, 2048 MiB | 不适合本机跑 VoxCPM2/1.5/0.5B |
| PyTorch | `2.8.0+cpu` | 当前无法使用 CUDA 推理 |
| `torch.cuda.is_available()` | `false` | 本机 GPU 当前对 PyTorch 不可用 |
| `voxcpm` | 未安装 | 不能直接本地调用 VoxCPM Python API |
| `vllm` | 未安装 | 不能直接本地启动 vLLM-Omni |
| `torchaudio` / `soundfile` | 已安装 | 音频 I/O 基础可用 |
| `huggingface_hub` / `modelscope` | 已安装 | 具备模型下载相关包，但不建议本机下载大模型作为默认路径 |
| Docker | 客户端存在，daemon 未运行 | 不能立即跑容器化 vLLM 服务 |
| 磁盘空余 | C: 24.56GB, D: 21.14GB, G: 16.87GB | 可容纳少量模型/输出，但对多模型缓存偏紧 |

本地化判断:

- **本机离线本地化**: 不推荐作为默认方案。CPU 版 PyTorch 可尝试极慢推理，但用户体验不可控。
- **局域网/远程 GPU 私有服务**: 推荐。仍满足“本地化/私有化”目标，主项目通过 `base_url` 调用内网服务。
- **公网 API**: 可选兜底。适合用户已有服务或托管 GPU，不作为默认。

---

## 3. VoxCPM 上游功能清单

### 3.1 模型版本

| 版本 | 状态 | 主要能力 | 采样率 | 语言 | 参考显存 |
| --- | --- | --- | --- | --- | --- |
| VoxCPM2 | 最新推荐 | 多语言 TTS、音色设计、可控克隆、极致克隆、流式生成 | 48kHz | 30 种语言 + 多种中文方言 | 约 8GB |
| VoxCPM1.5 | 稳定版 | 中英 TTS、音频续写式克隆、SFT/LoRA | 44.1kHz | 中文、英文 | 约 6GB |
| VoxCPM-0.5B | 旧版 | 中英 TTS、音频续写式克隆 | 16kHz | 中文、英文 | 约 5GB |

### 3.2 VoxCPM2 主要功能

- **文本转语音**: 直接输入文本生成语音。
- **30 语言合成**: 支持中文、英文、日语、韩语、法语、德语、西语、俄语、越南语、泰语等。
- **中文方言**: 支持四川话、粤语、吴语、东北话、河南话、陕西话、山东话、天津话、闽南话等。
- **音色设计**: 无需参考音频，用自然语言描述音色，例如性别、年龄、情绪、语速、角色。
- **可控声音克隆**: 上传参考音频，克隆音色，并可用控制指令调整情绪、语速和风格。
- **极致克隆 / 音频续写**: 同时提供参考音频和准确 transcript，模型从参考音频后续写，追求最高相似度。
- **上下文感知韵律**: 根据文本语义推断语气和停顿。
- **文本规范化**: 可启用数字、日期等规范化。
- **流式生成**: Python API 提供 `generate_streaming()`。
- **CLI**: `voxcpm design`、`voxcpm clone`、`voxcpm batch`。
- **Web Demo**: 官方 Gradio app，包含参考音频上传、ASR 填充 prompt transcript、控制参数。
- **生产部署**: vLLM-Omni 支持 OpenAI-compatible `/v1/audio/speech`；NanoVLLM-VoxCPM 支持高吞吐 CUDA 推理和 streaming。
- **微调**: 支持 SFT / LoRA，但不进入本项目 MVP。

### 3.3 对本项目的价值映射

| VoxCPM 能力 | 项目内用途 | MVP 优先级 |
| --- | --- | --- |
| 文本转语音 | AI 视频生成 narration、文章朗读、脚本配音预览 | P0 |
| 音色设计 | 不上传参考音频即可生成角色/风格声音 | P0 |
| 参考音频克隆 | 用户自备授权声音，用于稳定品牌音色 | P1 |
| 极致克隆 | 需要 transcript 的高保真克隆 | P2 |
| 30 语言 / 方言 | 面向多语种搬运、中文方言本地化配音 | P1 |
| streaming | 长文本配音或在线预览 | P2 |
| batch CLI | 批量脚本生成语音素材 | P2 |
| vLLM-Omni API | 外部 GPU 服务基础 TTS | P0 |
| LoRA 微调 | 个性化长期声音模型 | 暂不做 |

---

## 4. 推荐集成架构

### 4.1 边界原则

主项目负责:

- 本地环境检测与服务健康检查
- 配置管理和密钥加密/遮罩
- Voice task 创建、取消、状态、日志和输出文件索引
- 输入文本、参考音频路径、输出目录的安全校验
- 调用 VoxCPM 服务或 worker
- 将音频结果接入 AI 视频生成管线
- Vue/Naive UI 页面

推理侧负责:

- `voxcpm` 模型加载
- CUDA/MPS/CPU 设备选择
- vLLM-Omni 或 NanoVLLM 服务
- 模型缓存、依赖隔离和 GPU 资源管理

### 4.2 三种接入方式

#### 方案 A: 外部 VoxCPM HTTP 服务（推荐 MVP）

主项目通过 `base_url` 调用一个稳定的 HTTP 服务。这个服务可以是用户自己部署的本机/局域网/远程 GPU 服务。

优点:

- 不污染主项目依赖。
- 可支持 reference audio、prompt transcript、control instruction、CFG、steps、normalize、denoise 等完整参数。
- 适合 Windows 主项目 + Linux GPU 推理服务的组合。

缺点:

- 需要定义并文档化服务契约。
- 用户需要单独部署服务。

#### 方案 B: vLLM-Omni OpenAI-compatible API（基础 TTS 兜底）

调用 `/v1/audio/speech`，适合只需要 `model + input + voice` 的基础语音生成。

优点:

- 兼容 OpenAI audio speech 形态。
- 适合生产 GPU 服务、并发和流式输出。

缺点:

- 标准 `/v1/audio/speech` 不一定覆盖参考音频克隆和 VoxCPM 专有参数。
- vLLM-Omni 偏 Linux/GPU，当前本机不满足。

#### 方案 C: 本地 Python worker / CLI（实验）

在独立 Python 环境中运行 `voxcpm`，主项目通过子进程或本地 HTTP worker 调用。

优点:

- 最接近“纯本机离线”。
- 能使用 VoxCPM Python API 全能力。

缺点:

- 当前本机 CPU-only，体验不可控。
- Windows 上 Triton/torch.compile 有额外兼容风险。
- 依赖重，不能放入主进程。

推荐顺序: **A -> B -> C**。

---

## 5. 后端模块设计

建议新增独立包:

```text
monitor/voice/
├── __init__.py
├── env.py              # 本地环境与远程服务健康探测
├── clients.py          # VoxCPM HTTP / OpenAI speech / local worker clients
├── tasks.py            # VoiceTaskManager
├── schemas.py          # 请求与响应规范化
├── storage.py          # 输出音频、metadata、参考音频索引
└── safety.py           # 引用音频策略、披露元数据、长度限制
```

命名使用 `voice` 而不是 `voxcpm`，便于未来接入 Edge TTS、Azure、OpenAI、MiniMax、VibeVoice 等 provider。VoxCPM 是第一个完整落地的本地优先 provider。

### 5.1 配置项草案

| Key | 默认值 | 说明 |
| --- | --- | --- |
| `voice_provider` | `voxcpm_http` | `voxcpm_http` / `openai_speech` / `local_worker` / `edge` / `silent` |
| `voice_output_dir` | `data/voice` | 语音输出目录 |
| `voxcpm_enabled` | `false` | VoxCPM 总开关 |
| `voxcpm_backend` | `http` | `http` / `openai_speech` / `local_worker` |
| `voxcpm_base_url` | `""` | 外部服务地址 |
| `voxcpm_api_key` | `""` | 可选 bearer token，需加密落盘 |
| `voxcpm_model` | `openbmb/VoxCPM2` | 模型名或 served model |
| `voxcpm_voice` | `default` | 默认 voice |
| `voxcpm_device` | `auto` | local worker 使用 |
| `voxcpm_control_instruction` | `""` | 默认音色描述 |
| `voxcpm_cfg_value` | `2.0` | 1.0-3.0 |
| `voxcpm_inference_timesteps` | `10` | 4-30 推荐 |
| `voxcpm_normalize` | `true` | 文本规范化 |
| `voxcpm_denoise_reference` | `false` | 参考音频降噪 |
| `voxcpm_max_text_chars` | `3000` | 单次请求文本上限 |
| `voxcpm_require_disclosure` | `true` | 生成 metadata 记录 AI 生成 |
| `voxcpm_allow_reference_clone` | `false` | 默认关闭参考音频克隆 |
| `voxcpm_allow_ultimate_clone` | `false` | 默认关闭 prompt transcript 模式 |

敏感配置:

- `voxcpm_api_key` 必须加入后端响应遮罩和落盘加密列表。
- 任何服务 URL 不允许包含用户名/密码，避免配置泄漏。

### 5.2 API 草案

```http
GET  /api/voice/env
POST /api/voice/env/check
POST /api/voice/tasks
GET  /api/voice/tasks
GET  /api/voice/tasks/{task_id}
POST /api/voice/tasks/{task_id}/cancel
GET  /api/voice/audio/{task_id}
POST /api/voice/smoke-test
```

创建任务请求:

```json
{
  "provider": "voxcpm_http",
  "mode": "voice_design",
  "text": "欢迎使用 AI 视频生成管线。",
  "control_instruction": "年轻女性，温柔清晰，适合科技解说",
  "reference_audio_path": "",
  "prompt_text": "",
  "cfg_value": 2.0,
  "inference_timesteps": 10,
  "normalize": true,
  "denoise": false,
  "source": "manual"
}
```

任务状态:

```json
{
  "task_id": "voice_20260606_001",
  "status": "running",
  "progress": 40,
  "stage": "synthesizing",
  "message": "正在调用 VoxCPM 服务",
  "audio_path": "",
  "metadata_path": "",
  "created_at": "2026-06-06T16:30:00+08:00",
  "updated_at": "2026-06-06T16:30:12+08:00"
}
```

### 5.3 数据表草案

```text
voice_tasks
├── task_id TEXT PRIMARY KEY
├── provider TEXT
├── backend TEXT
├── mode TEXT
├── source TEXT
├── source_task_id TEXT
├── text TEXT
├── control_instruction TEXT
├── reference_audio_path TEXT
├── prompt_text TEXT
├── status TEXT
├── progress INTEGER
├── stage TEXT
├── message TEXT
├── output_audio_path TEXT
├── metadata_path TEXT
├── error TEXT
├── created_at TEXT
└── updated_at TEXT
```

metadata 文件记录:

- provider、backend、model、cfg、steps、normalize、denoise
- input text hash
- reference audio hash/path
- disclosure flag
- upstream response摘要
- 生成耗时、采样率、音频时长

---

## 6. 前端 UI 设计

使用现有 Vue 3 + Naive UI + `DESIGN.md` 暖色系统，不引入新 UI 依赖。

### 6.1 页面入口

推荐新增一个一级页面:

- 路由: `/ai-voice`
- 导航名: `AI 语音`
- 位置: `AI 创作` 附近

同时在 AI 设置页增加一个轻量配置区或跳转卡片:

- `VoxCPM 服务地址`
- `API Key`
- `Provider`
- `默认音色描述`
- `允许参考音频克隆`

如果希望最小化导航复杂度，也可以把 `/ai-voice` 做成 `AiCreation.vue` 的第三个 tab；但独立页面更清晰，避免当前 AI 创作页继续膨胀。

### 6.2 页面布局

```text
AI 语音
├── 顶部状态区
│   ├── 本机环境
│   ├── VoxCPM 服务连通性
│   └── 当前 Provider
├── 左侧: 生成表单
│   ├── 模式: 音色设计 / 参考克隆 / 极致克隆
│   ├── 文本
│   ├── 音色描述
│   ├── 参考音频路径或上传
│   ├── prompt transcript
│   └── 高级参数折叠区
└── 右侧: 结果与历史
    ├── 最新音频播放器
    ├── 输出文件路径
    ├── 任务状态
    └── 最近任务表
```

### 6.3 视觉规则

来自 `DESIGN.md` 和 `ui-ux-pro-max` 检查:

- 背景使用 `--bg` Parchment，卡片使用 `--surface` Ivory。
- 主 CTA 使用 `--accent` Terracotta。
- 不使用 emoji 作为图标，沿用内联 SVG 图标风格。
- 表单输入必须有 label。
- 按钮点击期间 loading + disabled。
- 错误显示在相关表单附近。
- 任务状态区域使用 `aria-live="polite"`。
- 移动端单列；桌面端 2 栏；不出现横向滚动。
- 高级参数默认折叠，保持页面简单。

---

## 7. AI 视频生成管线接入

现有 `scripts/video_gen_pipeline.py` 已有:

- `tts_provider`
- `local_tts_url`
- edge-tts fallback
- silent/offline fallback

推荐演进:

1. 保留现有行为。
2. 新增 `voice_provider` 解析函数。
3. 当任务 `tts_workflow` 或配置选择 `voxcpm` 时，调用 voice task/client。
4. 生成音频后返回给现有 `_render_video()`，不改视频合成逻辑。
5. 将 `voice_task_id`、`voice_provider`、`audio_path` 写入视频任务 metadata。

这样不会重写视频管线，只替换 narration synthesis 的 provider 层。

---

## 8. 环境检测设计

`GET /api/voice/env` 返回缓存结果，`POST /api/voice/env/check` 执行完整探测。

检测项:

- Python 版本与可执行路径
- OS / 架构
- `ffmpeg` / `ffprobe`
- `nvidia-smi`、GPU 名称、显存、驱动
- `torch` 版本、CUDA 是否可用、CUDA 版本、设备列表
- `voxcpm`、`vllm`、`torchaudio`、`soundfile`、`torchcodec`、`huggingface_hub`、`modelscope`
- Docker client 和 daemon
- 磁盘空间
- `voxcpm_base_url` 健康检查
- `/v1/audio/speech` smoke test 可选

输出要包含:

- `status`: `ok` / `warning` / `error`
- `reason`: 明确原因
- `recommendation`: 下一步建议
- `can_run_local`: 是否适合本机 local worker
- `recommended_backend`: `http` / `openai_speech` / `local_worker`

---

## 9. 安全与使用边界

语音生成和声音克隆有明确滥用风险，项目默认策略应保守:

- 默认关闭参考音频克隆和极致克隆。
- UI 明确提示“只使用本人拥有授权的参考音频”。
- 不自动从下载视频中抽取人物声音作为 reference audio。
- 所有输出 metadata 默认记录 `ai_generated: true`。
- 自动分发前应保留人工审核门槛。
- 不提供绕过 disclosure、批量仿冒或隐藏生成来源的功能。
- API token 与服务地址按现有敏感字段规则处理。

---

## 10. 测试策略

不跑真实模型也能覆盖大部分集成风险:

- 环境检测函数: monkeypatch `subprocess`、`importlib`、磁盘信息。
- 配置保存: 默认值、密钥遮罩、masked secret preservation、URL 校验。
- Client adapter: mock HTTP 成功、401、timeout、非音频响应、JSON 文件引用。
- Voice task manager: fake provider 跑任务生命周期、取消、错误落库。
- API contract: 路由、payload、错误码。
- Vue contract: 路由存在、i18n key 存在、敏感输入遮罩逻辑。
- 视频管线: fake voice provider 返回音频路径，确认不破坏 edge/silent fallback。

真实端到端只作为手动验证:

- `voice_design` 短文本生成
- reference audio 克隆
- AI 视频生成使用 VoxCPM 音频

---

## 11. 待讨论决策

1. MVP 页面采用独立 `/ai-voice`，还是放入 `AI 创作` 第三个 tab？
2. 首个可用 backend 选 `voxcpm_http`，还是优先兼容 vLLM-Omni `/v1/audio/speech`？
3. 是否默认允许 reference audio 克隆？推荐默认关闭，用户显式开启。
4. AI 视频生成中，VoxCPM 是否作为默认 TTS，还是只作为可选 provider？推荐可选 provider。
5. 是否需要后续提供一个官方推荐的 `voxcpm-worker` 示例脚本？推荐第二阶段做，不进入 MVP。

---

## 12. 参考资料

- [OpenBMB/VoxCPM GitHub](https://github.com/OpenBMB/VoxCPM)
- [VoxCPM Quick Start](https://voxcpm.readthedocs.io/en/latest/quickstart.html)
- [VoxCPM Installation](https://voxcpm.readthedocs.io/en/latest/installation.html)
- [VoxCPM Usage Guide](https://voxcpm.readthedocs.io/en/latest/usage_guide.html)
- [VoxCPM API Reference](https://voxcpm.readthedocs.io/en/latest/reference/api.html)
- [VoxCPM FAQ & Troubleshooting](https://voxcpm.readthedocs.io/en/latest/faq.html)
- [VoxCPM vLLM-Omni deployment](https://voxcpm.readthedocs.io/en/latest/deployment/vllm_omni.html)
- [VoxCPM NanoVLLM deployment](https://voxcpm.readthedocs.io/en/latest/deployment/nanovllm_voxcpm.html)
- [DESIGN.md](../../../DESIGN.md)

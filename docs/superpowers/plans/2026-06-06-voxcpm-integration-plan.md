# VoxCPM 集成实施计划草案

> **Status:** Draft for discussion. Do not implement until the spec is approved.  
> **Spec:** `docs/superpowers/specs/2026-06-06-voxcpm-integration-feasibility-design.md`

**Goal:** 以本地优先、服务隔离、API 兜底的方式把 OpenBMB VoxCPM 接入本项目，提供 AI 语音生成、环境检测、UI 页面和 AI 视频生成配音能力。

**Recommended MVP:** `voxcpm_http` provider + 环境检测 + `/ai-voice` 页面 + 视频生成 TTS provider 接入。vLLM-Omni OpenAI-compatible speech 作为基础 TTS 兼容路径。

---

## Phase 0: Review and Decisions

- [ ] 用户审阅 spec。
- [ ] 决定 UI 入口: 独立 `/ai-voice` 或 `AI 创作` 第三个 tab。
- [ ] 决定首个 backend: `voxcpm_http` 或 `openai_speech`。
- [ ] 确认 reference audio clone 默认策略: 默认关闭或默认开启。
- [ ] 确认 AI 视频生成里 VoxCPM 是可选 provider 还是默认 provider。

Exit criteria:

- spec 通过讨论或完成修订。
- MVP 路线明确。

---

## Phase 1: Environment Detection Foundation

Files:

- Add: `monitor/voice/__init__.py`
- Add: `monitor/voice/env.py`
- Add: `scripts/voice_env.py`
- Modify: `server/__main__.py`
- Add: `tests/test_voice_env.py`
- Add: `tests/test_voice_env_api.py`

Tasks:

- [ ] 实现只读探测: Python、OS、ffmpeg、ffprobe、nvidia-smi、torch、CUDA、voxcpm、vllm、torchaudio、soundfile、torchcodec、Docker、磁盘空间。
- [ ] 生成稳定 JSON: `status`、`reason`、`recommendation`、`can_run_local`、`recommended_backend`。
- [ ] 添加 `GET /api/voice/env`。
- [ ] 添加 `POST /api/voice/env/check`。
- [ ] 添加 CLI: `python scripts/voice_env.py --json`。
- [ ] 测试 Windows 无 CUDA、Docker daemon 未运行、缺少 voxcpm、远程服务不可达等场景。

Verification:

```powershell
python scripts/voice_env.py --json
python -m pytest tests/test_voice_env.py tests/test_voice_env_api.py -q
```

Notes:

- 不安装依赖。
- 不下载模型。
- 不启动 Docker/container。

---

## Phase 2: Config Schema and Secret Handling

Files:

- Modify: `config/settings.py`
- Modify: `server/__main__.py`
- Modify: `frontend-vue/src/api/config.ts`
- Add: `tests/test_voice_config.py`
- Extend: `tests/test_ai_content_config_masking_contract.py`

Tasks:

- [ ] 增加 spec 中的 `voice_*` 和 `voxcpm_*` 默认配置。
- [ ] 将 `voxcpm_api_key` 加入 `_SECRET_CONFIG_KEYS`。
- [ ] 将 `voxcpm_api_key` 加入 `_CONFIG_RESPONSE_SECRET_KEYS`。
- [ ] 扩展 `/api/config` allowlist。
- [ ] 保存配置时保留 masked secret。
- [ ] 校验 `voxcpm_backend` enum。
- [ ] 校验 `voxcpm_base_url` 必须是 HTTP(S)，且 URL 不包含明文用户名密码。
- [ ] 扩展前端 `AppConfig` 类型。

Verification:

```powershell
python -m pytest tests/test_voice_config.py tests/test_ai_content_config_masking_contract.py -q
```

---

## Phase 3: Voice Client Adapters

Files:

- Add: `monitor/voice/clients.py`
- Add: `monitor/voice/schemas.py`
- Add: `monitor/voice/storage.py`
- Add: `monitor/voice/safety.py`
- Add: `tests/test_voice_clients.py`
- Add: `tests/test_voice_storage.py`

Tasks:

- [ ] 定义 `VoiceSynthesisRequest` 和 `VoiceSynthesisResult`。
- [ ] 实现 `VoxCpmHttpClient`，支持 JSON + multipart reference audio。
- [ ] 实现 `OpenAiSpeechClient`，兼容 `/v1/audio/speech` 的基础 TTS。
- [ ] 预留 `LocalWorkerClient` 接口，但 MVP 不实现启动 worker。
- [ ] 保存 audio bytes 到 `voice_output_dir`。
- [ ] 保存 `metadata.json`。
- [ ] 支持 `wav` / `mp3` content-type 推断。
- [ ] 映射 HTTP 401、timeout、非音频响应、服务端 JSON 错误。
- [ ] 实现文本长度限制和 reference clone gate。

Verification:

```powershell
python -m pytest tests/test_voice_clients.py tests/test_voice_storage.py -q
```

Implementation caution:

- 不 import `voxcpm`。
- 不引入 `vllm`。
- 不把 VoxCPM heavy dependencies 加入主依赖。

---

## Phase 4: Voice Task Manager and API

Files:

- Add: `monitor/voice/tasks.py`
- Modify: `monitor/schema.sql`
- Modify: `monitor/db.py` or add `monitor/db/queries/voice.py`
- Modify: `server/__main__.py`
- Add: `tests/test_voice_tasks_api.py`

Tasks:

- [ ] 新增 `voice_tasks` 表迁移。
- [ ] 增加 query helpers: create/list/get/update/cancel。
- [ ] 实现 `VoiceTaskManager` 后台线程任务。
- [ ] 添加 `POST /api/voice/tasks`。
- [ ] 添加 `GET /api/voice/tasks`。
- [ ] 添加 `GET /api/voice/tasks/{task_id}`。
- [ ] 添加 `POST /api/voice/tasks/{task_id}/cancel`。
- [ ] 添加 `GET /api/voice/audio/{task_id}`。
- [ ] 添加 `POST /api/voice/smoke-test`。
- [ ] 实现安全路径解析和输出目录限制。
- [ ] fake provider 测试任务成功、失败、取消。

Verification:

```powershell
python -m pytest tests/test_voice_tasks_api.py -q
```

---

## Phase 5: Vue UI Page

Files:

- Add: `frontend-vue/src/views/AiVoice.vue`
- Add: `frontend-vue/src/api/voice.ts`
- Modify: `frontend-vue/src/router/index.ts`
- Modify: `frontend-vue/src/components/layout/AppSider.vue`
- Modify: `frontend-vue/src/views/settings/AiSettings.vue` or add `frontend-vue/src/views/settings/VoiceSettings.vue`
- Modify: `frontend-vue/src/views/SettingsHub.vue` if a settings page is added
- Modify: `frontend-vue/src/locales/zh.json`
- Modify: `frontend-vue/src/locales/en.json`
- Add/extend UI contract tests

Tasks:

- [ ] 新增 `/ai-voice` route。
- [ ] 侧边栏增加 `AI 语音`，使用内联 SVG 图标。
- [ ] 顶部卡片展示环境、本机可行性、服务连通性、当前 provider。
- [ ] 生成表单支持三种模式: 音色设计、参考克隆、极致克隆。
- [ ] 高级参数折叠: CFG、steps、normalize、denoise。
- [ ] 输出区显示播放器、文件路径、metadata、复制路径。
- [ ] 最近任务表支持刷新、状态、打开/播放。
- [ ] 环境检测按钮调用 `/api/voice/env/check`。
- [ ] Smoke test 按钮调用 `/api/voice/smoke-test`。
- [ ] 所有交互控件有 label、loading、disabled、focus state。
- [ ] 默认隐藏 reference clone，除非配置允许。
- [ ] 中英文 i18n 补齐。

Verification:

```powershell
cd frontend-vue
npm run build
```

Manual UI verification:

- 打开 `/ai-voice`。
- 检查 375px、768px、1024px、1440px。
- 确认无横向滚动。
- 确认无 emoji icon。
- 确认错误、loading、空状态可见。

---

## Phase 6: AI Video Generation TTS Integration

Files:

- Modify: `scripts/video_gen_pipeline.py`
- Add: `tests/test_video_gen_voice_provider.py`
- Extend: `tests/test_ai_content_provider_pipeline_contract.py`

Tasks:

- [ ] 抽取 TTS provider 选择逻辑。
- [ ] 增加 `voice_provider` / `voxcpm` 分支。
- [ ] 用 fake voice client 测试返回音频路径。
- [ ] 保留 edge-tts、local_tts_url、offline-silence 行为。
- [ ] 视频任务 metadata 记录 `voice_provider`、`voice_task_id`、`audio_path`。
- [ ] 失败时根据配置决定 fallback 到 silent 还是报错。

Verification:

```powershell
python -m pytest tests/test_video_gen_voice_provider.py tests/test_ai_content_provider_pipeline_contract.py -q
```

---

## Phase 7: Optional Local Worker Guide

Files:

- Add: `docs/voxcpm-worker.md`
- Optional Add: `scripts/voxcpm_worker_example.py`
- Optional Add: `scripts/voxcpm_smoke.py`

Tasks:

- [ ] 文档化独立 venv / uv 环境安装方式。
- [ ] 文档化 Windows 注意事项: CPU 慢、Triton、`optimize=False`。
- [ ] 文档化 Linux CUDA 推荐路径。
- [ ] 提供最小 HTTP 服务契约示例。
- [ ] 提供 health endpoint 示例。

Verification:

```powershell
python scripts/voxcpm_smoke.py --base-url http://127.0.0.1:8808
```

Notes:

- 此阶段不作为 MVP 必须项。
- 示例 worker 不应被主服务自动启动。

---

## Phase 8: Documentation and Final Verification

Files:

- Add: `docs/voxcpm-integration.md`
- Modify: `README.md` after implementation is verified

Tasks:

- [ ] 写用户文档: 本地环境检测、远程服务配置、vLLM-Omni、VoxCPM HTTP 服务契约。
- [ ] 写安全使用说明。
- [ ] 写常见错误: CPU-only、CUDA 不可用、Docker daemon 未运行、ffmpeg 缺失、服务超时。
- [ ] 更新 README 功能列表。
- [ ] 跑后端相关测试。
- [ ] 跑前端 build。
- [ ] 如可用，手动用短文本完成一次 smoke test。

Verification:

```powershell
python -m pytest tests/test_voice_env.py tests/test_voice_config.py tests/test_voice_clients.py tests/test_voice_tasks_api.py tests/test_video_gen_voice_provider.py -q
cd frontend-vue
npm run build
```

---

## Delivery Criteria

- [ ] spec 中讨论项已决策。
- [ ] 环境检测可在无 VoxCPM、无 CUDA、Docker daemon 未运行时给出可理解建议。
- [ ] API key 不明文返回，不破坏已有 secret masking。
- [ ] `/ai-voice` 页面可以完成 smoke test 和任务查看。
- [ ] AI 视频生成可选使用 VoxCPM provider。
- [ ] 现有 edge/local/silent TTS 行为保持兼容。
- [ ] 没有将重型 VoxCPM/vLLM 依赖加入主依赖。
- [ ] 文档说明本机限制、推荐 GPU 服务路径和安全边界。

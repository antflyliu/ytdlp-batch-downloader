# Voice Provider Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a unified, flow-aware voice provider architecture so video generation, manual voice tasks, future article transcription, and future clip workflows can dynamically select Edge TTS, local HTTP TTS, OpenAI, Azure, MiniMax, VoxCPM, VibeVoice, Whisper, or silent providers without coupling workflow code to concrete provider classes.

**Architecture:** Add a shared `monitor/voice` domain with capability-specific provider interfaces, provider selection policy, storage/safety helpers, and script-friendly facades. Migrate the existing video narration path first while preserving `tts_provider`, `local_tts_url`, `tts_workflow`, Edge TTS, local HTTP TTS, and silent/offline behavior. Add external providers behind mocked tests and capability metadata. Add voice task/API/UI surfaces after the direct pipeline migration is stable.

**Tech Stack:** Python stdlib HTTP/subprocess/pathlib/dataclasses, existing SQLite helpers in `monitor/db.py`, existing custom HTTP server in `server/__main__.py`, Vue 3 + Naive UI frontend, pytest. Do not add provider SDK dependencies in the base app; call remote HTTP APIs with stdlib unless a later task explicitly obtains dependency approval.

---

## References

Design and repo references:

- `docs/superpowers/specs/2026-06-06-voice-provider-architecture-design.md`
- `docs/superpowers/specs/2026-06-06-vibevoice-integration-feasibility-design.md`
- `docs/superpowers/specs/2026-06-06-voxcpm-integration-feasibility-design.md`
- `docs/superpowers/plans/2026-06-06-vibevoice-integration-plan.md`
- `docs/superpowers/plans/2026-06-06-voxcpm-integration-plan.md`
- Current provider patterns: `scripts/image_generation.py`, `scripts/llm_client.py`
- Current TTS integration: `scripts/video_gen_pipeline.py`
- Current ASR integration: `scripts/article_generator.py`
- Current config/API/frontend integration: `config/settings.py`, `server/__main__.py`, `frontend-vue/src/views/AiCreation.vue`, `frontend-vue/src/views/settings/AiSettings.vue`

Official/provider documentation constraints:

- OpenAI Text to Speech: https://platform.openai.com/docs/guides/text-to-speech
- OpenAI Speech to Text: https://platform.openai.com/docs/guides/speech-to-text
- OpenAI Audio API Reference: https://platform.openai.com/docs/api-reference/audio/create
- Azure Speech REST Text to Speech: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech
- MiniMax API overview: https://platform.minimax.io/docs/api-reference/api-overview
- MiniMax HTTP T2A API: https://platform.minimax.io/docs/api-reference/speech-t2a-http
- MiniMax WebSocket T2A API: https://platform.minimax.io/docs/api-reference/speech-t2a-websocket
- MiniMax async long text T2A: https://platform.minimax.io/docs/api-reference/speech-t2a-async-create
- MiniMax voice clone: https://platform.minimax.io/docs/api-reference/voice-cloning-clone
- MiniMax voice design: https://platform.minimax.io/docs/api-reference/voice-design-design
- Edge TTS project README: https://github.com/rany2/edge-tts/blob/master/README.md
- VibeVoice repository/docs: https://github.com/microsoft/VibeVoice
- VoxCPM repository/docs: https://github.com/OpenBMB/VoxCPM and https://voxcpm.readthedocs.io/en/latest/

---

## Current Coupling to Preserve and Then Remove

Current runtime surface:

- `scripts/video_gen_pipeline.py` directly chooses Edge/local/silent providers in `_synthesize_narration()`.
- `video_gen_tasks.tts_workflow` stores a per-task provider-ish free text value.
- `config/settings.py` has `tts_provider` and `local_tts_url`.
- `scripts/article_generator.py` directly chooses Whisper fallback using `whisper_provider` and related config.
- `frontend-vue/src/views/AiCreation.vue` exposes free text `tts_workflow`.
- `frontend-vue/src/views/settings/AiSettings.vue` exposes global `tts_provider` and `local_tts_url`.

Compatibility requirements:

- `edge-tts` and `edge_tts` must resolve to the same provider.
- `local` must keep current behavior: use `local_tts_url` when configured, otherwise silent only when fallback policy allows it.
- `silent`, `offline`, `mock`, and `none` must produce a generated silent WAV.
- Explicit configured local TTS failure must not silently fall back; this is already locked by `tests/test_ai_content_provider_pipeline_contract.py`.
- Video rendering, storyboard creation, image generation, BGM, and `_probe_audio_duration()` must remain outside the provider migration.

---

## Provider Boundary Rules

Implementers must follow these rules across all tasks:

- Workflow code asks for a capability and flow, not for a concrete class.
- Workflow code imports only `monitor.voice` facade functions such as `synthesize_speech(request, cfg)` or `transcribe_media(request, cfg)`.
- Workflow code must not import `EdgeTtsProvider`, `OpenAiSpeechProvider`, `AzureSpeechProvider`, `MiniMaxSpeechProvider`, `VoxCpmHttpProvider`, or `VibeVoiceTtsProvider`.
- Provider fallback is controlled by `monitor/voice/selection.py`, not by individual providers.
- A provider may ignore unsupported optional fields only when the selected mode does not require them.
- A requested provider that lacks the requested capability fails before expensive work begins.
- Real provider tests must use fake HTTP/subprocess implementations; automated tests must not call OpenAI, Azure, MiniMax, VibeVoice, VoxCPM, Edge network services, or local large models.
- Do not add `voxcpm`, `vllm`, CUDA, VibeVoice, Azure SDK, OpenAI SDK, or websocket dependencies to base requirements.
- Reference cloning and prompt-transcript cloning remain disabled unless config explicitly enables them.

---

## Phase 0: Establish Regression Coverage Before Edits

Purpose: lock the existing TTS and config behavior before introducing the new abstraction.

Files:

- Modify: `tests/test_ai_content_provider_pipeline_contract.py`
- Add: `tests/test_voice_provider_contract.py`
- Add: `tests/test_voice_selection_contract.py`

Tasks:

- [ ] Add a regression test proving `tts_workflow="edge-tts"` still reaches the Edge path through the future facade.
- [ ] Add a regression test proving `tts_workflow="local"` with configured `local_tts_url` fails visibly when the service fails.
- [ ] Add a regression test proving `tts_workflow="silent"` creates a WAV under the task output directory.
- [ ] Add a test for alias normalization: `edge-tts -> edge_tts`, `offline -> silent`, `mock -> silent`, `none -> silent`, `voxcpm -> voxcpm_http`.
- [ ] Add a selection test where a task-level provider beats flow defaults and global defaults.
- [ ] Add a selection test where an explicit unavailable provider fails when fallback is not allowed.

Expected initial result:

```powershell
python -m pytest tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py -q
```

The new tests should fail before Phase 1 implementation because `monitor/voice` does not exist yet.

Commit after Phase 0:

```powershell
git add tests/test_ai_content_provider_pipeline_contract.py tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py
git commit -m "Lock voice provider compatibility before abstraction

The existing video narration behavior is the migration boundary for the unified voice provider layer.

Constraint: Edge, local HTTP, and silent TTS behavior must survive the provider abstraction.
Confidence: high
Scope-risk: narrow
Tested: python -m pytest tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py -q
Not-tested: real provider endpoints
"
```

---

## Phase 1: Build Core Voice Package and Contracts

Purpose: create the reusable provider domain without changing video/article behavior yet.

Files:

- Add: `monitor/voice/__init__.py`
- Add: `monitor/voice/capabilities.py`
- Add: `monitor/voice/schemas.py`
- Add: `monitor/voice/providers.py`
- Modify: `tests/test_voice_provider_contract.py`

Implementation details:

- [ ] Define capability constants in `monitor/voice/capabilities.py`:
  - `SPEECH_SYNTHESIS = "speech_synthesis"`
  - `TRANSCRIPTION = "transcription"`
  - `STREAMING_SYNTHESIS = "streaming_synthesis"`
  - `VOICE_DESIGN = "voice_design"`
  - `REFERENCE_CLONE = "reference_clone"`
  - `PROMPT_TRANSCRIPT_CLONE = "prompt_transcript_clone"`
  - `SSML = "ssml"`
  - `VOICE_LIST = "voice_list"`
- [ ] Define stable provider ids and aliases:
  - `silent`, `edge_tts`, `local_http_tts`, `openai_speech`, `azure_speech`, `minimax_speech`, `voxcpm_http`, `voxcpm_openai_speech`, `vibevoice_tts`, `vibevoice_realtime`, `whisper_local`, `whisper_api`, `vibevoice_asr`, `vibevoice_vllm_asr`
- [ ] Create `SpeechSynthesisRequest` dataclass with text, output directory, flow, provider, mode, voice, language, model, response format, speed, pitch, volume, style, control instruction, reference audio path, prompt text, streaming, source, source task id, and `metadata`.
- [ ] Create `SpeechSynthesisResult` dataclass with provider, path, mime type, duration, sample rate, metadata path, and raw metadata.
- [ ] Create `TranscriptSegment`, `TranscriptionRequest`, and `TranscriptionResult` dataclasses.
- [ ] Create `ProviderInfo` dataclass with provider id, label, capabilities, configured flag, fields, modes, safety flags, and sort order.
- [ ] Define `SpeechSynthesisProvider` and `TranscriptionProvider` protocols in `monitor/voice/providers.py`.
- [ ] Implement `VoiceProviderRegistry` with register, list, get, capability filtering, and alias normalization.
- [ ] Export stable facade names from `monitor/voice/__init__.py`.

Provider contract sketch:

```python
class SpeechSynthesisProvider(Protocol):
    provider_id: str

    def info(self) -> ProviderInfo:
        raise NotImplementedError

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def synthesize(self, request: SpeechSynthesisRequest, cfg: Mapping[str, Any]) -> SpeechSynthesisResult:
        raise NotImplementedError
```

Verification:

```powershell
python -m pytest tests/test_voice_provider_contract.py -q
```

Commit after Phase 1:

```powershell
git add monitor/voice tests/test_voice_provider_contract.py
git commit -m "Create voice provider contracts

Voice capabilities are split into synthesis and transcription so future providers can register only the functions they support.

Constraint: The provider domain must support Edge, local HTTP, OpenAI, Azure, MiniMax, VoxCPM, VibeVoice, and Whisper without workflow-specific imports.
Rejected: A single broad VoiceProvider interface | it would force ASR-only and TTS-only providers to expose unrelated methods.
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_provider_contract.py -q
Not-tested: video pipeline migration
"
```

---

## Phase 2: Implement Flow-Aware Provider Selection

Purpose: enable dynamic provider choice by task, flow, capability, and fallback policy.

Files:

- Add: `monitor/voice/selection.py`
- Modify: `monitor/voice/__init__.py`
- Modify: `tests/test_voice_selection_contract.py`

Implementation details:

- [ ] Create `ProviderSelectionRequest` with capability, flow, mode, requested provider, fallback allowed, and options.
- [ ] Create `ProviderSelectionResult` with provider id, capability, flow, mode, fallback chain, effective options, and reason.
- [ ] Implement config parsing for:
  - `voice_provider`
  - `voice_fallback_order`
  - `voice_flow_defaults_json`
  - legacy `tts_provider`
  - legacy `tts_workflow`
  - legacy `whisper_provider`
- [ ] Implement precedence:
  1. Task-level explicit provider from `requested_provider`.
  2. Flow-level default from `voice_flow_defaults_json`.
  3. Capability-level default from `voice_provider` or legacy fields.
  4. Capability fallback order.
  5. Failure with a clear provider/capability message.
- [ ] Preserve explicit-provider behavior: an explicit real provider must fail if unavailable unless request fallback is allowed.
- [ ] Treat `silent` as always configured for `speech_synthesis`.
- [ ] Treat `edge_tts` as configured when command or module is discoverable; command discovery may use `shutil.which("edge-tts")`.
- [ ] Treat `local_http_tts` as configured when `local_tts_url` is non-empty.
- [ ] Leave OpenAI/Azure/MiniMax/VoxCPM/VibeVoice configured checks in their provider classes once added.

Example flow defaults:

```json
{
  "video_generation.speech_synthesis": "edge_tts",
  "manual_voice.speech_synthesis": "openai_speech",
  "article_generation.transcription": "whisper_api",
  "clip_pipeline.transcription": "whisper_local"
}
```

Verification:

```powershell
python -m pytest tests/test_voice_selection_contract.py -q
```

Commit after Phase 2:

```powershell
git add monitor/voice/selection.py monitor/voice/__init__.py tests/test_voice_selection_contract.py
git commit -m "Route voice providers through flow-aware selection

Provider selection now has one policy boundary for task overrides, flow defaults, capability defaults, aliases, and fallback.

Constraint: Workflows need per-task dynamic provider choices without branching on concrete provider classes.
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_selection_contract.py -q
Not-tested: real video narration call path
"
```

---

## Phase 3: Add Storage and Safety Helpers

Purpose: normalize file materialization, metadata, path safety, text length gates, and clone gates before providers write outputs.

Files:

- Add: `monitor/voice/storage.py`
- Add: `monitor/voice/safety.py`
- Add: `tests/test_voice_storage.py`
- Add: `tests/test_voice_safety.py`

Implementation details:

- [ ] Implement `resolve_voice_output_root(cfg)` using `voice_output_dir`, defaulting to `data/voice`.
- [ ] Implement deterministic task output directories under `voice_output_dir`.
- [ ] Implement `safe_output_path(root, relative_or_name)` that rejects path traversal and absolute paths outside the root.
- [ ] Implement `write_metadata(output_dir, metadata)` with ISO timestamp and no secret values.
- [ ] Implement `write_audio_bytes(output_dir, output_name, bytes, response_format)` with extension inference.
- [ ] Implement `write_silent_wav(path, duration_sec=1.0, sample_rate=16000)` to replace duplicated silent WAV logic later.
- [ ] Implement `hash_text(text)` and `hash_file(path)` helpers.
- [ ] Enforce `voice_max_text_chars` in `safety.py`.
- [ ] Enforce `voice_allow_reference_clone` and `voice_allow_prompt_transcript_clone`.
- [ ] Ensure `metadata.json` always includes `ai_generated`, provider, capability, source, source task id, disclosure required, and input text hash.

Verification:

```powershell
python -m pytest tests/test_voice_storage.py tests/test_voice_safety.py -q
```

Commit after Phase 3:

```powershell
git add monitor/voice/storage.py monitor/voice/safety.py tests/test_voice_storage.py tests/test_voice_safety.py
git commit -m "Centralize voice output storage and safety checks

Generated speech and transcripts now have one path-safe storage policy and one metadata policy.

Constraint: Generated voice files must stay inside configured output roots and record AI-generated disclosure metadata.
Rejected: Let each provider write arbitrary output paths | it would duplicate path validation and metadata rules.
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_storage.py tests/test_voice_safety.py -q
Not-tested: server file-serving route
"
```

---

## Phase 4: Implement Local Synthesis Providers

Purpose: implement the providers needed to replace the current video narration function without network credentials.

Files:

- Add: `monitor/voice/synthesis.py`
- Modify: `monitor/voice/__init__.py`
- Modify: `tests/test_voice_provider_contract.py`
- Modify: `tests/test_ai_content_provider_pipeline_contract.py`

Providers:

- `SilentSpeechProvider`
- `EdgeTtsSpeechProvider`
- `LocalHttpTtsProvider`

Implementation details:

- [ ] Register all three providers through `build_synthesis_registry(cfg)` or `get_default_voice_registry(cfg)`.
- [ ] `SilentSpeechProvider` writes a WAV with `storage.write_silent_wav()` and metadata.
- [ ] `EdgeTtsSpeechProvider` runs `edge-tts --text <text> --write-media <output.mp3>` via `subprocess.run()` with an argument list, not a shell string.
- [ ] If Edge output is MP3, return `mime_type="audio/mpeg"` and let existing duration probing handle the file.
- [ ] `LocalHttpTtsProvider` POSTs JSON to `local_tts_url`, accepts raw audio responses, and accepts JSON responses containing a file URL/path when safely retrievable.
- [ ] Preserve existing current local HTTP contract: JSON contains at least text, output path, and provider-compatible fields.
- [ ] Raise a clear error when configured local HTTP TTS fails; do not let this provider call silent fallback.
- [ ] Mock `subprocess.run` in Edge tests.
- [ ] Mock `urllib.request.urlopen` or the selected stdlib HTTP function in local HTTP tests.

Facade:

- [ ] Add `synthesize_speech(request, cfg, registry=None)` to `monitor/voice/__init__.py` or `monitor/voice/synthesis.py`.
- [ ] The facade must call provider selection, then one provider, then return `SpeechSynthesisResult`.
- [ ] A separate `synthesize_speech_with_fallback(request, cfg, selection_request)` may iterate fallback providers only through `selection.py` results.

Verification:

```powershell
python -m pytest tests/test_voice_provider_contract.py tests/test_ai_content_provider_pipeline_contract.py -q
```

Commit after Phase 4:

```powershell
git add monitor/voice/synthesis.py monitor/voice/__init__.py tests/test_voice_provider_contract.py tests/test_ai_content_provider_pipeline_contract.py
git commit -m "Implement local voice synthesis providers

Silent, Edge TTS, and local HTTP TTS now live behind the shared synthesis facade used by future workflows.

Constraint: Existing explicit local TTS failures must stay visible instead of falling through to silent audio.
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_provider_contract.py tests/test_ai_content_provider_pipeline_contract.py -q
Not-tested: real edge-tts command on this machine
"
```

---

## Phase 5: Migrate Video Narration to the Voice Facade

Purpose: remove provider-specific branching from `scripts/video_gen_pipeline.py` while preserving video generation behavior.

Files:

- Modify: `scripts/video_gen_pipeline.py`
- Add: `tests/test_video_gen_voice_provider.py`
- Modify: `tests/test_ai_content_provider_pipeline_contract.py`

Implementation details:

- [ ] Replace `_synthesize_narration()` provider branching with construction of `SpeechSynthesisRequest`.
- [ ] Pass `flow="video_generation"` and `source="video_generation"`.
- [ ] Pass `source_task_id=task.get("task_id")` when available.
- [ ] Use `task.get("tts_workflow")` as `requested_provider`.
- [ ] Keep the method signature and return tuple compatible: `(audio_path, audio_provider, audio_duration)`.
- [ ] Keep `_probe_audio_duration()` as the duration source.
- [ ] Keep storyboard text extraction unchanged.
- [ ] Keep final result JSON key `tts_provider` for compatibility, and add `voice_provider` plus `voice_metadata_path` if available.
- [ ] Add a fake provider test where the video pipeline receives a generated audio path through the facade.
- [ ] Add regression coverage for Edge/local/silent aliases from existing task payloads.

Verification:

```powershell
python -m pytest tests/test_video_gen_voice_provider.py tests/test_ai_content_provider_pipeline_contract.py -q
```

Commit after Phase 5:

```powershell
git add scripts/video_gen_pipeline.py tests/test_video_gen_voice_provider.py tests/test_ai_content_provider_pipeline_contract.py
git commit -m "Use the voice facade for video narration

Video generation now asks for speech synthesis by flow and task provider override instead of branching on provider names.

Constraint: Rendering and storyboard behavior must remain unchanged during the provider migration.
Confidence: high
Scope-risk: moderate
Tested: python -m pytest tests/test_video_gen_voice_provider.py tests/test_ai_content_provider_pipeline_contract.py -q
Not-tested: full video render with real provider audio
"
```

---

## Phase 6: Add Unified Voice Config and Secret Handling

Purpose: expose global defaults, provider credentials, and safety gates without removing legacy fields.

Files:

- Modify: `config/settings.py`
- Modify: `server/__main__.py`
- Modify: `frontend-vue/src/api/config.ts`
- Modify: `frontend-vue/src/views/settings/AiSettings.vue`
- Modify: `tests/test_ai_content_config_masking_contract.py`
- Modify: `tests/test_sensitive_secret_masking.py`
- Modify: `tests/test_ai_settings_secret_masking.py`
- Add: `tests/test_voice_config.py`

Config keys to add:

- `voice_provider`
- `voice_fallback_order`
- `voice_flow_defaults_json`
- `voice_output_dir`
- `voice_require_disclosure`
- `voice_allow_reference_clone`
- `voice_allow_prompt_transcript_clone`
- `voice_max_text_chars`
- `openai_speech_base_url`
- `openai_speech_api_key`
- `openai_speech_model`
- `openai_speech_voice`
- `azure_speech_region`
- `azure_speech_endpoint`
- `azure_speech_api_key`
- `azure_speech_voice`
- `azure_speech_output_format`
- `minimax_speech_base_url`
- `minimax_speech_api_key`
- `minimax_speech_model`
- `minimax_speech_voice`
- `voxcpm_base_url`
- `voxcpm_api_key`
- `voxcpm_model`
- `voxcpm_default_voice`
- `voxcpm_default_control_instruction`
- `vibevoice_tts_base_url`
- `vibevoice_tts_api_key`
- `vibevoice_tts_model`
- `vibevoice_tts_voice`
- `vibevoice_asr_base_url`
- `vibevoice_asr_api_key`
- `vibevoice_asr_model`

Secret keys to add to `_SECRET_CONFIG_KEYS`:

- `openai_speech_api_key`
- `azure_speech_api_key`
- `minimax_speech_api_key`
- `voxcpm_api_key`
- `vibevoice_tts_api_key`
- `vibevoice_asr_api_key`

Implementation details:

- [ ] Preserve existing `tts_provider` and `local_tts_url`; they remain compatibility aliases.
- [ ] Extend `_api_config_save` allowlist in `server/__main__.py`.
- [ ] Preserve masked secret values on save for all new secret keys.
- [ ] Validate provider defaults through alias normalization.
- [ ] Validate `voice_flow_defaults_json` parses as an object whose keys are `flow.capability` strings and values are provider ids or aliases.
- [ ] Validate URL fields use `http://` or `https://` when non-empty.
- [ ] Reject URLs with embedded username/password.
- [ ] Add frontend TypeScript fields in `frontend-vue/src/api/config.ts`.
- [ ] In `AiSettings.vue`, add a compact "Voice Provider" section with global provider, fallback order, flow defaults JSON, output dir, and safety toggles.
- [ ] Keep provider credentials in an advanced credentials section.

Verification:

```powershell
python -m pytest tests/test_voice_config.py tests/test_ai_content_config_masking_contract.py tests/test_sensitive_secret_masking.py tests/test_ai_settings_secret_masking.py -q
cd frontend-vue
npm run build
```

Commit after Phase 6:

```powershell
git add config/settings.py server/__main__.py frontend-vue/src/api/config.ts frontend-vue/src/views/settings/AiSettings.vue tests/test_voice_config.py tests/test_ai_content_config_masking_contract.py tests/test_sensitive_secret_masking.py tests/test_ai_settings_secret_masking.py
git commit -m "Expose unified voice provider configuration

The app can now store flow defaults, fallback order, provider credentials, and voice safety gates without replacing legacy TTS settings.

Constraint: Existing masked secret preservation must apply to every new provider API key.
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_config.py tests/test_ai_content_config_masking_contract.py tests/test_sensitive_secret_masking.py tests/test_ai_settings_secret_masking.py -q; cd frontend-vue; npm run build
Not-tested: manual settings save in browser
"
```

---

## Phase 7: Add Provider Discovery and Environment APIs

Purpose: let UI and workflows discover configured providers and run safe environment checks.

Files:

- Add: `monitor/voice/env.py`
- Modify: `server/__main__.py`
- Add: `tests/test_voice_env.py`
- Add: `tests/test_voice_api_contract.py`

API routes:

- `GET /api/voice/providers`
- `GET /api/voice/providers?capability=speech_synthesis&flow=video_generation`
- `GET /api/voice/env`
- `POST /api/voice/env/check`
- `POST /api/voice/smoke-test`

Implementation details:

- [ ] `GET /api/voice/providers` returns provider id, label, capabilities, configured flag, modes, fields, safety flags, and config reason.
- [ ] Provider list must be capability-filterable and flow-aware.
- [ ] Environment check is read-only: Python, OS, ffmpeg, ffprobe, Docker CLI/daemon, nvidia-smi, torch, CUDA availability, relevant optional package presence, disk free space, and remote provider base URL health.
- [ ] Environment check must not install packages, download models, start Docker, or contact paid synthesis endpoints.
- [ ] `POST /api/voice/smoke-test` accepts a short text and provider id; it runs only when explicitly invoked.
- [ ] Smoke test length limit should be lower than normal synthesis, for example 300 characters.
- [ ] Errors returned to UI must not include secret values.

Verification:

```powershell
python -m pytest tests/test_voice_env.py tests/test_voice_api_contract.py -q
```

Commit after Phase 7:

```powershell
git add monitor/voice/env.py server/__main__.py tests/test_voice_env.py tests/test_voice_api_contract.py
git commit -m "Publish voice provider discovery and environment checks

The frontend can now discover providers by capability and flow, and users can inspect local readiness without triggering model installs or paid synthesis.

Constraint: Environment checks are diagnostic only and must be free of side effects.
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_env.py tests/test_voice_api_contract.py -q
Not-tested: browser rendering of provider list
"
```

---

## Phase 8: Add External TTS Provider Adapters

Purpose: implement OpenAI, Azure, MiniMax, VoxCPM, and VibeVoice as provider adapters without changing workflow code.

Files:

- Modify: `monitor/voice/synthesis.py`
- Add: `tests/test_voice_external_synthesis_providers.py`
- Add: `tests/test_voice_provider_payloads.py`

Provider implementation order:

1. `openai_speech`
2. `azure_speech`
3. `minimax_speech`
4. `voxcpm_openai_speech`
5. `voxcpm_http`
6. `vibevoice_tts`
7. `vibevoice_realtime` as an external HTTP service adapter only

OpenAI details:

- [ ] Use `openai_speech_base_url`, defaulting to `https://api.openai.com/v1`.
- [ ] POST to `/audio/speech`.
- [ ] Request fields: `model`, `input`, `voice`, `response_format`, `speed`, and `instructions` when `control_instruction` is present.
- [ ] Default model from config should be `gpt-4o-mini-tts`.
- [ ] Default voice from config should be `alloy` unless the user sets another voice.
- [ ] Support output formats documented by OpenAI: `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm`.
- [ ] Do not use the OpenAI SDK.

Azure details:

- [ ] Use `azure_speech_endpoint` when set; otherwise derive from `azure_speech_region` as `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`.
- [ ] POST SSML to the REST TTS endpoint.
- [ ] Use `Ocp-Apim-Subscription-Key` for API key auth.
- [ ] Use `X-Microsoft-OutputFormat` from `azure_speech_output_format`.
- [ ] Map basic request fields to SSML voice, language, style, rate/speed, pitch, and volume where supported.
- [ ] Escape user text before embedding in SSML.

MiniMax details:

- [ ] Use `minimax_speech_base_url`, defaulting to `https://api.minimax.io`.
- [ ] Support synchronous HTTP T2A first.
- [ ] Request fields should include model, text, voice id, speed, pitch, volume, and output format where supported by the MiniMax HTTP T2A docs.
- [ ] Normalize response variants into local audio bytes: direct audio, hex-encoded audio, URL/file references, or provider JSON with nested data.
- [ ] Add provider metadata for `input_sensitive` and response status fields when present.
- [ ] Implement voice design and voice clone only as modes guarded by safety config; basic TTS must work without those modes.

VoxCPM details:

- [ ] `voxcpm_openai_speech` uses OpenAI-compatible `/audio/speech` shape for basic TTS.
- [ ] `voxcpm_http` uses a generic external service contract:

```json
{
  "text": "short narration",
  "voice": "default",
  "model": "openbmb/VoxCPM2",
  "mode": "voice_design",
  "control_instruction": "clear young tech explainer",
  "reference_audio_path": "",
  "prompt_text": "",
  "response_format": "wav",
  "normalize_text": true,
  "denoise_reference": false
}
```

- [ ] The generic service may return raw audio, JSON with base64/hex audio, or JSON with a downloadable URL.
- [ ] Reference audio and prompt transcript modes must be rejected unless config gates are enabled.

VibeVoice details:

- [ ] `vibevoice_tts` uses a generic HTTP service contract similar to `local_http_tts`, with explicit model and voice fields.
- [ ] `vibevoice_realtime` is represented as a provider capability but should not require websocket dependencies in the base app.
- [ ] If direct WebSocket support becomes necessary, add a separate worker/service plan rather than adding a base dependency.

Verification:

```powershell
python -m pytest tests/test_voice_external_synthesis_providers.py tests/test_voice_provider_payloads.py tests/test_voice_provider_contract.py -q
```

Commit after Phase 8:

```powershell
git add monitor/voice/synthesis.py tests/test_voice_external_synthesis_providers.py tests/test_voice_provider_payloads.py tests/test_voice_provider_contract.py
git commit -m "Add external speech synthesis adapters

OpenAI, Azure, MiniMax, VoxCPM, and VibeVoice can now be selected through the same synthesis contract.

Constraint: Base application dependencies must remain lightweight; providers use HTTP adapters instead of SDK imports.
Rejected: Provider-specific workflow branches | they would couple video and manual voice flows to concrete APIs.
Confidence: medium
Scope-risk: broad
Tested: python -m pytest tests/test_voice_external_synthesis_providers.py tests/test_voice_provider_payloads.py tests/test_voice_provider_contract.py -q
Not-tested: paid provider endpoints
"
```

---

## Phase 9: Add Voice Task Table and Task Service

Purpose: support manual voice workspace history, long-running synthesis, future transcription, cancellation, and output links.

Files:

- Modify: `monitor/schema.sql`
- Modify: `monitor/db.py`
- Add: `monitor/voice/tasks.py`
- Modify: `server/__main__.py`
- Add: `tests/test_voice_tasks_schema.py`
- Add: `tests/test_voice_tasks_api.py`

Database schema:

```sql
CREATE TABLE IF NOT EXISTS voice_tasks (
    task_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    capability TEXT NOT NULL,
    mode TEXT,
    source TEXT,
    source_task_id TEXT,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT,
    message TEXT,
    input_text_hash TEXT,
    input_path TEXT,
    output_audio_path TEXT,
    output_text_path TEXT,
    output_srt_path TEXT,
    metadata_path TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    cancel_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
```

API routes:

- `POST /api/voice/synthesis/tasks`
- `POST /api/voice/transcription/tasks`
- `GET /api/voice/tasks`
- `GET /api/voice/tasks/{task_id}`
- `POST /api/voice/tasks/{task_id}/cancel`
- `GET /api/voice/file?path=data/voice/voice_xxx/output.wav`

Implementation details:

- [ ] Add schema bootstrap and migration logic for `voice_tasks`.
- [ ] Add db helpers: create, update, get, list, mark cancel requested.
- [ ] Implement `VoiceTaskManager` with background thread execution for synthesis.
- [ ] Store only text hash in table; full request text may live in `input.json` inside the task directory if needed.
- [ ] Keep output file serving restricted to `voice_output_dir`, `video_gen_output_dir`, and `article_output_dir` as needed.
- [ ] Create tasks for manual synthesis first.
- [ ] Link video-generated voice metadata through `video_gen_tasks.result_json` rather than adding a `voice_task_id` column immediately.
- [ ] Use fake providers in task lifecycle tests.

Verification:

```powershell
python -m pytest tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_ai_content_workflow_schema_contract.py -q
```

Commit after Phase 9:

```powershell
git add monitor/schema.sql monitor/db.py monitor/voice/tasks.py server/__main__.py tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_ai_content_workflow_schema_contract.py
git commit -m "Add voice task persistence and task APIs

Manual synthesis and future transcription tasks now have durable status, output paths, cancellation, and metadata.

Constraint: Voice task storage must be additive and must not alter existing video or article task contracts.
Confidence: medium
Scope-risk: broad
Tested: python -m pytest tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_ai_content_workflow_schema_contract.py -q
Not-tested: long-running real provider cancellation
"
```

---

## Phase 10: Add Frontend Provider Selection and Manual Voice UI

Purpose: replace hard-coded/free-text provider input with capability-driven provider choice and add a manual voice page.

Files:

- Add: `frontend-vue/src/api/voice.ts`
- Add: `frontend-vue/src/views/AiVoice.vue`
- Modify: `frontend-vue/src/views/AiCreation.vue`
- Modify: `frontend-vue/src/views/settings/AiSettings.vue`
- Modify: `frontend-vue/src/router/index.ts`
- Modify: `frontend-vue/src/components/layout/AppSider.vue`
- Modify: `frontend-vue/src/views/SettingsHub.vue`
- Modify: `frontend-vue/src/i18n.ts`
- Add or modify frontend contract tests under `tests/`

Implementation details:

- [ ] Create `frontend-vue/src/api/voice.ts` for provider list, env check, smoke test, task create/list/detail/cancel, and file URLs.
- [ ] In `AiCreation.vue`, replace the free-text `tts_workflow` input with an `NSelect` populated by `/api/voice/providers?capability=speech_synthesis&flow=video_generation`.
- [ ] Preserve a hidden/raw advanced override field only if needed for compatibility during migration.
- [ ] Include provider advanced fields based on provider `fields` and `modes`.
- [ ] Add `AiVoice.vue` for manual synthesis:
  - text input
  - flow selector defaulting to `manual_voice`
  - provider selector
  - voice/language/format/speed basics
  - advanced control instruction
  - clone controls hidden until enabled
  - generated audio player
  - recent tasks table
- [ ] Add environment status card and "Run check" button.
- [ ] Add disclosure notice for AI-generated speech.
- [ ] Add route `/ai-voice`.
- [ ] Add sidebar entry `AI 语音`.
- [ ] Keep mobile layout single-column and desktop layout two-column.
- [ ] Ensure labels, loading states, disabled states, and error states are visible.

Verification:

```powershell
cd frontend-vue
npm run build
python -m pytest tests/test_ai_content_frontend_contract.py tests/test_i18n_en_referenced_keys_exist.py -q
```

Manual browser verification:

- Start the server.
- Open `http://127.0.0.1:5000/#/ai-voice`.
- Open `http://127.0.0.1:5000/#/ai-creation`.
- Check widths 375px, 768px, 1024px, and 1440px.
- Confirm provider select loads when backend is available.
- Confirm no horizontal scroll.
- Confirm generated speech disclosure is visible.

Commit after Phase 10:

```powershell
git add frontend-vue/src/api/voice.ts frontend-vue/src/views/AiVoice.vue frontend-vue/src/views/AiCreation.vue frontend-vue/src/views/settings/AiSettings.vue frontend-vue/src/router/index.ts frontend-vue/src/components/layout/AppSider.vue frontend-vue/src/views/SettingsHub.vue frontend-vue/src/i18n.ts tests/test_ai_content_frontend_contract.py tests/test_i18n_en_referenced_keys_exist.py
git commit -m "Expose dynamic voice provider selection in the UI

Users can select providers per video task and run manual synthesis through provider metadata instead of free-text workflow names.

Constraint: UI must stay capability-driven so future providers can appear without workflow-specific form rewrites.
Confidence: medium
Scope-risk: broad
Tested: cd frontend-vue; npm run build; python -m pytest tests/test_ai_content_frontend_contract.py tests/test_i18n_en_referenced_keys_exist.py -q
Not-tested: browser smoke test with real provider audio
"
```

---

## Phase 11: Add Transcription Provider Foundation

Purpose: prepare ASR providers without forcing ASR concepts into TTS providers.

Files:

- Add: `monitor/voice/transcription.py`
- Modify: `monitor/voice/__init__.py`
- Add: `tests/test_voice_transcription_contract.py`
- Add: `tests/test_article_transcription_provider_selection.py`

Providers:

- `whisper_local`
- `whisper_api`
- `vibevoice_asr`
- `vibevoice_vllm_asr`

Implementation details:

- [ ] Implement transcription provider protocols and registry using the same `ProviderInfo` model.
- [ ] Wrap current remote Whisper-compatible API behavior as `whisper_api`.
- [ ] Wrap current local faster-whisper branch as `whisper_local` without changing its output contract.
- [ ] Add `vibevoice_asr` generic HTTP adapter with hotwords and language hint.
- [ ] Add `vibevoice_vllm_asr` adapter for OpenAI-compatible chat/completions or transcription-like VibeVoice vLLM service responses, based on configured service contract.
- [ ] Normalize all output to `TranscriptionResult` with text, language, segments, transcript path, SRT path, raw path, and raw metadata.
- [ ] Use fake HTTP and fake local transcriber tests.
- [ ] Keep article generation unchanged until Phase 12.

Verification:

```powershell
python -m pytest tests/test_voice_transcription_contract.py tests/test_article_transcription_provider_selection.py -q
```

Commit after Phase 11:

```powershell
git add monitor/voice/transcription.py monitor/voice/__init__.py tests/test_voice_transcription_contract.py tests/test_article_transcription_provider_selection.py
git commit -m "Add transcription provider foundation

Whisper and VibeVoice ASR can now share the voice domain without expanding the speech synthesis interface.

Constraint: ASR must be a separate capability from TTS to avoid provider contracts that are too broad.
Confidence: medium
Scope-risk: moderate
Tested: python -m pytest tests/test_voice_transcription_contract.py tests/test_article_transcription_provider_selection.py -q
Not-tested: article pipeline integration
"
```

---

## Phase 12: Integrate Article ASR Through Provider Selection

Purpose: let article generation dynamically choose Whisper or VibeVoice ASR while preserving subtitle-first behavior.

Files:

- Modify: `scripts/article_generator.py`
- Modify: `tests/test_ai_content_provider_pipeline_contract.py`
- Add: `tests/test_article_generator_voice_transcription.py`

Implementation details:

- [ ] Keep current order: local subtitle, remote subtitle, ASR fallback, LLM processing.
- [ ] Replace only the ASR fallback branch with `TranscriptionRequest` and `ProviderSelectionRequest(flow="article_generation", capability="transcription")`.
- [ ] Use existing `whisper_provider` as compatibility default when `voice_flow_defaults_json` does not specify article transcription.
- [ ] Preserve current transcript text passed into article drafting.
- [ ] Store normalized metadata path in article task stage JSON when available.
- [ ] Add tests where `article_generation.transcription` selects `whisper_api`.
- [ ] Add tests where a task or config selects `vibevoice_asr`.
- [ ] Add tests where VibeVoice ASR failure falls back only when policy allows it.

Verification:

```powershell
python -m pytest tests/test_article_generator_voice_transcription.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py -q
```

Commit after Phase 12:

```powershell
git add scripts/article_generator.py tests/test_article_generator_voice_transcription.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py
git commit -m "Route article ASR through voice providers

Article generation keeps subtitle-first behavior while moving ASR fallback selection behind the shared transcription capability.

Constraint: Existing Whisper local and API behavior must remain the default until flow defaults are explicitly changed.
Confidence: medium
Scope-risk: broad
Tested: python -m pytest tests/test_article_generator_voice_transcription.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py -q
Not-tested: real VibeVoice ASR service
"
```

---

## Phase 13: Documentation and Manual Verification

Purpose: document provider configuration, dynamic selection, safety gates, and real-world smoke tests.

Files:

- Add: `docs/voice-provider-architecture.md`
- Add: `docs/voice-provider-external-services.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-06-voice-provider-architecture-design.md` only if implementation decisions changed the architecture

Documentation contents:

- [ ] Provider matrix and capabilities.
- [ ] Flow default examples for video generation, manual voice, article generation, and clip pipeline.
- [ ] OpenAI setup: API key, base URL, model, voice, response format.
- [ ] Azure setup: region/endpoint, API key, voice, output format, SSML behavior.
- [ ] MiniMax setup: API key, model, voice, synchronous HTTP T2A, clone/design gates.
- [ ] Edge TTS setup: command availability and current CLI behavior.
- [ ] VoxCPM setup: external HTTP contract and OpenAI-compatible speech fallback.
- [ ] VibeVoice setup: ASR service contract and TTS service contract.
- [ ] Safety rules for reference audio and disclosure.
- [ ] Troubleshooting: missing `edge-tts`, unreachable service, invalid API key, unsupported provider mode, unsafe output path, long text limit.
- [ ] Manual verification recipes.

Manual verification:

- [ ] `voice_provider=edge_tts`, video generation creates narration using Edge when command is available.
- [ ] `tts_workflow=silent`, video generation completes with silent WAV.
- [ ] `local_tts_url` configured to invalid URL, explicit local task fails visibly.
- [ ] `openai_speech` smoke test with a short text if an API key is available.
- [ ] `azure_speech` smoke test if Azure Speech credentials are available.
- [ ] `minimax_speech` smoke test if MiniMax credentials are available.
- [ ] `voxcpm_http` smoke test against a local/remote service if available.
- [ ] `vibevoice_asr` smoke test against a local/remote service if available.

Full automated verification:

```powershell
python -m pytest tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py tests/test_voice_storage.py tests/test_voice_safety.py tests/test_voice_external_synthesis_providers.py tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_video_gen_voice_provider.py tests/test_article_generator_voice_transcription.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py -q
cd frontend-vue
npm run build
```

Commit after Phase 13:

```powershell
git add docs/voice-provider-architecture.md docs/voice-provider-external-services.md README.md docs/superpowers/specs/2026-06-06-voice-provider-architecture-design.md
git commit -m "Document unified voice provider operation

The provider architecture, flow defaults, external service contracts, and safety controls are now documented for users and future implementers.

Constraint: Real provider credentials and large-model services are optional, so docs must separate mocked automated verification from manual endpoint smoke tests.
Confidence: medium
Scope-risk: narrow
Tested: python -m pytest tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py tests/test_voice_storage.py tests/test_voice_safety.py tests/test_voice_external_synthesis_providers.py tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_video_gen_voice_provider.py tests/test_article_generator_voice_transcription.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py -q; cd frontend-vue; npm run build
Not-tested: all paid provider endpoints
"
```

---

## Final Acceptance Criteria

- [ ] Existing Edge/local/silent video TTS behavior is preserved through aliases and regression tests.
- [ ] `scripts/video_gen_pipeline.py` no longer branches on concrete voice provider implementation details.
- [ ] Provider selection supports task-level override, flow defaults, capability defaults, fallback order, and explicit-provider failure policy.
- [ ] `GET /api/voice/providers` returns capability-filtered provider metadata for frontend dynamic forms.
- [ ] New provider API keys are encrypted/masked and masked values are preserved on save.
- [ ] OpenAI, Azure, MiniMax, VoxCPM, VibeVoice, Edge, local HTTP, and silent TTS all register under one synthesis capability.
- [ ] Whisper and VibeVoice ASR register under one transcription capability.
- [ ] Reference clone and prompt-transcript clone are disabled by default and enforced server-side.
- [ ] Every generated audio output has local file materialization and `metadata.json`.
- [ ] Voice task storage is additive and does not break `article_tasks` or `video_gen_tasks`.
- [ ] Frontend can dynamically choose providers for video generation and manual voice tasks.
- [ ] Automated tests do not require real paid APIs, Edge network access, local GPU, VibeVoice, VoxCPM, or vLLM.

---

## Recommended Execution Strategy

Use **Subagent-Driven Development** for implementation because the work has independent lanes:

- Agent A: provider contracts, selection, storage, safety, local providers.
- Agent B: config/API/db/task service.
- Agent C: frontend provider selection and manual voice UI.
- Agent D: external provider adapters with mocked HTTP tests.
- Agent E: transcription provider and article integration.

Run integration verification in the main thread after each phase. Keep commits phase-sized and use the Lore commit protocol shown above.

Inline execution is also viable for Phases 0-5 if you want the smallest initial migration before adding the API/UI/manual task surface.

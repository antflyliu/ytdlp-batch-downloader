# Unified Voice Provider Architecture Design

## 1. Executive Summary

The current VibeVoice and VoxCPM drafts are directionally compatible, but they should not land as two independent vertical modules. VibeVoice currently proposes `monitor/vibevoice`, while VoxCPM already moves toward `monitor/voice`. The right architecture is a unified `monitor/voice` domain with separate capability interfaces:

- `SpeechSynthesisProvider` for TTS and voice generation.
- `TranscriptionProvider` for ASR and transcript generation.

TTS should be the first implementation surface because it directly replaces the current hard-coded narration path in `scripts/video_gen_pipeline.py`. ASR should be designed in the same domain, but implemented later as a provider replacement for the existing Whisper branch in `scripts/article_generator.py`.

This keeps Edge TTS, Azure Speech, OpenAI Audio Speech, MiniMax, VoxCPM, and VibeVoice TTS on one extension path, while still allowing VibeVoice ASR to join without forcing ASR-specific concepts into every TTS provider.

## 2. Inputs Reviewed

This design synthesizes:

- `docs/superpowers/specs/2026-06-06-vibevoice-integration-feasibility-design.md`
- `docs/superpowers/plans/2026-06-06-vibevoice-integration-plan.md`
- `docs/superpowers/specs/2026-06-06-voxcpm-integration-feasibility-design.md`
- `docs/superpowers/plans/2026-06-06-voxcpm-integration-plan.md`
- Current code in `scripts/video_gen_pipeline.py`, `scripts/article_generator.py`, `scripts/image_generation.py`, `config/settings.py`, `server/__main__.py`, and `frontend-vue/src/views/settings/AiSettings.vue`
- Provider patterns already used by image generation, LLM clients, dynamic proxy adapters, and WeChat collection providers.

External API shape was checked against current official/project documentation:

- OpenAI Text to Speech: https://platform.openai.com/docs/guides/text-to-speech
- Azure Speech REST Text to Speech: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech
- MiniMax API overview and voice cloning docs: https://platform.minimax.io/docs/api-reference/api-overview and https://platform.minimax.io/docs/api-reference/voice-cloning-clone
- Edge TTS project README: https://github.com/rany2/edge-tts/blob/master/README.md

## 3. Current State

### 3.1 Existing TTS Surface

The current TTS implementation is embedded in `scripts/video_gen_pipeline.py`:

```text
VideoGenerationPipeline._synthesize_narration()
-> edge-tts shell command when provider starts with "edge"
-> local HTTP TTS when local_tts_url is configured
-> silent WAV fallback when no usable provider exists
```

Global config only has:

```text
tts_provider
local_tts_url
```

Per video task config only has:

```text
video_gen_tasks.tts_workflow
```

The pipeline intentionally does not silently replace a configured failing local TTS provider. Existing tests lock this behavior.

### 3.2 Existing ASR Surface

ASR is not modeled as a provider layer yet. `scripts/article_generator.py` currently uses subtitle-first behavior and falls back to Whisper-compatible ASR based on:

```text
whisper_provider
whisper_base_url
whisper_api_key
whisper_model
whisper_device
whisper_compute_type
whisper_language
```

VibeVoice ASR should become a `TranscriptionProvider`, not a special article pipeline fork.

### 3.3 Existing Provider Patterns Worth Reusing

`scripts/image_generation.py` is the closest implementation pattern:

- Request/result dataclasses.
- Small provider base class.
- Provider factory.
- Provider configuration checks.
- Fallback order.
- Local placeholder fallback.
- Focused provider contract tests.

`monitor/provider_adapters` is useful for registry mechanics, but voice should not copy the dynamic proxy data model. Proxy providers normalize external lists into candidates; voice providers execute one bounded media task and materialize a file.

## 4. Architecture Goals

1. Add new voice providers without changing video, article, or UI orchestration code each time.
2. Keep heavy model dependencies out of the main process and `requirements.txt`.
3. Support both local command providers and remote API providers.
4. Preserve current Edge/local/silent TTS behavior during migration.
5. Allow richer providers such as VoxCPM and MiniMax to expose advanced options without polluting simple providers.
6. Keep ASR and TTS in the same voice domain but separate capability interfaces.
7. Make generated audio traceable with metadata, safety gates, and source/provider information.
8. Avoid provider-specific tables unless usage stabilizes and the data is query-worthy.

## 5. Non-Goals

The first architecture pass must not:

- Install or vendor VibeVoice, VoxCPM, vLLM, CUDA, Triton, or Docker images.
- Load large models inside `server/__main__.py`.
- Make VoxCPM or VibeVoice the default TTS provider.
- Enable voice cloning from downloaded YouTube video audio by default.
- Implement LoRA/fine-tuning, batch GPU serving, or model download management.
- Replace the full article, clip, or video generation workflows.

## 6. Options Considered

### Option A: Provider per Product Module

Create `monitor/vibevoice` and `monitor/voxcpm` separately, each with its own config, task manager, API, UI, and pipeline integration.

Pros:

- Fast to start if only one provider is targeted.
- Each provider can keep upstream-specific terminology.

Cons:

- Duplicates config, task storage, output file handling, API routes, UI state, and safety logic.
- Future Edge TTS, Azure, OpenAI, and MiniMax would create more vertical modules.
- Video generation would become a branching matrix of provider-specific calls.

Decision: rejected.

### Option B: Single Generic `VoiceProvider`

Define one provider interface that supports all possible operations:

```text
VoiceProvider.transcribe(...)
VoiceProvider.synthesize(...)
VoiceProvider.clone(...)
VoiceProvider.stream(...)
```

Pros:

- One registry and one task table.
- Looks simple at the naming level.

Cons:

- Forces TTS-only providers to carry ASR methods.
- Forces ASR-only providers to carry TTS methods.
- Encourages broad, weak contracts and runtime capability checks everywhere.
- Makes testing harder because every provider looks larger than it is.

Decision: rejected.

### Option C: Unified Voice Domain with Capability Interfaces

Create one `monitor/voice` domain and split capabilities:

```text
SpeechSynthesisProvider.synthesize(request) -> SpeechSynthesisResult
TranscriptionProvider.transcribe(request) -> TranscriptionResult
```

Providers register the capabilities they support. A provider may implement one or both.

Pros:

- One domain for config, safety, task history, output storage, and UI.
- Clean TTS path for VoxCPM, Edge, Azure, OpenAI, MiniMax, VibeVoice.
- Clean ASR path for Whisper and VibeVoice ASR.
- Avoids leaking ASR concepts into TTS requests.
- Allows staged implementation: TTS first, ASR later.

Cons:

- Requires a small registry/capability model up front.
- UI needs to distinguish synthesis tasks from transcription tasks.

Decision: recommended.

## 7. Recommended Architecture

### 7.1 Package Layout

Use `monitor/voice` as the domain package:

```text
monitor/voice/
├── __init__.py
├── capabilities.py       # provider ids, capability ids, option schemas
├── schemas.py            # request/result dataclasses and normalization
├── providers.py          # Protocol/base classes and registry
├── selection.py          # flow-aware provider resolution and fallback policy
├── synthesis.py          # TTS provider implementations
├── transcription.py      # ASR provider implementations, later phase
├── storage.py            # output dirs, metadata, safe paths, file materialization
├── safety.py             # cloning gates, disclosure, text length, path rules
├── env.py                # local and remote health detection
└── tasks.py              # voice task service, background execution
```

For first implementation, `synthesis.py` may contain Edge/local/silent providers and HTTP/OpenAI-compatible providers. Provider classes can split into submodules once the file grows.

### 7.2 Provider Identity

Provider ids should be stable, lowercase strings:

```text
edge_tts
local_http_tts
openai_speech
azure_speech
minimax_speech
voxcpm_http
voxcpm_openai_speech
vibevoice_tts
vibevoice_realtime
whisper_local
whisper_api
vibevoice_asr
vibevoice_vllm_asr
silent
```

Keep aliases for backwards compatibility:

```text
edge-tts -> edge_tts
local -> local_http_tts when local_tts_url is set
local -> silent when local_tts_url is empty and the request did not explicitly demand local
none/offline/mock/silent -> silent
vibevoice_api -> vibevoice_tts
vibevoice_realtime -> vibevoice_realtime
voxcpm -> voxcpm_http
```

### 7.3 Capability Model

Each provider advertises capabilities separately from its id:

```python
SYNTHESIS = "speech_synthesis"
TRANSCRIPTION = "transcription"
STREAMING_SYNTHESIS = "streaming_synthesis"
VOICE_DESIGN = "voice_design"
REFERENCE_CLONE = "reference_clone"
PROMPT_TRANSCRIPT_CLONE = "prompt_transcript_clone"
SSML = "ssml"
VOICE_LIST = "voice_list"
```

This allows simple provider selection:

```text
resolve_provider(capability="speech_synthesis", provider_id="openai_speech")
```

Advanced UI can also use capabilities to decide which fields to show.

### 7.4 Decoupling Rules

Provider functionality must stay behind capability interfaces. Flows such as video generation, article generation, clip scoring, and manual voice tasks must not branch on provider-specific implementation details.

Hard rules:

- A workflow asks for a capability and mode, not a product module. Example: video generation asks for `speech_synthesis`, optionally with `mode=voice_design`.
- A provider declares capabilities and supported option fields. It does not own workflow orchestration.
- A provider may expose advanced fields through its capability schema, but those fields travel through generic request `metadata` / `options_json`, not provider-specific workflow columns.
- Workflow code must not import `VoxCpmHttpProvider`, `VibeVoiceRealtimeProvider`, `AzureSpeechProvider`, or other concrete providers directly.
- Workflow code may call only resolver/facade functions such as `synthesize_speech(...)` or `transcribe_media(...)`.
- If a requested provider lacks a requested capability or mode, resolution fails with a clear error before the workflow starts the expensive task.
- Fallback is a selection-policy decision, not a provider decision. A provider should not silently call a different provider.

This prevents coupling such as "video generation knows VoxCPM control fields" or "article generation knows VibeVoice vLLM response details". Those details stay in provider adapters and normalized result models.

### 7.5 Runtime Provider Selection

Provider selection must be dynamic at flow and task level. The resolver takes:

```python
@dataclass
class ProviderSelectionRequest:
    capability: str
    flow: str                         # video_generation / article_generation / clip_pipeline / manual_voice
    mode: str | None = None            # plain_tts / voice_design / reference_clone / transcription
    requested_provider: str | None = None
    fallback_allowed: bool = True
    options: dict[str, Any] = field(default_factory=dict)
```

Selection precedence:

1. Task-level explicit provider, for example `tts_workflow`, future `voice_provider`, or an API payload field.
2. Flow-level default, for example "video generation TTS uses Edge TTS, article fallback ASR uses Whisper API".
3. Capability-level default, for example `voice_provider` for synthesis or `transcription_provider` for ASR.
4. Capability fallback order, for example `edge_tts,local_http_tts,silent`.
5. Final hard failure when a real provider was explicitly requested and is unavailable.

The resolver returns a concrete provider plus normalized options:

```python
@dataclass
class ProviderSelectionResult:
    provider_id: str
    capability: str
    flow: str
    mode: str | None
    fallback_chain: list[str]
    effective_options: dict[str, Any]
```

This allows different flows to adjust provider choices independently:

| Flow | Capability | Example default | Example override |
| --- | --- | --- | --- |
| AI video generation | `speech_synthesis` | `edge_tts` | one video task uses `voxcpm_http` |
| Manual AI voice page | `speech_synthesis` | `openai_speech` | user switches to `azure_speech` |
| Article generation fallback | `transcription` | `whisper_api` | one task uses `vibevoice_asr` |
| Clip pipeline | `transcription` | `whisper_local` | long interview task uses `vibevoice_vllm_asr` |

The UI should consume `GET /api/voice/providers` and show providers filtered by capability and flow, not hard-coded provider-specific forms.

## 8. Core Data Contracts

### 8.1 Speech Synthesis Request

```python
@dataclass
class SpeechSynthesisRequest:
    text: str
    output_dir: Path
    output_name: str = "narration"
    provider: str | None = None
    flow: str = "manual_voice"
    voice: str | None = None
    language: str | None = None
    model: str | None = None
    response_format: str = "wav"
    speed: float | None = None
    pitch: str | None = None
    volume: str | None = None
    style: str | None = None
    control_instruction: str | None = None
    reference_audio_path: str | None = None
    prompt_text: str | None = None
    normalize_text: bool | None = None
    denoise_reference: bool | None = None
    streaming: bool = False
    source: str = "manual"
    source_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Notes:

- `voice`, `language`, `speed`, and `response_format` cover Edge TTS, OpenAI, Azure, and MiniMax basics.
- `control_instruction`, `reference_audio_path`, `prompt_text`, `normalize_text`, and `denoise_reference` cover VoxCPM and MiniMax/VoxCPM-style cloning.
- Providers ignore unsupported optional fields only if they are not required by the selected mode. They must fail clearly if a user requests an unsupported mode.

### 8.2 Speech Synthesis Result

```python
@dataclass
class SpeechSynthesisResult:
    provider: str
    path: Path
    mime_type: str
    duration_sec: float | None = None
    sample_rate: int | None = None
    metadata_path: Path | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
```

Every successful synthesis should materialize a local audio file and write `metadata.json`.

### 8.3 Transcription Request

```python
@dataclass
class TranscriptionRequest:
    media_path: str | Path
    output_dir: Path
    provider: str | None = None
    flow: str = "manual_voice"
    language_hint: str = "auto"
    hotwords: list[str] = field(default_factory=list)
    diarization: bool = False
    source: str = "manual"
    source_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 8.4 Transcription Result

```python
@dataclass
class TranscriptionResult:
    provider: str
    text: str
    language: str | None = None
    transcript_path: Path | None = None
    srt_path: Path | None = None
    raw_path: Path | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
```

`TranscriptSegment` should support speaker-aware ASR:

```python
@dataclass
class TranscriptSegment:
    start: float | None
    end: float | None
    text: str
    speaker: str | None = None
```

## 9. Provider Matrix

| Provider | TTS | ASR | Streaming | Voice design | Reference clone | SSML | Primary integration |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `silent` | Yes | No | No | No | No | No | local generated WAV |
| `edge_tts` | Yes | No | No in MVP | No | No | No | CLI or Python module |
| `local_http_tts` | Yes | No | Depends service | Depends service | Depends service | Depends service | generic POST service |
| `openai_speech` | Yes | No | Yes | voice/instructions only | No by default | No | `/v1/audio/speech` |
| `azure_speech` | Yes | No | SDK later | Voice/style via SSML | Custom voice by account | Yes | Azure Speech REST |
| `minimax_speech` | Yes | No | Provider-dependent | Yes | Yes | No | MiniMax speech APIs |
| `voxcpm_http` | Yes | No | Provider-dependent | Yes | Yes | No | external VoxCPM service |
| `voxcpm_openai_speech` | Yes | No | Provider-dependent | Limited | Limited | No | OpenAI-compatible `/v1/audio/speech` |
| `vibevoice_tts` | Yes | No | Provider-dependent | Limited | No by default | No | external service |
| `vibevoice_realtime` | Yes | No | Yes | Built-in voices | No by default | No | websocket/service wrapper |
| `whisper_local` | No | Yes | No | No | No | No | current faster-whisper path |
| `whisper_api` | No | Yes | No | No | No | No | current compatible API |
| `vibevoice_asr` | No | Yes | Provider-dependent | No | No | No | external VibeVoice ASR API |
| `vibevoice_vllm_asr` | No | Yes | Yes | No | No | No | vLLM compatible endpoint |

## 10. Configuration Design

Preserve current fields:

```text
tts_provider
local_tts_url
```

Add unified fields:

```text
voice_provider = "edge_tts" | "local_http_tts" | "openai_speech" | ...
voice_fallback_order = "edge_tts,local_http_tts,silent"
voice_flow_defaults_json = "{}"
voice_output_dir = "data/voice"
voice_require_disclosure = true
voice_allow_reference_clone = false
voice_allow_prompt_transcript_clone = false
voice_max_text_chars = 5000
```

Add provider-specific fields only for stable provider options:

```text
openai_speech_base_url
openai_speech_api_key
openai_speech_model
openai_speech_voice

azure_speech_region
azure_speech_endpoint
azure_speech_api_key
azure_speech_voice
azure_speech_output_format

minimax_speech_base_url
minimax_speech_api_key
minimax_speech_model
minimax_speech_voice

voxcpm_base_url
voxcpm_api_key
voxcpm_model
voxcpm_default_voice
voxcpm_default_control_instruction

vibevoice_tts_base_url
vibevoice_tts_api_key
vibevoice_tts_model
vibevoice_tts_voice

vibevoice_asr_base_url
vibevoice_asr_api_key
vibevoice_asr_model
```

Sensitive keys must be added to `config/settings.py` `_SECRET_CONFIG_KEYS` and to backend response masking/preservation logic.

Avoid adding every possible provider parameter to global config. Rare or task-specific values should live in `voice_options_json` on the task.

`voice_flow_defaults_json` allows dynamic defaults per workflow without schema churn:

```json
{
  "video_generation.speech_synthesis": "edge_tts",
  "manual_voice.speech_synthesis": "openai_speech",
  "article_generation.transcription": "whisper_api",
  "clip_pipeline.transcription": "whisper_local"
}
```

The value is a default only. A task-level provider selection still wins.

## 11. Task and Storage Design

### 11.1 Voice Task Table

Use one `voice_tasks` table:

```sql
CREATE TABLE IF NOT EXISTS voice_tasks (
    task_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                 -- synthesis / transcription / env_check
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

Reasons:

- One table supports manual voice workspace history and pipeline-generated voice tasks.
- `kind` prevents TTS and ASR field confusion.
- `options_json` avoids schema churn for provider-specific controls.
- Pipeline tasks can reference `voice_task_id` from `video_gen_tasks.result_json` or `article_tasks.stage_json` first.

### 11.2 Output Layout

Use deterministic task directories:

```text
data/voice/
└── voice_20260606_<id>/
    ├── input.json
    ├── output.wav
    ├── transcript.txt
    ├── transcript.srt
    ├── raw-response.json
    └── metadata.json
```

All file serving must remain restricted to configured output roots.

### 11.3 Metadata

Every generated audio file should include metadata:

```json
{
  "ai_generated": true,
  "provider": "voxcpm_http",
  "capability": "speech_synthesis",
  "model": "openbmb/VoxCPM2",
  "voice": "default",
  "source": "video_generation",
  "source_task_id": "video_gen_xxx",
  "input_text_hash": "sha256:...",
  "reference_audio_hash": "sha256:...",
  "disclosure_required": true,
  "created_at": "2026-06-06T00:00:00+08:00"
}
```

Do not log full long text or secrets.

## 12. API Design

Use unified routes:

```http
GET  /api/voice/providers
GET  /api/voice/providers?capability=speech_synthesis&flow=video_generation
GET  /api/voice/env
POST /api/voice/env/check
POST /api/voice/synthesis/tasks
POST /api/voice/transcription/tasks
GET  /api/voice/tasks
GET  /api/voice/tasks/{task_id}
POST /api/voice/tasks/{task_id}/cancel
GET  /api/voice/file?path=...
POST /api/voice/smoke-test
```

`GET /api/voice/providers` returns capabilities and UI schema:

```json
{
  "providers": [
    {
      "id": "edge_tts",
      "label": "Edge TTS",
      "capabilities": ["speech_synthesis"],
      "configured": true,
      "fields": ["voice", "rate", "pitch", "volume"],
      "safety": {"reference_clone": false}
    }
  ]
}
```

Video generation can call the provider layer directly in-process first. A full `voice_task_id` can be created later when the user needs visible voice history for every generated video.

The API should accept provider overrides in task payloads:

```json
{
  "flow": "video_generation",
  "capability": "speech_synthesis",
  "provider": "voxcpm_http",
  "mode": "voice_design",
  "options": {
    "control_instruction": "young clear tech explainer voice"
  }
}
```

Provider override fields are explicit runtime choices. They must not mutate global defaults unless the settings API is called.

## 13. Pipeline Integration

### 13.1 Video Generation

Replace only `_synthesize_narration()` selection logic:

```text
current storyboard text
-> SpeechSynthesisRequest
-> ProviderSelectionRequest(flow="video_generation", capability="speech_synthesis")
-> synthesize_speech_with_fallback()
-> SpeechSynthesisResult.path
-> existing _render_video()
```

Preserve:

- `edge-tts`
- `local_tts_url`
- `silent/offline/mock`
- configured provider failure behavior
- `_probe_audio_duration()`
- final video rendering logic

Record in `video_gen_tasks.result_json`:

```json
{
  "voice_provider": "edge_tts",
  "voice_task_id": "voice_xxx",
  "audio_path": "...",
  "audio_duration_sec": 12.3
}
```

Runtime selection examples:

- A default video task can use global `video_generation.speech_synthesis=edge_tts`.
- A specific video task can set `tts_workflow=voxcpm_http` and pass `voice_options_json` for voice design.
- A production profile can switch the flow default to `azure_speech` without touching video rendering code.
- If `voxcpm_http` is explicitly requested and unavailable, the task should fail unless the request explicitly allows fallback.

### 13.2 Article Generation

Keep current order:

```text
local subtitle
-> remote subtitle via yt-dlp
-> configured TranscriptionProvider
-> LLM optimize/summary/rewrite
```

Initial implementation should only refactor provider selection; it must not change the article output contract.

Article generation should resolve ASR through:

```text
ProviderSelectionRequest(flow="article_generation", capability="transcription")
```

This allows a single article task to use VibeVoice ASR while the default remains Whisper.

### 13.3 Clip Pipeline

Clip pipeline should consume normalized `.txt` / `.srt` artifacts first. Speaker-aware scoring can wait until the VibeVoice ASR path is stable.

## 14. UI Design

Use the current Vue frontend, not the older `monitor_web` plan:

- `frontend-vue/src/views/AiCreation.vue` should replace free-text `tts_workflow` with a provider select and advanced options.
- `frontend-vue/src/views/settings/AiSettings.vue` should expose global defaults, provider keys, and safe toggles.
- A future `frontend-vue/src/views/AiVoice.vue` can provide manual synthesis/transcription tasks and task history.

UI should be capability-driven:

- Basic TTS fields: text, provider, voice, language, format, speed.
- Edge fields: rate, pitch, volume.
- Azure fields: SSML toggle, voice, output format, region/endpoint in settings.
- VoxCPM/MiniMax fields: control instruction and reference audio only when cloning is enabled.
- VibeVoice ASR fields: hotwords and language hint.

For dynamic per-flow selection:

- Settings UI manages global defaults and flow defaults.
- Task creation UI manages per-task overrides.
- Manual voice UI manages interactive provider choice.
- Provider-specific advanced fields appear only after the selected provider advertises the matching capability schema.

Default UI behavior:

- Hide reference clone unless `voice_allow_reference_clone=true`.
- Show disclosure for generated speech.
- Do not auto-fill reference audio from downloaded videos.
- Do not expose longform multi-speaker TTS as a default mode.

## 15. Safety Rules

Voice generation has higher abuse risk than ordinary text generation. The shared safety layer must enforce:

- TTS disabled or non-default for high-risk providers unless configured.
- Reference cloning disabled by default.
- Prompt-transcript cloning disabled by default.
- Explicit user-owned/authorized reference audio notice.
- No automatic extraction of speaker identity from downloaded videos.
- `metadata.json` with `ai_generated: true`.
- Output files restricted to configured output roots.
- API keys encrypted and masked.
- No full secret or long generated script logging.
- Provider errors sanitized before reaching UI.

## 16. Testing Strategy

Add tests before implementation:

- Provider registry aliases and capability lookup.
- Flow-aware provider selection precedence.
- Task-level provider override wins over flow defaults.
- Flow defaults win over global capability defaults.
- Explicit provider failure does not fallback unless fallback was allowed by request/policy.
- `SpeechSynthesisRequest` normalization.
- Edge provider command construction with fake `subprocess.run`.
- Local HTTP provider raw audio and JSON file-reference responses.
- Configured local TTS failure is not silently replaced.
- Silent fallback only when no explicit real provider was requested.
- Metadata writing and output-root path safety.
- Secret masking and masked secret preservation for new keys.
- Video pipeline integration with fake synthesis provider.
- Future ASR provider selection without running real models.

Do not require real VibeVoice, VoxCPM, Azure, OpenAI, MiniMax, or Edge network calls in automated tests.

## 17. Migration Plan

### Phase 1: Foundation

- Create `monitor/voice/schemas.py`, `providers.py`, `storage.py`, `safety.py`, and `synthesis.py`.
- Implement `silent`, `edge_tts`, and `local_http_tts`.
- Add provider alias normalization.
- Add focused tests.

### Phase 2: Video Pipeline Adapter

- Update `scripts/video_gen_pipeline.py` to call the shared synthesis layer.
- Preserve existing behavior for `tts_workflow`.
- Record provider metadata in result JSON.

### Phase 3: Config and UI

- Add unified voice config fields and secret masking.
- Update `AiSettings.vue` provider options.
- Replace free-text TTS workflow in `AiCreation.vue` with a select while preserving raw compatibility.

### Phase 4: External TTS Providers

- Add `openai_speech`.
- Add `azure_speech`.
- Add `minimax_speech`.
- Add `voxcpm_http` and `voxcpm_openai_speech`.
- Add `vibevoice_tts` and `vibevoice_realtime` as service/API clients.

### Phase 5: Voice Tasks and Manual Workspace

- Add `voice_tasks`.
- Add `/api/voice/*` routes.
- Add manual `AiVoice.vue` task page.
- Link generated audio from video tasks to voice task history.

### Phase 6: ASR Capability

- Add `TranscriptionProvider`.
- Wrap current Whisper local/API behavior.
- Add VibeVoice ASR providers.
- Integrate article pipeline by replacing only the ASR fallback branch.

## 18. How Existing VibeVoice and VoxCPM Plans Should Change

### VibeVoice Plan

Replace `monitor/vibevoice` with `monitor/voice`:

- `VibeVoiceApiProvider` becomes a `TranscriptionProvider` implementation.
- `VibeVoiceVllmProvider` becomes a `TranscriptionProvider` implementation.
- `GenericTtsApiProvider` becomes `local_http_tts` or `vibevoice_tts` depending on service contract.
- `VibeVoiceRealtimeWsProvider` becomes a `SpeechSynthesisProvider` with `streaming_synthesis`.
- `/api/vibevoice/*` routes should not be added. Use `/api/voice/*`.

### VoxCPM Plan

Keep its `monitor/voice` direction, but generalize names:

- `VoiceSynthesisRequest` should become `SpeechSynthesisRequest`.
- `VoxCpmHttpClient` should be one provider, not the root voice client.
- `/api/voice/tasks` should distinguish `kind=synthesis`.
- VoxCPM advanced fields go into `options_json` and provider-specific UI sections.

## 19. Main Risks

1. Over-generalization: avoid building a provider marketplace. Implement only what current workflows need.
2. Silent fallback masking failures: keep explicit provider failures visible.
3. Secret leakage: add all new provider API keys to encryption, masking, and preservation tests.
4. Clone misuse: keep reference clone disabled and never infer reference audio automatically.
5. Long-running generation: real remote TTS can exceed current 300s assumptions; make timeouts provider-configurable.
6. UI sprawl: use capability-driven advanced sections rather than one giant form.
7. Provider response variance: normalize all outputs to local files and metadata before handing them to pipelines.

## 20. Open Decisions

These can be decided during implementation planning:

1. Should Phase 1 live under `monitor/voice` only, or should a thin `scripts/voice_generation.py` facade be added for script imports?
   - Recommendation: add `monitor/voice`, and expose a small script-friendly function from that package.
2. Should `voice_tasks` be created in Phase 1 or Phase 5?
   - Recommendation: Phase 5. Keep Phase 1 smaller by returning direct synthesis results to video generation.
3. Should `voice_provider` replace `tts_provider` immediately?
   - Recommendation: no. Preserve `tts_provider` as a compatibility alias through at least one release.
4. Which external paid provider should land first after local/edge?
   - Recommendation: OpenAI first because its API shape is smallest, then Azure, then MiniMax/VoxCPM/VibeVoice service adapters.

## 21. Spec Self-Review

- Placeholder scan: no `TBD` or implementation placeholders remain.
- Consistency check: the package, routes, and provider ids consistently use the unified `monitor/voice` domain.
- Scope check: the design covers architecture and staged migration, not full provider implementation.
- Ambiguity check: TTS and ASR are explicitly separated as capability interfaces; TTS is the first implementation path.
- Compatibility check: current `tts_provider`, `local_tts_url`, and `tts_workflow` behavior is preserved through aliases and migration phases.

# VibeVoice 集成实施计划草案

> **Status:** Draft for discussion. Do not implement until the spec is approved.
> **Spec:** `docs/superpowers/specs/2026-06-06-vibevoice-integration-feasibility-design.md`

**Goal:** 以服务/API 优先方式把 Microsoft VibeVoice 的 ASR/TTS 能力接入本项目，并提供本地环境检测与简单一致的 Web UI。

**Recommended MVP:** VibeVoice-ASR remote/vLLM adapter + environment check + settings page. TTS follows as API provider after ASR path verified.

---

## Phase 0: Review and Decisions

- [ ] Review the feasibility spec with the user.
- [ ] Decide first priority: ASR-first or TTS-first.
- [ ] Decide UI placement: new `settings-voice` page or merge into `settings-ai`.
- [ ] Decide target runtime for VibeVoice-ASR: remote generic API, vLLM OpenAI-compatible API, or local experimental CLI.
- [ ] Confirm safety policy for generated speech: manual-review only vs allowed in automation.

Exit criteria:

- The spec is approved or edited.
- One MVP path is selected.

---

## Phase 1: Environment Detection Foundation

Files:

- Add: `monitor/vibevoice/__init__.py`
- Add: `monitor/vibevoice/env.py`
- Add: `scripts/vibevoice_env.py`
- Modify: `server/__main__.py`
- Modify: `tests/` with focused env route tests

Tasks:

- [ ] Implement read-only probes for Python, platform, ffmpeg/ffprobe, Docker CLI, Docker daemon, nvidia-smi, torch, package availability, disk space.
- [ ] Normalize result into stable JSON with `ok`, `status`, `reason`, and `recommendation`.
- [ ] Add `GET /api/vibevoice/env` for cached/quick status.
- [ ] Add `POST /api/vibevoice/env/check` for explicit re-check.
- [ ] Add CLI `python scripts/vibevoice_env.py --json`.
- [ ] Unit test probe functions using monkeypatch/mocked subprocess.
- [ ] Route test JSON shape.

Verification:

```powershell
python scripts/vibevoice_env.py --json
python -m pytest tests/test_vibevoice_env.py -q
```

Notes:

- This phase must not install packages or download models.
- It must not start Docker containers.

---

## Phase 2: Config Schema and Secret Handling

Files:

- Modify: `config/settings.py`
- Modify: `server/__main__.py`
- Modify: `monitor_web/js/modules/config.js` later in UI phase
- Add/modify tests for config preservation and secret masking

Tasks:

- [ ] Add default config keys listed in the spec.
- [ ] Add `vibevoice_asr_api_key` and `vibevoice_tts_api_key` to `_SECRET_CONFIG_KEYS`.
- [ ] Extend `/api/config` allowlist with VibeVoice keys.
- [ ] Preserve masked secret values on save.
- [ ] Validate URL fields are HTTP(S) and do not contain credentials.
- [ ] Validate backend enum values.
- [ ] Add tests for default config, save/load encryption, masked preservation, invalid backend rejection.

Verification:

```powershell
python -m pytest tests/test_vibevoice_config.py -q
```

---

## Phase 3: VibeVoice ASR Client Adapters

Files:

- Add: `monitor/vibevoice/clients.py`
- Add: `monitor/vibevoice/adapters.py`
- Add: `monitor/vibevoice/schemas.py`
- Add: `tests/test_vibevoice_asr_client.py`

Tasks:

- [ ] Define `TranscriptResult` normalized structure.
- [ ] Implement `VibeVoiceApiProvider` for generic API responses.
- [ ] Implement `VibeVoiceVllmProvider` for OpenAI-compatible vLLM ASR endpoint.
- [ ] Support hotwords.
- [ ] Persist raw response JSON to task output dir.
- [ ] Convert structured segments to `.txt` and optional `.srt`.
- [ ] Add request timeout and clear error mapping.
- [ ] Mock HTTP success, auth failure, timeout, malformed response, and streaming/non-streaming variants.

Verification:

```powershell
python -m pytest tests/test_vibevoice_asr_client.py -q
```

Implementation caution:

- Do not import VibeVoice model code in this phase.
- Do not add `vllm` or VibeVoice dependencies to `requirements.txt`.

---

## Phase 4: Voice Task Manager and API

Files:

- Add: `monitor/vibevoice/tasks.py`
- Modify: `monitor/schema.sql`
- Modify: `monitor/db.py` or add query helpers under `monitor/db/queries/`
- Modify: `server/__main__.py`
- Add: `tests/test_vibevoice_tasks_api.py`

Tasks:

- [ ] Add `voice_tasks` table migration.
- [ ] Add create/update/get/list query helpers.
- [ ] Implement `VoiceTaskManager` with background thread execution.
- [ ] Add `POST /api/vibevoice/asr/tasks`.
- [ ] Add task list/detail/cancel endpoints.
- [ ] Enforce safe input path handling for local media paths.
- [ ] Support `monitor_video_id` input by resolving existing downloaded media path where available.
- [ ] Return stable progress/status JSON.
- [ ] Test task lifecycle with fake provider.

Verification:

```powershell
python -m pytest tests/test_vibevoice_tasks_api.py -q
```

---

## Phase 5: UI Page for AI Voice

Files:

- Add: `monitor_web/templates/pages/settings-voice.html`
- Modify: `monitor_web/static/js/router.js`
- Modify: `monitor_web/js/load-partials.js`
- Modify: `monitor_web/js/modules/config.js`
- Add: `monitor_web/js/modules/vibevoice.js`
- Modify: `monitor_web/js/app.js`
- Modify: `monitor_web/static/i18n/zh.json`
- Modify: `monitor_web/static/i18n/en.json`
- Modify CSS only if existing classes are insufficient

Tasks:

- [ ] Add route `settings-voice`.
- [ ] Add settings hub card.
- [ ] Add page header, status cards, ASR provider form, TTS provider form, smoke-test area, recent task table.
- [ ] Wire `Run environment check`.
- [ ] Wire `Test ASR endpoint`.
- [ ] Wire `Start ASR task`.
- [ ] Show task status with text + badge and `aria-live`.
- [ ] Use existing card/form/button classes and `DESIGN.md` tokens.
- [ ] Add zh/en i18n keys.
- [ ] Ensure every input has a label.

Verification:

```powershell
python -m pytest tests/test_ai_settings_secret_masking.py -q
```

Manual UI verification:

- Open `http://127.0.0.1:5000/#/settings-voice`.
- Check 375px, 768px, 1024px, 1440px layouts.
- Confirm no horizontal scroll.
- Confirm save preserves unrelated config fields.
- Confirm error/loading states are visible.

---

## Phase 6: Article Pipeline ASR Integration

Files:

- Modify: `scripts/article_generator.py`
- Add tests around ASR provider selection

Tasks:

- [ ] Extract current Whisper-specific fallback into a provider selection function.
- [ ] Add VibeVoice ASR provider branch after subtitle download fails.
- [ ] Preserve current Whisper local/API behavior as fallback.
- [ ] Store `transcript_source = "vibevoice_asr"` when used.
- [ ] Store raw transcript metadata path in article task stage metadata.
- [ ] Add tests for provider selection and fallback without running models.

Verification:

```powershell
python -m pytest tests/test_article_generator_vibevoice_asr.py -q
python -m pytest tests/test_ai_content_workflow_schema_contract.py -q
```

---

## Phase 7: TTS Provider Integration

Files:

- Extend: `monitor/vibevoice/clients.py`
- Extend: `monitor/vibevoice/adapters.py`
- Extend: `monitor/vibevoice/tasks.py`
- Add tests

Tasks:

- [ ] Implement `GenericTtsApiProvider`.
- [ ] Implement `VibeVoiceRealtimeWsProvider` if endpoint contract is confirmed.
- [ ] Add `POST /api/vibevoice/tts/tasks`.
- [ ] Save output audio and `metadata.json`.
- [ ] Enforce text length cap.
- [ ] Enforce disclosure metadata.
- [ ] Add UI TTS smoke test.
- [ ] Optionally map `tts_provider = vibevoice_api` for video generation pipeline.

Verification:

```powershell
python -m pytest tests/test_vibevoice_tts_client.py -q
python -m pytest tests/test_vibevoice_tasks_api.py -q
```

---

## Phase 8: Documentation and Manual E2E

Files:

- Add: `docs/vibevoice-integration.md`
- Modify: `README.md` only after feature is implemented and verified

Tasks:

- [ ] Document remote GPU/vLLM deployment expectation.
- [ ] Document local machine limitations and environment checker interpretation.
- [ ] Document API service contract examples.
- [ ] Document responsible use policy.
- [ ] Run manual ASR task against a real VibeVoice service if available.
- [ ] Run manual TTS task against a real Realtime TTS service if available.
- [ ] Record known limitations.

Verification:

```powershell
python -m pytest tests/ -q
python scripts/vibevoice_env.py --json
```

Manual:

- ASR: one short local audio/video -> transcript text.
- Article pipeline: no subtitle video -> VibeVoice transcript -> article draft.
- TTS: short text -> generated audio -> browser preview.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Local machine cannot run models | Users may expect one-click local inference | Environment checker gives explicit recommendation; UI defaults to API/service |
| vLLM API format differs | ASR adapter may fail | Keep raw response capture and mocked contract tests |
| VibeVoice TTS misuse | Legal/reputation risk | TTS off by default, no voice cloning, disclosure metadata |
| Main server blocking | UI/API unresponsive | All inference tasks run in background manager or external service |
| Config sprawl | Settings page becomes noisy | Separate `settings-voice` page with simple defaults and advanced section |
| Dependency bloat | PyInstaller build breaks | No VibeVoice/vLLM deps in base requirements |

---

## Rollback Plan

- Config additions are inert when `vibevoice_enabled=false`.
- UI route can be hidden by removing the hub/nav entry.
- `voice_tasks` table is additive and does not affect existing download/monitor tables.
- Article pipeline keeps Whisper fallback and should continue working if VibeVoice calls fail.

---

## Completion Criteria

- Environment checker reports accurate local status.
- Remote ASR adapter works against mocked and at least one real service.
- UI can save config, run env check, start a task, and display result.
- Existing tests pass.
- No new default heavyweight dependencies.
- Generated speech is opt-in and records disclosure metadata.


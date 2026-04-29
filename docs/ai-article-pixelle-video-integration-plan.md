# AI Article And Pixelle Video Integration Plan

Branch: `codex/ai-article-pixelle-video-plan`

Source specs:

- `docs/superpowers/specs/2026-04-25-ai-article-integration-design.md`
- `docs/superpowers/specs/2026-04-25-pixelle-video-integration-design.md`

## Summary

This document is the reviewed implementation handoff for adding two AI content workflows to `ytdlp-batch-downloader`:

- AI article generation: downloaded video or monitored video -> subtitles/transcript -> optimized text -> summary/translation -> `draft.md` for article-tools.
- Pixelle-style video generation: topic or script -> storyboard -> image generation -> TTS -> short video assembly.

The implementation must fit the current project shape: a custom `MonitorHandler` server, `monitor.db` as the public database API surface, Vue/Naive UI on the frontend, and the existing Claude warm card visual system from `DESIGN.md`. Current scope is planning and implementation handoff only; no feature code is included in this document.

## Key Decisions

- Do not assume `server/modules/*` exists. P0 routes should be added in the existing `server/__main__.py` `MonitorHandler` flow unless a separate routing refactor is explicitly approved.
- Use polling-first task progress for P0. Do not reuse `/api/res-events`, because it is tied to Go proxy resource events and has a different event shape.
- Persist large artifacts as files, not SQLite blobs. Store transcripts, optimized text, article drafts, storyboard JSON, generated asset metadata, and final render metadata under task output directories.
- Keep SQLite focused on task identity, status, stage summaries, timestamps, output paths, errors, and query indexes.
- Do not make `DELETE` mean both cancel and purge. P0 should use explicit cooperative cancellation endpoints such as `POST /api/article/{task_id}/cancel` and `POST /api/video-generate/{task_id}/cancel`, while preserving task history.
- Keep generation workspaces separate from settings. Settings remain under `/settings-hub/ai`; article and video generation live in an AI creation workspace, with article generation also available as a contextual action from the video detail modal.
- Preserve the Claude warm UI language from `DESIGN.md`: warm surfaces, subtle borders, restrained terracotta accents, accessible focus states, and no cold admin-dashboard restyle.
- Copy only the required Pixelle template subset for P0, and include Pixelle's Apache 2.0 license plus modification notes with any copied template files.

## Implementation Changes

### Backend And API

- Add article task endpoints in the existing handler style:
  - `POST /api/article/generate`
  - `GET /api/article/list`
  - `GET /api/article/{task_id}`
  - `POST /api/article/{task_id}/cancel`
- Add video generation task endpoints in the existing handler style:
  - `POST /api/video-generate`
  - `GET /api/video-generate/list`
  - `GET /api/video-generate/{task_id}`
  - `POST /api/video-generate/{task_id}/cancel`
  - `GET /api/video-generate/templates`
  - a safe file-preview/download endpoint restricted to configured output directories
- Validate request bodies explicitly and return stable `400`, `404`, and `409` responses for invalid params, missing videos/templates, non-cancellable terminal tasks, and invalid output paths.
- Prefer background worker threads that update task rows after each stage. Add cancellation checks between stages and before long external calls where practical.

### Database

- Add a new idempotent migration, tentatively `v17_ai_content_workflows`, in both `monitor/schema.sql` and `monitor/db.py`.
- Create `article_tasks` with `monitor_video_id INTEGER` referencing `monitor_videos.id`, plus a `video_id TEXT` snapshot for external platform identity.
- Create `video_gen_tasks` with task status, mode, topic/script snapshot, template, stage JSON, output path, duration, file size, and error fields.
- Expose top-level `monitor.db` CRUD functions such as `create_article_task`, `update_article_task`, `get_article_task`, `list_article_tasks`, and matching video generation functions.
- Mark stale `running` or `cancelling` article/video generation tasks as interrupted on service startup, matching the existing web batch recovery pattern.

### Configuration

- Extend the full config chain for every new setting:
  - defaults in `config/settings.py`
  - save whitelist in `server/__main__.py`
  - response secret masking
  - `frontend-vue/src/api/config.ts` `AppConfig`
  - `frontend-vue/src/views/settings/AiSettings.vue` load/save behavior
- Add shared inference fields for the article workflow and video workflow, including remote LLM/Whisper endpoints, output directories, default target language, default article-tools path, ComfyUI/RunningHub settings, TTS provider settings, default template, and default scene count.
- Treat `whisper_api_key`, `comfyui_api_key`, and `runninghub_api_key` as secrets with masked round-trip preservation.

### Article Workflow

- Implement subtitle-first extraction using `yt-dlp` metadata and subtitle download before falling back to remote Whisper.
- Reuse or extend `scripts/llm_client.py` for OpenAI-compatible LM Studio style calls.
- Write task artifacts to a stable task output directory: raw subtitles/transcript, optimized transcript, summary, translated text, stage metadata, and final `draft.md`.
- Generate article-tools quick links from configured `article_tools_path`, but keep article-tools loosely coupled through `draft.md`.
- Treat draft write failure as a terminal error, not a pending task.

### Video Generation Workflow

- Generate storyboard JSON from topic/script using the shared LLM infrastructure.
- Generate images through ComfyUI first, with RunningHub fallback only when configured.
- Use the configured TTS provider. Do not add a new dependency for Edge-TTS in P0 unless dependency approval is given; if an existing command/API is available, use it behind a provider adapter.
- Assemble the final video with FFmpeg using generated images and audio. If HTML template rendering requires browser or Pixelle runtime dependencies, keep that as P1 and use an FFmpeg-native P0 assembly path.
- Keep template names/path fragments on a whitelist rooted under `templates/pixelle-templates/`.

### Frontend And UI

- Add a main `AI Creation` workspace route for generation tasks and history. Use tabs or segmented controls for article tasks and video generation.
- Add a contextual `Generate Article` action to the existing video detail modal for downloaded or monitored videos where enough metadata is available.
- Keep AI Settings under `/settings-hub/ai` and split it into grouped cards: shared inference, article defaults, video generation defaults, and advanced settings.
- Fix the existing `/settings-hub/global` dead link before adding new settings cards.
- Reuse existing warm card, table, filter-bar, button, and status badge styles. New pages should remain responsive: one column on mobile, at most two columns on tablet, and denser multi-column layout only on desktop.
- Add i18n keys for all visible navigation, actions, statuses, errors, and empty states.

## Test Plan

- Database and migration:
  - fresh bootstrap includes both new tables and indexes
  - old database upgrade adds the new tables
  - migration is idempotent
  - startup marks stale running/cancelling tasks as interrupted
- API and task state:
  - request validation matrix for article and video generation
  - list/detail responses for each status
  - cooperative cancellation for queued/running tasks
  - stable conflict response when cancelling terminal tasks
  - safe file endpoint rejects traversal and unconfigured paths
- Article workflow:
  - subtitle path succeeds without Whisper
  - no-subtitle path falls back to remote Whisper
  - LLM optimize/summary/translation failure maps to task error
  - draft output includes expected article-tools handoff data
  - paths containing spaces, Chinese characters, and Windows separators are handled
- Video workflow:
  - storyboard generation writes valid JSON
  - ComfyUI failure falls back only when RunningHub is configured
  - TTS failure is surfaced clearly
  - FFmpeg failure marks task error and preserves diagnostics
  - template whitelist and Pixelle license files are verified
- Frontend:
  - route exists for AI creation workspace
  - sidebar entry follows active/aria-current behavior
  - video detail modal exposes article generation action
  - config fields save and reload through the full whitelist/masking chain
  - no missing zh/en i18n keys
  - mobile layout does not overflow

Recommended verification commands after implementation:

```powershell
python -m pytest tests/test_monitor_schema_bootstrap.py tests/test_ai_settings_secret_masking.py tests/test_frontend_video_detail_clip_action.py -q
python -m pytest tests/test_article_* tests/test_video_gen_* -q
cd frontend-vue
npm run build
cd ..
python -m pytest tests/ -q
```

Manual acceptance should also cover:

- `POST -> poll detail/list -> done/error` for article generation.
- `POST -> poll detail/list -> done/error` for video generation.
- `POST /cancel` during a long-running task.
- Opening the generated `draft.md` handoff links.
- Opening or downloading the final generated video.
- Confirming `templates/pixelle-templates/` includes `LICENSE` and modification notes.

## Assumptions

- P0 avoids adding new Python or Node dependencies. Any new dependency must be approved separately.
- Article-tools remains an external/static handoff target and is integrated through generated `draft.md`.
- Pixelle-Video is used as a template and architecture reference, not copied wholesale.
- SSE is a P1 enhancement unless a dedicated task event queue and frontend consumer are designed first.
- No implementation code should be changed as part of creating this planning artifact.

# Unified Voice Provider Architecture

This project uses one `monitor/voice` domain for speech synthesis and transcription. Providers are selected by capability and flow, so workflow code can choose `edge_tts`, `openai_speech`, `vibevoice_asr`, or future providers without importing concrete provider classes.

## Capabilities

| Capability | Purpose | Current providers |
| --- | --- | --- |
| `speech_synthesis` | Text to audio for video narration and manual voice tasks | `edge_tts`, `local_http_tts`, `openai_speech`, `azure_speech`, `minimax_speech`, `voxcpm_openai_speech`, `voxcpm_http`, `vibevoice_tts`, `vibevoice_realtime`, `silent` |
| `transcription` | Audio/video to transcript for article generation and future clip workflows | `whisper_local`, `whisper_api`, `vibevoice_asr`, `vibevoice_vllm_asr` |
| `voice_design` | Provider-specific voice design mode | `minimax_speech` |
| `reference_clone` | Provider-specific reference audio clone mode | `minimax_speech` |
| `ssml` | SSML input or SSML-derived payload | `azure_speech` |

No workflow should import a concrete provider such as `OpenAiSpeechProvider` or `VibeVoiceAsrProvider`. Workflows create a request object and call the voice domain entrypoint.

## Selection Order

Provider selection is centralized in `monitor/voice/selection.py`.

1. Explicit task/request provider.
2. Flow default from `voice_flow_defaults_json`, for example `video_generation.speech_synthesis`.
3. Capability default, for example `voice_provider` for synthesis or `transcription_provider` for ASR.
4. Legacy compatibility defaults such as `tts_workflow` and `whisper_provider`.
5. Fallback order.

Example:

```json
{
  "manual_voice.speech_synthesis": "openai_speech",
  "video_generation.speech_synthesis": "edge_tts",
  "article_generation.transcription": "whisper_api",
  "clip_pipeline.transcription": "whisper_local"
}
```

## Workflow Integration

`scripts/video_gen_pipeline.py` uses `SpeechSynthesisRequest` and `synthesize_speech()`. The task-level `tts_workflow` field is preserved for compatibility, but it now maps to provider ids.

`scripts/article_generator.py` keeps its subtitle-first behavior. Only the ASR fallback branch goes through `TranscriptionRequest` and provider selection. Article-specific Whisper wrappers preserve the existing local Whisper chunking, progress messages, and remote Whisper behavior while allowing VibeVoice ASR to be selected by flow defaults.

Manual voice synthesis uses durable `voice_tasks` rows and `/api/voice/synthesis/tasks`. The Vue `/ai-voice` page creates synthesis tasks, lists recent tasks, cancels pending/running work, and plays completed audio through `/api/voice/file`.

## Safety Rules

- Generated voice metadata records provider, capability, source, and disclosure fields.
- Reference clone is disabled unless `voice_allow_reference_clone=true`.
- MiniMax reference clone input must live under the configured reference/output directory and be `.mp3`, `.m4a`, or `.wav`, max 20 MB.
- Provider-returned `audio_url` downloads are same-origin with the provider endpoint only, reject embedded credentials, and block private/link-local hosts.
- `/api/voice/file` only serves files inside `voice_output_dir`.
- Remote environment checks do not probe provider URLs unless `include_remote=true`.

## Verification

Automated tests use fake HTTP/subprocess implementations. They must not call paid providers, Edge network services, local large models, VibeVoice, VoxCPM, or vLLM.

Useful focused checks:

```powershell
python -m pytest tests/test_voice_provider_contract.py tests/test_voice_selection_contract.py tests/test_voice_storage.py tests/test_voice_safety.py -q
python -m pytest tests/test_voice_external_synthesis_providers.py tests/test_voice_provider_payloads.py -q
python -m pytest tests/test_voice_tasks_schema.py tests/test_voice_tasks_api.py tests/test_voice_api_contract.py -q
python -m pytest tests/test_article_generator_voice_transcription.py tests/test_voice_transcription_contract.py -q
cd frontend-vue
npm run build
```

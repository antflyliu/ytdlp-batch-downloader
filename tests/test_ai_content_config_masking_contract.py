"""Contract tests for AI article/video workflow config surface and secret masking."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"
CONFIG_API = ROOT / "frontend-vue" / "src" / "api" / "config.ts"
AI_SETTINGS = ROOT / "frontend-vue" / "src" / "views" / "settings" / "AiSettings.vue"
ZH_LOCALE = ROOT / "frontend-vue" / "src" / "locales" / "zh.json"
EN_LOCALE = ROOT / "frontend-vue" / "src" / "locales" / "en.json"


def _require_snippets(text: str, snippets: list[str], reason: str) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        pytest.fail(f"{reason}. Missing: {missing}")


def test_backend_config_masking_whitelist_includes_ai_article_and_video_secrets():
    text = SERVER_MAIN.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            '"whisper_api_key"',
            '"comfyui_api_key"',
            '"runninghub_api_key"',
            '"minimax_api_key"',
            '"openai_api_key"',
            '"gemini_api_key"',
            '"openai_speech_api_key"',
            '"azure_speech_api_key"',
            '"minimax_speech_api_key"',
            '"voxcpm_api_key"',
            '"vibevoice_tts_api_key"',
            '"vibevoice_asr_api_key"',
        ],
        "Backend config masking whitelist for P0 AI workflow secrets is incomplete",
    )


def test_backend_config_save_whitelist_includes_ai_article_and_video_fields():
    text = SERVER_MAIN.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            '"whisper_api_key"',
            '"whisper_compute_type"',
            '"whisper_device"',
            '"whisper_chunk_seconds"',
            '"whisper_language"',
            '"article_tools_path"',
            '"article_output_dir"',
            '"video_gen_output_dir"',
            '"comfyui_api_key"',
            '"runninghub_api_key"',
            '"image_generation_provider"',
            '"image_generation_fallback_order"',
            '"minimax_api_key"',
            '"openai_api_key"',
            '"gemini_api_key"',
            '"default_scene_count"',
            '"default_template"',
            '"voice_provider"',
            '"voice_fallback_order"',
            '"voice_flow_defaults_json"',
            '"voice_output_dir"',
            '"voice_require_disclosure"',
            '"voice_allow_reference_clone"',
            '"voice_allow_prompt_transcript_clone"',
            '"voice_max_text_chars"',
            '"transcription_provider"',
            '"openai_speech_api_key"',
            '"azure_speech_api_key"',
            '"minimax_speech_api_key"',
            '"voxcpm_api_key"',
            '"vibevoice_tts_api_key"',
            '"vibevoice_asr_api_key"',
        ],
        "Backend config save whitelist for P0 AI workflows is incomplete",
    )


def test_frontend_app_config_includes_ai_article_and_video_fields():
    text = CONFIG_API.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            "whisper_api_key?: string",
            "whisper_compute_type?: string",
            "whisper_device?: string",
            "whisper_chunk_seconds?: number",
            "whisper_language?: string",
            "article_tools_path?: string",
            "article_output_dir?: string",
            "video_gen_output_dir?: string",
            "comfyui_api_key?: string",
            "runninghub_api_key?: string",
            "image_generation_provider?: string",
            "minimax_api_key?: string",
            "openai_api_key?: string",
            "gemini_api_key?: string",
            "default_template?: string",
            "default_scene_count?: number",
            "voice_provider?: string",
            "voice_fallback_order?: string",
            "voice_flow_defaults_json?: string",
            "voice_output_dir?: string",
            "voice_require_disclosure?: boolean",
            "voice_allow_reference_clone?: boolean",
            "voice_allow_prompt_transcript_clone?: boolean",
            "voice_max_text_chars?: number",
            "transcription_provider?: string",
            "openai_speech_api_key?: string",
            "azure_speech_api_key?: string",
            "minimax_speech_api_key?: string",
            "voxcpm_api_key?: string",
            "vibevoice_tts_api_key?: string",
            "vibevoice_asr_api_key?: string",
        ],
        "Frontend AppConfig contract for P0 AI workflows is incomplete",
    )


def test_ai_settings_masks_new_ai_workflow_secrets_with_round_trip_preservation():
    text = AI_SETTINGS.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            "whisperApiKeyInput",
            "comfyuiApiKeyInput",
            "runninghubApiKeyInput",
            "minimaxApiKeyInput",
            "openaiApiKeyInput",
            "geminiApiKeyInput",
            "payload.whisper_api_key = MASKED_SECRET_VALUE",
            "whisper_compute_type",
            "whisper_device",
            "whisper_chunk_seconds",
            "whisper_language",
            "payload.comfyui_api_key = MASKED_SECRET_VALUE",
            "payload.runninghub_api_key = MASKED_SECRET_VALUE",
            "payload.minimax_api_key = MASKED_SECRET_VALUE",
            "payload.openai_api_key = MASKED_SECRET_VALUE",
            "payload.gemini_api_key = MASKED_SECRET_VALUE",
            "openaiSpeechApiKeyInput",
            "azureSpeechApiKeyInput",
            "minimaxSpeechApiKeyInput",
            "voxcpmApiKeyInput",
            "vibevoiceTtsApiKeyInput",
            "vibevoiceAsrApiKeyInput",
            "payload.openai_speech_api_key = MASKED_SECRET_VALUE",
            "payload.azure_speech_api_key = MASKED_SECRET_VALUE",
            "payload.minimax_speech_api_key = MASKED_SECRET_VALUE",
            "payload.voxcpm_api_key = MASKED_SECRET_VALUE",
            "payload.vibevoice_tts_api_key = MASKED_SECRET_VALUE",
            "payload.vibevoice_asr_api_key = MASKED_SECRET_VALUE",
        ],
        "AiSettings does not yet preserve masked P0 AI workflow secrets",
    )


def test_ai_settings_exposes_anthropic_llm_provider_option():
    settings_text = AI_SETTINGS.read_text(encoding="utf-8")
    zh_text = ZH_LOCALE.read_text(encoding="utf-8")
    en_text = EN_LOCALE.read_text(encoding="utf-8")

    _require_snippets(
        settings_text + zh_text + en_text,
        [
            "value: 'anthropic'",
            "t('config.llmAnthropic')",
            '"llmAnthropic": "Anthropic"',
        ],
        "AiSettings LLM provider dropdown does not expose the Anthropic-compatible provider",
    )

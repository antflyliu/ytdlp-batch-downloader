from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_SETTINGS = ROOT / "frontend-vue" / "src" / "views" / "settings" / "AiSettings.vue"


def test_ai_settings_does_not_bind_masked_secret_to_password_input():
    text = AI_SETTINGS.read_text(encoding="utf-8")

    assert 'v-model:value="llmApiKeyInput"' in text
    assert 'v-model:value="form.llm_api_key"' not in text
    assert "form.llm_api_key = data.llm_api_key || ''" not in text


def test_ai_settings_preserves_saved_secret_when_masked_value_is_unedited():
    text = AI_SETTINGS.read_text(encoding="utf-8")

    assert "const MASKED_SECRET_VALUE = '***'" in text
    assert "hasSavedLlmApiKey.value = loadedLlmApiKey === MASKED_SECRET_VALUE" in text
    assert "llmApiKeyInput.value = hasSavedLlmApiKey.value ? '' : loadedLlmApiKey" in text
    assert "if (hasSavedLlmApiKey.value && !llmApiKeyInput.value)" in text
    assert "payload.llm_api_key = MASKED_SECRET_VALUE" in text

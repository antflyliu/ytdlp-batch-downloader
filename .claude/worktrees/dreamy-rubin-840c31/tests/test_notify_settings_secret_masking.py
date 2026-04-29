from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTIFY_SETTINGS = ROOT / "frontend-vue" / "src" / "views" / "settings" / "NotifySettings.vue"


def test_notify_settings_does_not_bind_masked_secrets_to_password_inputs():
    text = NOTIFY_SETTINGS.read_text(encoding="utf-8")

    assert 'v-model:value="dingtalkSecretInput"' in text
    assert 'v-model:value="telegramTokenInput"' in text
    assert 'v-model:value="form.global_dingtalk_sign_secret"' not in text
    assert 'v-model:value="form.global_telegram_token"' not in text
    assert "form.global_dingtalk_sign_secret = data.global_dingtalk_sign_secret || ''" not in text
    assert "form.global_telegram_token = data.global_telegram_token || ''" not in text


def test_notify_settings_preserves_saved_secrets_when_masked_values_are_unedited():
    text = NOTIFY_SETTINGS.read_text(encoding="utf-8")

    assert "const MASKED_SECRET_VALUE = '***'" in text
    assert "hasSavedDingtalkSecret.value = loadedDingtalkSecret === MASKED_SECRET_VALUE" in text
    assert "hasSavedTelegramToken.value = loadedTelegramToken === MASKED_SECRET_VALUE" in text
    assert "dingtalkSecretInput.value = hasSavedDingtalkSecret.value ? '' : loadedDingtalkSecret" in text
    assert "telegramTokenInput.value = hasSavedTelegramToken.value ? '' : loadedTelegramToken" in text
    assert "if (hasSavedDingtalkSecret.value && !dingtalkSecretInput.value)" in text
    assert "if (hasSavedTelegramToken.value && !telegramTokenInput.value)" in text
    assert "payload.global_dingtalk_sign_secret = MASKED_SECRET_VALUE" in text
    assert "payload.global_telegram_token = MASKED_SECRET_VALUE" in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "frontend-vue" / "src" / "views"


def read_view(name: str) -> str:
    return (VIEWS / name).read_text(encoding="utf-8")


def test_global_settings_keeps_masked_secrets_out_of_password_inputs():
    text = read_view("settings/GlobalSettings.vue")

    assert 'v-model:value="dingtalkSecretInput"' in text
    assert 'v-model:value="telegramTokenInput"' in text
    assert 'v-model:value="form.global_dingtalk_sign_secret"' not in text
    assert 'v-model:value="form.global_telegram_token"' not in text
    assert "payload.global_dingtalk_sign_secret = MASKED_SECRET_VALUE" in text
    assert "payload.global_telegram_token = MASKED_SECRET_VALUE" in text


def test_accounts_omits_unedited_masked_account_secrets_from_payload():
    text = read_view("Accounts.vue")

    assert 'v-model:value="dingtalkSignSecretInput"' in text
    assert 'v-model:value="telegramBotTokenInput"' in text
    assert 'v-model:value="formData.dingtalk_sign_secret"' not in text
    assert 'v-model:value="formData.telegram_bot_token"' not in text
    assert "data.telegram_bot_token = MASKED_SECRET_VALUE" not in text
    assert "data.dingtalk_sign_secret = MASKED_SECRET_VALUE" not in text
    assert "if (token) data.telegram_bot_token = token" in text
    assert "if (signSecret) data.dingtalk_sign_secret = signSecret" in text


def test_api_key_edit_form_does_not_show_masked_key_as_editable_value():
    text = read_view("ApiKeys.vue")

    assert ':placeholder="keyValuePlaceholder"' in text
    assert "form.key_value = k.key_value" not in text
    assert "form.key_value = ''" in text
    assert "keyValueSavedPlaceholder" in text


def test_dynamic_provider_secret_inputs_use_saved_placeholders_and_preserve_sentinels():
    text = read_view("DynamicProviders.vue")

    assert "const MASKED_SECRET_VALUE = '***'" in text
    assert "hasSavedRotatingPassword.value = row.adapter_type === 'rotating_gateway' && !!cfg.password" in text
    assert "hasSavedListAuthPassword.value = (" in text
    assert "hasSavedLocalProxyUrl.value = row.adapter_type === 'local_gateway' && !!cfg.local_proxy_url" in text
    assert "form.value.config.password = cfg.password ? '***' : ''" not in text
    assert "cfg.password = MASKED_SECRET_VALUE" in text
    assert "cfg.local_proxy_url = MASKED_SECRET_VALUE" in text


def test_proxy_pool_edit_form_preserves_existing_masked_proxy_url_when_unedited():
    text = read_view("ProxyPools.vue")

    assert ':placeholder="proxyUrlPlaceholder"' in text
    assert "formData.proxy_url = node.proxy_url" not in text
    assert "const body: { name: string; enabled: boolean; proxy_url?: string }" in text
    assert "if (!editingNode.value || formData.proxy_url.trim())" in text

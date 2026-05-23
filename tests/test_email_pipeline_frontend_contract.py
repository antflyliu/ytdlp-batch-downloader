from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EMAIL_PIPELINE_VIEW = ROOT / "frontend-vue" / "src" / "views" / "EmailPipeline.vue"
EMAIL_API = ROOT / "frontend-vue" / "src" / "api" / "email.ts"
SERVER_MAIN = ROOT / "server" / "__main__.py"
FRONTEND = ROOT / "frontend-vue" / "src"


def test_gmail_one_click_oauth_does_not_preselect_existing_account():
    text = EMAIL_PIPELINE_VIEW.read_text(encoding="utf-8")

    assert "selectedGmailAuthAccountId.value = gmailIds[0]" not in text
    assert "const selectedAccountId = accountId || selectedGmailAuthAccountId.value || null" in text
    assert "...(selectedAccountId ? { account_id: selectedAccountId } : {})" in text
    assert "readPending" in text
    assert "sendPending" in text


def test_email_pipeline_exposes_outlook_email_source_fields():
    view_text = EMAIL_PIPELINE_VIEW.read_text(encoding="utf-8")
    api_text = EMAIL_API.read_text(encoding="utf-8")

    assert "{ label: 'outlookEmail', value: 'outlook_email' }" in view_text
    assert "accountForm.provider === 'outlook_email'" in view_text
    assert "outlook_email_base_url" in view_text
    assert "outlook_email_remote_email" in view_text
    assert "outlook_email_folder" in view_text
    assert "outlookEmailApiKeyInput" in view_text
    assert "accountForm.provider === 'imap'" in view_text
    assert "payload.outlook_email_api_key" in view_text
    assert "outlook_email_api_key?: string" in api_text
    assert "has_outlook_email_api_key?: boolean" in api_text


def test_email_pipeline_exposes_deep_reprocess_action_and_api_route():
    view_text = EMAIL_PIPELINE_VIEW.read_text(encoding="utf-8")
    api_text = EMAIL_API.read_text(encoding="utf-8")
    server_text = SERVER_MAIN.read_text(encoding="utf-8")

    assert "runReprocess" in view_text
    assert "emailPipeline.messages.reprocess" in view_text
    assert "reprocessMessage" in api_text
    assert "`/api/email/messages/${id}/reprocess`" in api_text
    assert 'path.endswith("/reprocess")' in server_text


def test_email_analysis_rules_are_part_of_config_contract():
    api_text = EMAIL_API.read_text(encoding="utf-8")
    server_text = SERVER_MAIN.read_text(encoding="utf-8")
    config_api_text = (ROOT / "frontend-vue" / "src" / "api" / "config.ts").read_text(encoding="utf-8")
    config_settings_text = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")

    assert "email_analysis_rules?: Record<string, unknown>" in config_api_text
    assert '"email_analysis_rules"' in server_text
    assert '"email_analysis_rules": {}' in config_settings_text
    assert "ReprocessMessagePayload" in api_text


def test_email_analysis_rules_settings_center_contract_is_wired():
    api_text = EMAIL_API.read_text(encoding="utf-8")
    router_text = (FRONTEND / "router" / "index.ts").read_text(encoding="utf-8")
    hub_text = (FRONTEND / "views" / "SettingsHub.vue").read_text(encoding="utf-8")
    sider_text = (FRONTEND / "components" / "layout" / "AppSider.vue").read_text(encoding="utf-8")
    header_text = (FRONTEND / "components" / "layout" / "AppHeader.vue").read_text(encoding="utf-8")
    zh_text = (FRONTEND / "locales" / "zh.json").read_text(encoding="utf-8")
    en_text = (FRONTEND / "locales" / "en.json").read_text(encoding="utf-8")
    settings_page = FRONTEND / "views" / "settings" / "EmailAnalysisRulesSettings.vue"
    settings_text = settings_page.read_text(encoding="utf-8")

    assert settings_page.is_file()
    assert "EmailAnalysisRulesState" in api_text
    assert "raw_rules?: unknown" in api_text
    assert "normalized_rules?: Record<string, unknown>" in api_text
    assert "getAnalysisRules" in api_text
    assert "'/api/email/analysis-rules'" in api_text
    assert "'/api/email/analysis-rules/validate'" in api_text
    assert "'/api/email/analysis-rules/import'" in api_text
    assert "'/api/email/analysis-rules/export'" in api_text
    assert "'/api/email/analysis-rules/restore'" in api_text
    assert "settingsEmailAnalysisRules" in router_text
    assert "@/views/settings/EmailAnalysisRulesSettings.vue" in router_text
    assert "/settings-hub/email-analysis-rules" in hub_text
    assert "settings.emailAnalysisRulesTitle" in hub_text
    assert "settingsEmailAnalysisRules" in sider_text
    assert "settingsEmailAnalysisRules" in header_text
    assert "settingsEmailAnalysisRules" in zh_text
    assert "settingsEmailAnalysisRules" in en_text
    assert "data.raw_rules" in settings_text


def test_resource_index_defers_heavy_preview_and_decrypt_modules():
    resource_text = (FRONTEND / "views" / "ResourceIndex.vue").read_text(encoding="utf-8")
    action_text = (FRONTEND / "components" / "ResourceAction.vue").read_text(encoding="utf-8")
    preview_text = (FRONTEND / "components" / "Preview.vue").read_text(encoding="utf-8")
    vite_text = (ROOT / "frontend-vue" / "vite.config.ts").read_text(encoding="utf-8")

    assert "defineAsyncComponent" in resource_text
    assert "import('@/components/Preview.vue')" in resource_text
    assert "import('@/components/ResourceAction.vue')" in resource_text
    assert "import { getDecryptionArray } from '@/assets/js/decrypt.js'" not in action_text
    assert "await import('@/assets/js/decrypt.js')" in action_text
    assert 'import videojs from "video.js"' not in preview_text
    assert 'import flvjs from "flv.js"' not in preview_text
    assert 'await import("video.js")' in preview_text
    assert 'await import("flv.js")' in preview_text
    assert "manualChunks(id)" in vite_text
    assert "vendor-vue" in vite_text
    assert "vendor-media-video" in vite_text

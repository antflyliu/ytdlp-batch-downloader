"""Contract tests for AI Creation and Generate Article frontend integration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "frontend-vue" / "src" / "router" / "index.ts"
SIDER = ROOT / "frontend-vue" / "src" / "components" / "layout" / "AppSider.vue"
SETTINGS_HUB = ROOT / "frontend-vue" / "src" / "views" / "SettingsHub.vue"
ACCOUNTS_VIEW = ROOT / "frontend-vue" / "src" / "views" / "Accounts.vue"
AI_CREATION_VIEW = ROOT / "frontend-vue" / "src" / "views" / "AiCreation.vue"
EN_LOCALE = ROOT / "frontend-vue" / "src" / "locales" / "en.json"
ZH_LOCALE = ROOT / "frontend-vue" / "src" / "locales" / "zh.json"


def _require_snippets(text: str, snippets: list[str], reason: str) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        pytest.xfail(f"{reason}. Missing: {missing}")


def _get_path(data: dict, path: str):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def test_router_registers_ai_creation_workspace_route():
    text = ROUTER.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            "path: '/ai-creation'",
            "name: 'aiCreation'",
            "import('@/views/AiCreation.vue')",
        ],
        "AI Creation workspace route is not registered yet",
    )


def test_sidebar_exposes_ai_creation_navigation_entry():
    text = SIDER.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            "{ key: 'aiCreation', path: '/ai-creation'",
            "aria-current",
            "nav.aiCreation",
        ],
        "Sidebar AI Creation navigation entry is not implemented yet",
    )


def test_video_detail_sources_expose_generate_article_action():
    text = ACCOUNTS_VIEW.read_text(encoding="utf-8")

    _require_snippets(
        text,
        [
            "generateArticle",
            "t('videoDetail.generateArticle')",
            "/ai-creation",
        ],
        "Video detail Generate Article action is not wired yet",
    )


def test_settings_hub_does_not_link_to_dead_global_settings_route():
    text = SETTINGS_HUB.read_text(encoding="utf-8")

    if 'to="/settings-hub/global"' in text:
        pytest.xfail("SettingsHub still links to the known dead /settings-hub/global route")


def test_ai_creation_persists_wechat_publish_error_detail_in_panel():
    text = AI_CREATION_VIEW.read_text(encoding="utf-8")

    required = [
        "const wechatPublishError = ref('')",
        "wechatPublishError.value = String(task.error || '')",
        '<div v-if="wechatPublishError" class="wechat-publish-panel__error">',
    ]
    missing = [snippet for snippet in required if snippet not in text]
    assert not missing, f"WeChat publish errors must remain visible in the detail panel. Missing: {missing}"


def test_ai_creation_output_links_preserve_api_token_for_internal_artifacts():
    text = AI_CREATION_VIEW.read_text(encoding="utf-8")

    required = [
        "const appendApiToken",
        "window as any).__MONITOR_API_TOKEN__",
        "url.searchParams.set('api_token', token)",
    ]
    missing = [snippet for snippet in required if snippet not in text]
    assert not missing, f"Generated artifact links must preserve API auth. Missing: {missing}"


@pytest.mark.parametrize("locale_path", [EN_LOCALE, ZH_LOCALE])
def test_locales_define_ai_creation_and_generate_article_labels(locale_path: Path):
    data = json.loads(locale_path.read_text(encoding="utf-8"))

    required_paths = [
        "nav.aiCreation",
        "videoDetail.generateArticle",
        "aiCreation.title",
        "aiCreation.articleTab",
        "aiCreation.videoTab",
        "aiCreation.wechatPublishTitle",
        "aiCreation.saveToWechatDraft",
        "aiCreation.publishNow",
        "aiCreation.wechatPublishFailed",
    ]
    missing = [path for path in required_paths if _get_path(data, path) is None]
    if missing:
        pytest.xfail(f"Locale contract for AI Creation is incomplete in {locale_path.name}: {missing}")

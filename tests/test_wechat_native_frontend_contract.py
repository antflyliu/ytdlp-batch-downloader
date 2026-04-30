from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_wechat_frontend_route_and_nav_are_wired():
    router = (ROOT / "frontend-vue" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
    sider = (ROOT / "frontend-vue" / "src" / "components" / "layout" / "AppSider.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend-vue" / "src" / "api" / "wechatNativeCollect.ts").read_text(encoding="utf-8")
    zh = (ROOT / "frontend-vue" / "src" / "locales" / "zh.json").read_text(encoding="utf-8")
    en = (ROOT / "frontend-vue" / "src" / "locales" / "en.json").read_text(encoding="utf-8")

    assert "/wechat-native-collect" in router
    assert "WechatNativeCollect.vue" in router
    assert "wechatNativeCollect" in sider
    assert "/api/wechat-native/login/start" in api
    assert "/api/wechat-native/tasks/start" in api
    assert '"wechatNativeCollect"' in zh
    assert '"wechatNativeCollect"' in en


def test_native_wechat_result_links_to_ai_creation():
    native_view = (ROOT / "frontend-vue" / "src" / "views" / "WechatNativeCollect.vue").read_text(encoding="utf-8")
    ai_view = (ROOT / "frontend-vue" / "src" / "views" / "AiCreation.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend-vue" / "src" / "api" / "wechatNativeCollect.ts").read_text(encoding="utf-8")
    request = (ROOT / "frontend-vue" / "src" / "api" / "request.ts").read_text(encoding="utf-8")

    assert "openAiCreation" in native_view
    assert "sourceType" in native_view
    assert "wechatArticle" in native_view
    assert "articleArtifact" in native_view
    assert "articlePath" in native_view
    assert "getQrcodeBlob" in api
    assert "responseType: 'blob'" in api
    assert "loginQrObjectUrl" in native_view
    assert "api_token" not in native_view
    assert "api_token" not in request or "useQueryToken" in request
    assert "getQueryString('sourceType')" in ai_view or "getQueryString(\"sourceType\")" in ai_view
    assert "getQueryString('articleArtifact')" in ai_view or "getQueryString(\"articleArtifact\")" in ai_view
    assert "getQueryString('articlePath')" in ai_view or "getQueryString(\"articlePath\")" in ai_view
    assert "wechat_artifact_id" in ai_view
    assert "videoUrl: String(item.url" not in native_view
    assert "openWechatPublish" in native_view
    assert "publishIntent: 'wechatDraft'" in native_view
    assert "getQueryString('publishIntent')" in ai_view or "getQueryString(\"publishIntent\")" in ai_view
    assert "normalizeWechatPublishIntent" in ai_view
    assert "pendingWechatPublishTaskId.value = taskId" in ai_view
    assert "pendingWechatPublishAutoSubmit" in ai_view
    assert "async function maybeAutoSubmitPendingWechatPublish" in ai_view
    assert "await submitArticleTask()" in ai_view
    assert "const autoSubmitted = await maybeAutoSubmitPendingWechatPublish()" in ai_view
    assert "maybeSubmitPendingWechatPublish" in ai_view
    assert "submitWechatPublish(mode)" in ai_view
    assert "confirmPublishSelectedArticleNow()" in ai_view
    assert "previewNextPage" in native_view
    assert "previewPreviousPage" in native_view


def test_native_wechat_account_results_are_bounded_scroll_panel():
    native_view = (ROOT / "frontend-vue" / "src" / "views" / "WechatNativeCollect.vue").read_text(encoding="utf-8")
    zh = (ROOT / "frontend-vue" / "src" / "locales" / "zh.json").read_text(encoding="utf-8")
    en = (ROOT / "frontend-vue" / "src" / "locales" / "en.json").read_text(encoding="utf-8")

    assert "account-list account-list--bounded" in native_view
    assert ".account-list--bounded" in native_view
    assert "max-height: clamp(" in native_view
    assert "overflow-y: auto;" in native_view
    assert "scrollbar-gutter: stable;" in native_view
    assert ".account-item:focus-visible" in native_view
    assert "account-item__body" in native_view
    assert "wechatNativeCollect.accountCount" in native_view
    assert '"accountCount": "{n} 个账号"' in zh
    assert '"accountCount": "{n} accounts"' in en


def test_existing_wechat_collect_page_identifies_exporter_path():
    collect_view = (ROOT / "frontend-vue" / "src" / "views" / "WechatCollect.vue").read_text(encoding="utf-8")
    zh = (ROOT / "frontend-vue" / "src" / "locales" / "zh.json").read_text(encoding="utf-8")
    en = (ROOT / "frontend-vue" / "src" / "locales" / "en.json").read_text(encoding="utf-8")

    assert "wechatCollect.exporterNotice" in collect_view
    assert "wechat-article-exporter" in zh
    assert "wechat-article-exporter" in en

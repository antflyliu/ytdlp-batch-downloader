# Bugfix Report: WeChat Native Download Link Normalization

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

In the native WeChat collection page, clicking the download button for a previewed article could fail with `文章链接不合法`. The preview and task result areas also did not show the article's original URL, making it hard to inspect which source article a download result belonged to.

**Reproduction steps:**
1. Open the native WeChat collection page and preview articles for an account.
2. Click the download button on a preview item whose backend link is returned as `http://mp.weixin.qq.com/s?...` or contains HTML-escaped query separators.
3. Observe `文章链接不合法` instead of a local download task.

**Impact:** Native WeChat article downloads could fail for valid article links returned by the WeChat backend. Users also lacked direct source-link visibility in preview and task result areas.

## Investigation Summary

- **Symptoms examined:** Download action rejected valid WeChat article links before creating a task.
- **Code inspected:** `monitor/wechat_collect/models.py`, `monitor/wechat_collect/tasks.py`, `monitor/wechat_collect/html_export.py`, `server/__main__.py`, `frontend-vue/src/views/WechatNativeCollect.vue`.
- **Hypotheses tested:** Frontend payload shape regression, backend task serializer issue, strict article URL validator. The strict validator matched the observed failure.

## Discovered Root Cause

The article URL validator only accepted `https://mp.weixin.qq.com/s...`. The WeChat backend can return valid article links as `http://mp.weixin.qq.com/s?...`, protocol-relative links, or HTML-escaped URLs such as `&amp;` in query strings. These were rejected before the task could start.

**Defect type:** Overly strict validation / missing normalization.

**Why it occurred:** URL validation was written for canonical article URLs but was reused on upstream backend URLs without first normalizing them.

**Contributing factors:** The preview UI submitted selected article links directly from upstream article metadata.

## Resolution for the Issue

**Changes made:**
- `monitor/wechat_collect/models.py` - Added `normalize_mp_article_url()` and made validation/preview normalization accept backend HTTP and escaped links.
- `monitor/wechat_collect/tasks.py` - Normalizes selected article links before validation, download, and result persistence.
- `monitor/wechat_collect/html_export.py` - Normalizes article URL before HTTP download.
- `server/__main__.py` - Normalizes selected article URLs and direct article URL payloads before task creation.
- `frontend-vue/src/views/WechatNativeCollect.vue` - Shows original article links in preview items and task result rows.
- `frontend-vue/src/locales/zh.json` / `frontend-vue/src/locales/en.json` - Added original-link labels.

**Approach rationale:** Centralizing URL normalization keeps strict host/path validation while accepting real backend URL variants. UI changes expose the source link without changing task storage semantics.

**Alternatives considered:**
- Loosen the regex to accept `http` directly - rejected because it would still miss escaped/protocol-relative variants and would not canonicalize persisted task results.
- Normalize only in the frontend - rejected because API callers and background services would still hit the same bug.

## Regression Test

**Test files:** `tests/test_wechat_native_client.py`, `tests/test_wechat_native_tasks.py`, `tests/test_wechat_native_frontend_contract.py`

**Test names:**
- `test_mp_article_url_normalization_accepts_backend_http_and_escaped_links`
- `test_native_collection_urls_mode_normalizes_backend_article_links`
- `test_native_wechat_result_links_to_ai_creation`

**What they verify:** Valid WeChat backend article links are normalized and accepted; task downloads use the normalized URL; preview and task result UI contain source-link display hooks.

**Run command:** `python -m pytest tests/test_wechat_native_client.py tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py`

## Affected Files

| File | Change |
|------|--------|
| `monitor/wechat_collect/models.py` | Added canonical article URL normalization. |
| `monitor/wechat_collect/tasks.py` | Normalized selected article URLs before task download. |
| `monitor/wechat_collect/html_export.py` | Normalized article URLs before fetching article HTML. |
| `server/__main__.py` | Normalized API task-start payload URLs. |
| `frontend-vue/src/views/WechatNativeCollect.vue` | Added original-link display in preview and task result areas. |
| `frontend-vue/src/locales/zh.json` | Added Chinese original-link label. |
| `frontend-vue/src/locales/en.json` | Added English original-link label. |
| `tests/test_wechat_native_client.py` | Added URL normalization regression coverage. |
| `tests/test_wechat_native_tasks.py` | Added selected-article HTTP-link download regression coverage. |
| `tests/test_wechat_native_frontend_contract.py` | Added frontend source-link contract checks. |

## Verification

**Automated:**
- [x] Regression test passes
- [x] Native WeChat related test suite passes
- [x] Frontend production build passes

**Manual verification:**
- No live WeChat session was used. Verification was based on regression tests covering the rejected URL shape and on Vite production build compilation.

## Prevention

**Recommendations to avoid similar bugs:**
- Validate canonicalized URLs, not raw upstream URLs.
- Keep URL normalization in shared backend model code rather than UI-only helpers.
- Preserve task-result source URLs in UI so future link-shape issues are easier to diagnose.

## Related

- User report: native WeChat preview download button shows `文章链接不合法`.

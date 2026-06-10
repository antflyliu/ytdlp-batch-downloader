# Bugfix Report: WeChat Native Task Result Download Flow

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

On the native WeChat collection page, the article preview list and the task result list exposed visually similar download actions but executed different behaviours. The left preview action started a native collection download task, saving the article through the server-side collection pipeline. The right task-result action downloaded the existing artifact Blob through the browser, which could save to the browser's download location instead of the configured/native collection output directory.

**Reproduction steps:**
1. Open the native WeChat collection page and select a completed task with successful article results.
2. Click the right-side task result "Download file" action.
3. Observe the browser file download flow instead of a new native collection download task like the left-side "Download" action.

**Impact:** Users could get different save-location behaviour from two download buttons in the same workflow, making the right-side action inconsistent with the preview download action.

## Investigation Summary

- **Symptoms examined:** The screenshot showed left-side "Download" and right-side "Download file" controls in the same page behaving differently.
- **Code inspected:** `frontend-vue/src/views/WechatNativeCollect.vue`, `frontend-vue/src/api/wechatNativeCollect.ts`, `monitor/wechat_collect/tasks.py`, `server/__main__.py`, and existing native WeChat tests.
- **Hypotheses tested:** Backend artifact endpoint issue, task serializer issue, and frontend action divergence. The frontend divergence matched the behaviour.

## Discovered Root Cause

The task-result `downloadArtifact()` handler fetched `/api/wechat-native/artifacts/{id}` as a Blob, created a browser object URL, and clicked a temporary anchor with `link.download`. The preview download handler instead called `startArticleDownload()`, which posts selected article URLs to `/api/wechat-native/tasks/start`.

**Defect type:** Inconsistent frontend action routing.

**Why it occurred:** The task result action was implemented as an artifact export/download shortcut while the preview action later standardized on server-side native collection task creation.

**Contributing factors:** The task result button label ("Download file") made the old browser-download behaviour look acceptable even though users expected it to match the preview download workflow.

## Resolution for the Issue

**Changes made:**
- `frontend-vue/src/views/WechatNativeCollect.vue` - Changed the right-side task result download button to use the same `startingTask` loading state and call `startArticleDownload([item], ...)` instead of downloading an artifact Blob.
- `tests/test_wechat_native_frontend_contract.py` - Added a regression test proving `downloadArtifact()` reuses the article download task flow and no longer calls `getArtifactBlob`, `URL.createObjectURL`, or `link.download`.

**Approach rationale:** Reusing the existing preview download path keeps article downloads consistently routed through the native collection task API while still allowing the output directory to come from the current page configuration. That output directory can differ from the original task artifact's location, so the fix avoids assuming the existing artifact path is the desired save target.

**Alternatives considered:**
- Add another backend endpoint to copy artifacts into a configured output directory - rejected because it would duplicate task output semantics and bypass the collection/download pipeline.
- Keep Blob download but change the label - rejected because it would not address the inconsistent save-location behaviour.

## Regression Test

**Test file:** `tests/test_wechat_native_frontend_contract.py`

**Test name:** `test_native_wechat_task_result_download_reuses_article_download_flow`

**What it verifies:** The right-side task result download handler delegates to `startArticleDownload([item], ...)`, uses the shared `startingTask` loading state, and does not perform browser Blob downloads.

**Run command:** `python -m pytest -q tests/test_wechat_native_frontend_contract.py`

## Affected Files

| File | Change |
|------|--------|
| `frontend-vue/src/views/WechatNativeCollect.vue` | Rewired right-side task result download to start a native article download task. |
| `tests/test_wechat_native_frontend_contract.py` | Added contract coverage for task-result download flow consistency. |
| `specs/bugfixes/wechat-native-task-result-download-flow/report.md` | Documented the bug, root cause, fix, and verification. |

## Verification

**Automated:**
- [x] Regression test passes: `python -m pytest -q tests/test_wechat_native_frontend_contract.py`
- [x] Native WeChat focused tests pass: `python -m pytest -q tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py`
- [x] Frontend production build passes: `npm run build` from `frontend-vue`

**Manual verification:**
- No live WeChat session was used. Behaviour was verified through frontend contract tests and Vite compilation.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep same-page actions with the same label/intent routed through a shared handler.
- Add contract tests around workflow entry points, not just route/API presence.
- Avoid direct browser artifact downloads when the user intent is a server-side collection/download task.

## Related

- User report: right-side native WeChat task-result "Download file" should match the left-side article preview download action.

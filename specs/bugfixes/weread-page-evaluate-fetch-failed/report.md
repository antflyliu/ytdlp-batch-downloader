# Bugfix Report: WeRead Page Evaluate Fetch Failed

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

WeRead exports could fail while reading book metadata with an internal Playwright error:

`Page.evaluate: TypeError: Failed to fetch`

**Reproduction steps:**
1. Open the WeRead exporter page.
2. Use a reusable debug Chrome session.
3. Start an export for a readable WeRead book.
4. Observe the task fail during metadata loading with `Page.evaluate: TypeError: Failed to fetch`.

**Impact:** The task failed before chapter export started, even when Chrome CDP was available and the user had logged in.

## Investigation Summary

- **Symptoms examined:** The task error came from Playwright `page.evaluate()` and included a browser-side `fetch` failure.
- **Code inspected:** `monitor/weread_exporter/core.py` and `tests/test_weread_exporter_integration.py`.
- **Hypotheses tested:** Login state missing, Chrome CDP unavailable, invalid book id, and metadata fetch running from the wrong browser origin.

## Discovered Root Cause

`WeReadPlaywrightRunner.fetch_book_meta()` opened a new blank page and executed browser JavaScript that called `fetch('https://i.weread.qq.com/...', { credentials: 'include' })`. Running the request from `about:blank` made the request vulnerable to browser page-context fetch/CORS failure, which surfaced as `Page.evaluate: TypeError: Failed to fetch`.

**Defect type:** Browser-context networking misuse.

**Why it occurred:** Metadata reads were implemented as page JavaScript instead of using Playwright's BrowserContext-bound request API.

**Contributing factors:** The previous implementation did not have a regression test that rejected metadata fetches through `page.evaluate`.

## Resolution for the Issue

**Changes made:**
- `monitor/weread_exporter/core.py` - Changed metadata reads to use `context.request.get/post`, which shares the browser context cookies but does not run through page JavaScript CORS.
- `monitor/weread_exporter/core.py` - Added response validation and clearer `WeReadExportError` messages for metadata HTTP/JSON/network failures.
- `monitor/weread_exporter/core.py` - Kept a page-based fallback for contexts without `request`, but it now navigates to WeRead first and validates response status.
- `tests/test_weread_exporter_integration.py` - Added a regression test proving metadata fetches use `context.request` and do not call `page.evaluate`.

**Approach rationale:** `context.request` is the correct Playwright surface for authenticated API calls tied to the same browser context. It keeps logged-in cookies while avoiding page-origin fetch failures.

**Alternatives considered:**
- Keep `page.evaluate` and add retries - rejected because retries do not fix the origin/CORS failure.
- Fetch from Python `urllib` - rejected because it would require manually extracting and synchronizing browser cookies.

## Regression Test

**Test file:** `tests/test_weread_exporter_integration.py`
**Test name:** `test_weread_runner_fetches_book_meta_with_context_request`

**What it verifies:** Metadata retrieval calls BrowserContext `request.get/post`, forwards the expected WeRead payload, normalizes book/chapter metadata, and does not create a page for `page.evaluate`.

**Run command:** `python -m pytest tests/test_weread_exporter_integration.py tests/test_monitor_server_static_auth.py -q`

## Affected Files

| File | Change |
|------|--------|
| `monitor/weread_exporter/core.py` | Uses BrowserContext request API for WeRead metadata and wraps failures clearly. |
| `tests/test_weread_exporter_integration.py` | Adds regression coverage for context-request metadata fetching. |
| `specs/bugfixes/weread-page-evaluate-fetch-failed/report.md` | Documents root cause, fix, and verification. |

## Verification

**Automated:**
- [x] Regression test fails before the fix and passes after the fix.
- [x] `python -m pytest tests/test_weread_exporter_integration.py tests/test_monitor_server_static_auth.py -q`
- [x] `python -m ruff check monitor\weread_exporter\core.py tests\test_weread_exporter_integration.py`
- [x] `python -m compileall monitor\weread_exporter tests\test_weread_exporter_integration.py`
- [ ] Full repository test suite was not run because the workspace already contains many unrelated in-progress changes.

**Manual verification:**
- The fix removes the browser `page.evaluate(fetch(...))` path for normal Playwright contexts, so the screenshot's `Page.evaluate: TypeError: Failed to fetch` failure mode is no longer used for metadata retrieval.

## Prevention

**Recommendations to avoid similar bugs:**
- Use BrowserContext `request` for authenticated API reads when page rendering is not required.
- Reserve `page.evaluate` for DOM/canvas extraction, not cross-origin API fetches.
- Add endpoint/request-path tests whenever a browser automation flow depends on logged-in API calls.

## Related

- `specs/bugfixes/weread-chrome-cdp-not-detected/report.md`
- `specs/bugfixes/weread-chrome-cdp-reuse/`
- `specs/bugfixes/weread-editable-cdp-settings-and-pending-start/report.md`

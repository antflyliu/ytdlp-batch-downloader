# Bugfix Report: WeRead Current Web API Export

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

The WeRead exporter failed for the reader URL:

`https://weread.qq.com/web/reader/4a232bb05c71d64a2ea0506k1ff325f02181ff1de7742fc`

The export either failed before chapter export while reading book metadata, or failed during chapter navigation when the reader page never reached Playwright `networkidle`.

**Reproduction steps:**
1. Start the local web service.
2. Start a WeRead export for the target reader URL through `/api/weread-exporter/tasks/start`.
3. Reuse the visible Chrome CDP session that is already logged in to WeRead.
4. Observe metadata/login errors from the old API path, or a chapter timeout during reader navigation.

**Impact:** Users could not reliably export the target WeRead book, and a valid web login could still be treated as unusable.

## Investigation Summary

- **Symptoms examined:** The Chrome profile could render WeRead web pages, but `i.weread.qq.com/book/info` returned `401 LOGIN ERR`. The reader URL parsed to `4a232bb05c71d64a2ea0506`, while the current WeRead web APIs use `815574` for this book. Chapter export also timed out when waiting for `networkidle`.
- **Code inspected:** `monitor/weread_exporter/core.py`, `monitor/weread_exporter/tasks.py`, `server/__main__.py`, and `tests/test_weread_exporter_integration.py`.
- **Hypotheses tested:** Expired Chrome login, missing CDP cookies, wrong book ID, current web API drift, and Playwright waiting on background WeRead network traffic.

## Discovered Root Cause

The exporter still depended on the legacy `i.weread.qq.com` metadata APIs and assumed the reader URL key was the same ID needed by the current web API. For the target book, WeRead's current web reader exposes reader key `4a232bb05c71d64a2ea0506`, but `/web/book/readInfo` and `/web/book/outline` require web book ID `815574`.

**Defect type:** Upstream API drift and identifier mapping bug.

**Why it occurred:** The original implementation was built around older WeRead API endpoints. WeRead's current browser app now uses `weread.qq.com/web/...` endpoints and separate IDs for reader routes and book metadata.

**Contributing factors:**
- Login validation checked insufficient state and could force unnecessary re-login.
- `networkidle` is unstable on the WeRead reader because background web requests can keep the page busy.

## Resolution for the Issue

**Changes made:**
- `monitor/weread_exporter/core.py` - Added current web session validation through `wr_vid` and `/web/user`.
- `monitor/weread_exporter/core.py` - Added Chrome CDP reuse support so exports use the same debug Chrome profile/session after the first login.
- `monitor/weread_exporter/core.py` - Added reader-page metadata discovery to map reader key `4a232bb05c71d64a2ea0506` to web book ID `815574`.
- `monitor/weread_exporter/core.py` - Added current web metadata fetching through `/web/book/readInfo` and `/web/book/outline`.
- `monitor/weread_exporter/core.py` - Kept the old `i.weread.qq.com` metadata path as a fallback for compatibility.
- `monitor/weread_exporter/core.py` - Changed chapter navigation to `domcontentloaded` so export is not blocked by background network activity.
- `monitor/weread_exporter/tasks.py` - Prepares a reusable Chrome CDP session before running export tasks.
- `tests/test_weread_exporter_integration.py` - Added regression coverage for current web metadata, Chrome CDP reuse, login reuse, and chapter navigation.

**Approach rationale:** The fix follows the browser application's current API surface while preserving the old metadata path as a fallback. Login reuse is validated against the current web session endpoint, so a user only needs to log in again when WeRead reports the web session is invalid.

**Alternatives considered:**
- Keep calling `i.weread.qq.com` only - rejected because it returned `401 LOGIN ERR` with an otherwise valid web login.
- Use the reader key as the web metadata book ID - rejected because the target book's current web book ID is `815574`.
- Continue using `networkidle` with a larger timeout - rejected because background traffic makes it non-deterministic.

## Regression Test

**Test file:** `tests/test_weread_exporter_integration.py`

**Test names:**
- `test_weread_runner_prefers_current_web_reader_metadata`
- `test_weread_runner_fetch_chapter_does_not_wait_for_networkidle`
- `test_weread_runner_reuses_valid_web_session_without_opening_login`
- `test_weread_runner_auto_mode_prefers_existing_chrome_cdp`
- `test_weread_task_service_auto_starts_cdp_before_runner`

**What it verifies:** The exporter resolves current WeRead web metadata, uses the reader key for chapter URLs, avoids `networkidle` timeouts, reuses a valid logged-in web session without opening a login page, and starts/reuses Chrome CDP for task execution.

**Run command:** `venv_build\Scripts\python.exe -m pytest tests\test_weread_exporter_integration.py -q`

## Affected Files

| File | Change |
|------|--------|
| `monitor/weread_exporter/core.py` | Current WeRead web API support, login/session validation, Chrome CDP context reuse, and chapter navigation timeout fix. |
| `monitor/weread_exporter/tasks.py` | Task-level Chrome CDP preparation and endpoint/profile propagation. |
| `tests/test_weread_exporter_integration.py` | Regression tests for the repaired export flow. |
| `specs/bugfixes/weread-current-web-api-export/report.md` | Root-cause and verification record. |

## Verification

**Automated:**
- [x] `venv_build\Scripts\python.exe -m pytest tests\test_weread_exporter_integration.py -q`
- [x] `venv_build\Scripts\python.exe -m pytest tests\test_monitor_server_static_auth.py -q`
- [x] `venv_build\Scripts\python.exe -m ruff check monitor\weread_exporter\core.py monitor\weread_exporter\tasks.py tests\test_weread_exporter_integration.py`
- [x] `venv_build\Scripts\python.exe -m py_compile monitor\weread_exporter\core.py monitor\weread_exporter\tasks.py tests\test_weread_exporter_integration.py`
- [ ] Full repository test suite was not run because the workspace contains many unrelated in-progress changes.

**Manual verification:**
- Started a fresh local service on port `5057` with the project virtual environment.
- Submitted a clean export to `data\weread_exports\codex_verify_20260609_1781007206`.
- Verified task `wrd_bf2e2622fa08` completed with `status=done`, `total=15`, `success=15`, `failed=0`, and `skipped=0`.
- Verified merged Markdown artifact: `data\weread_exports\codex_verify_20260609_1781007206\商业的本质.md`.
- Verified task metadata includes `web_book_id=815574` and `reader_book_id=4a232bb05c71d64a2ea0506`.

## Prevention

**Recommendations to avoid similar bugs:**
- Prefer the same API family used by the live web app when exporting from browser sessions.
- Treat CDP availability, Chrome profile reuse, and WeRead login validity as separate checks.
- Keep regression coverage for current reader URLs whose route key differs from the web metadata book ID.
- Avoid `networkidle` on pages with known background polling or analytics traffic.

## Related

- `specs/bugfixes/weread-book-info-login-err/report.md`
- `specs/bugfixes/weread-chrome-cdp-reuse/report.md`
- `specs/bugfixes/weread-page-evaluate-fetch-failed/report.md`

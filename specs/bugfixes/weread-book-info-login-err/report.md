# Bugfix Report: WeRead Book Info Login Err

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

After restarting the Web UI and retrying the WeRead export, the task failed while reading metadata with:

`微信读书元数据请求失败：book/info HTTP 401 LOGIN ERR`

**Reproduction steps:**
1. Start the WeRead exporter with a reusable Chrome CDP session.
2. Submit a WeRead book URL.
3. The runner reports Chrome CDP as available.
4. The export fails at `book/info` with HTTP 401 `LOGIN ERR`.

**Impact:** The task failed before chapter export started. Users saw a backend API error even though the UI showed a reusable Chrome session.

## Investigation Summary

- **Symptoms examined:** `book/info` returned HTTP 401 `LOGIN ERR` from `i.weread.qq.com`.
- **Code inspected:** `monitor/weread_exporter/core.py` login check and metadata fetch flow.
- **Hypotheses tested:** Missing route, broken fetch transport, missing cookies in context request, and expired/invalid WeRead login credentials.

## Discovered Root Cause

The runner treated a Chrome CDP connection and a non-login URL as proof of WeRead login. That was not enough: WeRead can still return `401 LOGIN ERR` when the short-lived API login state is missing or expired. `ensure_login()` only checked whether the page URL contained `login`, so it incorrectly allowed the export to continue into metadata fetching.

**Defect type:** Login-state validation bug.

**Why it occurred:** The previous login check validated browser navigation state, not the actual WeRead API state needed by `book/info`.

**Contributing factors:** Chrome CDP availability was displayed as reusable session availability, but that does not guarantee WeRead API authentication.

## Resolution for the Issue

**Changes made:**
- `monitor/weread_exporter/core.py` - Added `_book_info_session_valid()` to probe the current book's `book/info` endpoint before export continues.
- `monitor/weread_exporter/core.py` - Updated `ensure_login()` to accept `book_id`, open the login page when `book/info` returns 401, and wait until the API login probe succeeds.
- `monitor/weread_exporter/core.py` - Updated `run_async()` to pass the target `book_id` into `ensure_login()`.
- `monitor/weread_exporter/core.py` - Kept page-session metadata fallback for cases where `context.request` lacks a valid login state.
- `tests/test_weread_exporter_integration.py` - Added regression coverage for 401 fallback and login waiting.

**Approach rationale:** The export depends on WeRead API authentication, so the login gate should validate the same API surface before moving to metadata extraction.

**Alternatives considered:**
- Treat CDP availability as logged-in state - rejected because it still allows expired WeRead credentials through.
- Immediately fail on 401 - rejected because the user can recover by logging in through the debug Chrome window.

## Regression Test

**Test file:** `tests/test_weread_exporter_integration.py`
**Test names:**
- `test_weread_runner_falls_back_to_page_fetch_when_context_request_is_unauthorized`
- `test_weread_runner_ensure_login_waits_when_book_info_returns_401`

**What it verifies:** A 401 from `context.request` no longer ends the task immediately, and `ensure_login()` waits for a real `book/info` login probe to succeed before continuing.

**Run command:** `python -m pytest tests/test_weread_exporter_integration.py tests/test_monitor_server_static_auth.py -q`

## Affected Files

| File | Change |
|------|--------|
| `monitor/weread_exporter/core.py` | Validates WeRead API login state and waits for re-login on 401. |
| `tests/test_weread_exporter_integration.py` | Adds regression tests for 401 login handling. |
| `specs/bugfixes/weread-book-info-login-err/report.md` | Documents root cause, fix, and verification. |

## Verification

**Automated:**
- [x] 401 login-state regression tests pass.
- [x] `python -m pytest tests/test_weread_exporter_integration.py tests/test_monitor_server_static_auth.py -q`
- [x] `python -m ruff check monitor\weread_exporter\core.py tests\test_weread_exporter_integration.py`
- [x] `python -m compileall monitor\weread_exporter tests\test_weread_exporter_integration.py`
- [ ] Full repository test suite was not run because the workspace already contains many unrelated in-progress changes.

**Manual verification:**
- Confirmed the local CDP session can reproduce `book/info HTTP 401 LOGIN ERR`.
- The runner now handles that state by opening the debug Chrome login flow instead of immediately failing at metadata fetch.

## Prevention

**Recommendations to avoid similar bugs:**
- Validate login using the same authenticated API that the export path depends on.
- Keep CDP availability and application login state separate in UI/backend assumptions.
- Add regression tests for recoverable authentication failures, not only transport failures.

## Related

- `specs/bugfixes/weread-page-evaluate-fetch-failed/report.md`
- `specs/bugfixes/weread-chrome-cdp-reuse/report.md`
- `specs/bugfixes/weread-editable-cdp-settings-and-pending-start/report.md`

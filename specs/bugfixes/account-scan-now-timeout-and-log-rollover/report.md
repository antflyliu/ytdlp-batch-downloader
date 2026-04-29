# Bugfix Report: Account Scan Now Timeout and Log Rollover

**Date:** 2026-04-25
**Status:** Fixed

## Description of the Issue

Clicking "立即扫描" on the account management page could fail or time out while the server printed repeated `--- Logging error ---` blocks. The logs showed `PermissionError: [WinError 32]` during `ytdl.log` rotation, followed by YouTube API connection timeouts.

**Reproduction steps:**
1. Start the monitor server on Windows with a large or rollover-ready `logs/ytdl.log`.
2. Trigger an account scan from the account management page.
3. Observe repeated rollover errors and, when YouTube is unreachable, repeated playlist page attempts until the frontend request times out.

**Impact:** Manual account scans were unreliable on Windows, especially when the log file needed rotation or the network path to YouTube was unavailable.

## Investigation Summary

- **Symptoms examined:** Windows file-lock rollover failures, synchronous scan endpoint timeout, repeated playlist page fetch attempts after `WinError 10060`.
- **Code inspected:** `logging_config.py`, `server/__main__.py`, `monitor/scheduler.py`, `monitor/fetcher.py`, `ytb_api.py`, existing scan and playlist retry tests.
- **Hypotheses tested:** Frontend button binding failure was ruled out by existing scan-now tests; the backend scan path was reaching `_scan_account`. The failure was caused by backend logging and retry behavior.

## Discovered Root Cause

`logging_config.get_logger()` created a separate `RotatingFileHandler` for every named logger, all targeting `logs/ytdl.log`. On Windows, one handler can keep the file open while another tries to rename it during rollover, causing `WinError 32`.

Separately, `/api/accounts/scan` waited for the full scan to finish before returning to the browser, while playlist/search pagination handlers caught transient API exceptions and continued the loop without advancing the page token. Persistent network failures retried the same request until the frontend's 30-second timeout was hit.

**Defect type:** Windows file-lock race, synchronous endpoint timeout, and retry-loop control-flow bug.

**Why it occurred:** Logging was intended to be shared, but the handler was not actually shared. API error handling treated page fetch errors as skippable, but there was no safe way to skip without a valid next page token.

**Contributing factors:** Windows rename semantics are stricter than POSIX; the scan endpoint runs synchronously; the YouTube HTTP client previously used default socket timeout behavior.

## Resolution for the Issue

**Changes made:**
- `logging_config.py:36` - Added `WindowsSafeRotatingFileHandler`, which skips locked rollover attempts and still writes the current record.
- `logging_config.py:54` - Added a singleton shared file handler for all named loggers.
- `logging_config.py:69` - Updated `get_logger()` to reuse the shared handler and disable propagation.
- `monitor/scheduler.py:526` - Added per-account manual scan locks.
- `monitor/scheduler.py:891` - Added `trigger_scan_async()` to run manual scans in a daemon background thread and reject duplicate in-flight scans for the same account.
- `server/__main__.py:1529` - Changed the scan API to enqueue the scan and return immediately with queue status.
- `ytb_api.py:18` - Added configurable YouTube API timeout with a safe 15-second default.
- `ytb_api.py:68` - Created the YouTube API client with bounded `httplib2.Http(timeout=...)`.
- `ytb_api.py:501` and `ytb_api.py:530` - Stop playlist scanning after page/detail API errors to avoid repeating the same page.
- `ytb_api.py:657` and `ytb_api.py:687` - Applied the same loop guard to search mode.

**Approach rationale:** This keeps the existing scan implementation and log file location, but changes the Web endpoint to a trigger-style contract that matches the UI message ("scan triggered"). Network instability is recorded in scan events/logs instead of blocking the HTTP request.

**Alternatives considered:**
- Disable log rotation entirely - rejected because it would allow unbounded log growth.
- Increase the frontend request timeout - rejected because it would still leave the browser blocked on external YouTube network behavior.
- Retry playlist page fetch multiple times - rejected because a single OS-level connect timeout can already approach the frontend timeout budget.

## Regression Test

**Test files:**
- `tests/test_logging_config_windows_rollover.py`
- `tests/test_account_scan_async_trigger.py`
- `tests/test_ytb_api_playlist_retry.py`

**Test names:**
- `test_trigger_scan_async_starts_daemon_thread_and_rejects_duplicate`
- `test_account_scan_endpoint_queues_background_scan`
- `test_safe_rotating_handler_keeps_logging_when_rollover_file_is_locked`
- `test_get_logger_reuses_one_file_handler_for_all_named_loggers`
- `test_collector_uses_bounded_http_timeout_for_youtube_client`
- `test_breaks_after_playlist_page_error_without_repeating_same_request`
- `test_breaks_after_search_page_error_without_repeating_same_request`

**What they verify:** The scan API queues background work and returns immediately; duplicate in-flight manual scans for the same account are rejected; locked rollover no longer emits logging errors or drops records; loggers share one handler; YouTube clients use bounded HTTP timeout; playlist/search loops stop after page errors instead of repeating the same request.

**Run command:** `python -m pytest tests\test_logging_config_windows_rollover.py tests\test_ytb_api_playlist_retry.py -q`

## Affected Files

| File | Change |
|------|--------|
| `logging_config.py` | Shared safe rotating handler for Windows lock-safe logging |
| `monitor/scheduler.py` | Async manual scan trigger and duplicate in-flight scan guard |
| `server/__main__.py` | Scan API now queues manual scan and returns immediately |
| `ytb_api.py` | Bounded YouTube HTTP timeout and safe loop exit on API page/detail errors |
| `tests/test_account_scan_async_trigger.py` | Regression coverage for async scan API behavior |
| `tests/test_logging_config_windows_rollover.py` | Regression coverage for safe logging behavior |
| `tests/test_ytb_api_playlist_retry.py` | Regression coverage for timeout and non-repeating retry behavior |

## Verification

**Automated:**
- [x] Regression tests pass: `11 passed`
- [x] Related scan/channel tests pass: `27 passed`
- [x] Syntax compile passes: `python -m compileall logging_config.py ytb_api.py monitor\scheduler.py server\__main__.py`
- [ ] Full suite pass not confirmed: `python -m pytest -q` timed out after 304 seconds without failure output.

**Manual verification:**
- Reviewed the supplied stack trace against the updated logging and scan loop paths.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep file handlers singleton per process when multiple named loggers write to one file.
- Avoid `continue` after API page-fetch errors unless the code can advance to a different page token.
- Keep user-facing synchronous endpoints within the frontend timeout budget, or move long-running scans to background jobs.

## Related

- Existing scan-now binding coverage: `tests/test_accounts_scan_now_es_module_bindings.py`

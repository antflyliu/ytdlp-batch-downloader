# Bugfix Report: WeRead Chrome CDP Not Detected

## Summary

The WeRead exporter UI could show "Chrome CDP not detected" even after the previous CDP reuse work. The app only detected a CDP endpoint; it did not provide a way to create one from inside the workflow.

## Root Cause

The backend checked `http://127.0.0.1:9222/json/version`, but the application still opened the UI through normal browser launch paths such as `webbrowser.open()`. A normally started Chrome process does not expose Chrome DevTools Protocol, and Playwright cannot retrofit CDP onto that running process.

## Fix

- Added Chrome executable discovery in `monitor/weread_exporter/core.py`.
- Added `launch_chrome_cdp()` / `ensure_chrome_cdp()` to start Chrome with:
  - `--remote-debugging-port=9222`
  - `--user-data-dir=<data>/weread_chrome_cdp_profile`
  - `https://weread.qq.com/web/shelf`
- Exposed a backend endpoint: `POST /api/weread-exporter/chrome/start`.
- Updated WeRead export task execution to try preparing Chrome CDP before creating the Playwright runner in auto mode.
- Updated the frontend to show an "Open Debug Chrome" action when CDP is missing.
- Added config fields for launchability and the dedicated debug Chrome profile directory.

## Behavior

The first click opens a dedicated debug Chrome window. The user signs in to WeRead in that window once; subsequent exports reuse that profile through CDP. If Chrome cannot be found or the CDP port still does not respond, the existing isolated Chromium fallback remains available in auto mode.

## Verification

1. `python -m pytest tests/test_weread_exporter_integration.py -q` passes: 11 tests.
2. `python -m ruff check server\__main__.py monitor\weread_exporter tests\test_weread_exporter_integration.py` passes.
3. `python -m compileall monitor\weread_exporter server` passes.
4. Locale JSON validation passes for `frontend-vue/src/locales/zh.json` and `frontend-vue/src/locales/en.json`.
5. `npm run build` in `frontend-vue` passes.

## Files Changed

| File | Change |
|---|---|
| `monitor/weread_exporter/core.py` | Added Chrome discovery and debug Chrome launch helpers. |
| `monitor/weread_exporter/tasks.py` | Exposed CDP launch metadata and auto-starts CDP before exports. |
| `server/__main__.py` | Added `POST /api/weread-exporter/chrome/start`. |
| `frontend-vue/src/api/wereadExporter.ts` | Added API/config fields for debug Chrome startup. |
| `frontend-vue/src/views/WeReadExporter.vue` | Added an action to open debug Chrome and display its profile directory. |
| `frontend-vue/src/locales/zh.json` | Updated WeRead exporter copy and debug Chrome labels. |
| `frontend-vue/src/locales/en.json` | Updated WeRead exporter copy and debug Chrome labels. |
| `tests/test_weread_exporter_integration.py` | Added regression tests for debug Chrome launch and task preflight. |
| `docs/2026-06-06-weread-exporter-integration-analysis.md` | Documented the app-managed debug Chrome profile. |

## Remaining Risk

This does not automatically reuse cookies from an already-running normal Chrome profile. Chrome does not allow adding the remote debugging port to an existing normal process. The app-managed debug profile is the safe, repeatable path.

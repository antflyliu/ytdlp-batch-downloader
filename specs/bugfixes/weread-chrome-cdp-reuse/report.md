# Bugfix Report: WeRead Exporter Chrome Session Reuse

## Summary

The WeRead exporter always launched a separate Playwright Chromium persistent context. Users who were already signed in to WeRead in their normal Chrome browser still had to sign in again in the exporter window, which made the export workflow unnecessarily awkward.

## Root Cause

`WeReadPlaywrightRunner.run_async()` directly called `playwright.chromium.launch_persistent_context(...)` with the app-managed `weread_browser_profile` directory. That profile is intentionally isolated from the user's normal Chrome profile, so it cannot see cookies or login state from an already-open Chrome window.

Playwright also cannot attach to an arbitrary Chrome process after it has been started normally. Reusing an existing Chrome session requires Chrome DevTools Protocol access, typically by starting Chrome with `--remote-debugging-port=9222`.

## Fix

- Added an automatic browser selection path in `monitor/weread_exporter/core.py`.
- In `auto` mode, the runner first attempts `playwright.chromium.connect_over_cdp()` against `WEREAD_CHROME_CDP_ENDPOINT` or `http://127.0.0.1:9222`.
- If CDP is reachable, the exporter uses Chrome's default browser context and opens task pages as new tabs in the existing logged-in session.
- If CDP is not reachable, the runner falls back to the previous isolated Chromium persistent profile.
- Forced modes are available via environment:
  - `WEREAD_BROWSER_MODE=chrome_cdp`
  - `WEREAD_BROWSER_MODE=persistent`
  - `WEREAD_CHROME_CDP_ENDPOINT=http://127.0.0.1:9222`
- The config API and WeRead exporter UI now expose Chrome CDP availability and endpoint status.

## Safety

The CDP path does not read or copy Chrome profile files. It uses the browser context exposed by Chrome itself. The runner only closes pages it creates; it does not call `Browser.close()` on the connected Chrome instance.

## Verification

1. Regression test failed before implementation because `WeReadPlaywrightRunner` did not accept `browser_mode` or expose `_open_browser_context()`.
2. `python -m pytest tests/test_weread_exporter_integration.py -q` passes: 9 tests.
3. `python -m compileall monitor\weread_exporter` passes.
4. `python -m json.tool frontend-vue\src\locales\zh.json` and `frontend-vue\src\locales\en.json` pass.
5. `npm run build` in `frontend-vue` passes.

## Files Changed

| File | Change |
|---|---|
| `monitor/weread_exporter/core.py` | Added Chrome CDP browser mode, endpoint configuration, auto fallback, and browser session handling. |
| `monitor/weread_exporter/tasks.py` | Exposed CDP availability and configured endpoint through `/api/weread-exporter/config`. |
| `frontend-vue/src/api/wereadExporter.ts` | Added config fields for browser mode and Chrome CDP status. |
| `frontend-vue/src/views/WeReadExporter.vue` | Displays reusable Chrome session status and CDP endpoint. |
| `frontend-vue/src/locales/zh.json` | Updated WeRead exporter copy and CDP status labels. |
| `frontend-vue/src/locales/en.json` | Updated WeRead exporter copy and CDP status labels. |
| `tests/test_weread_exporter_integration.py` | Added regression coverage for CDP preference, fallback, and forced-CDP error reporting. |
| `docs/2026-06-06-weread-exporter-integration-analysis.md` | Documented Chrome CDP reuse and remaining operational constraint. |

## Remaining Risk

This cannot reuse a Chrome window that was already started without a remote debugging port. In that case, the UI will show Chrome CDP as unavailable and the exporter will use the isolated Chromium fallback.

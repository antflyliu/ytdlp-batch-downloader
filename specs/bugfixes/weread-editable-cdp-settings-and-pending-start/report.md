# Bugfix Report: WeRead Editable CDP Settings And Pending Start

## Summary

The WeRead exporter showed Chrome CDP details as read-only display text. Users could not change the debugging endpoint or debug Chrome profile directory from the page. Starting an export could also leave the task in `pending` forever when an older export worker was still holding the single-run lock.

## Root Cause

The UI treated `chrome_cdp_endpoint` and `chrome_cdp_profile_dir` as backend configuration output only. The start-export payload did not include user-provided CDP settings, and the backend always fell back to environment/default values.

Separately, `WeReadExportTaskService.run_task()` entered `with self._run_lock:` before loading and updating the task. If a previous export was still running or stuck, newer task threads blocked on the lock without updating the task status or timing out.

## Fix

- Changed the WeRead exporter form to include editable Chrome CDP endpoint and debug Chrome profile directory inputs.
- Sent those values in both `POST /api/weread-exporter/tasks/start` and `POST /api/weread-exporter/chrome/start`.
- Stored the submitted CDP settings in task `meta_json`.
- Passed the task-specific endpoint to `WeReadPlaywrightRunner`.
- Started debug Chrome with the task-specific endpoint/profile directory.
- Replaced indefinite lock blocking with a bounded wait. If the worker stays busy, the task becomes `error` with a clear message instead of remaining `pending`.

## Verification

1. `python -m pytest tests/test_weread_exporter_integration.py -q` passes: 12 tests.
2. `python -m ruff check monitor\weread_exporter monitor\db\queries\weread_exporter.py server\__main__.py tests\test_weread_exporter_integration.py` passes.
3. `python -m compileall monitor\weread_exporter monitor\db\queries server` passes.
4. Locale JSON validation passes for `frontend-vue/src/locales/zh.json` and `frontend-vue/src/locales/en.json`.
5. `npm run build` in `frontend-vue` passes.

## Files Changed

| File | Change |
|---|---|
| `frontend-vue/src/views/WeReadExporter.vue` | Added editable CDP endpoint/profile inputs and sends them to backend actions. |
| `frontend-vue/src/api/wereadExporter.ts` | Extended payload types for CDP settings. |
| `monitor/weread_exporter/core.py` | Added an option-aware CDP ensure helper. |
| `monitor/weread_exporter/tasks.py` | Stores CDP settings, starts Chrome with them, passes endpoint to runner, and bounds worker lock waiting. |
| `monitor/db/queries/weread_exporter.py` | Persists initial task metadata. |
| `server/__main__.py` | Passes submitted CDP settings into Chrome startup. |
| `tests/test_weread_exporter_integration.py` | Covers custom CDP settings propagation and busy-worker timeout. |
| `docs/2026-06-06-weread-exporter-integration-analysis.md` | Documents editable CDP settings and pending timeout behavior. |

## Remaining Risk

If an existing export is actively running, a new task may still wait briefly. It will no longer remain pending indefinitely; it fails clearly if the worker does not become available within the configured wait timeout.

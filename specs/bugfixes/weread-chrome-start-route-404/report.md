# Bugfix Report: WeRead Chrome Start Route 404

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

Clicking "打开调试 Chrome" called `POST /api/weread-exporter/chrome/start` on the local Web UI and received `{"error": "未知 API"}` with HTTP 404.

**Reproduction steps:**
1. Start the monitor Web UI on `http://127.0.0.1:4999`.
2. Open the WeRead exporter page.
3. Click "打开调试 Chrome".
4. Observe HTTP 404 from `POST /api/weread-exporter/chrome/start`.

**Impact:** Users could not open the app-managed debug Chrome session from the WeRead exporter page, so the export flow still fell back to an unfriendly login path.

## Investigation Summary

- **Symptoms examined:** The live `4999` service returned `{"error": "未知 API"}` for the Chrome start endpoint.
- **Code inspected:** `frontend-vue/src/api/wereadExporter.ts`, `frontend-vue/src/views/WeReadExporter.vue`, `monitor_ui.py`, `monitor_server.py`, `server/__main__.py`, and WeRead exporter task/core modules.
- **Hypotheses tested:** The frontend path was wrong, `monitor_server` used a different handler, the backend route was missing, and the running process had not loaded the current route table.

## Discovered Root Cause

The current source registers `POST /api/weread-exporter/chrome/start` in `server.__main__.MonitorHandler`, but the running `monitor_ui.py` process on port `4999` was stale and still returned through the unknown-API fallback. There was also no HTTP-level regression test proving that `monitor_server.MonitorHandler` exposes this route.

**Defect type:** Runtime stale server state plus missing route regression coverage.

**Why it occurred:** The WeRead Chrome CDP route had been added in the backend, but the already-running local Web UI process continued serving an older route table.

**Contributing factors:** The route was previously covered at service/task level, not through the real local HTTP handler used by the desktop Web UI.

## Resolution for the Issue

**Changes made:**
- `tests/test_monitor_server_static_auth.py` - Added a regression test that starts `monitor_server.MonitorHandler`, posts to `/api/weread-exporter/chrome/start`, and verifies the request reaches `_weread_export_service.start_chrome_cdp`.
- Restarted the stale `4999` Web UI process from the current workspace source.

**Approach rationale:** A real HTTP handler test catches the exact failure mode seen by the button without launching Chrome during tests.

**Alternatives considered:**
- Only restart the server - fixes the immediate local symptom but does not prevent route regressions.
- Move the route into `monitor_server.py` - unnecessary because `monitor_server.py` correctly re-exports `server.__main__.MonitorHandler`.

## Regression Test

**Test file:** `tests/test_monitor_server_static_auth.py`
**Test name:** `test_weread_chrome_start_endpoint_is_registered_on_monitor_server`

**What it verifies:** `POST /api/weread-exporter/chrome/start` is registered on the same `monitor_server.MonitorHandler` used by `monitor_ui.py`, returns JSON, and forwards endpoint/profile/initial URL options to the WeRead Chrome CDP service.

**Run command:** `python -m pytest tests/test_monitor_server_static_auth.py tests/test_weread_exporter_integration.py -q`

## Affected Files

| File | Change |
|------|--------|
| `tests/test_monitor_server_static_auth.py` | Added HTTP-level regression coverage for the WeRead debug Chrome start route. |
| `specs/bugfixes/weread-chrome-start-route-404/report.md` | Documented investigation, root cause, fix, and verification. |

## Verification

**Automated:**
- [x] Regression test passes.
- [x] WeRead exporter integration tests pass.
- [x] Relevant ruff check passes.
- [x] Relevant Python compile check passes.
- [ ] Full repository test suite was not run because the workspace has many unrelated in-progress changes.

**Manual verification:**
- Restarted `monitor_ui.py --browser` on `127.0.0.1:4999` from the current workspace.
- Confirmed `GET /api/status` returns successfully.
- Confirmed `POST /api/weread-exporter/chrome/start` returns HTTP 200 with Chrome CDP JSON instead of `{"error": "未知 API"}`.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep user-facing button endpoints covered through the real `monitor_server.MonitorHandler` HTTP path.
- Restart the local Web UI after backend route changes, or use `python monitor_ui.py --browser --force-restart` when validating newly added APIs.
- Include endpoint registration tests when adding new frontend API calls.

## Related

- `specs/bugfixes/weread-chrome-cdp-not-detected/report.md`
- `specs/bugfixes/weread-editable-cdp-settings-and-pending-start/report.md`

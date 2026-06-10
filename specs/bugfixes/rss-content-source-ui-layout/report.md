# Bugfix Report: RSS Content Source UI Layout

**Date:** 2026-06-07
**Status:** Fixed

## Description of the Issue

The RSS content source home page used a flatter, narrower layout than the WeChat native collector module. The feed form, feed list, item list, and OPML tools were arranged as simple cards, which made the page look visually inconsistent and allowed long item lists and action buttons to stretch or crowd the working area.

**Reproduction steps:**
1. Open the frontend application.
2. Navigate to the RSS content source page.
3. Compare the layout with the WeChat native collector page.
4. Observe that the RSS page lacks the same high-card workbench structure, bounded list regions, warm interactive item styling, and responsive handling.

**Impact:** Medium visual and usability impact for users managing RSS subscriptions and generated article tasks.

## Investigation Summary

- **Symptoms examined:** RSS page screenshot, feed sidebar width, item action alignment, list scrolling, card radius, active state styling, and mobile breakpoints.
- **Code inspected:** `frontend-vue/src/views/RssPipeline.vue`, `frontend-vue/src/views/WechatNativeCollect.vue`, `DESIGN.md`, and `frontend-vue/src/styles/variables.css`.
- **Hypotheses tested:** The issue was not caused by data loading or API behavior; it was isolated to the RSS page template and scoped CSS.

## Discovered Root Cause

The RSS page had not adopted the newer native-collector workbench pattern. It used local `.card` sections with smaller radii, no Naive UI card header structure, no bounded internal scroll frames, and a simple two-column grid that did not protect dense article rows from crowding.

**Defect type:** UI layout inconsistency / responsive styling defect.

**Why it occurred:** The RSS page was implemented before or separately from the warmer Claude-inspired module layout used by the WeChat native collector.

**Contributing factors:** The RSS page mixed form, feed list, article list, and OPML import/export controls without a clear workbench hierarchy.

## Resolution for the Issue

**Changes made:**
- `frontend-vue/src/views/RssPipeline.vue` - Replaced simple section cards with `NCard` workbench cards for feeds, OPML, and items.
- `frontend-vue/src/views/RssPipeline.vue` - Moved OPML import/export into the left control stack, matching the native collector control/workbench split.
- `frontend-vue/src/views/RssPipeline.vue` - Added bounded scroll frames for feed lists and article lists.
- `frontend-vue/src/views/RssPipeline.vue` - Added warm gradients, terracotta active states, larger radii, softer shadows, and stable hover/focus behavior.
- `frontend-vue/src/views/RssPipeline.vue` - Improved responsive behavior for item action wrapping and narrow-screen form stacking.
- `tests/test_rss_pipeline_frontend_contract.py` - Added regression coverage for the RSS workbench structure and key layout/style invariants.

**Approach rationale:** This keeps behavior and data flow unchanged while aligning the RSS page with the existing WeChat native collector visual system and the warm design language in `DESIGN.md`.

**Alternatives considered:**
- Global shared card abstraction - Rejected because the requested change is scoped to one page and the existing pages use local scoped styles.
- Full component extraction from WeChat native collector - Rejected because it would broaden the diff and risk changing unrelated module behavior.

## Regression Test

**Test file:** `tests/test_rss_pipeline_frontend_contract.py`

**Test names:**
- `test_rss_pipeline_imports_naive_components_used_in_template`
- `test_rss_pipeline_matches_native_collect_workbench_layout`

**What it verifies:** The RSS page imports the required Naive UI components and contains the expected workbench cards, sidebar stack, bounded scrolling, warm active styling, transition behavior, and responsive breakpoint.

**Run command:** `python -m pytest -q tests/test_rss_pipeline_frontend_contract.py`

## Affected Files

| File | Change |
|------|--------|
| `frontend-vue/src/views/RssPipeline.vue` | RSS page layout and scoped CSS updated to match native collector styling. |
| `tests/test_rss_pipeline_frontend_contract.py` | Added structural/style regression checks for the RSS workbench layout. |
| `specs/bugfixes/rss-content-source-ui-layout/report.md` | Bugfix documentation. |

## Verification

**Automated:**
- [x] Regression test passes: `python -m pytest -q tests/test_rss_pipeline_frontend_contract.py`
- [x] Frontend production build passes: `npm run build` from `frontend-vue`
- [x] TypeScript/Vue typecheck passes: `.\node_modules\.bin\vue-tsc.cmd --noEmit` from `frontend-vue`
- [x] Full test suite executed: `python -m pytest -q`
- [ ] Full test suite passes
- [x] Lint availability checked

**Manual verification:**
- Attempted `npm run dev -- --host 127.0.0.1 --port 5173`; blocked by `Error: spawn EPERM` while Vite loaded config through esbuild.
- Attempted `npm run preview -- --host 127.0.0.1 --port 4173`; blocked by the same `Error: spawn EPERM`.
- Completed browser verification against the production `dist` build by serving `frontend-vue/dist` with `python -m http.server` and using Playwright with mocked RSS API responses.
- Desktop screenshot: `specs/bugfixes/rss-content-source-ui-layout/rss-pipeline-desktop.png`
- Mobile screenshot: `specs/bugfixes/rss-content-source-ui-layout/rss-pipeline-mobile.png`
- Playwright verified `.rss-workbench`, `.rss-items-card`, `.rss-list-frame`, and `.rss-items-frame` exist; desktop and mobile screenshots are non-blank; desktop and mobile have no horizontal overflow.

**Full-suite result:**
- `python -m pytest -q` produced `958 passed, 13 failed, 1 warning`.
- The failures are outside the RSS UI change surface:
  - `test_go_proxy_integration.py` - Go proxy singleton/process startup.
  - `tests/test_batch_webui_contract.py` - legacy batch web UI copy/cancel expectations.
  - `tests/test_monitor_duration.py` - monitor fetch duration persistence fixture behavior.
  - `tests/test_provider_scheduler_ui.py` - dynamic provider scheduler UI expectations.
  - `tests/test_scheduler_confirm_bug_cancel.py` - scheduler cancel button restoration.
  - `tests/test_scheduler_confirm_modal_ui.py` - app confirm modal CSS selector expectations.
  - `tests/test_thumbnail_generator.py` - Pollinations thumbnail request path.
  - `tests/test_wechat_native_frontend_contract.py` - WeChat native request token contract text.

**Lint availability:**
- `frontend-vue/package.json` exposes `dev`, `build`, and `preview`; it has no lint script.
- No project-level `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, or `.flake8` lint configuration was found.
- `eslint`, `ruff`, and `flake8` were not available on `PATH`.
- `vue-tsc --noEmit` was used as the available frontend static check and passed.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep source-management pages on the same `NCard` workbench pattern where they combine controls and large lists.
- Add structural contract tests for high-risk page layouts when visual consistency is a product requirement.
- Prefer bounded internal scroll frames for long operational lists instead of allowing the page layout to grow unbounded.

## Related

- `DESIGN.md`
- `frontend-vue/src/views/WechatNativeCollect.vue`

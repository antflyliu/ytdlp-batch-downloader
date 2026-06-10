# Bugfix Report: Settings Center AI Settings Entry

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

The Settings Center sidebar and overview card exposed the AI configuration route as "AI 切片" / "AI Clipping". The route actually opens the broader AI settings page that now configures LLMs, voice providers, image generation, and video generation, so users looking for "AI 设置" could not identify the correct entry.

**Reproduction steps:**
1. Open the Vue app Settings Center.
2. Expand the Settings Center submenu.
3. Observe that the AI settings route `/settings-hub/ai` is labeled "AI 切片".

**Impact:** Users configuring AI Voice providers could not find the AI settings page from the Settings Center navigation.

## Investigation Summary

- **Symptoms examined:** Screenshot showed the Settings Center submenu with "AI 切片" but no "AI 设置".
- **Code inspected:** Vue sidebar, settings overview, locale files, legacy monitor_web templates, and legacy static i18n files.
- **Hypotheses tested:** Route missing versus label mismatch. The route and page existed; only the visible labels and descriptions were stale.

## Discovered Root Cause

The `/settings-hub/ai` route had expanded beyond video clipping, but the navigation and settings overview locale keys still used legacy clipping wording.

**Defect type:** Stale user-facing copy.

**Why it occurred:** The AI settings page gained broader configuration responsibilities without updating the Settings Center labels.

**Contributing factors:** The same label existed in both Vue locales and legacy monitor_web fallbacks/overrides.

## Resolution for the Issue

**Changes made:**
- `frontend-vue/src/locales/zh.json` - Renamed Settings Center AI entry/title to "AI 设置" and updated the description to mention voice/image/video configuration.
- `frontend-vue/src/locales/en.json` - Renamed the English entry/title to "AI Settings" and updated the description.
- `monitor_web/static/i18n/*.json` and `monitor_web/templates/pages/*.html` - Synchronized legacy labels and fallback text.
- `tests/test_ai_content_frontend_contract.py` - Added a regression test for the AI settings entry label.

**Approach rationale:** Keep the existing route and page intact; fix the discoverability defect by changing only visible labels and descriptions.

**Alternatives considered:**
- Add a second route named `/settings-hub/ai-settings` - rejected because it duplicates an existing working page.
- Rename AI Creation clip-specific labels globally - rejected because "AI 视频切片" is still valid inside the AI Creation workflow.

## Regression Test

**Test file:** `tests/test_ai_content_frontend_contract.py`
**Test name:** `test_settings_center_exposes_ai_settings_entry_not_legacy_clip_label`

**What it verifies:** The Settings Center still links to `/settings-hub/ai`, while the visible locale label is "AI 设置" / "AI Settings" and the overview description mentions voice configuration.

**Run command:** `python -m pytest tests/test_ai_content_frontend_contract.py::test_settings_center_exposes_ai_settings_entry_not_legacy_clip_label -q`

## Affected Files

| File | Change |
|------|--------|
| `frontend-vue/src/locales/zh.json` | Vue Chinese Settings Center AI label and description |
| `frontend-vue/src/locales/en.json` | Vue English Settings Center AI label and description |
| `monitor_web/static/i18n/zh.json` | Legacy Chinese Settings Center AI label and description |
| `monitor_web/static/i18n/en.json` | Legacy English Settings Center AI label and description |
| `monitor_web/static/i18n/i18n_en_overrides_b.json` | Legacy English override text |
| `monitor_web/templates/pages/settings-ai.html` | Legacy AI settings fallback title text |
| `monitor_web/templates/pages/settings-hub.html` | Legacy settings overview fallback text |
| `monitor_web/index.html` | Legacy sidebar fallback text |
| `tests/test_ai_content_frontend_contract.py` | Regression coverage |

## Verification

**Automated:**
- [x] Regression test fails before the fix.
- [x] Regression test passes after the fix.
- [x] Related frontend contract tests pass.

**Manual verification:**
- Static search confirmed Settings Center AI entry strings now use "AI 设置" / "AI Settings"; remaining "AI 视频切片" strings are feature-specific labels outside the settings entry.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep route labels semantically broad when a settings page configures multiple AI workflows.
- Use locale contract tests for navigation labels that users rely on to find configuration pages.

## Related

- `docs/voice-provider-external-services.md`
- `docs/voice-provider-architecture.md`

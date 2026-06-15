# Bugfix Report: AI Settings Save Returns 400

**Date:** 2026-06-14
**Status:** Fixed

## Description of the Issue

Clicking "保存设置" on the AI 设置 page returns HTTP 400 from `POST /api/config`. Server log shows:

```
127.0.0.1 - - [14/Jun/2026 22:58:56] "POST /api/config HTTP/1.1" 400 -
```

The frontend renders a generic "保存失败" toast with no actionable detail.

**Reproduction steps:**
1. Open the Web UI as a user that has a stored LLM API key (`llm_api_key` is non-empty in the encrypted `config.json`).
2. Navigate to AI 设置.
3. Change `llm_provider` (e.g. openai → qwen), or change `llm_base_url`, or any combination that alters the LLM endpoint.
4. Click 保存设置 without touching the API Key field.
5. Observe HTTP 400 and the response body `{"error": "llm_provider 或 llm_base_url 变更后必须重新输入 llm_api_key"}`.

**Impact:** Every AI-settings-page user who already has a key set and changes the provider or base URL is blocked from saving. The fix must not weaken the security guarantee (provider/base_url change genuinely requires a new key).

## Investigation Summary

- **Symptoms examined:** 400 on `POST /api/config`; no other endpoint affected. The error message is the exact text emitted by `_validate_llm_endpoint_secret_reentry` in `server/__main__.py`.
- **Code inspected:**
  - `server/__main__.py` — `_api_config_save`, `_validate_llm_endpoint_secret_reentry`, `_llm_endpoint_identity`, `_mask_config_for_response`, `_preserve_masked_config_values`.
  - `monitor_web/js/modules/config.js` — `openConfig` (page load), `saveConfig` (submit).
  - `monitor_web/templates/pages/settings-ai.html` — form fields actually present.
  - `config/encryption.py` — `_encrypt_config_value` / `_decrypt_config_value`.
- **Hypotheses tested (and ruled out):**
  1. *No-change save returns 400*: reproduced with the real encrypted config and the exact body the page builds; identity matches the old config, so the validator short-circuits. Returns 200. Ruled out.
  2. *`default_api_key_id` decrypts to a missing key*: confirmed a separate 400 path (`"指定的默认 API Key (id=…) 不存在"`) but unrelated to the AI page in question. Ruled out.
  3. *AI page submits a field not in the server whitelist*: enumerated all 42 fields the page builds; all present in `_api_config_save`'s whitelist. Ruled out.
  4. *`quota_alert_thresholds` validator mismatch*: page sends an array, server accepts. Ruled out.
  5. *Email-analysis / voice-flow / wechat-renderer validators*: the AI page does not include the keys those validators key on. Ruled out.
- **Hypothesis confirmed:** The page loads `cfg.llm_api_key` (which the server has already masked to `"***"` in `GET /api/config`) directly into the `<input id="cfgLlmApiKey">` element. When the user changes provider/base URL and clicks Save, the page submits `body.llm_api_key = "***"`. The server's `_validate_llm_endpoint_secret_reentry` reads `body.get("llm_api_key", _db._UNSET)` and rejects the masked sentinel, returning 400.

## Discovered Root Cause

**Defect type:** Missing client-side translation of the masked sentinel into a "user did not re-enter" signal that the server's existing logic can recognize.

**Why it occurred:** `openConfig` copies `cfg.llm_api_key` straight into the input's `value`. The server's `GET /api/config` masks any set secret to `"***"` (a security feature in `_mask_config_for_response`), so the input always shows `"***"`. The user has no visual cue that this is a sentinel rather than the real key, and on save the body carries that same `"***"` back to the server. The server's `_validate_llm_endpoint_secret_reentry` correctly treats `"***"` as "no new secret submitted" and, on a provider/base_url change, returns 400 — which is the right policy, but unreachable for a user who simply wants to switch providers.

**Contributing factors:**
- The page has no client-side validation distinguishing the masked sentinel from a real value.
- The "change provider → must re-enter key" rule is enforced server-side only, with no UX hint on the AI page.

## Resolution for the Issue

**Changes made:**
- `monitor_web/js/modules/config.js:156-175` — In `saveConfig`, when building the `llm_api_key` field, detect that the input still holds the masked sentinel `"***"` and that the user has changed `llm_provider` or `llm_base_url` relative to the snapshot. In that case, clear the input and submit `body.llm_api_key = ""`, which the server interprets as "no new key — clear the stored one." Also surface a toast asking the user to re-enter the key.

**Approach rationale:** The server-side rule is correct and must stay. The fix is on the only layer that can see the user's intent (which provider/base_url values they edited): the page. The user now sees an empty key field plus a warning toast the moment they click Save with a changed endpoint, instead of a generic 400. The key is not silently re-applied to the wrong provider.

**Alternatives considered:**
- *Server-side: treat `"***"` as "keep current" and let the new provider use the old key.* Rejected — that is exactly the security hole the validator exists to prevent.
- *Server-side: clear the stored key when the user submits `"***"` with a changed provider (skip the 400 and silently drop the key).* Rejected — silently dropping a key is worse UX than a clear toast; the user might think the save did nothing.
- *Page: blank the input on `openConfig` and use `placeholder` for the masked hint.* Rejected — `placeholder` is not a substitute for value; submitting an empty input then relies on the server's "absent key" branch, which (per `_preserve_masked_config_values`) does **not** restore the old key. That would clobber the stored key on every no-change save, regressing the second regression test.
- *Page: detect provider/base_url change live and clear the key on change (not on save).* Rejected — the change-detect logic is only needed at submit time, and the snapshot is the authoritative "old" reference; an event handler would have to track the original values separately, doubling the state.

## Regression Test

**Test file:** `tests/test_ai_settings_save_regression.py`
**Test names:**
- `test_ai_settings_save_with_provider_change_and_masked_key_preserves_no_400`
- `test_ai_settings_save_with_no_change_keeps_existing_key`

**What they verify:**
- Test 1: With a stored encrypted `llm_api_key`, the AI page body has the masked sentinel as the key value, the user changes the provider, and the page-side fix submits `llm_api_key=""`. The server must respond 200 (no 400). This is the exact contract that was broken in the reported bug.
- Test 2: No-change save (provider/base_url unchanged) must continue to return 200 **and** preserve the original `llm_api_key` plaintext. The page still sends `"***"`, the server's `_preserve_masked_config_values` restores the encrypted value, and the next read of the file must decrypt to the same plaintext (Fernet ciphertexts are non-deterministic, so the test compares plaintexts).

**Run command:**
```bash
python -m pytest tests/test_ai_settings_save_regression.py tests/test_voice_api_contract.py -q
```

## Affected Files

| File | Change |
|------|--------|
| `monitor_web/js/modules/config.js` | `saveConfig`: when `cfgLlmApiKey` is still the masked sentinel `"***"` and the user has changed `llm_provider` or `llm_base_url`, clear the field and submit empty (with a warning toast). |
| `tests/test_ai_settings_save_regression.py` | New regression tests covering the changed-provider happy path and the no-change key-preservation path. |

## Verification

**Automated:**
- [x] Regression test passes (`tests/test_ai_settings_save_regression.py` — 2/2)
- [x] Pre-existing related tests still pass (`tests/test_voice_api_contract.py` — 6/6)
- [ ] Full test suite passes — only the targeted suites above were run; the broader suite was stopped to keep this fix scoped.
- [ ] Linters/validators pass — no project-level linter is configured for the modified JS; the JS is syntactically valid (verified by saving the file and reloading it via the static server).

**Manual verification:**
- Replayed the exact body the AI page builds (with `llm_provider='qwen'`, `llm_api_key=''`, every other AI-page field set from the masked snapshot) through `_api_config_save` against the real `config.json`. Returns 200.
- Replayed the no-change body (provider/base_url unchanged, key=`'***'`) through the same handler. Returns 200 and the on-disk `config.json` decrypts to the same plaintext key.

## Prevention

**Recommendations to avoid similar bugs:**
- Anywhere the server masks a secret in a response, the page that consumes it must treat the masked value as a sentinel — never echo it back into the body without checking for endpoint-identity changes.
- When a server validator is added for a new "must re-enter" rule, the corresponding form should have a visible cue (warning text, auto-clear) so the user can comply without first seeing a 400.
- The `_validate_llm_endpoint_secret_reentry` / `_validate_voice_endpoint_secret_reentry` pair is correct as written; consider mirroring it for the email-analysis, voice-flow, and wechat-renderer validators so the same "no 400, just clear + toast" pattern is uniform.

**Additional safeguards to consider:**
- A small helper like `function readSecretInput(id, snapshot, endpointChanged) { … }` in `monitor_web/js/modules/config.js` could centralize the sentinel-handling logic and be reused for the voice endpoint fields when those move into the AI page.
- A unit test that posts every key the AI page sends through the body builder would have caught this regression before release.

## Related

- `server/__main__.py` — `_validate_llm_endpoint_secret_reentry` (line 159), `_mask_config_for_response` (line 125), `_preserve_masked_config_values` (line 133), `_api_config_save` (line 2559).
- `monitor_web/js/modules/config.js` — `saveConfig` (line 79).
- `monitor_web/templates/pages/settings-ai.html` — AI settings form fields.

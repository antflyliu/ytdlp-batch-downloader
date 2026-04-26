# Bugfix Report: Vue I18n "Invalid linked format" Error

## Summary

Clicking "配置中心" (Settings Hub) in the sidebar caused a Vue I18n `SyntaxError: Invalid linked format` error in the browser console, preventing proper page rendering.

## Root Cause

**Vue I18n v9's message compiler treats `@` as a special character** that starts a "linked message" token (e.g., `@:otherKey` to reference another message, or `@.modifier:key` for modified references).

The project's locale JSON files (`zh.json`, `en.json`) contained literal `@` characters in message text that were being misinterpreted as linked message syntax:

| JSON Key | Message (before fix) | Issue |
|---|---|---|
| `setting.upstream_proxy_tip` | `...password@your.proxy.server...` | `@your.proxy.server` parsed as linked modifier |
| `config.channelUrlHint` | `@handle` | `@handle` parsed as linked key |
| `account.channelUrlPlaceholder` | `@C-HitShow / UCxxxx...` | `@C-HitShow` parsed as linked key |
| `config.telegramBotTokenHint` | `...@BotFather` | `@BotFather` parsed as linked key |
| `account.handlePlaceholder` | `@handle` | `@handle` parsed as linked key |
| `cache.confirmDeleteCache` | `@{handle}?` (en only) | `@{handle}` parsed as linked braced expression |

When Vue I18n's message compiler encounters `@` followed by text that doesn't form a valid linked message, it throws `INVALID_LINKED_FORMAT` (error code 10), which appears as `SyntaxError: Invalid linked format` in the browser console.

## Fix

Per Vue I18n v9 message syntax, literal `@` characters must be written as a literal interpolation expression (`{'@'}`) to prevent the compiler from treating them as linked message markers. Plain single quotes such as `'@'handle` are not sufficient; the compiler still reports `Invalid linked format`.

**zh.json** - 5 keys fixed:
- `setting.upstream_proxy_tip`: `password@your` → `password{'@'}your`
- `config.channelUrlHint`: `@handle` → `{'@'}handle`
- `account.channelUrlPlaceholder`: `@C-HitShow` → `{'@'}C-HitShow`
- `config.telegramBotTokenHint`: `@BotFather` → `{'@'}BotFather`
- `account.handlePlaceholder`: `@handle` → `{'@'}handle`

**en.json** - 6 keys fixed (same 5 as zh + `cache.confirmDeleteCache`):
- All the same keys as zh.json
- `cache.confirmDeleteCache`: `@{handle}` → `{'@'}{handle}`

## Verification

1. JSON validity: Both `zh.json` and `en.json` validated as valid JSON
2. Frontend build: `npm run build` succeeds without errors
3. Vue I18n compiler scan: every string in `zh.json` and `en.json` compiles with zero message-compiler errors
4. Regression test: `tests/test_locales_no_unescaped_at.py` verifies literal `@` characters use `{'@'}` syntax
5. Browser preview check: clicked `配置中心` and `通知与 Webhook`; console contained zero `Invalid linked format` / `[Vue Error]` / `SyntaxError` entries

## Files Changed

| File | Change |
|---|---|
| `frontend-vue/src/locales/zh.json` | 5 message values: literal `@` → `{'@'}` |
| `frontend-vue/src/locales/en.json` | 6 message values: literal `@` → `{'@'}` |
| `tests/test_locales_no_unescaped_at.py` | New regression test |
| `specs/bugfixes/vue-i18n-invalid-linked-format/report.md` | Updated bugfix notes and verification evidence |

## Prevention

The regression test at `tests/test_locales_no_unescaped_at.py` serves as a CI guard: if any future locale messages contain unescaped `@` characters, the test will fail with a descriptive message indicating which keys need escaping.

# Bugfix Report: AI Article LLM Invalid API Key

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

AI 创造模块生成文章时，LLM 调用遇到 `401 invalid_api_key` 后仍按普通网络错误重试，最终在任务详情中显示 `LLM 调用在 2 次重试后仍失败`。同时，配置中心在用户修改 `llm_provider` 或 `llm_base_url` 时允许继续提交掩码值 `***`，旧密钥会被静默套用到新端点。

**Reproduction steps:**
1. 配置 LLM Provider/Base URL/API Key。
2. 将 Provider 或 Base URL 改到另一个 OpenAI-compatible 网关，但不重新输入 LLM API Key。
3. 在 AI 创造模块生成文章，观察任务错误为 401 `missing or invalid API key`。

**Impact:** 用户无法从错误中判断要重新输入 LLM API Key；后台还会对认证错误做无意义等待和重试。

## Investigation Summary

- **Symptoms examined:** 用户提供的 `Error code: 401 - invalid_api_key` 日志，以及文章任务 `_llm_or_fallback` 调用路径。
- **Code inspected:** `scripts/llm_client.py`, `scripts/article_generator.py`, `server/__main__.py`, AI 设置页密钥掩码逻辑和现有敏感配置测试。
- **Hypotheses tested:** 密钥未保存被排除；本地 `load_config()` 能返回解密后的运行时密钥。更可能的问题是旧密钥被沿用到新端点，以及认证失败缺少专门处理。

## Discovered Root Cause

LLM retry helper没有区分认证失败和临时网络失败；文章生成层只把底层异常包成通用 `LLM 处理失败`。配置保存层也只对语音端点做“端点变化必须重输密钥”的保护，LLM 配置缺少同类校验。

**Defect type:** Missing validation and error classification.

**Why it occurred:** LLM 客户端最初把所有 provider 异常都视为可重试错误；后续语音 provider 增加了端点密钥重输保护，但 LLM provider 没有同步补齐。

**Contributing factors:** 前端为了保护密钥会提交 `***`，后端会保留旧值；这个模式在端点身份不变时正确，但端点身份变化时会掩盖配置不匹配。

## Resolution for the Issue

**Changes made:**
- `scripts/llm_client.py` - Added `LLMAuthenticationError`, authentication-error detection, and immediate stop for 401/invalid API key errors.
- `scripts/article_generator.py` - Formats article LLM authentication failures with provider/model/base URL context and guidance to re-enter LLM API Key.
- `server/__main__.py` - Rejects LLM Provider/Base URL changes when the submitted `llm_api_key` is still `***`.
- `tests/test_llm_client.py` - Regression coverage for no retry on authentication failures.
- `tests/test_ai_content_provider_pipeline_contract.py` - Regression coverage for article-task key re-entry guidance.
- `tests/test_sensitive_secret_masking.py` - Regression coverage for endpoint-change key re-entry validation.

**Approach rationale:** Authentication failures are deterministic configuration failures, so retrying is wasteful. Requiring key re-entry when endpoint identity changes prevents stale masked secrets from being reused against the wrong provider.

**Alternatives considered:**
- Fallback from `llm_api_key` to image-generation `openai_api_key` - rejected because those fields can belong to different services and silently sending another secret to the LLM endpoint would hide configuration mistakes.
- Keep retry behavior but improve copy only - rejected because 401 is not transient and should fail immediately.

## Regression Test

**Test file:** `tests/test_llm_client.py`
**Test name:** `test_retry_does_not_repeat_authentication_errors`

**What it verifies:** 401/invalid API key errors raise `LLMAuthenticationError` after one provider call.

**Run command:** `python -m pytest tests/test_llm_client.py::TestLLMClientRetry::test_retry_does_not_repeat_authentication_errors -q`

**Test file:** `tests/test_ai_content_provider_pipeline_contract.py`
**Test name:** `test_article_llm_auth_failure_reports_key_reentry_guidance`

**What it verifies:** Article generation surfaces authentication failures with safe backend context and LLM API Key re-entry guidance.

**Run command:** `python -m pytest tests/test_ai_content_provider_pipeline_contract.py::test_article_llm_auth_failure_reports_key_reentry_guidance -q`

**Test file:** `tests/test_sensitive_secret_masking.py`
**Test name:** `test_llm_endpoint_change_requires_api_key_reentry`

**What it verifies:** Saving a changed LLM endpoint with a masked key is rejected before stale credentials are persisted.

**Run command:** `python -m pytest tests/test_sensitive_secret_masking.py::test_llm_endpoint_change_requires_api_key_reentry -q`

## Affected Files

| File | Change |
|------|--------|
| `scripts/llm_client.py` | Classifies LLM authentication errors and skips retry |
| `scripts/article_generator.py` | Shows actionable article-task LLM authentication guidance |
| `server/__main__.py` | Requires LLM key re-entry on Provider/Base URL identity changes |
| `tests/test_llm_client.py` | Adds retry regression test |
| `tests/test_ai_content_provider_pipeline_contract.py` | Adds article error-message regression test |
| `tests/test_sensitive_secret_masking.py` | Adds config-save validation regression test |

## Verification

**Automated:**
- [x] `python -m pytest tests/test_llm_client.py::TestLLMClientRetry::test_retry_does_not_repeat_authentication_errors tests/test_ai_content_provider_pipeline_contract.py::test_article_llm_auth_failure_reports_key_reentry_guidance tests/test_sensitive_secret_masking.py::test_llm_endpoint_change_requires_api_key_reentry -q`
- [x] `python -m pytest tests/test_llm_client.py tests/test_ai_content_provider_pipeline_contract.py tests/test_sensitive_secret_masking.py tests/test_voice_config.py -q` (92 passed)
- [x] `python -m ruff check scripts/llm_client.py scripts/article_generator.py server/__main__.py tests/test_llm_client.py tests/test_ai_content_provider_pipeline_contract.py tests/test_sensitive_secret_masking.py --ignore E501`
- [ ] `python -m pytest tests/ -q` (987 passed, 8 failed in unrelated existing areas: batch web UI contract, monitor duration, provider scheduler UI, scheduler confirm modal/button contract, thumbnail Pollinations test)

**Manual verification:**
- Confirmed local config loading decrypts `llm_api_key` for runtime without printing the secret value.
- Confirmed no test or report prints API key contents.

## Prevention

**Recommendations to avoid similar bugs:**
- Treat LLM 401/invalid API key errors as configuration failures, not transient retry failures.
- Whenever a secret is preserved via `***`, validate whether the endpoint identity changed before keeping the old secret.
- Keep user-facing task errors actionable and include only non-secret backend context.

## Related

- `specs/bugfixes/ai-article-llm-empty-response-diagnostics/report.md`

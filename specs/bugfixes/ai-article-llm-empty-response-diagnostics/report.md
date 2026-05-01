# Bugfix Report: AI Article LLM Empty Response Diagnostics

**Date:** 2026-04-30
**Status:** Fixed

## Description of the Issue

Refreshing the AI article page showed `LLM 处理失败: 服务未返回内容` for a failed WeChat article task. The backend log excerpt also showed a traceback from `tests/test_ai_content_api_contract.py`, which made the runtime failure look like a test stub exception.

**Reproduction steps:**
1. Start an AI article task for a WeChat article with an LLM endpoint configured.
2. Let the LLM optimize stage fail because the provider raises or returns empty content.
3. Refresh the page and inspect the persisted task error.

**Impact:** Users could only see a generic empty-response message. Provider/model/base URL mistakes and upstream HTTP errors were hidden, slowing diagnosis.

## Investigation Summary

- **Symptoms examined:** Page error `LLM 处理失败: 服务未返回内容`; task `article_86e106db28c8` failed at `optimize`; pasted traceback referenced a pytest stub.
- **Code inspected:** `scripts/article_generator.py`, `scripts/llm_client.py`, `tests/test_ai_content_provider_pipeline_contract.py`, `tests/test_ai_content_api_contract.py`.
- **Hypotheses tested:** Runtime import failure was ruled out for the page failure; the pasted stack came from a test writing its intentional exception to the real app log.

## Discovered Root Cause

`LLMClient.call_with_retry()` swallowed the last provider exception and returned `None` after retries. `ArticleGenerationPipeline` then converted both real retry failures and true empty responses into the same generic `服务未返回内容` message.

**Defect type:** Error propagation and diagnostics gap.

**Why it occurred:** The retry helper was designed for older callers that treat `None` as a recoverable failure, but the article workflow persists the error directly to the UI and needs actionable details.

**Contributing factors:** The background-runner test logged an intentional stub exception to the shared app logger, polluting local runtime logs with a pytest traceback.

## Resolution for the Issue

**Changes made:**
- `scripts/llm_client.py` - Added optional `raise_last_error` support while preserving the default `None` return behavior.
- `scripts/article_generator.py` - Enabled diagnostic retry mode for article LLM calls and added safe provider/model/base URL context for true empty responses.
- `scripts/article_generator.py` - Made WeChat auto-publish tolerate render results without `cover_image_path`.
- `tests/test_ai_content_provider_pipeline_contract.py` - Added regression coverage for empty LLM responses and retained the auto-publish contract.
- `tests/test_llm_client.py` - Added retry diagnostics coverage.
- `tests/test_ai_content_api_contract.py` - Suppressed the intentional test exception from writing to the real app log.

**Approach rationale:** Keep shared retry behavior backward-compatible, and opt the article workflow into richer diagnostics where the persisted error is user-facing.

**Alternatives considered:**
- Always raise from `call_with_retry()` - rejected because other pipelines currently rely on `None` after exhausted retries.
- Keep the generic article error - rejected because it hides the actionable upstream failure.

## Regression Test

**Test file:** `tests/test_llm_client.py`
**Test name:** `test_retry_can_raise_last_error_for_callers_that_need_diagnostics`

**What it verifies:** Callers can opt into receiving the last upstream LLM exception after retries.

**Run command:** `python -m pytest tests/test_llm_client.py::TestLLMClientRetry::test_retry_can_raise_last_error_for_callers_that_need_diagnostics -q`

**Test file:** `tests/test_ai_content_provider_pipeline_contract.py`
**Test name:** `test_article_llm_empty_response_reports_selected_backend`

**What it verifies:** A true empty LLM response produces an actionable article error containing provider, model, and safe base URL context.

**Run command:** `python -m pytest tests/test_ai_content_provider_pipeline_contract.py::test_article_llm_empty_response_reports_selected_backend -q`

## Affected Files

| File | Change |
|------|--------|
| `scripts/llm_client.py` | Optional retry error propagation and unused import cleanup |
| `scripts/article_generator.py` | Article LLM diagnostics and WeChat render-result compatibility |
| `tests/test_llm_client.py` | Retry diagnostics regression test |
| `tests/test_ai_content_provider_pipeline_contract.py` | Article empty-response regression test |
| `tests/test_ai_content_api_contract.py` | Prevent intentional test exception from polluting app logs |

## Verification

**Automated:**
- [x] `python -m pytest tests/test_llm_client.py tests/test_ai_content_provider_pipeline_contract.py tests/test_ai_content_api_contract.py -q`
- [x] `python -m pytest tests/test_wechat_article_last_mile.py::test_wechat_config_includes_local_publish_quota -q`
- [x] `python -m ruff check scripts/article_generator.py scripts/llm_client.py tests/test_ai_content_provider_pipeline_contract.py tests/test_llm_client.py tests/test_ai_content_api_contract.py`
- [ ] `python -m pytest -q` timed out after 304 seconds before producing a failure summary.

**Manual verification:**
- Inspected `data/monitor.db` and confirmed the real failed task was `article_86e106db28c8` at stage `optimize`; the pasted pytest stack was log pollution rather than the task's runtime stack.

## Prevention

**Recommendations to avoid similar bugs:**
- Use explicit diagnostic modes for shared helpers when their errors are persisted to user-visible task records.
- Keep tests that intentionally raise exceptions from writing into shared application logs.
- Include non-secret provider context in user-facing LLM failures.

## Related

- Previous same-session fix: `specs/bugfixes/wechat-publish-config-quota-helper/report.md`

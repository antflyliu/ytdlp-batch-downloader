# Bugfix Report: 微信草稿保存标题超长失败

**Date:** 2026-06-08
**Status:** Fixed

## Description of the Issue

在 AI 创作模块中，任务 `article_47a48725578a` 点击「保存到草稿箱」时失败，页面提示“标题不能超过 32 个字符，当前 34 个字符”。

**Reproduction steps:**
1. 打开 AI 创作页，选择任务 `article_47a48725578a`。
2. 点击「保存到草稿箱」。
3. 观察到发布面板报标题长度错误并中止。

**Impact:** 影响 AI 创作到公众号草稿箱的发布链路，用户无法保存该任务的文章草稿。

## Investigation Summary

先复现本地任务目录，再顺着前端请求、HTTP 入口和微信发布器追踪数据流。

- **Symptoms examined:** 失败提示来自标题长度校验；任务目录中 `draft.md` 标题为 34 字符，而同目录 `wechat_publish.md` 已有 29 字符的发布标题。
- **Code inspected:** `frontend-vue/src/views/AiCreation.vue`、`server/__main__.py`、`monitor/wechat_publisher.py`、`scripts/article_generator.py`。
- **Hypotheses tested:** 仅修发布器不足以解决问题，因为 HTTP 层先做了预校验；仅改前端也不够，因为后台自动发布同样会走到长标题。

## Discovered Root Cause

发布入口错误地把 `draft.md` 的原始标题当作最终公众号标题，并在入队前用严格校验直接拒绝；而这个任务实际上已经生成了更适合发布的 `wechat_publish.md`，但没有被优先使用。

**Defect type:** 路径选择错误 + 缺少发布边界归一化。

**Why it occurred:** AI 任务生成了两份稿件：原始 `draft.md` 和发布优化稿 `wechat_publish.md`。手动保存草稿时仍默认提交 `draft.md`，HTTP 层又在标题超过 32 字符时直接报错。

**Contributing factors:** 发布标题和原始任务标题混用，导致“可自动修复的问题”被当成致命错误处理。

## Resolution for the Issue

**Changes made:**
- `frontend-vue/src/views/AiCreation.vue:685` - 发布按钮优先选择 `article_publish_markdown_path`。
- `server/__main__.py:3999` - 当请求来自文章任务且默认路径为 `draft.md` 时，自动切换到 `wechat_publish.md`。
- `server/__main__.py:4007` - 若未显式传 title，则优先使用渲染后的发布标题。
- `server/__main__.py:4051` - 发布前对标题做 32 字符归一化，避免草稿保存因轻微超限失败。
- `monitor/wechat_publisher.py:71` - 新增 `normalize_wechat_title()`。
- `monitor/wechat_publisher.py:540` - 创建草稿时统一使用归一化标题。
- `scripts/article_generator.py:2425` - 自动发布链路也改为使用归一化后的标题。

**Approach rationale:** 优先修正发布边界的数据选择，再用标题归一化兜底，保证旧入口、前端手动保存和后台自动发布都能稳定工作。

**Alternatives considered:**
- 只在 `validate_wechat_article_payload()` 中放宽限制 - 会掩盖真实的微信字段约束，不适合做边界校验。
- 只改前端选择稿件路径 - 无法覆盖旧客户端和后台自动发布路径。

## Regression Test

**Test file:** `tests/test_wechat_article_last_mile.py`
**Test name:** `test_create_draft_truncates_long_title_before_api_call`

**What it verifies:** 长标题进入草稿创建前会被压到 32 字符以内，不再因为标题长度直接失败。

**Additional coverage:** `test_wechat_publish_api_prefers_optimized_publish_markdown`、`tests/test_ai_content_frontend_contract.py::test_ai_creation_wechat_publish_prefers_publish_markdown_artifact`

**Run command:** `python -m pytest tests/test_wechat_article_last_mile.py tests/test_ai_content_frontend_contract.py -q`

## Affected Files

| File | Change |
|------|--------|
| `frontend-vue/src/views/AiCreation.vue` | 发布入口改为优先使用发布优化稿 |
| `server/__main__.py` | 兼容旧请求并归一化标题 |
| `monitor/wechat_publisher.py` | 新增标题归一化 helper |
| `scripts/article_generator.py` | 自动发布链路同步使用归一化标题 |
| `tests/test_wechat_article_last_mile.py` | 新增后端回归测试 |
| `tests/test_ai_content_frontend_contract.py` | 新增前端契约测试 |

## Verification

**Automated:**
- [x] Regression test passes
- [x] Full test file suite passes
- [x] Frontend build passes
- [x] Live WeChat draft task completed successfully for `article_47a48725578a`

**Manual verification:**
- 复现任务 `article_47a48725578a` 的 `draft.md` 标题为 34 字符，`wechat_publish.md` 标题为 29 字符。
- 通过本地脚本确认原实现会被标题长度校验拦截。
- 本地 127.0.0.1:4999 服务已重启并加载修复后的代码。

## Prevention

**Recommendations to avoid similar bugs:**
- 发布入口应优先选择面向目标平台的优化稿，而不是原始草稿。
- 进入外部 API 前，保留严格校验，同时对可安全归一化的字段做显式归一化。
- 任务产物中若同时存在 `draft.md` 和 `wechat_publish.md`，UI 需要明确选择发布稿。

## Related

- `output/articles/article_47a48725578a/draft.md`
- `output/articles/article_47a48725578a/wechat_publish.md`

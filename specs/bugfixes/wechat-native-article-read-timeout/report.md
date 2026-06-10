# Bugfix Report: WeChat Native Article Read Timeout

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

Downloading the WeChat article `自动爬取、处理公众号文章：用QClaw+WeChatDownload` from `https://mp.weixin.qq.com/s/5yRqm7g9sYXmHa4mW6hvqw` could fail in the native WeChat collection module with `Read timed out`.

**Reproduction steps:**
1. Open the native WeChat collection page.
2. Select or download the article `自动爬取、处理公众号文章：用QClaw+WeChatDownload`.
3. Observe the task result fail with `HTTPSConnectionPool(host='mp.weixin.qq.com', port=443): Read timed out`.

**Impact:** A transient slow read from `mp.weixin.qq.com` caused the whole local download task to fail. Markdown exports also risked losing title formatting, anchor links, plain URL link semantics, and local image copies.

## Investigation Summary

- **Symptoms examined:** User screenshot showed a read timeout while fetching the article HTML.
- **Code inspected:** `monitor/wechat_collect/html_export.py`, `monitor/wechat_collect/tasks.py`, `tests/test_wechat_native_client.py`, `tests/test_wechat_native_tasks.py`.
- **Hypotheses tested:** Invalid article URL, frontend selection payload issue, and single-attempt upstream article fetch. The failing regression test confirmed the single-attempt article fetch was the timeout failure path.

## Discovered Root Cause

`download_article()` made one `GET` request with a fixed timeout and immediately surfaced any `requests.ReadTimeout` as `WechatArticleError`. The asset localization path also made one image request per image. There was no retry/backoff for transient WeChat HTML or image reads.

**Defect type:** Missing retry policy for transient upstream network failures.

**Why it occurred:** The exporter assumed article HTML and image endpoints would respond within one request budget. Real `mp.weixin.qq.com` article pages and `mmbiz.qpic.cn` images can have intermittent slow reads.

**Contributing factors:** Markdown export focused on text extraction first and did not fully normalize title, image, anchor, and bare URL content into Markdown.

## Resolution for the Issue

**Changes made:**
- `monitor/wechat_collect/html_export.py` - Added article request timeout tuple, browser-like headers, retry/backoff for timeout/connection/5xx/429 failures, normalized source URLs, Markdown image/link preservation, title heading normalization, and bare URL linkification.
- `monitor/wechat_collect/tasks.py` - Added image URL safety checks, asset extension detection, image download retry/backoff, Markdown/HTML asset localization, and selected article URL normalization for batch downloads.
- `tests/test_wechat_native_client.py` - Added regression coverage for first-read timeout retry and Markdown title/text/link/image preservation.
- `tests/test_wechat_native_tasks.py` - Added regression coverage for selected article metadata, backend URL normalization, and image localization retry.

**Approach rationale:** Manual bounded retries are enough here and avoid a new dependency. Keeping this in the shared article exporter means single download, batch download, and account lookup by article URL all use the same resilient fetch behavior.

**Alternatives considered:**
- Only increase the timeout - rejected because a transient read timeout would still fail the task on the first slow response.
- Retry only task-level failures - rejected because it would re-run the whole article workflow and duplicate output path/result handling instead of retrying the flaky upstream request.
- Leave images remote-only - rejected for this bug because the user asked to verify that images are captured too; the exporter now localizes images when possible and preserves the original Markdown reference if an image cannot be downloaded.

## Regression Test

**Test files:** `tests/test_wechat_native_client.py`, `tests/test_wechat_native_tasks.py`

**Test names:**
- `test_download_article_retries_read_timeout_and_keeps_markdown_content`
- `test_export_article_html_outputs_html_text_markdown_and_json`
- `test_native_collection_download_localizes_markdown_images_and_preserves_links`

**What they verify:** Article HTML fetch retries after a `ReadTimeout`; Markdown output keeps title, text, anchor links, bare URLs, and images; image localization retries once after timeout and writes a non-empty local asset.

**Run command:** `python -m pytest tests/test_wechat_native_client.py tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py`

## Affected Files

| File | Change |
|------|--------|
| `monitor/wechat_collect/html_export.py` | Resilient article fetch, Markdown title/link/image normalization, source URL metadata. |
| `monitor/wechat_collect/tasks.py` | Local image asset download, retry, URL normalization, selected article metadata preservation. |
| `tests/test_wechat_native_client.py` | Article timeout retry and Markdown content regression coverage. |
| `tests/test_wechat_native_tasks.py` | Task download image localization and selected article regression coverage. |

## Verification

**Automated:**
- [x] Regression test fails before the fix with `文章下载失败: Read timed out`.
- [x] Regression tests pass after the fix.
- [x] Native WeChat related test suite passes: `61 passed`.
- [x] Frontend production build passes: `npm run build`.

**Manual verification:**
- Real article URL tested: `https://mp.weixin.qq.com/s/5yRqm7g9sYXmHa4mW6hvqw`.
- Real Markdown output path: `data/wechat-native-real-test/qclaw-wechatdownload.md`.
- Real output metrics: 4,985 bytes Markdown, title metadata `自动爬取、处理公众号文章：用QClaw+WeChatDownload`, author `周建辉 ahui`.
- Content checks passed: Markdown starts with `# <metadata title>`, contains `QClaw`, `WeChatDownload`, `Github`, and `xiaoguyu`.
- Link checks passed: 1 Markdown link captured, sample `https://github.com/xiaoguyu/wechatDownload/releases`.
- Image checks passed: 5 source image references, 5 localized image references, 0 remaining remote image references, 5 non-empty local image files totaling 534,154 bytes.

## Prevention

**Recommendations to avoid similar bugs:**
- Keep upstream article and asset requests on bounded retry policies instead of single-shot fetches.
- Regression-test timeout recovery with fake sessions that fail once and then succeed.
- Verify real WeChat article downloads with title, text, link, and image assertions before closing downloader regressions.

## Related

- User report: native WeChat download of `自动爬取、处理公众号文章：用QClaw+WeChatDownload` failed with `Read timed out`.

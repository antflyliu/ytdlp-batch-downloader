# Bugfix Report: WeRead Cover Book ID Misclassification

**Date:** 2026-06-09
**Status:** Fixed

## Description of the Issue

WeRead export failed for `book_id=0b0322e0813ab7435g0197d8` with:

`当前微信读书网页接口未返回章节目录；微信读书元数据请求失败：book/info HTTP 401 LOGIN ERR；页面会话读取也失败：Page.evaluate: Error: book/info HTTP 401`

**Impact:** The task failed before chapter export started, even though the debug Chrome CDP session was available and the WeRead web page could load the book.

## Investigation Summary

- The failing local tasks were `wrd_199b0353c0e3` and `wrd_98bfabc7776e`.
- A live CDP probe showed the reader page title as `底层逻辑2：理解商业世界的本质`.
- The page exposed multiple possible IDs:
  - `cpPlatform_ciP8oppqpzLpqhxJK9LLVg` from the cover CDN URL.
  - `3300035099` from live WeRead web API URLs such as `/web/book/readInfo?bookId=3300035099`.
  - `0b0322e0813ab7435g0197d8` from the reader route.

## Discovered Root Cause

`_fetch_book_meta_via_web_reader()` stopped at the first ID-like value it found. For this book, the first match could be the cover CDN asset ID (`cpPlatform_ciP8oppqpzLpqhxJK9LLVg`), not the real WeRead web metadata book ID.

Calling `/web/book/outline` with the cover asset ID returned placeholder entries without chapter titles, so the current web metadata path raised `当前微信读书网页接口未返回章节目录`. The exporter then fell back to the legacy `i.weread.qq.com/book/info` path, which returned `401 LOGIN ERR`, producing the confusing combined error.

## Resolution for the Issue

**Changes made:**
- `monitor/weread_exporter/core.py` now collects multiple web book ID candidates from the reader page.
- Current WeRead web API URLs are ranked above cover CDN IDs.
- Cover IDs are kept only as lower-priority fallback candidates.
- The metadata reader now retries each candidate until `/web/book/outline` returns usable chapters.
- `tests/test_weread_exporter_integration.py` adds a regression test where a cover `cpPlatform_...` ID appears before the real web `bookId`.

**Rejected alternatives:**
- Force re-login on every `book/info 401` - rejected because this failure can happen with a valid web login when the old `i.weread.qq.com` API is not usable.
- Remove the legacy metadata fallback entirely - rejected because it may still support older WeRead responses.

## Regression Test

**Test file:** `tests/test_weread_exporter_integration.py`

**Test name:** `test_weread_runner_retries_current_web_book_id_candidates`

**What it verifies:** A bad cover CDN candidate can fail first, then the exporter retries the real web book ID and returns valid chapter metadata without falling through to the old `book/info` path.

## Affected Files

| File | Change |
|------|--------|
| `monitor/weread_exporter/core.py` | Adds prioritized web book ID candidate extraction and retry. |
| `tests/test_weread_exporter_integration.py` | Adds regression coverage for cover ID misclassification. |
| `specs/bugfixes/weread-cover-book-id-misclassification/report.md` | Documents root cause, fix, and verification. |

## Verification

**Automated:**
- [x] `venv_build\Scripts\python.exe -m pytest tests\test_weread_exporter_integration.py::test_weread_runner_retries_current_web_book_id_candidates -q`
- [x] `venv_build\Scripts\python.exe -m pytest tests\test_weread_exporter_integration.py -q`
- [x] `venv_build\Scripts\python.exe -m ruff check monitor\weread_exporter\core.py tests\test_weread_exporter_integration.py`
- [x] `venv_build\Scripts\python.exe -m py_compile monitor\weread_exporter\core.py tests\test_weread_exporter_integration.py`

**Manual verification:**
- Connected to the local debug Chrome CDP endpoint at `http://127.0.0.1:9222`.
- Called the current `WeReadPlaywrightRunner.fetch_book_meta()` for `0b0322e0813ab7435g0197d8`.
- Verified metadata resolves to `web_book_id=3300035099`, `reader_book_id=0b0322e0813ab7435g0197d8`, title `底层逻辑2：理解商业世界的本质`, author `刘润`, and 24 chapters.

**Not run:**
- Full repository test suite, because this workspace already contains many unrelated in-progress changes.

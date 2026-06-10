# Bugfix Report: RSS Content Source Edge Cases

Date: 2026-06-07

## Description

RSS 内容源模块在 RSS/Atom 兼容性、OPML 重导入、错误状态码、超大 Feed 处理和前端页面渲染上存在多个边界问题。修复目标是让内容解析更完整，订阅配置不被导入覆盖，并让页面和 API 错误反馈更可预期。

## Reproduction

- Atom `<author><name>...</name></author>` 只读取直接文本，作者为空。
- Atom XHTML `<content type="xhtml">...</content>` 只读取直接文本，导致正文/摘要丢失嵌套内容。
- 重新导入同一 Feed 的 OPML 会把已有 `enabled=false` 和自定义 `fetch_interval_minutes` 重置为默认值。
- 手动刷新订阅源时，Feed 内容解析失败被 API 归类为 404。
- 远端 Feed 超过读取上限时会被静默截断，后续表现为误导性的 XML 解析错误。
- `/rss-pipeline` 这类扩展名为空的 Vue SPA 路由直接访问会返回 404；即使只回退到 `index.html`，hash router 也不会进入目标页面。
- `RssPipeline.vue` 模板使用 Naive UI 组件但脚本未导入，构建后的页面渲染出未解析的自定义标签，OPML 文本框和按钮不是实际控件。

## Impact

- Atom 源内容丢失作者和正文，影响 AI 文章生成输入质量。
- OPML 同步可能意外启用已停用订阅源，或重置抓取频率。
- 用户看到错误的 404，难以判断是 Feed 不存在还是 Feed 内容无效。
- 超大 Feed 的失败原因不清晰。
- RSS 页面直接路由访问和 OPML 导入交互不稳定。

## Investigation

先用回归测试锁定解析、导入和 API 状态码行为，再用本地服务加载构建后的前端页面，通过 Browser 自动化检查真实 DOM 和 OPML 导入结果。Chrome 自动化也按插件流程尝试连接并诊断，但当前本机 Chrome profile/native host 配置不可用。

## Root Cause

- XML helper 只返回子节点 `text`，没有合并嵌套节点文本或保留嵌套 markup。
- OPML 导入统一走 upsert 默认值，没有读取已有 Feed 的运行配置。
- 服务层同时用 `ValueError` 表示不存在和业务输入错误，API 层无法区分 404 与 400。
- Feed 拉取只读取固定字节数，没有检测是否超限。
- 静态文件服务只对实际文件返回 Vue 产物，没有给扩展名为空的 SPA route 回退到 `index.html`。
- Vue `<script setup>` 没有显式导入模板中使用的 Naive UI 组件。

## Resolution

- `monitor/rss_collect/parser.py` 递归提取嵌套文本，并对正文类字段保留嵌套 XML/HTML markup。
- `monitor/rss_collect/service.py` 新增 `MAX_FEED_BYTES` 显式超限检测；不存在的 Feed/Item 改用 `LookupError`；OPML 重导入保留已有 `site_url`、`enabled` 和 `fetch_interval_minutes`。
- `server/__main__.py` 将 RSS 不存在错误映射为 404，解析/校验错误保持 400；扩展名为空的 Vue 路径重定向到对应 hash route，例如 `/rss-pipeline` 到 `/#/rss-pipeline`。
- `frontend-vue/src/views/RssPipeline.vue` 显式导入模板使用的 Naive UI 组件。
- 增加 RSS 解析、OPML 重导入、超大 Feed、API 状态码、SPA route 和前端组件导入契约测试。

## Tests

- `python -m pytest tests/test_rss_pipeline_frontend_contract.py tests/test_rss_collect_integration.py tests/test_monitor_server_static_auth.py -q`
  - Result: `30 passed`
- `python -m compileall monitor\rss_collect monitor\db\queries\rss_collect.py server\__main__.py tests\test_rss_collect_integration.py tests\test_monitor_server_static_auth.py tests\test_rss_pipeline_frontend_contract.py`
  - Result: passed
- `npm run build`
  - Result: passed
- `npx vue-tsc --noEmit`
  - Result: passed
- Browser automation on `http://127.0.0.1:5101/rss-pipeline`
  - Result: direct route redirected to `/#/rss-pipeline`, page rendered RSS content, native textarea/button controls existed, unresolved `nbutton`/`ninput` counts were `0`, OPML import changed title while preserving `enabled=false`, `fetch_interval_minutes=180`, and `site_url=https://example.com/`, preview expansion worked.

## Chrome Verification

Chrome automation was attempted because the task mentioned `@chrome`. The plugin connection was unavailable: `agent.browsers.get("extension")` reported no extension browser. Diagnostics showed Chrome is installed, but the selected Chrome profile (`Profile 6`) does not have the Codex Chrome Extension installed/enabled, and the expected Codex native host registry key is missing. Per the Chrome skill troubleshooting rules, native host/extension repair must be done from the Codex plugin UI, so Chrome page automation could not be completed in this session.

## Code Review

The requested `code-reviewer` subagent reviewed the scoped RSS changes. It found one medium issue: returning `index.html` for `/rss-pipeline` did not actually deep-link into the RSS page because the Vue router uses hash history. The fix was updated to redirect extensionless Vue paths to matching hash routes, and the server regression test plus Browser verification now cover direct `/rss-pipeline` entry.

## Files

- `monitor/rss_collect/parser.py`
- `monitor/rss_collect/service.py`
- `server/__main__.py`
- `frontend-vue/src/views/RssPipeline.vue`
- `tests/test_rss_collect_integration.py`
- `tests/test_monitor_server_static_auth.py`
- `tests/test_rss_pipeline_frontend_contract.py`
- `specs/bugfixes/rss-content-source-edge-cases/report.md`

## Prevention

- Keep parser regression fixtures for real RSS and Atom variants, especially nested Atom XHTML.
- Preserve runtime subscription settings when import flows update metadata.
- Keep API tests that distinguish missing resources from invalid remote content.
- Validate built frontend behavior for component-heavy pages, not just source-level imports.

## Remaining Risks

- Chrome plugin verification remains blocked until the local Codex Chrome Extension/native host setup is repaired.

# FeedFuse 功能迁移分析与生产级实施计划

## 1. 结论

FeedFuse 的代码不能直接合并到本项目。FeedFuse 是 Next.js 16 + React 19 + TypeScript + PostgreSQL + pg-boss 的完整 RSS 阅读器；当前项目是 Python HTTP 服务 + SQLite + Vue 3 + Naive UI 的下载、监控、采集与 AI 内容工作台。直接搬迁会引入不匹配的运行时、数据库、队列和前端框架。

可迁移的是功能模型：RSS/Atom 订阅、OPML 导入导出、RSS 条目解析、SSRF 防护、条目转 AI 内容处理。它们与当前项目的邮件内容流水线、微信公众号采集、AI 文章生成任务具有相同的“内容源 -> 清洗/整理 -> AI 生成”的业务形态。

## 2. 技术栈对比

| 维度 | FeedFuse | 当前项目 | 迁移判断 |
| --- | --- | --- | --- |
| 后端运行时 | Next.js Route Handlers + Node.js | Python `http.server` 风格 MonitorHandler | API 不能直接合并，需要 Python 改写 |
| 前端 | React 19 + Next.js App Router | Vue 3 + Vue Router + Naive UI | UI 不能直接搬迁，需要 Vue 页面 |
| 数据库 | PostgreSQL 16 | SQLite | schema、查询和迁移必须重写 |
| 队列 | pg-boss worker | Python 线程/现有调度器 | 不迁移 pg-boss，先走同步刷新 + 后台文章任务 |
| RSS 解析 | `rss-parser` | Python 标准库优先，安全解析用 `defusedxml` | 已用 hardened XML parser 实现基础 RSS/Atom |
| 全文抓取 | Mozilla Readability + jsdom | 当前无统一全文抓取模块 | 作为后续阶段，避免引入大依赖 |
| AI | OpenAI SDK | 现有 `scripts/llm_client.py` + AI 文章 pipeline | 复用现有 pipeline，不复制 FeedFuse AI runtime |
| 授权/安全 | Next API auth/session | Monitor API 现有认证/限流 | 新 API 挂在已有 `/api` 鉴权之后 |

## 3. FeedFuse 能力拆解

| FeedFuse 能力 | 当前项目适配判断 | 本分支处理 |
| --- | --- | --- |
| RSS 源管理 | 可迁移，映射为 SQLite 表和 Python API | 已新增 `rss_feeds` |
| RSS/Atom 拉取解析 | 可迁移，但不能使用 `rss-parser` | 已用 Python + `defusedxml` 实现 |
| OPML 导入导出 | 可迁移，结构简单且低耦合 | 已实现 |
| 全文抓取 | 可迁移但风险较高，需要 HTML 清洗、图片代理和 SSRF 策略 | 暂未迁移 |
| AI 摘要/翻译 | 当前项目已有 AI 文章生成能力，可复用现有 pipeline | RSS 条目可生成 `article_tasks` |
| AI 解读/多源 digest | 需要新增跨条目聚合任务模型 | 暂未迁移 |
| Fever 同步 | 与当前业务弱相关，且需要账号/同步协议模型 | 暂不迁移 |
| PostgreSQL/pg-boss 队列 | 技术栈不匹配 | 不迁移 |
| FeedFuse React 三栏阅读器 | 前端框架不匹配 | 改为 Vue RSS 内容源页面 |

## 4. 生产实施原则

1. 谨慎引入依赖。当前项目依赖面已经包含 Python、Vue、Naive UI、SQLite；RSS 基础能力优先用标准库完成，仅为 XML 安全解析新增 `defusedxml`。
2. 不破坏现有内容源。邮件、公众号、视频仍保留原有 `source_type`；RSS 新增 `rss_item`，避免复用 `email_message` 或 `wechat_article` 造成语义污染。
3. 数据迁移可重复。新表使用 `CREATE TABLE IF NOT EXISTS`，旧库通过 `schema_migrations` 的 `v23_rss_collect_sources` 增量迁移补齐。
4. 服务端抓取必须有 SSRF 防护。RSS URL 拒绝非 http/https、认证信息、本机、内网、保留地址和解析到内网的域名。
5. 前端先做内容源工作台，不做完整阅读器。当前项目的核心价值是下载/采集/AI 创作；RSS 页面应服务于“条目进入 AI 文章流水线”，不复制 FeedFuse 的阅读器产品。
6. 代码审核和验证必须覆盖既有能力。新增 `rss_item_id` 不应破坏邮件/公众号/视频文章任务。

## 5. 分阶段计划

| 阶段 | 目标 | 实施内容 | 验收标准 |
| --- | --- | --- | --- |
| Phase 0 分析 | 判断可迁移性 | 对比 FeedFuse 与当前项目技术栈、业务边界和安全要求 | 形成本文档，明确直接合并不可行 |
| Phase 1 数据和服务 | 建立 RSS 内容源后端 | 新增 `rss_feeds`、`rss_items`、RSS/OPML parser、service、SSRF guard | 新增单元测试通过，旧库迁移可重复 |
| Phase 2 API | 暴露管理和生成入口 | 新增 `/api/rss/*`，扩展 `/api/article/generate` | API 可添加、刷新、导入导出、生成文章任务 |
| Phase 3 AI 集成 | 接入现有 AI 文章 pipeline | `source_type=rss_item` 读取条目正文，生成 `article_tasks` | RSS 条目可追踪到 `article_task_id` |
| Phase 4 Vue UI | 提供可用工作台 | 新增 `/rss-pipeline` 页面和导航 | Vite build 通过，页面能完成基础 RSS 工作流 |
| Phase 5 审核与回归 | 降低集成风险 | 运行测试、构建、代码审核、安全自查 | 无 blocking issue；遗留风险记录清楚 |

## 6. 本分支合并范围

- 新增 RSS 数据模型：`rss_feeds`、`rss_items`。
- 给 `article_tasks` 增加 `rss_item_id`，用于追踪 RSS 条目生成的 AI 文章任务。
- 新增 Python RSS/Atom 解析、OPML 解析/导出、URL 安全校验和 RSS service；XML 解析使用 `defusedxml` 防止实体扩展类攻击。
- 新增 `/api/rss/...` API：
  - `GET /api/rss/feeds`
  - `POST /api/rss/feeds`
  - `DELETE /api/rss/feeds/:id`
  - `GET /api/rss/items`
  - `POST /api/rss/feeds/:id/refresh`
  - `POST /api/rss/opml/import`
  - `GET /api/rss/opml/export`
  - `POST /api/rss/items/:id/generate`
- 扩展 `/api/article/generate` 支持 `source_type=rss_item`。
- 新增 Vue 页面 `/rss-pipeline`，支持添加订阅、刷新、查看条目、OPML 导入导出、触发 AI 文章任务。

## 7. 不在本分支迁移的内容

- FeedFuse 的 PostgreSQL schema、pg-boss 队列和 Next.js API。
- FeedFuse 的完整三栏阅读器交互。
- 全文抓取和沉浸式双语阅读。
- Fever 同步。
- 多源 AI Digest 聚合。

这些功能不是不可做，而是需要新的 Python/Vue/SQLite 设计，不适合在第一阶段 RSS 内容源接入中一并迁移。

## 8. 验证计划

| 验证项 | 命令/方式 | 覆盖内容 |
| --- | --- | --- |
| RSS 后端单测 | `python -m pytest tests/test_rss_collect_integration.py -q` | RSS/Atom 解析、OPML、schema、RSS -> article task、URL 安全 |
| 相关回归 | `python -m pytest tests/test_email_collect_schema.py tests/test_email_collect_api_contract.py tests/test_ai_article_email_source_path.py tests/test_ai_article_wechat_source_path.py -q` | 既有邮件/公众号内容源不回退 |
| 编译检查 | `python -m compileall monitor\\rss_collect monitor\\db\\queries\\rss_collect.py monitor\\db.py server\\__main__.py scripts\\article_generator.py` | Python 语法和导入路径 |
| 前端构建 | `npm run build` in `frontend-vue` | Vue 页面、router、i18n、API 类型 |
| 工作区检查 | `git diff --check` | 空白和 patch 基础质量 |

## 9. 回滚与风险

- 回滚最小范围：删除 RSS 新增模块/API/UI，并移除 `rss_item_id` 相关代码；数据库中新增表不影响既有表读取。
- `rss_item_id` 是 nullable 新列，不改变既有任务创建参数的默认行为。
- RSS 拉取目前是同步 API 调用，超时 20 秒；后续如果源数量扩大，应迁移到调度/任务队列。
- RSS parser 是基础实现，覆盖主流 RSS/Atom，但不保证支持所有命名空间扩展；复杂 feed 可在后续按测试补强。
- OPML 导入当前通过 JSON body 传输，不支持大文件上传；大规模订阅迁移可后续加 multipart。

## 10. 代码审核结果

本分支完成实现后执行了代码审核和 UI/UX 审核。

### 代码审核

审核结论最初为 `REQUEST CHANGES`，主要原因是 RSS server-side fetch 存在生产级 SSRF 风险。已完成修复：

- 禁用 `urllib` 自动重定向，改为手动处理 301/302/303/307/308，并对每一跳 `Location` 重新执行 URL 安全校验。
- RSS 拉取禁用环境代理，直接连接目标 feed；响应建立后校验 peer IP，阻止 DNS 校验后实际连接到内网、本机或保留地址。
- OPML 导入复用同一 URL 安全策略，拒绝把内网、带认证信息或不安全协议的 feed 写入数据库。
- `/api/rss/items?feed_id=abc` 改为返回 400，不再静默退化成“列出全部条目”。
- OPML import 在 JSON 读取前增加 Content-Length 上限，并在 service 层增加字符数上限。
- XML 解析从 stdlib `ElementTree` 切换到 `defusedxml.ElementTree`，防止实体扩展类 XML 攻击。

### UI/UX 审核

审核结论为 `COMMENT / REQUEST POLISH BEFORE MERGE`。已完成修复：

- 为刷新间隔输入框增加可见和可访问 label。
- 删除订阅源增加确认、loading、错误处理和成功反馈。
- 条目列表增加“全部订阅”视图、分页式加载更多和错误提示。
- feed 选中态增加 `aria-pressed`。
- active feed 颜色改用项目 `--accent` / `--accent-dim` token，避免偏离 `DESIGN.md` 的暖色系统。
- feed 状态文本本地化。
- 条目增加摘要展开预览，降低误触发 AI 生成的风险。

## 11. 后续迁移建议

1. 全文抓取：优先做 Python 版 `readability`/HTML 清洗模块，必须复用 RSS URL 安全校验，禁止内网资源抓取。
2. AI 摘要/翻译：不要复制 FeedFuse 的 OpenAI runtime；应复用当前 `scripts/llm_client.py` 和 AI 文章配置。
3. AI 解读：新增 `rss_digest_tasks` 或复用 content variants 前，先定义跨条目输入上限、去重策略和输出平台。
4. 调度刷新：可在现有 scheduler/provider_scheduler 之外增加轻量 RSS refresh job，但要避免影响 YouTube 监控主循环。

# 微信公众号原生采集使用与维护指南

## 定位

原生采集是现有 `wechat-article-exporter` 第三方服务采集之外的一条本地路径。它通过微信公众号平台扫码登录，后端保存加密后的 MP `token` 与 Cookie，再用本项目自己的后台任务完成公众号搜索、文章列表拉取、文章导出和后续 AI 文章生成衔接。

两条采集路径同时保留：

| 路径 | 前端入口 | 后端路由 | 适用场景 |
| --- | --- | --- | --- |
| 第三方 exporter | `公众号采集` | `/api/wechat-collect/*` | 已部署 `wechat-article-exporter`，希望继续使用 AuthKey 与其导出能力 |
| 原生采集 | `公众号原生采集` | `/api/wechat-native/*` | 希望本地持有登录会话、任务历史和导出文件，不依赖第三方 exporter API |

## 用户流程

1. 打开 Vue 左侧导航的 `公众号原生采集`。
2. 点击 `扫码登录`，用可访问微信公众号平台的微信账号扫码，并在手机端确认。
3. 登录确认后，页面会得到一个不透明的 `session_id`。前端不会收到 MP `token` 或 Cookie。
4. 选择采集来源：
   - `文章链接`：输入一篇 `https://mp.weixin.qq.com/s/...` 文章链接，后端提取作者名后通过已登录 MP 后台搜索精确匹配公众号，再用后台返回的 `fakeid` 拉取该账号文章。
   - `fakeid`：直接输入已知 fakeid，可配合关键词过滤文章列表。
   - `多链接`：逐行输入文章 URL，跳过账号列表发现，直接按链接导出。
5. 选择导出格式、最大文章数、下载间隔和输出目录，启动任务。
6. 任务完成后，在结果中查看导出文件名和 `artifact_id`；Markdown/Text/HTML/JSON 文件可通过后端安全解析后继续用于 AI 文章生成或后续发布流程。

## 运行配置

原生采集复用现有公众号采集配置项：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `wechat_collection_output_dir` | `data/wechat-articles` | 原生和 exporter 采集的默认输出根目录 |
| `wechat_collection_default_format` | `markdown` | 默认导出格式，支持 `html`、`markdown`、`text`、`json` |
| `wechat_collection_delay_seconds` | `1.0` | 每篇文章下载后的延迟，任务层限制在 `0..30` 秒 |
| `wechat_collection_max_articles` | `50` | 默认最大文章数，任务层限制在 `1..1000` |

输出路径必须位于 `wechat_collection_output_dir` 下。后端会在任务启动前解析并校验路径，防止把文件写到采集根目录之外。

## API 摘要

会话与登录：

| 方法 | 路由 | 说明 |
| --- | --- | --- |
| `GET` | `/api/wechat-native/config` | 返回安全的采集默认配置 |
| `GET` | `/api/wechat-native/sessions` | 列出公开会话元数据，不返回 token/Cookie |
| `POST` | `/api/wechat-native/login/start` | 创建待扫码登录会话 |
| `GET` | `/api/wechat-native/login/{login_id}/qrcode` | 返回二维码图片 |
| `GET` | `/api/wechat-native/login/{login_id}/scan` | 查询扫码状态 |
| `POST` | `/api/wechat-native/login/{login_id}/confirm` | 确认登录并持久化会话 |
| `POST` | `/api/wechat-native/sessions/{session_id}/check` | 校验本地会话并访问 MP 后台首页确认上游可用性 |
| `POST` | `/api/wechat-native/sessions/{session_id}/logout` | 标记会话退出 |

采集与任务：

| 方法 | 路由 | 说明 |
| --- | --- | --- |
| `POST` | `/api/wechat-native/accounts/search` | 按关键词搜索公众号 |
| `POST` | `/api/wechat-native/accounts/by-url` | 从文章链接推断公众号 |
| `POST` | `/api/wechat-native/articles/preview` | 预览文章列表 |
| `POST` | `/api/wechat-native/tasks/start` | 创建并启动后台采集任务 |
| `GET` | `/api/wechat-native/tasks` | 列出原生采集任务 |
| `GET` | `/api/wechat-native/tasks/{task_id}` | 查询任务详情 |
| `POST` | `/api/wechat-native/tasks/{task_id}/cancel` | 请求取消任务 |

AI 文章衔接：

| 方法 | 路由 | 说明 |
| --- | --- | --- |
| `POST` | `/api/article/generate` | 当 `source_type=wechat_article` 时，可用 `article_source_path` 或 `article_text` 生成 AI 文章 |

`article_source_path` 同样必须位于 `wechat_collection_output_dir` 下，避免任意本地文件被作为文章输入读取。

## 后端模块边界

| 模块 | 职责 |
| --- | --- |
| `monitor/wechat_collect/native_login.py` | 微信 MP 扫码登录、二维码获取、扫码状态查询、登录确认 |
| `monitor/wechat_collect/session_store.py` | 加密保存 token/Cookie，返回安全会话元数据，处理过期和退出状态 |
| `monitor/wechat_collect/native_client.py` | 带会话的 MP HTTP 客户端，封装搜索公众号和文章列表接口 |
| `monitor/wechat_collect/html_export.py` | 下载文章正文并导出 HTML/Markdown/Text/JSON |
| `monitor/wechat_collect/providers.py` | provider 抽象，当前包含 native provider 与 exporter facade |
| `monitor/wechat_collect/tasks.py` | SQLite 持久化任务创建、后台执行、取消、结果写入 |
| `monitor/db/queries/wechat_collect.py` | 原生采集专用 CRUD，不把查询细节铺到 `monitor/db.py` |
| `server/__main__.py` | 暴露 `/api/wechat-native/*` 路由并保护路径边界 |

## 数据库表

| 表 | 说明 |
| --- | --- |
| `wechat_collect_sessions` | 原生登录会话。`token_enc` 与 `cookie_json_enc` 只保存加密值 |
| `wechat_collect_accounts` | 已发现公众号账号快照 |
| `wechat_collect_articles` | 已发现或已导出的文章快照 |
| `wechat_collect_tasks` | 原生采集任务、进度、结果和取消状态 |

新库由 `monitor/schema.sql` bootstrap；已有库由 `monitor/db.py` 中的 `v19_wechat_native_collect` 迁移补表。AI 文章工作流读取公众号文章的字段由 `v20_article_wechat_sources` 补齐。

## 安全约束

- 前端只持有 `session_id`，不持有 MP `token`、Cookie、AuthKey 或加密密文。
- `GET /api/wechat-native/sessions` 只返回昵称、头像、状态、过期时间等公开元数据。
- 原生采集任务不会向前端返回原始导出文件路径，只返回 `artifact_id` 与文件名；后端在打开或生成 AI 文章时再解析真实路径，并校验其必须位于 `wechat_collection_output_dir` 下。
- 登录会话默认按短期有效期保存；过期、登出或解密失败时需要重新扫码。
- 不要把 `session_id` 放进外部分享链接或日志上下文，它虽然不是原始凭据，但仍代表本地后端的会话引用。

## 代理与网络

原生采集通过 `monitor/wechat_collect/proxy_policy.py` 接入现有代理策略。后台任务默认按 `resolve_native_proxy_plan(cookies_present=True)` 选择请求代理，并把代理传给 WeChat MP API 和文章下载请求。若公众号平台请求失败，先检查：

- 当前动态代理/代理池是否可访问 `https://mp.weixin.qq.com`。
- 登录 Cookie 是否已经过期。
- 账号是否有权限访问公众号平台搜索和文章列表。
- WeChat MP 返回的 `base_resp.ret`，尤其是会话过期类错误。

## 验证命令

推荐在修改原生采集时至少运行：

```powershell
python -m pytest tests/test_wechat_collect_integration.py tests/test_wechat_native_schema.py tests/test_wechat_native_session_store.py tests/test_wechat_native_login_flow.py tests/test_wechat_native_client.py tests/test_wechat_native_tasks.py tests/test_wechat_native_api_contract.py tests/test_wechat_native_frontend_contract.py tests/test_ai_content_api_contract.py -q
cd frontend-vue
npm run build
```

如果只改前端文案或路由，也应保留 `tests/test_wechat_native_frontend_contract.py` 和 `npm run build`。如果改 SQLite schema 或会话存储，必须跑 schema/session/task 相关测试。

## 真实扫码 Smoke

启动后端服务后，可用脚本跑真实登录和 1 篇文章采集链路：

```powershell
python scripts/wechat_native_smoke.py --base-url http://127.0.0.1:5000 --api-token $env:MONITOR_API_TOKEN --fakeid <fakeid> --max-articles 1
```

脚本会下载二维码图片、等待扫码确认、调用 `/sessions/{session_id}/check`、预览文章列表、启动采集任务并轮询终态。也可以用 `--article-url https://mp.weixin.qq.com/s/...` 代替 `--fakeid`。

## 已知限制

- P0 导出是轻量 HTML 下载与文本/Markdown 转换，不追求完整资源打包、PDF、docx 或图片内联。
- 文章链接反查公众号依赖文章作者信息和公众号搜索结果，无法保证所有文章都能稳定反查 fakeid。文章 URL 或 HTML 里的 `__biz` 只是公开文章标识，不是 MP 后台 `appmsgpublish` 所需的 `fakeid`；不能精确匹配作者时需要手动搜索公众号或输入已知 fakeid。
- `check session` 会访问微信公众号后台首页，但页面结构可能变化；真正批量可用性仍以搜索、预览或采集请求为准。
- 微信公众号平台接口并非公开稳定 API，页面参数和响应结构变化时，需要优先补客户端解析测试。

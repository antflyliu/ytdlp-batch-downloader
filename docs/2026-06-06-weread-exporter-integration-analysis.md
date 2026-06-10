# weread-exporter 集成分析与实施记录

## 结论

`antflyliu/weread-exporter` 可以集成到当前项目，但不适合直接复制为常规服务端依赖。它是一个单文件 Python CLI 工具，依赖 Playwright 启动可见 Chromium，通过微信读书网页登录态和 Canvas `fillText` Hook 导出 Markdown。当前项目是 Python HTTP 服务 + SQLite + Vue 3 + Naive UI 的采集与 AI 内容工作台，因此最合适的第一阶段集成方式是：

- 保留 `weread-exporter` 的核心算法和运行假设。
- 将 CLI 流程封装为当前项目的后台任务服务。
- 通过 Vue 页面提供任务创建、进度查看、取消和结果下载。
- 将 Playwright 作为可选运行时依赖延迟检测，不强制加入主依赖。
- 优先通过 Chrome DevTools Protocol 复用调试 Chrome 会话；无法连接时可由应用启动专用调试 Chrome，仍不可用时回退到独立 Chromium profile。

## 技术栈差异

| 维度 | weread-exporter | 当前项目 | 集成判断 |
| --- | --- | --- | --- |
| 运行方式 | Python CLI | Python HTTP 服务 + 前端 UI | 需要封装为任务 API |
| 浏览器 | Playwright Chromium 可见窗口 | 服务默认不依赖浏览器自动化 | 作为可选能力，不阻断主服务启动；优先连接/启动 Chrome CDP |
| 登录 | 扫码登录，持久化浏览器 profile | Web UI API 鉴权 | 优先复用专用调试 Chrome 登录态；回退时由独立 Chromium 承载 |
| 输出 | Markdown + raw Canvas JSON | 多内容源工作台 | 映射为导出任务和 artifact 下载 |
| 数据状态 | 文件系统输出 | SQLite 任务状态 | 新增 `weread_export_tasks` |
| 前端 | 无 | Vue 3 + Naive UI | 新增统一风格页面 |

## 当前分支实现范围

- 新增 WeRead 导出任务表 `weread_export_tasks`，并接入 `schema_migrations` 的 `v24_weread_exporter_tasks`。
- 新增 `monitor/weread_exporter`：
  - `core.py`：迁移 `book_id` 解析、章节 hash、Canvas Hook、文本重建、Playwright 导出 runner。
  - `core.py`：新增 `WEREAD_BROWSER_MODE` / `WEREAD_CHROME_CDP_ENDPOINT`，默认自动尝试 `http://127.0.0.1:9222` 的 Chrome CDP。
  - `core.py`：新增调试 Chrome 启动能力，使用 `data/weread_chrome_cdp_profile` 保存会话；可通过 `WEREAD_CHROME_PATH` 指定 Chrome 路径。
  - `tasks.py`：任务创建、后台执行、取消、结果 artifact 解析和路径约束。
- 新增 `/api/weread-exporter/...` API：
  - `GET /api/weread-exporter/config`
  - `POST /api/weread-exporter/tasks/start`
  - `GET /api/weread-exporter/tasks`
  - `GET /api/weread-exporter/tasks/:id`
  - `POST /api/weread-exporter/tasks/:id/cancel`
  - `POST /api/weread-exporter/chrome/start`
  - `GET /api/weread-exporter/artifacts/:artifact_id`
- 新增 Vue 页面 `/weread-exporter`，支持：
  - 输入微信读书 URL 或 `book_id`。
  - 指定导出根目录下的输出子目录。
  - 选择是否保存 raw Canvas 坐标数据。
  - 查看 Playwright 是否安装、Chrome CDP 状态、浏览器 profile 目录、导出根目录。
  - 编辑 Chrome CDP 端点和调试 Chrome profile 目录；任务会按本次提交的值启动/连接浏览器。
  - 当 Chrome CDP 不可用时，一键打开专用调试 Chrome。
  - 查看任务列表、进度、取消任务、下载成功结果。
- 新增中英文文案、侧栏导航、页头标题。

## 不在本分支处理的内容

- 不自动安装 Playwright 或 Chromium。安装浏览器属于运行环境变更，保留为显式运维步骤。
- 不提供远程 QR 码代理。`weread-exporter` 依赖可见浏览器窗口；Chrome CDP 可复用专用调试 Chrome 会话，回退路径仍保留本机扫码体验。
- 不绕过微信读书阅读权限。用户必须拥有目标书籍的有效阅读权限。
- 不做 EPUB/PDF 输出。当前上游只导出 Markdown。
- 不把导出结果直接送入 AI 文章流水线。后续可以新增 `source_type=weread_book` 或“从 artifact 创建文章任务”。

## UI/UX 约束

页面遵循 `DESIGN.md` 和 `$ui-ux-pro-max` 对内容工作台的建议：

- 使用暖色卡片、`var(--accent)`、`var(--border)`、`var(--surface)` 等全局 token。
- 标题和详情区使用 Georgia serif，保持编辑感。
- 页面第一屏就是可操作工作台，而不是说明型 landing page。
- 所有按钮有明确 loading/disabled 状态；任务和结果项提供 hover/focus 反馈。
- 结果下载使用 artifact API，不暴露任意文件路径读取能力。

## 风险与后续建议

- Playwright 可见浏览器在无桌面环境的服务器上不可用；建议在桌面版或有显示环境的服务中使用。
- Playwright 不能接管普通启动且未开启远程调试端口的 Chrome；应用默认启动一个专用调试 Chrome profile。若必须复用普通 Chrome 的现有登录态，需要手动以 `--remote-debugging-port=9222` 重新启动该 Chrome，或通过 `WEREAD_CHROME_CDP_ENDPOINT` 指向其他端点。
- 任务服务仍串行执行导出；如果已有导出任务占用 worker，新任务会显示等待，并在超时后明确失败，避免长期停留在 `pending`。
- 微信读书前端 Canvas 渲染策略变化会影响文本捕获，需要用真实账号定期回归。
- 长篇书籍导出耗时较长，后续可以增加章节级重试、暂停/恢复和并发控制。
- 如果要把 WeRead 作为正式内容源，应补充版权提示、导出结果进入 AI 内容流水线的人工确认步骤，以及更细的任务审计记录。

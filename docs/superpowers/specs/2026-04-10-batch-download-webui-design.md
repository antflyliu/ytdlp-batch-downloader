# Web UI 批量下载弹窗 — 实现设计方案

> **As-built update (2026-04-10):** 当前实现已经从最初草案演进为服务端持有完整上传 URL 集的模式。以下几点优先于后续旧草案片段：
> - 上传接口返回 `upload_id` 与 `preview_urls`，完整 URL 列表保存在服务端上传会话中。
> - 启动接口使用 `upload_id` + `proxy_pool_id`（可选）+ 配置启动任务，不再直接接收前端持有的完整 `urls` 或裸 `proxy`。
> - Web UI 批量下载通过 `resolve_for_web_batch_download()` 路由，不再错误复用 account-only 的 `resolve_for_manual_download(None, ...)`。
> - Cookie 覆盖输入代表**服务器端路径**；UI 仅帮助用户填写该路径，不直接读取浏览器本地 Cookie 文件。
> - `/api/batch/tasks/:id` 对外统一返回规范化结果字段：`status` / `info` / `url`。
> - 新增 `POST /api/batch/tasks/:id/cancel`，前端点击“取消”会请求服务端取消任务；若当前视频仍在下载，任务会先进入 `cancelling`，随后落到 `cancelled`。
> - 最近任务已持久化到数据库（`web_batch_tasks`），服务重启后仍可查看历史任务；启动时会把残留 `running/cancelling` 任务标记为中断。

## 0. 当前最终契约（2026-04-10 as-built）

### API

| 端点 | 方法 | 当前用途 |
|------|------|----------|
| `/api/batch/upload` | POST multipart | 解析上传文件，返回 `upload_id`、`url_count`、`preview_urls` |
| `/api/batch/start` | POST JSON | 使用 `upload_id` + 配置启动任务 |
| `/api/batch/tasks` | GET | 返回最近批量任务列表（按创建时间倒序） |
| `/api/batch/tasks/:id` | GET | 返回单个任务详情与规范化结果 |
| `/api/batch/tasks/:id/cancel` | POST | 请求取消任务，状态进入 `cancelling/cancelled` |

### Web UI 语义

- 上传成功后，前端仅保留 `upload_id` 与预览，不持有完整 URL 列表
- 代理池选择传 `proxy_pool_id`，不传脱敏后的代理 URL
- Cookie 输入框表示**服务器端路径**
- 最近任务区可重新打开运行中/已完成/已取消任务

### 测试入口

- `tests/test_batch_webui_api_behavior.py`
- `tests/test_batch_webui_contract.py`
- `tests/test_batch_download_cancellation.py`

> **Agent 用途**：指导 `monitor_server.py` 后端 API + `monitor_web/index.html` 前端弹窗的实现
> **依赖**：复用 Tkinter 版已实现的 `BatchDownloadDialog` 设计逻辑；复用 `monitor_server.py` 已有 `_DownloadTaskManager` + `batch_download()` 引擎

---

## 1. 架构

### 1.1 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `monitor_server.py` | 新增 4 个 API 端点 + 复用 `_DownloadTaskManager` |
| 修改 | `monitor_web/index.html` | 新增 modal HTML + CSS + JS |

### 1.2 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/batch/upload` | POST multipart | 上传文件，调用 `read_urls_from_file()`，返回 URL 数量 |
| `/api/batch/start` | POST JSON | 启动下载：URLs + output_path + resolution + proxy + cookies + sub_langs |
| `/api/batch/tasks` | GET | 返回所有批次任务列表（含状态） |
| `/api/batch/tasks/:id` | GET | 返回单个任务详情 + 进度 |

### 1.3 复用已有能力

- `_DownloadTaskManager`：任务管理（进度、状态、结果）
- `batch_download()`：下载引擎（含 aria2 加速、代理路由、Cookie）
- `resolve_for_manual_download()`：统一代理解析链
- `log_download_decision()`：决策日志
- `load_config()` / `save_config()`：配置读写

### 1.4 回归安全边界

- 不修改已有 `/api/accounts/{id}/videos/batch-download` 端点
- 不修改已有 `_DownloadTaskManager` 内部逻辑
- 不修改 Tkinter `BatchDownloadDialog`

---

## 2. 后端 API 规格

### 2.1 `POST /api/batch/upload`

**multipart/form-data**：
- `file`: 上传文件（Excel/CSV/TXT）

**逻辑**：
1. 从 `request.files` 读取上传文件到临时目录
2. 调用 `read_urls_from_file()` 解析
3. 返回 URL 数量（不返回 URL 内容）

**Response**：
```json
{
  "ok": true,
  "filename": "video_list.xlsx",
  "url_count": 127,
  "urls": ["url1", "url2"]  // 前 5 条预览
}
```
或：
```json
{"ok": false, "error": "文件格式不支持或解析失败"}
```

### 2.2 `POST /api/batch/start`

**Request Body**：
```json
{
  "urls": ["https://youtube.com/...", ...],
  "output_path": "D:\\Videos",
  "resolution": "best",
  "proxy": null,
  "cookies_file": "",
  "sub_langs": "zh-Hans,en",
  "no_subs": false,
  "enable_aria2": false
}
```

**逻辑**：
1. 路径安全校验（同 `_api_account_videos_batch_download`）
2. Cookie 文件校验（同上）
3. 使用 `resolve_for_manual_download(direct=True)` 做代理解析（不走数据库账户绑定）
4. 调用 `_task_mgr.create_task()`
5. 在后台线程执行 `batch_download()`
6. 复用 `_DownloadTaskManager.update_progress()` 更新进度

**Response**：
```json
{
  "ok": true,
  "task_id": "abc123def456"
}
```

### 2.3 `GET /api/batch/tasks`

返回 `_task_mgr._tasks` 中所有任务（含已完成/进行中）。

**Response**：
```json
{
  "tasks": [
    {
      "task_id": "abc123",
      "status": "running",
      "total": 127,
      "completed": 4,
      "success": 3,
      "failed": 1,
      "current_video": "Python 入门教程 #12",
      "created_at": "2026-04-09T10:00:00+08:00"
    }
  ]
}
```

### 2.4 `GET /api/batch/tasks/:id`

返回单个任务详情。

**Response**：
```json
{
  "task_id": "abc123",
  "status": "running",
  "total": 127,
  "completed": 4,
  "success": 3,
  "failed": 1,
  "current_video": "Python 入门教程 #12",
  "results": [
    {"status": "成功", "info": "下载成功 | 代理: 直连 | 字幕: yt-dlp: subtitle.srt"},
    {"status": "失败", "info": "429 Too Many Requests | 代理: http://proxy:8080"}
  ],
  "created_at": "2026-04-09T10:00:00+08:00"
}
```

---

## 3. 前端弹窗规格

### 3.1 入口

`header-right` 第 4 个按钮：
```html
<button class="btn btn-ghost" onclick="openBatchDownload()">⬇ 批量下载</button>
```

### 3.2 Modal HTML 结构

```
modal-batch-download (max-width: 640px, height: 88vh)
├── modal-header (3px indigo left border)
│   ├── modal-title: "⬇  批量下载"
│   └── modal-close
└── modal-body
    ├── 上传区
    │   ├── pill: [Excel] [CSV] [TXT]  ← toggle, active 时 indigo 背景
    │   ├── drop-zone (dashed border)
    │   │   ├── idle: 虚线框 + 拖入图标 + "拖入或点击上传"
    │   │   └── selected: solid green border + "✓ video_list.xlsx · 127 条 URL"
    │   └── error: red border + "❌ 解析失败: xxx"
    │   └── upload-btn (hidden, 用于 file input)
    │
    ├── 配置区
    │   ├── form-row: 保存路径 + [浏览] 按钮
    │   ├── form-row: 视频画质 select
    │   ├── form-row: 字幕语言 input + checkbox 下载字幕
    │   ├── form-row: 代理池 select
    │   └── form-row: Cookie input + [浏览] 按钮
    │
    ├── 进度区（下载中显示）
    │   ├── track-bar (indigo fill + pulse dot)
    │   │   └── percentage label
    │   ├── current-video label
    │   ├── counter: "✓ 4/12  · ✗ 1  · ⏳ 122"
    │   └── log-toggle (▶/▼ 展开详情)
    │       └── log-text (JetBrains Mono, 滚动)
    │
    └── 底部按钮
        └── [▶ 开始下载] [取消] / [✓ 完成]
```

### 3.3 CSS 变量复用

```css
/* 复用现有变量 */
--accent: #6366f1           /* indigo, 主强调 */
--success: #22c55e
--error: #ef4444
--surface, --surface2       /* 卡片背景 */
--border                    /* 边框 */
--text, --text-muted        /* 文字 */
--mono: 'JetBrains Mono'    /* 日志区 */
```

### 3.4 交互逻辑

1. **上传**：`drop-zone` 点击 → `<input type="file">` → POST `/api/batch/upload`
2. **配置**：「浏览」→ `<input type="file" webkitdirectory?`（路径）或普通文件选择
3. **下载**：POST `/api/batch/start` → 开始轮询 `/api/batch/tasks/:id`
4. **进度**：每 2 秒轮询一次，更新 track-bar 填充 + 计数器 + 日志
5. **完成**：状态机切换按钮文本，显示汇总行
6. **错误**：网络错误 toast，不打断用户输入

---

## 4. 代理与 aria2

- 代理解析走 `resolve_for_manual_download(direct=True)`（不走账户绑定）
- aria2 加速：若 `config["enable_aria2"]` 为 True，传 `extra_ydl_opts=build_aria2_opts(proxy)`
- 速率限制：`_check_rate_limit()` 对 `/api/batch/*` 不豁免（防滥用）

---

## 5. 实现清单

| # | 任务 | 文件 |
|---|------|------|
| 1 | `POST /api/batch/upload` 后端 | `monitor_server.py` |
| 2 | `POST /api/batch/start` 后端 | `monitor_server.py` |
| 3 | `GET /api/batch/tasks` 后端 | `monitor_server.py` |
| 4 | `GET /api/batch/tasks/:id` 后端 | `monitor_server.py` |
| 5 | `openBatchDownload()` 前端 JS | `index.html` |
| 6 | modal HTML 结构 | `index.html` |
| 7 | modal CSS（轨道进度条 + 上传区） | `index.html` |
| 8 | 入口按钮加入 header-right | `index.html` |
| 9 | 轮询逻辑 + 状态切换 JS | `index.html` |
| 10 | 接口测试 | `tests/test_batch_server.py` |

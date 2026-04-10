---
name: project overview
description: YouTube 批量下载器 + 多账户视频监控系统
type: project
---

# YouTube Monitor — 项目概览

## 技术栈
- Python 3.12 + Tkinter GUI
- YouTube Data API v3 (search.list / playlistItems.list)
- APScheduler BackgroundScheduler (后台调度)
- SQLite (monitor.db)
- PyInstaller (exe 打包)

## 核心模块
- `ytb_api.py` — YouTube API 封装，支持 search/playlist 两种获取模式，含配额保护
- `monitor/` — 视频监控子系统
  - `db.py` — SQLite CRUD，线程安全
  - `fetcher.py` — YouTubeFetcher，支持 search/playlist 双模式
  - `detector.py` — 新视频检测 (INSERT OR IGNORE + get_new_video_ids)
  - `notifier.py` — 多平台通知 (飞书/钉钉/企微 + 文件日志)
  - `scheduler.py` — APScheduler 调度器，_GLOBAL_WEBHOOKS 支持多平台
  - `__main__.py` — CLI 入口 (list/stats/events/add/delete/enable/disable/start/stop/once)
  - `config.json` — 全局配置 (3 平台 Webhook URL)
  - `schema.sql` — 数据库 schema (accounts/events/videos/notify_logs)
- `monitor_ui.py` — 独立 Tkinter UI，含可嵌入组件 `MonitorPage`
- `ytdownload_ui.py` — 主下载器 UI，嵌入 `MonitorPage` 组件

## 数据库表
- `monitor_accounts` — 账户配置 (name/url/api_key_env/mode/limit/interval/enabled/notify)
- `monitor_events` — 扫描事件 (account/scan_started/scan_ended/status/total/new/error/duration)
- `monitor_videos` — 视频详情 (video_id/title/url/published/view_count/duration/thumbnail/notify_status/download_status/at/path/error)
- `monitor_notify_logs` — 通知日志 (event_id/platform/status/webhook_url/response/error/duration)
- `channel_meta_cache` — 频道元信息缓存 (handle→channel_id→uploads_playlist_id，永久缓存减少 API 调用)
- `api_quota_usage` — API Quota 使用记录 (api_key_env/date_key/api_calls/scans_done/blocked_scans)

## 新增模块
- `monitor/cache.py` — 频道元信息永久缓存，减少 103→0 API units/次（缓存命中时）
- `monitor/quota.py` — Quota 跟踪（budget 检查，80%/90%/100% 告警）
- `monitor_server.py` — Web UI 服务端（REST API + 静态文件，端口 5000）
- `monitor_web/index.html` — Web UI 前端（账户管理/视频详情/Quota 状态/缓存管理）

## 关键修复 (历史)
1. ytb_api.py — 修复无限翻页导致 Quota 超限，添加 max_limit/published_after_days 参数
2. monitor 模块 — 修复多平台通知 (飞书→飞书/钉钉/企微)
3. schema — feishu_url → webhook_url + notify_platform
4. PyInstaller — 修复 hidden_imports 缺失
5. monitor_ui — 修复表格头解包 bug
6. channel_meta_cache table missing — cache.py 中 _ensure_schema() 调用顺序错误（_DB_PATH/_log 需在 _ensure_schema() 前定义）
7. UNIQUE constraint on edit account — 前后端均未传 id，改为 UPDATE vs INSERT
8. sqlite3.Row.get() 缺失 — 全部改为返回 dict
9. _GLOBAL_WEBHOOKS always empty — UI 立即扫描绕过 scheduler.start()，添加 _ensure_global_webhooks()
10. 修复 set_global_feishu_url() 函数体被误删
11. notifier._log_result() 缺少 webhook_url 参数
12. monitor_notify_logs INSERT 使用 feishu_url 列名（schema 用 platform/webhook_url）
13. API cache refresh endpoint — 前端发送 body，后端未读
14. JS 页面空白 — index.html line 1332 缺少 forEach 闭合括号
15. /api/accounts/{id}/videos GET 路由缺失（只加了 POST）
16. **自动下载路径无 no_subs=True** — 调度器 `_auto_download_videos` 调用 `batch_download` 不传 `no_subs`，默认 False → 自动触发 WhisperX CPU 推理 → 修复：显式传 `no_subs=True`
17. **JS 语法错误** — `vdToggleAll` 末尾多余 `}` 导致所有 JS 功能失效
18. **video_ids 无类型校验** — API 接受任意值，非 list 类型触发 Python 异常暴露堆栈 → 修复：isinstance 校验
19. **vdToggle 每次重渲染** — 勾选一个 checkbox 触发整表 API 请求 + O(n) DOM 重建 → 修复：仅更新 DOM 状态

## 字幕下载策略（2026-04-04）

### WhisperX 绕过机制
- `batch_download()` 的 `no_subs=True` 参数完全跳过字幕处理（含 WhisperX）
- `no_subs=False` + `sub_langs` 有值 → yt-dlp 下载官方字幕 → 无字幕时静默跳过（WhisperX 不会被调用）
- 触发 WhisperX 的唯一路径：`no_subs=False` + `sub_langs` 有值 + yt-dlp 下载后检查无字幕 → 才进入 WhisperX 分支

### 默认行为
| 下载路径 | no_subs | sub_langs | 字幕行为 |
|----------|---------|-----------|---------|
| Web UI 批量下载（默认） | True | None | 不下载字幕 |
| Web UI + 开启字幕开关 | False | `default_sub_langs` | yt-dlp 下载官方字幕 |
| 调度器自动下载 | True（硬编码） | None | 不下载字幕 |
| CLI | False（默认） | `"zh-Hans,en"`（默认） | 下载字幕 |

### 前端字幕开关架构
```
vdSubToggle (checkbox)
    ↓ onchange
_updateVdSubLabelText() — 更新标签文字
    ↓
_getVdSubPayload() — 读取 _gConfig.default_sub_langs
    ↓ Object.assign
POST /api/accounts/{id}/videos/batch-download
    ↓
_api_account_videos_batch_download
    ↓ sub_langs, no_subs
batch_download(urls, output_path, ..., sub_langs, no_subs)
```

### 全局配置化
- `default_sub_langs` 新增到 `monitor/config.json`，默认值 `"zh-Hans,en"`
- 全局配置通过 `/api/config` GET 返回，`openConfig()` 打开弹窗时缓存到 `_gConfig` 变量
- `_getVdSubPayload()` 从 `_gConfig` 读取，页面刷新后需重新打开配置弹窗刷新缓存

## 数据库增强（2026-04-04）
- SQLite WAL 模式：`PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`
- 数据库备份函数：`backup_db()` — 保留最近 7 份到 `data/backup/`

## 测试基础设施（2026-04-04）
- GitHub Actions CI：`.github/workflows/ci.yml` — ruff lint + pytest + pyinstaller build
- `tests/test_batch_download_api.py`：12 个测试用例覆盖 video_ids 校验、字幕默认值、调度器 no_subs
- 入口: `monitor_ui.py` (`console=False`)
- 打包: `YouTubeMonitor.exe` (323MB)
- hiddenimports: apscheduler, requests, googleapiclient, tenacity, pandas, openpyxl, monitor.*
- datas: `monitor/config.json`, `monitor/schema.sql`

## 关键修复 (历史)
1. ytb_api.py — 修复无限翻页导致 Quota 超限，添加 max_limit/published_after_days 参数
2. monitor 模块 — 修复多平台通知 (飞书→飞书/钉钉/企微)
3. schema — feishu_url → webhook_url + notify_platform
4. PyInstaller — 修复 hiddenimports 缺失
5. monitor_ui — 修复表格头解包 bug

## 使用方式
```bash
# CLI
python -m monitor list
python -m monitor add "综艺Show" "@C-HitShow" --api-key-env YOUTUBE_Data_API_V3
python -m monitor start

# GUI
python monitor_ui.py
dist/YouTubeMonitor.exe  # PyInstaller 打包

# 嵌入 (ytdownload_ui.py 中)
import monitor_ui
self._monitor_page = monitor_ui.MonitorPage(frame, colors=self.colors)
```

## Session Memory Update (2026-04-10)

### Web UI 批量下载能力已完成的关键升级
- 批量上传/启动链路已改为 **server-owned `upload_id` 模型**：前端只保留预览与 `upload_id`，完整 URL 集由服务端保存。
- Web UI 批量下载已使用 **独立路由入口**，不再错误复用 account-only 的 `resolve_for_manual_download(None, ...)`。
- 代理选择语义已改为 **`proxy_pool_id`**；Cookie 覆盖语义已收敛为 **服务器端文件路径**。
- 批量任务已支持 **服务端取消**：状态流转为 `running -> cancelling -> cancelled`。
- 最近任务已从内存态升级为 **数据库持久化**（`web_batch_tasks`），服务重启后仍可查看；启动时会把残留 `running/cancelling` 任务标记为中断错误。
- 批量下载弹窗已具备轻量任务中心能力：
  - 最近任务下拉 + 卡片列表
  - 状态筛选（全部 / 进行中 / 已结束 / 已取消）
  - 汇总计数
  - 卡片级“重开 / 取消”操作
  - 运行中任务恢复查看
- multipart 上传解析运行时已从 **`cgi.FieldStorage`** 切换为项目内最小解析器 `monitor/http_multipart.py`；旧 `cgi` 方案保留为注释备用参考。

### schema / DB 对齐结论
- `monitor/data/monitor.db` 的运行时初始化 schema 来源是 **`monitor/schema.sql`**，不是仓库根目录的 `schema.sql`。
- 已补齐 `monitor/schema.sql` 中缺失的运行时对象，包括：
  - `api_quota_usage`
  - `channel_meta_cache`
  - `schema_migrations`
  - `alembic_version`
  - `dynamic_proxy_providers`
  - `download_decision_logs`
  - `provider_scheduler_runs`
  - `web_batch_tasks`
- 还为 `monitor/schema.sql` 的表字段补充了更详细的中文注释，说明字段用途、状态语义、时间格式、外键删除行为等。

### 关键验证状态
- 全量测试最近一次结果：`pytest -q` **265 passed**。
- 重点验证通过：
  - Web batch API behavior
  - UI contract
  - task cancellation
  - multipart parser
  - recent-task persistence / reopen / cancel actions

### 仍需注意的风险
- 取消仍是“尽快取消”，不是强杀底层下载进程。
- 根目录 `schema.sql` 与 `monitor/schema.sql` 仍是两套不同职责的 schema 文件，后续可再补职责说明避免混淆。

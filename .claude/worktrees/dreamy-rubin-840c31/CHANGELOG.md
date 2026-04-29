# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Web UI 字幕切换开关**：视频详情弹窗工具栏新增「字幕:否/是」切换，勾选后 yt-dlp 用 cookies 下载官方字幕
- **字幕语言可配置**：全局配置新增 `default_sub_langs` 字段，可在配置弹窗中自定义批量下载时的字幕语言
- **批量下载 API**：POST `/api/accounts/{id}/videos/batch-download`，支持 `sub_langs` / `no_subs` 参数
- **SQLite WAL 模式**：数据库连接启用 WAL + NORMAL 同步模式，提升多线程并发写入性能
- **数据库备份**：新增 `backup_db()` 函数，自动保留最近 7 份备份到 `data/backup/`

### Changed

#### ⚠️ 破坏性变更：字幕下载默认行为反转

- **变更前**：`batch_download()` 默认 `no_subs=False`，自动下载字幕；无官方字幕时触发 WhisperX ASR 生成
- **变更后**：默认 `no_subs=True`，**不再自动下载字幕，不再触发 WhisperX**
- **影响范围**：
  - Web UI 批量下载：默认不下载字幕（需手动开启「字幕」开关）
  - 调度器自动下载：始终不下载字幕（`no_subs=True` 硬编码）
  - CLI（`Youtube_Downloader.py`）：仍默认下载字幕（行为未变）
- **用户操作**：若需字幕，在 Web UI 详情弹窗工具栏勾选「字幕」开关；确保已配置 cookies 文件
- **WhisperX ASR**：仅在用户显式勾选字幕 + cookies 可用 + 无官方字幕时，由 yt-dlp 自动跳过（`no_subs=True` 时完全不进入 WhisperX 分支）

#### 调度器自动下载参数

- `monitor/scheduler.py` 的 `_auto_download_videos()` 显式传入 `no_subs=True`，专注快速下载视频

#### 批量下载 API 默认值

- `monitor_server.py` 的 `_api_account_videos_batch_download()`：
  - `no_subs` 默认值从 `False` 改为 `True`
  - `sub_langs` 默认值从 `"zh-Hans,en"` 改为 `None`（由前端显式传入）

### Fixed

- **`video_ids` 类型校验**：`POST /api/accounts/{id}/videos/batch-download` 现校验 video_ids 必须为整数数组，防止类型混淆
- **`output_path` 路径安全校验**：规范化路径并限制在允许根目录下，防止目录穿越攻击
- **错误响应脱敏**：账户操作/删除异常不再返回原始 Python 堆栈，改为「操作失败，请查看服务器日志」
- **`vdToggle` 性能优化**：勾选/取消视频不再触发整表重渲染，避免 N 次 API 请求和 O(n) DOM 重建
- **`vdToggleAll` 性能优化**：全选/取消全选不再触发 API 请求
- **`fmtTime` 异常处理**：日期解析失败时返回 `—` 而非原始 ISO 字符串
- **日志堆栈完整**：`scheduler.py` 批量下载异常日志补全 `exc_info=True`
- **CSS 死代码清理**：`.modal` 重复样式定义合并
- **`parseInt` radix 补全**：全部 5 处调用补全 `, 10` 参数

### Security

- 输入校验：`video_ids` 类型验证，防止类型混淆攻击
- 错误脱敏：异常堆栈不再暴露到 API 响应

## [0.x.x] — 2026-04-03

### Added

- 视频详情弹窗全屏化（占满整个页面）
- 视频时长列（`duration_sec`）显示
- 批量下载进度实时反馈
- 批量下载任务管理（`/api/download-tasks` 接口）
- YouTube API 视频时长解析（ISO 8601 → 秒）
- `get_videos_by_ids` 数据库查询接口

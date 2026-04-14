# YouTube 内容管道 — 产品定义

> **核心用户**：内容运营者（自己使用，未来可能扩展到团队）
> **核心价值主张**：把 YouTube 内容搬运到全网，实现监控 → 下载 → 分发的全链路自动化
> **竞品状态**：暂未找到同类开源竞品

---

## 1. 产品定位

### 1.1 当前是什么

一个本地运行的 YouTube 内容管道工具，包含三个逐步演进的能力层次：

```
层次 1：YouTube 视频批量下载
  └─ 从 Excel/TXT 导入 URL，CLI 或 GUI 下载，支持 aria2 加速

层次 2：YouTube 频道监控 + 通知
  └─ 多账户定时扫描、SQLite 持久化、飞书/钉钉/企微 Webhook 通知

层次 3：监控 → 自动下载 → 自动分发（规划中）
  └─ 新视频出现后自动下载，下载完成后自动上传到抖音/快手/B站等平台
```

### 1.2 长期是什么

**"内容运营者的内容管道操作系统"**

不是单一功能工具，而是一个可配置的内容自动化平台：
- 监控源：YouTube（当前）、未来可扩展到 B站/TikTok 等
- 处理节点：下载、转码、加水印、生成字幕、标题适配
- 分发节点：抖音、快手、B站、视频号、小红书、微信公众号等
- 编排方式：用户配置 pipeline，工具按序执行

### 1.3 不做什么（反Scope）

- **不做视频剪辑/特效**（交给 ffmpeg 或专业工具）
- **不做内容审核/合规**（用户负责）
- **不做多用户隔离/权限系统**（当前版本是单机工具）
- **不做云托管/SaaS**（当前版本是本地运行）

---

## 2. 核心用户画像

| 维度 | 描述 |
|------|------|
| **用户类型** | 内容运营者（YouTube 频道搬运 / 二次创作） |
| **使用频率** | 每日自动运行，偶需手动操作 |
| **技术背景** | 有一定动手能力，能配置 API Key、Cookie |
| **核心痛点** | 手动盯 YouTube 频道 → 手动下载 → 手动上传，重复繁琐 |
| **使用场景** | 搬运 YouTube 内容到国内平台（抖音/快手/B站） |
| **当前状态** | 自己用，没有团队协作需求 |

---

## 3. 核心使用流程

```
用户配置阶段（一次性）
├── 添加监控账户（YouTube 频道 URL + API Key）
├── 配置通知渠道（飞书 Webhook）
├── 配置下载设置（输出路径、是否自动下载）
├── 配置分发平台（sau 账号登录：抖音/快手/B站/视频号）
└── 配置分发规则（标题模板、标签、是否定时发布）

日常运行阶段（自动）
├── [定时] 扫描各频道最新视频
├── [检测] 发现新视频 → 入库
├── [通知] 推送飞书卡片（可配置开关）
├── [下载] 自动下载到本地（可配置开关）
├── [分发] 自动上传到已配置平台（可配置开关）
└── [记录] 全链路状态可查（下载状态、上传状态）
```

---

## 4. 功能模块

### 4.1 已实现

| 模块 | 入口 | 状态 |
|------|------|------|
| 批量下载（CLI/GUI） | `Youtube_Downloader.py` / `ytdownload_ui.py` | ✅ 稳定 |
| 频道监控 | `monitor/scheduler.py` | ✅ 稳定 |
| 通知推送 | `monitor/notifier.py` | ✅ 稳定（飞书/钉钉/企微） |
| Web UI 管理 | `monitor_server.py` + `monitor_web/` | ✅ 稳定 |
| API Key 管理 | SQLite `api_keys` 表 | ✅ 稳定 |
| 代理池管理 | `monitor/proxy_*.py` | ✅ 稳定 |
| Web 批量下载 | `monitor_server.py` / `monitor_web/index.html` | ✅ 新增 |
| 监控数据库 | SQLite `monitor_videos` 表 | ✅ 稳定 |

### 4.2 开发中

| 模块 | 说明 | 依赖 |
|------|------|------|
| 自动分发 | `social-auto-upload` sau CLI 集成 | Phase 0: sau 安装验证 |

#### 4.2.1 分发限流策略（已决策）

为防止平台检测账号关联，上传行为需遵循以下限流规则：

| 规则 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| 同账号上传间隔 | `upload_interval_minutes` | 30 | 同一账号两次上传之间至少间隔 N 分钟 |
| 单账号每日上限 | `account_daily_upload_limit` | 10 | 单账号每天最多上传 N 个视频 |
| 全局并发数 | `max_concurrent_uploads` | 1 | 同时最多 N 个上传任务在执行 |
| 失败重试间隔 | `retry_interval_minutes` | 60 | 上传失败后等待 N 分钟再重试 |
| 失败重试上限 | `max_upload_retries` | 3 | 单视频最多重试 N 次，超过则标记失败 |

限流实现方式：独立上传队列 + 调度器（类似 `monitor/scheduler.py`），不阻塞下载线程。

#### 4.2.2 上传失败通知（已决策）

复用现有 `monitor/notifier.py` 基础设施：

```
上传失败触发条件
├── 上传重试次数达到上限（max_upload_retries）
├── sau CLI 执行超时（默认 300s）
└── sau CLI 返回非零退出码

通知内容
├── 视频标题
├── 目标平台
├── 失败原因（sau stderr 或超时）
├── 重试次数
└── 操作建议（手动检查 / 重新触发）

通知渠道
└── 复用现有账户级 webhook 配置（飞书/钉钉/企微可选）
```

数据库层面新增 `monitor_videos.upload_notify_status` 字段，复用 `notify_status` 的 `pending/sent/failed` 模式。

### 4.3 规划中（优先级排序）

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P1 | 自动分发引擎 | 监控下载完成 → 自动触发 sau 上传 |
| P1 | 上传状态追踪 | DB 记录每个视频的上传平台/状态/时间 |
| P2 | 定时发布 | 支持设置发布时间（抖音/快手均支持定时） |
| P2 | 分发配置 UI | Web UI 配置各平台账号、标题模板、标签 |
| P3 | 视频预处理 | ffmpeg 加水印、重新编码（上传前标准化） |
| P3 | 多语言字幕生成 | WhisperX 生成字幕，配合上传 |
| P4 | 跨平台标题适配 | 每个分发平台不同的标题/描述策略 |
| P4 | 监控源扩展 | 支持监控 B站/TikTok 等其他平台 |

---

## 5. 架构现状与约束

### 5.1 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 核心语言 | Python 3.12 | 主力开发语言 |
| 下载引擎 | yt-dlp | YouTube 及其他平台下载 |
| 数据库 | SQLite | 监控数据持久化 |
| Web 服务 | `http.server` + 线程池 | `monitor_server.py`（2120行） |
| 前端 | Vanilla HTML/JS/CSS | `monitor_web/index.html`（296KB） |
| GUI | Tkinter | `monitor_ui.py`（1659行）/ `ytdownload_ui.py` |
| 打包 | PyInstaller | 输出 `YouTube批量下载器.exe`（~305MB） |
| 定时任务 | APScheduler | `monitor/scheduler.py` |
| 代理管理 | 自研代理池 | `monitor/proxy_*.py` |
| 分发引擎 | `social-auto-upload` sau | 第三方（浏览器自动化） |

### 5.2 数据库 Schema（16 张表）

```
核心业务表
├── monitor_accounts        # 监控账户（YouTube 频道）
├── monitor_events         # 扫描事件日志
├── monitor_videos         # 视频记录（下载状态 / 未来：上传状态）
├── monitor_notify_logs    # 通知发送日志
├── api_keys              # YouTube API Key 管理
├── api_quota_usage       # 每日配额使用记录
└── web_batch_tasks       # Web 批量下载任务历史

系统表
├── schema_migrations     # 数据库迁移版本追踪
├── app_state             # 应用状态（token 等）
└── channel_meta_cache    # 频道元数据缓存

代理相关表
├── proxy_pools           # 代理池配置
├── dynamic_proxy_providers   # 动态代理服务商
├── dynamic_proxy_candidates  # 代理候选池
├── download_decision_logs    # 下载决策日志
└── provider_scheduler_runs  # 提供商调度运行记录
```

### 5.3 关键约束

| 约束 | 说明 |
|------|------|
| **平台限制** | 国内平台（抖音/快手/B站等）均无公开上传 API，必须用浏览器自动化 |
| **Cookie 有效期** | sau 的平台登录 Cookie 通常 30 天有效，需定期刷新 |
| **账号风险** | 浏览器自动化可能触发平台检测，建议单账号低频操作 |
| **单机运行** | 当前无多用户/云端方案，数据和配置均在本地 |
| **PyInstaller 打包** | 每次重建 spec 文件需重加 `hiddenimports` |

---

## 6. 竞品分析

### 6.1 竞品现状

**暂未找到同类开源竞品。** 现有类似工具均为单一功能：

| 工具 | 功能 | 与本项目对比 |
|------|------|-------------|
| yt-dlp | 视频下载 | 有下载，无监控/分发 |
| social-auto-upload | 社交媒体上传 | 有上传，无监控/下载 |
| bilibili-upos | B站投稿 | 单一平台，无分发管理 |
| YTMC（Chrome扩展） | YouTube 监控 | 仅监控，无分发 |

### 6.2 差异化定位

本项目的护城河是**全链路打通**：
- 监控 → 下载 → 分发 三个环节在同一工具里共享同一套数据库和配置
- 用户只需配置一次，后续全自动化
- 状态全链路可查（哪个视频下载成功/失败、上传成功/失败）

---

## 7. 路线图

### Phase 0：环境验证（TODO）

- [ ] 在本机安装 `social-auto-upload`（`sau` CLI）
- [ ] `sau douyin login` 手动登录一次抖音
- [ ] 手动跑 `sau douyin upload-video` 确认可用
- [ ] 记录安装踩坑点，更新 `docs/superpowers/plans/`

### Phase 1：自动分发（TODO）

- [ ] `monitor_videos` 表新增 `upload_status` / `upload_at` / `upload_error` 字段
- [ ] `monitor/uploader.py` 封装 sau CLI 调用（超时、重试、日志）
- [ ] `monitor/scheduler.py` 下载成功后触发 `_trigger_upload()`
- [ ] `monitor_server.py` 新增 `/api/uploads` 端点
- [ ] `monitor_web/index.html` 新增上传状态面板

### Phase 2：分发配置 UI（TODO）

- [ ] Web UI 配置各平台账号名称
- [ ] 标题模板 / 标签配置
- [ ] 开启/关闭各平台分发开关
- [ ] 手动触发上传（针对特定视频）

### Phase 3：高级功能（TODO）

- [ ] 定时发布（各平台 API 或 sau 定时参数）
- [ ] 视频预处理（ffmpeg 水印/转码）
- [ ] 上传重试机制（失败自动重试 N 次）
- [ ] 分发历史统计面板

---

## 8. 非功能性需求

| 维度 | 当前状态 | 目标 |
|------|----------|------|
| **稳定性** | 监控服务可长期后台运行 | 保持 |
| **可观测性** | 日志 + 飞书通知 | 上传状态也需可查 |
| **安全性** | Bearer Token、CORS、API Key 加密 | 保持 |
| **可维护性** | 单文件 2000+ 行（monitor_server.py）| 逐步拆分 |
| **测试覆盖** | 53+ 测试用例 | 保持，新增上传相关测试 |

---

## 9. 开放问题

| 问题 | 决策 | 备注 |
|------|------|------|
| Tkinter UI vs Web UI：哪套是未来？ | **Web UI** | Tkinter 版本功能冻结，后续更新集中在 Web UI |
| 多平台分发是否需要排队/限流？ | **需要** | 防止平台检测关联，同账号上传间隔 ≥ N 分钟 |
| 是否需要上传失败人工通知？ | **需要** | 支持飞书等通知平台（可选），复用现有通知基础设施 |
| PyInstaller 打包后 sau CLI 是否可用？ | **待验证** | 需先在本地安装 sau 进行 Phase 0 验证，再考虑打包集成方案 |
| 视频预处理（水印/字幕）优先级？ | P3 | 暂缓，先跑通核心分发链路 |

---

## 10. 参考文档

- [实现设计](./DESIGN.md) — Web UI 批量下载弹窗的详细设计
- [批量下载 Web UI 实现计划](./docs/superpowers/plans/2026-04-10-batch-download-webui-implementation.md)
- [批量下载 Web UI 设计规范](./docs/superpowers/specs/2026-04-10-batch-download-webui-design.md)
- [social-auto-upload](https://github.com/dreammis/social-auto-upload) — 分发引擎

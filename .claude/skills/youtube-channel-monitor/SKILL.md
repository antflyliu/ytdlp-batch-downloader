---
name: youtube-channel-monitor
description: |
  YouTube 频道监控工具。基于 YouTube Data API v3 定时扫描频道新视频，支持飞书/钉钉/企微 Webhook 通知。
  **仅限 YouTube**，不支持 X/Bilibili。
  触发场景：
  - 添加/管理 YouTube 频道监控账户
  - 启动/停止定时调度器
  - 查看扫描统计和事件记录
  - 配置飞书/钉钉/企微通知
  - 查询 API Quota 使用情况
  - 排查扫描异常
---

# youtube-channel-monitor

基于 YouTube Data API v3 的频道新视频监控系统，支持 SQLite 持久化 + 多平台 Webhook 通知。

## 统一 CLI 入口

```bash
# 脚本自动定位项目根目录，从任意目录调用均有效
python scripts/cli.py <subcommand> [options]
```

所有子命令支持 `--json` 输出结构化数据（供 AI agent 解析）。

## 子命令一览

| 子命令 | 说明 |
|--------|------|
| `list` | 列出所有监控账户 |
| `stats` | 显示账户统计（扫描次数/新视频/最后扫描） |
| `events --limit N` | 显示最近 N 条扫描事件 |
| `quota [--api-key ENV]` | 查询 API Quota 使用情况 |
| `monitor add ...` | 添加监控账户 |
| `monitor enable/disable ID` | 启用/禁用账户 |
| `monitor delete ID` | 删除账户 |
| `monitor start` | 启动定时调度器 |
| `monitor stop` | 停止调度器 |
| `monitor reload` | 重载任务（扫描新添加的账户） |
| `monitor once` | 立即执行一次扫描（不启动调度器） |

## 快速开始

### 1. 添加监控账户

```bash
# 基础用法
python scripts/cli.py monitor add "频道名" "@channelHandle" \
    --api-key-env YOUTUBE_Data_API_V3 \
    --scan-interval 5 \
    --notify-platform feishu

# 指定 Webhook URL（优先级高于全局配置）
python scripts/cli.py monitor add "综艺Show" "UCxxxx" \
    --webhook-url "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"

# 扫描模式：playlist（推荐，1 unit/请求）vs search（100 units，推荐用于精确匹配）
python scripts/cli.py monitor add "频道名" "@handle" \
    --fetch-mode playlist \
    --fetch-limit 5

# 禁用通知
python scripts/cli.py monitor add "静默频道" "@handle" \
    --no-notify

# 添加后立即启动调度器
python scripts/cli.py monitor add "新频道" "@handle" \
    --api-key-env YOUTUBE_Data_API_V3 \
    --start
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `name` | — | 显示名称（任意字符串） |
| `channel_url` | — | 频道 URL：`@handle` / `UCxxxx` / 完整 URL |
| `--api-key-env` | YOUTUBE_Data_API_V3 | API Key 环境变量名 |
| `--fetch-mode` | playlist | 获取模式：`playlist`（推荐）或 `search` |
| `--fetch-limit` | 5 | 每次获取视频条数 |
| `--scan-interval` | 5 | 扫描间隔（分钟） |
| `--notify-platform` | feishu | 通知平台：`feishu` / `dingtalk` / `wecom` |
| `--webhook-url` | — | 账户专属 Webhook URL（覆盖全局配置） |
| `--feishu-mode` | card_json | 飞书发送方式：`card_json` 或 `template` |
| `--no-notify` | False | 禁用通知 |

### 2. 管理调度器

```bash
# 启动定时调度器（Ctrl+C 退出）
python scripts/cli.py monitor start

# 停止调度器
python scripts/cli.py monitor stop

# 重载任务（扫描新添加的账户，不影响运行中的任务）
python scripts/cli.py monitor reload

# 立即执行一次扫描（不启动调度器）
python scripts/cli.py monitor once
```

### 3. 查看状态

```bash
# 列出所有账户
python scripts/cli.py list --json

# 显示统计
python scripts/cli.py stats --json

# 显示最近事件
python scripts/cli.py events --limit 20 --json

# 查询 Quota
python scripts/cli.py quota --json
python scripts/cli.py quota --api-key YOUTUBE_Data_API_V3 --json
```

### 4. 管理账户

```bash
# 启用/禁用
python scripts/cli.py monitor enable 2
python scripts/cli.py monitor disable 3

# 删除
python scripts/cli.py monitor delete 4
```

## 数据库结构

数据库位于 `monitor/data/monitor.db`（SQLite WAL 模式）。

| 表 | 说明 |
|----|------|
| `monitor_accounts` | 监控账户配置 |
| `monitor_events` | 扫描事件记录 |
| `monitor_videos` | 发现的视频详情 |
| `monitor_notify_logs` | Webhook 发送记录 |
| `api_quota_usage` | API 调用配额追踪 |

### 关键字段速查

**monitor_accounts：**

| 字段 | 说明 |
|------|------|
| `channel_url` | `@handle` / `UCxxxx` / URL |
| `fetch_mode` | `playlist`（uploads playlist）或 `search` |
| `fetch_limit` | 每次获取视频数 |
| `scan_interval` | 扫描间隔（分钟） |
| `notify_platform` | `feishu` / `dingtalk` / `wecom` |
| `enabled` | 0=禁用 1=启用 |

**monitor_events：**

| 字段 | 说明 |
|------|------|
| `status` | `running` / `success` / `error` / `skipped` |
| `total_videos` | API 返回视频总数 |
| `new_videos` | 新增视频数（不在表中） |
| `duration_ms` | 扫描耗时 |

**monitor_videos：**

| 字段 | 说明 |
|------|------|
| `notify_status` | `pending` / `sent` / `failed` / `skipped` |
| `download_status` | `pending` / `downloaded` / `failed` |
| `download_path` | 本地文件路径 |

## 通知平台配置

### 飞书（默认）

两种模式：
- **card_json**（默认）：直接发送 JSON 卡片，无需模板配置
- **template**：需在飞书后台创建模板，获取 `template_id` 和 `scan_template_id`

全局 Webhook URL 配置在 `monitor/config.json`：
```json
{
  "global_feishu_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
  "quota_budget_per_day": 8000
}
```

### 钉钉 / 企业微信

```bash
python scripts/cli.py monitor add "频道" "@handle" \
    --notify-platform dingtalk \
    --webhook-url "https://oapi.dingtalk.com/robot/send?access_token=xxx"
```

## API Quota 说明

YouTube Data API v3 每日免费配额 **10,000 units**：
- `playlistItems.list`：1 unit/请求
- `search.list`：100 units/请求

**推荐配置：**
- 5 个频道，每 5 分钟扫描 → 每天约 1,440 次 `playlistItems.list`
- 配额消耗：约 1,440 units/天，远低于限额

**配额不足时：**
- `quota --json` 显示 `percent: 100`
- 调度器自动跳过扫描，记录 `blocked_scans`
- 可设置 Webhook 报警（见 `monitor/quota.py`）

## 故障排除

| 问题 | 排查步骤 |
|------|----------|
| 扫描报 403/quotaExceeded | 运行 `quota --json` 确认配额；增加扫描间隔 |
| 扫描报 404 accountNotFound | 检查 `channel_url` 是否正确（@handle vs UC ID） |
| 飞书通知失败 | 检查 `global_feishu_url` 是否有效；查看 `monitor_notify_logs` 表 |
| 调度器不执行 | 运行 `monitor once` 查看错误；检查 `--api-key-env` 环境变量是否设置 |
| 视频未入库 | 检查 `monitor_events.new_videos` 是否为 0；可能是 playlist 获取模式问题 |
| 代理问题 | API 请求走系统代理；下载走 `monitor/config.json` 中配置的代理 |

## 项目结构

```
monitor/
├── db.py              # SQLite CRUD（accounts/events/videos/notify_logs/quota）
├── scheduler.py        # APScheduler 定时调度
├── notifier.py         # 飞书/钉钉/企微通知
├── fetcher.py          # YouTube API v3 视频获取
├── quota.py            # API 配额追踪
├── cache.py            # 频道元信息缓存
├── config.json         # 全局配置（Webhook URL / Quota 预算）
└── schema.sql          # 数据库 schema
```

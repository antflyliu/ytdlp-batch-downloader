# 打包 exe 使用指南

## 概述

项目提供两个独立的 exe 文件，位于 `dist/` 目录：

| exe 文件 | 功能 |
|----------|------|
| `YouTube批量下载器.exe` | 图形界面，支持频道获取、数据库管理、批量下载 |
| `YouTubeMonitor.exe` | 频道监控 Web 服务，支持定时扫描、通知推送、Web 管理界面 |

两个 exe 互不依赖，可单独使用。

---

## 环境准备（新机器首次运行）

### 必须安装

| 软件 | 安装方式 | 验证方法 |
|------|----------|----------|
| **ffmpeg** | `winget install ffmpeg` 或 [官网下载](https://ffmpeg.org/download.html)，加入 PATH | 终端执行 `ffmpeg -version` |

### 可选安装

| 软件 | 必须 | 说明 |
|------|------|------|
| **aria2c** | 否 | 多连接加速。未安装时自动降级为 yt-dlp 内置分片，不影响下载 |
| **VC++ Redistributable** | 兜底 | 一般系统已有。缺失时安装 [x64 下载](https://aka.ms/vs/17/release/vc_redist.x64.exe) |

> 两个 exe 均已打包 Python 运行时和所有 Python 依赖，无需安装 Python 环境。

---

## 目录准备

首次使用前，在 exe 同级目录下创建以下文件夹：

```
dist/                          （exe 所在目录）
├── YouTube批量下载器.exe
├── YouTubeMonitor.exe
├── data/                      ← 创建此文件夹
│   └── monitor.db             （运行后自动生成）
├── videos/                    ← 创建此文件夹（下载输出目录）
└── logs/                      ← 创建此文件夹（日志输出目录）
```

---

## 使用 YouTube 批量下载器

### 启动

双击 `YouTube批量下载器.exe`，图形界面自动打开（无需浏览器）。

### 功能模块

#### 1. 获取频道视频

输入 YouTube 频道 URL（如 `@频道名` 或完整频道链接），设置「前 N 条」数量，点击「获取视频」。

- 数据可保存为 **SQLite**（推荐，支持后台补全上传日期）或 **CSV** 格式
- SQLite 格式存储后可继续在 GUI 中筛选、选择并下载

#### 2. 数据库浏览器

点击「打开」，选择 SQLite 数据库文件（由频道获取功能生成），可：

- 查看视频统计：总数、完整数据、待补全、待下载、已下载、下载失败
- **筛选**：标题搜索、日期范围、频道筛选、播放量下限、数据状态、下载状态
- **排序**：点击列标题按标题/日期/播放量/时长/状态排序
- **分页**：上一页/下一页导航
- **全选/反选**：勾选后批量操作
- **补全上传日期**：仅处理勾选的视频，后台运行
- **导出 CSV**：将勾选的视频导出
- **下载所选**：将勾选的视频加入下载列表

#### 3. 批量下载

- **URL 文件**：支持 Excel (`.xlsx`/`.xls`)、CSV、纯文本 (`.txt`)、SQLite 数据库
- **保存路径**：选择视频保存目录
- **字幕下载**：勾选后下载字幕文件，可指定语言（如 `zh-Hans,en,ja`）
- **Cookie**：填写浏览器导出的 Cookie 文件路径（支持 `.txt` 和 `.json` 格式）
- **代理**：单个代理地址或代理池文件（每行一个，自动轮换）
- 点击「开始下载」执行批量下载

### 打开监控 Web UI

界面右上角点击「打开监控 Web UI」，自动启动监控服务并打开浏览器管理界面。

---

## 使用 YouTubeMonitor（频道监控）

### 启动

双击 `YouTubeMonitor.exe`，自动打开浏览器访问 Web 管理界面（端口 5000）。

命令行参数：

```bash
$env:MONITOR_API_TOKEN="123456"       # 设置 auth token
YouTubeMonitor.exe --port 8080        # 指定端口
YouTubeMonitor.exe --no-browser       # 不自动打开浏览器
YouTubeMonitor.exe --force-restart    # 强制重启
```

### Web 管理界面功能

- **账户管理**：添加/编辑/删除监控账户，设置扫描间隔、获取条数、通知方式
- **API Key 管理**：添加/管理 YouTube Data API v3 Keys，查看每日配额使用情况
- **全局配置**：下载目录、cookies 路径、aria2 加速开关、Webhook URL、配额告警阈值等
- **调度器控制**：启动/停止定时扫描，查看最近扫描事件
- **配额统计**：查看各 API Key 今日已用配额、扫描次数、被阻止次数
- **手动扫描**：立即触发指定账户的扫描
- **历史任务**：查看历史批量下载任务，支持重新下载

### 无浏览器模式

```bash
# 仅启动调度器，无 Web 界面（常驻后台）
python -m monitor

# 单次扫描所有账户后退出
python -m monitor --once
```

---

## 配置说明

配置文件位于 `monitor/config.json`（首次运行后自动生成在 `data/` 目录）：

```json
{
  "default_scan_interval": 60,
  "default_fetch_limit": 5,
  "download_output_path": "videos",
  "enable_aria2": false,
  "global_feishu_url": "",
  "global_dingtalk_url": "",
  "quota_budget_per_day": 8000,
  "quota_alert_thresholds": [80, 90, 100]
}
```

| 配置项 | 说明 |
|--------|------|
| `download_output_path` | 下载视频保存路径 |
| `enable_aria2` | 是否启用 aria2c 多连接加速 |
| `global_feishu_url` | 飞书 Webhook 地址（全局通知） |
| `quota_budget_per_day` | 每个 API Key 每日配额上限 |
| `quota_alert_thresholds` | 配额告警阈值百分比 |

---

## 常见问题

### Q：运行 exe 报错缺少 DLL

安装 [VC++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe)。

### Q：下载视频没有声音或画面

确保 ffmpeg 已安装并在 PATH 中。终端执行 `ffmpeg -version` 验证。

### Q：下载速度慢

1. 安装 aria2c 并确保在 PATH 中（`aria2c --version` 验证）
2. 或在全局配置中开启「aria2 多连接加速」
3. 配置代理池，自动轮换代理

### Q：提示 API Quota 超限

- 检查 Web UI「API Keys」页面，查看各 Key 今日已用配额
- 降低扫描频率（增大扫描间隔）
- 申请更高配额：[Google Cloud Console](https://console.cloud.google.com/)
- 参考配额分配方案：`docs/quota-analysis.md`

### Q：监控服务端口被占用

启动时指定其他端口：

```bash
YouTubeMonitor.exe --port 8080
```

### Q：想要备份数据库

`data/monitor.db` 包含所有监控账户、视频记录和 API Key 配置。备份时注意：
- 数据库包含明文 API Key，请妥善保管
- 自动备份功能（`monitor/db.py`）会排除 `api_keys` 表中的敏感信息

---

## 快速参考

| 操作 | 操作方式 |
|------|----------|
| 批量下载视频 | 双击 `YouTube批量下载器.exe` → 准备 URL 文件 → 开始下载 |
| 监控频道 | 双击 `YouTubeMonitor.exe` → Web UI 添加账户 → 启动调度器 |
| 获取频道视频 | `YouTube批量下载器.exe` → 输入频道 URL → 获取视频 |
| 查看监控状态 | `YouTubeMonitor.exe` → 浏览器 Web UI |
| 手动触发扫描 | Web UI → 账户列表 → 点击「扫描」按钮 |

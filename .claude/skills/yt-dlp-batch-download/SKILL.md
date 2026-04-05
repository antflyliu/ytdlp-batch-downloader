---
name: yt-dlp-batch-download
description: |
  YouTube 批量视频下载工具。支持 yt-dlp 支持的所有网站批量下载。
  **当前仓库重点验证 YouTube**。X/Bilibili 需补充测试代码后再写入说明。
  触发场景：
  - 批量下载 YouTube 视频
  - 从 URL 文件批量下载视频
  - 使用代理下载视频
  - 下载失败排错
  - 检查依赖是否就绪 (yt-dlp / aria2c / ffmpeg)
  - 检测 URL 是否可下载
  - 批量下载并指定分辨率/字幕/并发参数
---

# yt-dlp-batch-download

基于 `yt-dlp` + `aria2c`（可选）的批量视频下载工具，支持 YouTube 等所有 yt-dlp 支持的网站。

## 统一 CLI 入口

```bash
# 脚本自动定位项目根目录，从任意目录调用均有效
python scripts/cli.py <subcommand> [options]
```

**子命令一览：**

| 子命令 | 说明 |
|--------|------|
| `deps` | 检查 yt-dlp / aria2c / ffmpeg 依赖是否就绪 |
| `check-url <URL>` | 检测单个 URL 是否可下载 |
| `download -i <input> -o <dir>` | 批量下载视频 |
| `monitor start/stop/once/list` | 启动/停止/单次执行/列出监控 |
| `stats` | 显示监控账户统计 |
| `events --limit N` | 显示最近 N 条扫描记录 |
| `list` | 列出所有监控账户 |

所有子命令支持 `--json` 输出结构化数据（供 AI agent 解析）。

## 快速开始

### 1. 检查依赖

```bash
python scripts/cli.py deps --json
```

返回示例：
```json
{
  "all_ok": false,
  "tools": [
    {"name": "yt-dlp", "available": true, "version": "2026.03.17"},
    {"name": "aria2c", "available": false, "note": "未找到 aria2c"},
    {"name": "ffmpeg", "available": true, "version": "2024-..."},
    {"name": "whisperx", "available": true, "version": "optional"}
  ]
}
```

**必需依赖**：yt-dlp、ffmpeg
**可选依赖**：aria2c（提供更快的多连接下载）、whisperx（ASR 字幕生成）

### 2. 检测 URL

```bash
python scripts/cli.py check-url "https://www.youtube.com/watch?v=VIDEO_ID" --json
```

返回视频标题、时长、作者等信息。

### 3. 批量下载

```bash
# 从文件读取 URL（.xlsx / .txt / .csv）
python scripts/cli.py download -i urls.xlsx -o ./videos -r 1080p

# 逗号分隔 URL
python scripts/cli.py download -i "url1,url2,url3" -o ./videos -r 720p

# 带代理
python scripts/cli.py download -i urls.txt -o ./videos -p http://127.0.0.1:7890

# 代理池（自动轮换）
python scripts/cli.py download -i urls.txt --proxy-file proxies.txt

# 不下载字幕
python scripts/cli.py download -i urls.txt --no-subs

# 不使用 aria2c（用 yt-dlp 内置分片）
python scripts/cli.py download -i urls.txt --no-aria2

# 从浏览器读取已登录 Cookie（绕过机器人检测）
python scripts/cli.py download -i urls.txt --cookies-from-browser chrome

# JSON 输出（供 AI agent 调用）
python scripts/cli.py download -i urls.txt --json
```

**关键参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-r` resolution | 1080p | 视频分辨率：720p / 1080p / 1440p |
| `--no-aria2` | False | 禁用 aria2c，改用 yt-dlp 内置分片下载 |
| `--concurrent-fragments` | 4 | yt-dlp 分片并发数（未用 aria2 时生效） |
| `--sub-lang` | zh-Hans,en | 字幕语言，逗号分隔 |
| `--no-subs` | False | 不下载字幕 |
| `--cookies-from-browser` | None | 从浏览器读取 cookie，绕过机器人检测 |
| `--cookies` | None | Cookie 文件路径（Netscape 格式） |
| `--whisper-model` | medium | WhisperX 模型：tiny / base / small / medium / large-v3 |
| `--whisper-device` | auto | WhisperX 设备：auto / cpu / cuda |

## YouTube 频道监控

```bash
# 列出监控账户
python scripts/cli.py list --json

# 查看统计
python scripts/cli.py stats --json

# 查看最近扫描事件
python scripts/cli.py events --limit 20 --json

# 添加监控账户
python scripts/cli.py monitor add "频道名" "@channelHandle" \
    --scan-interval 5 --notify-platform feishu

# 启动定时调度器
python scripts/cli.py monitor start

# 停止调度器
python scripts/cli.py monitor stop

# 立即执行一次扫描（不启动调度器）
python scripts/cli.py monitor once

# 启用/禁用账户
python scripts/cli.py monitor enable 2
python scripts/cli.py monitor disable 3

# 删除账户
python scripts/cli.py monitor delete 4
```

监控模块详情见 `monitor/` 目录，数据库位于 `monitor/data/monitor.db`。

## 故障排除

| 问题 | 排查步骤 |
|------|----------|
| 下载失败 429 | 配置代理或 `--cookies-from-browser` 绕过机器人检测 |
| aria2c 报错 | 运行 `python scripts/cli.py deps` 确认 aria2c 在 PATH 中 |
| 字幕下载失败 | 检查网络代理；确认 `--sub-lang` 参数正确 |
| URL 检测失败 | 运行 `python scripts/cli.py check-url <URL>` 查看具体错误 |
| 监控账户扫描异常 | 运行 `python scripts/cli.py events --limit 10` 查看错误信息 |

## 项目结构

```
ytdlp-batch-downloader/
├── Youtube_Downloader.py    # 批量下载核心函数
├── scripts/
│   └── cli.py              # 统一 CLI 入口（Skill 调用此脚本）
├── monitor/
│   ├── db.py               # SQLite CRUD
│   ├── scheduler.py         # APScheduler 定时调度
│   ├── notifier.py          # 飞书/钉钉/企微通知
│   ├── fetcher.py           # YouTube API 视频获取
│   ├── quota.py             # API 配额追踪
│   └── cache.py             # 频道元信息缓存
├── monitor_server.py        # Web UI (REST API + HTML)
└── monitor_ui.py            # Tkinter 管理界面
```

## 依赖

```
必需:
  yt-dlp>=2024.x
  pandas>=1.x
  openpyxl>=3.x
  tqdm>=4.x

可选:
  aria2c>=1.36              # 多连接加速下载
  ffmpeg                    # 视频合并
  whisperx                  # ASR 字幕生成
  APScheduler               # 定时任务
  requests                  # Webhook 通知
```

# YouTube 视频批量下载器

一款基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的 YouTube 工具集，包含：

1. **批量下载**：从 Excel / TXT 导入 URL，图形界面或命令行批量下载视频（可选 aria2 多连接加速）。
2. **频道监控**（可选）：多账户、定时扫描频道新视频、SQLite 持久化、YouTube Data API 配额统计，并支持飞书 / 钉钉 / 企业微信通知与 Web 管理界面。

---

## 目录

- [功能特性](#功能特性)
- [前置依赖](#前置依赖)
- [快速开始](#快速开始)
- [YouTube 频道监控](#youtube-频道监控)
- [使用说明（批量下载）](#使用说明批量下载)
- [打包指南](#打包指南保姆手册)
- [消息通知](#消息通知)
- [Claude Code / Agent Skill 集成](#claude-code--agent-skill-集成)
- [文件结构](#文件结构)
- [技术栈](#技术栈)
- [开发与测试](#开发与测试)

---

## 功能特性

### 批量下载

- 支持 Excel (`.xlsx`/`.xls`) 和纯文本 (`.txt`) 两种 URL 文件格式
- 自定义视频分辨率（720p / 1080p / 1440p）
- 自定义下载数量、HTTP 代理与代理池
- 可视化下载进度条（`ytdownload_ui.py`）
- **字幕**：Web UI 批量下载默认不下载字幕；开启「字幕」后，yt-dlp 使用 cookies 拉取官方字幕
- **WhisperX ASR**：仅在用户显式开启字幕且视频无官方字幕时，由流程触发 ASR 生成字幕
- **aria2**：CLI 默认使用 `aria2c` 外部下载器；可用 `--no-aria2` 改为 yt-dlp 内置分片，并用 `--concurrent-fragments` 调节并发

### 频道监控（`monitor/`）

- 多监控账户、可配置扫描间隔与每次获取条数
- **SQLite** 存储账户与视频记录；**APScheduler** 定时扫描
- **YouTube Data API** 调用与每日配额统计（`monitor/quota.py`）
- **通知**：飞书（含 JSON 2.0 卡片 / 模板）、钉钉、企业微信 Webhook
- **Web UI**：`monitor_server.py` + `monitor_web/`，支持后台下载任务、全局配置（含「启用 aria2」等）
- 可选阅读：[扫描后自动下载方案说明](docs/auto-download-on-scan-plan-v2.md)

---

## 前置依赖

### 必须安装

| 依赖 | 说明 |
|------|------|
| **Python 3.9+** | 运行环境 |
| **ffmpeg** | 合并与编码；见 [FFmpeg 安装指南](docs/ffmpeg安装指南.md) |
| **yt-dlp** | 下载引擎 |

安装 Python 依赖（版本以仓库内 `requirements.txt` 为准）：

```bash
pip install -r requirements.txt
```

当前 `requirements.txt` 主要包含：`yt-dlp`、`pandas`、`tqdm`、`google-api-python-client`、`APScheduler`、`requests`、`openpyxl`、`tenacity` 等（监控与批量下载共用）。

### 可选

| 依赖 | 说明 |
|------|------|
| **aria2c** | 多连接加速；未安装时 CLI 可用 `--no-aria2` |
| **whisperx** | 无官方字幕时的 ASR：`pip install whisperx`（体积较大，按需安装） |

### WhisperX 模型

默认 CLI 使用 `medium` 模型；首次使用会下载到 `~/.cache/huggingface/hub/`。

### aria2 安装（Windows）

本项目 `Youtube_Downloader.py` 默认通过 **aria2c** 作为外部下载器；请确保可在终端执行 `aria2c`（已加入 `PATH`）。

**方式一：winget（推荐）**

```powershell
winget install --id aria2.aria2 --source winget --accept-package-agreements --accept-source-agreements
```

新开终端后执行 `aria2c --version` 验证。

**方式二**：从 [aria2 Releases](https://github.com/aria2/aria2/releases) 下载，将含 `aria2c.exe` 的目录加入系统 `Path`。

**不使用 aria2 时**：`python Youtube_Downloader.py ... --no-aria2`，并可用 `--concurrent-fragments N` 调节内置分片并发。

#### aria2 与内置分片对比（CLI）

速度因网络、代理、YouTube 限流而异，建议同一 URL、同一网络做对照：一次默认 aria2，一次 `--no-aria2 --concurrent-fragments 16`（可按机器调低）。输出目录分开，避免断点续传干扰对比。

监控 Web UI：**全局配置** 中可开启「aria2 多连接加速」；开启后，调度器自动下载、接口触发的下载等路径会与 `Youtube_Downloader.build_aria2_opts()` 对齐（见 `monitor/config.json` 中 `enable_aria2`）。

---

## 快速开始

### 方式一：批量下载图形界面

```bash
pip install -r requirements.txt
python ytdownload_ui.py
```

主窗口内可打开 **监控 Web UI**（本地 HTTP，详见下文）。

### 方式二：CLI 命令行下载

```bash
# 单链接或列表文件（Excel/TXT）
python Youtube_Downloader.py -i "https://www.youtube.com/watch?v=xxx" -o videos

python Youtube_Downloader.py -i urls.xlsx -o videos -r 1080p -p http://127.0.0.1:7890

# 不下载字幕
python Youtube_Downloader.py -i urls.xlsx --no-subs

# 字幕语言（CLI 默认会尝试下载字幕，以代码与参数为准）
python Youtube_Downloader.py -i urls.xlsx --sub-lang "zh-Hans,en,ja"

# 关闭 aria2，仅内置分片
python Youtube_Downloader.py -i urls.xlsx -o videos --no-aria2 --concurrent-fragments 8
```

### 方式三：打包 exe

- 批量下载 GUI：按下文 [打包指南](#打包指南保姆手册) 使用 `YouTube批量下载器.spec` / 文档中的 PyInstaller 示例，生成 `dist/YouTube批量下载器.exe`。
- 仅监控服务：仓库提供 `YouTubeMonitor.spec`（入口为 `monitor_server.py`，需一并打包 `monitor/`、`monitor_web/` 等数据文件），用于独立运行监控 Web UI。

---

## YouTube 频道监控

### 运行方式（任选）

| 方式 | 命令 | 说明 |
|------|------|------|
| Web 服务（默认端口 5000） | `python monitor_server.py` | 浏览器访问控制台；可加 `--port`、`--no-browser` |
| 独立拉起 Web（端口 18999） | `python monitor_ui.py` | 无 Tk 时也可只开浏览器界面 |
| 无界面调度 | `python -m monitor` | 常驻调度；`--once` 单次跑完全部账户 |
| CLI 管理账户 | `python -m monitor --list` / `--add ...` | 详见 `monitor/__main__.py` 帮助 |

### 配置与数据

- 全局配置：`monitor/config.json`（飞书/钉钉/企业微信 Webhook、默认扫描参数、下载目录与 cookies 路径、`enable_aria2` 等）。**勿将含真实密钥的配置提交到公开仓库**；本地可复制示例后自行填写。
- 数据库：由 `monitor/db.py` 初始化，默认位于项目数据目录（见代码中的路径解析）。
- **YouTube Data API**：API Key 存储于 SQLite 数据库（`api_keys` 表），通过 Web UI「🔑 API Keys」按钮管理。自动迁移：若存在 `YOUTUBE_Data_API_V3` 等环境变量，首次启动时自动导入为数据库 Key（优先级：账户指定 → 系统默认 → 环境变量）。
- **REST API 认证**：除 `/api/status` 外，所有 `/api/*` 端点均需携带 `Authorization: Bearer <token>` 请求头。Token 在首次启动时自动生成并存储于 `app_state` 表；可通过环境变量 `MONITOR_API_TOKEN` 自定义。

### REST API 端点

所有端点（除 `/api/status`）均需 `Authorization: Bearer <token>` header。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 健康检查（无需认证） |
| GET | `/api/accounts` | 列出所有监控账户 |
| POST | `/api/accounts` | 新增/编辑账户 |
| DELETE | `/api/accounts/{id}` | 删除账户 |
| POST | `/api/accounts/scan` | 手动触发扫描 |
| GET | `/api/accounts/{id}/videos` | 分页查询视频（含搜索/排序） |
| GET | `/api/api-keys` | 列出所有 API Key（key_value 已掩码） |
| POST | `/api/api-keys` | 新增 API Key |
| POST | `/api/api-keys/{id}` | 更新 API Key |
| DELETE | `/api/api-keys/{id}` | 删除 API Key |
| GET | `/api/api-keys/{id}` | 获取单个 Key 详情 |
| GET | `/api/token` | 获取当前 Bearer token |
| GET | `/api/config` | 获取全局配置 |
| POST | `/api/config` | 保存全局配置 |
| GET | `/api/quota` | 今日 API 配额使用情况 |
| GET | `/api/events` | 最近扫描事件 |
| GET | `/api/stats` | 账户统计 |
| POST | `/api/scheduler/start` | 启动调度器 |
| POST | `/api/scheduler/stop` | 停止调度器 |
| GET | `/api/download-tasks/{id}` | 下载任务进度 |

调用示例：
```bash
# 获取当前 token
curl http://127.0.0.1:5000/api/token

# 列出 API Keys（需认证）
curl -H "Authorization: Bearer <token>" http://127.0.0.1:5000/api/api-keys
```

### 与批量下载的关系

监控模块在需要拉取视频流时复用 `Youtube_Downloader.batch_download` 与 `build_aria2_opts()`，保证 CLI、监控后台、Web 触发的下载行为一致。

---

## 使用说明（批量下载）

### 1. 准备 URL 文件

**Excel**：需包含名为 `url` 的列。  
**TXT**：每行一条链接。

详见 [视频链接使用说明](docs/视频链接使用说明.md)。

### 2. 在 GUI 中操作

选择格式与文件、保存路径、分辨率与数量（留空表示不限制条数），必要时填写代理并保存，点击「开始下载」。

---

## 打包指南（保姆手册）

### 前置条件

```bash
python --version
pip --version
```

### 创建虚拟环境与安装依赖

```bash
cd ytdlp-batch-downloader
python -m venv venv_build
venv_build\Scripts\activate   # Windows
pip install -r requirements.txt
pip install pyinstaller
```

### 打包批量下载 GUI（示例）

```bash
python -m PyInstaller --onefile --noconsole --name "YouTube批量下载器" --add-data "docs;docs" --clean ytdownload_ui.py
```

输出一般在 `dist/YouTube批量下载器.exe`。目标机器仍需安装 **ffmpeg**。

### 打包监控程序

使用根目录 `YouTubeMonitor.spec`：

```bash
pyinstaller YouTubeMonitor.spec
```

具体 `datas`、`hiddenimports` 以 spec 文件为准。

### 常见问题

- **缺少 dll**：安装 Visual C++ Redistributable。
- **exe 过大**：勿用装满 torch/sklearn 的全局环境打包，应用干净虚拟环境。
- **`docs` 未打进包**：Windows 下 `--add-data "docs;docs"` 使用分号。

---

## 消息通知

### 飞书

- 机器人 Webhook（开放平台）：在飞书群中添加自定义机器人，复制 Webhook 地址填入 `monitor/config.json` 或账户级配置。
- 官方文档：[自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)（以飞书当前文档为准）。

发送方式支持 **Markdown 卡片（JSON 2.0）** 与 **模板卡片**；桌面端 `monitor_ui` 账户对话框中可选择模式并保存模板 ID。

---

## 文件结构

```
ytdlp-batch-downloader/
├── ytdownload_ui.py           # 批量下载 GUI 入口
├── Youtube_Downloader.py      # 下载核心（含 build_aria2_opts、batch_download）
├── ytb_api.py                 # YouTube Data API 辅助（监控等使用）
├── requirements.txt
├── proxy_config.json          # 代理配置（运行时可生成）
├── scripts/
│   └── cli.py                # 统一 CLI 入口（Skill 调用此脚本）
├── monitor/                   # 频道监控包
│   ├── __main__.py            # python -m monitor CLI
│   ├── db.py / scheduler.py / notifier.py / quota.py / …
│   ├── config.json            # 全局监控配置（本地敏感信息勿泄露）
│   └── schema.sql
├── monitor_server.py          # 监控 Web HTTP API + 静态页面
├── monitor_web/               # 监控前端（index.html 等）
├── monitor_ui.py              # 监控 Tk 页面或独立 Web 启动器
├── .claude/skills/            # Claude Code Skill 定义
│   ├── yt-dlp-batch-download/SKILL.md
│   └── youtube-channel-monitor/SKILL.md
├── mcp-server/                # OpenClaw MCP Server
│   ├── server.py
│   └── openclaw-config.json
├── tests/                     # pytest 用例
├── docs/                      # 使用说明与方案文档
├── schema.sql                 # 根目录 SQL（若与 monitor 并存以实际为准）
└── dist/                      # 打包输出（本地生成）
```

---

## 技术栈

| 领域 | 技术 |
|------|------|
| 批量 GUI | tkinter |
| 下载 | yt-dlp、可选 aria2c、ffmpeg |
| 监控服务 | 标准库 `http.server`、SQLite、APScheduler |
| API | Google YouTube Data API v3（`google-api-python-client`） |
| 通知 | requests → 飞书 / 钉钉 / 企业微信 Webhook |
| 表格 | pandas、openpyxl |
| 字幕 ASR（可选） | WhisperX |

---

## 开发与测试

```bash
pip install -r requirements.txt
# 按需: pip install pytest
python -m pytest tests/ -q
```

部分测试依赖环境变量或网络/API，失败时请查看具体用例说明。

---

## Claude Code / Agent Skill 集成

本项目提供两个 Claude Code Skill，支持在 Claude Code、Codex、OpenClaw 等 Agent 平台中直接调用。

### 目录结构（新增）

```
ytdlp-batch-downloader/
├── scripts/
│   └── cli.py              # 统一 CLI 入口（Skill 调用此脚本）
├── .claude/skills/
│   ├── yt-dlp-batch-download/SKILL.md       # 批量下载 Skill
│   └── youtube-channel-monitor/SKILL.md     # 频道监控 Skill
└── mcp-server/
    ├── server.py            # OpenClaw MCP Server（零依赖 stdio）
    └── openclaw-config.json # OpenClaw MCP 配置示例
```

### Skill 触发词

| Skill | 触发方式 |
|-------|--------|
| `@yt-dlp-batch-download` | 批量下载相关任务 |
| `@youtube-channel-monitor` | 频道监控相关任务 |

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/antflyliu/ytdlp-batch-downloader.git
cd ytdlp-batch-downloader
```

#### 2. 创建软链接

Skill 文件位于项目内 `.claude/skills/` 目录，需创建软链接到 Claude Code 的 skill 目录：

**Windows：**

```powershell
# 管理员权限打开 PowerShell
mklink /D "$env:USERPROFILE%\.claude\skills\yt-dlp-batch-download" "%CD%\.claude\skills\yt-dlp-batch-download"
mklink /D "$env:USERPROFILE%\.claude\skills\youtube-channel-monitor" "%CD%\.claude\skills\youtube-channel-monitor"


mklink /J "C:\Users\Administrator\.claude\skills\youtube-channel-monitor" ".claude\skills\youtube-channel-monitor"


```

**macOS / Linux：**

```bash
ln -s "$(pwd)/.claude/skills/yt-dlp-batch-download" ~/.claude/skills/
ln -s "$(pwd)/.claude/skills/youtube-channel-monitor" ~/.claude/skills/
```

#### 3. 重启 Claude Code

Claude Code 启动时自动扫描 `~/.claude/skills/` 下的所有 `SKILL.md` 并注册。重启后即可使用触发词。

### 验证

在 Claude Code 中输入：

```
@ytdlp-batch-download  批量下载几个 YouTube 视频
@youtube-channel-monitor 查看当前监控账户状态
```

### CLI 子命令一览

Skill 内部调用 `scripts/cli.py`，所有子命令支持 `--json` 输出供 AI 解析：

| 子命令 | 说明 |
|--------|------|
| `deps` | 检查 yt-dlp / aria2c / ffmpeg 依赖 |
| `check-url <URL>` | 检测 URL 可下载性 |
| `download -i <input> -o <dir>` | 批量下载视频 |
| `monitor start/stop/once/list` | 启动/停止/单次/列出监控 |
| `stats` | 监控账户统计 |
| `events --limit N` | 最近扫描事件 |
| `list` | 账户列表 |
| `quota [--api-key ENV]` | API Quota 查询 |

### OpenClaw MCP Server（可选）

如需在 OpenClaw 中使用，将 `mcp-server/openclaw-config.json` 内容合并到 OpenClaw 配置文件中：

```json
{
  "mcpServers": {
    "ytdlp-downloader": {
      "command": "python",
      "args": ["mcp-server/server.py"],
      "cwd": "<项目根目录>",
      "transportType": "stdio"
    }
  }
}
```

---

## 许可证与声明

请遵守 YouTube 服务条款及当地法律法规；本工具仅供个人学习与合法用途。仓库内示例配置、Webhook 占位符请勿直接用于生产而不经审查。

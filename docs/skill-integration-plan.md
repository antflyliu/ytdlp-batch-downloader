# Skill 封装实施计划

> 基于 Codex GPT-5.4 + Sonnet 分析，2026-04-05

## 背景

当前项目 `ytdlp-batch-downloader` 存在一个 Claude Code Skill（`.claude/skills/ytdlp-batch-downloader/SKILL.md`），但已严重过时：
- 描述的是旧架构（`scripts/yt_channel_fetch.py` 等已不存在）
- 缺少 monitor/ 模块、APScheduler、Web UI 等核心功能
- X/Bilibili 多平台描述不准确（缺乏实际验证代码）

## 决策

- **两 Skill 方案**：拆分为 `yt-dlp-batch-download` + `youtube-channel-monitor`
- **三平台兼容**：Claude Code + Codex + OpenClaw（Phase 1 只做 Claude Code）
- **统一 CLI 入口**：`scripts/cli.py` 整合所有子命令
- **保守描述**：明确写"YouTube 已验证" + "支持 yt-dlp 所有支持网站"

## 阶段一：yt-dlp-batch-download Skill（Phase 1）

### 1.1 统一 CLI 包装器

**文件**：`scripts/cli.py`

```bash
python scripts/cli.py deps                # 检查 yt-dlp/aria2c/ffmpeg 依赖
python scripts/cli.py check-url "URL"     # 检测 URL 是否可下载
python scripts/cli.py download -i urls.txt -o ./videos/ -r 1080p  # 批量下载
python scripts/cli.py monitor start       # 启动定时监控
python scripts/cli.py monitor stop        # 停止监控
python scripts/cli.py monitor once        # 立即执行一次扫描
python scripts/cli.py stats               # 查看统计
```

- argparse 统一入口，不重复 `Youtube_Downloader.py` 和 `monitor/__main__.py` 的逻辑
- `deps` 子命令输出结构化状态（`--json` 输出 JSON 格式供 AI 判断）

### 1.2 Skill 定义

**目录**：
```
.claude/skills/yt-dlp-batch-download/
├── SKILL.md          # Skill 定义（触发场景 + 用法 + 示例）
└── scripts/          # 薄脚本入口（引用项目源码路径）
```

**触发关键词**（`description` 字段）：
- 批量下载 YouTube/X/Bilibili 视频
- 从 URL 文件批量下载
- 使用代理下载
- 下载失败排错
- aria2c 多线程加速

**Skill 内容维度**：
- 依赖检查（`deps` 子命令）
- URL 验证（`check-url` 子命令）
- 批量下载用法（`download` 子命令）
- 常见报错排查
- Cookie / 代理配置

### 1.3 Skill 描述（保守写法）

> 支持 yt-dlp 支持的网站批量下载。**当前仓库重点验证 YouTube**。X/Bilibili 需补充测试代码后再写入说明。

## 阶段二：youtube-channel-monitor Skill（Phase 2）

- `monitor` / `stats` 子命令用法
- SQLite schema 说明
- 飞书/钉钉/企微通知配置
- Quota 配额管理
- APScheduler 定时任务排错

## 三平台兼容性

| 平台 | Phase 1 | Phase 2 |
|---|---|---|
| Claude Code | ✅ `.claude/skills/` | ✅ |
| Codex | ✅ 同一 SKILL.md | ✅ |
| OpenClaw | 🔜 MCP 封装 | 🔜 |

## 阶段三：OpenClaw MCP Server（Phase 3）✅

### 3.1 MCP Server 实现

**文件**：`mcp-server/server.py`（~280行，零依赖，纯 stdio 实现）

- 8 个工具：`deps`、`check_url`、`download`、`monitor`、`stats`、`events`、`list_accounts`、`quota`
- 每个工具调用 `scripts/cli.py --json`，解析输出为 `structuredContent`
- MCP 协议：JSON-RPC 2.0 over stdin/stdout
- 初始化 → `tools/list` → `tools/call` 标准流程

### 3.2 OpenClaw 配置

**文件**：`mcp-server/openclaw-config.json`

```json
{
  "mcpServers": {
    "ytdlp-downloader": {
      "command": "python",
      "args": ["mcp-server/server.py"],
      "cwd": "D:\\WORKSPACE\\video-download-space\\ytdlp-batch-downloader",
      "transportType": "stdio"
    }
  }
}
```

### 3.3 使用方式

1. 将 `openclaw-config.json` 内容合并到 OpenClaw 全局配置
2. MCP Server 自动发现 8 个工具
3. Agent 可直接调用：`tools/call { name: "deps" }`、`tools/call { name: "quota", arguments: { api_key_env: "YOUTUBE_Data_API_V3" } }`

### 3.4 容器环境注意

- **存储问题**：视频下载到容器内，重启丢失 → 建议配置 `download.output_dir` 映射到持久卷
- **环境变量**：API Key / Webhook URL 通过 OpenClaw 环境变量注入
- **超时控制**：download 工具超时 7200s，其他工具 15-60s

## 三平台兼容性

| 平台 | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Claude Code | ✅ `.claude/skills/` | ✅ | — |
| Codex | ✅ 同一 SKILL.md | ✅ | — |
| OpenClaw | ✅ MCP Server | ✅ MCP Server | ✅ |

## 预期成本

- Phase 1（下载 Skill）：✅ 完成
- Phase 2（监控 Skill）：✅ 完成
- Phase 3（OpenClaw MCP）：✅ 完成（~1小时）

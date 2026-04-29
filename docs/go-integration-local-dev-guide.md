# Go 代理集成本地开发指南

> 本文档说明如何基于本地源码 `D:\WORKSPACE\video-download-space\res-downloader` 进行开发、编译和集成。

---

## 一、源码目录

```
D:\WORKSPACE\video-download-space\
├── res-downloader/          # Go 源码（独立管理，不纳入 Python 项目仓库）
│   ├── main.go
│   ├── go.mod
│   ├── core/
│   │   ├── proxy.go         # MitM 代理
│   │   ├── http.go          # HTTP 服务器
│   │   ├── resource.go      # 资源嗅探
│   │   ├── downloader.go    # 分块下载
│   │   ├── rule.go          # 规则引擎
│   │   ├── config.go        # 配置存储
│   │   └── plugins/         # 插件系统
│   └── build/               # Wails 构建脚本（独立后不再使用）
│
└── ytdlp-batch-downloader/  # Python 项目
    ├── go_proxy_manager.py  # 子进程管理器（待创建）
    └── docs/
        └── go-integration-feasibility-report.md
```

---

## 二、Go 源码修改工作流

### 2.1 推荐的开发顺序

1. **在 `res-downloader/` 中修改 Go 源码**
2. **编译为 `res-downloader.exe`**
3. **在 `ytdlp-batch-downloader/` 中通过 Python 测试调用**
4. **验证通过后，回到步骤 1 继续迭代**

### 2.2 编译命令

```bash
cd D:\WORKSPACE\video-download-space\res-downloader

# Windows
go build -ldflags="-s -w" -o res-downloader.exe .

# 编译产物路径（相对于 res-downloader 目录）
# D:\WORKSPACE\video-download-space\res-downloader\res-downloader.exe
```

### 2.3 编译产物位置约定

| 平台 | 产物路径 | 说明 |
|------|----------|------|
| Windows | `res-downloader/res-downloader.exe` | 直接运行 |
| macOS | `res-downloader/res-downloader_darwin_amd64` | 需 `chmod +x` |
| Linux | `res-downloader/res-downloader_linux_amd64` | 需 `chmod +x` |

Python 侧 `GoProxyManager` 启动时会通过相对路径或环境变量指定可执行文件位置。

---

## 三、Phase 0 改造任务清单

> 目标: 将 `res-downloader` 从 Wails 应用改造为纯后端服务。

### 3.1 需要修改的 Go 文件

| 文件 | 修改内容 | 预计改动量 |
|------|----------|:---------:|
| `core/app.go` | 删除 `wailsapp/runtime` 引用；删除 `EventsEmit` 调用 | ~30 行 |
| `core/http.go` | 增加 `/health` 健康检查端点；增加 `/ws` WebSocket 端点 | ~60 行 |
| `go.mod` | 删除 `wailsapp/wails/v2`；新增 `gorilla/websocket` | ~5 行 |

### 3.2 改造后的 API 端点

```
GET  /health              # 健康检查（用于 Python 侧启动探测）
GET  /ws                 # WebSocket 连接（推送 proxy_event、download_progress）
GET  /api/resources      # 获取已嗅探到的资源列表
POST /api/download       # 触发下载任务
GET  /api/config         # 获取配置（端口、规则等）
POST /api/config         # 更新配置
```

### 3.3 WebSocket 事件格式

```json
// resource_found 事件
{"event": "resource_found", "data": {"url": "https://...mp4", "mime": "video/mp4", "host": "v.example.com", "size": 123456}}

// download_progress 事件
{"event": "download_progress", "data": {"id": "xxx", "progress": 45, "speed": "2.5MB/s"}}

// proxy_started / proxy_stopped 事件
{"event": "proxy_started", "data": {"port": 8899}}
```

---

## 四、Python 侧集成任务清单

| 任务 | 优先级 | 预计工作量 |
|------|:------:|:---------:|
| 创建 `go_proxy_manager.py` 子进程管理器 | P0 | 0.5 人天 |
| 在 `monitor_ui.py` 中集成 GoProxyManager 生命周期 | P0 | 0.25 人天 |
| 在 `server/__main__.py` 添加 `/api/proxy/*` 路由 | P1 | 0.25 人天 |
| Web UI 对接代理嗅探面板 | P1 | 0.5 人天 |
| 证书安装引导 UI | P2 | 0.25 人天 |

---

## 五、关键设计决策

### 5.1 进程生命周期管理

- Go 子进程由 Python 主进程（`monitor_ui.py`）管理
- 启动顺序: Python 主进程 → Go 子进程 → Flask 服务器
- 退出顺序: Go 子进程 → Flask 服务器 → Python 主进程

### 5.2 通信协议

- **Python → Go**: HTTP REST API（同步调用，如启动代理、触发下载）
- **Go → Python**: WebSocket（异步事件，如嗅探到资源、下载进度）

### 5.3 端口约定

| 端口 | 用途 | 说明 |
|------|------|------|
| 8898 | Go HTTP API | Go 子进程监听 |
| 8899 | MitM 代理端口 | 浏览器/系统代理指向此端口 |
| 5000 | Flask Web UI | Python 项目已有端口 |

Python 侧 Flask 服务通过 `/api/proxy/*` 转发到 Go API（`http://127.0.0.1:8898`）。

---

## 六、测试验证

### 6.1 MVP 验证步骤

```bash
# 1. 编译 Go
cd D:\WORKSPACE\video-download-space\res-downloader
go build -ldflags="-s -w" -o res-downloader.exe .

# 2. 运行 MVP 测试（见可行性报告第七章）
# python mvp_test.py

# 3. 手动浏览器代理测试
# - 浏览器配置 HTTP 代理: 127.0.0.1:8899
# - 访问一个视频页面
# - 检查 /api/resources 是否返回了媒体 URL
```

### 6.2 验收标准

- Go 子进程 `/health` 返回 200
- 浏览器配置代理后能嗅探到至少 1 个媒体资源 URL
- Python 能通过 WebSocket 接收并处理 `resource_found` 事件

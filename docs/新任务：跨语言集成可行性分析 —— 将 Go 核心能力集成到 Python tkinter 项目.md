# 新任务：跨语言集成可行性分析 —— 将 Go 核心能力集成到 Python tkinter 项目

## 背景说明

当前的 Python GUI 项目（tkinter 外壳 + HTML 页面）ytdlp-batch-downloader，现在需要将以下 Go 项目的核心能力集成进来：
- 目标项目：https://github.com/putyy/res-downloader
- 该项目用 Go 实现了本地代理服务器（MitM）、流量嗅探、资源提取（视频/音频等）、分块下载、AES 解密等能力
- Go 项目核心模块：core/proxy.go、core/http.go、core/resource.go、core/downloader.go、core/rule.go、core/plugins/

## 我的 Python 项目现状

请先阅读我项目根目录下的所有 Python 源码文件，理解：
1. 项目的整体架构（入口文件、模块划分）
2. tkinter 主窗口的生命周期管理方式
3. HTML 页面是如何嵌入到 tkinter 中的（WebView 组件？CEF？还是其他方案）
4. 项目当前的依赖管理文件（requirements.txt / pyproject.toml）
5. 有无已使用的网络/代理相关库

## res-downloader 项目现状分析（需要你主动读取源码）

请访问并阅读 https://github.com/putyy/res-downloader 的以下文件，在分析各集成方案之前，先总结该项目的核心架构：

### 1. 整体架构梳理
请阅读 main.go 和 wails.json，回答：
- 该项目如何通过 Wails 框架将 Go 后端与前端 UI 绑定？
- 哪些部分属于 UI 层（可剥离），哪些属于纯后端逻辑（需要保留）？
- Go 模块的入口是什么，启动流程是怎样的？

### 2. 代理服务器层（core/proxy.go + core/http.go）
请阅读这两个文件，回答：
- 代理服务器采用什么协议和实现方式（HTTP/HTTPS MitM？透明代理？SOCKS5？）
- 如何处理 HTTPS 流量（证书生成、安装、CA 根证书管理）？
- 代理服务器的生命周期如何管理（启动端口、停止方式）？
- 是否有对系统代理设置的自动配置逻辑（system_windows.go / system_darwin.go / system_linux.go）？

### 3. 资源嗅探与规则层（core/resource.go + core/rule.go）
请阅读这两个文件，回答：
- 资源识别的核心逻辑是什么（URL 规则匹配？响应头分析？内容类型过滤？）？
- rule.go 中定义了哪些类型的规则，规则的数据结构是什么？
- 资源对象（Resource）包含哪些字段，如何传递给下载器？

### 4. 插件系统（core/plugins/ 目录）
请列出 plugins/ 下的所有文件，并分析：
- 插件机制是如何设计的（接口定义是什么）？
- 已实现了哪些平台的插件（微信、微博、B站等）？
- 各插件对特定平台做了哪些特殊处理（如加密解析、特殊请求头、Token 提取）？
- 插件与核心代理层是如何解耦的？

### 5. 下载器（core/downloader.go）
请阅读该文件，回答：
- 支持哪些下载模式（直接下载、分片下载、HLS/m3u8 流？）？
- 并发控制是如何实现的（goroutine pool？channel？）？
- 断点续传、重试机制是否存在？
- 下载进度如何回传给前端？

### 6. 数据存储与配置（core/config.go + core/storage.go）
请阅读这两个文件，回答：
- 配置信息存储在哪里（文件路径、格式）？
- 嗅探到的资源列表如何持久化（内存？SQLite？JSON 文件？）？
- 有哪些可配置项（代理端口、下载目录、过滤规则等）？

### 7. 外部依赖评估
请阅读 go.mod，列出主要的第三方依赖库，并评估：
- 哪些依赖在剥离 Wails 后仍然需要保留？
- 有无依赖是强绑定 Wails 运行时的，剥离时需要替换？
- 整体依赖树是否存在难以跨平台编译的 CGo 依赖？

### 8. 现状总结
基于以上分析，请用一段话概括：
- res-downloader 核心能力的边界在哪里（最小可复用的核心是什么）？
- 当前代码与 Wails UI 的耦合程度如何，剥离难度如何评估？
- 是否存在任何明显的"集成友好"或"集成障碍"的设计特征？

### 9. 构建与发布体系分析（build/ 目录）

请阅读 build/ 目录及其子目录，至少包括：
- build/README.md
- build/windows/
- build/linux/
- build/darwin/

请重点分析：

1. build 目录的职责边界
- 该目录只是安装包脚本与资源目录，还是包含了平台相关运行依赖处理逻辑？
- 哪些内容和 Wails 强绑定，哪些内容在“Go 后端独立进程化”之后仍然可复用？

2. Windows 构建链路
- 当前 Windows 打包是否依赖 Wails + NSIS？
- `-webview2 Embed` 的使用意味着什么？
- 如果未来只保留 Go 后端能力而不保留 Wails GUI，这部分构建流程是否可以大幅简化？
- 若最终与 Python 项目一起分发，Windows 下更适合“内嵌 Go 可执行文件 + PyInstaller”，还是保留独立安装器？

3. macOS 构建链路
- 当前是否通过 `wails build -platform darwin/universal` 产出通用二进制？
- DMG 的生成方式是什么？
- 如果只提取 Go 核心能力，是否还需要沿用 DMG 产物，还是改为普通二进制更合理？
- 证书、权限、代理、CA 安装在 macOS 上可能带来哪些额外集成限制？

4. Linux 构建链路
- 当前 Linux 是否同时支持本地编译、Docker 编译、Debian 包、AppImage？
- Dockerfile 的存在是否说明 Linux 构建依赖较重或环境敏感？
- WebKit 相关文件复制逻辑是否说明当前 Wails GUI 对 Linux 运行环境有额外依赖？
- 如果改成纯 Go 后端供 Python 调用，哪些 Linux 打包步骤可以删除？

5. 构建产物与集成影响
- 当前 build 流程最终产出的是什么：GUI 安装包、可执行程序、平台依赖包、图标资源？
- 如果我选择“Python 主程序 + Go 子进程”方案，哪些现有构建脚本可以直接复用，哪些应该废弃重写？
- 如果我选择“Go 编译为动态库”方案，现有 build 目录是否几乎无参考价值？

6. 结论
- 从 build 目录看，res-downloader 更适合被当作：
  A. 一个完整桌面应用拆分复用
  B. 一个可抽离的后台服务
  C. 一个适合源码级重写参考的项目
- 请结合 build 目录给出对最终集成策略的修正意见。

## 需要深入分析的核心问题

请逐一分析以下每个方案的技术可行性、实现难度、维护成本和风险，最终给出明确推荐：

### 方案 A：将 Go 核心编译为共享库（CGo → .so/.dll/.dylib），Python 通过 ctypes/cffi 调用

分析要点：
- res-downloader 的 core/ 代码是否具备编译为 C shared library 的条件（有无 CGo export 接口、goroutine/channel 使用情况）
- proxy.go 启动的是一个长期运行的 HTTP 代理服务，这种有状态的服务如何通过 C 接口暴露和管理生命周期
- Python ctypes/cffi 调用 Go 共享库的内存管理陷阱（Go GC 与 Python GC 的冲突）
- 跨平台编译的复杂度（Windows/macOS/Linux 各需要什么工具链）

### 方案 B：将 Go 程序编译为独立可执行文件，Python 通过 subprocess 管理其生命周期，通过 localhost HTTP/IPC 通信

分析要点：
- res-downloader 已有 HTTP Server（core/app.go），是否可以剥离 Wails UI 层，直接作为纯后端进程运行
- Python 侧用什么方式启动、监控、优雅退出这个子进程（subprocess.Popen、信号处理）
- 进程间通信设计：REST API vs Unix Socket vs Named Pipe，哪个更适合本场景
- 用 PyInstaller 打包时如何将 Go 可执行文件一并打包（--add-binary）
- 进程崩溃检测和自动重启机制

### 方案 C：用 Python 重新实现 Go 的核心逻辑（mitmproxy + 自研嗅探规则）

分析要点：
- 仔细阅读 core/proxy.go 和 core/http.go，评估 Python mitmproxy 库能否等效替代其 MitM 代理实现
- 仔细阅读 core/resource.go 和 core/rule.go，评估资源识别规则的复杂度，Python 重写的工作量
- 仔细阅读 core/downloader.go，评估下载逻辑（分块、并发、重试）用 Python aiohttp/httpx 重写的难度
- 仔细阅读 core/plugins/ 目录，分析各平台插件（微信、微博等）的特殊处理逻辑能否在 Python 中复现
- 性能对比：代理吞吐量、并发处理能力，Python GIL 是否是瓶颈

### 方案 D：混合方案（Subprocess + 部分 Python 重写）

基于前三个方案的分析，是否存在更优的组合策略？

## 分析输出要求

请按以下格式输出：

1. **各方案评分表**：从"实现难度/周期、稳定性、维护成本、跨平台支持、打包分发便捷性"五个维度，对每个方案打分（1-5分）

2. **最终推荐方案**：明确说明推荐哪个方案，以及理由

3. **推荐方案的实施路线图**：分阶段列出具体步骤，包括：
   - 需要安装的工具和依赖
   - 需要修改/新增的文件
   - 关键代码片段示例（接口定义、进程管理、通信协议等）
   - 预估工作量（以"人天"为单位）

4. **风险清单与规避建议**：列出实施过程中最可能踩到的 3-5 个坑，并给出规避方案

5. **最小可验证原型（MVP）设计**：描述一个最小的原型验证方案，让我能在 1 天内验证核心集成路径是否可行

## 注意事项

- 分析过程中请直接读取 res-downloader 的源码（已在 GitHub 上），不要基于假设
- 请特别关注 res-downloader 对系统证书（HTTPS MitM）的依赖，这是集成难度的关键因素
- 考虑到我的 Python 项目使用 tkinter，请评估在 tkinter 的主线程模型下，管理后台代理服务的线程安全问题
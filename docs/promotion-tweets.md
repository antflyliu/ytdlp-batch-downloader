# 推广推文

> 用于 Twitter/X 发布。两篇定位不同：短推 = 传播钩子 + 即刻行动；长推 = 技术深度 + 差异化背书。

---

## 短推文（~240 字符）

```
监控 10+ 个 YouTube 频道，新视频自动推送通知 → 自动下载 → 自动生成字幕。

代理熔断、API 配额保险模型、Web UI 管理一切。

Claude Code 说一句话就能触发下载。

github.com/antflyliu/ytdl...

RT = 免费帮我宣传 🙏
```

**字符数：~240（含链接和 RT 标注）**

**发布格式建议**：粘贴正文，附链接作为首条回复。

---

## 长推文 Thread（约 9 条）

**标题 Hook**：为什么我花 6 个月造了这个 YouTube 工具轮子

---

**Tweet 1（Hook）**

为什么我花了 6 个月造了一个 YouTube 工具轮子

因为市面上的工具：

- 监控要付费订阅
- 下载限速限格式
- API 配额靠猜，没有保险
- 没有字幕自动生成

我忍不了了，自己写了一个，全部开源

---

**Tweet 2（核心定位）**

ytdlp-batch-downloader

一个基于 yt-dlp 的 YouTube 全栈工具集，包含：

→ 批量下载（Excel/CSV/TXT/SQLite 多格式）
→ 频道监控（定时扫描 + 通知推送）
→ 频道视频获取（URL → SQLite/CSV）
→ Web 管理界面（一切可控）

GitHub: github.com/antflyliu/ytdl...

---

**Tweet 3（差异化：配额保险模型）**

最让我骄傲的功能：API 配额保险分配模型。

大多数工具的配额策略 = "祈祷别超"。

我的做法 = 数学模型。

playlist 模式：3 units/次
保险值（覆盖缓存失效+重试）：5 units/次
85% 上限：5 分钟扫描 ≤ 5 频道/Key

每增加一个频道，我知道确切的配额边界。

详见：docs/quota-analysis.md

---

**Tweet 4（差异化：代理熔断机制）**

代理失败？自动换下一个。

这个工具的代理池不是"轮询"，是"熔断"：

- 429 限流 → 换代理
- 超时 → 换代理
- SOCKS 错误 → 换代理
- 全部失败 → 直连兜底

零人工干预，全部自动。

---

**Tweet 5（差异化：WhisperX ASR）**

没有字幕的视频，我选择不下载。

WhisperX ASR 集成：
- 自动检测无字幕视频
- 调用 WhisperX 生成字幕（GPU/CPU 都支持）
- VTT → SRT 自动转换

youtube.com/watch?v=xxx → 视频 + 字幕文件

---

**Tweet 6（Claude Code Skill 集成）**

如果你用 Claude Code / OpenClaw，这个工具可以「说话触发」：

```
@ytdlp-batch-download 下载这几个频道的最新视频
@youtube-channel-monitor 查看当前配额使用情况
```

两个 Skill：
- @yt-dlp-batch-download
- @youtube-channel-monitor

---

**Tweet 7（技术栈透明）**

没有炫技，但每个组件都经过生产验证：

- yt-dlp 下载核心 + aria2 多连接
- SQLite 持久化（API Keys 加密存储）
- Bearer Token 认证 + 速率限制
- APScheduler 定时任务
- Web UI（tkinter + 纯 HTTP 服务）
- WhisperX ASR（可选，按需安装）

---

**Tweet 8（打包 exe，零依赖运行）**

不想装 Python 环境？

两个打包 exe，拿来即用：
- YouTube批量下载器.exe（GUI）
- YouTubeMonitor.exe（Web 服务）

仅需安装 ffmpeg，其余全部内置。

详见：docs/exe使用指南.md

---

**Tweet 9（CTA）**

花了 6 个月打磨，每一个功能都是实际需求驱动的。

如果你做 YouTube 频道研究、内容采集、或者只是想下载视频不被打扰：

★ Star 支持一下
github.com/antflyliu/ytdl...

有问题/建议，欢迎 Issue 和 PR。

by @DavisNc9527

---

## 发布建议

| 推文 | 格式 | 最佳发布时间 |
|------|------|------------|
| 短推 | 单条 + 链接作为回复 | 工作日 12:00-13:00 或 20:00-21:00 |
| 长推 | Thread，每条单独发 | 周末早晨或节假日（读者有时间刷 Thread）|

## 备选 Hook（短推）

如果想测试不同角度，可用以下 Hook 替换 Tweet 1：

**Hook A（痛点驱动）**：
```
每天手动搜 YouTube 新视频 → 通知 → 下载 → 找字幕。

我把这个流程自动化了，全部开源。
github.com/antflyliu/ytdl...
```

**Hook B（技术背书）**：
```
YouTube API 配额不够用？

我做了一套保险模型，数学保证不超限。
开源：github.com/antflyliu/ytdl...
```

**Hook C（简洁直接）**：
```
开源 YouTube 下载 + 监控工具，支持：
- 自动字幕（WhisperX）
- 代理池熔断
- Claude Code 语音触发

github.com/antflyliu/ytdl...
```

# YouTube 视频批量下载器

一款支持 Excel / TXT 文件导入的 YouTube 视频批量下载工具，提供可视化界面。

---

## 功能特性

- 支持 Excel (.xlsx/.xls) 和纯文本 (.txt) 两种 URL 文件格式
- 自定义视频分辨率（720p / 1080p / 1440p）
- 自定义下载数量
- 支持 HTTP 代理设置
- 可视化下载进度条
- 自动保存代理配置
- **字幕下载**：Web UI 批量下载默认不下载字幕；开启「字幕」开关后，yt-dlp 用 cookies 下载官方字幕
- **WhisperX ASR**：仅在用户显式开启字幕 + 无官方字幕时，由 yt-dlp 触发 ASR 生成

---

## 前置依赖

### 必须安装

| 依赖 | 说明 | 安装命令 |
|------|------|---------|
| **Python 3.9+** | Python 运行环境 | [官网下载](https://www.python.org/downloads/) |
| **ffmpeg** | 视频合并与编码核心 | 见下方 [ffmpeg 安装指南](docs/ffmpeg安装指南.md) |
| **yt-dlp** | YouTube 下载引擎 | `pip install yt-dlp` |
| **pandas** | 读取 Excel 文件 | `pip install pandas` |
| **tqdm** | 进度条显示 | `pip install tqdm` |

安装所有 Python 依赖：
```bash
pip install -r requirements.txt
```

### 可选

- **aria2c** — 多线程加速下载（CLI 默认启用，见下方 [aria2 安装（Windows）](#aria2-安装windows)）。未安装时可使用 `--no-aria2` 仅依赖 yt-dlp 内置分片。
- **whisperx** — 仅在用户显式开启字幕 + 无官方字幕时触发 ASR 生成字幕（需要 torch CPU 版，GPU 可加速）。Web UI 批量下载默认不下载字幕，WhisperX 不会被自动触发。
  ```bash
  pip install whisperx
  ```

### WhisperX 模型

WhisperX 默认使用 `medium` 模型，支持本地缓存：
- `faster-whisper-medium` ✅（本地已有）
- `faster-distil-whisper-large-v2` ✅（本地已有，可选更高质量）

首次使用 WhisperX 时会自动下载模型到 `~/.cache/huggingface/hub/`。

### aria2 安装（Windows）

本项目 `Youtube_Downloader.py` 默认通过 **aria2c** 作为外部下载器加速；请确保本机可执行 `aria2c`（已加入 PATH）。

**方式一：winget（推荐）**

在 PowerShell 或 CMD 中执行（可能需要管理员权限或 UAC 确认）：

```powershell
winget install --id aria2.aria2 --source winget --accept-package-agreements --accept-source-agreements
```

装完后**新开一个终端**，验证：

```powershell
aria2c --version
```

若能看到版本号（例如 `aria2 version 1.37.0`），即安装成功。

**方式二：手动安装**

1. 打开 [aria2 Releases](https://github.com/aria2/aria2/releases)，下载 Windows 压缩包并解压到任意目录。
2. 将该目录（内含 `aria2c.exe`）加入系统 **环境变量 → Path**。
3. 新开终端后执行 `aria2c --version` 验证。

**不使用 aria2 时**：运行 CLI 时加 `--no-aria2`，将仅使用 yt-dlp 内置分片并发（可用 `--concurrent-fragments` 调整）。

#### aria2 与内置分片对比测试（CLI）

速度差异因网络、代理、YouTube 限流而异，**以本机实测为准**。建议用**同一 URL、同一网络与代理**做两次下载对比总耗时：

1. **清空或换目录**：两次测试使用**不同输出目录**（例如 `-o test_aria2` 与 `-o test_native`），避免断点续传与已合并文件干扰观感。
2. **方案 A（默认 aria2）**：不加 `--no-aria2`，例如：
   ```bash
   python Youtube_Downloader.py -i "https://www.youtube.com/watch?v=VIDEO_ID" -o test_aria2 --no-subs
   ```
3. **方案 B（仅 yt-dlp 分片）**：关闭 aria2，并适当提高内置分片数以便对比公平，例如：
   ```bash
   python Youtube_Downloader.py -i "https://www.youtube.com/watch?v=VIDEO_ID" -o test_native --no-aria2 --concurrent-fragments 16 --no-subs
   ```
4. **记录**：各跑 1～2 次，用系统时钟或日志时间戳看**从开始到「下载完成」**的墙钟时间；若出现 429、频繁重试，说明并发过高，可把 `--concurrent-fragments` 或 aria2 连接相关参数调低再测。

说明：监控 Web UI（⚙ 全局配置 → 启用 aria2 多连接加速）支持一键开启 aria2 加速，开启后「启动监控」自动下载、「立即扫描」自动下载、视频详情「下载选中」三条路径均走 aria2c 16 连接并发。CLI `Youtube_Downloader.py` 默认启用 aria2，加 `--no-aria2` 可关闭。

---

## 快速开始

### 方式一：直接运行源码

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python ytdownload_ui.py
```

### 方式二：CLI 命令行下载

```bash
# 基本用法
python Youtube_Downloader.py -i "https://www.youtube.com/watch?v=xxx" -o videos

# 从文件下载（Excel/TXT）
python Youtube_Downloader.py -i urls.xlsx -o videos

# 指定分辨率和代理
python Youtube_Downloader.py -i urls.xlsx -o videos -r 1080p -p http://127.0.0.1:7890

# 不下载字幕
python Youtube_Downloader.py -i urls.xlsx --no-subs

# 指定字幕语言（CLI 默认下载字幕；Web UI 批量下载默认不下载字幕）
python Youtube_Downloader.py -i urls.xlsx --sub-lang "zh-Hans,en,ja"

# 指定 WhisperX 模型和设备
python Youtube_Downloader.py -i urls.xlsx --whisper-model large-v3 --whisper-device cpu
```

### 方式三：运行打包好的 exe

```bash
# 双击 dist/YouTube批量下载器.exe 即可运行
```

---

## 使用说明

### 1. 准备 URL 文件

**Excel 格式** — 文件中需包含名为 `url` 的列：

| url |
|-----|
| https://www.youtube.com/watch?v=xxx |
| https://www.youtube.com/shorts/xxx |

**TXT 格式** — 每行一条链接：
```
https://www.youtube.com/watch?v=xxx
https://www.youtube.com/shorts/xxx
```

详细说明请查看 [视频链接使用说明](docs/视频链接使用说明.md)。

### 2. 填写下载设置

1. 选择文件格式（Excel / TXT）
2. 点击「浏览」选择 URL 文件
3. 确认保存路径（默认为 exe 所在目录下的 `videos` 文件夹）
4. （可选）填写代理地址并保存

### 3. 设置下载选项

- 选择视频分辨率（默认 1080p）
- 设置下载数量（留空则下载全部）

### 4. 开始下载

点击「开始下载」，进度条会实时显示下载进度。

---

## 打包指南（保姆手册）

### 前置条件

确保安装了 Python 3.9+ 和 pip：

```bash
python --version
pip --version
```

### Step 1：创建虚拟环境

```bash
cd ytdlp-batch-downloader
python -m venv venv_build
```

### Step 2：安装打包依赖

```bash
# 激活虚拟环境（Windows）
venv_build\Scripts\activate

# 安装项目依赖 + PyInstaller
pip install yt-dlp pandas tqdm pyinstaller
```

### Step 3：打包

```bash
# --onefile       打包成单个 exe 文件
# --noconsole     无控制台窗口（GUI 程序不需要）
# --name          输出 exe 的文件名
# --add-data      附加文档目录（docs 文件夹打包进去）
# --clean         清理之前的构建缓存

python -m PyInstaller --onefile --noconsole --name "YouTube批量下载器" --add-data "docs;docs" --clean ytdownload_ui.py
```

### Step 4：获取 exe

打包完成后，exe 文件位于：

```
dist/YouTube批量下载器.exe
```

整个 `dist` 目录即为可分发的绿色版软件，复制到任意 Windows 电脑即可运行（前提是目标电脑已安装 ffmpeg）。

### 常见问题

**Q: 打包后运行提示 dll 缺失？**
> 确保在打包的电脑上已经安装了 Visual C++ Redistributable。

**Q: exe 太大（超过 1GB）？**
> 原因：全局 Python 环境装了 sklearn/torch 等巨型库。解决：务必使用虚拟环境 `venv_build` 进行打包，不要用全局 Python。

**Q: docs 文件夹没有打包进去？**
> 确认 `--add-data "docs;docs"` 语法（Windows 用分号分隔）。如果文档打不开，检查 exe 运行目录下是否有 `docs` 文件夹。

**Q: 如何重新打包？**
> 先关闭正在运行的 exe，然后删除 `build` 和 `dist` 目录，重新执行 Step 3 即可。

---

## 消息通知

### 飞书

** webhook 文档： **
https://www.feishu.cn/hc/zh-CN/articles/807992406756-webhook-%E8%A7%A6%E5%8F%91%E5%99%A8


---

## 文件结构

```
ytdlp-batch-downloader/
├── ytdownload_ui.py          # GUI 主程序入口
├── Youtube_Downloader.py      # 下载核心逻辑
├── requirements.txt           # Python 依赖列表
├── proxy_config.json          # 代理配置（自动生成）
├── videos/                    # 默认下载目录
├── docs/
│   ├── ffmpeg安装指南.md      # FFmpeg 安装说明
│   └── 视频链接使用说明.md     # URL 文件格式说明
└── dist/
    └── YouTube批量下载器.exe   # 打包后的可执行文件
```

---

## 技术栈

- **GUI**: tkinter（Python 内置，无需额外安装）
- **下载引擎**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **外部下载器**: aria2c（可选）
- **视频处理**: ffmpeg
- **字幕生成**: [WhisperX](https://github.com/m-bain/whisperX)（用户显式开启字幕时触发 ASR 生成）


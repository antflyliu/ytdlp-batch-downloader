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
- **字幕下载**：yt-dlp 自动字幕优先、手动字幕降级
- **WhisperX ASR**：无字幕视频自动生成 SRT 字幕

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

- **aria2c** — 多线程加速下载。如需使用，请确保已安装并添加到 PATH。
- **whisperx** — 无字幕视频 ASR 生成字幕（自动启用）。需要 torch CPU 版，GPU 可加速。
  ```bash
  pip install whisperx
  ```

### WhisperX 模型

WhisperX 默认使用 `medium` 模型，支持本地缓存：
- `faster-whisper-medium` ✅（本地已有）
- `faster-distil-whisper-large-v2` ✅（本地已有，可选更高质量）

首次使用 WhisperX 时会自动下载模型到 `~/.cache/huggingface/hub/`。

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

# 指定字幕语言
python Youtube_Downloader.py -i urls.xlsx --sub-lang "zh-Hans,en,ja"

# 指定 WhisperX 模型和设备
python Youtube_Downloader.py -i urls.xlsx --whisper-model large-v3 --whisper-device cpu
```

### 方式二：运行打包好的 exe

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
- **字幕生成**: [WhisperX](https://github.com/m-bain/whisperX)（ASR 自动生成）

```

(venv_build) PS D:\WORKSPACE\video-download-space\ytdlp-batch-downloader> nvidia-smi
Tue Mar 31 13:08:08 2026
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 572.40                 Driver Version: 572.40         CUDA Version: 12.8     |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                  Driver-Model | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce MX150         WDDM  |   00000000:01:00.0 Off |                  N/A |
| N/A   56C    P5            N/A  / 5001W |     592MiB /   2048MiB |     29%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            6024    C+G   ...yb3d8bbwe\WindowsTerminal.exe      N/A      |
|    0   N/A  N/A            8904    C+G   ...e-2.7.1-Beta-x64\Snipaste.exe      N/A      |
|    0   N/A  N/A            9144    C+G   D:\INSTALLED\Typora\Typora.exe        N/A      |
|    0   N/A  N/A           12584    C+G   ...y\StartMenuExperienceHost.exe      N/A      |
|    0   N/A  N/A           13856    C+G   ....0.3856.84\msedgewebview2.exe      N/A      |
|    0   N/A  N/A           14376    C+G   ...5n1h2txyewy\TextInputHost.exe      N/A      |
|    0   N/A  N/A           14404    C+G   ....0.3856.84\msedgewebview2.exe      N/A      |
|    0   N/A  N/A           16368    C+G   ....0.3856.84\msedgewebview2.exe      N/A      |
|    0   N/A  N/A           18192    C+G   ...y\Comet\Application\comet.exe      N/A      |
|    0   N/A  N/A           21864    C+G   C:\Program Files\flomo\flomo.exe      N/A      |
|    0   N/A  N/A           23128    C+G   ..._cw5n1h2txyewy\SearchHost.exe      N/A      |
|    0   N/A  N/A           24056    C+G   ...App_cw5n1h2txyewy\LockApp.exe      N/A      |
|    0   N/A  N/A           28160    C+G   ...indows\System32\ShellHost.exe      N/A      |
+-----------------------------------------------------------------------------------------+


(venv_build) PS D:\WORKSPACE\video-download-space\ytdlp-batch-downloader> pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

```

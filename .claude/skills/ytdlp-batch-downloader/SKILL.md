---
name: ytdlp-batch-downloader
description: |
  ⚠️ 此 Skill 已过时。请使用 `@yt-dlp-batch-download` 获取最新版本。
  新版支持统一 CLI（`scripts/cli.py`）、YouTube 频道监控、APScheduler 定时任务。
  触发场景（兼容旧版）：
  - 批量下载 YouTube 视频
  - 从 URL 文件下载
  - 使用代理下载
---

# ytdlp-batch-downloader (Legacy)

> ⚠️ **已迁移至 `@yt-dlp-batch-download`**。此文件仅保留用于向后兼容。

请改用：
```bash
# 统一 CLI 入口
python scripts/cli.py deps
python scripts/cli.py download -i urls.txt -o ./videos
python scripts/cli.py check-url "URL"
```

详见 `scripts/cli.py --help` 或使用 `@yt-dlp-batch-download` Skill。

本项目是一个 YouTube 批量下载工具，支持从 Excel/TXT 文件读取 URL，使用 aria2c 多线程加速。

## 项目结构

```
ytdlp-batch-downloader/
├── Youtube_Downloader.py    # 主程序
├── videos.txt              # URL 列表（示例）
├── videos.xlsx             # Excel 格式 URL 列表
├── videos/                 # 下载目录
├── venv_build/             # Python 虚拟环境
└── docs/                   # 文档
```

## 核心功能

1. **多源输入**: 支持 `.xlsx` 和 `.txt` 格式的 URL 列表
2. **多线程下载**: 使用 aria2c 分 16 片并发下载
3. **分辨率选择**: 720p / 1080p / 1440p
4. **代理支持**: 可配置 HTTP/SOCKS 代理
5. **结果导出**: 下载完成后自动生成 Excel 报告

## 快速开始

### 方式一：直接运行主程序

```bash
cd D:\WORKSPACE\video-download-space\ytdlp-batch-downloader
python Youtube_Downloader.py
```

### 方式二：导入模块使用

```python
from Youtube_Downloader import batch_download, read_urls_from_file

# 读取 URL 列表
urls = read_urls_from_file("videos.xlsx")

# 执行下载
results = batch_download(
    urls=urls,
    output_path="videos/",
    resolution="1080p",
    proxy="http://127.0.0.1:7890"  # 可选
)
```

## 常用命令

| 任务 | 命令 |
|------|------|
| 检查 yt-dlp 版本 | `pip show yt-dlp` |
| 更新 yt-dlp | `pip install -U yt-dlp` |
| 检查 aria2c | `aria2c --version` |
| 查看视频信息 | `yt-dlp --dump-json "URL"` |

## URL 格式说明

支持的格式：
- 标准链接: `https://www.youtube.com/watch?v=VIDEO_ID`
- 短链接: `https://youtu.be/VIDEO_ID`
- Shorts: `https://youtube.com/shorts/VIDEO_ID`

Excel 文件要求：
- 包含 `URL` 列（不区分大小写）
- 第一行为表头

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| 下载失败 | 检查网络/代理设置 |
| aria2c 报错 | 确保已安装并添加到 PATH |
| 格式不支持 | 视频可能地区限制或已下架 |
| Excel 读取失败 | 确认有 `openpyxl` 库 |

## 依赖

```
yt-dlp>=2024.x
pandas>=1.x
openpyxl>=3.x
tqdm>=4.x
aria2c>=1.36
```

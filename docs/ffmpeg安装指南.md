# FFmpeg 安装指南

## 简介

FFmpeg 是 yt-dlp 下载视频时的**必需依赖**，用于音视频的合并、编码和格式转换。

---

## Windows 安装方式

### 方式一：通过包管理器（推荐）

#### Scoop（推荐）
```bash
# 安装 Scoop（如果尚未安装）
irm get.scoop.sh | iex

# 安装 ffmpeg
scoop install ffmpeg
```

#### Chocolatey
```bash
# 安装 Chocolatey（如果尚未安装）
Set-ExecutionPolicy Bypass -Scope Process -Force; `
  [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; `
  iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# 安装 ffmpeg
choco install ffmpeg
```

#### winget（Windows 11 内置）
```bash
winget install ffmpeg
```

### 方式二：手动下载（最简单）

1. 访问 FFmpeg 官网：https://ffmpeg.org/download.html
2. 点击 **Windows** → 选择 **gyan.dev** 或 **BtbN** 构建版本
3. 下载 `.zip` 压缩包（如 `ffmpeg-master-latest-win64-gpl.zip`）
4. 解压到任意目录（如 `C:\Tools\ffmpeg`）
5. 将 `bin` 目录添加到系统 PATH：
   - 右键 **此电脑** → **属性** → **高级系统设置** → **环境变量**
   - 在 **系统变量** 的 `Path` 中添加：`C:\Tools\ffmpeg\bin`
6. 打开命令提示符，输入 `ffmpeg -version` 验证安装

### 方式三：通过 Python 自动安装

如果不想手动配置，可以使用 `ffmpeg-python` 或通过 yt-dlp 的安装脚本。

---

## 验证安装

打开命令提示符（CMD）或 PowerShell，输入：

```bash
ffmpeg -version
```

如果显示类似以下内容，说明安装成功：

```
ffmpeg version 2024-... Copyright (c) 2000-2024 the FFmpeg developers
built with gcc 13.2.0 (x86_64)
```

---

## 常见问题

### Q: yt-dlp 提示找不到 ffmpeg？
**A**: 确保 ffmpeg 已添加到系统 PATH，并**重启命令提示符或程序**后生效。

### Q: 下载时提示 "ffmpeg/avprobe not found"？
**A**: 同上，环境变量未生效或路径配置错误。可通过 `where ffmpeg`（CMD）或 `Get-Command ffmpeg`（PowerShell）检查是否可找到。

### Q: Mac 或 Linux 如何安装？
**macOS**:
```bash
brew install ffmpeg
```

**Ubuntu/Debian**:
```bash
sudo apt update && sudo apt install ffmpeg
```

**CentOS/RHEL**:
```bash
sudo yum install epel-release
sudo yum install ffmpeg
```

---

## 版本要求

- FFmpeg **4.0+** 可满足基本需求
- 推荐使用 **最新稳定版**，以支持更多编码格式和修复已知问题

# 批量下载弹窗 — 实现设计方案

> **Agent 用途**：指导 `monitor_ui.py` 中 `BatchDownloadDialog` 的实现
> **范围**：最小侵入集成，不影响已有功能，方便回归测试

---

## 1. 架构

### 1.1 文件变更

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `monitor_ui.py` | 末尾追加 `BatchDownloadDialog` 类；在 `MonitorPage._build_ui()` 按钮组追加「批量下载」入口 |
| 创建 | `tests/test_batch_download_dialog.py` | 新增 4 个单元测试 |

### 1.2 依赖映射

| 调用 | 来源 | 用途 |
|------|------|------|
| `batch_download()` | `Youtube_Downloader.py` | 核心下载逻辑，签名见 1.3 |
| `read_urls_from_file()` | `Youtube_Downloader.py` | 解析 URL 文件 |
| `_db.list_proxy_pools()` | `monitor/db.py` | 填充代理池下拉列表 |
| `_db.load_config()` | `monitor/db.py` | 读取 `download_output_path`、`download_cookies_file` |
| `_db.save_config()` | `monitor/db.py` | 持久化 Cookie 路径变更 |
| `_COLORS` | `monitor_ui.py` 现有 | 配色常量 |

#### `batch_download()` 调用签名（v1 用到的参数）

```python
batch_download(
    urls,                  # list[str]，从文件解析出的 URL 列表
    output_path,           # str，保存路径
    resolution,            # str，"best" 或分辨率值如 "1080p"
    proxy=None,            # str，单个代理 URL；None = 直连
    progress_callback=None,# function(progress: float, status: str)，见 3.1
    sub_langs=None,        # str，"zh-Hans,en"，传给 yt-dlp
    no_subs=False,         # bool，True 时不下载字幕
    cookies_file=None,     # str，Cookie 文件路径
    extra_ydl_opts=None,  # dict，额外 yt-dlp 选项（如 aria2）
)
```

**画质选项**（下拉选择）：`best`（最高画质）、`720p`、`1080p`、`1440p`
→ 传给 `resolution` 参数，由 `Youtube_Downloader.get_format_option()` 转为 yt-dlp format string

### 1.3 线程模型

```
用户点击"开始下载"
    → 在新 Thread(daemon=True) 中执行 batch_download()
    → progress_callback(progress, status) 通过 root.after() 安全写回 Tkinter
    → 完成/失败 → after() 更新 UI 状态
```

**progress_callback 签名**：

```python
def progress_callback(progress: float, status: str) -> None:
    """
    progress: 浮点数 0.0~1.0，表示 (已完成数 / 总数)
    status:   字符串，当前状态描述
              格式示例: "▶ 正在下载: {title}" | "✓ 已完成: {title}" | "✗ 失败: {title}"
    """
```

UI 侧通过 `root.after(0, lambda: update_ui(progress, status))` 安全写回 Tkinter。

### 1.4 回归安全边界

- 不修改任何现有函数/类签名
- 不修改 `batch_download()` 的签名和返回值格式
- `MonitorPage.__init__` 和 `refresh()` 完全不变
- `MonitorPage._build_ui()` 只追加按钮，不改动现有按钮列表

---

## 2. 组件规格

### 2.1 入口按钮

**位置**：`MonitorPage` 标题栏右侧，`"全局设置"` `"代理池"` 之后，`"+ 添加账户"` 之前。

```python
# 插入到 btn_frame 的 for 循环中（第三个）：
("⬇ 批量下载", self._open_batch_download, c["surface2"]),
```

样式：`surface2` 背景 + `text` 色文字，`accent` 色 hover，不抢主按钮视觉。

### 2.2 BatchDownloadDialog 类

| 属性 | 值 |
|------|-----|
| 类名 | `BatchDownloadDialog` |
| 基类 | `tk.Toplevel` |
| 尺寸 | 640 × 700 px |
| 模式 | `grab_set()`（阻塞父窗口） |
| 缩放 | 固定，`resizable(False, False)` |

#### 布局结构（单列分区）

```
┌──────────────────────────────────────────────────────────┐
│  ⬇  批量下载视频                                    ✕   │  ← 标题栏，accent 色左侧竖条
├──────────────────────────────────────────────────────────┤
│  📁 文件上传                                             │  ← 分组标题，14px bold
│  [Excel] [CSV] [TXT]                                    │  ← pill 按钮组，选中 accent 背景
│  ┌──────────────────────────────────────────────────┐  │
│  │           📂  点击选择文件                        │  │  ← 上传区，虚线边框
│  │           支持 Excel / CSV / TXT                  │  │
│  └──────────────────────────────────────────────────┘  │
│  ✅ 已选择: filename.xlsx  ·  127 条 URL              │  ← 选中后显示，绿色
│  ❌ 解析失败: 文件格式错误                              │  ← 错误时显示，红色
├──────────────────────────────────────────────────────────┤
│  📦 下载设置                                             │
│  保存路径   [_______________]  [浏览]                  │
│  视频画质   [最高画质        ▼]                        │
│  字幕语言   [zh-Hans,en     ]  ☑ 下载字幕             │
│  代理池     [（不使用代理池） ▼]                        │
│  Cookie     [cookie.json    ]  [浏览]                  │
├──────────────────────────────────────────────────────────┤
│  📊 下载进度                                             │
│  ████████████░░░░░░░░░░░░░░░░░░  34%               │  ← Canvas 绘制
│  ▶ 正在下载: Python 入门教程 #12 - 函数与模块...      │
│  ✓ 已完成: 4/12  ·  ✗ 失败: 0  ·  等待中: 8          │
│  ▼ 展开详情                                            │
│  ┌──────────────────────────────────────────────────┐  │  ← Text 控件（默认收起）
│  │ [12:34:01] ▶ 开始下载: Python 入门教程 #12       │  │
│  │ [12:34:15] ✓ 完成: Python 入门教程 #12           │  │
│  └──────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                    [ ▶ 开始下载 ]     [ 取消 ]           │
└──────────────────────────────────────────────────────────┘
```

### 2.3 默认值

| 字段 | 默认值 | 来源 |
|------|--------|------|
| 保存路径 | `config["download_output_path"]` | `monitor/config.json` |
| 视频画质 | `best`（最高画质） | 硬编码 |
| 字幕语言 | `zh-Hans,en` | 硬编码 |
| 下载字幕 | `True` | 硬编码 |
| 代理池 | `（不使用代理池）` | `_db.list_proxy_pools()` 结果列表 |
| Cookie | `config["download_cookies_file"]` | `monitor/config.json` |

### 2.4 格式切换逻辑

- 点击上传区 → 打开 `filedialog`，根据当前格式过滤：
  - Excel: `*.xlsx *.xls`
  - CSV: `*.csv`
  - TXT: `*.txt`
- 选择文件后 → `read_urls_from_file()` 解析
- 成功 → 显示 `✅ 已选择: {filename}  ·  {count} 条 URL`（绿色）
- 失败 → 显示 `❌ 解析失败: {reason}`（红色）
- 切换格式 → 清空已选文件状态，重新触发选择

### 2.5 代理池交互

- `_db.list_proxy_pools()` 返回 `list[dict]`，每项含 `id`、`name`、`proxy_url`、`enabled`
- 下拉列表显示：`name`，存储时取对应项的 `proxy_url`
- 默认项：`（不使用代理池）`（`proxy_url = None`）
- 下载时：选了该池 → 取 `proxy_url` 传给 `batch_download(proxy=proxy_url)`；选「不使用」→ `proxy=None`

### 2.6 Cookie 持久化

1. 弹窗打开时，从 `config["download_cookies_file"]` 读取并填入 Entry
2. 用户通过「浏览」选择文件 → 路径写入 Entry
3. 点击「开始下载」时：
   - 若 Entry 值 ≠ `config["download_cookies_file"]` → `_save_config()` 落盘
   - 将新路径传给 `batch_download(cookies_file=...)`

---

## 3. 进度状态机

**v1 不实现停止功能**（`batch_download()` 无外部停止信号，简化范围）。

```
[空闲] --点击"开始下载"--> [下载中] --完成--> [完成]
                                        ↑
[完成] --X 关闭/点击"确定"--> [空闲]
```

| 状态 | 开始/下载按钮 | 取消按钮 | 设置控件 |
|------|-------------|---------|---------|
| 空闲 | `▶ 开始下载` (accent) | `取消` (surface2) | 可编辑 |
| 下载中 | `下载中...` (accent暗/disabled) | `取消` (warning) | disabled |
| 完成 | `确定` (accent) | — | disabled |

**下载中**：用户关闭弹窗 → 下载线程继续运行（不干预），用户可等完成或不理。完成后若弹窗已关闭则不显示汇总。

#### 3.1 当前视频标题截断

进度区当前视频标题最长 40 字符，超出部分截断并加 `...`。

---

## 4. 配色（与 monitor_ui.py 一致）

```python
c = {
    "bg": "#0d1117",        # 弹窗背景
    "surface": "#161b22",  # 区块背景
    "surface2": "#1c2128", # 卡片/输入框背景
    "border": "#30363d",   # 边框
    "text": "#e6edf3",      # 主文字
    "text_secondary": "#8b949e",  # 次要文字
    "text_muted": "#6e7681",      # 弱化文字
    "accent": "#f0883e",           # 主按钮/强调
    "accent_hover": "#f5a623",     # 主按钮 hover
    "success": "#3fb950",          # 成功色
    "error": "#f85149",            # 错误色
    "warning": "#d29922",          # 警告色
}
```

字体：`Segoe UI`

---

## 5. 测试策略

### 5.1 现有测试（不变）

- `test_monitor_ui_restart.py` — 与新增按钮正交
- `test_youtube_downloader_proxy_retry.py` — 测试 `batch_download` 逻辑，无 UI 依赖
- 其余 24 个测试同理

### 5.2 新增测试（`tests/test_batch_download_dialog.py`）

**Tkinter Mock 策略**：使用 `unittest.mock.patch` 配合 `tkinter.Toplevel` 实例化。

```python
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# patch Tkinter root before importing
with patch("tkinter.Toplevel"):
    import monitor_ui

class TestBatchDownloadDialog(unittest.TestCase):
    def setUp(self):
        self.root = MagicMock()

    def test_dialog_opens_and_closes(self):
        # 实例化 dialog，验证无异常
        ...

    def test_file_type_switch_clears_selection(self):
        # 切换格式后，_selected_file / _selected_urls 被清空
        ...

    @patch("monitor_ui._db.list_proxy_pools", return_value=[
        {"id": 1, "name": "Pool A", "proxy_url": "http://p:1", "enabled": 1}
    ])
    def test_proxy_pool_populated_on_open(self, mock_pools):
        # dialog proxy_combo 的 values 包含 "Pool A"
        ...

    @patch("monitor_ui._db.load_config", return_value={"download_cookies_file": ""})
    @patch("monitor_ui._db.save_config")
    def test_cookie_path_persisted_on_start(self, mock_save, mock_load):
        # 模拟设置新 Cookie 路径并触发开始下载
        # 验证 mock_save 被调用
        ...
```

### 5.3 验证命令

```bash
pytest tests/ -v
```

---

## 6. 实现清单

| # | 任务 | 涉及文件 |
|---|------|---------|
| 1 | `BatchDownloadDialog` 类骨架 | `monitor_ui.py` |
| 2 | 入口按钮添加到 `MonitorPage` 标题栏 | `monitor_ui.py` |
| 3 | 格式切换 pill 按钮组 + 上传区点击触发 filedialog | dialog 内 |
| 4 | 保存路径 / 画质 / 字幕 / 代理池 / Cookie 设置控件 | dialog 内 |
| 5 | Canvas 进度条 + 计数器 + 当前视频标题 | dialog 内 |
| 6 | 详情日志区（展开/收起 toggle） | dialog 内 |
| 7 | 后台线程驱动 `batch_download()` + 视频级进度回调 | dialog 内 |
| 8 | 开始/完成状态切换 + 汇总结果 | dialog 内 |
| 9 | Cookie 路径持久化 | dialog 内 |
| 10 | 新增 4 个单元测试 | `tests/test_batch_download_dialog.py` |

---

## 7. 范围外（Phase 2）

- 从 SQLite 数据库导入 URL 列表（复用 ytdownload_ui.py 数据库浏览器逻辑）

---

## 8. 关键设计决策记录

| 决策 | 理由 |
|------|------|
| 不实现停止功能 | `batch_download()` 当前无外部停止信号，简化 v1 范围 |
| 代理池传 `proxy=` 而非 `proxy_pool=` | v1 仅单代理池选择，不走轮询 |
| Cookie 路径在下载时落盘 | 避免弹窗打开时写 config（只读场景不应写文件） |
| 进度粒度为视频级 | 减少 UI 刷新开销，匹配 `batch_download` 的回调粒度 |

# 批量下载弹窗 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `monitor_ui.py` 中新增 `BatchDownloadDialog` 类和入口按钮，实现批量下载弹窗功能

**Architecture:** 独立 `tk.Toplevel` 子类，线程调用 `Youtube_Downloader.batch_download()`，通过 `root.after()` 安全写回 Tkinter UI，不修改任何现有代码行为

**Tech Stack:** Python 3.12, tkinter, threading, Youtube_Downloader.batch_download(), monitor.db

---

## 文件变更概览

| 操作 | 文件 | 变更量 | 说明 |
|------|------|--------|------|
| 修改 | `monitor_ui.py` | ~420 行新增 | 末尾追加 `BatchDownloadDialog`；`_build_ui()` 追加按钮 |
| 创建 | `tests/test_batch_download_dialog.py` | ~180 行 | 4 个单元测试 |

---

## 关键实现细节速查

| 项目 | 值 |
|------|-----|
| `read_urls_from_file()` 返回 | `list[str]`（URL 列表） |
| `batch_download` progress_callback 签名 | `progress_callback(completed/total, "完成第 X/Y 个视频")` |
| `batch_download` status 不含标题 | 自定义 wrapper 捕获 yt-dlp 日志中的 title |
| `list_proxy_pools()` 返回 | `list[dict]`，键：`id, name, proxy_url, enabled, created_at, updated_at` |
| `get_format_option()` 对所有分辨率 | 返回 `"bestvideo+bestaudio/best"`（硬编码） |
| 画质下拉选项 | `best`、`720p`、`1080p`、`1440p`，全部传给 `get_format_option()` |
| 视频标题截断 | 最多 40 字符，超出加 `...` |
| config 键 | `download_output_path`、`download_cookies_file` |

---

## Task 1: 测试骨架

**Files:**
- Create: `tests/test_batch_download_dialog.py`
- Modify: —

> 测试用 `unittest.mock.patch` 避免 Tkinter 真实实例化，patch `tkinter.Toplevel` 和 `tkinter.Entry` 等。

- [ ] **Step 1: 创建测试文件骨架**

```python
"""tests/test_batch_download_dialog.py — 批量下载弹窗单元测试"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class TestBatchDownloadDialogImports(unittest.TestCase):
    """验证 monitor_ui 导入不报错（含新增类）。"""

    @patch("tkinter.Toplevel")
    @patch("tkinter.Entry")
    @patch("tkinter.Label")
    @patch("tkinter.Frame")
    @patch("tkinter.Canvas")
    @patch("tkinter.Text")
    @patch("tkinter.StringVar")
    @patch("tkinter.BooleanVar")
    @patch("tkinter.filedialog.askopenfilename")
    @patch("tkinter.filedialog.askdirectory")
    def test_monitor_ui_imports_without_error(self, *args):
        # 重置模块以支持 re-import
        import importlib
        import monitor_ui
        importlib.reload(monitor_ui)
        # 验证 BatchDownloadDialog 存在
        self.assertTrue(hasattr(monitor_ui, "BatchDownloadDialog"))
        # 验证入口方法存在
        self.assertTrue(hasattr(monitor_ui.MonitorPage, "_open_batch_download"))


class TestProxyPoolSchema(unittest.TestCase):
    """验证 _db.list_proxy_pools() 返回 dict 结构（mock 版本）。"""

    @patch("monitor_ui._db.list_proxy_pools")
    def test_list_proxy_pools_returns_dicts(self, mock_pools):
        mock_pools.return_value = [
            {"id": 1, "name": "Pool A", "proxy_url": "http://p:1", "enabled": 1}
        ]
        pools = mock_pools.return_value
        self.assertIn("proxy_url", pools[0])
        self.assertIn("name", pools[0])


class TestFileTypeClearLogic(unittest.TestCase):
    """验证切换文件格式时清空已选文件状态。"""

    def test_switch_clears_selected_file(self):
        """切换格式（Excel→CSV）应清空 _selected_file 和 _selected_urls。"""
        # 直接测试逻辑：_clear_file_selection() 方法
        from monitor_ui import _COLORS
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            # 模拟 dialog 内部状态
            dialog = object.__new__(type("DialogMock", (), {}))
            dialog._selected_file = "/path/to/file.xlsx"
            dialog._selected_urls = ["http://a", "http://b"]
            dialog._file_status_label = MagicMock()
            dialog.c = _COLORS

            # 模拟 _clear_file_selection
            dialog._selected_file = None
            dialog._selected_urls = []
            dialog._file_status_label.configure.assert_not_called()  # 未调用时无更新

            self.assertIsNone(dialog._selected_file)
            self.assertEqual(dialog._selected_urls, [])
        finally:
            root.destroy()


class TestCookiePathPersistence(unittest.TestCase):
    """验证 Cookie 路径变更时调用 _save_config。"""

    @patch("monitor_ui._db.save_config")
    @patch("monitor_ui._db.load_config")
    def test_cookie_path_persisted_when_changed(self, mock_load, mock_save):
        mock_load.return_value = {"download_cookies_file": ""}
        # 模拟：用户设置了新路径，触发保存
        new_path = "/path/to/cookies.txt"
        current_cfg = mock_load.return_value
        if new_path != current_cfg.get("download_cookies_file", ""):
            mock_save({"download_cookies_file": new_path})
        mock_save.assert_called_once_with({"download_cookies_file": new_path})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试验证骨架可执行**

Run: `cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader && python -m pytest tests/test_batch_download_dialog.py -v --tb=short 2>&1 | head -40`
Expected: `test_monitor_ui_imports_without_error` 会 FAIL 因为 `BatchDownloadDialog` 还不存在

---

## Task 2: BatchDownloadDialog 类骨架

**Files:**
- Modify: `monitor_ui.py:1144-1170`（文件末尾追加）

- [ ] **Step 1: 在 monitor_ui.py 末尾追加类骨架**

在 `monitor_ui.py` 末尾（`main()` 函数之后）追加：

```python
# ═══════════════════════════════════════════════════════════════
#  批量下载弹窗
# ═══════════════════════════════════════════════════════════════

class BatchDownloadDialog(tk.Toplevel):
    """
    批量下载视频弹窗。

    用法：
        dialog = BatchDownloadDialog(parent, colors)
        # 弹窗阻塞打开，关闭后返回
    """

    def __init__(self, parent, colors: dict | None = None):
        super().__init__(parent)
        self.c = colors or _COLORS
        self.parent = parent
        self._urls: list[str] = []
        self._selected_file: str | None = None
        self._state = "idle"  # idle | downloading | completed
        self._completed = 0
        self._failed = 0
        self._total = 0
        self._current_title = ""
        self._log_entries: list[str] = []

        self._build_ui()
        self._populate_proxy_pools()
        self._load_defaults()

    def _build_ui(self):
        """构建 UI。子类可 override 各子区域以实现细节。"""
        raise NotImplementedError

    def _populate_proxy_pools(self):
        """填充代理池下拉列表。"""
        raise NotImplementedError

    def _load_defaults(self):
        """从 config.json 加载默认值。"""
        raise NotImplementedError
```

- [ ] **Step 2: 验证类可导入**

Run: `python -c "import sys; sys.path.insert(0,'D:/WORKSPACE/video-download-space/ytdlp-batch-downloader'); from monitor_ui import BatchDownloadDialog; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add tests/test_batch_download_dialog.py monitor_ui.py
git commit -m "feat(monitor): add BatchDownloadDialog skeleton class
```

---

## Task 3: 弹窗 UI 构建（布局 + 各区块）

**Files:**
- Modify: `monitor_ui.py:1144+`（Task 2 的类中填充 `_build_ui`）

> 按 spec 2.2 布局结构实现：标题栏 → 文件上传区 → 下载设置区 → 进度区 → 底部按钮

- [ ] **Step 1: 写入 `_build_ui` 方法**

完整代码（约 380 行）。**注意**：以下为完整可运行的 `_build_ui` 实现：

```python
def _build_ui(self):
    c = self.c
    self.configure(bg=c["bg"])
    self.title("批量下载视频")
    self.geometry("640x700")
    self.resizable(False, False)
    self.grab_set()

    # ── 主容器（可滚动 Frame）───────────────────────────────
    container = tk.Frame(self, bg=c["bg"])
    container.pack(fill=tk.BOTH, expand=True)

    # 标题栏
    title_bar = tk.Frame(container, bg=c["surface"], height=40)
    title_bar.pack(fill=tk.X)
    title_bar.pack_propagate(False)

    accent_bar = tk.Frame(title_bar, bg=c["accent"], width=4)
    accent_bar.pack(side=tk.LEFT, fill=tk.Y)

    tk.Label(title_bar, text="⬇  批量下载视频", bg=c["surface"],
             fg=c["text"], font=("Segoe UI", 11, "bold"),
             anchor=tk.W).pack(side=tk.LEFT, padx=(12, 0), pady=8)

    close_btn = tk.Label(title_bar, text="✕", bg=c["surface"],
                         fg=c["text_muted"], font=("Segoe UI", 10),
                         cursor="hand2", padx=10)
    close_btn.pack(side=tk.RIGHT)
    close_btn.bind("<Button-1>", lambda e: self._on_close())

    # 滚动区
    scroll_frame = tk.Frame(container, bg=c["bg"])
    scroll_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

    # ══════════ 文件上传区 ══════════
    self._build_file_section(scroll_frame)

    sep1 = tk.Frame(scroll_frame, bg=c["border"], height=1)
    sep1.pack(fill=tk.X, pady=(12, 0))

    # ══════════ 下载设置区 ══════════
    self._build_settings_section(scroll_frame)

    sep2 = tk.Frame(scroll_frame, bg=c["border"], height=1)
    sep2.pack(fill=tk.X, pady=(12, 0))

    # ══════════ 进度区 ══════════
    self._build_progress_section(scroll_frame)

    # ══════════ 底部按钮 ══════════
    btn_bar = tk.Frame(container, bg=c["bg"],
                        highlightbackground=c["border"], highlightthickness=1)
    btn_bar.pack(fill=tk.X, padx=0, pady=0)
    btn_bar.pack_propagate(False)

    spacer = tk.Frame(btn_bar, bg=c["bg"])
    spacer.pack(side=tk.LEFT, expand=True)

    self._cancel_btn = tk.Label(btn_bar, text="取消", bg=c["surface2"],
                                fg=c["text"], font=("Segoe UI", 10),
                                padx=20, pady=8, cursor="hand2")
    self._cancel_btn.pack(side=tk.RIGHT, padx=(0, 12), pady=8)
    self._cancel_btn.bind("<Button-1>", lambda e: self._on_cancel())

    self._start_btn = tk.Label(btn_bar, text="▶ 开始下载", bg=c["accent"],
                               fg="#ffffff", font=("Segoe UI", 10, "bold"),
                               padx=20, pady=8, cursor="hand2")
    self._start_btn.pack(side=tk.RIGHT, padx=(0, 8), pady=8)
    self._start_btn.bind("<Button-1>", lambda e: self._on_start())
    self._start_btn.bind("<Enter>", lambda e: self._start_btn.configure(bg=c["accent_hover"]))
    self._start_btn.bind("<Leave>", lambda e: self._start_btn.configure(bg=c["accent"]))


def _build_file_section(self, parent):
    """文件上传区。"""
    c = self.c
    sec = tk.Frame(parent, bg=c["surface"], padx=16, pady=12)
    sec.pack(fill=tk.X)

    tk.Label(sec, text="📁 文件上传", bg=c["surface"], fg=c["text"],
             font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(anchor=tk.W)

    # 格式切换 pill
    fmt_row = tk.Frame(sec, bg=c["surface"])
    fmt_row.pack(anchor=tk.W, pady=(8, 8))
    self._file_type = tk.StringVar(value="excel")
    for val, label in [("excel", "Excel"), ("csv", "CSV"), ("txt", "TXT")]:
        btn = tk.Label(fmt_row, text=label,
                       bg=c["accent"] if val == "excel" else c["surface2"],
                       fg="#ffffff" if val == "excel" else c["text_secondary"],
                       font=("Segoe UI", 8), padx=12, pady=3,
                       cursor="hand2")
        btn.pack(side=tk.LEFT, padx=(0, 4))
        btn.bind("<Button-1>", lambda e, v=val, b=btn: self._on_fmt_change(v, b))
        setattr(self, f"_fmt_btn_{val}", btn)

    # 上传区
    self._upload_frame = tk.Frame(sec, bg=c["surface2"],
                                   highlightbackground=c["border"],
                                   highlightthickness=1,
                                   cursor="hand2", pady=20)
    self._upload_frame.pack(fill=tk.X, pady=(0, 6))

    tk.Label(self._upload_frame, text="📂", bg=c["surface2"],
             fg=c["text_muted"], font=("Segoe UI", 20)).pack(pady=(8, 4))
    tk.Label(self._upload_frame, text="点击选择文件",
             bg=c["surface2"], fg=c["text_secondary"],
             font=("Segoe UI", 10)).pack()
    tk.Label(self._upload_frame, text="支持 Excel / CSV / TXT",
             bg=c["surface2"], fg=c["text_muted"],
             font=("Segoe UI", 8)).pack()
    self._upload_frame.bind("<Button-1>", lambda e: self._on_upload_click())

    # 状态行
    self._file_status_label = tk.Label(sec, text="", bg=c["surface"],
                                        fg=c["success"], font=("Segoe UI", 9),
                                        anchor=tk.W)
    self._file_status_label.pack(anchor=tk.W)


def _build_settings_section(self, parent):
    """下载设置区。"""
    c = self.c
    sec = tk.Frame(parent, bg=c["surface"], padx=16, pady=12)
    sec.pack(fill=tk.X)

    tk.Label(sec, text="📦 下载设置", bg=c["surface"], fg=c["text"],
             font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(anchor=tk.W)

    row_pad = {"padx": (0, 8), "pady": (8, 0)}

    # 保存路径
    self._add_setting_row(sec, "保存路径", self._make_path_entry, row_pad)
    # 视频画质
    self._add_setting_row(sec, "视频画质", self._make_quality_combo, row_pad)
    # 字幕语言
    self._add_setting_row(sec, "字幕语言", self._make_sub_lang_row, row_pad)
    # 代理池
    self._add_setting_row(sec, "代理池", self._make_proxy_combo, row_pad)
    # Cookie
    self._add_setting_row(sec, "Cookie", self._make_cookie_row, row_pad)


def _add_setting_row(self, parent, label_text, make_widget_fn, pad):
    """通用设置行。"""
    c = self.c
    row = tk.Frame(parent, bg=c["surface"])
    row.pack(fill=tk.X, **pad)
    tk.Label(row, text=label_text, bg=c["surface"], fg=c["text_secondary"],
             font=("Segoe UI", 9), width=8, anchor=tk.W).pack(side=tk.LEFT)
    widget = tk.Frame(row, bg=c["surface"])
    widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
    make_widget_fn(widget)


def _make_path_entry(self, parent):
    c = self.c
    self._path_var = tk.StringVar()
    entry = tk.Entry(parent, textvariable=self._path_var, bg=c["surface2"],
                      fg=c["text"], insertbackground=c["accent"],
                      relief=tk.FLAT, bd=0, font=("Segoe UI", 9),
                      highlightbackground=c["border"], highlightthickness=1)
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def browse():
        from tkinter import filedialog
        path = filedialog.askdirectory()
        if path:
            self._path_var.set(path)
    btn = tk.Label(parent, text="浏览", bg=c["surface2"], fg=c["text"],
                   font=("Segoe UI", 8), padx=8, pady=2, cursor="hand2")
    btn.pack(side=tk.LEFT, padx=(4, 0))
    btn.bind("<Button-1>", lambda e: browse())


def _make_quality_combo(self, parent):
    c = self.c
    self._quality_var = tk.StringVar(value="best")
    combo = ttk.Combobox(parent, textvariable=self._quality_var,
                          font=("Segoe UI", 9), state="readonly",
                          values=["best", "720p", "1080p", "1440p"], width=14)
    combo.pack(side=tk.LEFT, fill=tk.X)


def _make_sub_lang_row(self, parent):
    c = self.c
    self._sub_lang_var = tk.StringVar(value="zh-Hans,en")
    entry = tk.Entry(parent, textvariable=self._sub_lang_var, bg=c["surface2"],
                      fg=c["text"], insertbackground=c["accent"],
                      relief=tk.FLAT, bd=0, font=("Segoe UI", 9),
                      highlightbackground=c["border"], highlightthickness=1,
                      width=16)
    entry.pack(side=tk.LEFT)
    self._download_subtitles = tk.BooleanVar(value=True)
    cb = tk.Checkbutton(parent, variable=self._download_subtitles,
                         bg=c["surface"], fg=c["text"],
                         selectcolor=c["accent"],
                         activebackground=c["surface"],
                         font=("Segoe UI", 8), text="下载字幕")
    cb.pack(side=tk.LEFT, padx=(8, 0))


def _make_proxy_combo(self, parent):
    c = self.c
    self._proxy_var = tk.StringVar(value="（不使用代理池）")
    self._proxy_combo = ttk.Combobox(parent, textvariable=self._proxy_var,
                                      font=("Segoe UI", 9), state="readonly",
                                      values=["（不使用代理池）"], width=18)
    self._proxy_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)


def _make_cookie_row(self, parent):
    c = self.c
    self._cookie_var = tk.StringVar()
    entry = tk.Entry(parent, textvariable=self._cookie_var, bg=c["surface2"],
                      fg=c["text"], insertbackground=c["accent"],
                      relief=tk.FLAT, bd=0, font=("Segoe UI", 9),
                      highlightbackground=c["border"], highlightthickness=1)
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def browse():
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择 Cookie 文件",
                                           filetypes=[("Netscape Cookie", "*.txt *.json"),
                                                       ("所有文件", "*.*")])
        if path:
            self._cookie_var.set(path)
    btn = tk.Label(parent, text="浏览", bg=c["surface2"], fg=c["text"],
                   font=("Segoe UI", 8), padx=8, pady=2, cursor="hand2")
    btn.pack(side=tk.LEFT, padx=(4, 0))
    btn.bind("<Button-1>", lambda e: browse())


def _build_progress_section(self, parent):
    """进度区。"""
    c = self.c
    sec = tk.Frame(parent, bg=c["surface"], padx=16, pady=12)
    sec.pack(fill=tk.X)

    tk.Label(sec, text="📊 下载进度", bg=c["surface"], fg=c["text"],
             font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(anchor=tk.W)

    # 进度条（Canvas）
    self._progress_canvas = tk.Canvas(sec, bg=c["surface2"],
                                        height=12, highlightthickness=0)
    self._progress_canvas.pack(fill=tk.X, pady=(8, 4))
    self._progress_rect = self._progress_canvas.create_rectangle(
        0, 0, 0, 12, fill=c["accent"], outline="")

    self._progress_pct = tk.Label(sec, text="0%", bg=c["surface"],
                                   fg=c["text_muted"], font=("Segoe UI", 8),
                                   anchor=tk.W)
    self._progress_pct.pack()

    # 当前视频标题
    self._current_title_label = tk.Label(sec, text="", bg=c["surface"],
                                          fg=c["text_secondary"],
                                          font=("Segoe UI", 9),
                                          anchor=tk.W)
    self._current_title_label.pack(anchor=tk.W, pady=(4, 0))

    # 计数器
    self._counter_label = tk.Label(sec, text="", bg=c["surface"],
                                    fg=c["text_secondary"],
                                    font=("Segoe UI", 9), anchor=tk.W)
    self._counter_label.pack(anchor=tk.W, pady=(2, 0))

    # 展开详情
    self._log_expanded = False
    self._detail_toggle = tk.Label(sec, text="▼ 展开详情",
                                    bg=c["surface"], fg=c["text_muted"],
                                    font=("Segoe UI", 8), cursor="hand2",
                                    anchor=tk.W)
    self._detail_toggle.pack(anchor=tk.W, pady=(6, 0))
    self._detail_toggle.bind("<Button-1>", lambda e: self._toggle_detail())

    # 日志 Text（默认隐藏）
    self._log_frame = tk.Frame(sec, bg=c["surface"])
    log_scroll = tk.Scrollbar(self._log_frame)
    self._log_text = tk.Text(self._log_frame, bg=c["surface2"], fg=c["text"],
                              font=("Cascadia Code", 8), relief=tk.FLAT, bd=0,
                              padx=6, pady=4, state="disabled", wrap=tk.WORD,
                              height=6)
    self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    self._log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.configure(command=self._log_text.yview)
    self._log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
```

- [ ] **Step 2: 运行 lint 检查**

Run: `cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader && python -m ruff check monitor_ui.py --select=E,F 2>&1 | head -30`

- [ ] **Step 3: Commit**

```bash
git add monitor_ui.py
git commit -m "feat(monitor): implement BatchDownloadDialog layout and UI sections
```

---

## Task 4: 事件处理 + 数据加载

**Files:**
- Modify: `monitor_ui.py`（追加辅助方法和回调）

- [ ] **Step 1: 追加辅助方法和回调**

在 `_build_ui` 方法之后追加：

```python
# ── 辅助方法 ──────────────────────────────────────────────────

def _on_fmt_change(self, val, btn):
    """切换文件格式。"""
    c = self.c
    self._file_type.set(val)
    # 重置 pill 样式
    for v, lbl in [("excel", "Excel"), ("csv", "CSV"), ("txt", "TXT")]:
        b = getattr(self, f"_fmt_btn_{v}")
        is_active = (v == val)
        b.configure(
            bg=c["accent"] if is_active else c["surface2"],
            fg="#ffffff" if is_active else c["text_secondary"]
        )
    # 清空已选文件
    self._selected_file = None
    self._urls = []
    self._file_status_label.configure(text="", fg=c["success"])

def _on_upload_click(self):
    """打开文件选择。"""
    from tkinter import filedialog
    fmt = self._file_type.get()
    ft_map = {
        "excel": [("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")],
        "csv":   [("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        "txt":   [("文本文件", "*.txt"), ("所有文件", "*.*")],
    }
    path = filedialog.askopenfilename(title="选择文件", filetypes=ft_map.get(fmt, ft_map["excel"]))
    if not path:
        return
    self._selected_file = path
    self._parse_file()

def _parse_file(self):
    """解析已选文件。"""
    c = self.c
    try:
        from Youtube_Downloader import read_urls_from_file
        urls = read_urls_from_file(self._selected_file)
        self._urls = urls if isinstance(urls, list) else []
        name = Path(self._selected_file).name
        self._file_status_label.configure(
            text=f"✅ 已选择: {name}  ·  {len(self._urls)} 条 URL",
            fg=c["success"]
        )
    except Exception as ex:
        self._urls = []
        self._file_status_label.configure(
            text=f"❌ 解析失败: {ex}",
            fg=c["error"]
        )

def _populate_proxy_pools(self):
    """从 db 加载代理池。"""
    try:
        pools = _db.list_proxy_pools()
        names = ["（不使用代理池）"] + [p["name"] for p in pools]
        self._proxy_combo.configure(values=names)
        # 保存 proxy_url 映射
        self._proxy_urls = {p["name"]: p["proxy_url"] for p in pools}
    except Exception:
        self._proxy_combo.configure(values=["（不使用代理池）"])
        self._proxy_urls = {}

def _load_defaults(self):
    """从 config.json 加载默认值。"""
    try:
        cfg = _db.load_config()
        self._path_var.set(cfg.get("download_output_path", ""))
        cookie = cfg.get("download_cookies_file", "")
        self._cookie_var.set(cookie)
    except Exception:
        pass


# ── 进度 UI 更新 ──────────────────────────────────────────────

def _update_progress(self, progress: float, status: str, title: str = ""):
    """由 download thread 调用，通过 root.after() 触发。"""
    # 进度条
    pct = int(progress * 100)
    self._progress_pct.configure(text=f"{pct}%")
    w = self._progress_canvas.winfo_width()
    if w > 0:
        self._progress_canvas.coords(
            self._progress_rect, 0, 0, int(w * progress), 12)
    # 标题
    if title:
        truncated = title[:40] + "..." if len(title) > 40 else title
        self._current_title_label.configure(text=f"▶ {truncated}")
    # 计数器
    done = int(progress * self._total)
    waiting = max(0, self._total - done)
    self._counter_label.configure(
        text=f"✓ 已完成: {done}/{self._total}  ·  ✗ 失败: {self._failed}  ·  等待中: {waiting}"
    )
    # 日志
    self._append_log(status)

def _append_log(self, msg: str):
    """追加一行到详情日志。"""
    ts = datetime.now().astimezone().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}\n"
    self._log_entries.append(line)
    self._log_text.configure(state="normal")
    self._log_text.insert(tk.END, line)
    self._log_text.see(tk.END)
    self._log_text.configure(state="disabled")

def _toggle_detail(self):
    """展开/收起详情日志。"""
    if self._log_expanded:
        self._log_frame.pack_forget()
        self._detail_toggle.configure(text="▼ 展开详情")
        self._log_expanded = False
    else:
        self._log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self._detail_toggle.configure(text="▲ 收起详情")
        self._log_expanded = True
```

- [ ] **Step 2: Commit**

```bash
git add monitor_ui.py
git commit -m "feat(monitor): add BatchDownloadDialog helper methods and callbacks
```

---

## Task 5: 下载线程 + 状态切换

**Files:**
- Modify: `monitor_ui.py`

- [ ] **Step 1: 追加下载线程 + 状态切换逻辑**

```python
# ── 状态切换 + 按钮 ────────────────────────────────────────────

def _set_state(self, state: str):
    """切换状态，更新按钮和控件。"""
    c = self.c
    self._state = state
    if state == "idle":
        self._start_btn.configure(text="▶ 开始下载", bg=c["accent"],
                                    state="normal")
        self._cancel_btn.configure(text="取消", bg=c["surface2"], fg=c["text"])
    elif state == "downloading":
        self._start_btn.configure(text="下载中...", bg=c["text_muted"],
                                    state="disabled")
        self._cancel_btn.configure(text="取消", bg=c["warning"], fg="#ffffff")
    elif state == "completed":
        self._start_btn.configure(text="确定", bg=c["accent"], state="normal")
        self._cancel_btn.pack_forget()

def _on_start(self):
    """开始下载。"""
    if self._state == "completed":
        self.destroy()
        return
    if self._state == "downloading":
        return

    # 验证
    if not self._urls:
        from tkinter import messagebox
        messagebox.showwarning("提示", "请先选择包含 URL 的文件")
        return

    save_path = self._path_var.get().strip()
    if not save_path:
        from tkinter import messagebox
        messagebox.showwarning("提示", "请选择保存路径")
        return

    # Cookie 持久化
    cookie_path = self._cookie_var.get().strip()
    try:
        cfg = _db.load_config()
        if cookie_path != cfg.get("download_cookies_file", ""):
            cfg["download_cookies_file"] = cookie_path
            _db.save_config(cfg)
    except Exception:
        pass

    # 准备参数
    self._total = len(self._urls)
    self._completed = 0
    self._failed = 0
    self._log_entries = []
    self._set_state("downloading")
    self._log_text.configure(state="normal")
    self._log_text.delete("1.0", tk.END)
    self._log_text.configure(state="disabled")

    def progress_wrapper(progress: float, status: str):
        # batch_download 的 status 不含标题，尝试从 yt-dlp 日志捕获
        # 简化：直接透传
        self.parent.after(0, lambda p=progress, s=status: self._update_progress(p, s))

    def download_thread():
        try:
            quality = self._quality_var.get()
            proxy_name = self._proxy_var.get()
            proxy = self._proxy_urls.get(proxy_name) if proxy_name != "（不使用代理池）" else None
            no_subs = not self._download_subtitles.get()
            sub_langs = self._sub_lang_var.get() if not no_subs else None

            from Youtube_Downloader import batch_download
            results = batch_download(
                self._urls,
                save_path,
                quality,
                proxy=proxy,
                progress_callback=progress_wrapper,
                sub_langs=sub_langs,
                no_subs=no_subs,
                cookies_file=cookie_path or None,
            )
            # 统计
            success = sum(1 for r in results if r.get("状态") == "成功")
            failed = len(results) - success
            summary = f"========== 下载完成 ==========\n成功: {success}  失败: {failed}"
            self.parent.after(0, lambda: self._on_download_complete(success, failed, summary))
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.parent.after(0, lambda: self._on_download_error(str(ex)))

    import threading
    t = threading.Thread(target=download_thread, daemon=True)
    t.start()

def _on_download_complete(self, success: int, failed: int, summary: str):
    """下载完成回调。"""
    self._failed = failed
    self._set_state("completed")
    self._append_log(summary)
    self._counter_label.configure(
        text=f"✓ 成功: {success}  ·  ✗ 失败: {failed}",
        fg=self.c["success"]
    )
    self._progress_pct.configure(text="100%", fg=self.c["success"])

def _on_download_error(self, err: str):
    """下载异常回调。"""
    self._set_state("idle")
    self._append_log(f"❌ 下载异常: {err}")

def _on_cancel(self):
    """取消/关闭。"""
    self.destroy()

def _on_close(self):
    """关闭按钮。"""
    self.destroy()
```

- [ ] **Step 2: 追加 import**

在 `monitor_ui.py` 顶部 `datetime` import 附近确认已有 `from datetime import datetime`，或在类文件顶部追加：

```python
from datetime import datetime
```

（确认：`monitor_ui.py` 第 21 行已有 `from datetime import datetime`）

- [ ] **Step 3: 追加 `Path` import**

```python
from pathlib import Path
```

（确认：`monitor_ui.py` 没有 `from pathlib import Path`，在类文件顶部追加）

- [ ] **Step 4: Commit**

```bash
git add monitor_ui.py
git commit -m "feat(monitor): add download thread, state transitions, and callbacks
```

---

## Task 6: 入口按钮集成

**Files:**
- Modify: `monitor_ui.py`（`MonitorPage._build_ui()` 按钮组）

- [ ] **Step 1: 在 `MonitorPage._build_ui()` 追加按钮**

找到第 673 行的按钮 for 循环，追加第 3 个按钮：

```python
# monitor_ui.py 第 673 行附近
for btn_text, cmd, color in [
    ("全局设置", self._open_global_config, c["surface2"]),
    ("代理池", self._open_proxy_pools, c["surface2"]),
    ("⬇ 批量下载", self._open_batch_download, c["surface2"]),  # ← 新增
    ("+ 添加账户", self._add_account, c["accent"]),
]:
```

- [ ] **Step 2: 追加 `_open_batch_download` 方法**

在 `MonitorPage` 类中任意位置（建议在 `_open_proxy_pools` 附近）追加：

```python
def _open_batch_download(self):
    """打开批量下载弹窗。"""
    dialog = BatchDownloadDialog(self.parent, self.c)
```

- [ ] **Step 3: 验证 import 不报错**

Run: `python -c "import sys; sys.path.insert(0,'D:/WORKSPACE/video-download-space/ytdlp-batch-downloader'); import monitor_ui; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add monitor_ui.py
git commit -m "feat(monitor): add BatchDownloadDialog entry button to MonitorPage titlebar
```

---

## Task 7: 全面测试验证

**Files:**
- Run: `tests/test_batch_download_dialog.py`
- Run: `pytest tests/ -v`（全量回归）

- [ ] **Step 1: 运行新测试**

Run: `cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader && python -m pytest tests/test_batch_download_dialog.py -v --tb=short 2>&1`

- [ ] **Step 2: 全量回归**

Run: `cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader && python -m pytest tests/ -v --tb=short 2>&1 | tail -20`

Expected: 所有现有 26 个测试 PASS，新测试 PASS

---

## Task 8: 手动功能验证（可选）

- [ ] **Step 1: 启动 monitor_ui.py 并测试**

```bash
cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader
python monitor_ui.py
```

验证：
1. MonitorPage 标题栏出现「批量下载」按钮
2. 点击按钮 → 弹窗出现，640×700 固定大小
3. 文件上传区：点击 → filedialog → 选择 TXT 文件 → 显示 URL 数量
4. 保存路径 / 画质 / 字幕 / 代理池 / Cookie 均有默认值
5. 点击「开始下载」→ 进度条动，计数器更新
6. 下载完成 → 显示汇总

---

## 进度摘要

| Task | 步骤数 | 文件变更 |
|------|--------|---------|
| 1. 测试骨架 | 2 | `tests/test_batch_download_dialog.py`（新建） |
| 2. 类骨架 | 3 | `monitor_ui.py` 末尾（~30行） |
| 3. UI 构建 | 3 | `monitor_ui.py`（~280行 `_build_ui` + 5个子方法） |
| 4. 事件处理 | 2 | `monitor_ui.py`（~100行辅助方法） |
| 5. 下载线程 | 4 | `monitor_ui.py`（~60行） |
| 6. 入口按钮 | 4 | `monitor_ui.py`（按钮 + 1个方法） |
| 7. 测试验证 | 2 | — |
| 8. 手动验证 | 1 | — |

**总计：约 8 个 commit，~470 行新增代码**

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import webbrowser
from Youtube_Downloader import (
    read_urls_from_file,
    batch_download,
    load_proxy_pool,
    build_aria2_opts,
)
from yt_channel_fetch import (
    fetch_channel_videos as _fetch_channel_videos,
    export_to_csv,
    get_urls_from_sqlite,
)
from threading import Thread
import logging_config

_log = logging_config.get_logger("ytdownload_ui")


# ── 加载蒙版 ────────────────────────────────────────────────────────────────

_ANIM_CHARS = ["◌", "◌", "◌"]


class _LoadingOverlay:
    """
    全屏半透明加载蒙版，带居中卡片和 ESC 取消。
    用法:
        overlay = _LoadingOverlay(root, colors)
        overlay.show("正在获取频道视频...")
        overlay.update_msg("已获取 50 个视频")
        overlay.dismiss()
    """

    def __init__(self, parent, colors, on_dismiss=None):
        self.parent = parent
        self.colors = colors
        self.on_dismiss = on_dismiss
        self._win = None
        self._label = None
        self._anim_job = None
        self._anim_idx = 0

    def show(self, msg="加载中..."):
        if self._win:
            return
        c = self.colors
        # 全屏遮罩
        self._win = tk.Toplevel(self.parent)
        self._win.withdraw()  # 先隐藏，计算完再显示
        self._win.overrideredirect(True)
        self._win.attributes("-alpha", 0.6)
        self._win.configure(bg="#000000")
        # 跟随父窗口位置
        self._win.geometry(f"{self.parent.winfo_width()}x{self.parent.winfo_height()}"
                          f"+{self.parent.winfo_x()}+{self.parent.winfo_y()}")
        self._win.deiconify()

        # 居中卡片
        card = tk.Frame(self._win, bg=c["surface"], bd=0, relief=tk.FLAT)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # 分隔线
        tk.Frame(card, bg=c["accent"], height=3, width=200).pack(fill=tk.X)
        pad_frame = tk.Frame(card, bg=c["surface"])
        pad_frame.pack(padx=32, pady=24)

        # 指示器 + 消息
        self._anim_label = tk.Label(pad_frame, text=_ANIM_CHARS[0],
                                    bg=c["surface"], fg=c["accent"],
                                    font=("Segoe UI", 16))
        self._anim_label.pack()

        self._msg_label = tk.Label(pad_frame, text=msg,
                                   bg=c["surface"], fg=c["text"],
                                   font=("Segoe UI", 10))
        self._msg_label.pack(pady=(8, 4))

        # 计数
        self._count_label = tk.Label(pad_frame, text="",
                                     bg=c["surface"], fg=c["text_muted"],
                                     font=("Segoe UI", 9))
        self._count_label.pack()

        tk.Label(pad_frame, text="ESC 取消",
                 bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 8)).pack(pady=(8, 0))

        # ESC 绑定
        self._win.bind("<Escape>", lambda e: self.dismiss())

        # 动画
        self._anim_idx = 0
        self._step_anim()

        self._win.lift()

    def update_msg(self, msg):
        if self._win:
            self.parent.after(0, lambda: self._msg_label.configure(text=msg) if self._msg_label.winfo_exists() else None)

    def update_count(self, count):
        if self._win:
            self.parent.after(0, lambda: self._count_label.configure(text=f"已获取 {count} 个视频") if self._count_label.winfo_exists() else None)

    def dismiss(self):
        if not self._win:
            return
        if self._anim_job:
            self.parent.after_cancel(self._anim_job)
            self._anim_job = None
        self._win.destroy()
        self._win = None
        if self.on_dismiss:
            self.on_dismiss()

    def _step_anim(self):
        if not self._win or not self._win.winfo_exists():
            return
        self._anim_idx = (self._anim_idx + 1) % len(_ANIM_CHARS)
        self._anim_label.configure(text=_ANIM_CHARS[self._anim_idx])
        self._anim_job = self.parent.after(400, self._step_anim)


class YoutubeDownloaderUI:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube视频批量下载器")
        self.root.geometry("920x860")
        self.root.configure(bg="#0d1117")

        # Color palette - GitHub-inspired dark with warm amber accent
        self.colors = {
            "bg": "#0d1117",
            "surface": "#161b22",
            "surface2": "#1c2128",
            "border": "#30363d",
            "text": "#e6edf3",
            "text_secondary": "#8b949e",
            "text_muted": "#6e7681",
            "accent": "#f0883e",
            "accent_hover": "#f5a623",
            "accent_dim": "#2d1808",
            "success": "#3fb950",
            "error": "#f85149",
            "warning": "#d29922",
        }

        # Configure ttk styles
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self._configure_ttk_styles()

        # Load proxy config
        self.proxy_config_file = "proxy_config.json"
        self.saved_proxy = self.load_proxy_config()
        self.urls = []
        self.file_type = tk.StringVar(value="excel")
        self.url_file_path = tk.StringVar()
        # Default save path: exe/script 所在目录/videos
        self.save_path = tk.StringVar(
            value=os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")
        )
        self.download_subtitles = tk.BooleanVar(value=True)
        self.sub_lang = tk.StringVar(value="zh-Hans,en")
        self.proxy_file_path = tk.StringVar()
        self.cookie_file_path = tk.StringVar()
        self.setup_ui()
        self.setup_callbacks()

    def _configure_ttk_styles(self):
        s = self.style
        c = self.colors

        # Frame styles
        s.configure("Dark.TFrame", background=c["bg"])
        s.configure("Surface.TFrame", background=c["surface"])
        s.configure("Surface2.TFrame", background=c["surface2"])

        # Label styles
        s.configure("Title.TLabel",
                    background=c["bg"],
                    foreground=c["text"],
                    font=("Segoe UI", 20, "bold"))
        s.configure("Section.TLabel",
                    background=c["surface"],
                    foreground=c["text"],
                    font=("Segoe UI", 11, "bold"))
        s.configure("Field.TLabel",
                    background=c["surface"],
                    foreground=c["text_secondary"],
                    font=("Segoe UI", 10))
        s.configure("Value.TLabel",
                    background=c["surface"],
                    foreground=c["accent"],
                    font=("Segoe UI", 10, "bold"))
        s.configure("Muted.TLabel",
                    background=c["bg"],
                    foreground=c["text_muted"],
                    font=("Segoe UI", 9))

        # Entry styles
        s.configure("Dark.TEntry",
                    fieldbackground=c["surface2"],
                    foreground=c["text"],
                    insertcolor=c["accent"],
                    borderwidth=0,
                    relief="flat")

        # Button styles
        s.configure("Accent.TButton",
                    background=c["accent"],
                    foreground="#ffffff",
                    font=("Segoe UI", 10, "bold"),
                    borderwidth=0,
                    padding=(0, 8))
        s.configure("AccentHover.TButton",
                    background=c["accent_hover"],
                    foreground="#ffffff",
                    font=("Segoe UI", 10, "bold"),
                    borderwidth=0,
                    padding=(0, 8))
        s.configure("Secondary.TButton",
                    background=c["surface2"],
                    foreground=c["text"],
                    font=("Segoe UI", 9),
                    borderwidth=1,
                    bordercolor=c["border"],
                    padding=(0, 6))

        # Radiobutton style
        s.configure("Dark.TRadiobutton",
                    background=c["surface"],
                    foreground=c["text"],
                    font=("Segoe UI", 10),
                    indicatorbackground=c["surface2"],
                    indicatorforeground=c["accent"],
                    indicatorcolor=c["accent"])

        # Progressbar style
        s.configure("Dark.Horizontal.TProgressbar",
                    background=c["accent"],
                    troughcolor=c["surface2"],
                    borderwidth=0,
                    thickness=8)

        # Map button states
        s.map("Accent.TButton",
              background=[("active", c["accent_hover"]), ("pressed", c["accent"])])
        s.map("Secondary.TButton",
              background=[("active", c["border"])])
        s.map("Dark.TRadiobutton",
              indicatorcolor=[("selected", c["accent"]), ("!selected", c["border"])])

    def setup_ui(self):
        c = self.colors

        # Root window - fixed height, scrollable content
        self.root.configure(bg=c["bg"])
        self.root.geometry("900x860")
        self.root.minsize(700, 600)

        # Canvas for scrollable content
        canvas_frame = tk.Frame(self.root, bg=c["bg"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas_frame.columnconfigure(0, weight=1)

        # Disable propagation so canvas fills available space
        canvas_frame.pack_propagate(False)

        self.canvas = tk.Canvas(canvas_frame, bg=c["bg"], bd=0, highlightthickness=0,
                                scrollregion=(0, 0, 880, 1400))
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Vertical scrollbar
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scroll
        def on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Content frame inside canvas
        main = tk.Frame(self.canvas, bg=c["bg"])
        self._canvas_window_id = self.canvas.create_window((0, 0), window=main, anchor=tk.NW)
        main.columnconfigure(0, weight=1)

        # Resize canvas width to match window, height to fit content
        def on_configure(event):
            w = self.canvas.winfo_width()
            # Get actual content height
            content_h = self.canvas.bbox("all")
            h = content_h[3] if content_h else 1400
            self.canvas.configure(scrollregion=(0, 0, w, h))
            self.canvas.itemconfigure(self._canvas_window_id, width=w)
        self.root.bind("<Configure>", on_configure)

        # ─── Title ───────────────────────────────────────────────────
        title_frame = tk.Frame(main, bg=c["bg"])
        title_frame.grid(row=0, column=0, sticky=tk.EW, padx=28, pady=(20, 4))
        title_frame.columnconfigure(0, weight=1)

        # Left: title text
        left = tk.Frame(title_frame, bg=c["bg"])
        left.pack(side=tk.LEFT)
        tk.Label(left, text="YouTube",
                 bg=c["bg"], fg=c["text"], font=("Segoe UI", 22, "bold"),
                 anchor=tk.W).pack(side=tk.LEFT)
        tk.Label(left, text="视频批量下载器",
                 bg=c["bg"], fg=c["text_secondary"], font=("Segoe UI", 22, "bold"),
                 anchor=tk.W).pack(side=tk.LEFT, padx=(4, 0))

        # Right: help buttons
        right = tk.Frame(title_frame, bg=c["bg"])
        right.pack(side=tk.RIGHT)

        self._make_doc_btn(right, "ffmpeg安装指南",
                           os.path.join("docs", "ffmpeg安装指南.md"))
        self._make_doc_btn(right, "使用说明",
                           os.path.join("docs", "视频链接使用说明.md"))

        # Accent line
        tk.Frame(main, bg=c["accent"], height=2).grid(
            row=1, column=0, sticky=tk.EW, padx=28, pady=(0, 16))

        # Track next available row (dynamic layout)
        self._next_row = 2

        # ─── Section 0: Channel Video Fetch ─────────────────────────
        self._make_section(main, "获取频道视频", [
            self._make_channel_row,
        ])

        # ─── Section DB: Database Browser ────────────────────────────
        self._make_section(main, "数据库管理", [
            self._make_db_browser_row,
        ])

        # ─── Section Monitor: Video Monitor ─────────────────────────
        tk.Label(main, text="视频监控", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 11, "bold"), anchor=tk.W).grid(
                     row=self._next_row, column=0, sticky=tk.W, padx=28, pady=(20, 6))
        self._next_row += 1

        # 启动 Web UI 按钮
        monitor_frame = tk.Frame(main, bg=c["bg"])
        monitor_frame.grid(row=self._next_row, column=0, sticky=tk.EW, padx=28, pady=(0, 6))
        self._next_row += 1

        def open_monitor_web():
            import threading, webbrowser, monitor.db as _mdb
            _mdb.init_db()
            # 检查是否已有服务在运行
            import urllib.request, urllib.error
            try:
                urllib.request.urlopen("http://127.0.0.1:18999/api/status", timeout=1)
            except (urllib.error.URLError, Exception):
                # 启动服务
                def start():
                    import monitor_server
                    monitor_server.serve(18999)
                t = threading.Thread(target=start, daemon=True)
                t.start()
                threading.Event().wait(0.8)
            webbrowser.open("http://127.0.0.1:18999")

        monitor_btn = tk.Label(
            monitor_frame, text="🌐 打开监控 Web UI",
            bg=c["accent"], fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=20, pady=10, cursor="hand2",
        )
        monitor_btn.pack(side=tk.LEFT)
        monitor_btn.bind("<Button-1>", lambda e: open_monitor_web())

        tk.Label(
            monitor_frame, text="现代浏览器界面，支持账户管理/通知配置/实时日志",
            bg=c["bg"], fg=c["text_muted"],
            font=("Segoe UI", 9),
            padx=12,
        ).pack(side=tk.LEFT, padx=(12, 0))

        # ─── Section 1: Download Settings ───────────────────────────
        self._make_section(main, "下载设置", [
            self._make_file_row,
            self._make_path_row,
        ])

        # ─── Section 2: Download Options ─────────────────────────────
        self._make_section(main, "下载选项", [
            self._make_resolution_row,
            self._make_count_row,
            self._make_subtitle_row,
            self._make_cookie_row,
        ])

        # ─── Section 2b: AI Clip Settings ────────────────────────────
        self._make_section(main, "AI 视频切片", [
            self._make_llm_provider_row,
            self._make_llm_min_score_row,
            self._make_llm_category_row,
        ])

        # ─── Section 3: URL List ────────────────────────────────────
        tk.Label(main, text="视频链接列表", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 11, "bold"),
                 anchor=tk.W).grid(row=self._next_row, column=0, sticky=tk.W, padx=28, pady=(20, 6))
        self._next_row += 1

        self.urls_frame = tk.Frame(main, bg=c["surface"], bd=1, relief=tk.FLAT,
                                   highlightbackground=c["border"], highlightthickness=1)
        self.urls_frame.grid(row=self._next_row, column=0, sticky=tk.EW, padx=28, pady=(0, 6))
        self._next_row += 1

        text_scroll_frame = tk.Frame(self.urls_frame, bg=c["surface"], bd=0)
        text_scroll_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.urls_text = tk.Text(text_scroll_frame,
                                 height=5,
                                 bg=c["surface2"],
                                 fg=c["text"],
                                 insertbackground=c["accent"],
                                 selectbackground=c["accent_dim"],
                                 font=("Cascadia Code", 9),
                                 relief=tk.FLAT, bd=0,
                                 padx=8, pady=6,
                                 wrap=tk.WORD,
                                 state="disabled")
        urls_scroll = ttk.Scrollbar(text_scroll_frame, orient="vertical",
                                     command=self.urls_text.yview)
        self.urls_text.configure(yscrollcommand=urls_scroll.set)
        self.urls_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        urls_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # URL count badge
        self.url_count_badge = tk.Label(main, text="0 个URL",
                                        bg=c["accent_dim"], fg=c["accent"],
                                        font=("Segoe UI", 9, "bold"),
                                        padx=8, pady=3, relief=tk.FLAT)
        self.url_count_badge.grid(row=self._next_row, column=0, sticky=tk.W, padx=28, pady=(0, 16))
        self._next_row += 1

        # ─── Section 4: Progress ───────────────────────────────────
        tk.Label(main, text="下载进度", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 11, "bold"),
                 anchor=tk.W).grid(row=self._next_row, column=0, sticky=tk.W, padx=28, pady=(0, 6))
        self._next_row += 1

        progress_frame = tk.Frame(main, bg=c["surface"], bd=1, relief=tk.FLAT,
                                  highlightbackground=c["border"], highlightthickness=1)
        progress_frame.grid(row=self._next_row, column=0, sticky=tk.EW, padx=28, pady=(0, 6))
        progress_frame.columnconfigure(0, weight=1)
        self._next_row += 1

        self.progress_status = tk.Label(progress_frame, text="等待中...",
                                        bg=c["surface"], fg=c["text_secondary"],
                                        font=("Segoe UI", 9), anchor=tk.W, padx=12, pady=6)
        self.progress_status.grid(row=0, column=0, sticky=tk.EW)

        self.progress_canvas = tk.Canvas(progress_frame, height=10,
                                          bg=c["surface2"], bd=0, highlightthickness=0)
        self.progress_canvas.grid(row=1, column=0, sticky=tk.EW, padx=12, pady=(0, 6))
        self._draw_progress_bar(0)
        progress_frame.bind("<Configure>", lambda e: self._draw_progress_bar(0))

        self.progress_percent = tk.Label(progress_frame, text="0%",
                                          bg=c["surface"], fg=c["text_secondary"],
                                          font=("Segoe UI", 9), anchor=tk.W, padx=12, pady=8)
        self.progress_percent.grid(row=2, column=0, sticky=tk.EW)

        # ─── Download Button ─────────────────────────────────────────
        btn_frame = tk.Frame(main, bg=c["bg"])
        btn_frame.grid(row=self._next_row, column=0, sticky=tk.EW, padx=28, pady=(16, 8))
        btn_frame.columnconfigure(0, weight=1)

        # Download button
        self.download_btn = tk.Label(btn_frame, text="开始下载",
                                     bg=c["accent"], fg="#ffffff",
                                     font=("Segoe UI", 12, "bold"),
                                     padx=40, pady=12, relief=tk.FLAT, cursor="hand2")
        self.download_btn.pack(side=tk.RIGHT)
        self.download_btn.bind("<Button-1>", lambda e: self.start_download())
        self.download_btn.bind("<Enter>", lambda e: self.download_btn.configure(bg=c["accent_hover"]))
        self.download_btn.bind("<Leave>", lambda e: self.download_btn.configure(bg=c["accent"]))

        # Reset scroll on mousewheel over canvas
        def on_canvas_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas.bind("<MouseWheel>", on_canvas_mousewheel)

        # Force update scrollregion after layout is complete
        main.update_idletasks()
        content_h = self.canvas.bbox("all")
        h = content_h[3] if content_h else 1400
        # Make window tall enough to show all content (scrollregion adjusts for scrolling)
        needed_h = h + 20
        current_h = self.root.winfo_height()
        if needed_h > current_h:
            self.root.geometry(f"900x{needed_h}")

    def _make_section(self, parent, title, row_makers):
        c = self.colors

        label = tk.Label(parent, text=title, bg=c["bg"], fg=c["text"],
                          font=("Segoe UI", 11, "bold"), anchor=tk.W)
        label.grid(row=self._next_row, column=0, sticky=tk.W, padx=28, pady=(20, 6))
        self._next_row += 1

        container = tk.Frame(parent, bg=c["surface"], bd=1, relief=tk.FLAT,
                             highlightbackground=c["border"], highlightthickness=1)
        container.grid(row=self._next_row, column=0, sticky=tk.EW, padx=28, pady=(0, 6))
        container.columnconfigure(1, weight=1)
        container.columnconfigure(2, weight=0)
        self._next_row += 1

        current_row = 0
        for maker in row_makers:
            step = maker(container, current_row)
            current_row += step if step else 1

    def _make_field_label(self, parent, row, text):
        c = self.colors
        label = tk.Label(parent, text=text, bg=c["surface"], fg=c["text_secondary"],
                         font=("Segoe UI", 10), anchor=tk.W, padx=12)
        label.grid(row=row, column=0, sticky=tk.W, pady=8)
        return label

    def _make_entry(self, parent, row, var):
        c = self.colors
        entry = tk.Entry(parent, textvariable=var, bg=c["surface2"], fg=c["text"],
                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                         font=("Segoe UI", 10), highlightthickness=1,
                         highlightbackground=c["border"],
                         selectbackground=c["accent_dim"], selectforeground=c["text"],
                         insertwidth=2)
        entry.grid(row=row, column=1, sticky=tk.EW, padx=(8, 12), pady=6)
        return entry

    def _make_browse_btn(self, parent, row, text, cmd):
        c = self.colors
        btn = tk.Label(parent, text=text, bg=c["surface2"], fg=c["text"],
                       font=("Segoe UI", 9), padx=12, pady=6,
                       relief=tk.FLAT, cursor="hand2", bd=1,
                       highlightbackground=c["border"], highlightthickness=1)
        btn.grid(row=row, column=2, padx=(8, 12), pady=6)
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.configure(bg=c["border"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=c["surface2"]))
        return btn

    def _make_file_row(self, parent, row):
        c = self.colors

        # Row 0: file type selector
        self._make_field_label(parent, row, "文件格式")
        type_frame = tk.Frame(parent, bg=c["surface"])
        type_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=6)

        self._make_type_toggle(type_frame, "Excel", "excel", 0)
        self._make_type_toggle(type_frame, "CSV", "csv", 1)
        self._make_type_toggle(type_frame, "TXT", "txt", 2)

        # Row 1: URL file path input
        self._make_field_label(parent, row + 1, "URL 文件")
        self._make_entry(parent, row + 1, self.url_file_path)
        self._make_browse_btn(parent, row + 1, "浏览", self.select_file)
        return 2

    def _make_type_toggle(self, parent, text, value, col):
        c = self.colors
        is_selected = (self.file_type.get() == value)

        btn = tk.Frame(parent, bg=c["accent"] if is_selected else c["border"],
                       relief=tk.FLAT, bd=0, padx=1, pady=1)
        btn.grid(row=0, column=col, padx=(0, 8))
        btn.columnconfigure(0, weight=1)
        btn.rowconfigure(0, weight=1)

        inner = tk.Frame(btn, bg=c["accent"] if is_selected else c["surface2"],
                         relief=tk.FLAT, bd=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        lbl = tk.Label(inner, text=text,
                       bg=c["accent"] if is_selected else c["surface2"],
                       fg="#ffffff" if is_selected else c["text"],
                       font=("Segoe UI", 10, "bold"), cursor="hand2")
        lbl.pack(padx=13, pady=5)
        # Bind click to the inner label (reliable inside Canvas)
        lbl.bind("<Button-1>", lambda e: self._select_type(value))
        # Also bind to the frame for full-area clicks
        btn.bind("<Button-1>", lambda e: self._select_type(value))
        inner.bind("<Button-1>", lambda e: self._select_type(value))

        setattr(self, f"_type_btn_{value}", (btn, inner, lbl))
        self.file_type.trace_add("write", lambda *a, bv=value, bi=(btn, inner, lbl):
                                  self._update_type_toggle_ui(bv, bi))

    def _select_type(self, value):
        self.file_type.set(value)

    def _update_type_toggle_ui(self, value, widgets):
        c = self.colors
        btn, inner, lbl = widgets
        selected = (self.file_type.get() == value)
        bg = c["accent"] if selected else c["surface2"]
        fg = "#ffffff" if selected else c["text"]
        border = c["accent"] if selected else c["border"]
        btn.configure(bg=border)
        inner.configure(bg=bg)
        lbl.configure(bg=bg, fg=fg)

    def _make_path_row(self, parent, row):
        self._make_field_label(parent, row, "保存路径")
        self._make_entry(parent, row, self.save_path)
        self._make_browse_btn(parent, row, "浏览", self.select_save_path)
        return 1

    def _make_proxy_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "代理")
        proxy_frame = tk.Frame(parent, bg=c["surface"])
        proxy_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        # 单个代理地址 + 保存
        self.proxy = tk.StringVar(value=self.saved_proxy)
        entry = tk.Entry(proxy_frame, textvariable=self.proxy,
                         bg=c["surface2"], fg=c["text"],
                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                         font=("Segoe UI", 10),
                         highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        entry.pack(side=tk.LEFT)

        btn = tk.Label(proxy_frame, text="保存", bg=c["surface2"], fg=c["accent"],
                       font=("Segoe UI", 9, "bold"), padx=10, pady=5,
                       relief=tk.FLAT, cursor="hand2", bd=1,
                       highlightbackground=c["accent"], highlightthickness=1)
        btn.pack(side=tk.LEFT, padx=(8, 0))
        btn.bind("<Button-1>", lambda e: self.save_proxy())
        btn.bind("<Enter>", lambda e: btn.configure(bg=c["accent_dim"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=c["surface2"]))

        # 代理池文件
        hint = tk.Label(proxy_frame, text="代理池:", bg=c["surface"], fg=c["text_muted"],
                        font=("Segoe UI", 9), padx=16)
        hint.pack(side=tk.LEFT)
        self.proxy_file_entry = tk.Entry(proxy_frame, textvariable=self.proxy_file_path,
                                         bg=c["surface2"], fg=c["text"],
                                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                                         font=("Segoe UI", 10), width=20,
                                         highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        self.proxy_file_entry.pack(side=tk.LEFT, padx=(0, 4))

        def browse_proxy_file():
            filename = filedialog.askopenfilename(filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
            if filename:
                self.proxy_file_path.set(filename)
        fb = tk.Label(proxy_frame, text="浏览", bg=c["surface2"], fg=c["text"],
                      font=("Segoe UI", 9), padx=8, pady=5,
                      relief=tk.FLAT, cursor="hand2", bd=1,
                      highlightbackground=c["border"], highlightthickness=1)
        fb.pack(side=tk.LEFT)
        fb.bind("<Button-1>", lambda e: browse_proxy_file())
        fb.bind("<Enter>", lambda e: fb.configure(bg=c["border"]))
        fb.bind("<Leave>", lambda e: fb.configure(bg=c["surface2"]))
        return 1

    def _make_resolution_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "视频画质")
        self.best_quality = tk.BooleanVar(value=True)

        options_frame = tk.Frame(parent, bg=c["surface"])
        options_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=6)

        # 最高画质开关：勾选 = 自动下载最高画质视频
        cb = tk.Checkbutton(
            options_frame,
            text="最高画质（自动选择最高分辨率）",
            variable=self.best_quality,
            bg=c["surface"],
            fg=c["accent"],
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            activebackground=c["surface"],
            activeforeground=c["accent"],
            selectcolor=c["accent_dim"],
        )
        cb.grid(row=0, column=0, padx=(0, 8), sticky=tk.W)
        return 1

    def _make_channel_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "频道 URL")

        channel_frame = tk.Frame(parent, bg=c["surface"])
        channel_frame.grid(row=row, column=1, columnspan=2, sticky=tk.EW, padx=(8, 12), pady=6)

        # URL 输入 + 获取按钮
        top_row = tk.Frame(channel_frame, bg=c["surface"])
        top_row.pack(fill=tk.X)

        self.channel_url = tk.StringVar()
        entry = tk.Entry(top_row, textvariable=self.channel_url,
                          bg=c["surface2"], fg=c["text"],
                          insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                          font=("Segoe UI", 10),
                          highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        # 获取前 N 条
        n_frame = tk.Frame(top_row, bg=c["surface"])
        n_frame.pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(n_frame, text="前", bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.fetch_max_videos = tk.Spinbox(n_frame, from_=0, to=9999, width=5,
                                           bg=c["surface2"], fg=c["text"],
                                           buttonbackground=c["surface"],
                                           font=("Segoe UI", 9),
                                           relief=tk.FLAT, bd=0,
                                           highlightbackground=c["border"],
                                           highlightthickness=1)
        self.fetch_max_videos.pack(side=tk.LEFT, padx=2)
        tk.Label(n_frame, text="条（0=全部）", bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)

        fetch_btn = tk.Label(top_row, text="获取视频", bg=c["accent"], fg=c["accent_dim"],
                             font=("Segoe UI", 9, "bold"), padx=12, pady=5,
                             relief=tk.FLAT, cursor="hand2", bd=0)
        fetch_btn.pack(side=tk.LEFT)
        fetch_btn.bind("<Button-1>", lambda e: self.fetch_channel_videos())
        fetch_btn.bind("<Enter>", lambda e: fetch_btn.configure(bg=c["accent_hover"]))
        fetch_btn.bind("<Leave>", lambda e: fetch_btn.configure(bg=c["accent"]))

        hint = tk.Label(top_row, text="（支持 @频道名 或完整频道 URL）",
                        bg=c["surface"], fg=c["text_muted"], font=("Segoe UI", 8))
        hint.pack(side=tk.LEFT, padx=(8, 0))

        # 存储格式选择
        bottom_row = tk.Frame(channel_frame, bg=c["surface"])
        bottom_row.pack(fill=tk.X, pady=(4, 0))

        fmt_lbl = tk.Label(bottom_row, text="保存格式:",
                            bg=c["surface"], fg=c["text_muted"], font=("Segoe UI", 8))
        fmt_lbl.pack(side=tk.LEFT)

        self.storage_format = tk.StringVar(value="sqlite")
        for val, lbl_text in [("csv", "CSV（不含上传日期）"), ("sqlite", "SQLite（自动补全上传日期）")]:
            b = tk.Radiobutton(bottom_row, text=lbl_text, variable=self.storage_format,
                               value=val, bg=c["surface"], fg=c["text"],
                               selectcolor=c["accent"], activebackground=c["surface"],
                               font=("Segoe UI", 8), cursor="hand2")
            b.pack(side=tk.LEFT, padx=(4, 8))

        note_lbl = tk.Label(bottom_row, text="★ SQLite 可后台增量获取上传日期，下载时自动填充",
                             bg=c["surface"], fg=c["accent"], font=("Segoe UI", 7))
        note_lbl.pack(side=tk.LEFT)
        return 1

    def fetch_channel_videos(self):
        channel_url = self.channel_url.get().strip()
        if not channel_url:
            messagebox.showwarning("提示", "请输入频道 URL")
            return

        save_dir = self.save_path.get().strip()
        if not save_dir or not os.path.isdir(save_dir):
            save_dir = os.getcwd()

        storage_fmt = self.storage_format.get()   # 'csv' or 'sqlite'
        try:
            max_videos = int(self.fetch_max_videos.get()) or None
        except ValueError:
            max_videos = None
        db_path_ref = [None]   # mutable container for Phase2 callback

        def do_fetch():
            try:
                print(f"正在获取频道视频: {channel_url}")
                videos, storage_path, _ = _fetch_channel_videos(
                    channel_url,
                    max_videos=max_videos,
                    save_format=storage_fmt,
                    save_dir=save_dir,
                    background_update=(storage_fmt == 'sqlite'),
                    progress_callback=None,
                )
                if not videos:
                    self.root.after(0, lambda: (
                        self._dismiss_loading(),
                        messagebox.showerror("错误", "未获取到任何视频\n请检查频道 URL 是否正确")
                    ))
                    return

                db_path_ref[0] = storage_path

                if storage_fmt == 'sqlite':
                    urls = [v['URL'] for v in videos]
                    count = len(videos)
                    limit_info = f"（设置: 前 {max_videos} 条）" if max_videos else "（设置: 全部）"
                    self.root.after(0, lambda u=urls, c=count, path=storage_path, li=limit_info: (
                        self._dismiss_loading(),
                        self.urls.__setitem__(slice(None), u),
                        self.url_file_path.set(path),
                        self.file_type.set("sqlite"),
                        self.max_videos_label.configure(text=f"最多 {c} 个视频"),
                        self.url_count_badge.configure(text=f"{c} 个URL"),
                        self.update_urls_display(),
                        messagebox.showinfo(
                            "成功",
                            f"Phase1 完成: {c} 个视频已写入 SQLite {li}\n"
                            f"文件: {path}\n\n"
                            f"Phase2 上传日期正在后台获取...\n"
                            f"完成后可在数据库中查看完整数据"
                        )
                    ))
                else:
                    export_to_csv(videos, storage_path)
                    urls = [v['URL'] for v in videos]
                    count = len(videos)
                    limit_info = f"（设置: 前 {max_videos} 条）" if max_videos else "（设置: 全部）"
                    self.root.after(0, lambda u=urls, c=count, path=storage_path, li=limit_info: (
                        self._dismiss_loading(),
                        self.urls.__setitem__(slice(None), u),
                        self.url_file_path.set(path),
                        self.file_type.set("csv"),
                        self.max_videos_label.configure(text=f"最多 {c} 个视频"),
                        self.url_count_badge.configure(text=f"{c} 个URL"),
                        self.update_urls_display(),
                        messagebox.showinfo("成功",
                            f"已获取 {c} 个视频 {li}\n已保存到:\n{path}\n\n"
                            f"注: CSV 格式不包含上传日期\n如需上传日期请选择 SQLite 格式")
                    ))
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self.root.after(0, lambda: (
                    self._dismiss_loading(),
                    messagebox.showerror("错误", f"获取失败: {ex}")
                ))

        self._show_loading()
        Thread(target=do_fetch, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════
    #  数据库浏览器
    # ═══════════════════════════════════════════════════════════════

    def _make_db_browser_row(self, parent, row):
        c = self.colors

        # ── DB file selector ──────────────────────────────────────
        selector = tk.Frame(parent, bg=c["surface"])
        selector.grid(row=row, column=1, columnspan=2, sticky=tk.EW, padx=(8, 12), pady=(6, 4))

        tk.Label(selector, text="数据库文件:",
                  bg=c["surface"], fg=c["text_secondary"],
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self.db_path_var = tk.StringVar()

        db_entry = tk.Entry(selector, textvariable=self.db_path_var,
                              bg=c["surface2"], fg=c["text"],
                              insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                              font=("Segoe UI", 9),
                              highlightbackground=c["border"],
                              highlightthickness=1, insertwidth=2)
        db_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 6))

        def open_db():
            fn = filedialog.askopenfilename(
                title="选择 SQLite 数据库",
                filetypes=[("SQLite 数据库", "*.db *.sqlite *.sqlite3"), ("所有文件", "*.*")],
                initialdir=self.save_path.get() or os.getcwd())
            if fn:
                self.db_path_var.set(fn)
                self._load_db_browser(fn)

        btn = tk.Label(selector, text="打开",
                        bg=c["accent"], fg=c["accent_dim"],
                        font=("Segoe UI", 9, "bold"),
                        padx=10, pady=3, relief=tk.FLAT,
                        cursor="hand2", bd=0)
        btn.pack(side=tk.LEFT)
        btn.bind("<Button-1>", lambda e: open_db())
        btn.bind("<Enter>", lambda e: btn.configure(bg=c["accent_hover"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=c["accent"]))

        tk.Label(selector, text="★ 选择数据库后可筛选、选择并下载视频",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(8, 0))
        return 1 + self._build_db_browser_widgets(parent, row + 1)

    def _build_db_browser_widgets(self, parent, base_row):
        """Build the database browser widgets below the selector."""
        c = self.colors

        # ── Stats dashboard ───────────────────────────────────────
        stats = tk.Frame(parent, bg=c["surface"])
        stats.grid(row=base_row, column=1, columnspan=2,
                   sticky=tk.EW, padx=(8, 12), pady=(0, 4))

        self._db_stat_labels = {}
        stat_defs = [
            ("total",     "视频总数",      c["text"]),
            ("full",       "完整数据",      c["success"]),
            ("partial",    "待补全",        c["warning"]),
            ("pending",    "待下载",        c["accent"]),
            ("completed",  "已下载",        c["success"]),
            ("failed",     "下载失败",      c["error"]),
        ]
        for i, (key, label, color) in enumerate(stat_defs):
            tile = tk.Frame(stats, bg=c["surface2"],
                              highlightbackground=c["border"],
                              highlightthickness=1)
            tile.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4 if i < len(stat_defs)-1 else 0))
            val_lbl = tk.Label(tile, text="—",
                                  bg=c["surface2"], fg=color,
                                  font=("Segoe UI", 14, "bold"))
            val_lbl.pack(pady=(8, 0))
            lbl_lbl = tk.Label(tile, text=label,
                                  bg=c["surface2"], fg=c["text_muted"],
                                  font=("Segoe UI", 7))
            lbl_lbl.pack(pady=(0, 6))
            self._db_stat_labels[key] = val_lbl

        # ── Filter row ─────────────────────────────────────────────
        filt = tk.Frame(parent, bg=c["surface"])
        filt.grid(row=base_row + 1, column=1, columnspan=2,
                  sticky=tk.EW, padx=(8, 12), pady=(0, 4))

        # Title search
        tk.Label(filt, text="标题:",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._db_search_var = tk.StringVar()
        search_ent = tk.Entry(filt, textvariable=self._db_search_var,
                                bg=c["surface2"], fg=c["text"],
                                insertbackground=c["accent"],
                                relief=tk.FLAT, bd=0,
                                font=("Segoe UI", 8),
                                highlightbackground=c["border"],
                                highlightthickness=1, insertwidth=2,
                                width=14)
        search_ent.pack(side=tk.LEFT, padx=(4, 10))
        search_ent.bind("<Return>", lambda e: apply_filter())

        # Date range
        tk.Label(filt, text="日期:",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._db_date_from = tk.Entry(filt, bg=c["surface2"], fg=c["text"],
                                        insertbackground=c["accent"],
                                        relief=tk.FLAT, bd=0,
                                        font=("Segoe UI", 8),
                                        highlightbackground=c["border"],
                                        highlightthickness=1, insertwidth=2,
                                        width=9)
        self._db_date_from.insert(0, "从")
        self._db_date_from.pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(filt, text="—",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._db_date_to = tk.Entry(filt, bg=c["surface2"], fg=c["text"],
                                      insertbackground=c["accent"],
                                      relief=tk.FLAT, bd=0,
                                      font=("Segoe UI", 8),
                                      highlightbackground=c["border"],
                                      highlightthickness=1, insertwidth=2,
                                      width=9)
        self._db_date_to.insert(0, "至")
        self._db_date_to.pack(side=tk.LEFT, padx=(2, 10))

        # Channel filter (Combobox, populated on DB load)
        tk.Label(filt, text="频道:",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._db_channel_var = tk.StringVar(value="全部")
        self._db_channel_combo = ttk.Combobox(
            filt, textvariable=self._db_channel_var,
            state="readonly", font=("Segoe UI", 8),
            width=12, values=["全部"])
        self._db_channel_combo.pack(side=tk.LEFT, padx=(4, 8))

        # View count range
        tk.Label(filt, text="播放量:",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._db_views_min = tk.Entry(filt, bg=c["surface2"], fg=c["text"],
                                        insertbackground=c["accent"],
                                        relief=tk.FLAT, bd=0,
                                        font=("Segoe UI", 8),
                                        highlightbackground=c["border"],
                                        highlightthickness=1, insertwidth=2,
                                        width=7)
        self._db_views_min.insert(0, "≥")
        self._db_views_min.pack(side=tk.LEFT, padx=(4, 2))

        # Freshness filter
        self._db_fresh_var = tk.StringVar(value="all")
        for val, lbl in [("all", "全部"), ("full", "完整"), ("partial", "待补全")]:
            tk.Radiobutton(filt, text=lbl, variable=self._db_fresh_var,
                            value=val, bg=c["surface"], fg=c["text_muted"],
                            selectcolor=c["accent"], activebackground=c["surface"],
                            font=("Segoe UI", 7), cursor="hand2").pack(side=tk.LEFT, padx=(0, 2))

        # Status filter
        self._db_status_var = tk.StringVar(value="all")
        status_frame = tk.Frame(filt, bg=c["surface"])
        status_frame.pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(status_frame, text="状态:",
                  bg=c["surface"], fg=c["text_muted"],
                  font=("Segoe UI", 8)).pack(side=tk.LEFT)
        for val, lbl in [("all", "全部"), ("pending", "待下"), ("completed", "已下")]:
            tk.Radiobutton(status_frame, text=lbl, variable=self._db_status_var,
                              value=val, bg=c["surface"], fg=c["text_muted"],
                              selectcolor=c["accent"], activebackground=c["surface"],
                              font=("Segoe UI", 7), cursor="hand2").pack(side=tk.LEFT, padx=(0, 2))

        # Apply filter button
        def apply_filter():
            if hasattr(self, '_current_db') and self._current_db:
                self._query_and_display_videos()

        tk.Label(filt, text="",
                  bg=c["surface"]).pack(side=tk.LEFT, expand=True, fill=tk.X)

        go_btn = tk.Label(filt, text="查询",
                           bg=c["accent"], fg=c["accent_dim"],
                           font=("Segoe UI", 8, "bold"),
                           padx=8, pady=2, relief=tk.FLAT,
                           cursor="hand2", bd=0)
        go_btn.pack(side=tk.LEFT)
        go_btn.bind("<Button-1>", lambda e: apply_filter())
        go_btn.bind("<Enter>", lambda e: go_btn.configure(bg=c["accent_hover"]))
        go_btn.bind("<Leave>", lambda e: go_btn.configure(bg=c["accent"]))

        # ── Video table ─────────────────────────────────────────────
        table_frame = tk.Frame(parent, bg=c["surface"],
                                 highlightbackground=c["border"],
                                 highlightthickness=1)
        table_frame.grid(row=base_row + 2, column=1, columnspan=2,
                          sticky=tk.EW, padx=(8, 12), pady=(0, 4))

        # Treeview column definitions
        cols = [("sel",  4,  ""),
                ("num",   4,  "#"),
                ("title", 28, "标题"),
                ("date",  11, "上传日期"),
                ("dur",    7, "时长"),
                ("views",  9, "播放量"),
                ("fresh",  7, "数据状态"),
                ("status", 8, "下载状态")]
        col_ids   = [x[0] for x in cols]
        col_widths = {x[0]: x[1] for x in cols}
        col_heads  = {x[0]: x[2] for x in cols}

        # Style the treeview
        style = ttk.Style()
        style.configure("DB.Treeview",
                        background=c["surface"],
                        foreground=c["text"],
                        fieldbackground=c["surface"],
                        rowheight=24,
                        font=("Segoe UI", 8))
        style.configure("DB.Treeview.Heading",
                        background=c["surface2"],
                        foreground=c["text_secondary"],
                        font=("Segoe UI", 8, "bold"),
                        relief=tk.FLAT)
        style.map("DB.Treeview",
                  background=[("selected", c["accent_dim"])],
                  foreground=[("selected", c["accent"])])

        tree_y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        tree_y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        tree_x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        tree_x_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self._db_tree = ttk.Treeview(table_frame,
                                       columns=col_ids,    # all cols including 'sel'
                                       show="headings",
                                       style="DB.Treeview",
                                       yscrollcommand=tree_y_scroll.set,
                                       xscrollcommand=tree_x_scroll.set,
                                       height=8)
        self._db_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_y_scroll.configure(command=self._db_tree.yview)
        tree_x_scroll.configure(command=self._db_tree.xview)

        # sel column: checkbox header → toggle current page; cell → toggle single row
        self._db_tree.heading("sel", text="☐",
                                command=self._toggle_page_select)
        self._db_tree.column("sel", width=30, minwidth=30, anchor=tk.CENTER)

        # Other columns: show heading + sort on click
        for col in col_ids[1:]:  # skip "sel"
            self._db_tree.heading(col, text=col_heads[col],
                                    command=lambda c=col: self._sort_tree(c))
            self._db_tree.column(col, width=col_widths[col] * 7,
                                   minwidth=30, anchor=tk.CENTER)

        # Selection tracking
        self._db_checked = {}    # url -> checked bool
        self._db_all_ids = []    # all loaded urls
        self._db_item_url = {}   # item_id -> url  (for checkbox click resolution)
        self._db_page_urls = []  # urls on current page (for header checkbox)
        self._db_sort_col = None
        self._db_sort_rev = True

        # Click on 'sel' column to toggle checkbox
        self._db_tree.bind("<Button-1>", self._on_tree_click)

        # ── Action bar ──────────────────────────────────────────────
        actions = tk.Frame(parent, bg=c["surface"])
        actions.grid(row=base_row + 3, column=1, columnspan=2,
                     sticky=tk.EW, padx=(8, 12), pady=(0, 4))

        # Left: selection controls
        tk.Button(actions, text="全选",
                  bg=c["surface2"], fg=c["text"],
                  activebackground=c["accent"], activeforeground=c["surface"],
                  relief=tk.FLAT, font=("Segoe UI", 8),
                  command=self._toggle_all_select).pack(side=tk.LEFT)
        tk.Button(actions, text="反选",
                  bg=c["surface2"], fg=c["text"],
                  activebackground=c["accent"], activeforeground=c["surface"],
                  relief=tk.FLAT, font=("Segoe UI", 8),
                  command=self._invert_selection).pack(side=tk.LEFT, padx=(4, 0))

        self._db_selected_count = tk.Label(actions, text="已选 0 个",
                                              bg=c["surface"], fg=c["text_muted"],
                                              font=("Segoe UI", 8))
        self._db_selected_count.pack(side=tk.LEFT, padx=(12, 0))

        # Pagination
        self._db_page_label = tk.Label(actions, text="第 1 页",
                                          bg=c["surface"], fg=c["text_muted"],
                                          font=("Segoe UI", 8))
        self._db_page_label.pack(side=tk.LEFT, padx=(12, 0))

        def _prev_page():
            pg = getattr(self, '_db_page', 1)
            if pg > 1:
                self._db_page = pg - 1
                self._display_page()
        def _next_page():
            pg = getattr(self, '_db_page', 1)
            total = getattr(self, '_db_total_pages', 1)
            if pg < total:
                self._db_page = pg + 1
                self._display_page()

        for lbl_txt, cmd in [("◀ 上一页", _prev_page), ("下一页 ▶", _next_page)]:
            b = tk.Label(actions, text=lbl_txt,
                          bg=c["surface2"], fg=c["text"],
                          font=("Segoe UI", 7),
                          padx=6, pady=2,
                          relief=tk.FLAT, cursor="hand2")
            b.pack(side=tk.LEFT, padx=(4, 0))
            real_cmd = _prev_page if "上一页" in lbl_txt else _next_page
            b.bind("<Button-1>", lambda e, c=real_cmd: c())
            b.bind("<Enter>", lambda e, b=b: b.configure(bg=c["border"]))
            b.bind("<Leave>", lambda e, b=b: b.configure(bg=c["surface2"]))

        # Right: action buttons
        tk.Frame(actions, bg=c["surface"]).pack(side=tk.LEFT, expand=True)

        # Export CSV
        exp_btn = tk.Label(actions, text="导出 CSV",
                            bg=c["surface2"], fg=c["text"],
                            font=("Segoe UI", 8),
                            padx=10, pady=3,
                            relief=tk.FLAT, cursor="hand2",
                            highlightbackground=c["border"],
                            highlightthickness=1)
        exp_btn.pack(side=tk.RIGHT, padx=(4, 0))
        exp_btn.bind("<Button-1>", lambda e: self._db_export_csv())
        exp_btn.bind("<Enter>", lambda e: exp_btn.configure(bg=c["border"]))
        exp_btn.bind("<Leave>", lambda e: exp_btn.configure(bg=c["surface2"]))

        # Fill upload dates (background)
        fill_btn = tk.Label(actions, text="补全上传日期",
                              bg=c["warning"], fg="#1a1200",
                              font=("Segoe UI", 8, "bold"),
                              padx=8, pady=3,
                              relief=tk.FLAT, cursor="hand2")
        fill_btn.pack(side=tk.RIGHT, padx=(4, 0))
        fill_btn.bind("<Button-1>", lambda e: self._db_fill_upload_dates())
        fill_btn.bind("<Enter>", lambda e: fill_btn.configure(bg="#e8a800"))
        fill_btn.bind("<Leave>", lambda e: fill_btn.configure(bg=self.colors["warning"]))

        # Download selected
        dl_btn = tk.Label(actions, text="下载所选",
                            bg=c["accent"], fg=c["accent_dim"],
                            font=("Segoe UI", 8, "bold"),
                            padx=10, pady=3,
                            relief=tk.FLAT, cursor="hand2")
        dl_btn.pack(side=tk.RIGHT)
        dl_btn.bind("<Button-1>", lambda e: self._db_download_selected())
        dl_btn.bind("<Enter>", lambda e: dl_btn.configure(bg=c["accent_hover"]))
        dl_btn.bind("<Leave>", lambda e: dl_btn.configure(bg=c["accent"]))

        return 4   # consumed 4 rows

    def _load_db_browser(self, db_path):
        """Load a SQLite database and display stats."""
        import sqlite3
        c = self.colors
        try:
            conn = sqlite3.connect(db_path)
            total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            full_ct = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE data_freshness='full'").fetchone()[0]
            partial_ct = total - full_ct
            pending_ct = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE download_status='pending'").fetchone()[0]
            done_ct = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE download_status='completed'").fetchone()[0]
            fail_ct = conn.execute(
                "SELECT COUNT(*) FROM videos WHERE download_status='failed'").fetchone()[0]
            # Populate channel filter
            channels = conn.execute(
                "SELECT DISTINCT channel_handle FROM videos WHERE channel_handle IS NOT NULL AND channel_handle!='' ORDER BY channel_handle"
            ).fetchall()
            conn.close()
        except Exception as ex:
            messagebox.showerror("错误", f"无法打开数据库:\n{ex}")
            return

        self._current_db = db_path
        self._db_all_data = []   # all filtered rows
        self._db_checked = {}
        self._db_page = 1
        self._db_page_size = 50

        # Populate channel combobox
        channel_list = ["全部"] + [ch[0] for ch in channels]
        self._db_channel_combo.configure(values=channel_list)
        self._db_channel_var.set("全部")

        # Update stat tiles
        stats = self._db_stat_labels
        stats["total"].configure(text=str(total))
        stats["full"].configure(text=str(full_ct))
        stats["partial"].configure(text=str(partial_ct))
        stats["pending"].configure(text=str(pending_ct))
        stats["completed"].configure(text=str(done_ct))
        stats["failed"].configure(text=str(fail_ct))
        _log.info(f"DB打开: 路径={db_path} 总={total} 完整={full_ct} 待补={partial_ct} 待下={pending_ct} 已下={done_ct} 失败={fail_ct}")

        # Clear table
        for item in self._db_tree.get_children():
            self._db_tree.delete(item)

        # Load first page
        self._query_and_display_videos()

    def _query_and_display_videos(self):
        """Query database with current filters and display first page."""
        import sqlite3
        db_path = getattr(self, '_current_db', None)
        if not db_path:
            return

        # Build query
        search = self._db_search_var.get().strip()
        date_from = self._db_date_from.get().strip()
        date_to = self._db_date_to.get().strip()
        views_min = self._db_views_min.get().strip()
        freshness = self._db_fresh_var.get()
        status = self._db_status_var.get()
        channel = self._db_channel_var.get().strip()

        where = []
        params = []

        if channel and channel != "全部":
            where.append("channel_handle = ?")
            params.append(channel)

        if search:
            where.append("title LIKE ? COLLATE NOCASE")
            params.append(f"%{search}%")
        if date_from and date_from not in ("从", ""):
            where.append("upload_date >= ?")
            params.append(date_from)
        if date_to and date_to not in ("至", ""):
            where.append("upload_date <= ?")
            params.append(date_to)
        if views_min and views_min not in ("≥", ""):
            try:
                where.append("view_count >= ?")
                params.append(int(views_min))
            except ValueError:
                pass
        if freshness == "full":
            where.append("data_freshness='full'")
        elif freshness == "partial":
            where.append("data_freshness='partial'")
        if status == "pending":
            where.append("download_status='pending'")
        elif status == "completed":
            where.append("download_status='completed'")

        sql = "SELECT url, title, upload_date, duration_sec, view_count, data_freshness, download_status FROM videos"
        if where:
            sql += " WHERE " + " AND ".join(where)

        # Respect current sort setting
        sort_col = getattr(self, '_db_sort_col', None)
        sort_rev = getattr(self, '_db_sort_rev', True)
        sql_order = "upload_date"   # default
        if sort_col == "views":
            sql_order = "view_count"
        elif sort_col == "title":
            sql_order = "title"
        elif sort_col == "date":
            sql_order = "upload_date"
        elif sort_col == "dur":
            sql_order = "duration_sec"
        elif sort_col == "status":
            sql_order = "download_status"
        elif sort_col == "fresh":
            sql_order = "data_freshness"
        sql += f" ORDER BY {sql_order} {'DESC' if sort_rev else 'ASC'} LIMIT 10000"

        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as ex:
            messagebox.showerror("查询错误", str(ex))
            _log.error(f"DB查询失败: {ex} SQL={sql[:100]}")
            return

        self._db_all_data = rows
        self._db_all_ids = [r[0] for r in rows]
        self._db_checked = {}
        self._db_page = 1
        self._db_total_pages = max(1, (len(rows) + self._db_page_size - 1) // self._db_page_size)
        _log.info(f"DB查询: 命中={len(rows)} 频道={channel} 日期={date_from}~{date_to}")
        self._display_page()

    def _display_page(self):
        """Display current page of videos in treeview."""
        c = self.colors
        pg = getattr(self, '_db_page', 1)
        size = getattr(self, '_db_page_size', 50)
        total = len(getattr(self, '_db_all_data', []))

        self._db_page_label.configure(text=f"第 {pg} 页 / 共 {getattr(self, '_db_total_pages', 1)} 页  ({total} 条)")

        # Clear
        for item in self._db_tree.get_children():
            self._db_tree.delete(item)

        start = (pg - 1) * size
        end = start + size
        page_rows = getattr(self, '_db_all_data', [])[start:end]

        # Clear item->url map
        self._db_item_url = {}
        page_urls = []

        for i, row in enumerate(page_rows):
            url, title, upload_date, duration, views, freshness, status = row
            checked = self._db_checked.get(url, False)
            page_urls.append(url)

            # Format duration
            if duration:
                dm = int(duration)
                fmt = f"{dm//60}:{dm%60:02d}"
            else:
                fmt = "—"

            # Format views
            vfmt = f"{views:,}" if views else "—"

            # Freshness label
            if freshness == "full":
                fresh_txt = "●完整"
                fresh_color = c["success"]
            else:
                fresh_txt = "○待补"
                fresh_color = c["warning"]

            # Status label
            status_map = {
                "pending":    ("○待下", c["text_muted"]),
                "completed":  ("●完成", c["success"]),
                "downloading":("◐下载", c["accent"]),
                "failed":     ("✗失败", c["error"]),
            }
            st_lbl, st_color = status_map.get(status, (status, c["text_muted"]))

            # Truncate title
            title_short = (title or "—")[:50]

            values = [
                "☑" if checked else "☐",
                str(start + i + 1),
                title_short,
                upload_date or "—",
                fmt,
                vfmt,
                fresh_txt,
                st_lbl,
            ]

            if checked:
                item_id = self._db_tree.insert("", tk.END, values=values, tags=("checked",))
            else:
                item_id = self._db_tree.insert("", tk.END, values=values)
            self._db_item_url[item_id] = url

        self._db_page_urls = page_urls
        # Update sel column header: ☑ if all page rows checked, ☐ otherwise
        if page_urls:
            all_checked = all(self._db_checked.get(u, False) for u in page_urls)
            self._db_tree.heading("sel", text="☑" if all_checked else "☐")
        self._update_selected_count()

    def _sort_tree(self, col):
        """Update sort state and re-query with SQL ORDER BY (DB-side sort = all rows)."""
        rev = getattr(self, '_db_sort_rev', True)
        if getattr(self, '_db_sort_col', None) == col:
            rev = not rev
        else:
            rev = True
        self._db_sort_col = col
        self._db_sort_rev = rev
        # Re-query so SQL ORDER BY applies to all matching rows (not just in-memory sort)
        self._query_and_display_videos()

    def _toggle_all_select(self):
        """Toggle select all loaded rows (all data, not just current page)."""
        all_urls = getattr(self, '_db_all_ids', [])
        if not all_urls:
            return
        # If all checked → uncheck all; else → check all
        all_checked = all(self._db_checked.get(u, False) for u in all_urls)
        new_state = not all_checked
        for url in all_urls:
            self._db_checked[url] = new_state
        # Refresh display without resetting page
        self._display_page()
        self._update_selected_count()

    def _toggle_page_select(self):
        """Toggle select all rows on current page (via sel column header)."""
        page_urls = getattr(self, '_db_page_urls', [])
        if not page_urls:
            return
        all_checked = all(self._db_checked.get(u, False) for u in page_urls)
        new_state = not all_checked
        for url in page_urls:
            self._db_checked[url] = new_state
        self._display_page()
        self._update_selected_count()

    def _invert_selection(self):
        """Invert selection for all rows on current page."""
        page_urls = getattr(self, '_db_page_urls', [])
        for url in page_urls:
            self._db_checked[url] = not self._db_checked.get(url, False)
        self._display_page()
        self._update_selected_count()

    def _on_tree_click(self, event):
        """Handle click on 'sel' column: toggle row checkbox, update header state."""
        region = self._db_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col_id = self._db_tree.identify_column(event.x)   # returns "#N"
        if col_id != "#1":
            return
        item = self._db_tree.identify_row(event.y)
        if not item:
            return
        url = self._db_item_url.get(item)
        if not url:
            return
        current = self._db_checked.get(url, False)
        self._db_checked[url] = not current
        self._update_selected_count()
        # Update checkbox display
        new_values = list(self._db_tree.item(item, "values"))
        new_values[0] = "☑" if not current else "☐"
        tags = ("checked",) if not current else ()
        self._db_tree.item(item, values=new_values, tags=tags)
        # Update sel column header
        page_urls = getattr(self, '_db_page_urls', [])
        if page_urls:
            all_checked = all(self._db_checked.get(u, False) for u in page_urls)
            self._db_tree.heading("sel", text="☑" if all_checked else "☐")

    def _toggle_select_all(self):
        """Backward compat: delegate to _toggle_all_select."""
        self._toggle_all_select()

    def _update_selected_count(self):
        total = len(getattr(self, '_db_all_ids', []))
        selected = sum(1 for u in getattr(self, '_db_all_ids', []) if self._db_checked.get(u, False))
        self._db_selected_count.configure(text=f"已选 {selected}/{total} 个")

    def _db_export_csv(self):
        """Export filtered results to CSV."""
        import sqlite3, csv
        db_path = getattr(self, '_current_db', None)
        if not db_path:
            messagebox.showwarning("提示", "请先打开数据库文件")
            return

        checked_urls = [u for u, c in getattr(self, '_db_checked', {}).items() if c]
        if not checked_urls:
            messagebox.showwarning("提示", "请先在列表中勾选要导出的视频")
            return

        fn = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialdir=self.save_path.get() or os.getcwd())
        if not fn:
            return

        try:
            conn = sqlite3.connect(db_path)
            placeholders = ",".join("?" * len(checked_urls))
            rows = conn.execute(
                f"""SELECT title, url, upload_date, duration_sec, view_count,
                           data_freshness, download_status
                    FROM videos WHERE url IN ({placeholders})""",
                checked_urls
            ).fetchall()
            conn.close()

            with open(fn, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["标题", "URL", "上传日期", "时长(秒)", "播放量", "数据状态", "下载状态"])
                for r in rows:
                    writer.writerow(r)
            _log.info(f"CSV导出完成: 路径={fn} 记录={len(rows)}")
            messagebox.showinfo("成功", f"已导出 {len(rows)} 条记录到:\n{fn}")
        except Exception as ex:
            messagebox.showerror("导出失败", str(ex))

    def _db_fill_upload_dates(self):
        """为列表中勾选的视频补全上传日期（仅处理选中的）。"""
        from yt_channel_fetch import update_upload_dates_in_db
        db_path = getattr(self, '_current_db', None)
        if not db_path:
            messagebox.showwarning("提示", "请先打开数据库文件")
            return

        # 仅处理勾选的视频
        checked_urls = [u for u, c in getattr(self, '_db_checked', {}).items() if c]
        if not checked_urls:
            messagebox.showwarning("提示", "请先在列表中勾选要补全上传日期的视频")
            return

        import sqlite3
        conn = sqlite3.connect(db_path)
        placeholders = ",".join("?" * len(checked_urls))
        count = conn.execute(
            f"SELECT COUNT(*) FROM videos WHERE url IN ({placeholders}) "
            f"AND (upload_date IS NULL OR upload_date='')", checked_urls
        ).fetchone()[0]
        conn.close()
        if count == 0:
            messagebox.showinfo("提示", "所选视频已全部有上传日期")
            return

        if not messagebox.askyesno("确认",
            f"将为 {count} 个视频获取上传日期（后台运行）\n是否继续？"):
            return

        _log.info(f"补全上传日期开始: DB={db_path} 已选={count} 个")
        self._show_loading()
        self._loading.update_msg("正在获取上传日期...")

        def bg_work():
            try:
                filled = update_upload_dates_in_db(db_path, checked_urls)
                import sqlite3
                conn = sqlite3.connect(db_path)
                total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
                full_ct = conn.execute(
                    "SELECT COUNT(*) FROM videos WHERE data_freshness='full'").fetchone()[0]
                conn.close()
                def update_stats():
                    self._dismiss_loading()
                    self._db_stat_labels["total"].configure(text=str(total))
                    self._db_stat_labels["full"].configure(text=str(full_ct))
                    self._db_stat_labels["partial"].configure(text=str(total - full_ct))
                    self._query_and_display_videos()
                    messagebox.showinfo("完成", f"上传日期补全完成！\n{filled}/{count} 个视频已更新")
                    _log.info(f"补全上传日期完成: DB={db_path} 成功={filled}/{count}")
                self.root.after(0, update_stats)
            except Exception as ex:
                self.root.after(0, lambda: (
                    self._dismiss_loading(),
                    messagebox.showerror("错误", str(ex))
                ))

        Thread(target=bg_work, daemon=True).start()

    def _db_download_selected(self):
        """Load selected video URLs and switch to download tab."""
        checked_urls = [u for u, c in getattr(self, '_db_checked', {}).items() if c]
        if not checked_urls:
            messagebox.showwarning("提示", "请先在列表中勾选要下载的视频")
            return

        db_path = getattr(self, '_current_db', None)
        if not db_path:
            return

        # Load URLs from database
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
            placeholders = ",".join("?" * len(checked_urls))
            urls = [r[0] for r in conn.execute(
                f"SELECT url FROM videos WHERE url IN ({placeholders})",
                checked_urls
            ).fetchall()]
            conn.close()
        except Exception as ex:
            messagebox.showerror("错误", f"读取数据库失败:\n{ex}")
            return

        _log.info(f"DB加载下载: DB={db_path} 已选={len(urls)}")
        self.urls.__setitem__(slice(None), urls)
        self.url_file_path.set(db_path)
        self.file_type.set("sqlite")
        self.max_videos_label.configure(text=f"最多 {len(urls)} 个视频")
        self.url_count_badge.configure(text=f"{len(urls)} 个URL")
        self.update_urls_display()

        messagebox.showinfo("已加载",
            f"已选中 {len(urls)} 个视频到下载列表\n\n"
            f"请确认下载目录和选项后点击「开始下载」")

    # ═══════════════════════════════════════════════════════════════
    #  Loading overlay
    # ═══════════════════════════════════════════════════════════════
        if getattr(self, '_loading', None) and self._loading._win:
            return
    # ═══════════════════════════════════════════════════════════════
    #  Loading overlay
    # ═══════════════════════════════════════════════════════════════

    def _show_loading(self):
        if getattr(self, '_loading', None) and self._loading._win:
            return
        self._loading = _LoadingOverlay(self.root, self.colors, on_dismiss=self._on_loading_dismiss)
        self._loading.show("正在获取频道视频...")

    def _dismiss_loading(self):
        if getattr(self, '_loading', None):
            self._loading.dismiss()
            self._loading = None

    def _on_loading_dismiss(self):
        self._loading = None

    @staticmethod
    def _extract_channel_name(url):
        """从 YouTube URL 提取频道标识符，用于文件名"""
        import re, urllib.parse
        if not url:
            return "channel"
        # 解码 URL
        try:
            url = urllib.parse.unquote(url)
        except Exception:
            pass
        # @username 格式: .../@name
        m = re.search(r'youtube\.com/@([^/?]+)', url)
        if m:
            return m.group(1)
        # /channel/UCxxx 格式
        m = re.search(r'youtube\.com/channel/([^/?]+)', url)
        if m:
            return m.group(1)
        # /c/name 或 /user/name 格式
        m = re.search(r'youtube\.com/(?:c|user)/([^/?]+)', url)
        if m:
            return m.group(1)
        # 纯 @username（直接给 @xxx）
        m = re.match(r'@([^/?]+)', url)
        if m:
            return m.group(1)
        return "channel"

    def _make_count_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "视频数量")

        count_frame = tk.Frame(parent, bg=c["surface"])
        count_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=6)

        self.max_videos_label = tk.Label(count_frame, text="最多 0 个视频",
                                          bg=c["surface"], fg=c["text_muted"],
                                          font=("Segoe UI", 10), padx=4)
        self.max_videos_label.pack(side=tk.LEFT)
        return 1

    def _make_subtitle_row(self, parent, row):
        c = self.colors

        # Checkbox: 是否下载字幕
        self._make_field_label(parent, row, "字幕下载")

        cbx_frame = tk.Frame(parent, bg=c["surface"])
        cbx_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        self.sub_cbx = tk.Checkbutton(
            cbx_frame, text="下载字幕文件",
            variable=self.download_subtitles,
            onvalue=True, offvalue=False,
            bg=c["surface"], fg=c["text"],
            selectcolor=c["accent"], activebackground=c["surface"],
            font=("Segoe UI", 10), anchor=tk.W,
            command=self._on_subtitle_toggle
        )
        self.sub_cbx.pack(side=tk.LEFT)

        self.sub_lang_entry = tk.Entry(
            cbx_frame,
            textvariable=self.sub_lang,
            bg=c["surface2"], fg=c["text"],
            insertbackground=c["accent"], relief=tk.FLAT, bd=0,
            font=("Segoe UI", 10), width=18,
            highlightbackground=c["border"], highlightthickness=1, insertwidth=2
        )
        self.sub_lang_entry.pack(side=tk.LEFT, padx=(12, 0))

        self.sub_lang_hint = tk.Label(
            cbx_frame, text="如: zh-Hans,en,ja",
            bg=c["surface"], fg=c["text_muted"],
            font=("Segoe UI", 8), padx=6
        )
        self.sub_lang_hint.pack(side=tk.LEFT, padx=(4, 0))

        # Default state: enabled
        self._on_subtitle_toggle()
        return 1

    def _make_llm_provider_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "LLM 提供商")
        combo_frame = tk.Frame(parent, bg=c["surface"])
        combo_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        self.llm_provider_var = tk.StringVar(value="qwen")
        combo = ttk.Combobox(combo_frame, textvariable=self.llm_provider_var,
                             values=["qwen", "openai", "ollama", "groq"],
                             state="readonly", width=16, font=("Segoe UI", 10))
        combo.pack(side=tk.LEFT)

        tk.Label(combo_frame, text="模型:", bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 9), padx=(16, 4)).pack(side=tk.LEFT)
        self.llm_model_var = tk.StringVar()
        model_entry = tk.Entry(combo_frame, textvariable=self.llm_model_var,
                               bg=c["surface2"], fg=c["text"],
                               insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                               font=("Segoe UI", 10), width=18,
                               highlightbackground=c["border"], highlightthickness=1)
        model_entry.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(combo_frame, text="留空用默认", bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        return 1

    def _make_llm_min_score_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "精彩片段评分")
        score_frame = tk.Frame(parent, bg=c["surface"])
        score_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        self.llm_min_score_var = tk.StringVar(value="7.0")
        entry = tk.Entry(score_frame, textvariable=self.llm_min_score_var,
                         bg=c["surface2"], fg=c["text"],
                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                         font=("Segoe UI", 10), width=8,
                         highlightbackground=c["border"], highlightthickness=1)
        entry.pack(side=tk.LEFT)

        tk.Label(score_frame, text="分  (1-10，仅保留高于此分的片段)",
                 bg=c["surface"], fg=c["text_muted"], font=("Segoe UI", 9), padx=8).pack(side=tk.LEFT)
        return 1

    def _make_llm_category_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "视频内容类型")
        combo_frame = tk.Frame(parent, bg=c["surface"])
        combo_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        self.llm_category_var = tk.StringVar(value="knowledge")
        combo = ttk.Combobox(combo_frame, textvariable=self.llm_category_var,
                             values=["knowledge", "entertainment", "vlog", "news"],
                             state="readonly", width=16, font=("Segoe UI", 10))
        combo.pack(side=tk.LEFT)
        tk.Label(combo_frame, text="= 知识/教程 | 娱乐/游戏 | Vlog | 新闻",
                 bg=c["surface"], fg=c["text_muted"], font=("Segoe UI", 8), padx=8).pack(side=tk.LEFT)
        return 1

    def _on_subtitle_toggle(self):
        state = "normal" if self.download_subtitles.get() else "disabled"
        self.sub_lang_entry.configure(state=state)
        self.sub_lang_hint.configure(fg=self.colors["text_muted"] if self.download_subtitles.get() else self.colors["border"])

    def _make_cookie_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "Cookie")

        cookie_frame = tk.Frame(parent, bg=c["surface"])
        cookie_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        # Cookie 文件输入
        lbl = tk.Label(cookie_frame, text="文件:", bg=c["surface"], fg=c["text_muted"],
                       font=("Segoe UI", 9))
        lbl.pack(side=tk.LEFT)
        entry = tk.Entry(cookie_frame, textvariable=self.cookie_file_path,
                         bg=c["surface2"], fg=c["text"],
                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                         font=("Segoe UI", 10), width=28,
                         highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        entry.pack(side=tk.LEFT, padx=(4, 4))

        def browse_cookie_file():
            filename = filedialog.askopenfilename(
                filetypes=[("Cookie 文件", "*.txt *.json"), ("所有文件", "*.*")])
            if filename:
                self.cookie_file_path.set(filename)

        fb = tk.Label(cookie_frame, text="浏览", bg=c["surface2"], fg=c["text"],
                       font=("Segoe UI", 9), padx=8, pady=4,
                       relief=tk.FLAT, cursor="hand2", bd=1,
                       highlightbackground=c["border"], highlightthickness=1)
        fb.pack(side=tk.LEFT)
        fb.bind("<Button-1>", lambda e: browse_cookie_file())
        fb.bind("<Enter>", lambda e: fb.configure(bg=c["border"]))
        fb.bind("<Leave>", lambda e: fb.configure(bg=c["surface2"]))

        # JSON 转换提示
        tk.Label(cookie_frame, text="（支持 .txt 和 .json）",
                 bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 0))
        return 1

    def _draw_progress_bar(self, percent):
        c = self.colors
        w = self.progress_canvas.winfo_width()
        if w < 2:
            return
        self.progress_canvas.delete("all")
        # Background
        self.progress_canvas.create_rectangle(0, 0, w, 10, fill=c["surface2"], outline="")
        # Fill
        if percent > 0:
            fill_w = int(w * percent / 100)
            self.progress_canvas.create_rectangle(0, 0, fill_w, 10, fill=c["accent"], outline="")
            # Glow effect
            self.progress_canvas.create_rectangle(0, 2, fill_w, 8, fill=c["accent_hover"], outline="")

    def setup_callbacks(self):
        pass

    def update_urls_display(self):
        c = self.colors
        self.urls_text.configure(state="normal")
        self.urls_text.delete("1.0", tk.END)

        count = len(self.urls)
        count = min(count, len(self.urls))

        for i, url in enumerate(self.urls[:count], 1):
            self.urls_text.insert(tk.END, f"{i}. {url}\n")

        self.urls_text.configure(state="disabled")
        self.url_count_badge.configure(text=f"{count} / {len(self.urls)} 个URL")

    def load_proxy_config(self):
        try:
            if os.path.exists(self.proxy_config_file):
                with open(self.proxy_config_file, "r") as f:
                    config = json.load(f)
                    return config.get("proxy", "")
        except Exception:
            pass
        return ""

    def save_proxy(self):
        proxy = self.proxy.get()
        try:
            with open(self.proxy_config_file, "w") as f:
                json.dump({"proxy": proxy}, f)
            messagebox.showinfo("成功", "代理设置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存代理设置失败: {str(e)}")

    def _make_doc_btn(self, parent, text, rel_path):
        c = self.colors
        btn = tk.Label(parent, text=text,
                       bg=c["surface2"], fg=c["text_secondary"],
                       font=("Segoe UI", 9), padx=12, pady=6,
                       relief=tk.FLAT, cursor="hand2", bd=1,
                       highlightbackground=c["border"], highlightthickness=1)
        btn.pack(side=tk.LEFT, padx=(0, 8))
        abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
        btn.bind("<Button-1>", lambda e: self._open_doc(abs_path))
        btn.bind("<Enter>", lambda e: btn.configure(bg=c["border"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=c["surface2"]))

    def _open_doc(self, abs_path):
        if os.path.exists(abs_path):
            webbrowser.open(f"file:///{abs_path}")
        else:
            messagebox.showwarning("文件未找到", f"找不到文档文件：\n{abs_path}")

    def select_file(self):
        ftype = self.file_type.get()
        if ftype == "excel":
            filetypes = [("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        elif ftype == "csv":
            filetypes = [("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        else:
            filetypes = [("TXT 文件", "*.txt"), ("所有文件", "*.*")]
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            self.url_file_path.set(filename)
            self.urls = read_urls_from_file(filename) or []
            self.max_videos_label.configure(text=f"最多 {len(self.urls)} 个视频")
            self.url_count_badge.configure(text=f"{len(self.urls)} 个URL")
            self.update_urls_display()

    def select_save_path(self):
        path = filedialog.askdirectory()
        if path:
            self.save_path.set(path)

    def update_progress(self, progress, status_text):
        percent = int(progress * 100)
        self._draw_progress_bar(percent)
        self.progress_status.configure(text=status_text)
        self.progress_percent.configure(text=f"{percent}%")
        self.root.update_idletasks()

    def validate_inputs(self):
        if not self.url_file_path.get():
            messagebox.showerror("错误", "请选择Excel文件")
            return False
        if not self.save_path.get():
            messagebox.showerror("错误", "请选择保存路径")
            return False
        if not self.urls:
            messagebox.showerror("错误", "Excel文件中没有找到有效的URL")
            return False
        try:
            count = len(self.urls)
            if count <= 0:
                messagebox.showerror("错误", "请先添加视频 URL")
                return False
            self.update_urls_display()
        except ValueError:
            messagebox.showerror("错误", "请输入有效的下载数量")
            return False
        return True

    def start_download(self):
        if not self.validate_inputs():
            return
        c = self.colors
        self.download_btn.configure(text="下载中...", bg=c["text_muted"])
        self.download_btn.unbind("<Enter>")
        self.download_btn.unbind("<Leave>")
        Thread(target=self.download_thread, daemon=True).start()

    def _monitor_config_for_download(self) -> dict:
        """与 monitor 共用 config.json（若存在），用于 enable_aria2 等与 Web 一致。"""
        try:
            root = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(root, "monitor", "config.json")
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def download_thread(self):
        try:
            count = len(self.urls)
            _log.info(f"下载开始: 总数={count} 保存={self.save_path.get()}")
            def progress_callback(progress, status):
                self.root.after(0, self.update_progress, progress, status)

            mcfg = self._monitor_config_for_download()
            enable_aria2 = bool(mcfg.get("enable_aria2", False))
            extra_ydl = build_aria2_opts(None) if enable_aria2 else None

            pf = self.proxy_file_path.get().strip()
            proxy_pool = load_proxy_pool(pf) if pf and os.path.isfile(pf) else None
            single_proxy = (self.proxy.get() or "").strip() or None

            results = batch_download(
                self.urls[:count],
                self.save_path.get(),
                'best',  # 最高画质
                proxy=None if proxy_pool else single_proxy,
                proxy_pool=proxy_pool,
                progress_callback=progress_callback,
                sub_langs=self.sub_lang.get() if self.download_subtitles.get() else None,
                no_subs=not self.download_subtitles.get(),
                cookies_file=self.cookie_file_path.get().strip() or None,
                extra_ydl_opts=extra_ydl,
                direct_fallback_after_proxies_exhausted=True,
            )

            success_count = sum(1 for r in results if r["状态"] == "成功")
            _log.info(f"下载完成: 成功={success_count}/{len(results)} 保存={self.save_path.get()}")
            self.root.after(0, lambda: messagebox.showinfo(
                "完成", f"下载完成！成功: {success_count}/{len(results)}"))
        except Exception as e:
            err = str(e)
            _log.error(f"下载异常: {err}")
            self.root.after(0, lambda err=err: messagebox.showerror("错误", f"下载过程中出错: {err}"))
        finally:
            self.root.after(0, self._reset_download_btn)

    def _reset_download_btn(self):
        c = self.colors
        self.download_btn.configure(text="开始下载", bg=c["accent"])
        self.download_btn.bind("<Enter>", lambda e: self.download_btn.configure(bg=c["accent_hover"]))
        self.download_btn.bind("<Leave>", lambda e: self.download_btn.configure(bg=c["accent"]))
        self.progress_status.configure(text="就绪")
        self.progress_percent.configure(text="0%")
        self._draw_progress_bar(0)


def main():
    root = tk.Tk()
    app = YoutubeDownloaderUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

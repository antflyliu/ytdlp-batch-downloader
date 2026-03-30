import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import webbrowser
from Youtube_Downloader import read_urls_from_file, batch_download, load_proxy_pool
from threading import Thread


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
        self.use_browser_cookie = tk.BooleanVar(value=False)
        self.cookie_browser = tk.StringVar(value="edge")
        self.cookie_file_path = tk.StringVar()
        self.cookie_profile = tk.StringVar(value="Profile 1")
        self._temp_cookie_path = None  # JSON→Netscape 转换后的临时文件路径
        self._cookie_status = tk.StringVar()  # 转换状态显示
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
                                scrollregion=(0, 0, 880, 1200))
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
            h = content_h[3] if content_h else 1200
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

        # ─── Section 1: Download Settings ───────────────────────────
        self._make_section(main, "下载设置", [
            self._make_file_row,
            self._make_path_row,
            self._make_proxy_row,
        ])

        # ─── Section 2: Download Options ─────────────────────────────
        self._make_section(main, "下载选项", [
            self._make_resolution_row,
            self._make_count_row,
            self._make_subtitle_row,
            self._make_cookie_row,
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
        h = content_h[3] if content_h else 1200
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
        self._make_type_toggle(type_frame, "TXT", "txt", 1)

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
        self._make_field_label(parent, row, "视频分辨率")
        self.resolution = tk.StringVar(value="1080p")

        options_frame = tk.Frame(parent, bg=c["surface"])
        options_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=6)

        resolutions = [("720p", "720p"), ("1080p", "1080p"), ("1440p", "1440p")]
        for i, (text, value) in enumerate(resolutions):
            self._make_radio_option(options_frame, text, value, i)
        return 1

    def _make_radio_option(self, parent, text, value, col):
        c = self.colors
        is_default = (value == self.resolution.get())

        btn = tk.Frame(parent, bg=c["accent"] if is_default else c["border"],
                       relief=tk.FLAT, bd=0, padx=1, pady=1)
        btn.grid(row=0, column=col, padx=(0, 8))
        btn.columnconfigure(0, weight=1)
        btn.rowconfigure(0, weight=1)

        inner = tk.Frame(btn, bg=c["accent_dim"] if is_default else c["surface2"],
                          relief=tk.FLAT, bd=0)
        inner.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(inner, text=text,
                       bg=c["accent_dim"] if is_default else c["surface2"],
                       fg=c["accent"] if is_default else c["text"],
                       font=("Segoe UI", 10, "bold"), cursor="hand2")
        lbl.pack(padx=13, pady=6)

        # Bind to all levels for reliable click detection inside Canvas
        lbl.bind("<Button-1>", lambda e: self._select_resolution(value))
        btn.bind("<Button-1>", lambda e: self._select_resolution(value))
        inner.bind("<Button-1>", lambda e: self._select_resolution(value))

        setattr(self, f"_res_btn_{value}", (btn, inner, lbl))
        self.resolution.trace_add("write", lambda *a, bv=value, bi=(btn, inner, lbl):
                                   self._update_radio_ui(bv, bi))

    def _select_resolution(self, value):
        self.resolution.set(value)

    def _update_radio_ui(self, value, widgets):
        c = self.colors
        btn, inner, lbl = widgets
        selected = (self.resolution.get() == value)
        inner_bg = c["accent_dim"] if selected else c["surface2"]
        fg = c["accent"] if selected else c["text"]
        border = c["accent"] if selected else c["border"]
        btn.configure(bg=border)
        inner.configure(bg=inner_bg)
        lbl.configure(fg=fg, bg=inner_bg)

    def _make_count_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "下载数量")
        self.download_count = tk.StringVar()

        count_frame = tk.Frame(parent, bg=c["surface"])
        count_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=6)

        entry = tk.Entry(count_frame, textvariable=self.download_count,
                          bg=c["surface2"], fg=c["text"],
                          insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                          font=("Segoe UI", 10), width=8,
                          highlightbackground=c["border"], highlightthickness=1,
                          insertwidth=2)
        entry.pack(side=tk.LEFT)

        self.max_videos_label = tk.Label(count_frame, text="最多 0 个视频",
                                          bg=c["surface"], fg=c["text_muted"],
                                          font=("Segoe UI", 9), padx=12)
        self.max_videos_label.pack(side=tk.LEFT, padx=(12, 0))
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

    def _on_subtitle_toggle(self):
        state = "normal" if self.download_subtitles.get() else "disabled"
        self.sub_lang_entry.configure(state=state)
        self.sub_lang_hint.configure(fg=self.colors["text_muted"] if self.download_subtitles.get() else self.colors["border"])

    def _make_cookie_row(self, parent, row):
        c = self.colors
        self._make_field_label(parent, row, "Cookie")

        cookie_frame = tk.Frame(parent, bg=c["surface"])
        cookie_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, padx=(8, 12), pady=4)

        # 浏览器 Cookie 复选框
        cbx = tk.Checkbutton(
            cookie_frame, text="从浏览器读取（需已登录YouTube）",
            variable=self.use_browser_cookie,
            onvalue=True, offvalue=False,
            bg=c["surface"], fg=c["text"],
            selectcolor=c["accent"], activebackground=c["surface"],
            font=("Segoe UI", 10), anchor=tk.W,
            command=self._on_cookie_toggle
        )
        cbx.pack(side=tk.LEFT)

        # 浏览器选择下拉
        browsers = [("Edge", "edge"), ("Chrome", "chrome"), ("Firefox", "firefox")]
        browser_combo = ttk.Combobox(
            cookie_frame, textvariable=self.cookie_browser,
            values=[v for _, v in browsers],
            state="readonly", width=8, font=("Segoe UI", 10)
        )
        browser_combo.pack(side=tk.LEFT, padx=(8, 0))

        # Profile 输入框
        sep2 = tk.Label(cookie_frame, text="Profile:", bg=c["surface"], fg=c["text_muted"],
                        font=("Segoe UI", 9))
        sep2.pack(side=tk.LEFT, padx=(8, 0))
        profile_entry = tk.Entry(cookie_frame, textvariable=self.cookie_profile,
                                 bg=c["surface2"], fg=c["text"],
                                 insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                                 font=("Segoe UI", 10), width=10,
                                 highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        profile_entry.pack(side=tk.LEFT, padx=(2, 0))

        # 分隔符
        sep = tk.Label(cookie_frame, text="|", bg=c["surface"], fg=c["text_muted"], font=("Segoe UI", 10))
        sep.pack(side=tk.LEFT, padx=(12, 0))

        # Cookie 文件
        lbl = tk.Label(cookie_frame, text="文件:", bg=c["surface"], fg=c["text_muted"],
                       font=("Segoe UI", 9), padx=0)
        lbl.pack(side=tk.LEFT)
        entry = tk.Entry(cookie_frame, textvariable=self.cookie_file_path,
                         bg=c["surface2"], fg=c["text"],
                         insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                         font=("Segoe UI", 10), width=20,
                         highlightbackground=c["border"], highlightthickness=1, insertwidth=2)
        entry.pack(side=tk.LEFT, padx=(0, 4))

        def browse_cookie_file():
            filename = filedialog.askopenfilename(
                filetypes=[("Cookie 文件", "*.txt *.json"), ("所有文件", "*.*")])
            if not filename:
                return
            ext = filename.lower().rsplit(".", 1)[-1]
            if ext == "json":
                # JSON → 自动转换为 Netscape 临时文件
                import export_cookies
                try:
                    tmp_path, count, missing = export_cookies.convert_json_to_temp_netscape(filename)
                    self._temp_cookie_path = tmp_path
                    self.cookie_file_path.set(filename)
                    if missing:
                        self._cookie_status.set(f"⚠️ 转换成功 {count} 个，但缺失: {', '.join(missing)}")
                    else:
                        self._cookie_status.set(f"✅ 转换成功 {count} 个，关键 Cookie 完整")
                except Exception as e:
                    self._temp_cookie_path = None
                    self.cookie_file_path.set("")
                    self._cookie_status.set(f"❌ JSON 转换失败: {e}")
            else:
                self._temp_cookie_path = None
                self.cookie_file_path.set(filename)
                self._cookie_status.set("")

        fb = tk.Label(cookie_frame, text="浏览", bg=c["surface2"], fg=c["text"],
                       font=("Segoe UI", 9), padx=8, pady=4,
                       relief=tk.FLAT, cursor="hand2", bd=1,
                       highlightbackground=c["border"], highlightthickness=1)
        fb.pack(side=tk.LEFT)
        fb.bind("<Button-1>", lambda e: browse_cookie_file())
        fb.bind("<Enter>", lambda e: fb.configure(bg=c["border"]))
        fb.bind("<Leave>", lambda e: fb.configure(bg=c["surface2"]))

        # 转换状态标签
        status_lbl = tk.Label(cookie_frame, textvariable=self._cookie_status,
                              bg=c["surface"], fg=c["accent"],
                              font=("Segoe UI", 8), anchor=tk.W)
        status_lbl.pack(side=tk.LEFT, padx=(8, 0))

        self._on_cookie_toggle()
        return 1

    def _on_cookie_toggle(self):
        state = "normal" if self.use_browser_cookie.get() else "disabled"
        # cookie file still always editable, browser dropdown controlled by checkbox
        pass

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
        def on_count_change(*args):
            if self.urls:
                self.update_urls_display()
        self.download_count.trace_add("write", on_count_change)

    def update_urls_display(self):
        c = self.colors
        self.urls_text.configure(state="normal")
        self.urls_text.delete("1.0", tk.END)

        count = int(self.download_count.get()) if self.download_count.get() else len(self.urls)
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
            count = int(self.download_count.get() or len(self.urls))
            if count <= 0 or count > len(self.urls):
                messagebox.showerror("错误", f"下载数量必须在1到{len(self.urls)}之间")
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

    def download_thread(self):
        try:
            count = int(self.download_count.get() or len(self.urls))
            proxy = self.proxy.get()
            proxy_file = self.proxy_file_path.get().strip()
            proxy_pool = load_proxy_pool(proxy_file) if proxy_file else None

            if proxy_pool:
                print(f"[代理池] 已加载 {len(proxy_pool)} 个代理，启用自动轮换")
                proxy = None  # 代理池优先
            elif proxy:
                print(f"[代理] 使用单个代理: {proxy}")

            def progress_callback(progress, status):
                self.root.after(0, self.update_progress, progress, status)

            results = batch_download(
                self.urls[:count],
                self.save_path.get(),
                self.resolution.get(),
                proxy=proxy,
                progress_callback=progress_callback,
                sub_langs=self.sub_lang.get() if self.download_subtitles.get() else None,
                no_subs=not self.download_subtitles.get(),
                proxy_pool=proxy_pool,
                cookies_from_browser=self.cookie_browser.get() + ':' + self.cookie_profile.get() if self.use_browser_cookie.get() else None,
                cookies_file=self._temp_cookie_path or self.cookie_file_path.get().strip() or None,
            )

            success_count = sum(1 for r in results if r["状态"] == "成功")
            self.root.after(0, lambda: messagebox.showinfo(
                "完成", f"下载完成！成功: {success_count}/{len(results)}"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"下载过程中出错: {str(e)}"))
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

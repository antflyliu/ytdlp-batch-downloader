"""
monitor_ui.py — YouTube 视频监控管理页面
作为独立窗口嵌入到 ytdownload_ui.py 的"数据库管理"区域，
或作为独立窗口运行。

支持：
  - 添加/编辑/删除监控账户
  - 启动/停止定时调度器
  - 实时显示扫描事件日志
  - 飞书 Webhook 全局配置
"""
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone

import tkinter as tk
from tkinter import ttk, messagebox

# 添加项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import logging_config
import monitor.db as _db
import monitor.scheduler as _scheduler

_log = logging_config.get_logger("monitor_ui")

# ── 数据库初始化 ──────────────────────────────────────────────────────────────
_db.init_db()
_db.ensure_app_state_table()

# ── 颜色主题 ────────────────────────────────────────────────────────────────

_COLORS = {
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
    "purple": "#bc8cff",
}


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _load_config() -> dict:
    return _db.load_config()


def _save_config(cfg: dict) -> None:
    path = _db.get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ── 添加/编辑账户弹窗 ──────────────────────────────────────────────────────

class AccountDialog(tk.Toplevel):
    def __init__(self, parent, account: dict | None = None):
        super().__init__(parent)
        self.account = account
        self.result = None
        self._build_ui()

    def _build_ui(self):
        c = _COLORS
        self.configure(bg=c["bg"])
        self.title("编辑监控账户" if self.account else "添加监控账户")
        self.geometry("540x540")
        self.resizable(False, False)
        self.grab_set()

        frame = tk.Frame(self, bg=c["bg"])
        frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)
        frame.columnconfigure(1, weight=1)

        # 基本信息行
        basic_fields = [
            ("账户名称",       "name",        0, "显示名称，如'综艺Show'"),
            ("频道 URL",       "channel_url", 2, "@C-HitShow / UCxxxx / 完整URL"),
            ("API Key 环境变量", "api_key_env", 4, "如 YOUTUBE_Data_API_V3"),
        ]
        self._vars = {}

        for label_text, key, row, hint in basic_fields:
            tk.Label(frame, text=label_text, bg=c["bg"], fg=c["text_secondary"],
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W, pady=(8, 0))
            var = tk.StringVar(value=self.account.get(key, "") if self.account else "")
            self._vars[key] = var
            entry = tk.Entry(frame, textvariable=var, bg=c["surface2"], fg=c["text"],
                           insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                           font=("Segoe UI", 9),
                           highlightbackground=c["border"], highlightthickness=1)
            entry.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0))
            # hint 放在下一行，不与 entry 重叠
            tk.Label(frame, text=hint, bg=c["bg"], fg=c["text_muted"],
                    font=("Segoe UI", 7)).grid(row=row+1, column=1, sticky=tk.W, padx=(8, 0))

        # 分隔
        sep = tk.Frame(frame, bg=c["border"], height=1)
        sep.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(4, 4))

        # 扫描参数行
        scan_fields = [
            ("获取模式",        "fetch_mode",    7, "",           "playlist"),
            ("每次获取条数",    "fetch_limit",   9, "建议 5~20",  "5"),
            ("扫描间隔(分钟)",  "scan_interval", 11, "建议 5~30", "5"),
        ]
        for label_text, key, row, hint, default in scan_fields:
            tk.Label(frame, text=label_text, bg=c["bg"], fg=c["text_secondary"],
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky=tk.W, pady=(8, 0))
            var = tk.StringVar(value=self.account.get(key, "") if self.account else default)
            self._vars[key] = var
            if key == "fetch_mode":
                combo = ttk.Combobox(frame, textvariable=var, font=("Segoe UI", 9),
                                     values=["playlist", "search"], state="readonly", width=16)
                combo.grid(row=row, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
            else:
                entry = tk.Entry(frame, textvariable=var, bg=c["surface2"], fg=c["text"],
                               insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                               font=("Segoe UI", 9), width=10,
                               highlightbackground=c["border"], highlightthickness=1)
                entry.grid(row=row, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
            # hint 放在下一行，不与 entry/combo 重叠
            if hint:
                tk.Label(frame, text=hint, bg=c["bg"], fg=c["text_muted"],
                        font=("Segoe UI", 7)).grid(row=row+1, column=1, sticky=tk.W, padx=(8, 0))

        # 分隔
        sep2 = tk.Frame(frame, bg=c["border"], height=1)
        sep2.grid(row=12, column=0, columnspan=2, sticky=tk.EW, pady=(4, 4))

        # 通知设置行
        tk.Label(frame, text="通知平台", bg=c["bg"], fg=c["text_secondary"],
                 font=("Segoe UI", 9)).grid(row=13, column=0, sticky=tk.W, pady=(8, 0))

        self._vars["notify_platform"] = tk.StringVar(
            value=(self.account.get("notify_platform", "feishu") if self.account else "feishu")
        )
        platform_frame = tk.Frame(frame, bg=c["bg"])
        platform_frame.grid(row=13, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        for plat, label, color in [
            ("feishu",   "飞书",   "#7B68EE"),
            ("dingtalk", "钉钉",   "#1677FF"),
            ("wecom",    "企微",   "#52C41A"),
        ]:
            btn = tk.Label(platform_frame, text=label, bg=c["surface2"], fg=c["text"],
                          font=("Segoe UI", 8), padx=10, pady=4, cursor="hand2",
                          relief=tk.FLAT,
                          highlightbackground=c["border"], highlightthickness=1)
            btn.pack(side=tk.LEFT, padx=(0, 6))
            btn.bind("<Button-1>", lambda e, p=plat: self._select_platform(p))
            self._vars[f"_plat_btn_{plat}"] = btn

        tk.Label(frame, text="Webhook URL", bg=c["bg"], fg=c["text_secondary"],
                 font=("Segoe UI", 9)).grid(row=14, column=0, sticky=tk.W, pady=(8, 0))
        self._vars["webhook_url"] = tk.StringVar(
            value=self.account.get("webhook_url", "") if self.account else "")
        webhook_entry = tk.Entry(frame, textvariable=self._vars["webhook_url"],
                              bg=c["surface2"], fg=c["text"],
                              insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                              font=("Segoe UI", 9),
                              highlightbackground=c["border"], highlightthickness=1)
        webhook_entry.grid(row=14, column=1, sticky=tk.EW, padx=(8, 0), pady=(8, 0))
        tk.Label(frame, text="留空则使用全局配置",
                bg=c["bg"], fg=c["text_muted"], font=("Segoe UI", 7)
               ).grid(row=15, column=1, sticky=tk.W, padx=(8, 0))

        # 飞书模板配置（仅飞书平台显示）
        self._feishu_template_group = tk.Frame(frame, bg=c["bg"])

        tk.Label(self._feishu_template_group, text="飞书发送方式", bg=c["bg"],
                 fg=c["text_secondary"], font=("Segoe UI", 9)).grid(
                     row=0, column=0, sticky=tk.W, pady=(8, 0))
        self._vars["feishu_message_mode"] = tk.StringVar(
            value=(self.account.get("feishu_message_mode", "card_json") if self.account else "card_json")
        )
        mode_combo = ttk.Combobox(self._feishu_template_group, textvariable=self._vars["feishu_message_mode"],
                                   font=("Segoe UI", 9), values=["card_json", "template"],
                                   state="readonly", width=18)
        mode_combo.grid(row=0, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        tk.Label(self._feishu_template_group, text="详情模板 ID", bg=c["bg"],
                 fg=c["text_secondary"], font=("Segoe UI", 9)).grid(
                     row=1, column=0, sticky=tk.W, pady=(8, 0))
        self._vars["feishu_template_id"] = tk.StringVar(
            value=(self.account.get("feishu_template_id", "") if self.account else "")
        )
        tpl_entry = tk.Entry(self._feishu_template_group, textvariable=self._vars["feishu_template_id"],
                             bg=c["surface2"], fg=c["text"],
                             insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                             font=("Segoe UI", 9), width=28,
                             highlightbackground=c["border"], highlightthickness=1)
        tpl_entry.grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        tk.Label(self._feishu_template_group, text="飞书卡片模板 ID",
                bg=c["bg"], fg=c["text_muted"], font=("Segoe UI", 7)
               ).grid(row=2, column=1, sticky=tk.W, padx=(8, 0))

        tk.Label(self._feishu_template_group, text="扫描确认模板", bg=c["bg"],
                 fg=c["text_secondary"], font=("Segoe UI", 9)).grid(
                     row=3, column=0, sticky=tk.W, pady=(8, 0))
        self._vars["feishu_scan_template_id"] = tk.StringVar(
            value=(self.account.get("feishu_scan_template_id", "") if self.account else "")
        )
        scan_entry = tk.Entry(self._feishu_template_group, textvariable=self._vars["feishu_scan_template_id"],
                               bg=c["surface2"], fg=c["text"],
                               insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                               font=("Segoe UI", 9), width=28,
                               highlightbackground=c["border"], highlightthickness=1)
        scan_entry.grid(row=3, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))
        tk.Label(self._feishu_template_group, text="扫描确认卡片模板 ID（可为空）",
                bg=c["bg"], fg=c["text_muted"], font=("Segoe UI", 7)
               ).grid(row=4, column=1, sticky=tk.W, padx=(8, 0))

        self._feishu_template_group.grid(row=16, column=0, columnspan=2, sticky=tk.W)

        # 启用/通知复选框
        self._vars["enabled"] = tk.BooleanVar(
            value=bool(self.account.get("enabled", 1)) if self.account else True)
        self._vars["notify_enabled"] = tk.BooleanVar(
            value=bool(self.account.get("notify_enabled", 1)) if self.account else True)

        for key, label_text in [("enabled", "启用监控"), ("notify_enabled", "发送通知")]:
            cb = tk.Checkbutton(frame, text=label_text, variable=self._vars[key],
                              bg=c["bg"], fg=c["text"], selectcolor=c["accent"],
                              activebackground=c["bg"], font=("Segoe UI", 9))
            cb.grid(row=17 if key == "enabled" else 18, column=0, columnspan=2,
                    sticky=tk.W, pady=(8, 0))

        # 按钮
        btn_frame = tk.Frame(self, bg=c["bg"])
        btn_frame.pack(fill=tk.X, padx=24, pady=8)
        btn_frame.columnconfigure(0, weight=1)

        def do_save():
            name = self._vars["name"].get().strip()
            channel_url = self._vars["channel_url"].get().strip()
            api_key_env = self._vars["api_key_env"].get().strip()
            if not name or not channel_url or not api_key_env:
                messagebox.showwarning("提示", "名称、频道 URL、API Key 环境变量不能为空")
                return
            try:
                fetch_limit = int(self._vars["fetch_limit"].get() or 5)
                scan_interval = int(self._vars["scan_interval"].get() or 5)
            except ValueError:
                messagebox.showwarning("提示", "每次获取条数和扫描间隔必须是数字")
                return
            self.result = {
                "name": name,
                "channel_url": channel_url,
                "api_key_env": api_key_env,
                "fetch_mode": self._vars["fetch_mode"].get(),
                "fetch_limit": fetch_limit,
                "scan_interval": scan_interval,
                "enabled": self._vars["enabled"].get(),
                "notify_enabled": self._vars["notify_enabled"].get(),
                "notify_platform": self._vars["notify_platform"].get(),
                "webhook_url": self._vars["webhook_url"].get().strip() or None,
                "feishu_message_mode": self._vars["feishu_message_mode"].get(),
                "feishu_template_id": self._vars["feishu_template_id"].get().strip() or None,
                "feishu_scan_template_id": self._vars["feishu_scan_template_id"].get().strip() or None,
            }
            self.destroy()

        cancel_btn = tk.Label(btn_frame, text="取消", bg=c["surface2"], fg=c["text"],
                              font=("Segoe UI", 9), padx=16, pady=6, cursor="hand2")
        cancel_btn.grid(row=0, column=0)
        cancel_btn.bind("<Button-1>", lambda e: self.destroy())

        save_btn = tk.Label(btn_frame, text="保存", bg=c["accent"], fg="#ffffff",
                            font=("Segoe UI", 9, "bold"), padx=16, pady=6, cursor="hand2")
        save_btn.grid(row=0, column=1, padx=(8, 0))
        save_btn.bind("<Button-1>", lambda e: do_save())
        save_btn.bind("<Enter>", lambda e: save_btn.configure(bg=c["accent_hover"]))
        save_btn.bind("<Leave>", lambda e: save_btn.configure(bg=c["accent"]))

        # 高亮当前平台
        self._update_platform_ui()

    def _select_platform(self, platform: str):
        self._vars["notify_platform"].set(platform)
        self._update_platform_ui()

    def _update_platform_ui(self):
        c = _COLORS
        selected = self._vars["notify_platform"].get()
        plat_colors = {"feishu": "#7B68EE", "dingtalk": "#1677FF", "wecom": "#52C41A"}
        for plat, label, color in [("feishu", "飞书", "#7B68EE"), ("dingtalk", "钉钉", "#1677FF"), ("wecom", "企微", "#52C41A")]:
            btn = self._vars.get(f"_plat_btn_{plat}")
            if btn:
                is_sel = (plat == selected)
                btn.configure(
                    bg=color if is_sel else c["surface2"],
                    fg="#ffffff" if is_sel else c["text"],
                )
        # 飞书模板配置仅在飞书平台显示
        if hasattr(self, "_feishu_template_group"):
            if selected == "feishu":
                self._feishu_template_group.grid()
            else:
                self._feishu_template_group.grid_remove()


# ── 全局设置弹窗 ──────────────────────────────────────────────────────────

class GlobalConfigDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        c = _COLORS
        self.configure(bg=c["bg"])
        self.title("全局 Webhook 配置")
        self.geometry("500x280")
        self.grab_set()

        frame = tk.Frame(self, bg=c["bg"])
        frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)
        frame.columnconfigure(1, weight=1)

        cfg = _load_config()

        self._vars = {}
        webhook_fields = [
            ("飞书 Webhook URL",   "global_feishu_url",    "#7B68EE"),
            ("钉钉 Webhook URL",   "global_dingtalk_url",  "#1677FF"),
            ("企微 Webhook URL",   "global_wecom_url",     "#52C41A"),
        ]

        for i, (label, key, color) in enumerate(webhook_fields):
            tk.Label(frame, text=label, bg=c["bg"], fg=color,
                     font=("Segoe UI", 9)).grid(row=i, column=0, sticky=tk.W, pady=(6, 2))
            var = tk.StringVar(value=cfg.get(key, ""))
            self._vars[key] = var
            entry = tk.Entry(frame, textvariable=var, bg=c["surface2"], fg=c["text"],
                           insertbackground=c["accent"], relief=tk.FLAT, bd=0,
                           font=("Segoe UI", 9),
                           highlightbackground=c["border"], highlightthickness=1)
            entry.grid(row=i, column=1, sticky=tk.EW, padx=(8, 0), pady=(6, 2))

        tk.Label(frame, text="账户级 URL 会覆盖此处全局配置",
                 bg=c["bg"], fg=c["text_muted"], font=("Segoe UI", 7)
                ).grid(row=3, column=1, sticky=tk.W, padx=(8, 0), pady=(4, 0))

        btn_frame = tk.Frame(self, bg=c["bg"])
        btn_frame.pack(fill=tk.X, pady=16)
        btn_frame.columnconfigure(0, weight=1)

        def do_save():
            cfg["global_feishu_url"]    = self._vars["global_feishu_url"].get().strip()
            cfg["global_dingtalk_url"] = self._vars["global_dingtalk_url"].get().strip()
            cfg["global_wecom_url"]    = self._vars["global_wecom_url"].get().strip()
            _save_config(cfg)
            # 通知调度器更新全局 Webhook
            try:
                import monitor.scheduler as sch
                sch._GLOBAL_WEBHOOKS["feishu"]    = cfg["global_feishu_url"] or None
                sch._GLOBAL_WEBHOOKS["dingtalk"] = cfg["global_dingtalk_url"] or None
                sch._GLOBAL_WEBHOOKS["wecom"]   = cfg["global_wecom_url"] or None
            except Exception:
                pass
            messagebox.showinfo("成功", "全局配置已保存")
            self.destroy()

        cancel_btn = tk.Label(btn_frame, text="取消", bg=c["surface2"], fg=c["text"],
                              font=("Segoe UI", 9), padx=16, pady=6, cursor="hand2")
        cancel_btn.grid(row=0, column=0)
        cancel_btn.bind("<Button-1>", lambda e: self.destroy())

        save_btn = tk.Label(btn_frame, text="保存", bg=c["accent"], fg="#ffffff",
                            font=("Segoe UI", 9, "bold"), padx=16, pady=6, cursor="hand2")
        save_btn.grid(row=0, column=1, padx=(8, 0))
        save_btn.bind("<Button-1>", lambda e: do_save())
        save_btn.bind("<Enter>", lambda e: save_btn.configure(bg=c["accent_hover"]))
        save_btn.bind("<Leave>", lambda e: save_btn.configure(bg=c["accent"]))


# ── 监控管理页面主类 ──────────────────────────────────────────────────────

class MonitorPage:
    """
    可嵌入到 ytdownload_ui.py 的监控管理页面组件
    用法:
        page = MonitorPage(parent_frame, colors)
        page.refresh()
    """

    def __init__(self, parent, colors: dict | None = None):
        self.parent = parent
        self.colors = colors or _COLORS
        self.c = self.colors
        self._job = None  # 定时刷新 job id
        self._log_lines: list[str] = []
        self._log_max = 200

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        c = self.c

        # ── 标题栏 ────────────────────────────────────────────
        title_row = tk.Frame(self.parent, bg=c["bg"])
        title_row.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(title_row, text="视频监控", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 13, "bold"), anchor=tk.W).pack(side=tk.LEFT)

        # 调度器状态标签
        self._status_label = tk.Label(title_row, text="调度器: 未知", bg=c["bg"],
                                       fg=c["text_muted"], font=("Segoe UI", 9))
        self._status_label.pack(side=tk.LEFT, padx=(16, 0))

        # 右上角按钮
        btn_frame = tk.Frame(title_row, bg=c["bg"])
        btn_frame.pack(side=tk.RIGHT)

        for btn_text, cmd, color in [
            ("⚙ 全局设置", self._open_global_config, c["surface2"]),
            ("+ 添加账户", self._add_account, c["accent"]),
        ]:
            b = tk.Label(btn_frame, text=btn_text, bg=color, fg=c["text"] if color != c["accent"] else "#ffffff",
                         font=("Segoe UI", 8, "bold" if color == c["accent"] else "normal"),
                         padx=10, pady=4, cursor="hand2")
            b.pack(side=tk.LEFT, padx=(4, 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, b=b, col=color: b.configure(
                bg=col if col == _COLORS["accent"] else _COLORS["border"]))
            b.bind("<Leave>", lambda e, b=b, col=color: b.configure(bg=col))

        # ── 启动/停止按钮 ──────────────────────────────────────
        ctrl_frame = tk.Frame(self.parent, bg=c["bg"])
        ctrl_frame.pack(fill=tk.X, padx=20, pady=8)

        self._toggle_btn = tk.Label(
            ctrl_frame, text="▶ 启动监控",
            bg=c["success"], fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=20, pady=8, cursor="hand2",
        )
        self._toggle_btn.pack(side=tk.LEFT)
        self._toggle_btn.bind("<Button-1>", lambda e: self._toggle_scheduler())

        tk.Label(ctrl_frame, text=" ",
                 bg=c["bg"]).pack(side=tk.LEFT, padx=(4, 0))

        reload_btn = tk.Label(
            ctrl_frame, text="↻ 重载任务",
            bg=c["surface2"], fg=c["text"],
            font=("Segoe UI", 9),
            padx=14, pady=8, cursor="hand2",
            highlightbackground=c["border"], highlightthickness=1,
        )
        reload_btn.pack(side=tk.LEFT)
        reload_btn.bind("<Button-1>", lambda e: self._reload_jobs())

        tk.Label(ctrl_frame, text=" ",
                 bg=c["bg"]).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # ── 账户列表 ───────────────────────────────────────────
        list_frame = tk.Frame(self.parent, bg=c["surface"],
                              highlightbackground=c["border"], highlightthickness=1)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=8)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        # 使用 ttk.Treeview 实现可滚动表格
        cols = ("id", "name", "channel", "mode", "interval", "limit", "status", "notify", "actions")
        self._account_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=6)
        self._account_tree.tag_configure("even", background=c["surface"])
        self._account_tree.tag_configure("odd", background=c["surface2"])
        col_configs = [
            ("id", "ID", 35), ("name", "名称", 110), ("channel", "频道", 170),
            ("mode", "模式", 55), ("interval", "间隔", 45), ("limit", "获取", 40),
            ("status", "状态", 50), ("notify", "通知", 50), ("actions", "操作", 140),
        ]
        for col_id, text, width in col_configs:
            self._account_tree.heading(col_id, text=text)
            self._account_tree.column(col_id, width=width, anchor=tk.W)
        self._account_tree.column("actions", anchor=tk.CENTER)
        self._account_tree.grid(row=0, column=0, sticky="nsew")
        account_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._account_tree.yview)
        self._account_tree.configure(yscrollcommand=account_scroll.set)
        account_scroll.grid(row=0, column=1, sticky="ns")
        # 鼠标滚轮支持
        self._account_tree.bind("<MouseWheel>", lambda e: self._account_tree.yview_scroll(
            int(-e.delta / 120), "units"))
        self._account_tree.bind("<Button-4>", lambda e: self._account_tree.yview_scroll(-1, "units"))
        self._account_tree.bind("<Button-5>", lambda e: self._account_tree.yview_scroll(1, "units"))
        self._account_tree.bind("<Double-Button-1>", self._on_account_tree_click)

        # ── 事件日志 ──────────────────────────────────────────
        tk.Label(self.parent, text="扫描事件日志", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 10, "bold"), anchor=tk.W,
                 padx=20, pady=4).pack(fill=tk.X)

        log_frame = tk.Frame(self.parent, bg=c["surface"],
                             highlightbackground=c["border"], highlightthickness=1)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log_text = tk.Text(log_frame, bg=c["surface2"], fg=c["text"],
                                  font=("Cascadia Code", 8),
                                  relief=tk.FLAT, bd=0, padx=8, pady=6,
                                  state="disabled", wrap=tk.WORD,
                                  height=8)
        self._log_text.pack(fill=tk.BOTH, expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                                   command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 清除日志按钮
        tk.Label(log_frame, text="清除日志", bg=c["surface"], fg=c["text_muted"],
                 font=("Segoe UI", 7), cursor="hand2", padx=4, pady=2).pack(
                     anchor=tk.SE, padx=(0, 20), pady=4)
        # ↑ 绑定在下面 refresh 里

    def refresh(self):
        """刷新账户列表 + 调度器状态"""
        c = self.c

        # 调度器状态
        is_running = _scheduler.is_running()
        state_text = "● 运行中" if is_running else "○ 已停止"
        state_color = c["success"] if is_running else c["text_muted"]
        self._status_label.configure(text=f"调度器: {state_text}", fg=state_color)
        self._toggle_btn.configure(
            text="■ 停止监控" if is_running else "▶ 启动监控",
            bg=c["error"] if is_running else c["success"],
        )

        # 清空并重建账户列表
        for item in self._account_tree.get_children():
            self._account_tree.delete(item)

        accounts = _db.list_accounts()
        if not accounts:
            self._account_tree.insert("", tk.END, values=("暂无监控账户，点击右上角'添加账户'", "", "", "", "", "", "", "", ""))

        for i, acc in enumerate(accounts):
            enabled = acc["enabled"]
            notify = acc["notify_enabled"]
            values = (
                str(acc["id"]),
                acc["name"],
                acc["channel_url"][:25],
                acc["fetch_mode"],
                f"{acc['scan_interval']}m",
                str(acc["fetch_limit"]),
                "启用" if enabled else "禁用",
                "通知" if notify else "静默",
                "编辑 | 删 | 停/启 | 测",
            )
            item_id = self._account_tree.insert("", tk.END, values=values, tags=("even" if i % 2 == 0 else "odd", str(acc["id"])))

        # 定时刷新（每 3 秒）
        if self._job:
            self.parent.after_cancel(self._job)
        self._job = self.parent.after(3000, self.refresh)

    def _toggle_scheduler(self):
        if _scheduler.is_running():
            _scheduler.stop()
            self._append_log("调度器已停止")
        else:
            _scheduler.start()
            self._append_log("调度器已启动")
        self.refresh()

    def _reload_jobs(self):
        if not _scheduler.is_running():
            messagebox.showinfo("提示", "调度器未运行，请先启动")
            return
        n = _scheduler.reload_jobs()
        self._append_log(f"任务重载完成，当前 {n} 个活跃任务")

    def _add_account(self):
        dialog = AccountDialog(self.parent)
        self.parent.wait_window(dialog)
        if dialog.result:
            try:
                account_id = _db.add_account(
                    name=dialog.result["name"],
                    channel_url=dialog.result["channel_url"],
                    api_key_env=dialog.result["api_key_env"],
                    fetch_mode=dialog.result["fetch_mode"],
                    fetch_limit=dialog.result["fetch_limit"],
                    scan_interval=dialog.result["scan_interval"],
                    notify_enabled=dialog.result["notify_enabled"],
                    notify_platform=dialog.result["notify_platform"],
                    webhook_url=dialog.result.get("webhook_url"),
                )
                self._append_log(f"账户添加成功: {dialog.result['name']} (id={account_id})")
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self.refresh()
            except Exception as e:
                messagebox.showerror("错误", str(e))

    def _on_account_tree_click(self, event):
        """Treeview 行点击事件处理"""
        region = self._account_tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self._account_tree.identify_column(event.x)
            row_id = self._account_tree.identify_row(event.y)
            if not row_id:
                return
            item = self._account_tree.item(row_id)
            values = item["values"]
            if not values or values[0] == "暂无监控账户，点击右上角'添加账户'":
                return
            # 从 tags 中获取 account id
            acc_id = int(row_id)
            accs = _db.list_accounts()
            acc = next((a for a in accs if a["id"] == acc_id), None)
            if not acc:
                return
            # 操作列（#9）
            if column == "#9":
                # 在点击位置显示操作菜单
                menu = tk.Menu(self._account_tree, tearoff=0)
                menu.add_command(label="编辑", command=lambda: self._edit_account(acc))
                menu.add_command(label="删除", command=lambda: self._delete_account(acc))
                menu.add_command(label="停用" if acc["enabled"] else "启用",
                               command=lambda: self._toggle_account(acc))
                menu.add_command(label="测试扫描", command=lambda: self._test_account(acc))
                menu.tk_popup(event.x_root, event.y_root)
            else:
                # 双击任意列打开编辑
                self._edit_account(acc)

    def _edit_account(self, acc: dict):
        dialog = AccountDialog(self.parent, account=acc)
        self.parent.wait_window(dialog)
        if dialog.result:
            try:
                _db.update_account(
                    account_id=acc["id"],
                    name=dialog.result["name"],
                    channel_url=dialog.result["channel_url"],
                    api_key_env=dialog.result["api_key_env"],
                    fetch_mode=dialog.result["fetch_mode"],
                    fetch_limit=dialog.result["fetch_limit"],
                    scan_interval=dialog.result["scan_interval"],
                    enabled=dialog.result["enabled"],
                    notify_enabled=dialog.result["notify_enabled"],
                    notify_platform=dialog.result["notify_platform"],
                    webhook_url=dialog.result.get("webhook_url"),
                )
                self._append_log(f"账户已更新: {dialog.result['name']} (id={acc['id']})")
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self.refresh()
            except Exception as e:
                messagebox.showerror("错误", str(e))

    def _delete_account(self, acc: dict):
        if not messagebox.askyesno("确认删除", f"确定删除账户 '{acc['name']}' 吗？\n所有相关数据将被清除"):
            return
        try:
            _db.delete_account(acc["id"])
            self._append_log(f"账户已删除: {acc['name']} (id={acc['id']})")
            if _scheduler.is_running():
                _scheduler.reload_jobs()
            self.refresh()
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _toggle_account(self, acc: dict):
        new_enabled = not acc["enabled"]
        _db.update_account(acc["id"], enabled=new_enabled)
        self._append_log(f"账户 {'启用' if new_enabled else '禁用'}: {acc['name']}")
        if _scheduler.is_running():
            _scheduler.reload_jobs()
        self.refresh()

    def _test_account(self, acc: dict):
        self._append_log(f"开始测试扫描: {acc['name']} ...")
        threading.Thread(target=self._test_account_bg, args=(acc,), daemon=True).start()

    def _test_account_bg(self, acc: dict):
        try:
            _scheduler._scan_account(acc["id"])
            events = _db.get_recent_events(1)
            if events and events[0]["account_id"] == acc["id"]:
                e = events[0]
                msg = (f"测试完成: status={e['status']} "
                       f"返回={e['total_videos']} 新增={e['new_videos']} "
                       f"耗时={e['duration_ms']}ms")
                self._append_log(msg)
            else:
                self._append_log(f"测试完成，但未获取到结果")
        except Exception as ex:
            self._append_log(f"测试失败: {ex}")

    def _open_global_config(self):
        GlobalConfigDialog(self.parent)

    def _append_log(self, msg: str):
        line = f"[{_now_str()}] {msg}"
        self._log_lines.append(line)
        if len(self._log_lines) > self._log_max:
            self._log_lines = self._log_lines[-self._log_max:]

        self._log_text.configure(state="normal")
        self._log_text.insert(tk.END, line + "\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state="disabled")

    def stop(self):
        """停止定时刷新（窗口关闭时调用）"""
        if self._job:
            self.parent.after_cancel(self._job)


# ── 独立窗口入口 ──────────────────────────────────────────────────────────

def run_standalone():
    """启动 Web UI（代替 Tkinter 弹框）"""
    import time
    port = 18999
    # 检查是否已在运行
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1)
        already_running = True
    except Exception:
        already_running = False

    if not already_running:
        import threading
        import http.server as _http

        from monitor_server import MonitorHandler
        server = _http.HTTPServer(("127.0.0.1", port), MonitorHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.8)

    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{port}")
    print(f"\n🌐 监控 Web UI 已启动: http://127.0.0.1:{port}")
    print(f"   按 Ctrl+C 停止\n")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    run_standalone()

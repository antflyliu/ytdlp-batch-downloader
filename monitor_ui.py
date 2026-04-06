"""
monitor_ui.py — YouTube 视频监控管理页面

两种使用方式：
  1) 独立运行（python monitor_ui.py）：启动本地 HTTP 服务并打开浏览器，
     页面由 monitor_web/index.html + monitor_server.py 提供。
  2) 嵌入主程序：将 MonitorPage 挂到 Tk 父 Frame（如 ytdownload_ui 的数据库区域）。

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
from datetime import datetime

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
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _load_config() -> dict:
    return _db.load_config()


def _save_config(cfg: dict) -> None:
    _db.save_config(cfg)


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
        self._feishu_mode_labels = {"Markdown 卡片（推荐）": "card_json", "飞书模板卡片": "template"}
        self._feishu_mode_reverse = {v: k for k, v in self._feishu_mode_labels.items()}
        raw_mode = self.account.get("feishu_message_mode", "card_json") if self.account else "card_json"
        self._vars["feishu_message_mode"] = tk.StringVar(
            value=self._feishu_mode_reverse.get(raw_mode, "Markdown 卡片（推荐）")
        )
        mode_combo = ttk.Combobox(self._feishu_template_group, textvariable=self._vars["feishu_message_mode"],
                                   font=("Segoe UI", 9),
                                   values=list(self._feishu_mode_labels.keys()),
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

        # 分隔
        sep3 = tk.Frame(frame, bg=c["border"], height=1)
        sep3.grid(row=19, column=0, columnspan=2, sticky=tk.EW, pady=(4, 4))

        # 下载代理设置
        tk.Label(frame, text="下载代理设置", bg=c["bg"], fg=c["accent"],
                 font=("Segoe UI", 9, "bold")).grid(
                     row=20, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        self._vars["proxy_enabled"] = tk.BooleanVar(
            value=bool(self.account.get("proxy_enabled", 0)) if self.account else False)

        def _toggle_proxy_section(*args):
            show = self._vars["proxy_enabled"].get()
            if hasattr(self, "_proxy_pool_row"):
                if show:
                    self._proxy_pool_row.grid()
                else:
                    self._proxy_pool_row.grid_remove()

        proxy_cb = tk.Checkbutton(frame, text="启用代理下载（防止下载时 IP 被限流）",
                                  variable=self._vars["proxy_enabled"],
                                  bg=c["bg"], fg=c["text"], selectcolor=c["accent"],
                                  activebackground=c["bg"], font=("Segoe UI", 9))
        proxy_cb.grid(row=21, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        self._vars["proxy_enabled"].trace_add("write", _toggle_proxy_section)

        # 代理池选择
        self._vars["proxy_pool_id"] = tk.IntVar(
            value=self.account.get("proxy_pool_id") or 0 if self.account else 0)

        self._proxy_pool_row = tk.Frame(frame, bg=c["bg"])
        tk.Label(self._proxy_pool_row, text="选择代理池", bg=c["bg"], fg=c["text_secondary"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W, pady=(4, 0))

        # 动态加载代理池列表
        pools = _db.list_proxy_pools()
        pool_choices = ["（不使用）"] + [f"{p['id']}: {p['name']}" for p in pools]
        pool_id_val = self.account.get("proxy_pool_id") or 0 if self.account else 0
        pool_display = (
            f"{pool_id_val}: {next((p['name'] for p in pools if p['id'] == pool_id_val), '（不使用）')}"
            if pool_id_val and pools else "（不使用）"
        )
        if pool_display not in pool_choices:
            pool_display = "（不使用）"
        self._vars["_proxy_pool_display"] = tk.StringVar(value=pool_display)

        proxy_combo = ttk.Combobox(self._proxy_pool_row,
                                   textvariable=self._vars["_proxy_pool_display"],
                                   font=("Segoe UI", 9),
                                   values=pool_choices,
                                   state="readonly", width=24)
        proxy_combo.grid(row=0, column=1, sticky=tk.W, padx=(8, 0), pady=(4, 0))

        # 初始状态
        if not self._vars["proxy_enabled"].get():
            self._proxy_pool_row.grid_remove()
        self._proxy_pool_row.grid(row=22, column=0, columnspan=2, sticky=tk.W)

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
            mode_display = self._vars["feishu_message_mode"].get()
            mode_raw = self._feishu_mode_labels.get(mode_display, "card_json")

            # 解析代理池 ID（从下拉显示文本提取）
            proxy_pool_id_val = 0
            if self._vars["proxy_enabled"].get():
                pool_display = self._vars["_proxy_pool_display"].get()
                if pool_display and pool_display != "（不使用）":
                    parts = pool_display.split(": ", 1)
                    if len(parts) == 2:
                        try:
                            proxy_pool_id_val = int(parts[0])
                        except ValueError:
                            proxy_pool_id_val = 0

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
                "feishu_message_mode": mode_raw,
                "feishu_template_id": self._vars["feishu_template_id"].get().strip() or None,
                "feishu_scan_template_id": self._vars["feishu_scan_template_id"].get().strip() or None,
                "proxy_pool_id": proxy_pool_id_val if proxy_pool_id_val else None,
                "proxy_enabled": self._vars["proxy_enabled"].get(),
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


# ── IP 代理池管理弹窗 ──────────────────────────────────────────

class ProxyPoolDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        c = _COLORS
        self.configure(bg=c["bg"])
        self.title("IP 代理池管理")
        self.geometry("560x360")
        self.grab_set()

        frame = tk.Frame(self, bg=c["bg"])
        frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)

        # 列表
        self._tree = ttk.Treeview(frame, columns=("name", "proxy", "enabled"), show="headings", height=10)
        self._tree.heading("name", text="名称")
        self._tree.heading("proxy", text="代理地址")
        self._tree.heading("enabled", text="状态")
        self._tree.column("name", width=120)
        self._tree.column("proxy", width=300)
        self._tree.column("enabled", width=80)
        self._tree.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        # 按钮行
        btn_frame = tk.Frame(frame, bg=c["bg"])
        btn_frame.pack(fill=tk.X)

        def refresh_list():
            for i in self._tree.get_children():
                self._tree.delete(i)
            for p in _db.list_proxy_pools():
                self._tree.insert("", "end", iid=str(p["id"]), values=(
                    p["name"], p["proxy_url"], "启用" if p["enabled"] else "禁用"
                ))

        def add_pool():
            dlg = tk.Toplevel(self)
            dlg.title("添加代理池")
            dlg.geometry("420x160")
            dlg.configure(bg=c["bg"])
            dlg.grab_set()
            vars_ = {
                "name": tk.StringVar(),
                "proxy": tk.StringVar(),
            }
            tk.Label(dlg, text="名称", bg=c["bg"], fg=c["text"]).grid(row=0, column=0, sticky=tk.W, padx=16, pady=(16, 4))
            tk.Entry(dlg, textvariable=vars_["name"], width=36).grid(row=0, column=1, padx=8, pady=(16, 4))
            tk.Label(dlg, text="代理地址", bg=c["bg"], fg=c["text"]).grid(row=1, column=0, sticky=tk.W, padx=16, pady=4)
            tk.Entry(dlg, textvariable=vars_["proxy"], width=36).grid(row=1, column=1, padx=8, pady=4)

            def save_pool():
                name = vars_["name"].get().strip()
                proxy = vars_["proxy"].get().strip()
                if not name or not proxy:
                    messagebox.showwarning("提示", "名称和代理地址不能为空")
                    return
                _db.add_proxy_pool(name, proxy)
                refresh_list()
                dlg.destroy()

            tk.Button(dlg, text="保存", command=save_pool).grid(row=2, column=1, sticky=tk.E, padx=8, pady=16)

        def toggle_selected():
            sel = self._tree.selection()
            if not sel:
                return
            pid = int(sel[0])
            pool = _db.get_proxy_pool(pid)
            if not pool:
                return
            _db.update_proxy_pool(pid, enabled=not bool(pool["enabled"]))
            refresh_list()

        def delete_selected():
            sel = self._tree.selection()
            if not sel:
                return
            pid = int(sel[0])
            pool = _db.get_proxy_pool(pid)
            if not pool:
                return
            if messagebox.askyesno("确认删除", f"确定删除代理池 '{pool['name']}' 吗？"):
                _db.delete_proxy_pool(pid)
                refresh_list()

        for text, cmd in [
            ("+ 添加代理", add_pool),
            ("启用/禁用", toggle_selected),
            ("删除", delete_selected),
        ]:
            tk.Button(btn_frame, text=text, command=cmd).pack(side=tk.LEFT, padx=(0, 8))

        refresh_list()


# ── 监控管理页面主类 ──────────────────────────────────────────────────────

class MonitorPage:
    """
    可嵌入到 ytdownload_ui.py 的监控管理页面（Tkinter）组件。

    账户列表使用 Canvas + 内部 Frame 分行绘制，替代 ttk.Treeview，
    以便在账户较多时配合滚动条完整展示；操作列使用独立 Label 按钮，
    避免 Treeview 单元格内难以布局的问题。

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
            ("🌐 代理池", self._open_proxy_pools, c["surface2"]),
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

        # ── 账户列表（Canvas + Scrollbar） ───────────────────────────
        # Treeview 在列多、行多时滚动与样式扩展成本高；Canvas 内嵌 Frame
        # 可任意放置控件。scrollregion 随 _account_rows_frame 的 Configure 更新。
        list_outer = tk.Frame(self.parent, bg=c["surface"],
                               highlightbackground=c["border"], highlightthickness=1)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=20, pady=8)

        self._account_canvas = tk.Canvas(
            list_outer, bg=c["surface"], highlightthickness=0,
            confine=True,
        )
        self._account_scroll_y = ttk.Scrollbar(list_outer, orient=tk.VERTICAL,
                                               command=self._account_canvas.yview)
        self._account_scroll_x = ttk.Scrollbar(list_outer, orient=tk.HORIZONTAL,
                                                command=self._account_canvas.xview)
        self._account_canvas.configure(
            yscrollcommand=self._account_scroll_y.set,
            xscrollcommand=self._account_scroll_x.set,
        )

        # 所有表头、数据行、空状态提示均挂在此 Frame 上，作为 Canvas 的单一子窗口
        self._account_rows_frame = tk.Frame(self._account_canvas, bg=c["surface"])
        self._account_canvas_window = self._account_canvas.create_window(
            (0, 0), window=self._account_rows_frame, anchor=tk.NW,
        )

        # 垂直条贴右、水平条贴底，避免与 Canvas 重叠
        self._account_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self._account_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._account_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Canvas 内部窗口大小变化时更新滚动区域
        def _on_frame_configure(event=None):
            self._account_canvas.configure(scrollregion=self._account_canvas.bbox("all"))
        self._account_rows_frame.bind("<Configure>", _on_frame_configure)

        # Canvas 窗口宽度跟随 Canvas 宽度变化
        def _on_canvas_configure(event):
            self._account_canvas.itemconfig(self._account_canvas_window, width=event.width)
        self._account_canvas.bind("<Configure>", _on_canvas_configure)

        # 滚轮：Windows/macOS 用 MouseWheel；Linux/X11 常用 Button-4/5
        def _on_mousewheel(e):
            self._account_canvas.yview_scroll(int(-e.delta / 120), "units")

        def _on_mousewheel_linux_up(_e):
            self._account_canvas.yview_scroll(-1, "units")

        def _on_mousewheel_linux_down(_e):
            self._account_canvas.yview_scroll(1, "units")

        for _w in (self._account_canvas, self._account_rows_frame):
            _w.bind("<MouseWheel>", _on_mousewheel)
            _w.bind("<Button-4>", _on_mousewheel_linux_up)
            _w.bind("<Button-5>", _on_mousewheel_linux_down)

        # 列宽（像素）与 place 的 x 累加一致，总宽约 820；操作列由下方按钮覆盖展示
        col_widths = [
            ("id",       "ID",      40),
            ("name",     "名称",   120),
            ("channel",  "频道",   200),
            ("mode",     "模式",   60),
            ("interval", "间隔",   50),
            ("limit",    "获取",   50),
            ("status",   "状态",   60),
            ("notify",   "通知",   60),
            ("actions",  "操作",  180),
        ]

        # 表头行
        header_frame = tk.Frame(self._account_rows_frame, bg=c["surface2"], height=28)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        col_x = 0
        for col_id, col_text, col_w in col_widths:
            lbl = tk.Label(header_frame, text=col_text, bg=c["surface2"],
                            fg=c["text_secondary"], font=("Segoe UI", 8, "bold"),
                            anchor=tk.W, padx=6)
            lbl.place(x=col_x, y=0, width=col_w, height=28)
            col_x += col_w

        # refresh() 时先销毁下列表，避免泄漏；表头固定不放入此列表
        self._account_row_widgets: list = []

        self._account_canvas.xview_moveto(0)
        self._total_col_width = col_x  # 与 col_widths 累加一致，供后续扩展横向滚动

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
        """刷新调度器状态，重建账户列表行，并更新 Canvas 滚动区域。

        每 3 秒由 after 再次调用自身，实现定时刷新。
        """
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

        # 清理旧行
        for w in self._account_row_widgets:
            w.destroy()
        self._account_row_widgets.clear()

        accounts = _db.list_accounts()
        if not accounts:
            empty_lbl = tk.Label(self._account_rows_frame, text="暂无监控账户，点击右上角「添加账户」",
                                  bg=c["surface"], fg=c["text_muted"],
                                  font=("Segoe UI", 9), anchor=tk.W, padx=6, pady=6)
            empty_lbl.pack(fill=tk.X)
            self._account_row_widgets.append(empty_lbl)
        else:
            for i, acc in enumerate(accounts):
                row_frame = tk.Frame(self._account_rows_frame, bg=c["surface"] if i % 2 == 0 else c["surface2"],
                                     height=32, cursor="hand2")
                row_frame.pack(fill=tk.X)
                row_frame.pack_propagate(False)

                bg_color = c["surface"] if i % 2 == 0 else c["surface2"]
                # 前 8 列为文本；第 9 列区域由下方独立按钮占据，此处不再放占位 Label
                values = [
                    (0,  str(acc["id"]),       40),
                    (40, acc["name"],          120),
                    (160, acc["channel_url"][:28] if len(acc["channel_url"]) > 28 else acc["channel_url"], 200),
                    (360, acc["fetch_mode"],    60),
                    (420, f"{acc['scan_interval']}m", 50),
                    (470, str(acc["fetch_limit"]), 50),
                    (520, "启用" if acc["enabled"] else "禁用", 60),
                    (580, "通知" if acc["notify_enabled"] else "静默", 60),
                ]
                for x, text, width in values:
                    lbl = tk.Label(row_frame, text=text, bg=bg_color,
                                   fg=c["text"], font=("Segoe UI", 8),
                                   anchor=tk.W, padx=6)
                    lbl.place(x=x, y=0, width=width, height=32)

                # 操作按钮区域
                for btn_idx, (btn_text, cmd) in enumerate([
                    ("编辑", lambda a=acc: self._edit_account(a)),
                    ("删除", lambda a=acc: self._delete_account(a)),
                    ("停用" if acc["enabled"] else "启用", lambda a=acc: self._toggle_account(a)),
                    ("测试", lambda a=acc: self._test_account(a)),
                ]):
                    is_edit = (btn_idx == 0)
                    btn_x = 640 + btn_idx * 45
                    btn = tk.Label(row_frame, text=btn_text, bg=c["accent"] if is_edit else c["surface2"],
                                   fg="#ffffff" if is_edit else c["text_secondary"],
                                   font=("Segoe UI", 7), anchor=tk.CENTER,
                                   cursor="hand2")
                    btn.place(x=btn_x, y=5, width=42, height=22)
                    btn.bind("<Button-1>", cmd)
                    normal_bg = c["accent"] if is_edit else c["surface2"]
                    hover_bg = c["accent_hover"] if is_edit else c["border"]
                    btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.configure(bg=h))
                    btn.bind("<Leave>", lambda e, b=btn, n=normal_bg: b.configure(bg=n))

                self._account_row_widgets.append(row_frame)

                # 鼠标悬停高亮
                def _on_enter(e, rf=row_frame):
                    rf.configure(bg=c["border"])
                def _on_leave(e, rf=row_frame, idx=i):
                    rf.configure(bg=c["surface"] if idx % 2 == 0 else c["surface2"])
                row_frame.bind("<Enter>", _on_enter)
                row_frame.bind("<Leave>", _on_leave)

        # 更新 Canvas 滚动区域
        self._account_rows_frame.update_idletasks()
        self._account_canvas.configure(scrollregion=self._account_canvas.bbox("all"))

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
                    feishu_message_mode=dialog.result.get("feishu_message_mode", "card_json"),
                    feishu_template_id=dialog.result.get("feishu_template_id"),
                    feishu_scan_template_id=dialog.result.get("feishu_scan_template_id"),
                    proxy_pool_id=dialog.result.get("proxy_pool_id"),
                    proxy_enabled=dialog.result.get("proxy_enabled", False),
                )
                self._append_log(f"账户添加成功: {dialog.result['name']} (id={account_id})")
                if _scheduler.is_running():
                    _scheduler.reload_jobs()
                self.refresh()
            except Exception as e:
                messagebox.showerror("错误", str(e))

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
                    feishu_message_mode=dialog.result.get("feishu_message_mode"),
                    feishu_template_id=dialog.result.get("feishu_template_id"),
                    feishu_scan_template_id=dialog.result.get("feishu_scan_template_id"),
                    proxy_pool_id=dialog.result.get("proxy_pool_id"),
                    proxy_enabled=dialog.result.get("proxy_enabled"),
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

    def _open_proxy_pools(self):
        ProxyPoolDialog(self.parent)

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


def _shutdown_existing_web_ui(port: int) -> bool:
    """尝试通过受保护的 shutdown API 关闭已运行的 Web UI。"""
    try:
        import urllib.request
        token = _db.get_api_token()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/system/shutdown",
            method="POST",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=2):
            pass
        # 等待端口释放（最多约 5s），给旧服务更充足的关闭时间，避免误判失败
        for _ in range(17):
            time.sleep(0.3)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=0.5)
            except Exception:
                return True
        return False
    except Exception:
        return False


# ── 独立窗口入口 ──────────────────────────────────────────────────────────

def run_standalone(force_restart: bool = False):
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

    if already_running and force_restart:
        print(f"\n♻️  检测到 Web UI 已在运行，正在强制重启: http://127.0.0.1:{port}")
        if not _shutdown_existing_web_ui(port):
            print("❌ 强制重启失败：无法关闭旧 Web UI 进程")
            return
        already_running = False

    if not already_running:
        import threading
        import http.server as _http

        from monitor_server import MonitorHandler
        server = _http.HTTPServer(("127.0.0.1", port), MonitorHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.8)
    else:
        print(f"\nℹ️  Web UI 已在运行: http://127.0.0.1:{port}")
        print("   如需加载最新代码，请执行: python monitor_ui.py --force-restart")

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
    import argparse
    parser = argparse.ArgumentParser(description="Launch Monitor Web UI")
    parser.add_argument("--force-restart", action="store_true", help="关闭旧的 Web UI 进程并重启")
    args = parser.parse_args()
    run_standalone(force_restart=args.force_restart)

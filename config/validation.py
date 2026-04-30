"""配置输入校验 — 钉钉签名密钥等配置项的合法性检查。"""

import re
import os
import shutil
from pathlib import Path


_BAOYU_MARKDOWN_TO_HTML_SCRIPT = (
    Path.home() / ".agents" / "skills" / "baoyu-markdown-to-html" / "scripts" / "main.ts"
)


def _has_baoyu_markdown_runner() -> bool:
    if str(os.environ.get("BAOYU_MARKDOWN_TO_HTML_COMMAND") or "").strip():
        return True
    if any(shutil.which(name) for name in ("bun.cmd", "bun.exe", "bun")):
        return True
    if os.name != "nt" and (shutil.which("npx.cmd") or shutil.which("npx")):
        return True
    return False


def normalize_dingtalk_sign_secret(value: str | None) -> str | None:
    """
    校验并归一化钉钉自定义机器人「加签」密钥。

    - None 或仅空白：视为未配置，返回 None。
    - 非空：须以 ``SEC`` 开头（与钉钉后台展示一致），长度在合理范围内。

    :raises ValueError: 非空但格式明显不正确时
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s.startswith("SEC"):
        raise ValueError("钉钉加签密钥须以 SEC 开头，请从钉钉机器人「加签」处完整复制")
    if len(s) < 16:
        raise ValueError("钉钉加签密钥过短，请检查是否复制完整")
    if len(s) > 512:
        raise ValueError("钉钉加签密钥过长")
    return s


def validate_wechat_renderer_config(cfg: dict) -> list[str]:
    """Validate the Markdown renderer portion of WeChat publish settings."""
    errors: list[str] = []
    cfg = cfg or {}

    valid_renderers = {"auto", "local", "baoyu", "baoyu-markdown-to-html"}
    renderer = str(cfg.get("wechat_markdown_renderer") or "auto").strip().lower()
    if renderer not in valid_renderers:
        errors.append(f"wechat_markdown_renderer 必须是 {sorted(valid_renderers)} 之一")
        return errors

    raw_script = str(cfg.get("wechat_baoyu_markdown_to_html_script") or "").strip()
    script_path = Path(raw_script).expanduser() if raw_script else _BAOYU_MARKDOWN_TO_HTML_SCRIPT
    if raw_script and not script_path.is_file():
        errors.append(f"wechat_baoyu_markdown_to_html_script 文件不存在: {script_path}")
    if renderer in {"baoyu", "baoyu-markdown-to-html"} and not script_path.is_file():
        errors.append(f"严格 baoyu 渲染需要可用的 baoyu-markdown-to-html 脚本: {script_path}")
    if renderer in {"baoyu", "baoyu-markdown-to-html"} and script_path.is_file() and not _has_baoyu_markdown_runner():
        errors.append("严格 baoyu 渲染需要本机 Bun，或通过 BAOYU_MARKDOWN_TO_HTML_COMMAND 配置可执行命令")

    return errors


def validate_wechat_config(cfg: dict) -> list[str]:
    """Validate WeChat Official Account publish settings."""
    errors: list[str] = []
    cfg = cfg or {}
    app_id = str(cfg.get("wechat_app_id") or "").strip()
    app_secret = str(cfg.get("wechat_app_secret") or "").strip()

    if not app_id:
        errors.append("wechat_app_id is required")
    elif not re.match(r"^wx[a-zA-Z0-9]{16}$", app_id):
        errors.append("wechat_app_id 格式不正确，应为 wx 开头 18 位字母数字")

    if not app_secret:
        errors.append("wechat_app_secret is required")
    elif len(app_secret) < 16:
        errors.append("wechat_app_secret 过短")

    valid_themes = {"default", "grace", "simple", "modern"}
    theme = str(cfg.get("wechat_default_theme") or "default")
    if theme not in valid_themes:
        errors.append(f"wechat_default_theme 必须是 {sorted(valid_themes)} 之一")

    valid_colors = {
        "blue", "green", "vermilion", "yellow", "purple", "sky",
        "rose", "olive", "black", "gray", "pink", "red", "orange",
    }
    color = str(cfg.get("wechat_default_color") or "blue")
    is_hex_color = re.match(r"^#[0-9a-fA-F]{6}$", color) is not None
    if color not in valid_colors and not is_hex_color:
        errors.append(f"wechat_default_color 必须是 {sorted(valid_colors)} 之一或 #RRGGBB")

    try:
        monthly_limit = int(cfg.get("wechat_publish_monthly_limit", 4))
    except (TypeError, ValueError):
        errors.append("wechat_publish_monthly_limit 必须是整数，0 表示不限制")
    else:
        if monthly_limit < 0 or monthly_limit > 999:
            errors.append("wechat_publish_monthly_limit 必须在 0 到 999 之间，0 表示不限制")

    errors.extend(validate_wechat_renderer_config(cfg))

    return errors

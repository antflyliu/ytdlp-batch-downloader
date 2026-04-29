"""配置输入校验 — 钉钉签名密钥等配置项的合法性检查。"""

import re


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

    return errors

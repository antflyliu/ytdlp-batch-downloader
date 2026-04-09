"""
账户等配置的输入校验（与存储层配合，非法输入在写入前拒绝）。
"""


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

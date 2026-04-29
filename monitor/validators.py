"""账户等配置的输入校验（向后兼容重导出，见 config/validation.py）。"""
from config.validation import normalize_dingtalk_sign_secret

__all__ = ["normalize_dingtalk_sign_secret"]

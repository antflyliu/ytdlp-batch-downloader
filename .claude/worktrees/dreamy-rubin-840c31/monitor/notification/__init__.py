"""
monitor.notification — notification subpackage
Re-exports all public APIs from submodules for backward compatibility.
"""

from .base import (
    _file_handler,     # internal: used by monitor/notifier.py
    _file_log,        # internal: used by monitor/notifier.py
    _format_duration_sec,
    _sanitize_url_for_md,
    FEISHU_MODE_CARD,
    FEISHU_MODE_TEMPLATE,
    Platform,
    setup_file_logging,
)

from .dingtalk import (
    finalize_dingtalk_webhook_url,
)

from .renderers import (
    _log_result,           # internal: used by monitor/notifier.py
    _redact_webhook_url,   # internal: used by monitor/notifier.py
    _send_webhook,         # internal: used by monitor/notifier.py
    build_notify_payload,
)

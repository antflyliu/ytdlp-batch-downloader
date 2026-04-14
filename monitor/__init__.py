"""
YouTube Monitor Package
"""
import sys

# Import monitor.db as a package (not db.py as a module).
# This loads monitor/db/__init__.py which:
#   - Loads db.py (the module)
#   - Registers sys.modules["monitor.db"] and sys.modules["monitor._db"]
#   - Loads subpackages (connection, db_core, migrations, crypto)
import monitor.db as _db_mod

# Register monitor._db alias for backward compatibility with code using
# "from monitor._db import ..." or "import monitor._db"
sys.modules["monitor._db"] = _db_mod

from monitor.scheduler import (
    start, stop, is_running, reload_jobs, get_next_run_times,
    set_global_feishu_url, set_global_dingtalk_url, set_global_wecom_url,
)
from monitor.fetcher import YouTubeFetcher
from monitor.detector import detect_new
from monitor.db import (
    init_db,
    list_accounts,
    get_account,
    add_account,
    update_account,
    delete_account,
    get_account_stats,
    get_recent_events,
)

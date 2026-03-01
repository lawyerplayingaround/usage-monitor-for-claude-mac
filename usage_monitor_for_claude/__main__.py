"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import traceback

from .app import UsageMonitorForClaude, crash_log

try:
    app = UsageMonitorForClaude()
    app.run()
except Exception:
    crash_log(traceback.format_exc())

"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import logging
import subprocess
import sys
import traceback

from usage_monitor_for_claude.app import UsageMonitorForClaude, crash_log

if not getattr(sys, 'frozen', False):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

try:
    app = UsageMonitorForClaude()
    app.run()

    if app.restart_requested:
        if getattr(sys, 'frozen', False):
            subprocess.Popen(
                [sys.executable],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                [sys.executable, '-m', 'usage_monitor_for_claude'],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
except Exception:
    crash_log(traceback.format_exc())

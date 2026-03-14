"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import logging
import os
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
            # Clear PyInstaller's internal env vars so the new
            # instance extracts to a fresh temp directory instead
            # of reusing the current (soon-to-be-deleted) one.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEI'))}
            subprocess.Popen(
                [sys.executable],
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(
                [sys.executable, '-m', 'usage_monitor_for_claude'],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
except Exception:
    crash_log(traceback.format_exc())

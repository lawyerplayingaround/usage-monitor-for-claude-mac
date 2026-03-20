"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import traceback

# Per-Monitor V2 must be set before pywebview's legacy SetProcessDPIAware() call,
# which only sets SYSTEM_DPI_AWARE and breaks native menu hover at high DPI.
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))

import webview  # type: ignore[import-untyped]  # no type stubs available

from usage_monitor_for_claude.app import UsageMonitorForClaude, crash_log
from usage_monitor_for_claude.single_instance import ensure_single_instance, release_instance_lock

if not getattr(sys, 'frozen', False):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

_result: dict = {}


def _run_app() -> None:
    """Run the tray application in a background thread (called by webview)."""
    try:
        app = UsageMonitorForClaude()
        app.run()
        _result['app'] = app
    except Exception:
        crash_log(traceback.format_exc())
    finally:
        # Destroy all webview windows (keeper + any open popups) so
        # webview.start() on the main thread returns.
        for win in list(webview.windows):
            try:
                win.destroy()
            except Exception:
                pass


try:
    if not ensure_single_instance():
        sys.exit(0)

    # pywebview requires the main thread for its GUI event loop.
    # A persistent hidden window keeps the loop alive while the
    # tray app and popup windows are managed in background threads.
    webview.create_window('', html='', hidden=True)
    webview.start(func=_run_app)

    app = _result.get('app')
    if app and app.restart_requested:
        release_instance_lock()

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

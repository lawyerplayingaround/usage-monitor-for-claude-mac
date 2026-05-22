"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import traceback

_verbose = '--verbose' in sys.argv

# In frozen builds (console=False), stdout/stderr go nowhere.
# --verbose attaches a console so diagnostics are visible.
if _verbose and getattr(sys, 'frozen', False):
    from usage_monitor_for_claude.verbose import setup_console
    setup_console()

if sys.platform == 'win32':
    import ctypes
    # Per-Monitor V2 must be set before pywebview's legacy SetProcessDPIAware() call,
    # which only sets SYSTEM_DPI_AWARE and breaks native menu hover at high DPI.
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))

if _verbose:
    from usage_monitor_for_claude.verbose import print_startup_diagnostics
    print_startup_diagnostics()

import webview  # type: ignore[import-untyped]  # no type stubs available

from usage_monitor_for_claude.app import UsageMonitorForClaude, crash_log
from usage_monitor_for_claude.single_instance import ensure_single_instance, release_instance_lock

if _verbose:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-5s %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )

_result: dict = {}


def _verbose_step(label: str) -> None:
    """Print a startup progress step in verbose mode."""
    if _verbose:
        print(f'  [startup] {label}', flush=True)


def _run_app() -> None:
    """Run the tray application in a background thread (called by webview)."""
    try:
        if _verbose:
            from usage_monitor_for_claude.verbose import print_runtime_diagnostics
            print_runtime_diagnostics()

        _verbose_step('UsageMonitorForClaude()...')
        app = UsageMonitorForClaude()
        _verbose_step('UsageMonitorForClaude()... OK')

        _verbose_step('app.run...')
        app.run()
        _result['app'] = app
    except Exception:
        _verbose_step(f'CRASH: {traceback.format_exc()}')
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
    _verbose_step('ensure_single_instance...')
    if not ensure_single_instance():
        _verbose_step('another instance is running, exiting')
        sys.exit(0)
    _verbose_step('ensure_single_instance... OK')

    if sys.platform == 'darwin':
        # AppKit requires NSStatusItem and any other GUI object to live on the
        # main thread, so pystray runs in-thread here.  The HTML popup is
        # currently disabled on macOS (Phase 3 of the port reintroduces it).
        _verbose_step('running pystray on main thread (macOS)...')
        _run_app()
        _verbose_step('pystray.run returned')
    else:
        # pywebview requires the main thread for its GUI event loop.
        # A persistent hidden window keeps the loop alive while the
        # tray app and popup windows are managed in background threads.
        _verbose_step('webview.create_window...')
        webview.create_window('', html='', hidden=True)
        _verbose_step('webview.create_window... OK')

        _verbose_step('webview.start...')
        webview.start(func=_run_app)
        _verbose_step('webview.start returned')

    app = _result.get('app')
    if app and app.restart_requested:
        release_instance_lock()

        # CREATE_NO_WINDOW only exists on Windows; on POSIX systems no console
        # is attached to a detached subprocess, so the flag is not needed.
        popen_kwargs: dict = {}
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        if getattr(sys, 'frozen', False):
            # Clear PyInstaller's internal env vars so the new
            # instance extracts to a fresh temp directory instead
            # of reusing the current (soon-to-be-deleted) one.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEI'))}
            subprocess.Popen([sys.executable], env=env, **popen_kwargs)
        else:
            subprocess.Popen([sys.executable, '-m', 'usage_monitor_for_claude'], **popen_kwargs)
except Exception:
    crash_log(traceback.format_exc())

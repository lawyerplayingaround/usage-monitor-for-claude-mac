"""Entry point for ``python -m usage_monitor_for_claude``."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

from usage_monitor_for_claude.instance_id import parse_config_dir

# --verbose triggers Win32-only diagnostics that read the registry and
# attach a console.  On macOS the unfrozen run already prints to stderr
# and the frozen .app has nothing to attach to, so the flag is a no-op
# off Windows.  Gating the import here prevents verbose.py's
# ``import winreg`` (Windows-only stdlib) from crashing the launch on
# macOS when the user passes --verbose.
_verbose = '--verbose' in sys.argv and sys.platform == 'win32'

# --config-dir selects which Claude account to monitor. It must be
# resolved into CLAUDE_CONFIG_DIR before any other package import:
# api, settings, verbose and i18n all read the variable at import or
# first-use time. Keep every other package import below this block.
_config_dir = parse_config_dir(sys.argv)
if _config_dir is not None:
    _config_path = Path(_config_dir)
    if not _config_path.is_dir():
        _config_error = f'--config-dir directory does not exist:\n{_config_dir}'
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(0, _config_error, 'Usage Monitor for Claude - Error', 0x10)
        else:
            print(_config_error, file=sys.stderr)
        sys.exit(1)
    os.environ['CLAUDE_CONFIG_DIR'] = str(_config_path.resolve())

# In frozen builds (console=False), stdout/stderr go nowhere.
# --verbose attaches a console so diagnostics are visible.
if _verbose and getattr(sys, 'frozen', False):
    from usage_monitor_for_claude.verbose import setup_console
    setup_console()

if sys.platform == 'win32':
    # Per-Monitor V2 must be set before pywebview's legacy SetProcessDPIAware() call,
    # which only sets SYSTEM_DPI_AWARE and breaks native menu hover at high DPI.
    # The API exists only from Windows 10 1703; ctypes raises AttributeError for a
    # missing export, which must not kill startup - pywebview's legacy call is the
    # fallback on older systems.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))
    except AttributeError:
        pass

if _verbose:
    from usage_monitor_for_claude.verbose import print_startup_diagnostics
    print_startup_diagnostics()

# pywebview is the popup host on Windows; on macOS the popup runs through
# the native ``_macos_popup`` module instead, and pywebview (with its bottle
# / clr_loader dependencies) is excluded from the PyInstaller bundle.
if sys.platform == 'win32':
    import webview  # type: ignore[import-untyped]  # no type stubs available

    # The notification identity is a Win32 concept (AppUserModelID) and the
    # module imports winreg at module level, so it only exists on Windows.
    from usage_monitor_for_claude.notification_identity import register_notification_identity

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
        # webview.start() on the main thread returns.  Only needed on the
        # Windows branch - macOS does not own a webview event loop.
        if sys.platform == 'win32':
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

    if sys.platform == 'win32':
        # Give notifications a fixed logo instead of the live tray icon.
        # Must run before any window is created (AppUserModelID requirement).
        _verbose_step('register_notification_identity...')
        register_notification_identity()

    if sys.platform == 'darwin':
        # AppKit requires NSStatusItem and other GUI objects to live on the
        # main thread, and pystray's _darwin backend runs NSApp.run() on the
        # calling thread.  The popup window is hosted by a native NSPanel +
        # WKWebView (see _macos_popup) and dispatched onto the same main
        # runloop via NSOperationQueue from popup worker threads.
        _verbose_step('running pystray on main thread (macOS)...')
        _run_app()
        if _result.get('app'):
            _result['app'].loop_exited = True
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

        passthrough_args = []
        if _config_dir is not None:
            passthrough_args.append(f'--config-dir={os.environ["CLAUDE_CONFIG_DIR"]}')
        if _verbose:
            passthrough_args.append('--verbose')

        if getattr(sys, 'frozen', False):
            # Clear PyInstaller's internal env vars so the new
            # instance extracts to a fresh temp directory instead
            # of reusing the current (soon-to-be-deleted) one.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('_PYI_', '_MEI'))}
            subprocess.Popen([sys.executable, *passthrough_args], env=env, **popen_kwargs)
        else:
            subprocess.Popen([sys.executable, '-m', 'usage_monitor_for_claude', *passthrough_args], **popen_kwargs)
except Exception:
    crash_log(traceback.format_exc())

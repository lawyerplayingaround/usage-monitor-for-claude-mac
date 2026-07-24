"""
CI probe: real WebView2 popup, synthetic data
=============================================

Reproduces the missing-footer report on Windows by running the actual
``UsagePopup`` host against a fixed synthetic snapshot on a CI runner,
then dumping the evidence needed to localize the bug:

* every ``report_height`` call (timestamp + height),
* every ``_resize_and_position`` call and any exception it raises,
* the final Win32 window rect and per-window DPI,
* the popup DOM state (footer class/display/rect, body scrollHeight).

Diagnostic only - runs from the ``debug/footer-probe`` branch, never
ships in a release.  All data is synthetic.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import threading
import time
import traceback
from types import SimpleNamespace

import webview

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from usage_monitor_for_claude import popup as popup_mod
from usage_monitor_for_claude.cache import CacheSnapshot

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'probe_log.txt')
_log_lines: list[str] = []
_log_lock = threading.Lock()


def log(message: str) -> None:
    line = f'[{time.monotonic():10.3f}] {message}'
    with _log_lock:
        _log_lines.append(line)
    print(line, flush=True)


def flush_log() -> None:
    with _log_lock:
        with open(LOG_PATH, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(_log_lines) + '\n')


def make_snapshot() -> CacheSnapshot:
    now = time.time()
    usage = {
        'five_hour': {'utilization': 18, 'resets_at': '2026-07-24T17:00:00-03:00'},
        'seven_day': {'utilization': 12, 'resets_at': '2026-07-30T18:00:00-03:00'},
        'seven_day_fable': {'utilization': 16, 'resets_at': '2026-07-30T18:00:00-03:00'},
    }
    profile = {'account': {'email': 'user@example.com'}, 'organization': {'organization_type': 'claude_max'}}
    return CacheSnapshot(usage=usage, profile=profile, last_success_time=now - 30, refreshing=False, last_error=None, version=3)


def install_instrumentation() -> None:
    """Wrap the height/resize path with logging without touching app code."""
    original_report = popup_mod._PopupApi.report_height
    original_resize = popup_mod.UsagePopup._resize_and_position

    def logged_report(self, height):
        log(f'report_height({height}) last={self._popup._last_height} shown={self._popup._shown}')
        return original_report(self, height)

    def logged_resize(self, height):
        try:
            result = original_resize(self, height)
            rect = get_window_rect(self._popup_hwnd)
            log(f'_resize_and_position({height}) OK rect={rect}')
            return result
        except Exception:
            log('_resize_and_position(%s) RAISED:\n%s' % (height, traceback.format_exc()))
            raise

    popup_mod._PopupApi.report_height = logged_report
    popup_mod.UsagePopup._resize_and_position = logged_resize
    popup_mod.find_installations = lambda: [SimpleNamespace(name='CLI', version='2.1.218')]


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


PROBE_JS = """
(function () {
    var f = document.getElementById('statusSection');
    var r = f ? f.getBoundingClientRect() : null;
    return JSON.stringify({
        readyState: document.readyState,
        elsDefined: typeof els !== 'undefined' && !!els,
        apiKeys: window.pywebview && window.pywebview.api ? Object.keys(window.pywebview.api) : null,
        bodyScrollHeight: document.body.scrollHeight,
        innerHeight: window.innerHeight,
        innerWidth: window.innerWidth,
        dpr: window.devicePixelRatio,
        bodyClass: document.body.className,
        footerClass: f ? f.className : null,
        footerDisplay: f ? getComputedStyle(f).display : null,
        footerRect: r ? {top: r.top, height: r.height} : null,
        statusText: (document.getElementById('statusText') || {}).textContent,
        appVersion: (document.getElementById('appVersion') || {}).textContent,
        visibleSections: Array.prototype.map.call(document.querySelectorAll('section.visible, footer.visible'), function (e) { return e.id; }),
    });
})()
"""


def probe_main() -> None:
    try:
        from importlib.metadata import version as pkg_version
        log(f'probe start: pywebview={pkg_version("pywebview")} python={sys.version.split()[0]}')

        app = SimpleNamespace(
            cache=SimpleNamespace(snapshot=make_snapshot()),
            _next_poll_time=time.time() + 150,
            _seconds_until_next_reset=lambda: 3600.0,
        )

        def run_popup():
            try:
                popup_mod.UsagePopup(app)
            except Exception:
                log('UsagePopup RAISED:\n' + traceback.format_exc())

        threading.Thread(target=run_popup, daemon=True).start()

        # Give the popup time to create, load, report, resize and show.
        # webview.windows[0] is the hidden dummy from __main__ parity below;
        # the popup is the second window once created.
        for second in range(12):
            time.sleep(1)
            if len(webview.windows) < 2:
                log(f't+{second + 1}s: popup window not in webview.windows yet')
                continue
            wv = webview.windows[1]
            try:
                state = wv.evaluate_js(PROBE_JS)
                hwnd = wv.native.Handle.ToInt32() if wv.native else 0
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) if hwnd else 0
                log(f't+{second + 1}s: rect={get_window_rect(hwnd)} dpi={dpi} dom={state}')
            except Exception:
                log(f't+{second + 1}s: probe evaluate_js failed:\n' + traceback.format_exc())

        log('probe done')
    except Exception:
        log('probe_main RAISED:\n' + traceback.format_exc())
    finally:
        flush_log()
        os._exit(0)


if __name__ == '__main__':
    install_instrumentation()
    webview.create_window('', html='', hidden=True)
    webview.start(func=probe_main)

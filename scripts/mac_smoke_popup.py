"""Mac smoke test: launch the app and exercise the popup programmatically.

Spawns a background thread that, after waiting for the tray icon to be
ready, calls ``on_show_popup``, introspects the popup state via the
existing bridge to confirm it rendered, then cycles through:

1. open
2. wait for content load
3. introspect DOM (popup width, visible sections)
4. force-close
5. wait
6. reopen
7. force-close
8. quit

Run from the project root:

    source .venv/bin/activate
    python scripts/mac_smoke_popup.py

Output is annotated with ``[smoke]`` lines.  Functional success is
indicated by all introspection checks passing (look for
``CHECK PASSED`` / ``CHECK FAILED`` lines).
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

# Make the package importable when running this file as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from usage_monitor_for_claude.app import UsageMonitorForClaude  # noqa: E402
from usage_monitor_for_claude import popup as popup_mod  # noqa: E402

_OPEN_DELAY = 3.0
_LOAD_WAIT = 2.5
_CLOSE_WAIT = 1.5
_SHOT_DIR = ROOT / 'scripts' / 'screenshots'


def _capture(name: str) -> None:
    """Capture a PNG screenshot of the entire display via ``screencapture``."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = _SHOT_DIR / f'{name}.png'
    try:
        subprocess.run(['/usr/sbin/screencapture', '-x', str(out)], check=True, timeout=5)
        print(f'[smoke] screenshot -> {out}', flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f'[smoke] screenshot failed: {exc}', flush=True)

# Test-only capture: wrap UsagePopup.__init__ so the smoke driver can grab the
# latest live popup instance without polluting production code.
_LIVE_POPUPS: list[popup_mod.UsagePopup] = []
_original_popup_init = popup_mod.UsagePopup.__init__


def _capturing_init(self: popup_mod.UsagePopup, app: UsageMonitorForClaude) -> None:
    _LIVE_POPUPS.append(self)
    try:
        _original_popup_init(self, app)
    finally:
        if self in _LIVE_POPUPS:
            _LIVE_POPUPS.remove(self)


popup_mod.UsagePopup.__init__ = _capturing_init  # type: ignore[method-assign]  # smoke-test instrumentation


def _current_popup() -> popup_mod.UsagePopup | None:
    """Return the most recently constructed live popup, or None."""
    return _LIVE_POPUPS[-1] if _LIVE_POPUPS else None


def _introspect_popup() -> dict[str, object]:
    """Query the running popup's DOM via ``evaluateJavaScript:completionHandler:``.

    Returns a dict with ``scroll_height``, ``has_usage``, ``has_status``,
    and ``title`` keys, or ``{'error': ...}`` if the popup is not live.
    """
    if sys.platform != 'darwin':
        return {}

    popup = _current_popup()
    if popup is None or not getattr(popup, '_running', False):
        return {'error': 'popup_not_running'}

    controller = getattr(popup, '_controller', None)
    if controller is None:
        return {'error': 'controller_missing'}

    probe = (
        '(function () { return JSON.stringify({'
        ' scroll_height: document.body.scrollHeight,'
        ' has_usage: !!document.querySelector("#usageSection.visible"),'
        ' has_status: !!document.querySelector("#statusSection.visible"),'
        ' install_visible: !!document.querySelector("#installSection.visible"),'
        ' title: document.getElementById("title") ? document.getElementById("title").textContent : ""'
        '}); })()'
    )
    raw = controller.evaluate_js_sync(probe, timeout=3.0)
    if raw is None:
        return {'error': 'js_no_response'}
    import json
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return {'error': 'js_unparseable', 'raw': str(raw)}


def _check(label: str, condition: bool, detail: str = '') -> bool:
    status = 'CHECK PASSED' if condition else 'CHECK FAILED'
    suffix = f' ({detail})' if detail else ''
    print(f'[smoke] {status}: {label}{suffix}', flush=True)
    return condition


def _smoke_runner(app: UsageMonitorForClaude) -> None:
    """Background driver that exercises the popup lifecycle."""
    try:
        time.sleep(_OPEN_DELAY)

        # ---------- Cycle 1: open, introspect, close ----------
        _capture('00_baseline_tray_only')

        print('[smoke] cycle 1 - on_show_popup', flush=True)
        app.on_show_popup()
        time.sleep(_LOAD_WAIT)

        _capture('01_popup_open')

        popup = _current_popup()
        _check('popup ref captured', popup is not None)
        _check('popup running', bool(popup and popup._running))
        _check('popup shown', bool(popup and popup._shown))

        info = _introspect_popup()
        print(f'[smoke] introspection result: {info}', flush=True)
        _check('JS bridge responded', bool(info))
        scroll_height = info.get('scroll_height') or 0
        _check(
            'content rendered (scroll_height > 0)', bool(scroll_height and int(scroll_height) > 0),
            detail=f'scroll_height={scroll_height}',
        )
        title = info.get('title') or ''
        _check('title injected', bool(title), detail=f'title={title!r}')

        # Geometry + dismiss monitor checks - confirm position vs. menu bar icon
        # and that NSEvent monitors are installed for click-outside / ESC.
        if popup is not None:
            controller = getattr(popup, '_controller', None)
            if controller is not None:
                _check('global mouse monitor installed', controller._global_monitor is not None)
                _check('local mouse monitor installed', controller._local_monitor is not None)
                _check('key (ESC) monitor installed', controller._key_monitor is not None)

                panel_frame = controller._panel.frame() if controller._panel is not None else None
                from usage_monitor_for_claude._macos_popup import status_item_screen_frame
                icon_frame = status_item_screen_frame(controller._status_item)
                if panel_frame is not None and icon_frame is not None:
                    print(f'[smoke] icon_frame  = {icon_frame}', flush=True)
                    print(f'[smoke] panel_frame = ({panel_frame.origin.x}, {panel_frame.origin.y}, '
                          f'{panel_frame.size.width}, {panel_frame.size.height})', flush=True)
                    icon_x, icon_y, icon_w, _icon_h = icon_frame
                    icon_center_x = icon_x + icon_w / 2
                    panel_center_x = panel_frame.origin.x + panel_frame.size.width / 2
                    _check(
                        'panel center near icon center (|delta| < icon_width)',
                        abs(panel_center_x - icon_center_x) < icon_w * 4,
                        detail=f'delta={panel_center_x - icon_center_x:.1f}',
                    )
                    _check(
                        'panel below icon (top edge < icon bottom)',
                        panel_frame.origin.y + panel_frame.size.height <= icon_y + 1,
                        detail=f'panel_top={panel_frame.origin.y + panel_frame.size.height:.1f}, icon_y={icon_y:.1f}',
                    )

        print('[smoke] cycle 1 - close via popup._close()', flush=True)
        if popup is not None:
            popup._close()
        time.sleep(_CLOSE_WAIT)

        _capture('02_after_close')

        # ---------- Cycle 2: re-open after dismiss ----------
        print('[smoke] cycle 2 - on_show_popup again', flush=True)
        app.on_show_popup()
        time.sleep(_LOAD_WAIT)

        _capture('03_reopen')

        popup2 = _current_popup()
        _check('re-open produced new popup', popup2 is not None and popup2 is not popup)
        _check('re-open popup shown', bool(popup2 and popup2._shown))

        print('[smoke] cycle 2 - close', flush=True)
        if popup2 is not None:
            popup2._close()
        time.sleep(_CLOSE_WAIT)

        print('[smoke] calling on_quit', flush=True)
        app.on_quit()
    except Exception:
        print('[smoke] CRASH:', flush=True)
        traceback.print_exc()
        try:
            app.on_quit()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    print(f'[smoke] platform={sys.platform}', flush=True)
    print('[smoke] creating UsageMonitorForClaude...', flush=True)
    app = UsageMonitorForClaude()
    print('[smoke] starting smoke driver thread...', flush=True)
    threading.Thread(target=_smoke_runner, args=(app,), daemon=True).start()
    print('[smoke] entering app.run() (blocks on NSApp runloop)', flush=True)
    app.run()
    print('[smoke] app.run() returned cleanly', flush=True)


if __name__ == '__main__':
    main()

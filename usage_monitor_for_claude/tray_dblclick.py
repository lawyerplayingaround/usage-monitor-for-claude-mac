"""
Double-click handling for the tray icon
========================================

Lets the menu bar / system tray icon serve two purposes at once:
single-click opens the usage popup, double-click launches the full
Claude Desktop app (falling back to ``claude.ai`` if the desktop app
is not installed).

The platforms ship the messaging in opposite shapes and we accommodate
both inside this one module:

* **Windows.**  ``pystray`` handles ``WM_LBUTTONUP`` (single click) and
  ``WM_RBUTTONUP`` (menu) but ignores ``WM_LBUTTONDBLCLK``.
  :class:`IconWithDoubleClick` subclasses ``pystray.Icon`` and overrides
  ``_on_notify`` to add the missing case.  ``Shell_NotifyIcon`` delivers
  ``WM_LBUTTONUP → WM_LBUTTONDBLCLK → WM_LBUTTONUP`` for a double-click
  sequence, so the first ``LBUTTONUP`` is deferred via a
  ``threading.Timer``; if a ``LBUTTONDBLCLK`` arrives within the
  OS-configured double-click time, the timer is cancelled and the
  double-click action runs.  The trailing second ``LBUTTONUP`` is
  silenced by a short post-double-click guard window.

* **macOS.**  ``pystray._darwin`` calls
  ``NSStatusItem.setMenu_(nsmenu)`` whenever its menu changes, which
  causes the menu to open on every click and prevents the button's
  action selector from firing.  :func:`install_macos_dblclick_handler`
  patches ``_update_menu`` so the menu is immediately detached
  (``setMenu_(None)``) after each rebuild, then swaps the button's
  target/action for an Objective-C dispatcher that distinguishes
  single from double left-click via ``NSEvent.clickCount``.  Right-click
  (and Ctrl+left-click) re-attaches the saved ``NSMenu`` via
  ``popUpMenuPositioningItem:atLocation:inView:`` so the menu remains
  reachable.

:func:`launch_claude_desktop` provides the shared "open Claude Desktop"
action.  On Windows it uses the ``claude:`` URL handler registered by
the MSIX install (with an EXE-path fallback read from
``HKCR\\claude\\shell\\open\\command``).  On macOS it uses
``open claude://`` then ``open -b com.anthropic.claudefordesktop``.
Both branches fall back to launching ``https://claude.ai/`` in the
default browser when nothing else is available.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Callable

import pystray  # type: ignore[import-untyped]  # no type stubs available

if sys.platform == 'win32':
    import winreg

__all__ = ['IconWithDoubleClick', 'install_macos_dblclick_handler', 'launch_claude_desktop']

# Maximum time after the double-click event during which the trailing
# trailing single-click event (released after the double-click) is
# suppressed.  The OS-default double-click interval is around 500 ms;
# 700 ms gives us comfortable margin even when the user has slowed it
# down.
_DBLCLICK_GUARD_S = 0.7

# How long to defer the single-click action, waiting to see if a
# double-click arrives.  Must be >= the user's configured double-click
# interval, otherwise slow double-clicks are missed.  480 ms (just under
# the Windows default of 500 ms) keeps the popup feeling snappy on plain
# single clicks while still catching typical double-clicks.
_SINGLE_CLICK_DEFER_S = 0.48

# Common fallback for both platforms when no Claude Desktop install is
# found.
_CLAUDE_WEB_FALLBACK = 'https://claude.ai/'

# Click classification kinds returned by the macOS dispatcher's
# ``handleClick_`` and consumed by ``_dispatch``.  Strings rather than
# enums to keep the dispatcher dependency-free (no functools/Enum import).
_CLICK_MENU = 'menu'
_CLICK_SINGLE = 'single'
_CLICK_DOUBLE = 'double'
_CLICK_IGNORE = 'ignore'


# ---------------------------------------------------------------------------
# Windows: subclassed pystray.Icon
# ---------------------------------------------------------------------------

if sys.platform == 'win32':
    # Win32 message constants.  Hard-coded so we do not depend on pystray's
    # private ``_util.win32`` module (which could move between versions);
    # the values are stable Win32 API constants - they will never change.
    _WM_LBUTTONUP = 0x0202
    _WM_LBUTTONDBLCLK = 0x0203

    _CLAUDE_URI_REG_KEY = r'claude\shell\open\command'


    class IconWithDoubleClick(pystray.Icon):  # type: ignore[misc]  # subclassing an untyped base class
        """``pystray.Icon`` subclass that distinguishes single from double click.

        Parameters
        ----------
        on_double_click : Callable[[], None] or None
            Invoked (in a background thread) when the user double-left-clicks
            the tray icon.  ``None`` disables the double-click behavior and
            the icon behaves identically to a vanilla ``pystray.Icon``.

        All other positional and keyword arguments are forwarded to the base
        ``pystray.Icon`` constructor unchanged.
        """

        def __init__(
            self,
            *args: Any,
            on_double_click: Callable[[], None] | None = None,
            **kwargs: Any,
        ) -> None:
            super().__init__(*args, **kwargs)
            self._on_double_click_cb: Callable[[], None] | None = on_double_click
            self._pending_single_click: threading.Timer | None = None
            self._last_dblclick_at: float = 0.0
            self._click_state_lock = threading.Lock()

        # pystray's internal handler - override to inject double-click logic.
        # The signature matches ``pystray._win32.Icon._on_notify(wparam, lparam)``.
        def _on_notify(self, wparam: int, lparam: int) -> None:  # type: ignore[override]  # overriding pystray internal hook
            if lparam == _WM_LBUTTONUP:
                self._handle_lbutton_up()
                return

            if lparam == _WM_LBUTTONDBLCLK and self._on_double_click_cb is not None:
                self._handle_lbutton_dblclk()
                return

            # Anything else - right-click menu, etc. - falls through to base.
            super()._on_notify(wparam, lparam)

        def _handle_lbutton_up(self) -> None:
            with self._click_state_lock:
                # If the user just double-clicked, the OS will deliver one
                # more LBUTTONUP for the second mouse-up.  Swallow it.
                if time.time() - self._last_dblclick_at < _DBLCLICK_GUARD_S:
                    return

                # Cancel any earlier-scheduled single-click timer.
                if self._pending_single_click is not None:
                    self._pending_single_click.cancel()

                # If no double-click handler is registered, fire single-click
                # immediately so behavior matches vanilla pystray.
                if self._on_double_click_cb is None:
                    self._pending_single_click = None
                    fire_now = True
                else:
                    timer = threading.Timer(_SINGLE_CLICK_DEFER_S, self._fire_single_click)
                    timer.daemon = True
                    self._pending_single_click = timer
                    timer.start()
                    fire_now = False

            if fire_now:
                self._fire_single_click()

        def _handle_lbutton_dblclk(self) -> None:
            with self._click_state_lock:
                if self._pending_single_click is not None:
                    self._pending_single_click.cancel()
                    self._pending_single_click = None
                self._last_dblclick_at = time.time()
                callback = self._on_double_click_cb

            if callback is None:
                return
            # Run on a background thread - the callback may take a while
            # (launching another process, registry reads, etc.) and we must
            # not block the message pump.
            threading.Thread(target=_safe_invoke, args=(callback,), daemon=True).start()

        def _fire_single_click(self) -> None:
            with self._click_state_lock:
                self._pending_single_click = None
            # ``self()`` invokes the default menu item, same as the base class.
            _safe_invoke(self)

else:
    # On non-Windows we still expose the name so a static ``from
    # .tray_dblclick import IconWithDoubleClick`` does not crash at
    # import time.  ``app.py`` only uses it under
    # ``if sys.platform == 'win32':``.
    IconWithDoubleClick = None  # type: ignore[assignment,misc]  # stub for non-win32 platforms


# ---------------------------------------------------------------------------
# macOS: monkey-patch an existing pystray._darwin.Icon
# ---------------------------------------------------------------------------

if sys.platform == 'darwin':
    import AppKit  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
    import Foundation  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
    import objc  # type: ignore[import-untyped]  # pyobjc has no type stubs


    class _ClickDispatcher(Foundation.NSObject):
        """Objective-C target that classifies clicks coming from the status button.

        Defined at module scope (rather than inside the installer function)
        because the Objective-C runtime rejects re-registration of the same
        class name - which would otherwise happen the second time the
        installer is called (e.g. across tests).
        """

        def initWithIcon_single_double_(self, host_icon: Any, single: Callable[[], None], double: Callable[[], None]) -> Any:
            self = objc.super(_ClickDispatcher, self).init()
            if self is None:
                return None
            self._host_icon = host_icon
            self._single = single
            self._double = double
            self._pending_timer = None
            self._lock = threading.Lock()
            return self

        def handleClick_(self, _sender: Any) -> None:
            event = AppKit.NSApp.currentEvent()
            if event is None:
                return

            event_type = event.type()
            modifier_flags = event.modifierFlags()
            click_count = event.clickCount()

            is_right_click = event_type in (
                AppKit.NSEventTypeRightMouseDown,
                AppKit.NSEventTypeRightMouseUp,
            )
            is_ctrl_left = (
                event_type in (AppKit.NSEventTypeLeftMouseDown, AppKit.NSEventTypeLeftMouseUp)
                and bool(modifier_flags & AppKit.NSEventModifierFlagControl)
            )

            if is_right_click or is_ctrl_left:
                kind = _CLICK_MENU
            elif click_count == 1:
                kind = _CLICK_SINGLE
            elif click_count == 2:
                kind = _CLICK_DOUBLE
            else:
                # 3rd, 4th, ... click in the same sequence - the user
                # already got their double-click action; ignore.
                kind = _CLICK_IGNORE

            self._dispatch(kind)

        @objc.python_method
        def _dispatch(self, kind: str) -> None:
            """Apply the timer / callback policy for a classified click.

            Split out from ``handleClick_`` so unit tests can exercise the
            single / double / triple branches without constructing real
            ``NSEvent`` objects.  ``NSEvent.clickCount`` is OS-managed and
            respects the user's System Settings double-click interval - a
            new click after the interval restarts at 1, so this method
            relies on the classification alone.

            Decorated with ``@objc.python_method`` so pyobjc does not
            mistake it for an Objective-C selector and reject the
            signature - it is a pure Python helper.
            """
            if kind == _CLICK_MENU:
                self._show_menu()
                return

            with self._lock:
                if self._pending_timer is not None:
                    self._pending_timer.cancel()
                    self._pending_timer = None

                if kind == _CLICK_SINGLE:
                    timer = threading.Timer(_SINGLE_CLICK_DEFER_S, self._fire_single)
                    timer.daemon = True
                    self._pending_timer = timer
                    timer.start()
                    callback = None
                elif kind == _CLICK_DOUBLE:
                    callback = self._double
                else:
                    callback = None

            if callback is not None:
                threading.Thread(target=_safe_invoke, args=(callback,), daemon=True).start()

        def _fire_single(self) -> None:
            with self._lock:
                self._pending_timer = None
            threading.Thread(target=_safe_invoke, args=(self._single,), daemon=True).start()

        def _show_menu(self) -> None:
            menu_handle = self._host_icon._menu_handle
            if not menu_handle:
                return
            nsmenu = menu_handle[0]
            button = self._host_icon._status_item.button()
            if button is None:
                return
            # popUpMenuPositioningItem positions the menu's first item at
            # ``atLocation`` in the given view's coordinate system.  Using
            # the button's own bounds height makes the menu drop down from
            # the icon - matching the native status-bar feel.
            location = Foundation.NSPoint(0, button.bounds().size.height + 2)
            nsmenu.popUpMenuPositioningItem_atLocation_inView_(None, location, button)


def install_macos_dblclick_handler(
    icon: pystray.Icon,
    on_single_click: Callable[[], None],
    on_double_click: Callable[[], None],
) -> None:
    """Make a pystray ``Icon`` distinguish single, double, and right click.

    Effect on the running status item:

    * left single-click  → ``on_single_click()`` (deferred briefly to
      give a possible double-click a chance to supersede it).
    * left double-click  → ``on_double_click()``.
    * right-click or Ctrl+left-click → the ``pystray`` menu opens in
      place, as it would on Windows.

    A no-op on platforms other than macOS.  Must be called after the
    ``pystray.Icon`` has been constructed (and its menu set) - calling
    this from ``app.py`` immediately after the constructor is fine
    because ``_update_menu`` runs lazily when pystray sets up the status
    item.

    Parameters
    ----------
    icon : pystray.Icon
        Already-constructed icon instance.
    on_single_click : callable
        Invoked (in a background thread) on plain single left-click.
    on_double_click : callable
        Invoked (in a background thread) on left double-click.
    """
    if sys.platform != 'darwin':
        return

    # Idempotency guard.  Re-calling the installer would capture the
    # already-patched ``_update_menu`` as ``original_update_menu`` and
    # produce infinite recursion on the next pystray menu rebuild.  A
    # private flag on the icon stops the second call from doing anything.
    if getattr(icon, '_dblclick_installed', False):
        return

    # 1) Detach pystray's NSMenu from the status item so left-clicks
    #    actually reach the button's action selector.  pystray re-attaches
    #    the menu every time ``_update_menu`` runs (e.g. when an item's
    #    ``checked=lambda`` changes), so we patch the method to immediately
    #    undo the attachment.
    original_update_menu = icon._update_menu

    def _patched_update_menu() -> None:
        original_update_menu()
        if icon._menu_handle is not None:
            icon._status_item.setMenu_(None)

    icon._update_menu = _patched_update_menu  # type: ignore[method-assign]  # monkey-patch pystray internal
    # Force one initial menu build so ``icon._menu_handle`` is populated.
    icon._update_menu()

    # 2) Wire the Objective-C click dispatcher.
    dispatcher = _ClickDispatcher.alloc().initWithIcon_single_double_(
        icon, on_single_click, on_double_click,
    )
    # Hold a strong Python reference so the Objective-C delegate stays
    # alive for the icon's lifetime (NSStatusBarButton only weak-refs its
    # target).
    icon._click_dispatcher = dispatcher  # type: ignore[attr-defined]  # extend pystray icon with our dispatcher reference

    button = icon._status_item.button()
    button.setTarget_(dispatcher)
    button.setAction_('handleClick:')
    # Fire the action on mouse down for both buttons so NSEvent.clickCount
    # is already final when handleClick_ runs.
    button.sendActionOn_(
        AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskRightMouseDown,
    )

    icon._dblclick_installed = True  # type: ignore[attr-defined]  # marker that the patch is in place


# ---------------------------------------------------------------------------
# Shared launcher
# ---------------------------------------------------------------------------

def launch_claude_desktop() -> None:
    """Open the Claude Desktop app, falling back to ``claude.ai`` on the web.

    Platform-specific behavior is delegated to a private helper.  Every
    branch ultimately falls back to the web app when no native install is
    available, so the feature degrades gracefully.
    """
    if sys.platform == 'win32':
        if _try_windows_uri_launch():
            return
        if _try_windows_registry_exe():
            return
    elif sys.platform == 'darwin':
        if _try_macos_uri_launch():
            return
        if _try_macos_bundle_id_launch():
            return

    try:
        webbrowser.open(_CLAUDE_WEB_FALLBACK)
    except Exception:  # noqa: BLE001 - launcher must never raise
        pass


# ---------------------------------------------------------------------------
# Windows launcher helpers
# ---------------------------------------------------------------------------

if sys.platform == 'win32':
    def _try_windows_uri_launch() -> bool:
        """Try the canonical ``claude:`` URL handler."""
        try:
            os.startfile('claude:')  # type: ignore[attr-defined]  # Windows-only
            return True
        except (OSError, AttributeError):
            return False

    def _try_windows_registry_exe() -> bool:
        """Fall back to reading the registered EXE path directly.

        Some setups have the URL protocol registered but disabled (or the
        MSIX activation has gone stale).  Reading the EXE path from
        ``HKCR\\claude\\shell\\open\\command`` and launching it directly is
        a secondary path before resorting to the web app.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _CLAUDE_URI_REG_KEY) as key:
                value, _ = winreg.QueryValueEx(key, '')
        except OSError:
            return False

        exe_path = _extract_exe_from_command(value)
        if not exe_path or not os.path.exists(exe_path):
            return False

        try:
            subprocess.Popen(
                [exe_path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return True
        except OSError:
            return False

    def _extract_exe_from_command(command: str) -> str | None:
        """Pull the first token out of a shell command string.

        The registry value looks like ``"C:\\Path\\Claude.exe" "%1"``.  We
        want just the EXE path, without the surrounding quotes and without
        the trailing ``"%1"`` placeholder.
        """
        cmd = command.strip()
        if not cmd:
            return None
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            if end == -1:
                return None
            return cmd[1:end]
        space = cmd.find(' ')
        return cmd if space == -1 else cmd[:space]


# ---------------------------------------------------------------------------
# macOS launcher helpers
# ---------------------------------------------------------------------------

if sys.platform == 'darwin':
    _CLAUDE_BUNDLE_ID = 'com.anthropic.claudefordesktop'

    def _try_macos_uri_launch() -> bool:
        """Open Claude Desktop via its registered ``claude://`` URL handler."""
        return _open_via_launch_services(['/usr/bin/open', 'claude://'])

    def _try_macos_bundle_id_launch() -> bool:
        """Open Claude Desktop via its bundle identifier.

        Used as a fallback when the ``claude://`` registration is missing
        (e.g. the user installed Claude.app outside ``/Applications`` and
        Launch Services has not re-scanned it yet).
        """
        return _open_via_launch_services(['/usr/bin/open', '-b', _CLAUDE_BUNDLE_ID])

    def _open_via_launch_services(argv: list[str]) -> bool:
        """Run ``open`` and return True if the launch succeeded."""
        try:
            result = subprocess.run(argv, capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            return False
        return result.returncode == 0


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _safe_invoke(callable_to_run: Callable[[], Any]) -> None:
    """Invoke a user callback, suppressing any exception it raises.

    A faulty handler must never crash the message pump (Windows) or the
    AppKit runloop (macOS) and take the tray icon down with it.
    """
    try:
        callable_to_run()
    except Exception:  # noqa: BLE001 - boundary swallow is the whole point
        pass

"""
macOS Popup Host
=================

Native ``NSPanel`` + ``WKWebView`` host for the popup HTML used by the
Windows build.  Replaces pywebview on macOS because pywebview's Cocoa
backend wants to own ``NSApplication``'s main runloop, which is already
owned by pystray for the menu bar icon.

The same ``popup.html``/``popup.css``/``popup.js`` files are reused without
modification.  A short ``WKUserScript`` injected at ``documentStart`` defines
``window.pywebview.api`` and forwards each method to a Swift-style message
handler that delivers a plain dict to Python.

All AppKit objects (panel, webview, monitors, delegates) live exclusively on
the main thread.  Public methods accept calls from any thread and dispatch
internally; the caller waits on a ``threading.Event`` for ``did_finish_load``
and ``window_closed`` callbacks.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

import AppKit  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
import Foundation  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
import WebKit  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
import objc  # type: ignore[import-untyped]  # pyobjc has no type stubs

__all__ = ['PopupController', 'dispatch_main_async', 'dispatch_main_sync', 'status_item_screen_frame', 'compute_popup_position']

# Style mask for a floating, borderless, non-activating panel that does not steal
# focus from the menu bar but still receives clicks normally.
_PANEL_STYLE_MASK = (
    AppKit.NSWindowStyleMaskBorderless
    | AppKit.NSWindowStyleMaskNonactivatingPanel
)

# Margin between the menu bar / status icon and the popup, matching the Windows margin.
_MARGIN = 6

# JavaScript shim installed at document-start so popup.js can call
# ``pywebview.api.close()``, ``pywebview.api.open_url()``,
# ``pywebview.api.refresh()``, and ``pywebview.api.report_height(h)`` unchanged.
_PYWEBVIEW_BRIDGE_JS = '''
window.pywebview = {
    api: {
        close: function () {
            window.webkit.messageHandlers.bridge.postMessage({method: 'close'});
        },
        open_url: function () {
            window.webkit.messageHandlers.bridge.postMessage({method: 'open_url'});
        },
        refresh: function () {
            window.webkit.messageHandlers.bridge.postMessage({method: 'refresh'});
        },
        report_height: function (h) {
            window.webkit.messageHandlers.bridge.postMessage({method: 'report_height', height: h});
        }
    }
};
'''


def dispatch_main_async(block: Callable[[], None]) -> None:
    """Run *block* on the AppKit main thread, returning immediately.

    Equivalent to ``DispatchQueue.main.async { }`` in Swift.  Safe to call
    from any thread, including the main thread itself (the block is then
    queued, not executed inline).
    """
    Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(block)


def dispatch_main_sync(block: Callable[[], Any]) -> Any:
    """Run *block* on the AppKit main thread and wait for it to finish.

    If already on the main thread, *block* is invoked inline to avoid
    deadlocking on the main runloop.  The block's return value is
    propagated to the caller.

    Exceptions raised by *block* are stored and re-raised in the caller's
    thread to keep tracebacks meaningful.
    """
    if Foundation.NSThread.isMainThread():
        return block()

    captured: dict[str, Any] = {}
    done = threading.Event()

    def _wrapper() -> None:
        try:
            captured['value'] = block()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            captured['exc'] = exc
        finally:
            done.set()

    Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(_wrapper)
    done.wait()
    if 'exc' in captured:
        raise captured['exc']
    return captured.get('value')


def status_item_screen_frame(status_item: Any) -> tuple[float, float, float, float] | None:
    """Return the status item button's frame in Cocoa screen coords.

    Parameters
    ----------
    status_item : NSStatusItem
        The pystray-owned status item.

    Returns
    -------
    tuple or None
        ``(x, y, width, height)`` with Cocoa's bottom-left origin, or
        ``None`` if the button is not yet attached to a window (very brief
        state during pystray startup).
    """
    button = status_item.button()
    if button is None:
        return None
    window = button.window()
    if window is None:
        return None
    bounds_in_window = button.convertRect_toView_(button.bounds(), None)
    frame_in_screen = window.convertRectToScreen_(bounds_in_window)
    origin = frame_in_screen.origin
    size = frame_in_screen.size
    return (float(origin.x), float(origin.y), float(size.width), float(size.height))


def compute_popup_position(
    icon_frame: tuple[float, float, float, float], popup_width: float, popup_height: float,
) -> tuple[float, float]:
    """Position the popup directly under the menu bar icon.

    The popup is centered horizontally on the icon when possible, then
    clamped to stay within the screen that owns the icon.  The vertical
    origin sits just below the icon (Cocoa coordinates: lower Y = lower
    on screen).

    Parameters
    ----------
    icon_frame : tuple
        ``(x, y, width, height)`` from :func:`status_item_screen_frame`.
    popup_width : float
        Logical popup width in points.
    popup_height : float
        Logical popup height in points.
    """
    icon_x, icon_y, icon_w, _icon_h = icon_frame
    icon_center_x = icon_x + icon_w / 2

    desired_x = icon_center_x - popup_width / 2
    desired_y = icon_y - popup_height - _MARGIN

    screen = _screen_containing_point(icon_center_x, icon_y)
    if screen is not None:
        visible = screen.visibleFrame()
        min_x = float(visible.origin.x) + _MARGIN
        max_x = float(visible.origin.x + visible.size.width) - popup_width - _MARGIN
        if max_x < min_x:
            max_x = min_x
        desired_x = max(min_x, min(max_x, desired_x))

        min_y = float(visible.origin.y) + _MARGIN
        if desired_y < min_y:
            desired_y = min_y

    return (desired_x, desired_y)


def _screen_containing_point(x: float, y: float) -> Any:
    """Return the NSScreen whose frame contains the given screen-space point."""
    point = Foundation.NSPoint(x, y)
    for screen in AppKit.NSScreen.screens():
        if AppKit.NSPointInRect(point, screen.frame()):
            return screen
    return AppKit.NSScreen.mainScreen()


class _BridgeHandler(Foundation.NSObject):
    """Receives ``window.webkit.messageHandlers.bridge.postMessage`` payloads."""

    def initWithCallback_(self, callback: Callable[[dict[str, Any]], None]) -> Any:
        self = objc.super(_BridgeHandler, self).init()
        if self is None:
            return None
        self._py_callback = callback
        return self

    def userContentController_didReceiveScriptMessage_(self, _controller: Any, message: Any) -> None:
        body = message.body()
        # body is an NSDictionary, copy to a plain Python dict for the caller.
        payload: dict[str, Any] = {}
        if body is not None:
            for key in body:
                payload[str(key)] = body[key]
        try:
            self._py_callback(payload)
        except Exception:  # noqa: BLE001 - never propagate into Cocoa
            pass


class _WindowDelegate(Foundation.NSObject):
    """Notifies Python when the panel is closed by the user or AppKit."""

    def initWithCallback_(self, callback: Callable[[], None]) -> Any:
        self = objc.super(_WindowDelegate, self).init()
        if self is None:
            return None
        self._py_callback = callback
        return self

    def windowWillClose_(self, _notification: Any) -> None:
        try:
            self._py_callback()
        except Exception:  # noqa: BLE001
            pass


class _NavigationDelegate(Foundation.NSObject):
    """Fires *on_did_finish_load* once the popup HTML is fully parsed."""

    def initWithCallback_(self, callback: Callable[[], None]) -> Any:
        self = objc.super(_NavigationDelegate, self).init()
        if self is None:
            return None
        self._py_callback = callback
        return self

    def webView_didFinishNavigation_(self, _webview: Any, _nav: Any) -> None:
        try:
            self._py_callback()
        except Exception:  # noqa: BLE001
            pass


class PopupController:
    """Lifecycle owner for a single popup window on macOS.

    Construction is cheap and thread-safe; the real AppKit work happens in
    :meth:`create_and_show`, which dispatches to the main thread.  All
    other public methods are also thread-safe.

    Parameters
    ----------
    html_url : str
        ``file://`` URL pointing at ``popup.html``.
    width : int
        Logical popup width in points.
    initial_height : int
        Initial popup height in points (resized later by
        :meth:`resize_and_position` once JS reports the real layout).
    bg_color : str
        CSS-style hex color (``'#1e1e1e'``) used as the panel background
        so the brief moment between create and first paint is not white.
    status_item : NSStatusItem
        The pystray-owned status item used for popup positioning.
    on_message : callable
        Called with a plain dict for every JS bridge message.  Possible
        keys are ``method`` (always present) and method-specific args.
    on_did_finish_load : callable
        Called once, after ``popup.html`` finishes loading and the JS
        bridge is ready.
    on_window_closed : callable
        Called when the panel is closed (user click-outside, ESC, or
        explicit :meth:`close`).
    """

    def __init__(
        self, html_url: str, width: int, initial_height: int, bg_color: str,
        status_item: Any,
        on_message: Callable[[dict[str, Any]], None],
        on_did_finish_load: Callable[[], None],
        on_window_closed: Callable[[], None],
    ) -> None:
        self._html_url = html_url
        self._width = width
        self._initial_height = initial_height
        self._bg_color = bg_color
        self._status_item = status_item
        self._on_message = on_message
        self._on_did_finish_load = on_did_finish_load
        self._on_window_closed = on_window_closed

        # All AppKit objects below are written on the main thread and read
        # from any thread via dispatch_main_async/sync.
        self._panel: Any = None
        self._webview: Any = None
        self._bridge: Any = None
        self._window_delegate: Any = None
        self._nav_delegate: Any = None
        self._global_monitor: Any = None
        self._local_monitor: Any = None
        self._key_monitor: Any = None
        self._closed = False

    # ------------------------------------------------------------------
    # Public API - safe from any thread
    # ------------------------------------------------------------------

    def create_and_load(self) -> None:
        """Create the panel hidden and start loading the HTML.  Blocks until ready."""
        dispatch_main_sync(self._create_on_main)

    def resize(self, height: int) -> None:
        """Resize the panel to *height* points and reposition under the icon."""
        dispatch_main_async(lambda: self._resize_on_main(height))

    def show(self) -> None:
        """Make the panel visible and start the click-outside monitors."""
        dispatch_main_async(self._show_on_main)

    def evaluate_js(self, script: str) -> None:
        """Run *script* in the WKWebView.  Errors are silently discarded."""
        dispatch_main_async(lambda: self._evaluate_js_on_main(script))

    def evaluate_js_sync(self, script: str, timeout: float = 3.0) -> Any:
        """Run *script* and return its result, blocking up to *timeout* seconds.

        Intended for tests and diagnostics.  Returns ``None`` on timeout, on
        a JavaScript error, or if the popup has already been closed.  Must
        be called from a non-main thread to avoid deadlocking the AppKit
        runloop.
        """
        if Foundation.NSThread.isMainThread():
            raise RuntimeError('evaluate_js_sync must not be called from the main thread')

        captured: dict[str, Any] = {}
        done = threading.Event()

        def _completion(result: Any, _error: Any) -> None:
            captured['result'] = result
            done.set()

        def _run() -> None:
            if self._webview is None or self._closed:
                done.set()
                return
            self._webview.evaluateJavaScript_completionHandler_(script, _completion)

        dispatch_main_async(_run)
        if not done.wait(timeout):
            return None
        return captured.get('result')

    def close(self) -> None:
        """Close the panel and tear down monitors and delegates."""
        dispatch_main_async(self._close_on_main)

    # ------------------------------------------------------------------
    # Main-thread implementations
    # ------------------------------------------------------------------

    def _create_on_main(self) -> None:
        config = WebKit.WKWebViewConfiguration.alloc().init()
        controller = config.userContentController()

        user_script = WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            _PYWEBVIEW_BRIDGE_JS,
            WebKit.WKUserScriptInjectionTimeAtDocumentStart,
            True,
        )
        controller.addUserScript_(user_script)

        self._bridge = _BridgeHandler.alloc().initWithCallback_(self._on_message)
        controller.addScriptMessageHandler_name_(self._bridge, 'bridge')

        frame = Foundation.NSMakeRect(0, 0, self._width, self._initial_height)
        self._webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self._webview.setValue_forKey_(False, 'drawsBackground')
        self._nav_delegate = _NavigationDelegate.alloc().initWithCallback_(self._on_did_finish_load)
        self._webview.setNavigationDelegate_(self._nav_delegate)

        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, _PANEL_STYLE_MASK, AppKit.NSBackingStoreBuffered, False,
        )
        self._panel.setLevel_(AppKit.NSPopUpMenuWindowLevel)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(_color_from_hex(self._bg_color))
        self._panel.setHasShadow_(True)
        self._panel.setMovableByWindowBackground_(False)
        self._panel.setReleasedWhenClosed_(False)
        # setHidesOnDeactivate_(True) would auto-hide the popup when our app loses
        # focus.  We deliberately keep it visible across deactivations because the
        # NSEvent global mouse monitor already dismisses on outside clicks; auto-
        # hiding on top of that creates a race where the panel disappears before
        # the user can interact with it (especially when launched from a tray
        # callback that does not activate the host process).
        self._panel.setHidesOnDeactivate_(False)
        # CanJoinAllSpaces makes the popup visible when the user is in a different
        # fullscreen Space (e.g. another app in fullscreen mode); without this the
        # panel is created on the original desktop Space and stays invisible.
        # FullScreenAuxiliary keeps it as a non-primary window in fullscreen apps.
        self._panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary,
        )
        self._panel.setContentView_(self._webview)

        self._window_delegate = _WindowDelegate.alloc().initWithCallback_(self._handle_window_closed)
        self._panel.setDelegate_(self._window_delegate)

        # WKWebView blocks sibling resources (popup.css, popup.js) when a file://
        # URL is loaded with loadRequest:.  loadFileURL: + allowingReadAccessToURL:
        # grants read access to the popup directory so the linked assets resolve.
        html_url = Foundation.NSURL.URLWithString_(self._html_url)
        allow_root = html_url.URLByDeletingLastPathComponent()
        self._webview.loadFileURL_allowingReadAccessToURL_(html_url, allow_root)

    def _resize_on_main(self, height: int) -> None:
        if self._panel is None:
            return
        position = self._compute_position(height)
        if position is None:
            return
        x, y = position
        frame = Foundation.NSMakeRect(x, y, self._width, height)
        self._panel.setFrame_display_animate_(frame, True, False)

    def _show_on_main(self) -> None:
        if self._panel is None or self._closed:
            return
        self._panel.orderFrontRegardless()
        self._install_dismiss_monitors()

    def _evaluate_js_on_main(self, script: str) -> None:
        if self._webview is None or self._closed:
            return
        self._webview.evaluateJavaScript_completionHandler_(script, None)

    def _close_on_main(self) -> None:
        self._handle_window_closed(internal=True)
        if self._panel is not None:
            self._panel.close()

    def _handle_window_closed(self, internal: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self._remove_dismiss_monitors()
        # The bridge handler holds a strong reference back to self via the
        # callback closure - clear it so the controller can be released.
        if self._bridge is not None and self._webview is not None:
            try:
                self._webview.configuration().userContentController().removeScriptMessageHandlerForName_('bridge')
            except Exception:  # noqa: BLE001
                pass
        if not internal:
            try:
                self._on_window_closed()
            except Exception:  # noqa: BLE001
                pass
        else:
            # Schedule the user callback after the close cascade completes.
            dispatch_main_async(self._on_window_closed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_position(self, height: int) -> tuple[float, float] | None:
        icon_frame = status_item_screen_frame(self._status_item)
        if icon_frame is None:
            return None
        return compute_popup_position(icon_frame, self._width, height)

    def _install_dismiss_monitors(self) -> None:
        if self._global_monitor is not None:
            return

        mouse_mask = AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskRightMouseDown
        key_mask = AppKit.NSEventMaskKeyDown

        def _on_outside_click(_event: Any) -> None:
            self.close()

        def _on_local_click(event: Any) -> Any:
            # Click inside our own popup panel?  Forward unchanged.
            window = event.window()
            if window is None or window is not self._panel:
                self.close()
            return event

        def _on_key(event: Any) -> Any:
            # 53 is the macOS key code for Escape.
            if event.keyCode() == 53:
                self.close()
                return None
            return event

        self._global_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mouse_mask, _on_outside_click,
        )
        self._local_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            mouse_mask, _on_local_click,
        )
        self._key_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            key_mask, _on_key,
        )

    def _remove_dismiss_monitors(self) -> None:
        if self._global_monitor is not None:
            AppKit.NSEvent.removeMonitor_(self._global_monitor)
            self._global_monitor = None
        if self._local_monitor is not None:
            AppKit.NSEvent.removeMonitor_(self._local_monitor)
            self._local_monitor = None
        if self._key_monitor is not None:
            AppKit.NSEvent.removeMonitor_(self._key_monitor)
            self._key_monitor = None


def _color_from_hex(hex_color: str) -> Any:
    """Parse a ``#rrggbb`` string into an ``NSColor`` (alpha 1)."""
    value = hex_color.lstrip('#')
    if len(value) != 6:
        return AppKit.NSColor.windowBackgroundColor()
    r = int(value[0:2], 16) / 255.0
    g = int(value[2:4], 16) / 255.0
    b = int(value[4:6], 16) / 255.0
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)

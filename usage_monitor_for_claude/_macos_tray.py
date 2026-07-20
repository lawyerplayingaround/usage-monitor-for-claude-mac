"""
macOS Tray Image Patch
=======================

Replaces :meth:`pystray._darwin.Icon._assert_image` so the menu bar icon

* is rendered at 2x the status bar thickness (retina-sharp on HiDPI displays),
* sets its logical size on the ``NSImage`` so AppKit treats the 2x bitmap as
  a single-point image instead of stretching a 22x22 bitmap full-size, and
* is marked as a template image, which makes AppKit adapt the icon's colors
  to the menu bar appearance (light/dark) automatically.

The upstream implementation in ``pystray._darwin._assert_image`` downsamples
the PIL source to ``thickness x thickness`` (~22x22 px) with LANCZOS and
hands AppKit the bitmap unchanged.  On retina menu bars that bitmap is
stretched 2x by the system, losing the antialiasing detail that LANCZOS
just produced.

This patch is invoked from ``app.py`` only when ``sys.platform == 'darwin'``.
"""
from __future__ import annotations

import io
import sys
import types

__all__ = ['install_macos_tray_patch', 'wake_runloop']


def install_macos_tray_patch(icon) -> None:
    """Install the retina/template ``_assert_image`` patch on a pystray Icon.

    Parameters
    ----------
    icon : pystray.Icon
        The Icon instance whose ``_assert_image`` method should be replaced.
        Only effective on macOS; a no-op on other platforms.
    """
    if sys.platform != 'darwin':
        return

    import AppKit  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
    import Foundation  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
    import PIL.Image  # type: ignore[import-untyped]  # Pillow ships partial stubs only

    def _assert_image(self) -> None:
        thickness = float(self._status_bar.thickness())
        logical_size = (int(thickness), int(thickness))
        retina_size = (logical_size[0] * 2, logical_size[1] * 2)

        if self._icon_image is not None and self._icon_image.size().width == logical_size[0]:
            return

        if self._icon.size == retina_size:
            source = self._icon
        else:
            source = self._icon.resize(retina_size, PIL.Image.LANCZOS)

        buf = io.BytesIO()
        source.save(buf, 'png')
        data = Foundation.NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))

        nsimg = AppKit.NSImage.alloc().initWithData_(data)
        nsimg.setSize_(Foundation.NSMakeSize(logical_size[0], logical_size[1]))
        nsimg.setTemplate_(True)

        self._icon_image = nsimg
        self._status_item.button().setImage_(self._icon_image)

    icon._assert_image = types.MethodType(_assert_image, icon)


def wake_runloop() -> None:
    """Post a no-op event so a pending ``NSApplication.stop_`` takes effect now.

    Cocoa's ``stop:`` only breaks ``NSApplication.run()`` after the runloop
    processes one more *event*; a menu action alone does not produce one, so
    a quit or restart chosen from the menu would otherwise hang until the
    user's next click.  The synthetic application-defined event supplies that
    one event immediately.
    """
    import AppKit  # type: ignore[import-untyped]  # pyobjc has no type stubs
    import Foundation  # type: ignore[import-untyped]  # pyobjc has no type stubs

    def _post() -> None:
        event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeApplicationDefined, Foundation.NSMakePoint(0, 0), 0, 0.0, 0, None, 0, 0, 0,
        )
        AppKit.NSApp.postEvent_atStart_(event, False)

    Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(_post)

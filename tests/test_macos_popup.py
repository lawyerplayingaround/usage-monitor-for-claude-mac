"""
macOS Popup Tests
==================

Unit tests for ``_macos_popup.compute_popup_position`` - the pure geometry
helper that decides where the popup sits relative to the status item icon.

The rest of ``_macos_popup`` (PopupController, NSEvent monitors, NSPanel)
is exercised end-to-end by ``scripts/mac_smoke_popup.py`` because it needs
a live AppKit runloop and a real ``NSStatusItem``; unit-testing those
parts would require mocking the entire AppKit/WebKit surface.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

_MAC_ONLY = unittest.skipUnless(sys.platform == 'darwin', 'macOS-specific popup geometry')


@_MAC_ONLY
class TestComputePopupPosition(unittest.TestCase):
    """Tests for compute_popup_position - centers popup under icon, clamps to screen."""

    def setUp(self) -> None:
        # Fake a 1440 x 900 logical screen at origin (0, 0) with a 22 pt menu
        # bar at the top.  visibleFrame's height excludes the menu bar so its
        # origin.y starts at the bottom of the screen and its top edge is the
        # underside of the menu bar.
        self._visible_frame = self._frame(0, 0, 1440, 878)
        self._screen = MagicMock()
        self._screen.frame.return_value = self._frame(0, 0, 1440, 900)
        self._screen.visibleFrame.return_value = self._visible_frame

    @staticmethod
    def _frame(x: float, y: float, w: float, h: float) -> MagicMock:
        """Build an NSRect-like mock with origin.x/y and size.width/height."""
        frame = MagicMock()
        frame.origin.x = x
        frame.origin.y = y
        frame.size.width = w
        frame.size.height = h
        return frame

    def _run(self, icon: tuple[float, float, float, float], popup_w: int, popup_h: int) -> tuple[float, float]:
        """Call compute_popup_position with the given fakes patched in."""
        from usage_monitor_for_claude import _macos_popup
        with patch.object(_macos_popup, '_screen_containing_point', return_value=self._screen):
            return _macos_popup.compute_popup_position(icon, popup_w, popup_h)

    def test_centered_below_icon_when_room(self) -> None:
        """When the screen has room, the popup is centered horizontally on the icon."""
        # Icon at (700, 878) - middle-top of screen, 40 wide
        x, _ = self._run((700, 878, 40, 22), 340, 500)
        icon_center = 700 + 40 / 2
        popup_center = x + 340 / 2
        self.assertAlmostEqual(popup_center, icon_center, places=1)

    def test_below_icon_vertically(self) -> None:
        """The popup top edge sits just under the icon, with the configured margin."""
        from usage_monitor_for_claude._macos_popup import _MARGIN
        _, y = self._run((700, 878, 40, 22), 340, 500)
        # In Cocoa, the panel's y is its bottom edge.  Top = y + height.
        top = y + 500
        self.assertLessEqual(top, 878 - _MARGIN + 0.5)
        self.assertGreater(top, 878 - _MARGIN - 5)

    def test_clamped_to_right_edge(self) -> None:
        """When the icon is near the right edge, the popup does not run off-screen."""
        from usage_monitor_for_claude._macos_popup import _MARGIN
        x, _ = self._run((1420, 878, 20, 22), 340, 500)
        self.assertLessEqual(x + 340, 1440 - _MARGIN + 0.5)

    def test_clamped_to_left_edge(self) -> None:
        """When the icon is near the left edge, the popup does not run off-screen."""
        from usage_monitor_for_claude._macos_popup import _MARGIN
        x, _ = self._run((5, 878, 20, 22), 340, 500)
        self.assertGreaterEqual(x, _MARGIN - 0.5)

    def test_clamped_to_top_when_popup_taller_than_screen(self) -> None:
        """A very tall popup is pinned to the bottom margin rather than wrapped off-screen."""
        from usage_monitor_for_claude._macos_popup import _MARGIN
        _, y = self._run((700, 878, 40, 22), 340, 1200)
        self.assertGreaterEqual(y, _MARGIN - 0.5)


@_MAC_ONLY
class TestColorFromHex(unittest.TestCase):
    """Tests for _color_from_hex - parses popup BG into an NSColor."""

    def test_parses_six_digit_hex(self) -> None:
        from usage_monitor_for_claude._macos_popup import _color_from_hex
        color = _color_from_hex('#1e1e1e')
        # NSColor exposes redComponent/greenComponent/blueComponent on RGB colors.
        red = color.redComponent()
        self.assertAlmostEqual(red, 0x1e / 255.0, places=3)

    def test_falls_back_on_short_input(self) -> None:
        from usage_monitor_for_claude._macos_popup import _color_from_hex
        # No exception for malformed input; AppKit windowBackgroundColor is returned.
        color = _color_from_hex('#abc')
        self.assertIsNotNone(color)


if __name__ == '__main__':
    unittest.main()

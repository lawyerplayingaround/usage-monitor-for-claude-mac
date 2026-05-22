"""
Tray Double-Click Tests
========================

Tests for ``usage_monitor_for_claude.tray_dblclick``: the cross-platform
double-click dispatcher plus the ``launch_claude_desktop`` fallback chain.

The structural shape of the macOS dispatcher (target/action wiring, menu
detachment) is exercised here.  Behavioral timing is covered by the
end-to-end ``scripts/mac_smoke_popup.py`` driver, which would require a
live AppKit runloop to reproduce inside unittest.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import usage_monitor_for_claude.tray_dblclick as dblclick_mod

_WIN32_ONLY = unittest.skipUnless(sys.platform == 'win32', 'Win32 tray hooks')
_MAC_ONLY = unittest.skipUnless(sys.platform == 'darwin', 'macOS NSStatusItem hooks')


class TestLaunchClaudeDesktopFallback(unittest.TestCase):
    """The launcher must never raise even when no Claude binary is found."""

    def test_falls_back_to_web_when_all_native_paths_fail(self):
        """Both URI and bundle-id launches fail → web fallback fires."""
        if sys.platform not in ('win32', 'darwin'):
            self.skipTest('platform has no native Claude launcher to exercise')

        with patch.object(dblclick_mod, 'webbrowser') as mock_browser:
            if sys.platform == 'darwin':
                with patch.object(dblclick_mod, '_try_macos_uri_launch', return_value=False), \
                     patch.object(dblclick_mod, '_try_macos_bundle_id_launch', return_value=False):
                    dblclick_mod.launch_claude_desktop()
            else:
                with patch.object(dblclick_mod, '_try_windows_uri_launch', return_value=False), \
                     patch.object(dblclick_mod, '_try_windows_registry_exe', return_value=False):
                    dblclick_mod.launch_claude_desktop()

        mock_browser.open.assert_called_once_with('https://claude.ai/')

    def test_swallows_webbrowser_exception(self):
        """Even if ``webbrowser.open`` raises, the launcher must return cleanly."""
        if sys.platform not in ('win32', 'darwin'):
            self.skipTest('platform has no native Claude launcher to exercise')

        with patch.object(dblclick_mod, 'webbrowser') as mock_browser:
            mock_browser.open.side_effect = RuntimeError('no browser')
            if sys.platform == 'darwin':
                with patch.object(dblclick_mod, '_try_macos_uri_launch', return_value=False), \
                     patch.object(dblclick_mod, '_try_macos_bundle_id_launch', return_value=False):
                    dblclick_mod.launch_claude_desktop()  # must not raise
            else:
                with patch.object(dblclick_mod, '_try_windows_uri_launch', return_value=False), \
                     patch.object(dblclick_mod, '_try_windows_registry_exe', return_value=False):
                    dblclick_mod.launch_claude_desktop()  # must not raise


@_MAC_ONLY
class TestMacosLaunchHelpers(unittest.TestCase):
    """The two macOS ``open``-based launch attempts treat exit codes correctly."""

    def test_uri_launch_returns_true_on_success(self):
        with patch.object(subprocess, 'run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(dblclick_mod._try_macos_uri_launch())

    def test_uri_launch_returns_false_on_nonzero_exit(self):
        with patch.object(subprocess, 'run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            self.assertFalse(dblclick_mod._try_macos_uri_launch())

    def test_uri_launch_returns_false_on_timeout(self):
        with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired(cmd='open', timeout=5)):
            self.assertFalse(dblclick_mod._try_macos_uri_launch())

    def test_uri_launch_returns_false_on_oserror(self):
        with patch.object(subprocess, 'run', side_effect=OSError('no such file')):
            self.assertFalse(dblclick_mod._try_macos_uri_launch())

    def test_bundle_id_launch_uses_known_identifier(self):
        with patch.object(subprocess, 'run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(dblclick_mod._try_macos_bundle_id_launch())
            args = mock_run.call_args[0][0]
            self.assertIn('com.anthropic.claudefordesktop', args)


@_MAC_ONLY
class TestInstallMacOSDblclickHandler(unittest.TestCase):
    """install_macos_dblclick_handler wires the click dispatcher correctly."""

    def setUp(self) -> None:
        # Build a mock icon shaped like pystray._darwin.Icon - just the
        # attributes the patch touches.
        self.mock_button = MagicMock()
        self.mock_status_item = MagicMock()
        self.mock_status_item.button.return_value = self.mock_button

        self.icon = MagicMock(spec=['_update_menu', '_status_item', '_menu_handle'])
        self.icon._status_item = self.mock_status_item
        self.icon._menu_handle = ('fake_nsmenu', ['cb1', 'cb2'])  # mimic _create_menu output

        self.single_cb = MagicMock()
        self.double_cb = MagicMock()

    def test_button_target_and_action_replaced(self):
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )

        # The new target must be the dispatcher we attach to the icon.
        self.assertTrue(hasattr(self.icon, '_click_dispatcher'))
        self.mock_button.setTarget_.assert_called_once_with(self.icon._click_dispatcher)
        self.mock_button.setAction_.assert_called_once_with('handleClick:')

    def test_menu_detached_after_install(self):
        """The patched _update_menu detaches the menu so left-clicks reach the button."""
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )

        # Force a menu rebuild to verify the post-rebuild detach.
        self.mock_status_item.setMenu_.reset_mock()
        self.icon._update_menu()
        # Last call should pass None (detach).
        self.mock_status_item.setMenu_.assert_called_with(None)

    def test_dispatcher_strong_reference_kept(self):
        """The dispatcher must be kept alive via a strong Python reference."""
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )
        self.assertIsNotNone(self.icon._click_dispatcher)

    def test_noop_on_non_darwin(self):
        """A platform mismatch returns silently without touching the icon."""
        # Pretend we are on Windows.
        with patch.object(dblclick_mod, 'sys', MagicMock(platform='win32')):
            dblclick_mod.install_macos_dblclick_handler(
                self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
            )
        self.mock_button.setTarget_.assert_not_called()


if __name__ == '__main__':
    unittest.main()

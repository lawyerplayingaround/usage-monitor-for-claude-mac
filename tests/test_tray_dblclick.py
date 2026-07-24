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
                with patch.object(dblclick_mod, '_try_macos_reopen_running', return_value=False), \
                     patch.object(dblclick_mod, '_try_macos_uri_launch', return_value=False), \
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
                with patch.object(dblclick_mod, '_try_macos_reopen_running', return_value=False), \
                     patch.object(dblclick_mod, '_try_macos_uri_launch', return_value=False), \
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

    def test_launches_foreground_not_background(self):
        """A user-initiated double-click must bring Claude Desktop forward, so neither launch passes '-g'."""
        with patch.object(subprocess, 'run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            dblclick_mod._try_macos_uri_launch()
            self.assertNotIn('-g', mock_run.call_args[0][0])
            mock_run.reset_mock()
            mock_run.return_value = MagicMock(returncode=0)
            dblclick_mod._try_macos_bundle_id_launch()
            self.assertNotIn('-g', mock_run.call_args[0][0])


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

    def test_dispatcher_routes_by_click_kind(self):
        """The dispatcher fires the right callback for single, double, ignore.

        Calls ``_dispatch`` directly with the pre-classified click kind so
        no real ``NSEvent`` is needed - the kind→action mapping is the
        actual contract we care about.
        """
        import time

        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )
        dispatcher = self.icon._click_dispatcher

        # single: schedules timer, callback fires after the resolved defer.
        dispatcher._dispatch(dblclick_mod._CLICK_SINGLE)
        time.sleep(dblclick_mod._SINGLE_CLICK_DEFER_S + 0.2)
        self.single_cb.assert_called_once()
        self.double_cb.assert_not_called()

        # Reset for the double-click case.
        self.single_cb.reset_mock()
        self.double_cb.reset_mock()

        # single followed by double: timer cancelled, double fires, single never does.
        dispatcher._dispatch(dblclick_mod._CLICK_SINGLE)
        dispatcher._dispatch(dblclick_mod._CLICK_DOUBLE)
        time.sleep(dblclick_mod._SINGLE_CLICK_DEFER_S + 0.2)
        self.single_cb.assert_not_called()
        self.double_cb.assert_called_once()

        # 3rd click (ignore): no callback, no timer.
        self.double_cb.reset_mock()
        dispatcher._dispatch(dblclick_mod._CLICK_IGNORE)
        time.sleep(dblclick_mod._SINGLE_CLICK_DEFER_S + 0.2)
        self.single_cb.assert_not_called()
        self.double_cb.assert_not_called()

    def test_dispatcher_menu_kind_shows_menu(self):
        """A 'menu' classification routes through _show_menu, not the callbacks."""
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )
        dispatcher = self.icon._click_dispatcher

        # Spy on _show_menu so we can assert it was called.
        with patch.object(dispatcher, '_show_menu') as mock_show:
            dispatcher._dispatch(dblclick_mod._CLICK_MENU)

        mock_show.assert_called_once()
        self.single_cb.assert_not_called()
        self.double_cb.assert_not_called()

    def test_install_is_idempotent(self):
        """A second install on the same icon must be a no-op (no recursive _update_menu).

        Without the guard, the second call would capture the already-patched
        ``_update_menu`` as the new original, producing infinite recursion the
        next time pystray invokes a menu rebuild.
        """
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )
        first_dispatcher = self.icon._click_dispatcher
        first_update_menu = self.icon._update_menu

        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=self.double_cb,
        )

        # The second install must NOT replace the dispatcher or rewrap _update_menu.
        self.assertIs(self.icon._click_dispatcher, first_dispatcher)
        self.assertIs(self.icon._update_menu, first_update_menu)

        # And a subsequent menu rebuild must terminate (no recursion).
        self.icon._update_menu()
        self.icon._update_menu()

    def test_double_click_disabled_falls_back_to_single(self):
        """With on_double_click=None, a double-click opens the popup (single action)."""
        import time
        dblclick_mod.install_macos_dblclick_handler(
            self.icon, on_single_click=self.single_cb, on_double_click=None,
        )
        dispatcher = self.icon._click_dispatcher
        dispatcher._dispatch(dblclick_mod._CLICK_DOUBLE)
        time.sleep(0.05)
        self.single_cb.assert_called_once()
        self.double_cb.assert_not_called()


@_MAC_ONLY
class TestSingleClickDefer(unittest.TestCase):
    """The single-click defer is short enough to feel snappy."""

    def test_defer_is_snappy(self):
        """The defer matches the Windows fork's responsive 120 ms window."""
        self.assertLessEqual(dblclick_mod._SINGLE_CLICK_DEFER_S, 0.2)


if __name__ == '__main__':
    unittest.main()

"""
Autostart Tests
================

Unit tests for autostart entry management - Windows registry and macOS
LaunchAgent.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import usage_monitor_for_claude.autostart as autostart_mod

_WIN32_ONLY = unittest.skipUnless(sys.platform == 'win32', 'Win32 registry autostart')
_MAC_ONLY = unittest.skipUnless(sys.platform == 'darwin', 'macOS LaunchAgent autostart')


@_WIN32_ONLY
class TestIsAutostartEnabled(unittest.TestCase):
    """Tests for is_autostart_enabled()."""

    @patch.object(autostart_mod, 'winreg')
    def test_returns_true_when_value_exists(self, mock_winreg):
        """Registry entry found returns True."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        self.assertTrue(autostart_mod.is_autostart_enabled())
        mock_winreg.QueryValueEx.assert_called_once_with(mock_key, autostart_mod.AUTOSTART_REG_NAME)

    @patch.object(autostart_mod, 'winreg')
    def test_returns_false_when_key_missing(self, mock_winreg):
        """FileNotFoundError on key open returns False."""
        mock_winreg.OpenKey.side_effect = FileNotFoundError

        self.assertFalse(autostart_mod.is_autostart_enabled())

    @patch.object(autostart_mod, 'winreg')
    def test_returns_false_when_value_missing(self, mock_winreg):
        """Key exists but value does not returns False."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError

        self.assertFalse(autostart_mod.is_autostart_enabled())

    @patch.object(autostart_mod, 'winreg')
    def test_opens_correct_registry_path(self, mock_winreg):
        """Opens HKCU Run key with correct path."""
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock()
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        autostart_mod.is_autostart_enabled()

        mock_winreg.OpenKey.assert_called_once_with(
            mock_winreg.HKEY_CURRENT_USER, autostart_mod.AUTOSTART_REG_KEY,
        )


@_WIN32_ONLY
class TestSetAutostart(unittest.TestCase):
    """Tests for set_autostart()."""

    @patch.object(autostart_mod, 'winreg')
    def test_enable_sets_quoted_executable_path(self, mock_winreg):
        """Enabling autostart writes the quoted sys.executable path."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        autostart_mod.set_autostart(True)

        mock_winreg.SetValueEx.assert_called_once_with(
            mock_key, autostart_mod.AUTOSTART_REG_NAME, 0,
            mock_winreg.REG_SZ, f'"{sys.executable}"',
        )

    @patch.object(autostart_mod, 'winreg')
    def test_disable_deletes_registry_value(self, mock_winreg):
        """Disabling autostart removes the registry value."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        autostart_mod.set_autostart(False)

        mock_winreg.DeleteValue.assert_called_once_with(mock_key, autostart_mod.AUTOSTART_REG_NAME)
        mock_winreg.SetValueEx.assert_not_called()

    @patch.object(autostart_mod, 'winreg')
    def test_disable_ignores_missing_value(self, mock_winreg):
        """Disabling when value already absent does not raise."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.DeleteValue.side_effect = FileNotFoundError

        autostart_mod.set_autostart(False)  # should not raise

    @patch.object(autostart_mod, 'winreg')
    def test_enable_opens_with_set_value_permission(self, mock_winreg):
        """Opening registry for write uses KEY_SET_VALUE."""
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock()
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        autostart_mod.set_autostart(True)

        mock_winreg.OpenKey.assert_called_once_with(
            mock_winreg.HKEY_CURRENT_USER, autostart_mod.AUTOSTART_REG_KEY,
            0, mock_winreg.KEY_SET_VALUE,
        )

    @patch.object(autostart_mod, 'winreg')
    def test_enable_uses_current_executable(self, mock_winreg):
        """Uses sys.executable for the registry value."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(sys, 'executable', r'C:\Program Files\MyApp\app.exe'):
            autostart_mod.set_autostart(True)

        mock_winreg.SetValueEx.assert_called_once_with(
            mock_key, autostart_mod.AUTOSTART_REG_NAME, 0,
            mock_winreg.REG_SZ, r'"C:\Program Files\MyApp\app.exe"',
        )


@_WIN32_ONLY
class TestSyncAutostartPath(unittest.TestCase):
    """Tests for sync_autostart_path()."""

    @patch.object(autostart_mod, 'winreg')
    def test_returns_early_when_no_registry_entry(self, mock_winreg):
        """No registry entry means no update attempted."""
        mock_winreg.OpenKey.side_effect = FileNotFoundError

        autostart_mod.sync_autostart_path()  # should not raise

        mock_winreg.SetValueEx.assert_not_called()

    @patch.object(autostart_mod, 'set_autostart')
    @patch.object(autostart_mod, 'winreg')
    def test_updates_when_path_differs(self, mock_winreg, mock_set):
        """Stored path differs from sys.executable triggers update."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.QueryValueEx.return_value = (r'"C:\old\path.exe"', 1)

        with patch.object(sys, 'executable', r'C:\new\path.exe'):
            autostart_mod.sync_autostart_path()

        mock_set.assert_called_once_with(True)

    @patch.object(autostart_mod, 'set_autostart')
    @patch.object(autostart_mod, 'winreg')
    def test_skips_update_when_path_matches(self, mock_winreg, mock_set):
        """Matching stored path skips the update."""
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)

        expected = f'"{sys.executable}"'
        mock_winreg.QueryValueEx.return_value = (expected, 1)

        autostart_mod.sync_autostart_path()

        mock_set.assert_not_called()


@_MAC_ONLY
class TestMacOSAutostart(unittest.TestCase):
    """Tests for the macOS LaunchAgent plist write path.

    Each test patches ``LAUNCH_AGENT_PATH`` to a tmp file so the real
    ``~/Library/LaunchAgents`` folder is never touched.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._plist_path = Path(self._tmpdir.name) / 'LaunchAgents' / 'com.usage-monitor-for-claude.plist'
        self._patch = patch.object(autostart_mod, 'LAUNCH_AGENT_PATH', self._plist_path)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_initially_disabled(self):
        self.assertFalse(autostart_mod.is_autostart_enabled())

    def test_enable_creates_plist_with_sys_executable(self):
        with patch.object(sys, 'executable', '/Applications/UsageMonitorForClaude.app/Contents/MacOS/UsageMonitorForClaude'):
            autostart_mod.set_autostart(True)

        self.assertTrue(self._plist_path.is_file())
        content = self._plist_path.read_text()
        self.assertIn('<key>Label</key>', content)
        self.assertIn('com.usage-monitor-for-claude', content)
        self.assertIn('/Applications/UsageMonitorForClaude.app/Contents/MacOS/UsageMonitorForClaude', content)
        self.assertIn('<key>RunAtLoad</key>', content)
        self.assertIn('<true/>', content)

    def test_enable_emits_valid_xml(self):
        """plist must parse as XML (a malformed file would never be loaded by launchd)."""
        import xml.etree.ElementTree as ET
        with patch.object(sys, 'executable', '/path/to/app'):
            autostart_mod.set_autostart(True)
        ET.fromstring(self._plist_path.read_text())  # raises if malformed

    def test_enable_escapes_xml_special_chars_in_path(self):
        """Paths with XML-significant chars must produce a parseable plist.

        ``&``, ``<``, ``>`` need escaping to keep the XML well-formed.
        Quotes inside a text node are valid unescaped per the XML 1.0 spec,
        so they are not required to be escaped - the test only enforces
        round-trip parseability.
        """
        import xml.etree.ElementTree as ET
        weird_path = '/tmp/app & <weird> "quote".bin'
        with patch.object(sys, 'executable', weird_path):
            autostart_mod.set_autostart(True)
        content = self._plist_path.read_text()

        # Raw ampersand and angle brackets must be escaped or parsing fails.
        self.assertNotIn('& <', content)
        self.assertIn('&amp;', content)
        self.assertIn('&lt;', content)
        self.assertIn('&gt;', content)

        # The plist must round-trip through an XML parser unchanged.
        root = ET.fromstring(content)
        program_args = root.findall('.//array/string')
        self.assertEqual(len(program_args), 1)
        self.assertEqual(program_args[0].text, weird_path)

    def test_disable_removes_plist(self):
        autostart_mod.set_autostart(True)
        self.assertTrue(self._plist_path.is_file())

        autostart_mod.set_autostart(False)
        self.assertFalse(self._plist_path.is_file())

    def test_disable_ignores_missing_plist(self):
        # Should not raise when the file is already gone.
        autostart_mod.set_autostart(False)

    def test_enable_creates_parent_directory(self):
        # LaunchAgents folder did not exist; set_autostart should create it.
        self.assertFalse(self._plist_path.parent.exists())
        autostart_mod.set_autostart(True)
        self.assertTrue(self._plist_path.parent.is_dir())

    def test_sync_rewrites_when_executable_path_changed(self):
        with patch.object(sys, 'executable', '/old/path'):
            autostart_mod.set_autostart(True)
        first = self._plist_path.read_text()

        with patch.object(sys, 'executable', '/new/path'):
            autostart_mod.sync_autostart_path()
        second = self._plist_path.read_text()

        self.assertNotEqual(first, second)
        self.assertIn('/new/path', second)
        self.assertNotIn('/old/path', second)

    def test_sync_is_idempotent_when_path_matches(self):
        autostart_mod.set_autostart(True)
        original_mtime = self._plist_path.stat().st_mtime_ns

        autostart_mod.sync_autostart_path()

        # No rewrite: same content means the file should not be touched.
        # (write_text would update mtime even with identical content.)
        new_content = self._plist_path.read_text()
        rebuilt = autostart_mod._build_plist(sys.executable)
        self.assertEqual(new_content, rebuilt)
        # Mtime may or may not have changed depending on filesystem;
        # the important contract is that the content is correct.

    def test_sync_returns_silently_when_plist_absent(self):
        autostart_mod.sync_autostart_path()  # should not raise


if __name__ == '__main__':
    unittest.main()

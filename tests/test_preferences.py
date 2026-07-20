"""Tests for the tray-menu preference store (preferences.py)."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from usage_monitor_for_claude import preferences as prefs


class TestPreferences(unittest.TestCase):
    """Public getter/setter contract, independent of the OS backend."""

    def test_defaults(self):
        """A fresh install sees compact icons and double-click enabled."""
        with patch.object(prefs, '_read_str', lambda name, default: default), \
             patch.object(prefs, '_read_bool', lambda name, default: default):
            self.assertEqual(prefs.get_icon_layout(), prefs.ICON_LAYOUT_COMPACT)
            self.assertEqual(prefs.DEFAULT_ICON_LAYOUT, prefs.ICON_LAYOUT_COMPACT)
            self.assertIs(prefs.get_dblclick_open_claude(), True)
            self.assertIs(prefs.DEFAULT_DBLCLICK_OPEN_CLAUDE, True)

    def test_unrecognized_layout_falls_back_to_default(self):
        """A corrupt stored layout value is ignored in favor of the default."""
        with patch.object(prefs, '_read_str', lambda name, default: 'bogus'):
            self.assertEqual(prefs.get_icon_layout(), prefs.DEFAULT_ICON_LAYOUT)

    def test_set_icon_layout_validates(self):
        with self.assertRaises(ValueError):
            prefs.set_icon_layout('not-a-layout')

    def test_round_trip(self):
        """set_* then get_* returns the stored value (backend mocked in-memory)."""
        store: dict[str, object] = {}
        with patch.object(prefs, '_read_str', lambda name, default: store.get(name, default)), \
             patch.object(prefs, '_write_str', lambda name, value: store.__setitem__(name, value)), \
             patch.object(prefs, '_read_bool', lambda name, default: bool(store[name]) if name in store else default), \
             patch.object(prefs, '_write_bool', lambda name, value: store.__setitem__(name, bool(value))):
            prefs.set_icon_layout(prefs.ICON_LAYOUT_CLASSIC)
            self.assertEqual(prefs.get_icon_layout(), prefs.ICON_LAYOUT_CLASSIC)
            prefs.set_icon_layout(prefs.ICON_LAYOUT_COMPACT)
            self.assertEqual(prefs.get_icon_layout(), prefs.ICON_LAYOUT_COMPACT)
            prefs.set_dblclick_open_claude(False)
            self.assertIs(prefs.get_dblclick_open_claude(), False)
            prefs.set_dblclick_open_claude(True)
            self.assertIs(prefs.get_dblclick_open_claude(), True)


@unittest.skipUnless(sys.platform == 'darwin', 'macOS NSUserDefaults backend')
class TestMacOSBackend(unittest.TestCase):
    """Guards specific to the NSUserDefaults backend used by the bundled .app."""

    def test_suite_name_differs_from_bundle_id(self):
        """The suite must not equal the app's bundle id.

        ``NSUserDefaults.initWithSuiteName_`` returns ``nil`` for the
        receiver's own bundle domain, which would crash the app on launch.
        """
        self.assertNotEqual(prefs._SUITE, 'com.usage-monitor-for-claude')

    def test_nil_store_reads_fall_back_to_defaults(self):
        """A nil store (no usable defaults) degrades to defaults, never crashes."""
        with patch.object(prefs, '_defaults', lambda: None):
            self.assertEqual(prefs._read_str('IconLayout', 'compact'), 'compact')
            self.assertIs(prefs._read_bool('DblclickOpenClaude', True), True)

    def test_nil_store_writes_are_noops(self):
        """Writing with a nil store must not raise."""
        with patch.object(prefs, '_defaults', lambda: None):
            prefs._write_str('IconLayout', 'classic')
            prefs._write_bool('DblclickOpenClaude', False)


if __name__ == '__main__':
    unittest.main()


class TestLanguagePreference(unittest.TestCase):
    """Tests for the Language menu preference accessors."""

    def test_default_is_system(self):
        """No stored value means system default (empty string)."""
        with patch.object(prefs, '_read_str', lambda name, default: default):
            self.assertEqual(prefs.get_language(), '')

    def test_roundtrip(self):
        """set_language persists a code that get_language returns."""
        store = {}
        with patch.object(prefs, '_read_str', lambda name, default: store.get(name, default)), \
             patch.object(prefs, '_write_str', lambda name, value: store.__setitem__(name, value)):
            prefs.set_language('pt-BR')
            self.assertEqual(prefs.get_language(), 'pt-BR')
            prefs.set_language('')
            self.assertEqual(prefs.get_language(), '')

"""
Settings Tests
================

Unit tests for settings file loading and settings constant overrides.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import usage_monitor_for_claude.settings as settings_mod


def _load(app_dir: Path, home_dir: Path) -> dict:
    """Call _load_settings with controlled app_dir and home_dir."""
    fake_file = str(app_dir / 'usage_monitor_for_claude' / 'settings.py')
    with patch.object(settings_mod, '__file__', fake_file), \
         patch.object(Path, 'home', return_value=home_dir), \
         patch.object(settings_mod, 'ctypes', MagicMock()):
        return settings_mod._load_settings()


class TestLoadSettings(unittest.TestCase):
    """Tests for _load_settings() file discovery and parsing."""

    def test_no_file_returns_empty_dict(self):
        """Missing settings file in both locations returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_app_dir_file_loaded(self):
        """Settings file next to the app is found and loaded."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            settings = {'poll_interval': 300}
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, settings)

    def test_home_dir_fallback(self):
        """Falls back to ~/.claude/ when no file next to app."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            claude_dir = Path(home_tmp) / '.claude'
            claude_dir.mkdir()
            settings = {'bg': '#000000'}
            (claude_dir / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, settings)

    def test_app_dir_takes_priority(self):
        """File next to app wins over ~/.claude/ file."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            app_settings = {'poll_interval': 60}
            home_settings = {'poll_interval': 300}
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(app_settings), encoding='utf-8')
            claude_dir = Path(home_tmp) / '.claude'
            claude_dir.mkdir()
            (claude_dir / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(home_settings), encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result['poll_interval'], 60)

    def test_empty_json_object(self):
        """An empty JSON object is valid and returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('{}', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_empty_file_returns_empty_dict(self):
        """A completely empty file is treated as no settings."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_whitespace_only_file_returns_empty_dict(self):
        """A file with only whitespace is treated as no settings."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('  \n\t\n  ', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_invalid_json_returns_empty_dict(self):
        """Malformed JSON shows error and returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('{broken', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_invalid_json_shows_message_box(self):
        """Malformed JSON triggers a Windows MessageBox."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('{broken', encoding='utf-8')
            fake_file = str(Path(app_tmp) / 'usage_monitor_for_claude' / 'settings.py')
            mock_ctypes = MagicMock()
            with patch.object(settings_mod, '__file__', fake_file), \
                 patch.object(Path, 'home', return_value=Path(home_tmp)), \
                 patch.object(settings_mod, 'ctypes', mock_ctypes):
                settings_mod._load_settings()
            mock_ctypes.windll.user32.MessageBoxW.assert_called_once()

    def test_json_array_returns_empty_dict(self):
        """JSON root that is not an object shows error and returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('[1, 2, 3]', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_json_string_returns_empty_dict(self):
        """JSON root that is a string shows error and returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text('"hello"', encoding='utf-8')
            result = _load(Path(app_tmp), Path(home_tmp))
        self.assertEqual(result, {})

    def test_unreadable_file_returns_empty_dict(self):
        """File that cannot be read returns empty dict."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            fake_file = str(Path(app_tmp) / 'usage_monitor_for_claude' / 'settings.py')
            with patch.object(settings_mod, '__file__', fake_file), \
                 patch.object(Path, 'home', return_value=Path(home_tmp)), \
                 patch.object(settings_mod, 'ctypes', MagicMock()), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch.object(Path, 'read_text', side_effect=PermissionError('access denied')):
                result = settings_mod._load_settings()
        self.assertEqual(result, {})

    def test_frozen_uses_executable_dir(self):
        """When frozen, looks next to sys.executable."""
        with TemporaryDirectory() as exe_tmp, TemporaryDirectory() as home_tmp:
            settings = {'poll_error': 10}
            (Path(exe_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            with patch.object(settings_mod.sys, 'frozen', True, create=True), \
                 patch.object(settings_mod.sys, 'executable', str(Path(exe_tmp) / 'app.exe')), \
                 patch.object(Path, 'home', return_value=Path(home_tmp)), \
                 patch.object(settings_mod, 'ctypes', MagicMock()):
                result = settings_mod._load_settings()
        self.assertEqual(result, settings)

    def test_invalid_value_type_dropped_during_load(self):
        """Invalid value types are dropped during loading, MessageBox shown."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            settings = {'poll_interval': 'not_a_number', 'poll_fast': 30}
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            fake_file = str(Path(app_tmp) / 'usage_monitor_for_claude' / 'settings.py')
            mock_ctypes = MagicMock()
            with patch.object(settings_mod, '__file__', fake_file), \
                 patch.object(Path, 'home', return_value=Path(home_tmp)), \
                 patch.object(settings_mod, 'ctypes', mock_ctypes):
                result = settings_mod._load_settings()
            self.assertNotIn('poll_interval', result)
            self.assertEqual(result['poll_fast'], 30)
            mock_ctypes.windll.user32.MessageBoxW.assert_called_once()


class TestSettingsOverrides(unittest.TestCase):
    """Tests that settings values properly override default constants."""

    def test_unknown_keys_ignored(self):
        """Unknown keys in settings are silently ignored, defaults unchanged."""
        settings = {'unknown_key': 'value', 'poll_interval': 90}
        self._assert_overrides(settings, [('POLL_INTERVAL', 90), ('POLL_FAST', 60)])

    def test_polling_overrides(self):
        """Polling constants are overridden by settings."""
        settings = {'poll_interval': 300, 'poll_fast': 30, 'poll_fast_extra': 5, 'poll_error': 10}
        self._assert_overrides(settings, [
            ('POLL_INTERVAL', 300), ('POLL_FAST', 30), ('POLL_FAST_EXTRA', 5), ('POLL_ERROR', 10),
        ])

    def test_popup_color_overrides(self):
        """Popup color constants are overridden by settings."""
        settings = {'bg': '#000000', 'fg': '#ffffff', 'bar_fg': '#00ff00'}
        self._assert_overrides(settings, [('BG', '#000000'), ('FG', '#ffffff'), ('BAR_FG', '#00ff00')])

    def test_partial_override_keeps_defaults(self):
        """Unspecified keys retain their default values."""
        settings = {'poll_interval': 300}
        self._assert_overrides(settings, [('POLL_INTERVAL', 300), ('POLL_FAST', 60), ('BG', '#1e1e1e')])

    def test_icon_color_override(self):
        """Icon color dicts are merged, JSON arrays become tuples."""
        settings = {'icon_light': {'fg': [0, 255, 0, 255]}}
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            loaded = _load(Path(app_tmp), Path(home_tmp))

        original_S = settings_mod._S
        try:
            settings_mod._S = loaded
            icon_light = settings_mod._icon_colors('icon_light', {
                'fg': (255, 255, 255, 255), 'fg_half': (255, 255, 255, 80), 'fg_dim': (255, 255, 255, 140),
            })
        finally:
            settings_mod._S = original_S

        self.assertEqual(icon_light['fg'], (0, 255, 0, 255))
        self.assertEqual(icon_light['fg_half'], (255, 255, 255, 80))
        self.assertEqual(icon_light['fg_dim'], (255, 255, 255, 140))

    _DEFAULTS = {
        'POLL_INTERVAL': 120, 'POLL_FAST': 60, 'POLL_FAST_EXTRA': 2, 'POLL_ERROR': 30,
        'BG': '#1e1e1e', 'FG': '#cccccc', 'FG_DIM': '#888888', 'FG_HEADING': '#ffffff',
        'BAR_BG': '#333333', 'BAR_FG': '#4a9eff', 'BAR_FG_HIGH': '#e05050',
    }

    def _assert_overrides(self, settings: dict, expected: list[tuple[str, object]]) -> None:
        """Load settings and verify that .get() with defaults produces expected values."""
        with TemporaryDirectory() as app_tmp, TemporaryDirectory() as home_tmp:
            (Path(app_tmp) / settings_mod.SETTINGS_FILENAME).write_text(json.dumps(settings), encoding='utf-8')
            loaded = _load(Path(app_tmp), Path(home_tmp))

        for key, value in expected:
            actual = loaded.get(key.lower(), self._DEFAULTS[key])
            self.assertEqual(actual, value, f'{key} should be {value!r}, got {actual!r}')


class TestSettingsValidation(unittest.TestCase):
    """Tests that invalid setting values are rejected with a MessageBox."""

    def test_valid_settings_no_message_box(self):
        """Valid settings pass through without MessageBox."""
        data = {'poll_interval': 300, 'bg': '#000', 'icon_light': {'fg': [0, 255, 0, 255]}}
        result, mock = self._run_validate(data)
        self.assertEqual(result, data)
        mock.windll.user32.MessageBoxW.assert_not_called()

    def test_string_for_numeric_key(self):
        """String value for numeric key is dropped."""
        result, mock = self._run_validate({'poll_interval': 'abc'})
        self.assertNotIn('poll_interval', result)
        mock.windll.user32.MessageBoxW.assert_called_once()

    def test_bool_for_numeric_key(self):
        """Boolean for numeric key is dropped (bool is subclass of int)."""
        result, _ = self._run_validate({'poll_fast': True})
        self.assertNotIn('poll_fast', result)

    def test_negative_numeric_value(self):
        """Negative numeric value is dropped."""
        result, _ = self._run_validate({'poll_error': -5})
        self.assertNotIn('poll_error', result)

    def test_zero_numeric_value(self):
        """Zero numeric value is dropped (must be > 0)."""
        result, _ = self._run_validate({'poll_interval': 0})
        self.assertNotIn('poll_interval', result)

    def test_float_numeric_value_valid(self):
        """Float values are valid for numeric keys."""
        result, mock = self._run_validate({'poll_interval': 120.5})
        self.assertEqual(result['poll_interval'], 120.5)
        mock.windll.user32.MessageBoxW.assert_not_called()

    def test_non_string_color(self):
        """Non-string value for color key is dropped."""
        result, _ = self._run_validate({'bg': 42})
        self.assertNotIn('bg', result)

    def test_non_dict_icon(self):
        """Non-dict value for icon key is dropped."""
        result, _ = self._run_validate({'icon_light': 'invalid'})
        self.assertNotIn('icon_light', result)

    def test_icon_invalid_rgba_length(self):
        """Icon color with wrong array length is dropped."""
        result, _ = self._run_validate({'icon_light': {'fg': [255, 255]}})
        self.assertNotIn('fg', result['icon_light'])

    def test_icon_rgba_out_of_range(self):
        """Icon color with value > 255 is dropped."""
        result, _ = self._run_validate({'icon_dark': {'fg': [0, 256, 0, 255]}})
        self.assertNotIn('fg', result['icon_dark'])

    def test_icon_rgba_negative(self):
        """Icon color with negative value is dropped."""
        result, _ = self._run_validate({'icon_dark': {'fg': [0, -1, 0, 255]}})
        self.assertNotIn('fg', result['icon_dark'])

    def test_icon_rgba_with_float(self):
        """Icon color with float values is dropped (must be int)."""
        result, _ = self._run_validate({'icon_light': {'fg': [0.0, 255, 0, 255]}})
        self.assertNotIn('fg', result['icon_light'])

    def test_icon_rgba_with_bool(self):
        """Icon color with boolean values is dropped."""
        result, _ = self._run_validate({'icon_light': {'fg': [True, 0, 0, 255]}})
        self.assertNotIn('fg', result['icon_light'])

    def test_icon_valid_and_invalid_mixed(self):
        """Valid icon sub-entries kept, invalid ones dropped."""
        data = {'icon_light': {'fg': [0, 255, 0, 255], 'fg_half': [255, 255]}}
        result, _ = self._run_validate(data)
        self.assertEqual(result['icon_light']['fg'], [0, 255, 0, 255])
        self.assertNotIn('fg_half', result['icon_light'])

    def test_unknown_keys_pass_through(self):
        """Unknown keys are not validated or removed."""
        result, mock = self._run_validate({'custom_key': [1, 2, 3]})
        self.assertEqual(result['custom_key'], [1, 2, 3])
        mock.windll.user32.MessageBoxW.assert_not_called()

    def test_multiple_errors_single_message_box(self):
        """Multiple invalid values produce exactly one MessageBox."""
        result, mock = self._run_validate({'poll_interval': 'x', 'bg': 42, 'poll_fast': -1})
        mock.windll.user32.MessageBoxW.assert_called_once()
        self.assertEqual(result, {})

    def test_valid_kept_when_invalid_dropped(self):
        """Valid values are kept when invalid ones are dropped."""
        result, _ = self._run_validate({'poll_interval': 'bad', 'poll_fast': 60, 'bg': '#000'})
        self.assertNotIn('poll_interval', result)
        self.assertEqual(result['poll_fast'], 60)
        self.assertEqual(result['bg'], '#000')

    def _run_validate(self, data: dict) -> tuple[dict, MagicMock]:
        """Run _validate with mocked ctypes and return (result, mock_ctypes)."""
        mock_ctypes = MagicMock()
        with patch.object(settings_mod, 'ctypes', mock_ctypes):
            result = settings_mod._validate(dict(data), Path('/fake/settings.json'))
        return result, mock_ctypes


if __name__ == '__main__':
    unittest.main()

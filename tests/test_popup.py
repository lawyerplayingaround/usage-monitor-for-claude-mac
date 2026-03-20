"""
Popup Tests
=============

Unit tests for popup data helpers: _usage_entries, _snapshot_to_dict,
and _init_config.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.cache import CacheSnapshot
from usage_monitor_for_claude.popup import _init_config, _snapshot_to_dict, _usage_entries


def _snap(
    usage=None, profile=None, last_success_time=None,
    refreshing=False, last_error=None, version=1,
) -> CacheSnapshot:
    """Build a CacheSnapshot with convenient defaults."""
    return CacheSnapshot(
        usage=usage or {},
        profile=profile,
        last_success_time=last_success_time,
        refreshing=refreshing,
        last_error=last_error,
        version=version,
    )


# ---------------------------------------------------------------------------
# _usage_entries
# ---------------------------------------------------------------------------

class TestUsageEntries(unittest.TestCase):
    """Tests for _usage_entries - extracts labelled tuples from usage dict."""

    def test_all_four_entries_returned(self):
        """Always returns exactly four entries regardless of content."""
        entries = _usage_entries({})
        self.assertEqual(len(entries), 4)

    def test_labels_match_translation_keys(self):
        """Each entry's label comes from the translation dict."""
        from usage_monitor_for_claude.i18n import T

        entries = _usage_entries({})
        labels = [e[0] for e in entries]
        self.assertEqual(labels, [T['session'], T['weekly'], T['weekly_sonnet'], T['weekly_opus']])

    def test_periods_are_correct(self):
        """5h entry uses 18000s, 7d entries use 604800s."""
        entries = _usage_entries({})
        periods = [e[2] for e in entries]
        self.assertEqual(periods, [5 * 3600, 7 * 24 * 3600, 7 * 24 * 3600, 7 * 24 * 3600])

    def test_data_extraction(self):
        """Entry data is pulled from the correct usage dict keys."""
        five_hour = {'utilization': 42, 'resets_at': '2026-01-01T00:00:00Z'}
        seven_day = {'utilization': 10, 'resets_at': '2026-01-07T00:00:00Z'}
        usage = {'five_hour': five_hour, 'seven_day': seven_day}

        entries = _usage_entries(usage)
        self.assertIs(entries[0][1], five_hour)
        self.assertIs(entries[1][1], seven_day)
        self.assertIsNone(entries[2][1])  # seven_day_sonnet missing
        self.assertIsNone(entries[3][1])  # seven_day_opus missing


# ---------------------------------------------------------------------------
# _snapshot_to_dict
# ---------------------------------------------------------------------------

class TestSnapshotToDict(unittest.TestCase):
    """Tests for _snapshot_to_dict - converts CacheSnapshot to popup JSON."""

    # -- profile --

    def test_no_profile(self):
        """Profile is None when snapshot has no profile."""
        result = _snapshot_to_dict(_snap(), installations=[])
        self.assertIsNone(result['profile'])

    def test_profile_extraction(self):
        """Email and plan are extracted from nested account/organization dicts."""
        profile = {
            'account': {'email': 'test@example.com'},
            'organization': {'organization_type': 'pro_team'},
        }
        result = _snapshot_to_dict(_snap(profile=profile), installations=[])
        self.assertEqual(result['profile']['email'], 'test@example.com')
        self.assertEqual(result['profile']['plan'], 'Pro Team')

    def test_empty_profile_hidden(self):
        """Empty profile dict from API is treated as absent (no broken UI)."""
        result = _snapshot_to_dict(_snap(profile={}), installations=[])
        self.assertIsNone(result['profile'])

    def test_profile_missing_nested_keys(self):
        """Present but incomplete profile defaults missing fields to empty strings."""
        result = _snapshot_to_dict(_snap(profile={'account': {}}), installations=[])
        self.assertEqual(result['profile']['email'], '')
        self.assertEqual(result['profile']['plan'], '')

    # -- usage bars --

    def test_no_usage_data(self):
        """Empty usage dict produces empty usage list."""
        result = _snapshot_to_dict(_snap(), installations=[])
        self.assertEqual(result['usage'], [])

    def test_skips_entries_without_utilization(self):
        """Entries with None utilization are omitted."""
        usage = {'five_hour': {'utilization': None}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertEqual(result['usage'], [])

    def test_skips_missing_entries(self):
        """Missing usage keys produce no bar entries."""
        usage = {'five_hour': None}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertEqual(result['usage'], [])

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=None)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='5h 0m')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_usage_bar_fields(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Each usage bar dict has all required fields with correct types."""
        usage = {'five_hour': {'utilization': 42, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])

        self.assertEqual(len(result['usage']), 1)
        bar = result['usage'][0]
        self.assertEqual(bar['pct_text'], '42%')
        self.assertAlmostEqual(bar['fill_pct'], 0.42)
        self.assertFalse(bar['warn'])
        self.assertIsNone(bar['marker_rel'])
        self.assertEqual(bar['reset_text'], '5h 0m')
        self.assertEqual(bar['midnights'], [])

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=30.0)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='3h 30m')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[0.5])
    def test_warn_when_usage_ahead_of_time(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Bar is marked warn when utilization exceeds elapsed percentage."""
        usage = {'five_hour': {'utilization': 60, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])

        bar = result['usage'][0]
        self.assertTrue(bar['warn'])
        self.assertAlmostEqual(bar['marker_rel'], 0.3)

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=80.0)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='1h 0m')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_no_warn_when_usage_behind_time(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Bar is not warn when utilization is below elapsed percentage."""
        usage = {'five_hour': {'utilization': 40, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])

        bar = result['usage'][0]
        self.assertFalse(bar['warn'])

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=50.0)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='2h 30m')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_no_warn_when_equal(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Exactly equal usage and elapsed is not a warning (strictly greater)."""
        usage = {'five_hour': {'utilization': 50, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertFalse(result['usage'][0]['warn'])

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=None)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_fill_pct_clamped_to_0_1(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Fill percentage is clamped between 0.0 and 1.0."""
        usage = {'five_hour': {'utilization': 150, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertEqual(result['usage'][0]['fill_pct'], 1.0)

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=None)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_zero_utilization(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Zero utilization produces 0% text and 0.0 fill."""
        usage = {'five_hour': {'utilization': 0, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        # utilization 0 is falsy, so `or 0` kicks in - entry is still shown
        bar = result['usage'][0]
        self.assertEqual(bar['pct_text'], '0%')
        self.assertAlmostEqual(bar['fill_pct'], 0.0)

    @patch('usage_monitor_for_claude.popup.elapsed_pct', return_value=None)
    @patch('usage_monitor_for_claude.popup.time_until', return_value='')
    @patch('usage_monitor_for_claude.popup.midnight_positions', return_value=[])
    def test_multiple_usage_entries(self, _mock_midnights, _mock_time_until, _mock_elapsed):
        """Multiple usage types each produce a bar entry."""
        usage = {
            'five_hour': {'utilization': 10, 'resets_at': '2026-01-01T05:00:00Z'},
            'seven_day': {'utilization': 20, 'resets_at': '2026-01-07T00:00:00Z'},
            'seven_day_sonnet': {'utilization': 30, 'resets_at': '2026-01-07T00:00:00Z'},
        }
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertEqual(len(result['usage']), 3)
        pcts = [b['pct_text'] for b in result['usage']]
        self.assertEqual(pcts, ['10%', '20%', '30%'])

    # -- extra usage --

    def test_no_extra_usage(self):
        """Extra is None when no extra_usage key in usage dict."""
        result = _snapshot_to_dict(_snap(), installations=[])
        self.assertIsNone(result['extra'])

    def test_extra_usage_disabled(self):
        """Extra is None when extra usage is not enabled."""
        usage = {'extra_usage': {'is_enabled': False, 'monthly_limit': 1000, 'used_credits': 500}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertIsNone(result['extra'])

    def test_extra_usage_zero_limit(self):
        """Extra is None when monthly limit is zero."""
        usage = {'extra_usage': {'is_enabled': True, 'monthly_limit': 0, 'used_credits': 0}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertIsNone(result['extra'])

    @patch('usage_monitor_for_claude.popup.format_credits', side_effect=lambda c: f'${c / 100:.2f}')
    def test_extra_usage_calculation(self, _mock_credits):
        """Extra usage computes percentage and formatted text correctly."""
        usage = {'extra_usage': {'is_enabled': True, 'monthly_limit': 10000, 'used_credits': 2500}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])

        extra = result['extra']
        self.assertIsNotNone(extra)
        self.assertEqual(extra['pct_text'], '25%')
        self.assertAlmostEqual(extra['fill_pct'], 0.25)
        self.assertIn('$25.00', extra['spent_text'])
        self.assertIn('$100.00', extra['spent_text'])

    @patch('usage_monitor_for_claude.popup.format_credits', side_effect=lambda c: f'${c / 100:.2f}')
    def test_extra_usage_fill_clamped(self, _mock_credits):
        """Extra usage fill is clamped to 1.0 when over limit."""
        usage = {'extra_usage': {'is_enabled': True, 'monthly_limit': 1000, 'used_credits': 2000}}
        result = _snapshot_to_dict(_snap(usage=usage), installations=[])
        self.assertEqual(result['extra']['fill_pct'], 1.0)

    # -- installations --

    def test_installations_passthrough(self):
        """Pre-computed installations list is passed through unchanged."""
        installs = [{'name': 'VS Code', 'version': '1.0.0'}]
        result = _snapshot_to_dict(_snap(), installations=installs)
        self.assertEqual(result['installations'], installs)

    @patch('usage_monitor_for_claude.popup.find_installations')
    def test_installations_auto_detected(self, mock_find):
        """When installations is None, find_installations() is called."""
        inst = MagicMock()
        inst.name = 'Cursor'
        inst.version = '2.0.0'
        mock_find.return_value = [inst]

        result = _snapshot_to_dict(_snap(), installations=None)
        mock_find.assert_called_once()
        self.assertEqual(result['installations'], [{'name': 'Cursor', 'version': '2.0.0'}])

    # -- status --

    def test_status_error_when_no_usage(self):
        """Shows error text when there's no usage data but there's an error."""
        result = _snapshot_to_dict(_snap(usage={}, last_error='Connection failed'), installations=[])
        self.assertEqual(result['status']['text'], 'Connection failed')
        self.assertTrue(result['status']['is_error'])

    def test_status_error_truncated(self):
        """Error messages are truncated to 120 characters."""
        long_error = 'x' * 200
        result = _snapshot_to_dict(_snap(usage={}, last_error=long_error), installations=[])
        self.assertEqual(len(result['status']['text']), 120)

    def test_status_refreshing_when_no_usage_no_error(self):
        """Shows refreshing status when no usage data and no error."""
        from usage_monitor_for_claude.i18n import T

        result = _snapshot_to_dict(_snap(usage={}, last_error=None), installations=[])
        self.assertEqual(result['status']['text'], T['status_refreshing'])
        self.assertFalse(result['status']['is_error'])

    @patch('usage_monitor_for_claude.popup.format_status', return_value=('Updated just now', False))
    def test_status_from_format_status_when_usage_present(self, _mock_fmt):
        """Uses format_status when usage data is available."""
        usage = {'five_hour': {'utilization': 50, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage, last_success_time=1000.0), installations=[])
        self.assertEqual(result['status']['text'], 'Updated just now')
        self.assertFalse(result['status']['is_error'])

    @patch('usage_monitor_for_claude.popup.format_status', return_value=('Error: timeout', True))
    def test_status_error_flag_from_format_status(self, _mock_fmt):
        """Error flag from format_status is propagated."""
        usage = {'five_hour': {'utilization': 50, 'resets_at': '2026-01-01T05:00:00Z'}}
        result = _snapshot_to_dict(_snap(usage=usage, last_error='timeout'), installations=[])
        self.assertTrue(result['status']['is_error'])

    # -- top-level dict structure --

    def test_all_top_level_keys_present(self):
        """Result always has profile, usage, extra, installations, status."""
        result = _snapshot_to_dict(_snap(), installations=[])
        self.assertEqual(set(result.keys()), {'profile', 'usage', 'extra', 'installations', 'status'})


# ---------------------------------------------------------------------------
# _init_config
# ---------------------------------------------------------------------------

class TestInitConfig(unittest.TestCase):
    """Tests for _init_config - builds the JS init() config object."""

    def test_top_level_keys(self):
        """Config has colors, t (translations), and data."""
        config = _init_config(_snap())
        self.assertEqual(set(config.keys()), {'colors', 't', 'data'})

    def test_colors_from_settings(self):
        """Color values come from settings module constants."""
        from usage_monitor_for_claude.settings import BAR_BG, BAR_FG, BAR_FG_WARN, BAR_MARKER, BG, FG, FG_DIM, FG_HEADING, FG_LINK

        config = _init_config(_snap())
        colors = config['colors']
        self.assertEqual(colors['bg'], BG)
        self.assertEqual(colors['fg'], FG)
        self.assertEqual(colors['fg_dim'], FG_DIM)
        self.assertEqual(colors['fg_heading'], FG_HEADING)
        self.assertEqual(colors['fg_link'], FG_LINK)
        self.assertEqual(colors['bar_bg'], BAR_BG)
        self.assertEqual(colors['bar_fg'], BAR_FG)
        self.assertEqual(colors['bar_fg_warn'], BAR_FG_WARN)
        self.assertEqual(colors['bar_marker'], BAR_MARKER)

    def test_translations_from_i18n(self):
        """Translation values come from the T dict."""
        from usage_monitor_for_claude.i18n import T

        config = _init_config(_snap())
        t = config['t']
        self.assertEqual(t['title'], T['popup_title'])
        self.assertEqual(t['account'], T['account'])
        self.assertEqual(t['email'], T['email'])
        self.assertEqual(t['plan'], T['plan'])
        self.assertEqual(t['usage'], T['usage'])
        self.assertEqual(t['extra_usage'], T['extra_usage'])
        self.assertEqual(t['claude_code'], T['claude_code'])
        self.assertEqual(t['changelog'], T['changelog'])

    def test_data_is_snapshot_to_dict_output(self):
        """The data key contains the output of _snapshot_to_dict."""
        snap = _snap(profile={'account': {'email': 'a@b.com'}, 'organization': {}})
        config = _init_config(snap)
        self.assertEqual(config['data']['profile']['email'], 'a@b.com')
        self.assertEqual(set(config['data'].keys()), {'profile', 'usage', 'extra', 'installations', 'status'})


if __name__ == '__main__':
    unittest.main()

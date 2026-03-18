"""
Formatting Tests
=================

Unit tests for elapsed_pct(), time_until(), and format_tooltip().
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.formatting import PERIOD_5H, PERIOD_7D, elapsed_pct, format_credits, format_status, format_tooltip, midnight_positions, time_until
from usage_monitor_for_claude.i18n import LOCALE_DIR

EN = json.loads((LOCALE_DIR / 'en.json').read_text(encoding='utf-8'))


# ---------------------------------------------------------------------------
# elapsed_pct
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.formatting.datetime')
class TestElapsedPct(unittest.TestCase):
    """Tests for elapsed_pct()."""

    def _setup(self, mock_dt, utc_now):
        mock_dt.now.return_value = utc_now
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat

    def test_empty_resets_at(self, mock_dt):
        """Empty resets_at returns None."""
        self.assertIsNone(elapsed_pct('', PERIOD_5H))

    def test_zero_period(self, mock_dt):
        """period_seconds=0 returns None."""
        self.assertIsNone(elapsed_pct('2025-01-15T12:00:00+00:00', 0))

    def test_negative_period(self, mock_dt):
        """Negative period_seconds returns None."""
        self.assertIsNone(elapsed_pct('2025-01-15T12:00:00+00:00', -100))

    def test_invalid_iso_string(self, mock_dt):
        """Invalid ISO string returns None."""
        self._setup(mock_dt, datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc))
        self.assertIsNone(elapsed_pct('not-a-date', PERIOD_5H))

    def test_naive_datetime_returns_none(self, mock_dt):
        """Timezone-naive ISO string causes subtraction error, returns None."""
        self._setup(mock_dt, datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc))
        self.assertIsNone(elapsed_pct('2025-01-15T14:00:00', PERIOD_5H))

    def test_just_started_zero_percent(self, mock_dt):
        """Reset is exactly period_seconds away, 0% elapsed."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        reset = utc_now + timedelta(seconds=PERIOD_5H)
        result = elapsed_pct(reset.isoformat(), PERIOD_5H)

        assert result is not None
        self.assertAlmostEqual(result, 0.0)

    def test_half_elapsed(self, mock_dt):
        """Half of period elapsed, 50%."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        reset = utc_now + timedelta(seconds=PERIOD_5H / 2)
        result = elapsed_pct(reset.isoformat(), PERIOD_5H)

        assert result is not None
        self.assertAlmostEqual(result, 50.0)

    def test_fully_elapsed_hundred_percent(self, mock_dt):
        """Reset is now, 100% elapsed."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        result = elapsed_pct(utc_now.isoformat(), PERIOD_5H)

        assert result is not None
        self.assertAlmostEqual(result, 100.0)

    def test_past_reset_clamped_to_100(self, mock_dt):
        """Reset already passed, clamped to 100%."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        reset = utc_now - timedelta(hours=1)
        result = elapsed_pct(reset.isoformat(), PERIOD_5H)

        assert result is not None
        self.assertAlmostEqual(result, 100.0)

    def test_far_future_clamped_to_0(self, mock_dt):
        """Reset much further out than period duration, clamped to 0%."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        reset = utc_now + timedelta(seconds=PERIOD_5H * 3)
        result = elapsed_pct(reset.isoformat(), PERIOD_5H)

        assert result is not None
        self.assertAlmostEqual(result, 0.0)

    def test_7day_period(self, mock_dt):
        """7-day period, 3.5 days elapsed, 50%."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        self._setup(mock_dt, utc_now)
        reset = utc_now + timedelta(seconds=PERIOD_7D / 2)
        result = elapsed_pct(reset.isoformat(), PERIOD_7D)

        assert result is not None
        self.assertAlmostEqual(result, 50.0)


# ---------------------------------------------------------------------------
# midnight_positions
# ---------------------------------------------------------------------------

class TestMidnightPositions(unittest.TestCase):
    """Tests for midnight_positions().

    Because midnight_positions converts to local time via astimezone(), tests
    construct inputs relative to the system timezone so results are predictable
    on any machine.
    """

    @staticmethod
    def _local_to_utc_iso(naive_local: datetime) -> str:
        """Convert a naive local datetime to a UTC ISO string."""
        return naive_local.astimezone(timezone.utc).isoformat()

    def test_empty_resets_at(self):
        """Empty resets_at returns empty list."""
        self.assertEqual(midnight_positions('', PERIOD_7D), [])

    def test_zero_period(self):
        """period_seconds=0 returns empty list."""
        self.assertEqual(midnight_positions('2025-01-15T12:00:00+00:00', 0), [])

    def test_negative_period(self):
        """Negative period_seconds returns empty list."""
        self.assertEqual(midnight_positions('2025-01-15T12:00:00+00:00', -100), [])

    def test_invalid_iso_string(self):
        """Invalid ISO string returns empty list."""
        self.assertEqual(midnight_positions('not-a-date', PERIOD_7D), [])

    def test_5h_period_no_midnight(self):
        """5h period within a single day has no midnight crossings."""
        # Period: 10:00-15:00 local on the same day - no midnight
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 15, 15, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_5H)
        self.assertEqual(result, [])

    def test_7d_period_has_seven_midnights(self):
        """7-day period from noon to noon has exactly 7 internal midnight boundaries."""
        # Period: Jan 15 12:00 to Jan 22 12:00 local - midnights on Jan 16-22
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 22, 12, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_7D)
        self.assertEqual(len(result), 7)

    def test_positions_are_sorted_ascending(self):
        """Positions must be in ascending order."""
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 22, 12, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_7D)
        self.assertEqual(result, sorted(result))

    def test_positions_in_valid_range(self):
        """All positions must be in the range (0.0, 1.0) exclusive."""
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 22, 12, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_7D)
        for pos in result:
            self.assertGreater(pos, 0.0)
            self.assertLess(pos, 1.0)

    def test_5h_period_spanning_midnight(self):
        """5h period crossing local midnight has exactly one midnight position."""
        # Period: 23:00-04:00 local, crosses one midnight
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 16, 4, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_5H)
        self.assertEqual(len(result), 1)

    def test_5h_midnight_position_is_correct(self):
        """Midnight position in a 5h period crossing midnight at the expected fraction."""
        # Period: 23:00-04:00 local. Midnight is 1h into a 5h period = 0.2
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 16, 4, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_5H)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], 0.2, places=2)

    def test_near_zero_positions_filtered(self):
        """Positions very close to 0.0 (< 0.003) are filtered out."""
        # Period: 23:59:50-04:59:50 local. Midnight is 10s in = 10/18000 ≈ 0.00056, filtered.
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 16, 4, 59, 50))
        result = midnight_positions(reset_iso, PERIOD_5H)
        for pos in result:
            self.assertGreater(pos, 0.003)

    def test_7d_first_position_approximately_correct(self):
        """First midnight in a 7d period starting at noon is at roughly 1/14 of the bar."""
        # Period: Jan 15 12:00 to Jan 22 12:00 local. First midnight is 12h into 168h = 1/14
        reset_iso = self._local_to_utc_iso(datetime(2025, 1, 22, 12, 0, 0))
        result = midnight_positions(reset_iso, PERIOD_7D)
        self.assertGreater(len(result), 0)
        self.assertAlmostEqual(result[0], 12 / 168, places=2)


# ---------------------------------------------------------------------------
# time_until
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.formatting.T', EN)
@patch('usage_monitor_for_claude.formatting.datetime')
class TestTimeUntil(unittest.TestCase):
    """Tests for time_until().

    Uses MagicMock for fromisoformat's return value so that
    astimezone() returns a controlled local datetime, making
    tests timezone-independent.
    """

    def _setup(self, mock_dt, utc_now, local_now, reset_local, remaining):
        mock_dt.now.side_effect = lambda tz=None: utc_now if tz else local_now

        mock_reset = MagicMock()
        mock_reset.__sub__.return_value = remaining
        mock_reset.astimezone.return_value = reset_local
        mock_dt.fromisoformat.return_value = mock_reset

    def test_empty_string(self, mock_dt):
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat
        self.assertEqual(time_until(''), '')

    def test_invalid_string(self, mock_dt):
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat
        self.assertEqual(time_until('not-a-date'), '')

    def test_past_reset_returns_empty(self, mock_dt):
        """Reset in the past (0 remaining minutes) returns empty string."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 11, 0, 0), timedelta(seconds=-3600))
        self.assertEqual(time_until('ignored'), '')

    def test_same_day_hours_and_minutes(self, mock_dt):
        """Reset today with >60 min remaining."""
        utc_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 10, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 30, 0), timedelta(hours=2, minutes=30))
        self.assertEqual(time_until('ignored'), 'Resets in 2h 30m (12:30)')

    def test_same_day_minutes_only(self, mock_dt):
        """Reset today with <60 min remaining."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 45, 0), timedelta(minutes=45))
        self.assertEqual(time_until('ignored'), 'Resets in 45m (12:45)')

    def test_same_day_exactly_60_minutes(self, mock_dt):
        """Exactly 60 minutes uses hours+minutes format."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 13, 0, 0), timedelta(hours=1))
        self.assertEqual(time_until('ignored'), 'Resets in 1h 0m (13:00)')

    def test_same_day_one_minute(self, mock_dt):
        """One minute remaining."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 1, 0), timedelta(minutes=1))
        self.assertEqual(time_until('ignored'), 'Resets in 1m (12:01)')

    def test_tomorrow(self, mock_dt):
        """Reset tomorrow."""
        utc_now = datetime(2025, 1, 15, 22, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 22, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 16, 10, 0, 0), timedelta(hours=12))
        self.assertEqual(time_until('ignored'), 'Resets tomorrow, 10:00')

    def test_future_weekday(self, mock_dt):
        """Reset in a few days shows weekday name."""
        # 2025-01-18 is Saturday (weekday index 5)
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 18, 14, 0, 0), timedelta(days=3, hours=2))
        self.assertEqual(time_until('ignored'), 'Resets on Sat, 14:00')

    def test_seconds_rounded_up(self, mock_dt):
        """Seconds >= 30 round up the displayed minute."""
        utc_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 10, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 30, 45), timedelta(hours=2, minutes=30, seconds=45))
        self.assertEqual(time_until('ignored'), 'Resets in 2h 30m (12:31)')

    def test_seconds_rounded_down(self, mock_dt):
        """Seconds < 30 keep the displayed minute unchanged."""
        utc_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 10, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 30, 15), timedelta(hours=2, minutes=30, seconds=15))
        self.assertEqual(time_until('ignored'), 'Resets in 2h 30m (12:30)')

    def test_seconds_exactly_30_rounds_up(self, mock_dt):
        """Exactly 30 seconds rounds up (>= boundary)."""
        utc_now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 10, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 30, 30), timedelta(hours=2, minutes=30, seconds=30))
        self.assertIn('12:31', time_until('ignored'))

    def test_less_than_60_seconds_returns_empty(self, mock_dt):
        """Less than 60 seconds remaining rounds to 0 minutes, returns empty."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 0, 59), timedelta(seconds=59))
        self.assertEqual(time_until('ignored'), '')

    def test_exactly_60_seconds_shows_one_minute(self, mock_dt):
        """Exactly 60 seconds remaining rounds to 1 minute, shown."""
        utc_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 12, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 12, 1, 0), timedelta(seconds=60))
        self.assertIn('1m', time_until('ignored'))

    def test_rounding_crosses_midnight_changes_branch(self, mock_dt):
        """Second rounding at 23:59:45 rolls over to 00:00 next day, changing branch."""
        utc_now = datetime(2025, 1, 15, 21, 0, 0, tzinfo=timezone.utc)
        local_now = datetime(2025, 1, 15, 21, 0, 0)
        self._setup(mock_dt, utc_now, local_now,
            datetime(2025, 1, 15, 23, 59, 45), timedelta(hours=2, minutes=59, seconds=45))

        result = time_until('ignored')

        self.assertIn('00:00', result)
        self.assertIn('tomorrow', result)


# ---------------------------------------------------------------------------
# format_tooltip
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.formatting.T', EN)
class TestFormatTooltip(unittest.TestCase):
    """Tests for format_tooltip()."""

    def test_error(self):
        result = format_tooltip({'error': 'Connection failed'})
        self.assertEqual(result, 'Usage Monitor: Error\nConnection failed')

    def test_auth_error(self):
        data = {'error': 'Unauthorized', 'auth_error': True}
        result = format_tooltip(data)
        self.assertEqual(result, 'Claude Session Expired\nPlease open Claude Code to refresh your session.')

    def test_error_message_truncated_to_80_chars(self):
        result = format_tooltip({'error': 'x' * 200})
        error_line = result.split('\n')[1]
        self.assertEqual(len(error_line), 80)

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_both_periods(self, _mock_tu):
        data = {
            'five_hour': {'utilization': 42.0, 'resets_at': ''},
            'seven_day': {'utilization': 15.0, 'resets_at': ''},
        }
        self.assertEqual(format_tooltip(data), 'Claude Usage\n5h: 42%\n7d: 15%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='Resets in 2h 30m (14:30)')
    def test_with_reset_info(self, _mock_tu):
        data = {'five_hour': {'utilization': 42.0, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n5h: 42% (Resets in 2h 30m (14:30))')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_utilization_none_skipped(self, _mock_tu):
        data = {
            'five_hour': {'utilization': None, 'resets_at': ''},
            'seven_day': {'utilization': 80.0, 'resets_at': ''},
        }
        self.assertEqual(format_tooltip(data), 'Claude Usage\n7d: 80%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_empty_data_shows_title_only(self, _mock_tu):
        self.assertEqual(format_tooltip({}), 'Claude Usage')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_zero_percent(self, _mock_tu):
        data = {'five_hour': {'utilization': 0.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n5h: 0%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_hundred_percent(self, _mock_tu):
        data = {'five_hour': {'utilization': 100.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n5h: 100%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_entry_none_skipped(self, _mock_tu):
        """Entry that is None is skipped by the guard clause."""
        data = {'five_hour': None, 'seven_day': {'utilization': 50.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n7d: 50%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_entry_empty_dict_skipped(self, _mock_tu):
        """Entry with no utilization key is skipped."""
        data = {'five_hour': {}, 'seven_day': {'utilization': 50.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n7d: 50%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_only_seven_day(self, _mock_tu):
        """Only seven_day present, five_hour absent."""
        data = {'seven_day': {'utilization': 25.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Claude Usage\n7d: 25%')

    def test_auth_error_false_shows_normal_error(self):
        """auth_error=False with error shows normal error, not auth message."""
        data = {'error': 'Something broke', 'auth_error': False}
        result = format_tooltip(data)
        self.assertEqual(result, 'Usage Monitor: Error\nSomething broke')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_extra_usage_ignored(self, _mock_tu):
        """Extra usage data is not shown in tooltip."""
        data = {
            'five_hour': {'utilization': 26.0, 'resets_at': ''},
            'extra_usage': {'is_enabled': True, 'monthly_limit': 1000, 'used_credits': 420.0},
        }
        self.assertEqual(format_tooltip(data), 'Claude Usage\n5h: 26%')


# ---------------------------------------------------------------------------
# tooltip length - Windows limits tooltip text to 127 characters
# ---------------------------------------------------------------------------

class TestTooltipMaxLength(unittest.TestCase):
    """Verify tooltip text stays within Windows' 127-char limit for all locales."""

    TOOLTIP_MAX = 127

    def _longest_reset(self, t: dict, max_hours: int) -> str:
        """Return the longest possible reset text for a given max-hour value."""
        dur = t['duration_hm'].format(h=max_hours, m=59)
        candidates = [
            t['resets_in'].format(duration=dur, clock='23:59'),
            t['resets_tomorrow'].format(clock='23:59'),
        ]
        for wd in t['weekdays']:
            candidates.append(t['resets_weekday'].format(day=wd, clock='23:59'))

        return max(candidates, key=len)

    def _worst_case_tooltip(self, t: dict) -> str:
        """Build the longest possible tooltip from a locale dict.

        Worst case: both 5h and 7d visible at 100%, each with the longest
        possible reset text (same-day, tomorrow, or weekday).
        """
        reset_5h = self._longest_reset(t, max_hours=4)
        reset_7d = self._longest_reset(t, max_hours=23)

        return f"{t['tooltip_title']}\n5h: 100% ({reset_5h})\n7d: 100% ({reset_7d})"

    def test_all_locales_fit_tooltip(self):
        """Every locale's worst-case tooltip must fit in 127 characters."""
        for locale_file in sorted(LOCALE_DIR.glob('*.json')):
            with self.subTest(locale=locale_file.stem):
                t = json.loads(locale_file.read_text(encoding='utf-8'))
                tooltip = self._worst_case_tooltip(t)
                self.assertLessEqual(
                    len(tooltip), self.TOOLTIP_MAX,
                    f"Locale '{locale_file.stem}' tooltip is {len(tooltip)} chars "
                    f"(max {self.TOOLTIP_MAX}):\n{tooltip}",
                )


# ---------------------------------------------------------------------------
# format_credits
# ---------------------------------------------------------------------------

class TestFormatCredits(unittest.TestCase):
    """Tests for format_credits()."""

    @patch('usage_monitor_for_claude.formatting._SYSTEM_CURRENCY_SYMBOL', '$')
    @patch('usage_monitor_for_claude.formatting.CURRENCY_SYMBOL', '$')
    @patch('usage_monitor_for_claude.formatting._locale.currency', return_value='$4.20')
    def test_uses_locale_currency(self, mock_currency):
        """Uses locale.currency() for formatting."""
        self.assertEqual(format_credits(420.0), '$4.20')
        mock_currency.assert_called_once_with(4.2, grouping=True)

    @patch('usage_monitor_for_claude.formatting._SYSTEM_CURRENCY_SYMBOL', '€')
    @patch('usage_monitor_for_claude.formatting.CURRENCY_SYMBOL', '$')
    @patch('usage_monitor_for_claude.formatting._locale.currency', return_value='10,00 €')
    def test_symbol_override_replaces(self, mock_currency):
        """Settings override replaces system symbol in formatted output."""
        self.assertEqual(format_credits(1000.0), '10,00 $')

    @patch('usage_monitor_for_claude.formatting._SYSTEM_CURRENCY_SYMBOL', '')
    @patch('usage_monitor_for_claude.formatting.CURRENCY_SYMBOL', '')
    @patch('usage_monitor_for_claude.formatting._locale.currency', side_effect=ValueError)
    def test_no_symbol_plain_number(self, mock_currency):
        """No currency symbol falls back to plain number."""
        self.assertEqual(format_credits(420.0), '4.20')

    @patch('usage_monitor_for_claude.formatting._SYSTEM_CURRENCY_SYMBOL', '')
    @patch('usage_monitor_for_claude.formatting.CURRENCY_SYMBOL', '¥')
    @patch('usage_monitor_for_claude.formatting._locale.currency', side_effect=ValueError)
    def test_locale_error_uses_symbol_fallback(self, mock_currency):
        """Locale error falls back to manual formatting with symbol."""
        self.assertEqual(format_credits(420.0), '¥\u00a04.20')

    @patch('usage_monitor_for_claude.formatting._SYSTEM_CURRENCY_SYMBOL', '$')
    @patch('usage_monitor_for_claude.formatting.CURRENCY_SYMBOL', '$')
    @patch('usage_monitor_for_claude.formatting._locale.currency', return_value='$0.00')
    def test_zero_cents(self, mock_currency):
        """Zero cents formats correctly."""
        self.assertEqual(format_credits(0.0), '$0.00')


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------

@patch('usage_monitor_for_claude.formatting.T', EN)
class TestFormatStatus(unittest.TestCase):
    """Tests for format_status()."""

    @patch('usage_monitor_for_claude.formatting.time')
    def test_just_now(self, mock_time):
        """Recent success shows 'Updated just now'."""
        mock_time.time.return_value = 1000.0
        text, has_error = format_status(last_success_time=970.0, refreshing=False, last_error=None)

        self.assertEqual(text, 'Updated just now')
        self.assertFalse(has_error)

    @patch('usage_monitor_for_claude.formatting.time')
    def test_minutes_ago(self, mock_time):
        """Success a few minutes ago shows duration."""
        mock_time.time.return_value = 1000.0
        text, has_error = format_status(last_success_time=700.0, refreshing=False, last_error=None)

        self.assertEqual(text, 'Updated 5m ago')
        self.assertFalse(has_error)

    @patch('usage_monitor_for_claude.formatting.time')
    def test_hours_ago(self, mock_time):
        """Success over an hour ago shows hours and minutes."""
        mock_time.time.return_value = 10000.0
        text, has_error = format_status(last_success_time=3400.0, refreshing=False, last_error=None)

        self.assertEqual(text, 'Updated 1h 50m ago')
        self.assertFalse(has_error)

    def test_refreshing_no_previous_data(self):
        """Refreshing with no prior success shows only 'Refreshing...'."""
        text, has_error = format_status(last_success_time=None, refreshing=True, last_error=None)

        self.assertEqual(text, 'Refreshing...')
        self.assertFalse(has_error)

    @patch('usage_monitor_for_claude.formatting.time')
    def test_refreshing_with_previous_data(self, mock_time):
        """Refreshing with cached data shows time and refreshing status."""
        mock_time.time.return_value = 1000.0
        text, has_error = format_status(last_success_time=970.0, refreshing=True, last_error=None)

        self.assertEqual(text, 'Updated just now \u00b7 Refreshing...')
        self.assertFalse(has_error)

    @patch('usage_monitor_for_claude.formatting.time')
    def test_error_with_cached_data(self, mock_time):
        """Error with cached data shows time and error message."""
        mock_time.time.return_value = 1000.0
        text, has_error = format_status(last_success_time=700.0, refreshing=False, last_error='Server down')

        self.assertEqual(text, 'Updated 5m ago \u00b7 Server down')
        self.assertTrue(has_error)

    def test_error_no_cached_data(self):
        """Error with no prior success shows only error message."""
        text, has_error = format_status(last_success_time=None, refreshing=False, last_error='Server down')

        self.assertEqual(text, 'Server down')
        self.assertTrue(has_error)

    def test_no_data_no_error_no_refreshing(self):
        """No data, no error, not refreshing returns empty string."""
        text, has_error = format_status(last_success_time=None, refreshing=False, last_error=None)

        self.assertEqual(text, '')
        self.assertFalse(has_error)


if __name__ == '__main__':
    unittest.main()

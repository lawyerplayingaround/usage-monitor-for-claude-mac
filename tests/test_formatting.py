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

from usage_monitor_for_claude.formatting import PERIOD_5H, PERIOD_7D, elapsed_pct, format_tooltip, time_until
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
        self.assertEqual(format_tooltip(data), 'Account & Usage\n5h: 42%\n7d: 15%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='Resets in 2h 30m (14:30)')
    def test_with_reset_info(self, _mock_tu):
        data = {'five_hour': {'utilization': 42.0, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n5h: 42% (Resets in 2h 30m (14:30))')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_utilization_none_skipped(self, _mock_tu):
        data = {
            'five_hour': {'utilization': None, 'resets_at': ''},
            'seven_day': {'utilization': 80.0, 'resets_at': ''},
        }
        self.assertEqual(format_tooltip(data), 'Account & Usage\n7d: 80%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_empty_data_shows_title_only(self, _mock_tu):
        self.assertEqual(format_tooltip({}), 'Account & Usage')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_zero_percent(self, _mock_tu):
        data = {'five_hour': {'utilization': 0.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n5h: 0%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_hundred_percent(self, _mock_tu):
        data = {'five_hour': {'utilization': 100.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n5h: 100%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_entry_none_skipped(self, _mock_tu):
        """Entry that is None is skipped by the guard clause."""
        data = {'five_hour': None, 'seven_day': {'utilization': 50.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n7d: 50%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_entry_empty_dict_skipped(self, _mock_tu):
        """Entry with no utilization key is skipped."""
        data = {'five_hour': {}, 'seven_day': {'utilization': 50.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n7d: 50%')

    @patch('usage_monitor_for_claude.formatting.time_until', return_value='')
    def test_only_seven_day(self, _mock_tu):
        """Only seven_day present, five_hour absent."""
        data = {'seven_day': {'utilization': 25.0, 'resets_at': ''}}
        self.assertEqual(format_tooltip(data), 'Account & Usage\n7d: 25%')

    def test_auth_error_false_shows_normal_error(self):
        """auth_error=False with error shows normal error, not auth message."""
        data = {'error': 'Something broke', 'auth_error': False}
        result = format_tooltip(data)
        self.assertEqual(result, 'Usage Monitor: Error\nSomething broke')


if __name__ == '__main__':
    unittest.main()

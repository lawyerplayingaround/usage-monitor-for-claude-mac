"""
Application Tests
===================

Unit tests for threshold alert logic in the application module.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.app import UsageMonitorForClaude


def _make_app(thresholds: list[float] | None = None) -> UsageMonitorForClaude:
    """Create a UsageMonitorForClaude with mocked icon and configurable thresholds.

    Parameters
    ----------
    thresholds : list[float] or None
        Alert thresholds to use for all variants.  Defaults to ``[80, 95]``.
    """
    if thresholds is None:
        thresholds = [80, 95]
    with patch('usage_monitor_for_claude.app.pystray'), \
         patch('usage_monitor_for_claude.app.create_icon_image'), \
         patch('usage_monitor_for_claude.app.taskbar_uses_light_theme', return_value=False):
        app = UsageMonitorForClaude()
    app.icon = MagicMock()
    app._thresholds_patch = patch('usage_monitor_for_claude.app.get_alert_thresholds', return_value=thresholds)
    app._thresholds_patch.start()
    return app


def _cleanup(app: UsageMonitorForClaude) -> None:
    """Stop patches started by _make_app."""
    app._thresholds_patch.stop()


class TestCheckThresholdAlerts(unittest.TestCase):
    """Tests for _check_threshold_alerts() notification logic."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_notification_on_first_crossing(self):
        """Notification fires when usage crosses a threshold for the first time."""
        self.app.usage_data = {'five_hour': {'utilization': 82}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()
        args = self.app.icon.notify.call_args
        self.assertIn('82%', args[0][0])

    def test_no_duplicate_notification(self):
        """No notification if threshold was already notified."""
        self.app.usage_data = {'five_hour': {'utilization': 82}}
        self.app._check_threshold_alerts()
        self.app.icon.notify.reset_mock()

        self.app.usage_data = {'five_hour': {'utilization': 85}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_higher_threshold_triggers_new_notification(self):
        """Crossing a higher threshold triggers a new notification."""
        self.app.usage_data = {'five_hour': {'utilization': 82}}
        self.app._check_threshold_alerts()
        self.app.icon.notify.reset_mock()

        self.app.usage_data = {'five_hour': {'utilization': 97}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()
        args = self.app.icon.notify.call_args
        self.assertIn('97%', args[0][0])

    def test_jump_past_multiple_thresholds_single_notification(self):
        """Jumping from below all thresholds to above multiple shows only one notification."""
        self.app.usage_data = {'five_hour': {'utilization': 97}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()
        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 95)

    def test_notification_shows_current_pct_not_threshold(self):
        """Notification message contains the actual usage %, not the threshold value."""
        self.app.usage_data = {'five_hour': {'utilization': 83.7}}
        self.app._check_threshold_alerts()

        args = self.app.icon.notify.call_args
        self.assertIn('84%', args[0][0])

    def test_re_notification_after_usage_drops(self):
        """After usage drops below a threshold, it can re-trigger."""
        self.app.usage_data = {'five_hour': {'utilization': 82}}
        self.app._check_threshold_alerts()
        self.app.icon.notify.reset_mock()

        # Usage drops below 80 (e.g. after reset)
        self.app.usage_data = {'five_hour': {'utilization': 30}}
        self.app._check_threshold_alerts()
        self.app.icon.notify.assert_not_called()

        # Usage rises above 80 again
        self.app.usage_data = {'five_hour': {'utilization': 81}}
        self.app._check_threshold_alerts()
        self.app.icon.notify.assert_called_once()

    def test_no_notification_when_thresholds_empty(self):
        """No notification when thresholds list is empty."""
        _cleanup(self.app)
        self.app = _make_app(thresholds=[])

        self.app.usage_data = {'five_hour': {'utilization': 99}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_on_startup_above_threshold(self):
        """On startup (no prior state), notification fires if already above threshold."""
        self.app.usage_data = {'five_hour': {'utilization': 90}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()

    def test_each_variant_tracked_independently(self):
        """Different variants are tracked independently."""
        self.app.usage_data = {
            'five_hour': {'utilization': 82},
            'seven_day': {'utilization': 50},
        }
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()
        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 80)
        self.assertEqual(self.app._notified_thresholds.get('seven_day', 0), 0)

    def test_multiple_variants_crossing_simultaneously(self):
        """Multiple variants crossing thresholds each get their own notification."""
        self.app.usage_data = {
            'five_hour': {'utilization': 82},
            'seven_day': {'utilization': 96},
        }
        self.app._check_threshold_alerts()

        self.assertEqual(self.app.icon.notify.call_count, 2)

    def test_variant_with_no_utilization_skipped(self):
        """Variants with None utilization are skipped."""
        self.app.usage_data = {'five_hour': {'utilization': None}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_missing_variant_skipped(self):
        """Missing variants in usage_data are skipped."""
        self.app.usage_data = {}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_usage_exactly_at_threshold(self):
        """Usage exactly at threshold value triggers notification."""
        self.app.usage_data = {'five_hour': {'utilization': 80}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()

    def test_usage_just_below_threshold(self):
        """Usage just below threshold does not trigger notification."""
        self.app.usage_data = {'five_hour': {'utilization': 79.9}}
        self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()


class TestTimeAwareAlerts(unittest.TestCase):
    """Tests for time-aware threshold alert suppression."""

    def setUp(self):
        self.app = _make_app()
        self._time_aware_patch = patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE', True)
        self._below_patch = patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 100)
        self._time_aware_patch.start()
        self._below_patch.start()

    def tearDown(self):
        self._below_patch.stop()
        self._time_aware_patch.stop()
        _cleanup(self.app)

    def test_alert_suppressed_when_usage_behind_time(self):
        """No notification when usage (82%) <= elapsed time (90%)."""
        self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_alert_shown_when_usage_ahead_of_time(self):
        """Notification fires when usage (82%) > elapsed time (50%)."""
        self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=50.0):
            self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()

    def test_fallback_when_elapsed_pct_none(self):
        """Notification fires normally when elapsed_pct returns None (no resets_at)."""
        self.app.usage_data = {'five_hour': {'utilization': 82}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=None):
            self.app._check_threshold_alerts()

        self.app.icon.notify.assert_called_once()

    def test_tracking_updated_when_suppressed(self):
        """Notified threshold tracking is updated even when alert is suppressed."""
        self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts()

        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 80)

    def test_no_re_notification_after_suppression(self):
        """After suppression, the same threshold does not re-trigger."""
        self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts()

        # Now time catches up less — usage is ahead, but threshold already tracked
        self.app.usage_data = {'five_hour': {'utilization': 84, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=50.0):
            self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_disabled_when_false(self):
        """With ALERT_TIME_AWARE=False, alerts fire regardless of time."""
        self._time_aware_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE', False):
            self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts()
        self._time_aware_patch.start()

        self.app.icon.notify.assert_called_once()

    def test_usage_equal_to_time_suppressed(self):
        """Notification suppressed when usage exactly equals elapsed time."""
        self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=82.0):
            self.app._check_threshold_alerts()

        self.app.icon.notify.assert_not_called()

    def test_threshold_at_or_above_below_cutoff_always_fires(self):
        """Threshold >= alert_time_aware_below fires even when usage <= time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 90):
            # Thresholds are [80, 95]. Usage crosses 95 which is >= 90 cutoff.
            self.app.usage_data = {'five_hour': {'utilization': 97, 'resets_at': '2025-01-15T14:30:00+00:00'}}
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=98.0):
                self.app._check_threshold_alerts()
        self._below_patch.start()

        self.app.icon.notify.assert_called_once()

    def test_threshold_below_cutoff_suppressed(self):
        """Threshold < alert_time_aware_below is suppressed when usage <= time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 90):
            # Thresholds are [80, 95]. Usage crosses 80 which is < 90 cutoff.
            self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts()
        self._below_patch.start()

        self.app.icon.notify.assert_not_called()

    def test_below_cutoff_exact_boundary_fires(self):
        """Threshold exactly at alert_time_aware_below fires regardless of time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 80):
            self.app.usage_data = {'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}}
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts()
        self._below_patch.start()

        self.app.icon.notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()

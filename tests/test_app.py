"""
Application Tests
===================

Unit tests for the application module: threshold alerts, update orchestration,
tray rendering, polling interval, and reset notifications.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude.app import UsageMonitorForClaude
from usage_monitor_for_claude.cache import UpdateResult
from usage_monitor_for_claude.claude_cli import RefreshResult


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


# ---------------------------------------------------------------------------
# _check_threshold_alerts
# ---------------------------------------------------------------------------

class TestCheckThresholdAlerts(unittest.TestCase):
    """Tests for _check_threshold_alerts() notification logic."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_notification_on_first_crossing(self):
        """Notification fires when usage crosses a threshold for the first time."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 82}})

        self.app.icon.notify.assert_called_once()
        args = self.app.icon.notify.call_args
        self.assertIn('82%', args[0][0])

    def test_no_duplicate_notification(self):
        """No notification if threshold was already notified."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 82}})
        self.app.icon.notify.reset_mock()

        self.app._check_threshold_alerts({'five_hour': {'utilization': 85}})

        self.app.icon.notify.assert_not_called()

    def test_higher_threshold_triggers_new_notification(self):
        """Crossing a higher threshold triggers a new notification."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 82}})
        self.app.icon.notify.reset_mock()

        self.app._check_threshold_alerts({'five_hour': {'utilization': 97}})

        self.app.icon.notify.assert_called_once()
        args = self.app.icon.notify.call_args
        self.assertIn('97%', args[0][0])

    def test_jump_past_multiple_thresholds_single_notification(self):
        """Jumping from below all thresholds to above multiple shows only one notification."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 97}})

        self.app.icon.notify.assert_called_once()
        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 95)

    def test_notification_shows_current_pct_not_threshold(self):
        """Notification message contains the actual usage %, not the threshold value."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 83.7}})

        args = self.app.icon.notify.call_args
        self.assertIn('84%', args[0][0])

    def test_re_notification_after_usage_drops(self):
        """After usage drops below a threshold, it can re-trigger."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 82}})
        self.app.icon.notify.reset_mock()

        # Usage drops below 80 (e.g. after reset)
        self.app._check_threshold_alerts({'five_hour': {'utilization': 30}})
        self.app.icon.notify.assert_not_called()

        # Usage rises above 80 again
        self.app._check_threshold_alerts({'five_hour': {'utilization': 81}})
        self.app.icon.notify.assert_called_once()

    def test_no_notification_when_thresholds_empty(self):
        """No notification when thresholds list is empty."""
        _cleanup(self.app)
        self.app = _make_app(thresholds=[])

        self.app._check_threshold_alerts({'five_hour': {'utilization': 99}})

        self.app.icon.notify.assert_not_called()

    def test_on_startup_above_threshold(self):
        """On startup (no prior state), notification fires if already above threshold."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 90}})

        self.app.icon.notify.assert_called_once()

    def test_each_variant_tracked_independently(self):
        """Different variants are tracked independently."""
        self.app._check_threshold_alerts({
            'five_hour': {'utilization': 82},
            'seven_day': {'utilization': 50},
        })

        self.app.icon.notify.assert_called_once()
        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 80)
        self.assertEqual(self.app._notified_thresholds.get('seven_day', 0), 0)

    def test_multiple_variants_crossing_simultaneously(self):
        """Multiple variants crossing thresholds each get their own notification."""
        self.app._check_threshold_alerts({
            'five_hour': {'utilization': 82},
            'seven_day': {'utilization': 96},
        })

        self.assertEqual(self.app.icon.notify.call_count, 2)

    def test_variant_with_no_utilization_skipped(self):
        """Variants with None utilization are skipped."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': None}})

        self.app.icon.notify.assert_not_called()

    def test_missing_variant_skipped(self):
        """Missing variants in data are skipped."""
        self.app._check_threshold_alerts({})

        self.app.icon.notify.assert_not_called()

    def test_usage_exactly_at_threshold(self):
        """Usage exactly at threshold value triggers notification."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 80}})

        self.app.icon.notify.assert_called_once()

    def test_usage_just_below_threshold(self):
        """Usage just below threshold does not trigger notification."""
        self.app._check_threshold_alerts({'five_hour': {'utilization': 79.9}})

        self.app.icon.notify.assert_not_called()


# ---------------------------------------------------------------------------
# Time-aware alerts
# ---------------------------------------------------------------------------

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
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        self.app.icon.notify.assert_not_called()

    def test_alert_shown_when_usage_ahead_of_time(self):
        """Notification fires when usage (82%) > elapsed time (50%)."""
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=50.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        self.app.icon.notify.assert_called_once()

    def test_fallback_when_elapsed_pct_none(self):
        """Notification fires normally when elapsed_pct returns None (no resets_at)."""
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=None):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82}})

        self.app.icon.notify.assert_called_once()

    def test_tracking_updated_when_suppressed(self):
        """Notified threshold tracking is updated even when alert is suppressed."""
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        self.assertEqual(self.app._notified_thresholds.get('five_hour'), 80)

    def test_no_re_notification_after_suppression(self):
        """After suppression, the same threshold does not re-trigger."""
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        # Now time catches up less - usage is ahead, but threshold already tracked
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=50.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 84, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        self.app.icon.notify.assert_not_called()

    def test_disabled_when_false(self):
        """With ALERT_TIME_AWARE=False, alerts fire regardless of time."""
        self._time_aware_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE', False):
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})
        self._time_aware_patch.start()

        self.app.icon.notify.assert_called_once()

    def test_usage_equal_to_time_suppressed(self):
        """Notification suppressed when usage exactly equals elapsed time."""
        with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=82.0):
            self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})

        self.app.icon.notify.assert_not_called()

    def test_threshold_at_or_above_below_cutoff_always_fires(self):
        """Threshold >= alert_time_aware_below fires even when usage <= time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 90):
            # Thresholds are [80, 95]. Usage crosses 95 which is >= 90 cutoff.
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=98.0):
                self.app._check_threshold_alerts({'five_hour': {'utilization': 97, 'resets_at': '2025-01-15T14:30:00+00:00'}})
        self._below_patch.start()

        self.app.icon.notify.assert_called_once()

    def test_threshold_below_cutoff_suppressed(self):
        """Threshold < alert_time_aware_below is suppressed when usage <= time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 90):
            # Thresholds are [80, 95]. Usage crosses 80 which is < 90 cutoff.
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})
        self._below_patch.start()

        self.app.icon.notify.assert_not_called()

    def test_below_cutoff_exact_boundary_fires(self):
        """Threshold exactly at alert_time_aware_below fires regardless of time."""
        self._below_patch.stop()
        with patch('usage_monitor_for_claude.app.ALERT_TIME_AWARE_BELOW', 80):
            with patch('usage_monitor_for_claude.app.elapsed_pct', return_value=90.0):
                self.app._check_threshold_alerts({'five_hour': {'utilization': 82, 'resets_at': '2025-01-15T14:30:00+00:00'}})
        self._below_patch.start()

        self.app.icon.notify.assert_called_once()


# ---------------------------------------------------------------------------
# update() orchestration
# ---------------------------------------------------------------------------

class TestUpdateOrchestration(unittest.TestCase):
    """Tests for update() delegating to cache and processing results."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_skipped_update_does_nothing(self):
        """When cache.update() returns None data, update() returns early."""
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=None)

        self.app.update()

        self.assertEqual(self.app._last_response, {})

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_success_updates_last_response(self, _icon, _tooltip):
        """Successful update stores response in _last_response."""
        data = {'five_hour': {'utilization': 42.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._last_response, data)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_status_image')
    def test_error_updates_last_response(self, _status, _tooltip):
        """Error update stores error response in _last_response."""
        data = {'error': 'server down'}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._last_response, data)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_token_refresh_notification(self, _icon, _tooltip):
        """Shows notification when token refresh updated CLI version."""
        data = {'five_hour': {'utilization': 10.0}}
        refresh = RefreshResult(success=True, updated=True, old_version='2.1.38', new_version='2.1.69', error='')
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data, token_refresh=refresh)

        self.app.update()

        self.app.icon.notify.assert_called_once()
        args = self.app.icon.notify.call_args[0]
        self.assertIn('2.1.38', args[0])
        self.assertIn('2.1.69', args[0])

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_no_notification_when_no_cli_update(self, _icon, _tooltip):
        """No notification when token refreshed but no CLI update."""
        data = {'five_hour': {'utilization': 10.0}}
        refresh = RefreshResult(success=True, updated=False, old_version='2.1.69', new_version='2.1.69', error='')
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data, token_refresh=refresh)

        self.app.update()

        self.app.icon.notify.assert_not_called()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_status_image')
    def test_error_returns_before_threshold_checks(self, _status, _tooltip):
        """Error response returns early without threshold checks."""
        data = {'error': 'fail'}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        with patch.object(self.app, '_check_threshold_alerts') as mock_check:
            self.app.update()
            mock_check.assert_not_called()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_update_tracks_previous_values(self, _icon, _tooltip):
        """update() stores current pct values for next comparison."""
        data = {'five_hour': {'utilization': 42.0}, 'seven_day': {'utilization': 15.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._prev_5h, 42.0)
        self.assertEqual(self.app._prev_7d, 15.0)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_status_image')
    def test_error_does_not_update_previous_values(self, _status, _tooltip):
        """Error response does not change tracked previous values."""
        self.app._prev_5h = 50.0
        self.app._prev_7d = 20.0
        data = {'error': 'fail'}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._prev_5h, 50.0)
        self.assertEqual(self.app._prev_7d, 20.0)


# ---------------------------------------------------------------------------
# Reset notifications
# ---------------------------------------------------------------------------

class TestResetNotifications(unittest.TestCase):
    """Tests for quota reset notifications in update()."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_5h_reset_notification(self, _icon, _tooltip):
        """Notification fires when 5h usage drops from >95% with 7d not blocking."""
        self.app._prev_5h = 97.0
        self.app._prev_7d = 50.0
        data = {'five_hour': {'utilization': 10.0}, 'seven_day': {'utilization': 50.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.app.icon.notify.assert_called_once()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_5h_reset_suppressed_when_7d_blocking(self, _icon, _tooltip):
        """No 5h reset notification when 7d is at 99%+."""
        self.app._prev_5h = 97.0
        self.app._prev_7d = 50.0
        data = {'five_hour': {'utilization': 10.0}, 'seven_day': {'utilization': 99.5}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        with patch.object(self.app, '_check_threshold_alerts'):
            self.app.update()

        self.app.icon.notify.assert_not_called()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_7d_reset_notification(self, _icon, _tooltip):
        """Notification fires when 7d usage drops from >98% with 5h not blocking."""
        self.app._prev_5h = 50.0
        self.app._prev_7d = 99.0
        data = {'five_hour': {'utilization': 50.0}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.app.icon.notify.assert_called_once()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_no_reset_notification_on_first_update(self, _icon, _tooltip):
        """No reset notification on first update (no previous values)."""
        data = {'five_hour': {'utilization': 10.0}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.app.icon.notify.assert_not_called()

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_7d_reset_suppressed_when_5h_blocking(self, _icon, _tooltip):
        """No 7d reset notification when 5h is at 99%+."""
        self.app._prev_5h = 50.0
        self.app._prev_7d = 99.0
        data = {'five_hour': {'utilization': 99.5}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        with patch.object(self.app, '_check_threshold_alerts'):
            self.app.update()

        self.app.icon.notify.assert_not_called()


# ---------------------------------------------------------------------------
# Fast polling (adaptive)
# ---------------------------------------------------------------------------

class TestFastPolling(unittest.TestCase):
    """Tests for adaptive fast polling when session usage is increasing."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_fast_polling_starts_on_usage_increase(self, _icon, _tooltip):
        """Fast polls start when 5h usage is increasing."""
        self.app._prev_5h = 40.0
        self.app._prev_7d = 10.0
        data = {'five_hour': {'utilization': 45.0}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertGreater(self.app._fast_polls_remaining, 0)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_fast_polling_decrements(self, _icon, _tooltip):
        """Fast poll counter decrements when usage is stable."""
        self.app._prev_5h = 40.0
        self.app._prev_7d = 10.0
        self.app._fast_polls_remaining = 2
        data = {'five_hour': {'utilization': 40.0}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._fast_polls_remaining, 1)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_fast_polling_not_below_zero(self, _icon, _tooltip):
        """Fast poll counter does not go below zero."""
        self.app._prev_5h = 40.0
        self.app._prev_7d = 10.0
        self.app._fast_polls_remaining = 0
        data = {'five_hour': {'utilization': 40.0}, 'seven_day': {'utilization': 10.0}}
        self.app.cache = MagicMock()
        self.app.cache.update.return_value = UpdateResult(data=data)

        self.app.update()

        self.assertEqual(self.app._fast_polls_remaining, 0)


# ---------------------------------------------------------------------------
# _render_tray
# ---------------------------------------------------------------------------

class TestRenderTray(unittest.TestCase):
    """Tests for _render_tray() icon and tooltip rendering."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='Usage: 42%')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_success_renders_icon(self, mock_icon, _tooltip):
        """Successful data renders usage icon."""
        self.app._last_response = {'five_hour': {'utilization': 42.0}, 'seven_day': {'utilization': 10.0}}
        self.app._render_tray()

        mock_icon.assert_called_once_with(42.0, 10.0, False)
        self.assertEqual(self.app.icon.title, 'Usage: 42%')

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='Error')
    @patch('usage_monitor_for_claude.app.create_status_image')
    def test_error_renders_exclamation(self, mock_status, _tooltip):
        """Error data renders '!' status icon."""
        self.app._last_response = {'error': 'server down'}
        self.app._render_tray()

        mock_status.assert_called_once_with('!', False)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='Auth Error')
    @patch('usage_monitor_for_claude.app.create_status_image')
    def test_auth_error_renders_c_exclamation(self, mock_status, _tooltip):
        """Auth error data renders 'C!' status icon."""
        self.app._last_response = {'error': 'expired', 'auth_error': True}
        self.app._render_tray()

        mock_status.assert_called_once_with('C!', False)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    def test_missing_utilization_defaults_to_zero(self, mock_icon, _tooltip):
        """Missing utilization values default to 0."""
        self.app._last_response = {'five_hour': {}, 'seven_day': {'utilization': None}}
        self.app._render_tray()

        mock_icon.assert_called_once_with(0, 0, False)


# ---------------------------------------------------------------------------
# _on_theme_changed
# ---------------------------------------------------------------------------

class TestOnThemeChanged(unittest.TestCase):
    """Tests for _on_theme_changed() theme switch handling."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.format_tooltip', return_value='tooltip')
    @patch('usage_monitor_for_claude.app.create_icon_image')
    @patch('usage_monitor_for_claude.app.taskbar_uses_light_theme', return_value=True)
    def test_theme_change_re_renders(self, _theme, mock_icon, _tooltip):
        """Theme change re-renders the tray icon."""
        self.app._light_taskbar = False
        self.app._last_response = {'five_hour': {'utilization': 50.0}, 'seven_day': {'utilization': 20.0}}

        self.app._on_theme_changed()

        self.assertTrue(self.app._light_taskbar)
        mock_icon.assert_called_once_with(50.0, 20.0, True)

    @patch('usage_monitor_for_claude.app.taskbar_uses_light_theme', return_value=False)
    def test_same_theme_no_render(self, _theme):
        """No re-render when theme hasn't changed."""
        self.app._light_taskbar = False
        self.app._last_response = {'five_hour': {'utilization': 50.0}}

        with patch.object(self.app, '_render_tray') as mock_render:
            self.app._on_theme_changed()
            mock_render.assert_not_called()

    @patch('usage_monitor_for_claude.app.taskbar_uses_light_theme', return_value=True)
    def test_theme_change_without_data_no_render(self, _theme):
        """Theme change without any data does not render."""
        self.app._light_taskbar = False
        self.app._last_response = {}

        with patch.object(self.app, '_render_tray') as mock_render:
            self.app._on_theme_changed()
            mock_render.assert_not_called()


# ---------------------------------------------------------------------------
# _calculate_poll_interval
# ---------------------------------------------------------------------------

class TestCalculatePollInterval(unittest.TestCase):
    """Tests for _calculate_poll_interval() adaptive interval logic."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_normal_interval(self):
        """Normal state returns POLL_INTERVAL."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 180)

    def test_fast_polling_interval(self):
        """When fast polling is active, returns POLL_FAST."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        self.app._fast_polls_remaining = 3
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 120)

    def test_error_interval(self):
        """Transient error returns POLL_ERROR."""
        self.app._last_response = {'error': 'server down'}
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 30)

    def test_rate_limited_with_high_remaining(self):
        """Rate-limited uses cache.rate_limit_remaining for the interval."""
        self.app._last_response = {'error': 'rate limited', 'rate_limited': True}
        self.app.cache = MagicMock()
        self.app.cache.rate_limit_remaining = 300.0
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 300)

    def test_rate_limited_with_low_remaining(self):
        """Rate-limited with low remaining uses POLL_INTERVAL as minimum."""
        self.app._last_response = {'error': 'rate limited', 'rate_limited': True}
        self.app.cache = MagicMock()
        self.app.cache.rate_limit_remaining = 10.0
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 180)

    def test_rate_limited_with_large_remaining(self):
        """Rate-limited with large remaining uses that value."""
        self.app._last_response = {'error': 'rate limited', 'rate_limited': True}
        self.app.cache = MagicMock()
        self.app.cache.rate_limit_remaining = 480.0
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 480)

    def test_rate_limited_remaining_capped_by_cache(self):
        """Rate-limited remaining reflects cache's capped backoff (MAX_BACKOFF=900)."""
        self.app._last_response = {'error': 'rate limited', 'rate_limited': True}
        self.app.cache = MagicMock()
        self.app.cache.rate_limit_remaining = 900.0
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 900)

    def test_rate_limited_expired(self):
        """Rate-limited with expired backoff uses POLL_INTERVAL."""
        self.app._last_response = {'error': 'rate limited', 'rate_limited': True}
        self.app.cache = MagicMock()
        self.app.cache.rate_limit_remaining = 0.0
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 180)

    def test_empty_response_returns_normal_interval(self):
        """Empty _last_response (initial state) returns POLL_INTERVAL."""
        self.app._last_response = {}
        interval = self.app._calculate_poll_interval()
        self.assertEqual(interval, 180)


# ---------------------------------------------------------------------------
# _seconds_until_next_reset
# ---------------------------------------------------------------------------

class TestSecondsUntilNextReset(unittest.TestCase):
    """Tests for _seconds_until_next_reset() calculation."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_no_data_returns_none(self):
        """No response data returns None."""
        self.app._last_response = {}
        self.assertIsNone(self.app._seconds_until_next_reset())

    def test_no_resets_at_returns_none(self):
        """Entry without resets_at returns None."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        self.assertIsNone(self.app._seconds_until_next_reset())

    @patch('usage_monitor_for_claude.app.datetime')
    def test_returns_seconds_to_nearest_reset(self, mock_dt):
        """Returns seconds to the nearest future reset."""
        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        self.app._last_response = {
            'five_hour': {'utilization': 50.0, 'resets_at': '2025-01-15T12:30:00+00:00'},
            'seven_day': {'utilization': 30.0, 'resets_at': '2025-01-15T14:00:00+00:00'},
        }

        result = self.app._seconds_until_next_reset()
        assert result is not None
        self.assertAlmostEqual(result, 1800.0, places=0)  # 30 minutes

    @patch('usage_monitor_for_claude.app.datetime')
    def test_past_reset_ignored(self, mock_dt):
        """Past reset times are ignored."""
        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        self.app._last_response = {
            'five_hour': {'utilization': 50.0, 'resets_at': '2025-01-15T11:00:00+00:00'},
        }

        self.assertIsNone(self.app._seconds_until_next_reset())


# ---------------------------------------------------------------------------
# Poll interval reset alignment
# ---------------------------------------------------------------------------

class TestResetAlignment(unittest.TestCase):
    """Tests for poll interval alignment with imminent reset."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_imminent_reset_aligns_poll(self):
        """When reset is imminent, interval aligns to reset time."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        with patch.object(self.app, '_seconds_until_next_reset', return_value=160.0):
            interval = self.app._calculate_poll_interval()

        # next_reset(160) + 5 = 165 <= interval(180) * 1.5 = 270, so aligned
        # max(165, POLL_FAST=120) = 165
        self.assertEqual(interval, 165)

    def test_distant_reset_no_alignment(self):
        """When reset is far away, normal interval is used."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        with patch.object(self.app, '_seconds_until_next_reset', return_value=500.0):
            interval = self.app._calculate_poll_interval()

        # next_reset(500) + 5 = 505 > interval(180) * 1.5 = 270, no alignment
        self.assertEqual(interval, 180)

    def test_reset_alignment_sets_fast_polls(self):
        """Reset alignment sets fast_polls_remaining for post-reset follow-up."""
        self.app._last_response = {'five_hour': {'utilization': 50.0}}
        self.app._fast_polls_remaining = 0
        with patch.object(self.app, '_seconds_until_next_reset', return_value=100.0):
            self.app._calculate_poll_interval()

        self.assertGreaterEqual(self.app._fast_polls_remaining, 2)


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

class TestMenuActions(unittest.TestCase):
    """Tests for menu action methods."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    def test_on_refresh_clears_failed_token(self):
        """on_refresh() clears the failed token guard before starting update."""
        self.app.cache = MagicMock()
        with patch('usage_monitor_for_claude.app.threading'):
            self.app.on_refresh()
        self.app.cache.clear_failed_token.assert_called_once()

    def test_on_refresh_starts_force_update_thread(self):
        """on_refresh() starts a thread with force=True."""
        self.app.cache = MagicMock()
        with patch('usage_monitor_for_claude.app.threading.Thread') as mock_thread:
            self.app.on_refresh()
            mock_thread.assert_called_once()
            call_kwargs = mock_thread.call_args[1]
            self.assertEqual(call_kwargs['kwargs'], {'force': True})

    def test_on_show_popup_guards_against_double_open(self):
        """on_show_popup() does nothing when popup is already open."""
        self.app._popup_open = True
        with patch('usage_monitor_for_claude.app.threading.Thread') as mock_thread:
            self.app.on_show_popup()
            mock_thread.assert_not_called()

    def test_on_quit_stops_running(self):
        """on_quit() sets running to False and stops the icon."""
        self.app.on_quit()
        self.assertFalse(self.app.running)
        self.app.icon.stop.assert_called_once()


# ---------------------------------------------------------------------------
# _is_user_away (idle/lock detection)
# ---------------------------------------------------------------------------

class TestIsUserAway(unittest.TestCase):
    """Tests for _is_user_away() idle and lock detection."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=True)
    def test_locked_is_away(self, _locked):
        """User is away when workstation is locked."""
        self.assertTrue(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=False)
    @patch('usage_monitor_for_claude.app.get_idle_seconds', return_value=400.0)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 300)
    def test_idle_over_threshold_is_away(self, _idle, _locked):
        """User is away when idle time exceeds IDLE_PAUSE."""
        self.assertTrue(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=False)
    @patch('usage_monitor_for_claude.app.get_idle_seconds', return_value=200.0)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 300)
    def test_idle_under_threshold_not_away(self, _idle, _locked):
        """User is not away when idle time is below IDLE_PAUSE."""
        self.assertFalse(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=False)
    @patch('usage_monitor_for_claude.app.get_idle_seconds', return_value=300.0)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 300)
    def test_idle_exactly_at_threshold_is_away(self, _idle, _locked):
        """User is away when idle time equals IDLE_PAUSE exactly."""
        self.assertTrue(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=False)
    @patch('usage_monitor_for_claude.app.get_idle_seconds', return_value=9999.0)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 0)
    def test_idle_disabled_with_zero(self, _idle, _locked):
        """Idle detection disabled when IDLE_PAUSE is 0."""
        self.assertFalse(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=True)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 0)
    def test_locked_detected_even_when_idle_disabled(self, _locked):
        """Lock detection works even when idle detection is disabled."""
        self.assertTrue(self.app._is_user_away())

    @patch('usage_monitor_for_claude.app.is_workstation_locked', return_value=False)
    @patch('usage_monitor_for_claude.app.get_idle_seconds', return_value=0.0)
    @patch('usage_monitor_for_claude.app.IDLE_PAUSE', 300)
    def test_active_user_not_away(self, _idle, _locked):
        """User is not away when active (0 idle seconds)."""
        self.assertFalse(self.app._is_user_away())


# ---------------------------------------------------------------------------
# _wait_for_activity
# ---------------------------------------------------------------------------

class TestWaitForActivity(unittest.TestCase):
    """Tests for _wait_for_activity() blocking behavior."""

    def setUp(self):
        self.app = _make_app()

    def tearDown(self):
        _cleanup(self.app)

    @patch('usage_monitor_for_claude.app.time.sleep')
    def test_exits_when_activity_resumes(self, mock_sleep):
        """Stops blocking when _is_user_away returns False."""
        with patch.object(self.app, '_is_user_away', side_effect=[True, True, False]):
            self.app._wait_for_activity()
        self.assertEqual(mock_sleep.call_count, 2)

    @patch('usage_monitor_for_claude.app.time.sleep')
    def test_exits_when_running_false(self, mock_sleep):
        """Stops blocking when running is set to False."""
        self.app.running = False
        with patch.object(self.app, '_is_user_away', return_value=True):
            self.app._wait_for_activity()
        mock_sleep.assert_not_called()

    @patch('usage_monitor_for_claude.app.time.sleep')
    def test_returns_immediately_if_not_away(self, mock_sleep):
        """Returns immediately when user is not away."""
        with patch.object(self.app, '_is_user_away', return_value=False):
            self.app._wait_for_activity()
        mock_sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()

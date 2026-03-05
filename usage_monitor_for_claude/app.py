"""
Application
=============

System tray application class with adaptive polling and event handling.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import pystray  # type: ignore[import-untyped]  # no type stubs available

from .api import api_headers, fetch_profile, fetch_usage, read_access_token
from .autostart import is_autostart_enabled, set_autostart, sync_autostart_path
from .claude_cli import refresh_token
from .settings import ALERT_TIME_AWARE, ALERT_TIME_AWARE_BELOW, POLL_ERROR, POLL_FAST, POLL_FAST_EXTRA, POLL_INTERVAL, get_alert_thresholds
from .formatting import PERIOD_5H, PERIOD_7D, elapsed_pct, format_tooltip
from .i18n import T
from .popup import UsagePopup
from .tray_icon import create_icon_image, create_status_image, taskbar_uses_light_theme, watch_theme_change


_VARIANT_NOTIFY_KEYS = {
    'five_hour': 'notify_threshold_five_hour',
    'seven_day': 'notify_threshold_seven_day',
    'seven_day_sonnet': 'notify_threshold_seven_day_sonnet',
    'seven_day_opus': 'notify_threshold_seven_day_opus',
}
_VARIANT_PERIODS = {
    'five_hour': PERIOD_5H,
    'seven_day': PERIOD_7D,
    'seven_day_sonnet': PERIOD_7D,
    'seven_day_opus': PERIOD_7D,
}


class UsageMonitorForClaude:
    """System tray application displaying Claude usage."""

    def __init__(self) -> None:
        """Set up the tray icon with context menu and polling state."""
        self.running = True
        self.usage_data: dict[str, Any] = {}
        self.profile_data: dict[str, Any] | None = None
        self._cached_usage: dict[str, Any] = {}
        self._last_success_time: float | None = None
        self._refreshing = False
        self._last_error: str | None = None
        self._last_failed_token: str | None = None
        self._prev_5h = None
        self._prev_7d = None
        self._fast_polls_remaining = 0
        self._consecutive_errors = 0
        self._popup_open = False
        self._data_version = 0
        self._notified_thresholds: dict[str, float] = {}
        self._light_taskbar = taskbar_uses_light_theme()
        self.icon = pystray.Icon(
            'usage_monitor',
            icon=create_icon_image(0, 0, self._light_taskbar),
            title=T['loading'],
            menu=pystray.Menu(
                pystray.MenuItem(T['title'].replace('&', '&&'), self.on_show_popup, default=True),
                pystray.MenuItem(T['refresh'], self.on_refresh),
                pystray.MenuItem(
                    T['autostart'], self.on_toggle_autostart,
                    checked=lambda item: is_autostart_enabled(),
                    visible=getattr(sys, 'frozen', False),
                ),
                pystray.MenuItem(T['quit'], self.on_quit),
            ),
        )

    def on_show_popup(self, icon: Any = None, item: Any = None) -> None:
        if self._popup_open:
            return
        threading.Thread(target=self._open_popup, daemon=True).start()

    def on_refresh(self, icon: Any = None, item: Any = None) -> None:
        self._last_failed_token = None
        threading.Thread(target=self.update, daemon=True).start()

    def on_toggle_autostart(self, icon: Any = None, item: Any = None) -> None:
        set_autostart(not is_autostart_enabled())

    def on_quit(self, icon: Any = None, item: Any = None) -> None:
        self.running = False
        self.icon.stop()

    def _open_popup(self) -> None:
        self._popup_open = True
        try:
            stale = self._last_success_time is None or time.time() - self._last_success_time > POLL_FAST
            if stale or not self.profile_data:
                def _bg_refresh() -> None:
                    if not self.profile_data:
                        self.profile_data = fetch_profile()
                    if stale:
                        self.update()
                threading.Thread(target=_bg_refresh, daemon=True).start()
            UsagePopup(self)
        finally:
            self._popup_open = False

    def _on_theme_changed(self) -> None:
        """Re-render the tray icon when the Windows theme changes."""
        light = taskbar_uses_light_theme()
        if light == self._light_taskbar:
            return

        self._light_taskbar = light
        if 'error' in self.usage_data:
            self.icon.icon = create_status_image('C!' if self.usage_data.get('auth_error') else '!', light)
        else:
            pct_5h = self.usage_data.get('five_hour', {}).get('utilization', 0) or 0
            pct_7d = self.usage_data.get('seven_day', {}).get('utilization', 0) or 0
            self.icon.icon = create_icon_image(pct_5h, pct_7d, light)

    def update(self) -> None:
        """Fetch current usage and update the tray icon and tooltip.

        Tracks session usage changes to enable adaptive fast-polling
        when usage is actively increasing. After a 401 auth error,
        subsequent polls only re-read the credentials file and skip
        the API call until the token actually changes.

        Successful responses are cached in ``_cached_usage`` so the
        popup can display stale-but-valid data during transient errors.
        """
        if self._last_failed_token is not None:
            if read_access_token() == self._last_failed_token:
                return

            self._last_failed_token = None

        self._refreshing = True
        self._data_version += 1

        self.usage_data = fetch_usage()

        if 'error' in self.usage_data:
            self._consecutive_errors += 1
            self._last_error = self.usage_data['error']
            server_msg = self.usage_data.get('server_message')
            if server_msg:
                self._last_error += f'\n{server_msg}'

            if self.usage_data.get('auth_error'):
                if self._try_token_refresh():
                    return
                self._last_failed_token = read_access_token()

            self.icon.icon = create_status_image('C!' if self.usage_data.get('auth_error') else '!', self._light_taskbar)
            self.icon.title = format_tooltip(self.usage_data)
            self._refreshing = False
            self._data_version += 1
            return

        pct_5h, pct_7d = self._apply_success()

        # Notify when quota resets after being nearly exhausted, but only if the other quota isn't blocking usage
        if self._prev_5h is not None and self._prev_5h > 95 and pct_5h < self._prev_5h and pct_7d < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])
        if self._prev_7d is not None and self._prev_7d > 98 and pct_7d < self._prev_7d and pct_5h < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])

        self._check_threshold_alerts()

        # Adaptive polling: speed up when session usage is increasing
        if self._prev_5h is not None and pct_5h > self._prev_5h:
            self._fast_polls_remaining = POLL_FAST_EXTRA + 1
        elif self._fast_polls_remaining > 0:
            self._fast_polls_remaining -= 1
        self._prev_5h = pct_5h
        self._prev_7d = pct_7d

    def _apply_success(self) -> tuple[float, float]:
        """Apply common state updates after a successful API response.

        Resets error tracking, caches the response, and updates the
        tray icon and tooltip.

        Returns
        -------
        tuple[float, float]
            The 5-hour and 7-day utilization percentages.
        """
        self._consecutive_errors = 0
        self._last_error = None
        self._last_success_time = time.time()
        self._cached_usage = self.usage_data

        pct_5h = self.usage_data.get('five_hour', {}).get('utilization', 0) or 0
        pct_7d = self.usage_data.get('seven_day', {}).get('utilization', 0) or 0

        self.icon.icon = create_icon_image(pct_5h, pct_7d, self._light_taskbar)
        self.icon.title = format_tooltip(self.usage_data)
        self._refreshing = False
        self._data_version += 1

        return pct_5h, pct_7d

    def _try_token_refresh(self) -> bool:
        """Attempt to refresh the OAuth token via ``claude update``.

        Called on 401 auth errors.  If the token is successfully
        refreshed, immediately retries the API call.  If ``claude update``
        also installed a newer CLI version, shows a notification.

        Returns
        -------
        bool
            True if the token was refreshed and the retry succeeded
            (caller should skip the normal error path).
        """
        result = refresh_token()
        if not result.success:
            return False

        if result.updated:
            self.icon.notify(
                T['notify_update'].format(old=result.old_version, new=result.new_version),
                T['notify_update_title'],
            )

        # Check if the token actually changed
        if read_access_token() == self._last_failed_token:
            return False

        # Token changed - retry the API call
        self.usage_data = fetch_usage()
        if 'error' not in self.usage_data:
            pct_5h, pct_7d = self._apply_success()
            self._prev_5h = pct_5h
            self._prev_7d = pct_7d
            return True

        return False

    def _check_threshold_alerts(self) -> None:
        """Show a notification when usage crosses a configured threshold.

        For each variant, finds the highest threshold exceeded by current
        utilization.  If it exceeds a threshold not yet notified, shows a
        single notification with the current usage percentage.  When usage
        drops (e.g. after reset), tracking resets so thresholds can
        re-trigger in the next cycle.
        """
        for variant_key, notify_key in _VARIANT_NOTIFY_KEYS.items():
            entry = self.usage_data.get(variant_key)
            if not entry or entry.get('utilization') is None:
                continue

            pct = entry['utilization']
            thresholds = get_alert_thresholds(variant_key)
            if not thresholds:
                continue

            exceeded = [t for t in thresholds if pct >= t]
            highest_exceeded = max(exceeded) if exceeded else 0
            last_notified = self._notified_thresholds.get(variant_key, 0)

            if ALERT_TIME_AWARE and highest_exceeded > last_notified and highest_exceeded < ALERT_TIME_AWARE_BELOW:
                time_pct = elapsed_pct(entry.get('resets_at'), _VARIANT_PERIODS[variant_key])
                if time_pct is not None and pct <= time_pct:
                    self._notified_thresholds[variant_key] = highest_exceeded
                    continue

            if highest_exceeded > last_notified:
                self.icon.notify(
                    T[notify_key].format(pct=f'{pct:.0f}'),
                    T['notify_threshold_title'],
                )
                self._notified_thresholds[variant_key] = highest_exceeded
            elif highest_exceeded < last_notified:
                self._notified_thresholds[variant_key] = highest_exceeded

    def _seconds_until_next_reset(self) -> float | None:
        """Return seconds until the earliest upcoming quota reset, or None."""
        now = datetime.now(timezone.utc)
        earliest = None
        for key in ('five_hour', 'seven_day', 'seven_day_sonnet', 'seven_day_opus'):
            entry = self.usage_data.get(key)
            if not entry or not entry.get('resets_at'):
                continue
            try:
                reset_time = datetime.fromisoformat(entry['resets_at'])
                seconds = (reset_time - now).total_seconds()
                if seconds > 0 and (earliest is None or seconds < earliest):
                    earliest = seconds
            except Exception:
                continue

        return earliest

    _MAX_BACKOFF = 900

    def poll_loop(self) -> None:
        """Poll the API in a loop with adaptive intervals.

        Uses faster polling (``POLL_FAST``) when session usage is increasing,
        slower polling (``POLL_INTERVAL``) when idle.  Rate-limit errors
        (HTTP 429) use the server's ``Retry-After`` header when available,
        otherwise exponential backoff starting at ``POLL_INTERVAL`` up to
        ``_MAX_BACKOFF`` (15 min).  Transient errors (5xx, network) use
        ``POLL_ERROR`` for quick recovery.

        When a quota reset is imminent (within ``interval * 1.5``), the
        next poll is aligned to the reset time for immediate post-reset
        feedback.
        """
        self.profile_data = fetch_profile()
        while self.running:
            self.update()
            if self.usage_data.get('rate_limited'):
                retry_after = self.usage_data.get('retry_after')
                if retry_after is not None and retry_after > 0:
                    interval = max(retry_after, POLL_INTERVAL)
                else:
                    interval = int(min(POLL_INTERVAL * (2 ** (self._consecutive_errors - 1)), self._MAX_BACKOFF))
            elif 'error' in self.usage_data:
                interval = POLL_ERROR
            elif self._fast_polls_remaining > 0:
                interval = POLL_FAST
            else:
                interval = POLL_INTERVAL

            # Align next poll to an imminent reset for faster feedback.
            # The +5s buffer guards against minor timing differences
            # (clocks, caches, processing delays). Follow-up uses POLL_FAST
            # regardless of user activity (quota was likely exhausted).
            next_reset = self._seconds_until_next_reset()
            if next_reset is not None and next_reset + 5 <= interval * 1.5:
                interval = max(int(next_reset) + 5, POLL_FAST)
                self._fast_polls_remaining = max(self._fast_polls_remaining, 2)

            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    def _on_icon_ready(self, icon: Any) -> None:
        """Called by pystray in a separate thread once the tray icon is set up."""
        try:
            icon.visible = True
            if getattr(sys, 'frozen', False):
                sync_autostart_path()
            if not api_headers():
                icon.notify(f"{T['warn_no_token']}\n{T['warn_login']}", T['title'])
            threading.Thread(target=watch_theme_change, args=(self._on_theme_changed,), daemon=True).start()
            self.poll_loop()
        except Exception:
            crash_log(traceback.format_exc())

    def run(self) -> None:
        self.icon.run(setup=self._on_icon_ready)


def crash_log(msg: str) -> None:
    """Show a crash message box (for windowless EXE builds)."""
    ctypes.windll.user32.MessageBoxW(0, msg[:2000], 'Usage Monitor for Claude - Error', 0x10)

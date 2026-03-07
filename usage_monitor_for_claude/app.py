"""
Application
=============

System tray application class with adaptive polling and event handling.
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import pystray  # type: ignore[import-untyped]  # no type stubs available

from .api import api_headers
from .autostart import is_autostart_enabled, set_autostart, sync_autostart_path
from .cache import UsageCache
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
        self.cache = UsageCache()

        # Last raw API response (may contain 'error') - for icon and polling decisions
        self._last_response: dict[str, Any] = {}

        # Notification state
        self._prev_5h: float | None = None
        self._prev_7d: float | None = None
        self._notified_thresholds: dict[str, float] = {}

        # Adaptive polling state
        self._fast_polls_remaining = 0

        # Popup state
        self._popup_lock = threading.Lock()
        self._popup_open = False

        # Theme state
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

    # ── Menu actions ──────────────────────────────────────────

    def on_show_popup(self, icon: Any = None, item: Any = None) -> None:
        with self._popup_lock:
            if self._popup_open:
                return
            self._popup_open = True
        threading.Thread(target=self._open_popup, daemon=True).start()

    def on_refresh(self, icon: Any = None, item: Any = None) -> None:
        self.cache.clear_failed_token()
        threading.Thread(target=self.update, kwargs={'force': True}, daemon=True).start()

    def on_toggle_autostart(self, icon: Any = None, item: Any = None) -> None:
        set_autostart(not is_autostart_enabled())

    def on_quit(self, icon: Any = None, item: Any = None) -> None:
        self.running = False
        self.icon.stop()

    # ── Popup ─────────────────────────────────────────────────

    def _open_popup(self) -> None:
        # _popup_open is set True under _popup_lock (in on_show_popup) and
        # reset here without the lock.  This is safe because False is the
        # permissive default - a momentary stale True only delays the next open.
        try:
            needs_profile = not self.cache.profile
            needs_refresh = self.cache.last_success_time is None or time.time() - self.cache.last_success_time >= POLL_FAST
            if needs_profile or needs_refresh:
                # Single thread: ensure_profile() and update() both acquire
                # cache._lock, so they must run sequentially.  Two threads
                # would cause update()'s non-blocking acquire to fail while
                # ensure_profile() holds the lock.
                def _bg_refresh() -> None:
                    if needs_profile:
                        self.cache.ensure_profile()
                    if needs_refresh:
                        self.update()
                threading.Thread(target=_bg_refresh, daemon=True).start()
            UsagePopup(self)
        finally:
            self._popup_open = False

    # ── Tray rendering ────────────────────────────────────────

    def _render_tray(self) -> None:
        """Re-render tray icon and tooltip from current state."""
        data = self._last_response
        if 'error' in data:
            self.icon.icon = create_status_image('C!' if data.get('auth_error') else '!', self._light_taskbar)
        else:
            pct_5h = data.get('five_hour', {}).get('utilization', 0) or 0
            pct_7d = data.get('seven_day', {}).get('utilization', 0) or 0
            self.icon.icon = create_icon_image(pct_5h, pct_7d, self._light_taskbar)
        self.icon.title = format_tooltip(data)

    def _on_theme_changed(self) -> None:
        """Re-render the tray icon when the Windows theme changes."""
        light = taskbar_uses_light_theme()
        if light == self._light_taskbar:
            return

        self._light_taskbar = light
        if self._last_response:
            self._render_tray()

    # ── Update orchestration ──────────────────────────────────

    def update(self, *, force: bool = False) -> None:
        """Request a data refresh from the cache and process the result.

        Parameters
        ----------
        force : bool
            Bypass the cooldown (e.g. for explicit user refresh).
        """
        result = self.cache.update(force=force)
        if result.data is None:
            return

        self._last_response = result.data
        self._render_tray()

        # Handle CLI update notification from token refresh
        if result.token_refresh and result.token_refresh.updated:
            self.icon.notify(
                T['notify_update'].format(old=result.token_refresh.old_version, new=result.token_refresh.new_version),
                T['notify_update_title'],
            )

        if 'error' in result.data:
            return

        pct_5h = result.data.get('five_hour', {}).get('utilization', 0) or 0
        pct_7d = result.data.get('seven_day', {}).get('utilization', 0) or 0

        # Notify when quota resets after being nearly exhausted, but only if the other quota isn't blocking usage
        if self._prev_5h is not None and self._prev_5h > 95 and pct_5h < self._prev_5h and pct_7d < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])
        if self._prev_7d is not None and self._prev_7d > 98 and pct_7d < self._prev_7d and pct_5h < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])

        self._check_threshold_alerts(result.data)

        # Adaptive polling: speed up when session usage is increasing
        if self._prev_5h is not None and pct_5h > self._prev_5h:
            self._fast_polls_remaining = POLL_FAST_EXTRA + 1
        elif self._fast_polls_remaining > 0:
            self._fast_polls_remaining -= 1
        self._prev_5h = pct_5h
        self._prev_7d = pct_7d

    # ── Notifications ─────────────────────────────────────────

    def _check_threshold_alerts(self, data: dict[str, Any]) -> None:
        """Show a notification when usage crosses a configured threshold.

        For each variant, finds the highest threshold exceeded by current
        utilization.  If it exceeds a threshold not yet notified, shows a
        single notification with the current usage percentage.  When usage
        drops (e.g. after reset), tracking resets so thresholds can
        re-trigger in the next cycle.
        """
        for variant_key, notify_key in _VARIANT_NOTIFY_KEYS.items():
            entry = data.get(variant_key)
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

    # ── Polling ───────────────────────────────────────────────

    def _seconds_until_next_reset(self) -> float | None:
        """Return seconds until the earliest upcoming quota reset, or None."""
        now = datetime.now(timezone.utc)
        earliest = None
        for key in ('five_hour', 'seven_day', 'seven_day_sonnet', 'seven_day_opus'):
            entry = self._last_response.get(key)
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

    def _calculate_poll_interval(self) -> int:
        """Determine the next poll interval based on current state.

        Returns
        -------
        int
            Seconds to wait before the next poll.
        """
        data = self._last_response

        if data.get('rate_limited'):
            remaining = self.cache.rate_limit_remaining
            interval = max(math.ceil(remaining), POLL_INTERVAL) if remaining > 0 else POLL_INTERVAL
        elif 'error' in data:
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

        return interval

    def poll_loop(self) -> None:
        """Poll the API in a loop with adaptive intervals."""
        self.cache.ensure_profile()
        while self.running:
            self.update()
            interval = self._calculate_poll_interval()

            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    # ── Lifecycle ─────────────────────────────────────────────

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

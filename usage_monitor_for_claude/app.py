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
from .settings import POLL_ERROR, POLL_FAST, POLL_FAST_EXTRA, POLL_INTERVAL
from .formatting import format_tooltip
from .i18n import T
from .popup import UsagePopup
from .tray_icon import create_icon_image, create_status_image, taskbar_uses_light_theme, watch_theme_change


class UsageMonitorForClaude:
    """System tray application displaying Claude usage."""

    def __init__(self) -> None:
        """Set up the tray icon with context menu and polling state."""
        self.running = True
        self.usage_data = {}
        self.profile_data = None
        self._last_failed_token: str | None = None
        self._prev_5h = None
        self._prev_7d = None
        self._fast_polls_remaining = 0
        self._popup_open = False
        self._data_version = 0
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
            self.update()
            if not self.profile_data:
                self.profile_data = fetch_profile()
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
        """
        if self._last_failed_token is not None:
            if read_access_token() == self._last_failed_token:
                return

            self._last_failed_token = None

        self.usage_data = fetch_usage()

        if 'error' in self.usage_data:
            if self.usage_data.get('auth_error'):
                self._last_failed_token = read_access_token()

            self.icon.icon = create_status_image('C!' if self.usage_data.get('auth_error') else '!', self._light_taskbar)
            self.icon.title = format_tooltip(self.usage_data)
            self._data_version += 1
            return

        pct_5h = self.usage_data.get('five_hour', {}).get('utilization', 0) or 0
        pct_7d = self.usage_data.get('seven_day', {}).get('utilization', 0) or 0

        # Notify when quota resets after being nearly exhausted, but only if the other quota isn't blocking usage
        if self._prev_5h is not None and self._prev_5h > 95 and pct_5h < self._prev_5h and pct_7d < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])
        if self._prev_7d is not None and self._prev_7d > 98 and pct_7d < self._prev_7d and pct_5h < 99:
            self.icon.notify(T['notify_reset'], T['notify_reset_title'])

        # Adaptive polling: speed up when session usage is increasing
        if self._prev_5h is not None and pct_5h > self._prev_5h:
            self._fast_polls_remaining = POLL_FAST_EXTRA + 1
        elif self._fast_polls_remaining > 0:
            self._fast_polls_remaining -= 1
        self._prev_5h = pct_5h
        self._prev_7d = pct_7d

        self.icon.icon = create_icon_image(pct_5h, pct_7d, self._light_taskbar)
        self.icon.title = format_tooltip(self.usage_data)
        self._data_version += 1

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

    def poll_loop(self) -> None:
        """Poll the API in a loop with adaptive intervals.

        Uses faster polling (``POLL_FAST``) when session usage is increasing,
        slower polling (``POLL_INTERVAL``) when idle, and error-rate polling
        (``POLL_ERROR``) after failed requests.  When a quota reset is
        imminent (within ``interval * 1.5``), the next poll is aligned to
        the reset time for immediate post-reset feedback.
        """
        self.profile_data = fetch_profile()
        while self.running:
            self.update()
            if 'error' in self.usage_data:
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

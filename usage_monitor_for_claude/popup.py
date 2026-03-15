"""
Popup Window
=============

Dark-themed popup window showing account info and usage bars.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import tkinter as tk
import webbrowser
from typing import TYPE_CHECKING, Any

from .claude_cli import CHANGELOG_URL, find_installations
from .settings import BAR_BG, BAR_FG, BAR_FG_WARN, BG, FG, FG_DIM, FG_HEADING
from .formatting import PERIOD_5H, PERIOD_7D, elapsed_pct, format_credits, format_status, midnight_positions, time_until
from .i18n import T

__all__ = ['UsagePopup']

if TYPE_CHECKING:
    from .app import UsageMonitorForClaude
    from .cache import CacheSnapshot


class UsagePopup:
    """Dark-themed popup window showing account info and usage bars."""

    WIDTH = 340
    _CHECK_MS = 2000

    def __init__(self, app: UsageMonitorForClaude) -> None:
        """Create and display a popup window with usage details.

        Blocks the calling thread until the window is closed (runs its own mainloop).

        Parameters
        ----------
        app : UsageMonitorForClaude
            Parent application providing ``cache`` for data access.
        """
        self.app = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)  # type: ignore[call-overload]  # tkinter overload stubs incomplete
        self.win.configure(bg=BG)
        self.win.minsize(self.WIDTH, 0)
        self.win.resizable(False, False)

        self._main_frame: tk.Frame | None = None
        self._account_frame: tk.Frame | None = None
        self._usage_frame: tk.Frame | None = None
        self._usage_bars: list[dict[str, Any]] = []
        self._extra_frame: tk.Frame | None = None
        self._extra_widgets: dict[str, Any] | None = None
        self._install_frame: tk.Frame | None = None
        self._status_frame: tk.Frame | None = None
        self._status_label: tk.Label | None = None
        self._status_text = ''
        self._status_fg = ''
        snap = self.app.cache.snapshot
        self._last_version = snap.version
        self._build_content(snap)

        self._position_near_tray()
        self._schedule_check()

        self.win.bind('<Escape>', lambda e: self._close())
        self.win.bind('<FocusOut>', lambda e: self._close())
        self.win.focus_force()

        self.root.mainloop()

    def _close(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _schedule_check(self) -> None:
        try:
            self.root.after(self._CHECK_MS, self._check_for_update)
        except tk.TclError:
            pass

    def _check_for_update(self) -> None:
        try:
            snap = self.app.cache.snapshot
            if snap.version != self._last_version:
                self._last_version = snap.version
                self._build_account_section(snap.profile)
                self._update_usage_section(snap.usage)
                self._update_extra_usage_section(snap.usage)
                self._build_installations_section()
                self._position_near_tray()
            self._update_countdowns()
            self._update_status_line()
            self._schedule_check()
        except tk.TclError:
            pass

    def _position_near_tray(self) -> None:
        """Place the popup near the system tray, growing away from the taskbar.

        Detects the taskbar position from the work area and anchors the
        popup so that size changes expand away from the taskbar edge.
        """
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()

        # Use the taskbar-aware work area so the popup clears the taskbar regardless of its size or DPI
        work_area = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)

        margin = 12

        # Horizontal: anchor near the taskbar side, grow away from it
        if work_area.left > 0:
            x = work_area.left + margin
        else:
            x = work_area.right - w - margin

        # Vertical: anchor near the taskbar side, grow away from it
        if work_area.top > 0:
            y = work_area.top + margin
        else:
            y = work_area.bottom - h - margin

        self.win.geometry(f'+{x}+{y}')

    def _build_content(self, snap: CacheSnapshot) -> None:
        """Build the popup layout: title bar, account info, and usage section."""
        pad = 16
        self._main_frame = tk.Frame(self.win, bg=BG, padx=pad)
        self._main_frame.pack(fill='both', expand=True, pady=(12, 16))

        # Title bar
        title_frame = tk.Frame(self._main_frame, bg=BG)
        title_frame.pack(fill='x', pady=(0, 4))
        tk.Label(title_frame, text=T['title'], font=('Segoe UI', 13, 'bold'), fg=FG_HEADING, bg=BG).pack(side='left')
        close_btn = tk.Label(title_frame, text='\u00d7', font=('Segoe UI', 16), fg=FG_DIM, bg=BG, cursor='hand2')
        close_btn.pack(side='right')
        close_btn.bind('<Button-1>', lambda e: self._close())

        # Account section
        self._build_account_section(snap.profile)

        # Usage section (rebuilt on refresh)
        self._build_usage_section(snap.usage)

        # Extra usage section
        self._build_extra_usage_section(snap.usage)

        # Claude Code installations
        self._build_installations_section()

        # Status line
        self._build_status_line()

    def _has_content(self, *frames: tk.Frame | None) -> bool:
        """Return True if at least one of the given frames has visible children."""
        return any(f and f.winfo_children() for f in frames)

    def _build_account_section(self, profile: dict[str, Any] | None) -> None:
        """Build the account info section, replacing any previous content."""
        if self._account_frame:
            for child in self._account_frame.winfo_children():
                child.destroy()
        else:
            self._account_frame = tk.Frame(self._main_frame, bg=BG)
            self._account_frame.pack(fill='x')

        if not profile:
            return

        self._section_heading(self._account_frame, T['account'])
        account = profile.get('account', {})
        org = profile.get('organization', {})
        plan = org.get('organization_type', '').replace('_', ' ').title()
        email = account.get('email', '')
        if email:
            self._info_row(self._account_frame, T['email'], email)
        if plan:
            self._info_row(self._account_frame, T['plan'], plan)

    def _usage_entries(self, usage: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None, int]]:
        """Return the list of usage entry tuples from the given usage data."""
        return [
            (T['session'], usage.get('five_hour'), PERIOD_5H),
            (T['weekly'], usage.get('seven_day'), PERIOD_7D),
            (T['weekly_sonnet'], usage.get('seven_day_sonnet'), PERIOD_7D),
            (T['weekly_opus'], usage.get('seven_day_opus'), PERIOD_7D),
        ]

    def _visible_entries(self, usage: dict[str, Any]) -> list[tuple[str, dict[str, Any], int]]:
        """Return only entries that have utilization data."""
        return [(label, entry, period) for label, entry, period in self._usage_entries(usage) if entry and entry.get('utilization') is not None]

    def _build_usage_section(self, usage: dict[str, Any]) -> None:
        """Build the usage bars section from scratch, replacing any previous content."""
        if self._usage_frame:
            for child in self._usage_frame.winfo_children():
                child.destroy()
        else:
            self._usage_frame = tk.Frame(self._main_frame, bg=BG)
            self._usage_frame.pack(fill='x')
        self._usage_bars = []

        if not usage:
            return

        if self._has_content(self._account_frame):
            tk.Frame(self._usage_frame, bg=BAR_BG, height=1).pack(fill='x', pady=(10, 4))
        self._section_heading(self._usage_frame, T['usage'])

        first = True
        for label, entry, period in self._visible_entries(usage):
            widgets = self._create_usage_bar(self._usage_frame, label, entry, period, first=first)
            self._usage_bars.append(widgets)
            first = False

    def _update_usage_section(self, usage: dict[str, Any]) -> None:
        """Update usage bars in-place, falling back to full rebuild if structure changed."""
        visible = self._visible_entries(usage)

        if len(visible) == len(self._usage_bars):
            for (_label, entry, period), widgets in zip(visible, self._usage_bars):
                self._update_usage_bar(widgets, entry, period)
            return

        self._build_usage_section(usage)
        self._build_extra_usage_section(usage)
        self._repack_status_line()

    def _extra_usage_data(self, usage: dict[str, Any]) -> tuple[float, float, float] | None:
        """Return extra usage (pct, used_cents, limit_cents), or None if not enabled."""
        extra = usage.get('extra_usage')
        if not extra or not extra.get('is_enabled'):
            return None

        limit = extra.get('monthly_limit', 0) or 0
        if limit <= 0:
            return None

        used = extra.get('used_credits', 0) or 0
        return (used / limit * 100, used, limit)

    def _build_extra_usage_section(self, usage: dict[str, Any]) -> None:
        """Build the extra usage section from scratch."""
        if self._extra_frame:
            for child in self._extra_frame.winfo_children():
                child.destroy()
        else:
            self._extra_frame = tk.Frame(self._main_frame, bg=BG)
            self._extra_frame.pack(fill='x')
        self._extra_widgets = None

        data = self._extra_usage_data(usage)
        if data is None:
            return

        pct, used, limit = data

        if self._has_content(self._account_frame, self._usage_frame):
            tk.Frame(self._extra_frame, bg=BAR_BG, height=1).pack(fill='x', pady=(10, 4))
        self._section_heading(self._extra_frame, T['extra_usage'])

        spent_text = T['extra_usage_spent'].format(used=format_credits(used), limit=format_credits(limit))

        row = tk.Frame(self._extra_frame, bg=BG)
        row.pack(fill='x', pady=(0, 4))
        spent_label = tk.Label(row, text=spent_text, fg=FG_DIM, bg=BG, font=('Segoe UI', 10), padx=0)
        spent_label.pack(side='left')
        pct_label = tk.Label(row, text=f'{pct:.0f}%', fg=FG, bg=BG, font=('Segoe UI', 10), padx=0)
        pct_label.pack(side='right')

        bar_h = 8
        bar_frame = tk.Frame(self._extra_frame, bg=BAR_BG, height=bar_h)
        bar_frame.pack(fill='x', padx=2, pady=(0, 2))
        bar_frame.pack_propagate(False)
        fill_pct = max(0.0, min(1.0, pct / 100))
        fill_frame = None
        if fill_pct > 0:
            fill_frame = tk.Frame(bar_frame, bg=BAR_FG)
            fill_frame.place(relwidth=fill_pct, relheight=1.0)

        self._extra_widgets = {
            'pct_label': pct_label, 'bar_frame': bar_frame,
            'fill_frame': fill_frame, 'spent_label': spent_label,
        }

    def _update_extra_usage_section(self, usage: dict[str, Any]) -> None:
        """Update extra usage bar in-place, or rebuild if visibility changed."""
        data = self._extra_usage_data(usage)
        had_section = self._extra_widgets is not None

        if (data is None) != (not had_section):
            self._build_extra_usage_section(usage)
            self._repack_status_line()
            return

        if data is None or self._extra_widgets is None:
            return

        pct, used, limit = data
        self._extra_widgets['pct_label'].configure(text=f'{pct:.0f}%')

        spent_text = T['extra_usage_spent'].format(used=format_credits(used), limit=format_credits(limit))
        self._extra_widgets['spent_label'].configure(text=spent_text)

        fill_pct = max(0.0, min(1.0, pct / 100))
        color = BAR_FG
        bar_frame = self._extra_widgets['bar_frame']
        if fill_pct > 0:
            if self._extra_widgets['fill_frame']:
                self._extra_widgets['fill_frame'].place_configure(relwidth=fill_pct)
                self._extra_widgets['fill_frame'].configure(bg=color)
            else:
                self._extra_widgets['fill_frame'] = tk.Frame(bar_frame, bg=color)
                self._extra_widgets['fill_frame'].place(relwidth=fill_pct, relheight=1.0)
        elif self._extra_widgets['fill_frame']:
            self._extra_widgets['fill_frame'].destroy()
            self._extra_widgets['fill_frame'] = None

    def _build_installations_section(self) -> None:
        """Build the Claude Code installations section showing discovered versions."""
        if self._install_frame:
            for child in self._install_frame.winfo_children():
                child.destroy()
        else:
            self._install_frame = tk.Frame(self._main_frame, bg=BG)
            self._install_frame.pack(fill='x')

        installations = find_installations()
        if not installations:
            return

        if self._has_content(self._account_frame, self._usage_frame, self._extra_frame):
            tk.Frame(self._install_frame, bg=BAR_BG, height=1).pack(fill='x', pady=(10, 4))

        self._section_heading(self._install_frame, T['claude_code'], link_text=T['changelog'], link_url=CHANGELOG_URL)

        for inst in installations:
            self._info_row(self._install_frame, inst.name, inst.version)

    def _build_status_line(self) -> None:
        """Build the status line at the bottom of the popup."""
        self._status_frame = tk.Frame(self._main_frame, bg=BG)
        self._status_frame.pack(fill='x', side='bottom')

        if self._has_content(self._account_frame, self._usage_frame, self._extra_frame, self._install_frame):
            tk.Frame(self._status_frame, bg=BAR_BG, height=1).pack(fill='x', pady=(10, 4))
        self._status_label = tk.Label(
            self._status_frame, text='', fg=FG_DIM, bg=BG,
            font=('Segoe UI', 8), wraplength=self.WIDTH - 32, justify='left',
        )
        self._status_label.pack(anchor='w')

        self._update_status_line()

    def _repack_status_line(self) -> None:
        """Ensure the status line stays at the bottom after section rebuilds."""
        if self._status_frame:
            self._status_frame.pack_forget()
            self._status_frame.pack(fill='x', side='bottom')

    def _update_status_line(self) -> None:
        """Refresh the status text with current freshness and error state."""
        if not self._status_label:
            return

        snap = self.app.cache.snapshot
        if not snap.usage:
            if snap.last_error:
                text, fg = snap.last_error[:120], '#e05050'
            else:
                text, fg = T['status_refreshing'], FG_DIM
        else:
            status_text, has_error = format_status(snap.last_success_time, snap.refreshing, snap.last_error)
            text, fg = status_text, '#e05050' if has_error else FG_DIM

        if text != self._status_text or fg != self._status_fg:
            self._status_text = text
            self._status_fg = fg
            self._status_label.configure(text=text, fg=fg)
            self._position_near_tray()

    def _update_countdowns(self) -> None:
        """Refresh reset countdown texts and elapsed markers between API polls."""
        for widgets in self._usage_bars:
            resets_at = widgets.get('resets_at', '')
            period_seconds = widgets.get('period_seconds', 0)

            reset_text = time_until(resets_at) if resets_at else ''
            reset_label = widgets['reset_label']
            if reset_text:
                reset_label.configure(text=reset_text)
            elif reset_label.winfo_manager():
                reset_label.pack_forget()

            time_pct = elapsed_pct(resets_at, period_seconds)
            if time_pct is not None and widgets['marker_frame']:
                marker_rel = max(0.0, min(1.0, time_pct / 100))
                widgets['marker_frame'].place_configure(relx=marker_rel)

    def _section_heading(self, parent: tk.Frame, text: str, *, link_text: str = '', link_url: str = '') -> None:
        if not link_text:
            tk.Label(parent, text=text, font=('Segoe UI', 9, 'bold'), fg=FG_DIM, bg=BG).pack(anchor='w', pady=(8, 2))
            return

        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=(8, 2))
        tk.Label(row, text=text, font=('Segoe UI', 9, 'bold'), fg=FG_DIM, bg=BG).pack(side='left')
        link = tk.Label(row, text=link_text, font=('Segoe UI', 8, 'underline'), fg=BAR_FG, bg=BG, cursor='hand2')
        link.pack(side='right')
        link.bind('<Button-1>', lambda e: webbrowser.open(link_url))

    def _info_row(self, parent: tk.Frame, label: str, value: str) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=0)
        tk.Label(row, text=label, fg=FG_DIM, bg=BG, font=('Segoe UI', 10)).pack(side='left')
        tk.Label(row, text=value, fg=FG, bg=BG, font=('Segoe UI', 10)).pack(side='right')

    def _create_usage_bar(
        self, parent: tk.Frame, label: str, entry: dict[str, Any], period_seconds: int, *, first: bool = False,
    ) -> dict[str, Any]:
        """Create a usage bar group and return widget references for in-place updates."""
        pct = entry.get('utilization', 0) or 0
        resets_at = entry.get('resets_at', '')
        time_pct = elapsed_pct(resets_at, period_seconds)
        warn = time_pct is not None and pct > time_pct

        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=(0 if first else 8, 4))
        tk.Label(row, text=label, fg=FG, bg=BG, font=('Segoe UI', 10), padx=0).pack(side='left')
        pct_label = tk.Label(row, text=f'{pct:.0f}%', fg=FG, bg=BG, font=('Segoe UI', 10), padx=0)
        pct_label.pack(side='right')

        bar_h = 8
        bar_frame = tk.Frame(parent, bg=BAR_BG, height=bar_h)
        bar_frame.pack(fill='x', padx=2, pady=(0, 2))
        bar_frame.pack_propagate(False)
        fill_pct = max(0.0, min(1.0, pct / 100))
        fill_frame = None
        if fill_pct > 0:
            fill_frame = tk.Frame(bar_frame, bg=BAR_FG_WARN if warn else BAR_FG)
            fill_frame.place(relwidth=fill_pct, relheight=1.0)

        # Day segment dividers at local midnight boundaries (z-order: fill -> dividers -> elapsed marker)
        divider_frames = []
        for relx in midnight_positions(resets_at, period_seconds):
            divider = tk.Frame(bar_frame, bg=BG, width=1)
            divider.place(relx=relx, relheight=1.0, width=1)
            divider_frames.append(divider)

        marker_frame = None
        if time_pct is not None:
            marker_rel = max(0.0, min(1.0, time_pct / 100))
            marker_frame = tk.Frame(bar_frame, bg='#ffffff', width=1)
            marker_frame.place(relx=marker_rel, relheight=1.0, width=1)

        reset_text = time_until(resets_at) if resets_at else ''
        reset_label = tk.Label(parent, text=reset_text, fg=FG_DIM, bg=BG, font=('Segoe UI', 8))
        if reset_text:
            reset_label.pack(anchor='w')

        return {
            'pct_label': pct_label, 'bar_frame': bar_frame,
            'fill_frame': fill_frame, 'divider_frames': divider_frames, 'marker_frame': marker_frame, 'reset_label': reset_label,
            'resets_at': resets_at, 'period_seconds': period_seconds,
        }

    def _update_usage_bar(self, widgets: dict[str, Any], entry: dict[str, Any], period_seconds: int) -> None:
        """Update an existing usage bar's values in-place."""
        pct = entry.get('utilization', 0) or 0
        resets_at = entry.get('resets_at', '')
        time_pct = elapsed_pct(resets_at, period_seconds)
        warn = time_pct is not None and pct > time_pct
        bar_frame = widgets['bar_frame']

        widgets['pct_label'].configure(text=f'{pct:.0f}%')

        fill_pct = max(0.0, min(1.0, pct / 100))
        color = BAR_FG_WARN if warn else BAR_FG
        if fill_pct > 0:
            if widgets['fill_frame']:
                widgets['fill_frame'].place_configure(relwidth=fill_pct)
                widgets['fill_frame'].configure(bg=color)
            else:
                widgets['fill_frame'] = tk.Frame(bar_frame, bg=color)
                widgets['fill_frame'].place(relwidth=fill_pct, relheight=1.0)
                widgets['fill_frame'].lower()
        elif widgets['fill_frame']:
            widgets['fill_frame'].destroy()
            widgets['fill_frame'] = None

        if resets_at != widgets['resets_at']:
            for divider in widgets['divider_frames']:
                divider.destroy()
            widgets['divider_frames'] = []
            for relx in midnight_positions(resets_at, period_seconds):
                divider = tk.Frame(bar_frame, bg=BG, width=1)
                divider.place(relx=relx, relheight=1.0, width=1)
                widgets['divider_frames'].append(divider)

        time_pct = elapsed_pct(resets_at, period_seconds)
        if time_pct is not None:
            marker_rel = max(0.0, min(1.0, time_pct / 100))
            if widgets['marker_frame']:
                widgets['marker_frame'].place_configure(relx=marker_rel)
            else:
                widgets['marker_frame'] = tk.Frame(bar_frame, bg='#ffffff', width=1)
                widgets['marker_frame'].place(relx=marker_rel, relheight=1.0, width=1)
        elif widgets['marker_frame']:
            widgets['marker_frame'].destroy()
            widgets['marker_frame'] = None

        widgets['resets_at'] = resets_at
        widgets['period_seconds'] = period_seconds

        reset_text = time_until(resets_at) if resets_at else ''
        reset_label = widgets['reset_label']
        if reset_text:
            reset_label.configure(text=reset_text)
            if not reset_label.winfo_manager():
                reset_label.pack(anchor='w')
        elif reset_label.winfo_manager():
            reset_label.pack_forget()

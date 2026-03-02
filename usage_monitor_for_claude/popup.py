"""
Popup Window
=============

Dark-themed popup window showing account info and usage bars.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import tkinter as tk
from typing import TYPE_CHECKING, Any

from .settings import BAR_BG, BAR_FG, BAR_FG_HIGH, BG, FG, FG_DIM, FG_HEADING
from .formatting import PERIOD_5H, PERIOD_7D, elapsed_pct, format_credits, time_until
from .i18n import T

if TYPE_CHECKING:
    from .app import UsageMonitorForClaude


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
            Parent application providing ``usage_data`` and ``profile_data``.
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
        self._usage_frame: tk.Frame | None = None
        self._usage_bars: list[dict[str, Any]] = []
        self._extra_frame: tk.Frame | None = None
        self._extra_widgets: dict[str, Any] | None = None
        self._last_version = self.app._data_version
        self._build_content()

        self.win.update_idletasks()
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
            if self.app._data_version != self._last_version:
                self._last_version = self.app._data_version
                self._update_usage_section()
                self._update_extra_usage_section()
            self._schedule_check()
        except tk.TclError:
            pass

    def _position_near_tray(self) -> None:
        """Place the popup in the bottom-right corner, above the Windows taskbar."""
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        sx = self.win.winfo_screenwidth()

        # Use the taskbar-aware work area so the popup clears the taskbar regardless of its size or DPI
        work_area = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)

        x = sx - w - 12
        y = work_area.bottom - h - 12
        self.win.geometry(f'+{x}+{y}')

    def _build_content(self) -> None:
        """Build the popup layout: title bar, account info, and usage section."""
        pad = 16
        self._main_frame = tk.Frame(self.win, bg=BG, padx=pad)
        self._main_frame.pack(fill='both', expand=True, pady=(12, 16))

        # ── Title bar ──
        title_frame = tk.Frame(self._main_frame, bg=BG)
        title_frame.pack(fill='x', pady=(0, 4))
        tk.Label(title_frame, text=T['title'], font=('Segoe UI', 13, 'bold'), fg=FG_HEADING, bg=BG).pack(side='left')
        close_btn = tk.Label(title_frame, text='\u00d7', font=('Segoe UI', 16), fg=FG_DIM, bg=BG, cursor='hand2')
        close_btn.pack(side='right')
        close_btn.bind('<Button-1>', lambda e: self._close())

        # ── Account section ──
        profile = self.app.profile_data
        if profile:
            self._section_heading(self._main_frame, T['account'])
            account = profile.get('account', {})
            org = profile.get('organization', {})
            plan = org.get('organization_type', '').replace('_', ' ').title()
            email = account.get('email', '')
            if email:
                self._info_row(self._main_frame, T['email'], email)
            if plan:
                self._info_row(self._main_frame, T['plan'], plan)
            tk.Frame(self._main_frame, bg=BAR_BG, height=1).pack(fill='x', pady=(10, 4))

        # ── Usage section (rebuilt on refresh) ──
        self._build_usage_section()

        # ── Extra usage section ──
        self._build_extra_usage_section()

    def _usage_entries(self) -> list[tuple[str, dict[str, Any] | None, int]]:
        """Return the list of usage entry tuples from current data."""
        usage = self.app.usage_data
        return [
            (T['session'], usage.get('five_hour'), PERIOD_5H),
            (T['weekly'], usage.get('seven_day'), PERIOD_7D),
            (T['weekly_sonnet'], usage.get('seven_day_sonnet'), PERIOD_7D),
            (T['weekly_opus'], usage.get('seven_day_opus'), PERIOD_7D),
        ]

    def _visible_entries(self) -> list[tuple[str, dict[str, Any], int]]:
        """Return only entries that have utilization data."""
        return [(label, entry, period) for label, entry, period in self._usage_entries() if entry and entry.get('utilization') is not None]

    def _build_usage_section(self) -> None:
        """Build the usage bars section from scratch, replacing any previous content."""
        usage = self.app.usage_data

        if self._usage_frame:
            self._usage_frame.destroy()
        self._usage_bars = []

        self._usage_frame = tk.Frame(self._main_frame, bg=BG)
        self._usage_frame.pack(fill='x')

        self._section_heading(self._usage_frame, T['usage'])

        if 'error' in usage:
            tk.Label(
                self._usage_frame, text=usage['error'][:120], fg='#e05050', bg=BG,
                font=('Segoe UI', 9), wraplength=self.WIDTH - 32, justify='left',
            ).pack(anchor='w', pady=4)
            return

        first = True
        for label, entry, period in self._visible_entries():
            widgets = self._create_usage_bar(self._usage_frame, label, entry, period, first=first)
            self._usage_bars.append(widgets)
            first = False

    def _update_usage_section(self) -> None:
        """Update usage bars in-place, falling back to full rebuild if structure changed."""
        usage = self.app.usage_data
        visible = self._visible_entries()

        if 'error' in usage or len(visible) != len(self._usage_bars):
            self._build_usage_section()
            self._build_extra_usage_section()
            return

        for (_label, entry, period), widgets in zip(visible, self._usage_bars):
            self._update_usage_bar(widgets, entry, period)

    def _extra_usage_data(self) -> tuple[float, float, float] | None:
        """Return extra usage (pct, used_cents, limit_cents), or None if not enabled."""
        extra = self.app.usage_data.get('extra_usage')
        if not extra or not extra.get('is_enabled'):
            return None

        limit = extra.get('monthly_limit', 0) or 0
        if limit <= 0:
            return None

        used = extra.get('used_credits', 0) or 0
        return (used / limit * 100, used, limit)

    def _build_extra_usage_section(self) -> None:
        """Build the extra usage section from scratch."""
        if self._extra_frame:
            self._extra_frame.destroy()
        self._extra_frame = None
        self._extra_widgets = None

        data = self._extra_usage_data()
        if data is None:
            return

        pct, used, limit = data
        high = pct >= 80

        self._extra_frame = tk.Frame(self._main_frame, bg=BG)
        self._extra_frame.pack(fill='x')

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
            fill_frame = tk.Frame(bar_frame, bg=BAR_FG_HIGH if high else BAR_FG)
            fill_frame.place(relwidth=fill_pct, relheight=1.0)

        self._extra_widgets = {
            'pct_label': pct_label, 'bar_frame': bar_frame,
            'fill_frame': fill_frame, 'spent_label': spent_label,
        }

    def _update_extra_usage_section(self) -> None:
        """Update extra usage bar in-place, or rebuild if visibility changed."""
        data = self._extra_usage_data()
        had_section = self._extra_widgets is not None

        if (data is None) != (not had_section):
            self._build_extra_usage_section()
            return

        if data is None or self._extra_widgets is None:
            return

        pct, used, limit = data
        high = pct >= 80
        self._extra_widgets['pct_label'].configure(text=f'{pct:.0f}%')

        spent_text = T['extra_usage_spent'].format(used=format_credits(used), limit=format_credits(limit))
        self._extra_widgets['spent_label'].configure(text=spent_text)

        fill_pct = max(0.0, min(1.0, pct / 100))
        color = BAR_FG_HIGH if high else BAR_FG
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

    def _section_heading(self, parent: tk.Frame, text: str) -> None:
        tk.Label(parent, text=text, font=('Segoe UI', 9, 'bold'), fg=FG_DIM, bg=BG).pack(anchor='w', pady=(8, 2))

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
        high = pct >= 80

        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=(4 if first else 8, 4))
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
            fill_frame = tk.Frame(bar_frame, bg=BAR_FG_HIGH if high else BAR_FG)
            fill_frame.place(relwidth=fill_pct, relheight=1.0)

        time_pct = elapsed_pct(resets_at, period_seconds)
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
            'fill_frame': fill_frame, 'marker_frame': marker_frame, 'reset_label': reset_label,
        }

    def _update_usage_bar(self, widgets: dict[str, Any], entry: dict[str, Any], period_seconds: int) -> None:
        """Update an existing usage bar's values in-place."""
        pct = entry.get('utilization', 0) or 0
        resets_at = entry.get('resets_at', '')
        high = pct >= 80
        bar_frame = widgets['bar_frame']

        widgets['pct_label'].configure(text=f'{pct:.0f}%')

        fill_pct = max(0.0, min(1.0, pct / 100))
        color = BAR_FG_HIGH if high else BAR_FG
        if fill_pct > 0:
            if widgets['fill_frame']:
                widgets['fill_frame'].place_configure(relwidth=fill_pct)
                widgets['fill_frame'].configure(bg=color)
            else:
                widgets['fill_frame'] = tk.Frame(bar_frame, bg=color)
                widgets['fill_frame'].place(relwidth=fill_pct, relheight=1.0)
        elif widgets['fill_frame']:
            widgets['fill_frame'].destroy()
            widgets['fill_frame'] = None

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

        reset_text = time_until(resets_at) if resets_at else ''
        reset_label = widgets['reset_label']
        if reset_text:
            reset_label.configure(text=reset_text)
            if not reset_label.winfo_manager():
                reset_label.pack(anchor='w')
        elif reset_label.winfo_manager():
            reset_label.pack_forget()

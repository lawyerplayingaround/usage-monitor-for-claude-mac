"""
Formatting
===========

Pure functions for formatting usage data: time-until-reset strings,
elapsed period percentages, credit amounts, status lines, and tooltip text.
"""
from __future__ import annotations

import locale as _locale
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .i18n import T
from .settings import CURRENCY_SYMBOL, _SYSTEM_CURRENCY_SYMBOL

__all__ = ['PERIOD_5H', 'PERIOD_7D', 'elapsed_pct', 'midnight_positions', 'time_until', 'format_credits', 'format_status', 'format_tooltip']

PERIOD_5H = 5 * 3600
PERIOD_7D = 7 * 24 * 3600


def elapsed_pct(resets_at: str, period_seconds: int) -> float | None:
    """Return elapsed percentage of a usage period, or None if not calculable.

    Parameters
    ----------
    resets_at : str
        ISO 8601 timestamp when the limit resets.
    period_seconds : int
        Total duration of the period in seconds (e.g. 18000 for 5h).

    Returns
    -------
    float or None
        Percentage of the period that has already elapsed (0-100),
        or None if the value cannot be determined.
    """
    if not resets_at or period_seconds <= 0:
        return None

    try:
        reset = datetime.fromisoformat(resets_at)
        now = datetime.now(timezone.utc)
        remaining = (reset - now).total_seconds()
        elapsed = period_seconds - remaining

        return max(0.0, min(100.0, elapsed / period_seconds * 100))
    except Exception:
        return None


def midnight_positions(resets_at: str, period_seconds: int) -> list[float]:
    """Return relative positions (0.0-1.0) of local midnight boundaries within a usage period.

    Parameters
    ----------
    resets_at : str
        ISO 8601 timestamp when the limit resets.
    period_seconds : int
        Total duration of the period in seconds.

    Returns
    -------
    list[float]
        Positions where local midnights fall within the period, each in the
        range (0.0, 1.0) exclusive.  Positions that would round to 0px at
        typical bar widths are omitted.
    """
    if not resets_at or period_seconds <= 0:
        return []

    try:
        reset_utc = datetime.fromisoformat(resets_at)
        start_utc = reset_utc - timedelta(seconds=period_seconds)

        start_local = start_utc.astimezone()
        end_local = reset_utc.astimezone()

        # First midnight after the period start
        midnight = (start_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        positions = []
        while midnight < end_local:
            elapsed = (midnight - start_local).total_seconds()
            rel = elapsed / period_seconds
            if rel > 0.003:
                positions.append(rel)
            midnight += timedelta(days=1)

        return positions
    except Exception:
        return []


def time_until(iso_str: str) -> str:
    """Return human-readable reset time.

    Same day:  "Resets in 2h 20m (14:30)"
    Tomorrow:  "Resets tomorrow, 12:00"
    Later:     "Resets Sat., 12:00"
    """
    try:
        reset = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        diff = reset - now

        total_min = max(0, int(diff.total_seconds() / 60))
        if total_min == 0:
            return ''

        reset_local = reset.astimezone()
        today = datetime.now().date()
        if reset_local.second >= 30:
            reset_local = reset_local.replace(second=0) + timedelta(minutes=1)
        else:
            reset_local = reset_local.replace(second=0)
        reset_date = reset_local.date()
        time_str = reset_local.strftime('%H:%M')

        if reset_date == today:
            if total_min >= 60:
                duration = T['duration_hm'].format(h=total_min // 60, m=total_min % 60)
            else:
                duration = T['duration_m'].format(m=total_min)
            return T['resets_in'].format(duration=duration, clock=time_str)

        if reset_date == today + timedelta(days=1):
            return T['resets_tomorrow'].format(clock=time_str)

        wd = T['weekdays'][reset_local.weekday()]
        return T['resets_weekday'].format(day=wd, clock=time_str)
    except Exception:
        return ''


def format_credits(cents: float) -> str:
    """Format a cent amount as a localized currency string.

    Uses the system locale for formatting (decimal separator, symbol placement,
    grouping).  If the user overrides ``currency_symbol`` in settings, the
    system symbol is replaced in the formatted output.

    Parameters
    ----------
    cents : float
        Amount in cents (e.g. 420.0 for 4.20 in the base currency unit).
    """
    amount = cents / 100

    try:
        formatted = _locale.currency(amount, grouping=True)

        if CURRENCY_SYMBOL != _SYSTEM_CURRENCY_SYMBOL and _SYSTEM_CURRENCY_SYMBOL:
            formatted = formatted.replace(_SYSTEM_CURRENCY_SYMBOL, CURRENCY_SYMBOL)

        return formatted
    except (ValueError, _locale.Error):
        if CURRENCY_SYMBOL:
            return f'{CURRENCY_SYMBOL}\u00a0{amount:.2f}'
        return f'{amount:.2f}'


def format_status(last_success_time: float | None, refreshing: bool, last_error: str | None) -> tuple[str, bool]:
    """Format the popup status line showing data freshness and current state.

    Parameters
    ----------
    last_success_time : float or None
        Unix timestamp of the last successful API response.
    refreshing : bool
        Whether an API call is currently in progress.
    last_error : str or None
        Error message from the most recent failed API call.

    Returns
    -------
    tuple[str, bool]
        ``(text, has_error)`` where *text* is the full status string
        and *has_error* indicates the text ends with an error message
        (so the caller can color it differently).
    """
    parts: list[str] = []

    if last_success_time is not None:
        seconds_ago = time.time() - last_success_time
        if seconds_ago < 60:
            parts.append(T['status_updated_now'])
        else:
            total_min = int(seconds_ago // 60)
            hours = total_min // 60
            mins = total_min % 60
            if hours > 0:
                duration = T['duration_hm'].format(h=hours, m=mins)
            else:
                duration = T['duration_m'].format(m=total_min)
            parts.append(T['status_updated'].format(duration=duration))

    if refreshing:
        parts.append(T['status_refreshing'])
        return (' \u00b7 '.join(parts), False)

    if last_error:
        parts.append(last_error)
        return (' \u00b7 '.join(parts), True)

    return (' \u00b7 '.join(parts), False)


def format_tooltip(data: dict[str, Any]) -> str:
    """Format usage data as short tooltip text."""
    if 'error' in data:
        if data.get('auth_error'):
            return f"{T['auth_expired_label']}\n{T['auth_expired_short']}"
        return f"{T['error_label']}\n{data['error'][:80]}"

    lines = [T['title']]
    for key, short in [('five_hour', '5h'), ('seven_day', '7d')]:
        entry = data.get(key)
        if entry and entry.get('utilization') is not None:
            pct = f"{entry['utilization']:.0f}%"
            reset = time_until(entry.get('resets_at', ''))
            line = f'{short}: {pct}'
            if reset:
                line += f' ({reset})'
            lines.append(line)

    return '\n'.join(lines)

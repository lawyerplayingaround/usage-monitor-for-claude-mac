"""
Settings
=========

Centralizes all user-tunable constants.  Structural constants (API URLs,
registry keys, file paths) remain in their respective modules.

Loads an optional ``usage-monitor-settings.json`` to let users override
any constant.  Search order:

1. Next to the executable (frozen) or project root (source)
2. ``~/.claude/usage-monitor-settings.json``

The app never creates this file — users place it manually.
"""
from __future__ import annotations

import ctypes
import json
import locale as _locale
import sys
from pathlib import Path

SETTINGS_FILENAME = 'usage-monitor-settings.json'

_NUMERIC_KEYS = frozenset({'poll_interval', 'poll_fast', 'poll_fast_extra', 'poll_error', 'max_backoff'})
_COLOR_KEYS = frozenset({'bg', 'fg', 'fg_dim', 'fg_heading', 'bar_bg', 'bar_fg', 'bar_fg_high'})
_ICON_KEYS = frozenset({'icon_light', 'icon_dark'})
_THRESHOLD_KEYS = frozenset({'alert_thresholds_five_hour', 'alert_thresholds_seven_day'})
_PERCENT_KEYS = frozenset({'alert_time_aware_below'})
_STRING_KEYS = frozenset({'currency_symbol'})
_BOOL_KEYS = frozenset({'alert_time_aware'})


def _load_settings() -> dict:
    """Read the first ``usage-monitor-settings.json`` found, or return ``{}``."""
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).parent
    else:
        app_dir = Path(__file__).resolve().parent.parent

    for path in (app_dir / SETTINGS_FILENAME, Path.home() / '.claude' / SETTINGS_FILENAME):
        if path.is_file():
            try:
                text = path.read_text(encoding='utf-8').strip()
                if not text:
                    return {}
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError(f'Expected a JSON object, got {type(data).__name__}')
                return _validate(data, path)
            except (json.JSONDecodeError, ValueError) as exc:
                ctypes.windll.user32.MessageBoxW(
                    0, f'Invalid JSON in settings file:\n{path}\n\n{exc}',
                    'Usage Monitor for Claude - Settings Error', 0x30,
                )
                return {}
            except OSError:
                return {}

    return {}


def _valid_rgba(value: object) -> bool:
    """Return True if *value* is a list of exactly 4 integers in 0\u2013255."""
    return (
        isinstance(value, list) and len(value) == 4
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)
    )


def _validate(data: dict, path: Path) -> dict:
    """Drop entries with invalid types or values and show a MessageBox listing errors."""
    errors: list[str] = []
    drop: list[str] = []

    for key, value in data.items():
        if key in _NUMERIC_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f'  {key}: expected a number, got {type(value).__name__}')
                drop.append(key)
            elif value <= 0:
                errors.append(f'  {key}: must be > 0, got {value}')
                drop.append(key)

        elif key in _COLOR_KEYS:
            if not isinstance(value, str):
                errors.append(f'  {key}: expected a color string, got {type(value).__name__}')
                drop.append(key)

        elif key in _THRESHOLD_KEYS:
            if not isinstance(value, list):
                errors.append(f'  {key}: expected an array, got {type(value).__name__}')
                drop.append(key)
            else:
                bad = [v for v in value if isinstance(v, bool) or not isinstance(v, (int, float)) or not (1 <= v <= 100)]
                if bad:
                    errors.append(f'  {key}: all values must be numbers between 1 and 100')
                    drop.append(key)
                else:
                    data[key] = sorted(set(value))

        elif key in _PERCENT_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f'  {key}: expected a number, got {type(value).__name__}')
                drop.append(key)
            elif not (1 <= value <= 100):
                errors.append(f'  {key}: must be between 1 and 100, got {value}')
                drop.append(key)

        elif key in _STRING_KEYS:
            if not isinstance(value, str):
                errors.append(f'  {key}: expected a string, got {type(value).__name__}')
                drop.append(key)

        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                errors.append(f'  {key}: expected true or false, got {type(value).__name__}')
                drop.append(key)

        elif key in _ICON_KEYS:
            if not isinstance(value, dict):
                errors.append(f'  {key}: expected an object, got {type(value).__name__}')
                drop.append(key)
            else:
                bad = [k for k, v in value.items() if not _valid_rgba(v)]
                for k in bad:
                    errors.append(f'  {key}.{k}: expected [R, G, B, A] with integers 0\u2013255')
                    del value[k]

    for key in drop:
        del data[key]

    if errors:
        ctypes.windll.user32.MessageBoxW(
            0, f'Invalid values in settings file:\n{path}\n\n' + '\n'.join(errors),
            'Usage Monitor for Claude - Settings Error', 0x30,
        )

    return data


def _icon_colors(key: str, defaults: dict[str, tuple]) -> dict[str, tuple]:
    """Merge icon color overrides from settings, converting JSON arrays to tuples."""
    overrides = _S.get(key, {})
    return {k: tuple(overrides[k]) if k in overrides else v for k, v in defaults.items()}


_S = _load_settings()

# ── Polling intervals (seconds) ───────────────────────────────
POLL_INTERVAL = _S.get('poll_interval', 120)
POLL_FAST = _S.get('poll_fast', 60)
POLL_FAST_EXTRA = _S.get('poll_fast_extra', 2)
POLL_ERROR = _S.get('poll_error', 30)
MAX_BACKOFF = _S.get('max_backoff', 900)

# ── Popup theme ───────────────────────────────────────────────
BG = _S.get('bg', '#1e1e1e')
FG = _S.get('fg', '#cccccc')
FG_DIM = _S.get('fg_dim', '#888888')
FG_HEADING = _S.get('fg_heading', '#ffffff')
BAR_BG = _S.get('bar_bg', '#333333')
BAR_FG = _S.get('bar_fg', '#4a9eff')
BAR_FG_HIGH = _S.get('bar_fg_high', '#e05050')

# ── Tray icon colors ─────────────────────────────────────────
ICON_LIGHT = _icon_colors('icon_light', {
    'fg': (255, 255, 255, 255),
    'fg_half': (255, 255, 255, 80),
    'fg_dim': (255, 255, 255, 140),
})
ICON_DARK = _icon_colors('icon_dark', {
    'fg': (0, 0, 0, 255),
    'fg_half': (0, 0, 0, 80),
    'fg_dim': (0, 0, 0, 140),
})

# ── Alert thresholds ────────────────────────────────────────
ALERT_THRESHOLDS_FIVE_HOUR: list[float] = _S.get('alert_thresholds_five_hour', [50, 80, 95])
ALERT_THRESHOLDS_SEVEN_DAY: list[float] = _S.get('alert_thresholds_seven_day', [95])
ALERT_TIME_AWARE: bool = _S.get('alert_time_aware', True)
ALERT_TIME_AWARE_BELOW: float = _S.get('alert_time_aware_below', 90)

# ── Currency ───────────────────────────────────────────────

def _detect_currency_symbol() -> str:
    """Detect the system locale currency symbol for monetary formatting."""
    try:
        _locale.setlocale(_locale.LC_MONETARY, '')
        return _locale.localeconv().get('currency_symbol', '') or ''
    except _locale.Error:
        return ''


_SYSTEM_CURRENCY_SYMBOL = _detect_currency_symbol()
CURRENCY_SYMBOL: str = _S.get('currency_symbol', _SYSTEM_CURRENCY_SYMBOL)

_ALERT_THRESHOLDS = {
    'five_hour': ALERT_THRESHOLDS_FIVE_HOUR,
    'seven_day': ALERT_THRESHOLDS_SEVEN_DAY,
    'seven_day_sonnet': ALERT_THRESHOLDS_SEVEN_DAY,
    'seven_day_opus': ALERT_THRESHOLDS_SEVEN_DAY,
}


def get_alert_thresholds(variant_key: str) -> list[float]:
    """Return the alert thresholds for a usage variant.

    Session (5h) and weekly (7d) quotas use separate threshold lists.
    All weekly variants (general, Sonnet, Opus) share the same thresholds.
    An empty list means alerts are disabled.

    Parameters
    ----------
    variant_key : str
        API variant key, e.g. ``'five_hour'`` or ``'seven_day_sonnet'``.
    """
    return _ALERT_THRESHOLDS.get(variant_key, [])

"""
Tray Icon
==========

Creates system tray icons and detects the host taskbar/menu bar theme.
"""
from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from typing import Callable

if sys.platform == 'win32':
    import ctypes
    import winreg

from PIL import Image, ImageDraw, ImageFont

from .settings import ICON_DARK, ICON_LIGHT

__all__ = ['load_font', 'taskbar_uses_light_theme', 'watch_theme_change', 'create_icon_image', 'create_status_image']

# Windows theme registry
THEME_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
THEME_REG_VALUE = 'SystemUsesLightTheme'
REG_NOTIFY_CHANGE_LAST_SET = 0x00000004

# macOS theme detection
_MACOS_DEFAULTS_BIN = '/usr/bin/defaults'
_MACOS_THEME_POLL_SECONDS = 5.0

TRANSPARENT = (0, 0, 0, 0)

# Icon layout names (mirror usage_monitor_for_claude.preferences).
ICON_LAYOUT_CLASSIC = 'classic'
ICON_LAYOUT_COMPACT = 'compact'

# Icon canvas metrics - tuned per platform.  The Mac menu bar gives the icon
# only ~22 logical points of height, so the number font is enlarged and the
# bars thickened to survive the LANCZOS downsample applied by pystray.  Two
# layouts are selectable from the tray menu: 'classic' (two bars - session over
# weekly, smaller glyph) and 'compact' (a single session bar with a large
# percentage glyph; the weekly quota is shown in the popup).  ``_FONT_NUM`` is
# keyed by layout; the other metrics are shared by both layouts on a platform.
if sys.platform == 'darwin':
    # SF Pro Semibold matches the look of the macOS system clock in the menu bar
    # while remaining bold enough to read against busy wallpapers.
    _WEIGHT = 'Semibold'
    _CENTER_TEXT = True
    _BAR_H = 8
    _BAR_GAP = 2
    _FONT_LETTER = 34
    _FONT_SYMBOL = 30
    _STATUS_FONT = 40
    _FONT_NUM = {ICON_LAYOUT_COMPACT: 46, ICON_LAYOUT_CLASSIC: 32}
else:
    _WEIGHT = None
    _CENTER_TEXT = False
    _BAR_H = 9
    _BAR_GAP = 3
    _FONT_LETTER = 42
    _FONT_SYMBOL = 36
    _STATUS_FONT = 46
    _FONT_NUM = {ICON_LAYOUT_COMPACT: 58, ICON_LAYOUT_CLASSIC: 40}

# Icon canvas and bar geometry (pixels)
ICON_SIZE = 64
BAR_HEIGHT = _BAR_H
BAR_GAP = _BAR_GAP
MARKER_WIDTH = 4


@functools.lru_cache(maxsize=None)
def load_font(size: int, symbol: bool = False, weight: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load font at given size. Use symbol=True for Unicode glyphs not in Arial.

    Parameters
    ----------
    size : int
        Font size in points.
    symbol : bool
        If True, load a font with broad Unicode symbol coverage.
    weight : str or None
        Named weight to apply to variable fonts (e.g. SFNS on macOS).  Accepted
        values include ``'Regular'``, ``'Medium'``, ``'Semibold'``, ``'Bold'``.
        Ignored on platforms whose fonts do not expose a named variation axis.
    """
    if sys.platform == 'darwin':
        if symbol:
            names = (
                '/System/Library/Fonts/Apple Symbols.ttf',
                '/System/Library/Fonts/Symbol.ttf',
                '/System/Library/Fonts/SFNS.ttf',
            )
        else:
            names = (
                '/System/Library/Fonts/SFNS.ttf',
                '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
                '/System/Library/Fonts/HelveticaNeue.ttc',
            )
    else:
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        if symbol:
            names = (f'{windir}\\Fonts\\seguisym.ttf', 'seguisym.ttf')
        else:
            names = (f'{windir}\\Fonts\\arialbd.ttf', 'arialbd.ttf', f'{windir}\\Fonts\\arial.ttf', 'arial.ttf')

    for name in names:
        try:
            font = ImageFont.truetype(name, size)
        except OSError:
            continue
        if weight and 'SFNS' in name:
            try:
                font.set_variation_by_name(weight)
            except (AttributeError, OSError):
                pass
        return font

    return ImageFont.load_default()


def taskbar_uses_light_theme() -> bool:
    """Return True if the host taskbar/menu bar uses the light theme.

    On Windows, reads ``SystemUsesLightTheme`` from the Personalize registry key.
    On macOS, checks ``AppleInterfaceStyle`` via ``defaults``.
    Returns False (dark) when the value cannot be read.
    """
    if sys.platform == 'darwin':
        return _macos_menu_bar_uses_light_theme()

    if sys.platform != 'win32':
        return False

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, THEME_REG_VALUE)
            return bool(value)
    except OSError:
        return False


def watch_theme_change(callback: Callable[[], None]) -> None:
    """Block the current thread and call *callback* whenever the host theme changes.

    On Windows, uses ``RegNotifyChangeKeyValue`` to sleep until the registry key
    is modified.  On macOS, polls ``AppleInterfaceStyle`` at a low frequency.
    Designed to run in a daemon thread.
    """
    if sys.platform == 'darwin':
        _watch_macos_theme_change(callback)
        return

    if sys.platform != 'win32':
        return

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_REG_KEY, 0, winreg.KEY_READ) as key:
        while True:
            if ctypes.windll.advapi32.RegNotifyChangeKeyValue(int(key), False, REG_NOTIFY_CHANGE_LAST_SET, None, False) != 0:
                return
            try:
                callback()
            except Exception:
                # A transient callback failure (icon re-render, Shell_NotifyIcon
                # during an Explorer restart) must not end theme watching for
                # the rest of the session.
                pass


def _macos_menu_bar_uses_light_theme() -> bool:
    """Return True when the macOS menu bar currently uses the light theme.

    ``defaults read -g AppleInterfaceStyle`` prints ``Dark`` in dark mode and
    exits non-zero with empty output in light mode (the default state, in
    which the preference is not stored).
    """
    try:
        result = subprocess.run(
            [_MACOS_DEFAULTS_BIN, 'read', '-g', 'AppleInterfaceStyle'],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True

    return result.stdout.strip() != 'Dark'


def _watch_macos_theme_change(callback: Callable[[], None]) -> None:
    """Poll the macOS appearance and fire *callback* whenever it changes."""
    last = _macos_menu_bar_uses_light_theme()
    while True:
        time.sleep(_MACOS_THEME_POLL_SECONDS)
        current = _macos_menu_bar_uses_light_theme()
        if current != last:
            last = current
            try:
                callback()
            except Exception:
                # A transient callback failure (icon re-render) must not end
                # theme watching for the rest of the session.
                pass


def create_icon_image(
    pct_top: float, pct_bottom: float, light_taskbar: bool = False,
    *, mode_top: str = 'utilization', mode_bottom: str = 'utilization',
    time_pct_top: float | None = None, time_pct_bottom: float | None = None,
    extra_usage_available: bool = False, layout: str = ICON_LAYOUT_CLASSIC,
) -> Image.Image:
    """Create tray icon: a glyph (percentage / 'C' / '$' / '✕') over the
    usage bar(s).

    The *layout* selects ``'classic'`` (two bars - session over weekly) or
    ``'compact'`` (a single session bar with a large glyph).

    Parameters
    ----------
    pct_top : float
        Utilization percentage (0-100) for the upper bar.
    pct_bottom : float
        Utilization percentage (0-100) for the lower bar.
    light_taskbar : bool
        Use dark-on-light colors for a light taskbar.
    mode_top : str
        Display mode for the upper bar: ``'utilization'`` (linear fill)
        or ``'overage'`` (fills as usage exceeds the time marker).
    mode_bottom : str
        Display mode for the lower bar.  Same semantics as *mode_top*.
    time_pct_top : float or None
        Elapsed-time percentage for the upper bar.  Draws the reset-time
        marker in ``utilization`` mode; required for ``overage`` mode.
    time_pct_bottom : float or None
        Elapsed-time percentage for the lower bar.  Same semantics as
        *time_pct_top*.
    extra_usage_available : bool
        True if the account has paid extra-usage credits still available.
        When a quota is fully exhausted, this decides whether to show ``$``
        (continuing costs money) or ``✕`` (fully blocked).
    """
    colors = ICON_DARK if light_taskbar else ICON_LIGHT
    fg, fg_half, fg_warn = colors['fg'], colors['fg_half'], colors['fg_warn']

    S = ICON_SIZE
    img = Image.new('RGBA', (S, S), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    # Top glyph: "✕" when any quota exhausted and no extra credits left,
    # "$" when exhausted but paid extra-usage still available,
    # "C" while usage is still zero, otherwise the percentage.
    stroke_width = 0
    any_exhausted = pct_top >= 100 or pct_bottom >= 100
    if any_exhausted and not extra_usage_available:
        text, font_size, symbol_glyph = '\u2715', _FONT_SYMBOL, True
        stroke_width = 2
    elif any_exhausted:
        text, font_size, symbol_glyph = '$', _FONT_LETTER, False
        stroke_width = 2
    elif pct_top > 0:
        # Clamp to 99: values in [99.5, 100) would round to a three-digit
        # '100' that overflows the canvas and reads as exhausted.
        text, font_size, symbol_glyph = f'{min(pct_top, 99):.0f}', _FONT_NUM[layout], False
    else:
        text, font_size, symbol_glyph = 'C', _FONT_LETTER, False

    font_kwargs: dict[str, bool | str] = {}
    if symbol_glyph:
        font_kwargs['symbol'] = True
    if _WEIGHT:
        font_kwargs['weight'] = _WEIGHT
    font = load_font(font_size, **font_kwargs)

    # Shrink the glyph to fit the canvas width.  At the large compact digit
    # size a wide two-digit percentage would otherwise overflow the 64 px
    # canvas and clip.
    fit_bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    fit_w = fit_bbox[2] - fit_bbox[0]
    if fit_w > S - 2:
        font = load_font(max(1, font_size * (S - 2) // fit_w), **font_kwargs)

    # Progress bar(s) - full width, flush to bottom.  The compact layout mirrors
    # the minimalist macOS menu bar look: a single session bar (pct_top) with a
    # large glyph above it; the weekly quota lives in the on-click popup.  The
    # classic layout keeps the original two-bar stack (session above weekly).
    if layout == ICON_LAYOUT_COMPACT:
        bar_top_y = S - BAR_HEIGHT
        bars = ((bar_top_y, pct_top, mode_top, time_pct_top),)
        text_area_h = bar_top_y
    else:
        bar2_y = S - BAR_HEIGHT
        bar1_y = bar2_y - BAR_GAP - BAR_HEIGHT
        bars = (
            (bar1_y, pct_top, mode_top, time_pct_top),
            (bar2_y, pct_bottom, mode_bottom, time_pct_bottom),
        )
        text_area_h = bar1_y

    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    tw = bbox[2] - bbox[0]
    if _CENTER_TEXT:
        # Vertically center the glyph in the area above the bar(s), biased a few
        # px upward for separation from the bar (aids legibility once the menu
        # bar downsamples the icon).
        text_y = (text_area_h - (bbox[3] - bbox[1])) / 2 - bbox[1] - 3
    else:
        text_y = -bbox[1]
    draw.text(((S - tw) / 2 - bbox[0], text_y), text, fill=fg, font=font, stroke_width=stroke_width, stroke_fill=fg)

    for y, pct, mode, time_pct in bars:
        _draw_usage_bar(draw, y, pct, mode, time_pct, fg, fg_half, fg_warn)

    return img


def _draw_usage_bar(draw: ImageDraw.ImageDraw, y: int, pct: float, mode: str, time_pct: float | None, fg: tuple, fg_half: tuple, fg_warn: tuple) -> None:
    """Draw one full-width usage bar at vertical offset *y*.

    In ``utilization`` mode the bar fills linearly with *pct* and shows a
    reset-time marker in *fg* at the *time_pct* position; the fill switches
    to *fg_warn* when usage is ahead of the elapsed time or fully exhausted,
    mirroring the popup's warning fill.  In ``overage`` mode the bar fills
    as *pct* exceeds *time_pct* and no marker is drawn - elapsed time is
    already encoded in the fill.
    """
    draw.rectangle([0, y, ICON_SIZE - 1, y + BAR_HEIGHT - 1], fill=fg_half)

    if mode == 'overage' and time_pct is not None:
        if time_pct >= 100:
            # End state for a stale window (elapsed time clamped to 100%,
            # e.g. between a reset and the confirming poll): usage below the
            # limit stayed within budget (empty bar), an exhausted quota
            # keeps the bar full - never the linear utilization fill.
            if pct >= 100:
                draw.rectangle([0, y, ICON_SIZE - 1, y + BAR_HEIGHT - 1], fill=fg)
            return

        overage = max(0.0, pct - time_pct)
        fill_ratio = min(1.0, overage / (100 - time_pct))
        fill_w = max(0, int(ICON_SIZE * fill_ratio))
        if fill_w > 0:
            draw.rectangle([0, y, fill_w - 1, y + BAR_HEIGHT - 1], fill=fg)
        return

    fill_w = max(0, min(ICON_SIZE, int(ICON_SIZE * pct / 100)))
    if fill_w > 0:
        warn = mode == 'utilization' and (pct >= 100 or (time_pct is not None and pct > time_pct))
        draw.rectangle([0, y, fill_w - 1, y + BAR_HEIGHT - 1], fill=fg_warn if warn else fg)

    if mode != 'utilization' or time_pct is None:
        return

    marker_x = min(ICON_SIZE - MARKER_WIDTH, max(0, int(ICON_SIZE * time_pct / 100) - MARKER_WIDTH // 2))
    marker_end = marker_x + MARKER_WIDTH - 1
    draw.rectangle([marker_x, y, marker_end, y + BAR_HEIGHT - 1], fill=fg)


def create_status_image(text: str, light_taskbar: bool = False) -> Image.Image:
    """Create monochrome centered-text icon for error/status states."""
    fg_dim = (ICON_DARK if light_taskbar else ICON_LIGHT)['fg_dim']

    S = 64
    img = Image.new('RGBA', (S, S), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    font = load_font(_STATUS_FONT, weight=_WEIGHT) if _WEIGHT else load_font(_STATUS_FONT)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1]), text, fill=fg_dim, font=font)

    return img

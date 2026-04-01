"""
Tray Icon
==========

Creates monochrome system tray icons and detects the Windows taskbar theme.
"""
from __future__ import annotations

import ctypes
import functools
import os
import winreg
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .settings import ICON_DARK, ICON_LIGHT

__all__ = ['load_font', 'taskbar_uses_light_theme', 'watch_theme_change', 'create_icon_image', 'create_status_image']

# Theme registry
THEME_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
THEME_REG_VALUE = 'SystemUsesLightTheme'
REG_NOTIFY_CHANGE_LAST_SET = 0x00000004

TRANSPARENT = (0, 0, 0, 0)


@functools.lru_cache(maxsize=None)
def load_font(size: int, symbol: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load font at given size. Use symbol=True for Unicode glyphs not in Arial."""
    windir = os.environ.get('WINDIR', 'C:\\Windows')
    if symbol:
        names = (f'{windir}\\Fonts\\seguisym.ttf', 'seguisym.ttf')
    else:
        names = (f'{windir}\\Fonts\\arialbd.ttf', 'arialbd.ttf', f'{windir}\\Fonts\\arial.ttf', 'arial.ttf')
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    return ImageFont.load_default()


def taskbar_uses_light_theme() -> bool:
    """Return True if the Windows taskbar uses the light theme.

    Reads ``SystemUsesLightTheme`` from the Personalize registry key.
    Returns False (dark) if the value cannot be read.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, THEME_REG_VALUE)
            return bool(value)
    except OSError:
        return False


def watch_theme_change(callback: Callable[[], None]) -> None:
    """Block the current thread and call *callback* whenever the taskbar theme changes.

    Uses ``RegNotifyChangeKeyValue`` to sleep until the registry key
    is modified, avoiding any polling.  Designed to run in a daemon thread.
    """
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_REG_KEY, 0, winreg.KEY_READ) as key:
        while True:
            if ctypes.windll.advapi32.RegNotifyChangeKeyValue(int(key), False, REG_NOTIFY_CHANGE_LAST_SET, None, False) != 0:
                return
            callback()


def create_icon_image(
    pct_top: float, pct_bottom: float, light_taskbar: bool = False,
    *, time_pct_top: float | None = None, time_pct_bottom: float | None = None,
) -> Image.Image:
    """Create monochrome tray icon: 'C' letter + two usage bars.

    Parameters
    ----------
    pct_top : float
        Utilization percentage (0-100) for the upper bar.
    pct_bottom : float
        Utilization percentage (0-100) for the lower bar.
    light_taskbar : bool
        Use dark-on-light colors for a light taskbar.
    time_pct_top : float or None
        Elapsed-time percentage for the upper bar.  When provided, the bar
        renders in ``overage`` mode: empty when usage is at or below the
        elapsed-time percentage (on pace or ahead), filling left-to-right
        as usage climbs toward 100%.
    time_pct_bottom : float or None
        Elapsed-time percentage for the lower bar.  Same semantics as
        *time_pct_top*.
    """
    colors = ICON_DARK if light_taskbar else ICON_LIGHT
    fg, fg_half = colors['fg'], colors['fg_half']

    S = 64
    img = Image.new('RGBA', (S, S), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    # Top text: "C", percentage when usage > 50%, or "✕" at 100%
    stroke_width = 0
    if pct_top >= 100:
        text, font = '\u2715', load_font(36, symbol=True)
        stroke_width = 2
    elif pct_top > 50:
        text, font = f'{pct_top:.0f}', load_font(40)
    else:
        text, font = 'C', load_font(42)

    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    tw = bbox[2] - bbox[0]
    draw.text(((S - tw) / 2 - bbox[0], -bbox[1]), text, fill=fg, font=font, stroke_width=stroke_width, stroke_fill=fg)

    # Progress bars - full width, flush to bottom
    bar_h = 9
    gap = 3
    bar2_y = S - bar_h
    bar1_y = bar2_y - gap - bar_h

    for y, pct, time_pct in ((bar1_y, pct_top, time_pct_top), (bar2_y, pct_bottom, time_pct_bottom)):
        draw.rectangle([0, y, S - 1, y + bar_h - 1], fill=fg_half)
        if time_pct is not None and time_pct < 100:
            overage = max(0.0, pct - time_pct)
            fill_ratio = min(1.0, overage / (100 - time_pct))
            fill_w = max(0, int(S * fill_ratio))
            if fill_w > 0:
                draw.rectangle([0, y, fill_w - 1, y + bar_h - 1], fill=fg)
        else:
            fill_w = max(0, min(S, int(S * pct / 100)))
            if fill_w > 0:
                draw.rectangle([0, y, fill_w - 1, y + bar_h - 1], fill=fg)

    return img


def create_status_image(text: str, light_taskbar: bool = False) -> Image.Image:
    """Create monochrome centered-text icon for error/status states."""
    fg_dim = (ICON_DARK if light_taskbar else ICON_LIGHT)['fg_dim']

    S = 64
    img = Image.new('RGBA', (S, S), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    font = load_font(46)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1]), text, fill=fg_dim, font=font)

    return img

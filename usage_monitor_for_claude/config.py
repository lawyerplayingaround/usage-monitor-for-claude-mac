"""
Configuration
===============

Centralizes all user-tunable constants.  Structural constants (API URLs,
registry keys, file paths) remain in their respective modules.
"""
from __future__ import annotations

# ── Polling intervals (seconds) ───────────────────────────────
POLL_INTERVAL = 120  # Default interval between API updates
POLL_FAST = 60  # Interval when usage is actively increasing
POLL_FAST_EXTRA = 2  # Extra fast polls after usage stops increasing
POLL_ERROR = 30  # Interval after a failed request

# ── Popup theme ───────────────────────────────────────────────
BG = '#1e1e1e'
FG = '#cccccc'
FG_DIM = '#888888'
FG_HEADING = '#ffffff'
BAR_BG = '#333333'
BAR_FG = '#4a9eff'
BAR_FG_HIGH = '#e05050'

# ── Tray icon colors ─────────────────────────────────────────
ICON_LIGHT = {  # Light icons for dark taskbar (default)
    'fg': (255, 255, 255, 255),
    'fg_half': (255, 255, 255, 80),
    'fg_dim': (255, 255, 255, 140),
}
ICON_DARK = {  # Dark icons for light taskbar
    'fg': (0, 0, 0, 255),
    'fg_half': (0, 0, 0, 80),
    'fg_dim': (0, 0, 0, 140),
}

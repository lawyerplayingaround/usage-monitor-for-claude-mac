"""
Autostart
==========

Manages autostart entries for the app.  On Windows this uses the
``HKCU\\...\\Run`` registry key; on macOS, a LaunchAgent plist under
``~/Library/LaunchAgents`` (implemented in a later phase - currently
a no-op stub on non-Windows platforms).
"""
from __future__ import annotations

import sys

__all__ = ['AUTOSTART_REG_KEY', 'AUTOSTART_REG_NAME', 'is_autostart_enabled', 'set_autostart', 'sync_autostart_path']

AUTOSTART_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART_REG_NAME = 'UsageMonitorForClaude'


if sys.platform == 'win32':
    import winreg

    def is_autostart_enabled() -> bool:
        """Check whether the app is registered to start with Windows."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
                winreg.QueryValueEx(key, AUTOSTART_REG_NAME)
                return True
        except FileNotFoundError:
            return False

    def set_autostart(enable: bool) -> None:
        """Create or remove the autostart registry entry."""
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, AUTOSTART_REG_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_REG_NAME)
                except FileNotFoundError:
                    pass

    def sync_autostart_path() -> None:
        """Update the autostart registry path if the EXE has been moved."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
                stored, _ = winreg.QueryValueEx(key, AUTOSTART_REG_NAME)
        except FileNotFoundError:
            return

        expected = f'"{sys.executable}"'
        if stored != expected:
            set_autostart(True)

else:
    def is_autostart_enabled() -> bool:
        """Autostart is not yet implemented on this platform."""
        return False

    def set_autostart(enable: bool) -> None:
        """Autostart is not yet implemented on this platform."""

    def sync_autostart_path() -> None:
        """Autostart is not yet implemented on this platform."""

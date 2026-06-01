"""
Autostart
==========

Manages autostart entries for the app.  On Windows this uses the
``HKCU\\...\\Run`` registry key.  On macOS, a ``LaunchAgent`` plist under
``~/Library/LaunchAgents``; ``launchd`` picks it up automatically at the
user's next login session.

The macOS plist write is the same kind of side effect as the Windows
registry entry: triggered only by explicit user toggle, points at a
well-known label, contains no credentials and no user data.  It complies
with the project's "no surprise writes" stance for the same reason the
Windows version does.
"""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = [
    'AUTOSTART_REG_KEY', 'AUTOSTART_REG_NAME',
    'LAUNCH_AGENT_LABEL', 'LAUNCH_AGENT_PATH',
    'is_autostart_enabled', 'set_autostart', 'sync_autostart_path',
]

AUTOSTART_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART_REG_NAME = 'UsageMonitorForClaude'

LAUNCH_AGENT_LABEL = 'com.usage-monitor-for-claude'
LAUNCH_AGENT_PATH = Path.home() / 'Library' / 'LaunchAgents' / f'{LAUNCH_AGENT_LABEL}.plist'


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

elif sys.platform == 'darwin':
    def _xml_escape(text: str) -> str:
        """Escape the three XML-significant chars in element text content.

        Inlined to avoid pulling ``xml.sax.saxutils`` into the PyInstaller
        bundle just for this single call.
        """
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def _build_plist(executable_path: str) -> str:
        """Build the LaunchAgent plist XML pointing at *executable_path*.

        Uses a small static template (no dynamic key names, no user data)
        so the on-disk file is fully auditable at a glance.
        """
        safe_path = _xml_escape(executable_path)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            f'    <key>Label</key>            <string>{LAUNCH_AGENT_LABEL}</string>\n'
            '    <key>ProgramArguments</key>\n'
            f'    <array><string>{safe_path}</string></array>\n'
            '    <key>RunAtLoad</key>        <true/>\n'
            '    <key>KeepAlive</key>        <false/>\n'
            '    <key>ProcessType</key>      <string>Interactive</string>\n'
            # Associate the agent with the app bundle (the label equals the
            # CFBundleIdentifier) so macOS shows the app's name + icon in the
            # Login Items / background-items list instead of a generic binary.
            f'    <key>AssociatedBundleIdentifiers</key> <string>{LAUNCH_AGENT_LABEL}</string>\n'
            '</dict>\n'
            '</plist>\n'
        )

    def is_autostart_enabled() -> bool:
        """Check whether the LaunchAgent plist exists in the user's LaunchAgents folder."""
        return LAUNCH_AGENT_PATH.is_file()

    def set_autostart(enable: bool) -> None:
        """Create or remove the LaunchAgent plist.

        macOS scans ``~/Library/LaunchAgents`` at every login and starts
        ``RunAtLoad=true`` agents automatically, so just writing/deleting
        the file is enough - no ``launchctl bootstrap`` call needed and
        the app is not double-launched while the user toggles the menu.
        """
        if enable:
            LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            LAUNCH_AGENT_PATH.write_text(_build_plist(sys.executable), encoding='utf-8')
        else:
            try:
                LAUNCH_AGENT_PATH.unlink()
            except FileNotFoundError:
                pass

    def sync_autostart_path() -> None:
        """Rewrite the plist if the executable path no longer matches.

        Mirrors the Windows ``sync_autostart_path`` semantics: when the
        user drags ``UsageMonitorForClaude.app`` to a new location and
        relaunches, the next startup heals the stale autostart entry.
        """
        if not LAUNCH_AGENT_PATH.is_file():
            return

        expected = _build_plist(sys.executable)
        try:
            current = LAUNCH_AGENT_PATH.read_text(encoding='utf-8')
        except OSError:
            return

        if current != expected:
            set_autostart(True)

else:
    def is_autostart_enabled() -> bool:
        """Autostart is not implemented on this platform."""
        return False

    def set_autostart(enable: bool) -> None:
        """Autostart is not implemented on this platform."""

    def sync_autostart_path() -> None:
        """Autostart is not implemented on this platform."""

"""
Autostart
==========

Manages autostart entries for the app.  On Windows this uses the
``HKCU\\...\\Run`` registry key.  On macOS, a ``LaunchAgent`` plist under
``~/Library/LaunchAgents``; ``launchd`` picks it up automatically at the
user's next login session.  Each monitor instance (one per Claude config
directory) uses its own registry value name / plist label and stores its
``--config-dir`` in the launch command.

The macOS plist write is the same kind of side effect as the Windows
registry entry: triggered only by explicit user toggle, points at a
well-known label, contains no credentials and no user data.  It complies
with the project's "no surprise writes" stance for the same reason the
Windows version does.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .instance_id import config_dir_suffix, effective_config_dir, is_default_config_dir

__all__ = [
    'AUTOSTART_REG_KEY', 'AUTOSTART_REG_BASE_NAME',
    'LAUNCH_AGENT_BASE_LABEL',
    'is_autostart_enabled', 'set_autostart', 'sync_autostart_path',
]

AUTOSTART_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART_REG_BASE_NAME = 'UsageMonitorForClaude'

LAUNCH_AGENT_BASE_LABEL = 'com.usage-monitor-for-claude'


if sys.platform == 'win32':
    import winreg

    def _autostart_reg_name() -> str:
        """Return the per-instance registry value name."""
        return AUTOSTART_REG_BASE_NAME + config_dir_suffix()

    def _autostart_command() -> str:
        """Return the command line to store in the registry for this instance."""
        command = f'"{sys.executable}"'
        if not is_default_config_dir():
            command += f' --config-dir="{effective_config_dir()}"'
        return command

    def is_autostart_enabled() -> bool:
        """Check whether the app is registered to start with Windows.

        Returns
        -------
        bool
            ``True`` if a matching registry value exists under ``HKCU\\...\\Run``.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
                winreg.QueryValueEx(key, _autostart_reg_name())
                return True
        except FileNotFoundError:
            return False

    def set_autostart(enable: bool) -> None:
        """Create or remove the autostart registry entry.

        Parameters
        ----------
        enable : bool
            ``True`` to register autostart, ``False`` to remove it.
        """
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, _autostart_reg_name(), 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, _autostart_reg_name())
                except FileNotFoundError:
                    pass

    def sync_autostart_path() -> None:
        """Update the autostart registry command if the EXE has been moved.

        Compares the stored command with the current expected one and
        silently updates the registry value when they differ.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
                stored, _ = winreg.QueryValueEx(key, _autostart_reg_name())
        except FileNotFoundError:
            return

        if stored != _autostart_command():
            set_autostart(True)

elif sys.platform == 'darwin':
    def _launch_agent_label() -> str:
        """Return the per-instance LaunchAgent label (base label plus config-dir suffix)."""
        return LAUNCH_AGENT_BASE_LABEL + config_dir_suffix()

    def _launch_agent_path() -> Path:
        """Return the plist path for this instance's LaunchAgent."""
        return Path.home() / 'Library' / 'LaunchAgents' / f'{_launch_agent_label()}.plist'

    def _launch_arguments() -> list[str]:
        """Return the launch argv to store in the plist for this instance."""
        arguments = [sys.executable]
        if not is_default_config_dir():
            arguments.append(f'--config-dir={effective_config_dir()}')
        return arguments

    def _xml_escape(text: str) -> str:
        """Escape the three XML-significant chars in element text content.

        Inlined to avoid pulling ``xml.sax.saxutils`` into the PyInstaller
        bundle just for this single call.
        """
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def _build_plist(launch_arguments: list[str]) -> str:
        """Build the LaunchAgent plist XML running *launch_arguments*.

        Uses a small static template (no dynamic key names, no user data)
        so the on-disk file is fully auditable at a glance.
        """
        argument_strings = ''.join(f'<string>{_xml_escape(argument)}</string>' for argument in launch_arguments)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            f'    <key>Label</key>            <string>{_launch_agent_label()}</string>\n'
            '    <key>ProgramArguments</key>\n'
            f'    <array>{argument_strings}</array>\n'
            '    <key>RunAtLoad</key>        <true/>\n'
            '    <key>KeepAlive</key>        <false/>\n'
            '    <key>ProcessType</key>      <string>Interactive</string>\n'
            # Associate the agent with the app bundle (the base label equals the
            # CFBundleIdentifier) so macOS can attribute the Login Items entry to
            # the app.  macOS resolves this to the app's real name + icon only
            # once the bundle is code-signed and trusted; an unsigned build still
            # shows a generic icon and "unidentified developer" there.
            f'    <key>AssociatedBundleIdentifiers</key> <string>{LAUNCH_AGENT_BASE_LABEL}</string>\n'
            '</dict>\n'
            '</plist>\n'
        )

    def is_autostart_enabled() -> bool:
        """Check whether the LaunchAgent plist exists in the user's LaunchAgents folder."""
        return _launch_agent_path().is_file()

    def set_autostart(enable: bool) -> None:
        """Create or remove the LaunchAgent plist.

        macOS scans ``~/Library/LaunchAgents`` at every login and starts
        ``RunAtLoad=true`` agents automatically, so just writing/deleting
        the file is enough - no ``launchctl bootstrap`` call needed and
        the app is not double-launched while the user toggles the menu.
        """
        plist_path = _launch_agent_path()
        if enable:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(_build_plist(_launch_arguments()), encoding='utf-8')
        else:
            try:
                plist_path.unlink()
            except FileNotFoundError:
                pass

    def sync_autostart_path() -> None:
        """Rewrite the plist if the stored launch command no longer matches.

        Mirrors the Windows ``sync_autostart_path`` semantics: when the
        user drags ``UsageMonitorForClaude.app`` to a new location and
        relaunches, the next startup heals the stale autostart entry.
        """
        plist_path = _launch_agent_path()
        if not plist_path.is_file():
            return

        expected = _build_plist(_launch_arguments())
        try:
            current = plist_path.read_text(encoding='utf-8')
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

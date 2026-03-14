"""
Command
========

Execute user-configured shell commands on usage events.

Commands run as fire-and-forget subprocesses.  Event details are passed
via environment variables so the user's script can inspect them without
any string interpolation in the command itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback

__all__ = ['run_event_command']


def run_event_command(command: str, env_vars: dict[str, str]) -> None:
    """Launch a shell command with event-specific environment variables.

    The command runs asynchronously (fire-and-forget).  Exceptions from
    ``subprocess.Popen`` are caught so the tray app is never disrupted
    by a misconfigured user command.

    Parameters
    ----------
    command : str
        Shell command string to execute.
    env_vars : dict[str, str]
        Mapping of ``USAGE_MONITOR_*`` environment variable names to
        their values.  Merged into the current process environment.
    """
    if not command:
        return

    env = {**os.environ, **env_vars}

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

    try:
        subprocess.Popen(
            command, shell=True, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except Exception:
        traceback.print_exc()

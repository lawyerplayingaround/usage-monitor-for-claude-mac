"""
Command Tests
===============

Unit tests for the command module: subprocess execution with environment variables.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

from usage_monitor_for_claude.command import run_event_command


class TestRunEventCommand(unittest.TestCase):
    """Tests for run_event_command() subprocess launching."""

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_command_executed_with_shell(self, mock_popen: MagicMock):
        """Command is passed to Popen with shell=True."""
        run_event_command('echo hello', {'USAGE_MONITOR_EVENT': 'reset'})

        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertEqual(args[0], 'echo hello')
        self.assertTrue(kwargs['shell'])

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_env_vars_merged_into_environment(self, mock_popen: MagicMock):
        """Event-specific variables are merged into the process environment."""
        env_vars = {
            'USAGE_MONITOR_EVENT': 'threshold',
            'USAGE_MONITOR_VARIANT': 'five_hour',
            'USAGE_MONITOR_UTILIZATION': '84.5',
        }
        run_event_command('notify.bat', env_vars)

        passed_env = mock_popen.call_args[1]['env']
        for key, value in env_vars.items():
            self.assertEqual(passed_env[key], value)

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_existing_env_preserved(self, mock_popen: MagicMock):
        """Existing environment variables are preserved alongside new ones."""
        with patch.dict('os.environ', {'PATH': '/usr/bin', 'HOME': '/home/user'}):
            run_event_command('test', {'USAGE_MONITOR_EVENT': 'reset'})

        passed_env = mock_popen.call_args[1]['env']
        self.assertEqual(passed_env['PATH'], '/usr/bin')
        self.assertEqual(passed_env['HOME'], '/home/user')
        self.assertEqual(passed_env['USAGE_MONITOR_EVENT'], 'reset')

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_stdout_stderr_devnull(self, mock_popen: MagicMock):
        """stdout and stderr are redirected to DEVNULL."""
        run_event_command('test', {'USAGE_MONITOR_EVENT': 'reset'})

        kwargs = mock_popen.call_args[1]
        self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_create_no_window_on_windows(self, mock_popen: MagicMock):
        """CREATE_NO_WINDOW flag is set on Windows."""
        with patch.object(sys, 'platform', 'win32'):
            run_event_command('test', {'USAGE_MONITOR_EVENT': 'reset'})

        kwargs = mock_popen.call_args[1]
        self.assertEqual(kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_no_creation_flags_on_non_windows(self, mock_popen: MagicMock):
        """No creation flags on non-Windows platforms."""
        with patch.object(sys, 'platform', 'linux'):
            run_event_command('test', {'USAGE_MONITOR_EVENT': 'reset'})

        kwargs = mock_popen.call_args[1]
        self.assertEqual(kwargs['creationflags'], 0)

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_empty_command_skipped(self, mock_popen: MagicMock):
        """Empty command string does not invoke Popen."""
        run_event_command('', {'USAGE_MONITOR_EVENT': 'reset'})

        mock_popen.assert_not_called()

    @patch('usage_monitor_for_claude.command.traceback.print_exc')
    @patch('usage_monitor_for_claude.command.subprocess.Popen', side_effect=OSError('not found'))
    def test_popen_exception_caught(self, mock_popen: MagicMock, mock_print_exc: MagicMock):
        """OSError from Popen is caught and printed to stderr."""
        run_event_command('nonexistent_command', {'USAGE_MONITOR_EVENT': 'reset'})

        mock_print_exc.assert_called_once()

    @patch('usage_monitor_for_claude.command.traceback.print_exc')
    @patch('usage_monitor_for_claude.command.subprocess.Popen', side_effect=ValueError('bad'))
    def test_unexpected_exception_caught(self, mock_popen: MagicMock, mock_print_exc: MagicMock):
        """Unexpected exceptions from Popen are caught and printed to stderr."""
        run_event_command('bad_command', {'USAGE_MONITOR_EVENT': 'reset'})

        mock_print_exc.assert_called_once()

    @patch('usage_monitor_for_claude.command.subprocess.Popen')
    def test_popen_not_waited(self, mock_popen: MagicMock):
        """Popen result is not waited on (fire-and-forget)."""
        run_event_command('long_running', {'USAGE_MONITOR_EVENT': 'reset'})

        mock_process = mock_popen.return_value
        mock_process.wait.assert_not_called()
        mock_process.communicate.assert_not_called()


if __name__ == '__main__':
    unittest.main()

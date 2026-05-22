"""
Single-Instance Guard
======================

Prevents multiple instances from running simultaneously.

On Windows, a named Win32 mutex tracks the holder, and a page-file-backed
shared memory segment stores its PID and version so a new instance can
identify and terminate it.

On POSIX platforms (macOS, Linux), the same guarantee is provided by an
``flock``-based lock file under the user's home directory.  The dialog
flow that asks whether to terminate a previous instance is replaced by a
simple "refuse to start" if the lock is held; the user must quit the
other instance manually.
"""
from __future__ import annotations

import os
import sys

from . import __version__
from .i18n import T

__all__ = ['ensure_single_instance', 'release_instance_lock']

_MUTEX_NAME = 'UsageMonitorForClaude_SingleInstance'
_PID_MAPPING_NAME = 'UsageMonitorForClaude_HolderPID'


if sys.platform == 'win32':
    import ctypes
    import ctypes.wintypes
    import struct

    _ERROR_ALREADY_EXISTS = 0xB7
    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _PAGE_READWRITE = 0x04
    _FILE_MAP_READ = 0x0004
    _FILE_MAP_WRITE = 0x0002

    # Shared memory layout: 4-byte PID + null-terminated UTF-8 version string.
    # 64 bytes is plenty for a PID and a version like "1.10.0".
    _SHARED_MEM_SIZE = 64

    # use_last_error=True captures GetLastError() immediately after each
    # FFI call into a ctypes-private thread-local, before Python can run
    # any intervening code that might reset it.
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _kernel32.CreateMutexW.argtypes = [ctypes.wintypes.LPCVOID, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE

    _kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    _kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

    _kernel32.CreateFileMappingW.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.LPCVOID, ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.LPCWSTR,
    ]
    _kernel32.CreateFileMappingW.restype = ctypes.wintypes.HANDLE

    _kernel32.OpenFileMappingW.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    _kernel32.OpenFileMappingW.restype = ctypes.wintypes.HANDLE

    _kernel32.MapViewOfFile.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.c_size_t,
    ]
    _kernel32.MapViewOfFile.restype = ctypes.c_void_p

    _kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    _kernel32.UnmapViewOfFile.restype = ctypes.wintypes.BOOL

    _kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
    _kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE

    _kernel32.TerminateProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.UINT]
    _kernel32.TerminateProcess.restype = ctypes.wintypes.BOOL

    _kernel32.WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = ctypes.wintypes.DWORD

    # Handles kept alive for the process lifetime; released on exit or
    # explicitly via release_instance_lock().
    _mutex_handle: int | None = None
    _pid_mapping_handle: int | None = None

    def _store_holder_info() -> None:
        """Store our PID and version in named shared memory (page-file backed)."""
        global _pid_mapping_handle
        _pid_mapping_handle = _kernel32.CreateFileMappingW(
            _INVALID_HANDLE, None, _PAGE_READWRITE, 0, _SHARED_MEM_SIZE, _PID_MAPPING_NAME,
        )
        if not _pid_mapping_handle:
            return

        view = _kernel32.MapViewOfFile(_pid_mapping_handle, _FILE_MAP_WRITE, 0, 0, _SHARED_MEM_SIZE)
        if not view:
            return

        version_bytes = __version__.encode('utf-8')[:_SHARED_MEM_SIZE - 5]
        payload = struct.pack(f'<I{len(version_bytes) + 1}s', os.getpid(), version_bytes + b'\x00')
        ctypes.memmove(view, payload, len(payload))
        _kernel32.UnmapViewOfFile(view)

    def _read_holder_info() -> tuple[int | None, str | None]:
        """Read PID and version of the mutex-holding instance from shared memory."""
        mapping = _kernel32.OpenFileMappingW(_FILE_MAP_READ, False, _PID_MAPPING_NAME)
        if not mapping:
            return None, None

        view = _kernel32.MapViewOfFile(mapping, _FILE_MAP_READ, 0, 0, _SHARED_MEM_SIZE)
        if not view:
            _kernel32.CloseHandle(mapping)
            return None, None

        raw = ctypes.string_at(view, _SHARED_MEM_SIZE)
        _kernel32.UnmapViewOfFile(view)
        _kernel32.CloseHandle(mapping)

        if len(raw) < 5:
            return None, None

        pid = struct.unpack('<I', raw[:4])[0]
        version = raw[4:].split(b'\x00', 1)[0].decode('utf-8', errors='replace') or None
        return pid if pid else None, version

    def _terminate_pid(pid: int) -> None:
        """Terminate a process by PID and wait until it is fully dead."""
        PROCESS_TERMINATE = 0x0001
        PROCESS_SYNCHRONIZE = 0x00100000

        handle = _kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, False, pid)
        if not handle:
            return

        if not _kernel32.TerminateProcess(handle, 1):
            _kernel32.CloseHandle(handle)
            return

        _kernel32.WaitForSingleObject(handle, 5000)
        _kernel32.CloseHandle(handle)

    def ensure_single_instance() -> bool:
        """Ensure only one instance is running.  Prompts to replace an existing instance."""
        global _mutex_handle
        _mutex_handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.get_last_error() != _ERROR_ALREADY_EXISTS:
            _store_holder_info()
            return True

        MB_YESNO = 0x04
        MB_ICONQUESTION = 0x20
        MB_TOPMOST = 0x40000
        IDYES = 6

        holder_pid, running_version = _read_holder_info()

        title = T['popup_title']
        if running_version:
            title += f' v{running_version}'

        message = T['already_running'].format(running_version=running_version or '?')

        answer = ctypes.windll.user32.MessageBoxW(
            None, message, title,
            MB_YESNO | MB_ICONQUESTION | MB_TOPMOST,
        )
        if answer != IDYES:
            _kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
            return False

        if holder_pid:
            _terminate_pid(holder_pid)
        _kernel32.CloseHandle(_mutex_handle)

        _mutex_handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        _store_holder_info()
        return True

    def release_instance_lock() -> None:
        """Release the mutex and shared memory so a new instance can start."""
        global _mutex_handle, _pid_mapping_handle

        if _mutex_handle:
            _kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None

        if _pid_mapping_handle:
            _kernel32.CloseHandle(_pid_mapping_handle)
            _pid_mapping_handle = None

else:
    import fcntl

    # POSIX: a per-user lock file under the home directory.  The lock is held
    # via flock LOCK_EX|LOCK_NB and released either explicitly or when the
    # process exits (the OS releases all flocks held by a dying process).
    _LOCK_PATH = os.path.expanduser('~/.usage-monitor-for-claude.lock')
    _lock_file = None

    def ensure_single_instance() -> bool:
        """Ensure only one instance is running by holding an flock on a lock file."""
        global _lock_file
        try:
            _lock_file = open(_LOCK_PATH, 'w')
        except OSError:
            # Cannot create lock file - allow startup rather than refusing.
            return True
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _lock_file.close()
            _lock_file = None
            return False
        _lock_file.write(f'{os.getpid()}\n{__version__}\n')
        _lock_file.flush()
        return True

    def release_instance_lock() -> None:
        """Release the flock and close the lock file."""
        global _lock_file
        if _lock_file is None:
            return
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        _lock_file.close()
        _lock_file = None

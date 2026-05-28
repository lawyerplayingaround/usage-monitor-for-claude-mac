"""
Idle Detection
===============

Detects user inactivity and workstation lock state.

On Windows, uses ``GetLastInputInfo`` and ``OpenInputDesktop`` via ctypes.
On macOS, uses ``CGEventSourceSecondsSinceLastEventType`` (Quartz) and
``CGSessionCopyCurrentDictionary`` to read the same signals.
"""
from __future__ import annotations

import sys

__all__ = ['get_idle_seconds', 'is_workstation_locked']


if sys.platform == 'win32':
    import ctypes
    import ctypes.wintypes

    # Ensure GetTickCount returns unsigned DWORD (default c_int overflows after ~24.8 days of uptime)
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.wintypes.DWORD

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ('cbSize', ctypes.wintypes.UINT),
            ('dwTime', ctypes.wintypes.DWORD),
        ]

    def get_idle_seconds() -> float:
        """Return seconds since the last keyboard or mouse input on Windows."""
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        # Simulate unsigned 32-bit subtraction so the result stays correct
        # when GetTickCount wraps after ~49 days of uptime.
        millis = (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF
        return millis / 1000.0

    def is_workstation_locked() -> bool:
        """Return True if the Windows workstation is locked."""
        hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0)
        if hdesk:
            ctypes.windll.user32.CloseDesktop(hdesk)
            return False
        return True

elif sys.platform == 'darwin':
    # Quartz (CoreGraphics) is part of pyobjc-framework-Quartz, which ships in
    # the default pyobjc install used by the macOS build of this app.
    from Quartz import (  # type: ignore[import-untyped]  # pyobjc framework has no type stubs
        CGEventSourceSecondsSinceLastEventType,
        CGSessionCopyCurrentDictionary,
        kCGAnyInputEventType,
        kCGEventSourceStateHIDSystemState,
    )

    def get_idle_seconds() -> float:
        """Return seconds since the last keyboard or mouse input on macOS."""
        try:
            return float(CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType))
        except Exception:
            return 0.0

    def is_workstation_locked() -> bool:
        """Return True if the macOS screen is currently locked."""
        try:
            session = CGSessionCopyCurrentDictionary()
        except Exception:
            return False
        if session is None:
            return False
        return bool(session.get('CGSSessionScreenIsLocked', False))

else:
    def get_idle_seconds() -> float:
        """Idle detection is not implemented on this platform."""
        return 0.0

    def is_workstation_locked() -> bool:
        """Workstation lock detection is not implemented on this platform."""
        return False

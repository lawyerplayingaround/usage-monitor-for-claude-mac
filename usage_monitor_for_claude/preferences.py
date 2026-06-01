"""
Preferences
===========

Reads and writes the user-toggleable preferences exposed in the tray
right-click menu, in the platform's native preference store so the app
never writes its own data files to disk:

* **Windows** - the registry under ``HKCU\\Software\\UsageMonitorForClaude``.
* **macOS** - a dedicated user defaults suite
  ``com.usage-monitor-for-claude.settings`` (``~/Library/Preferences``), the
  idiomatic equivalent of the Windows registry approach.  The suite is kept
  distinct from the bundled app's own bundle id, because ``NSUserDefaults``
  returns ``nil`` when asked for the receiver's own bundle domain by name.

Tracked preferences:

* ``IconLayout`` - either ``'classic'`` or ``'compact'``.
* ``DblclickOpenClaude`` - whether double-clicking the icon launches
  Claude Desktop.

``DEFAULT_ICON_LAYOUT`` and ``DEFAULT_DBLCLICK_OPEN_CLAUDE`` define what a
fresh install sees when no preference has been stored yet.
"""
from __future__ import annotations

import sys

__all__ = [
    'ICON_LAYOUT_CLASSIC', 'ICON_LAYOUT_COMPACT',
    'DEFAULT_ICON_LAYOUT', 'DEFAULT_DBLCLICK_OPEN_CLAUDE',
    'get_icon_layout', 'set_icon_layout',
    'get_dblclick_open_claude', 'set_dblclick_open_claude',
]

ICON_LAYOUT_CLASSIC = 'classic'
ICON_LAYOUT_COMPACT = 'compact'
_VALID_ICON_LAYOUTS = frozenset({ICON_LAYOUT_CLASSIC, ICON_LAYOUT_COMPACT})

DEFAULT_ICON_LAYOUT = ICON_LAYOUT_COMPACT
DEFAULT_DBLCLICK_OPEN_CLAUDE = True

_ICON_LAYOUT_NAME = 'IconLayout'
_DBLCLICK_NAME = 'DblclickOpenClaude'


# ---------------------------------------------------------------------------
# Platform-native backend.  Each provides _read_str/_write_str/_read_bool/
# _write_bool with the same contract; the public getters/setters below stay
# platform-agnostic.
# ---------------------------------------------------------------------------

if sys.platform == 'win32':
    import winreg

    _REG_KEY = r'Software\UsageMonitorForClaude'

    def _read_str(name: str, default: str) -> str:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return default
        return str(value)

    def _write_str(name: str, value: str) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def _read_bool(name: str, default: bool) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return default
        return bool(value)

    def _write_bool(name: str, value: bool) -> None:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(bool(value)))

elif sys.platform == 'darwin':
    # NSUserDefaults under a dedicated suite name so the value is shared whether
    # the app runs as the bundled ``.app`` or from source via ``python -m``.  The
    # suite must differ from the bundled app's own bundle id
    # (``com.usage-monitor-for-claude``): ``initWithSuiteName_`` returns ``nil``
    # for the receiver's own bundle domain, so a suite equal to the bundle id
    # would yield no store at all.  A nil store is also guarded everywhere below,
    # so a preferences failure degrades to defaults instead of crashing the app.
    _SUITE = 'com.usage-monitor-for-claude.settings'

    def _defaults():
        import Foundation
        return Foundation.NSUserDefaults.alloc().initWithSuiteName_(_SUITE)

    def _read_str(name: str, default: str) -> str:
        store = _defaults()
        value = store.stringForKey_(name) if store is not None else None
        return str(value) if value is not None else default

    def _write_str(name: str, value: str) -> None:
        store = _defaults()
        if store is None:
            return
        store.setObject_forKey_(value, name)
        store.synchronize()

    def _read_bool(name: str, default: bool) -> bool:
        store = _defaults()
        if store is None or store.objectForKey_(name) is None:
            return default
        return bool(store.boolForKey_(name))

    def _write_bool(name: str, value: bool) -> None:
        store = _defaults()
        if store is None:
            return
        store.setBool_forKey_(bool(value), name)
        store.synchronize()

else:
    # Other platforms (e.g. CI/Linux test hosts): in-memory only, not persisted.
    _MEMORY: dict[str, object] = {}

    def _read_str(name: str, default: str) -> str:
        value = _MEMORY.get(name)
        return str(value) if value is not None else default

    def _write_str(name: str, value: str) -> None:
        _MEMORY[name] = value

    def _read_bool(name: str, default: bool) -> bool:
        if name not in _MEMORY:
            return default
        return bool(_MEMORY[name])

    def _write_bool(name: str, value: bool) -> None:
        _MEMORY[name] = bool(value)


def get_icon_layout() -> str:
    """Return the active icon layout name (``'classic'`` or ``'compact'``).

    Falls back to :data:`DEFAULT_ICON_LAYOUT` when nothing is stored or the
    stored value is unrecognized.
    """
    text = _read_str(_ICON_LAYOUT_NAME, DEFAULT_ICON_LAYOUT)
    if text not in _VALID_ICON_LAYOUTS:
        return DEFAULT_ICON_LAYOUT
    return text


def set_icon_layout(value: str) -> None:
    """Persist the icon layout choice; *value* must be ``'classic'`` or ``'compact'``."""
    if value not in _VALID_ICON_LAYOUTS:
        raise ValueError(f'invalid icon layout: {value!r}')
    _write_str(_ICON_LAYOUT_NAME, value)


def get_dblclick_open_claude() -> bool:
    """Return whether double-clicking the tray icon launches Claude Desktop."""
    return _read_bool(_DBLCLICK_NAME, DEFAULT_DBLCLICK_OPEN_CLAUDE)


def set_dblclick_open_claude(enabled: bool) -> None:
    """Persist whether double-click launches Claude Desktop."""
    _write_bool(_DBLCLICK_NAME, bool(enabled))

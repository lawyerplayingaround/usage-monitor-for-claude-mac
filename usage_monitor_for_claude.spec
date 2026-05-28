# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Usage Monitor for Claude.

Build:
  pyinstaller usage_monitor_for_claude.spec

On Windows produces ``dist/UsageMonitorForClaude.exe``; on macOS produces
``dist/UsageMonitorForClaude.app`` (a proper application bundle with
``LSUIElement=True`` so it lives in the menu bar without a Dock icon).
The single spec file branches on ``sys.platform`` to keep the build
config in one auditable place.
"""

import re
import sys
from pathlib import Path

_IS_MAC = sys.platform == 'darwin'
_IS_WIN = sys.platform == 'win32'

# Pull __version__ from the package's __init__.py without importing it
# (PyInstaller runs this spec before the build environment is fully set up).
_init_text = Path('usage_monitor_for_claude/__init__.py').read_text(encoding='utf-8')
_version_match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", _init_text, re.M)
_VERSION = _version_match.group(1) if _version_match else '0.0.0'

# ---------------------------------------------------------------------------
# Per-platform Analysis configuration
# ---------------------------------------------------------------------------

if _IS_MAC:
    _hidden_imports = [
        'pystray._darwin',
        'objc',
        'AppKit',
        'Foundation',
        'Quartz',
        'WebKit',
        'usage_monitor_for_claude._macos_tray',
        'usage_monitor_for_claude._macos_popup',
    ]
    # 'xml' must stay - an empirical test (excluding it) results in
    # ``ImportError: this platform is not supported: No module named
    # 'xml'`` from ``pystray.__init__.backend()`` during the bundle's
    # cold start.  The trigger appears to be PyInstaller's
    # ``pkg_resources`` shim rather than pystray's own source (pystray's
    # files do not ``import xml`` directly), but the symptom is real
    # and reproducible.  Autostart on macOS inlines XML escaping so the
    # autostart module does not contribute to the xml requirement.
    _excludes = [
        'unittest', 'test',
        'xmlrpc', 'pydoc',
        'tkinter', '_tkinter',
        'PIL._avif', 'PIL._webp',
        'PIL._imagingcms', 'PIL._imagingmath', 'PIL._imagingtk', 'PIL._imagingmorph',
        'setuptools', '_distutils_hack',
        'asyncio', 'concurrent',
        'multiprocessing',
        'tomllib',
        'sqlite3',
        # Windows-only modules pulled in transitively otherwise:
        'pystray._win32',
        'pystray._util.win32',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
        'pythonnet',
        'bottle',
    ]
else:
    _hidden_imports = [
        'pystray._win32',
        'pystray._util',
        'pystray._util.win32',
        'webview',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
        'bottle',
    ]
    _excludes = [
        'unittest', 'test',
        'xmlrpc', 'pydoc',
        'tkinter', '_tkinter',
        'PIL._avif', 'PIL._webp',
        'PIL._imagingcms', 'PIL._imagingmath', 'PIL._imagingtk', 'PIL._imagingmorph',
        'setuptools', '_distutils_hack',
        'asyncio', 'concurrent',
        'multiprocessing',
        'xml', 'tomllib',
        'sqlite3',
    ]


a = Analysis(
    ['usage_monitor_for_claude/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('locale/*.json', 'locale'),
        ('usage_monitor_for_claude/popup/popup.html', 'usage_monitor_for_claude/popup'),
        ('usage_monitor_for_claude/popup/popup.css', 'usage_monitor_for_claude/popup'),
        ('usage_monitor_for_claude/popup/popup.js', 'usage_monitor_for_claude/popup'),
    ],
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Per-platform EXE / BUNDLE configuration
# ---------------------------------------------------------------------------

if _IS_MAC:
    # On macOS we use onedir layout (PyInstaller >= 6.0 deprecates onefile
    # inside .app bundles).  EXE builds the Mach-O binary; COLLECT gathers
    # the binary + dependent .so files + data files into a single folder;
    # BUNDLE wraps that folder into a standard .app structure.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='UsageMonitorForClaude',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        # Universal2 would also include x86_64; arm64 keeps the bundle small
        # on Apple Silicon Macs.  Change to 'universal2' if Intel support is
        # ever required.
        target_arch='arm64',
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='UsageMonitorForClaude',
    )

    app = BUNDLE(
        coll,
        name='UsageMonitorForClaude.app',
        icon=None,
        bundle_identifier='com.usage-monitor-for-claude',
        info_plist={
            # LSUIElement keeps the app out of the Dock and the application
            # menu bar - it only owns its NSStatusItem.
            'LSUIElement': True,
            'CFBundleName': 'UsageMonitorForClaude',
            'CFBundleDisplayName': 'Usage Monitor for Claude',
            'CFBundleShortVersionString': _VERSION,
            'CFBundleVersion': _VERSION,
            'NSHumanReadableCopyright': 'Original work Copyright (c) 2026 Jens Duttke. macOS port released under the same MIT license.',
            'NSHighResolutionCapable': True,
            # Minimum macOS that supports Apple Silicon native + modern WKWebView.
            'LSMinimumSystemVersion': '11.0',
        },
    )

else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='UsageMonitorForClaude',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        icon='usage_monitor_for_claude.ico',
        version='version_info.py',
    )

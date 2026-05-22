"""
Build Script
=============

Builds the standalone executable for Usage Monitor for Claude using
PyInstaller.

Usage:
    python build.py

Produces:
    dist/UsageMonitorForClaude.exe        (on Windows)
    dist/UsageMonitorForClaude.app/...    (on macOS - a proper app bundle)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / 'dist'
SPEC = ROOT / 'usage_monitor_for_claude.spec'


def _artifact_path() -> Path:
    """Return the expected output path for the current platform."""
    if sys.platform == 'darwin':
        return DIST / 'UsageMonitorForClaude.app'
    return DIST / 'UsageMonitorForClaude.exe'


def _artifact_size(path: Path) -> float:
    """Return the artifact size in megabytes (recursive for the .app bundle)."""
    if path.is_dir():
        total = sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
    else:
        total = path.stat().st_size
    return total / (1024 * 1024)


def build() -> None:
    """Run PyInstaller to produce the standalone executable."""
    print('Starting PyInstaller build ...')
    cmd = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', str(SPEC)]
    subprocess.check_call(cmd, cwd=str(ROOT))

    artifact = _artifact_path()
    if artifact.exists():
        size_mb = _artifact_size(artifact)
        print(f'\nBuild successful!  {artifact}  ({size_mb:.1f} MB)')
    else:
        print('\nBuild failed - artifact not found.')
        sys.exit(1)


if __name__ == '__main__':
    build()

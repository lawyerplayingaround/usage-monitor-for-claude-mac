# Usage Monitor for Claude - macOS Port

Living document for the `mac-port` branch.  Tracks divergences from the
Windows-only upstream, current build status, and remaining work.

The upstream project (jens-duttke/usage-monitor-for-claude) is explicitly
Windows-only.  This branch ports it to macOS while preserving the core
auditability guarantees of the original:

- credentials only ever live in HTTP Authorization headers (never in disk
  caches, never in logs);
- the only network destinations are `api.anthropic.com` and `api.github.com`
  (the latter only for upstream release checks);
- no `eval` / `exec` / dynamic imports.

---

## Status by phase

| Phase | Description | State |
| --- | --- | --- |
| 1 | Read access token from macOS Keychain | done |
| 2 | Tray icon visible in the menu bar | done |
| 3 | Detail popup (HTML or native) on click | pending |
| 4 | Login Item autostart + PyInstaller `.app` build | pending |
| 5 | Final end-to-end validation (network + filesystem audit) | pending |

---

## How to run the porting locally

The package lives in
`your local checkout/`.

```bash
cd "/path/to/usage-monitor-for-claude"
python3 -m venv .venv
source .venv/bin/activate
pip install requests Pillow pystray pywebview pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz pyinstaller
python3 -m usage_monitor_for_claude
```

The menu bar should show `C` (no data yet) and update to the current 5h
session percentage within a second.

To run the API-related tests:

```bash
python3 -m unittest tests.test_api
```

The file-based tests are auto-skipped on macOS; nine Keychain-specific tests
cover the macOS read path.  Other test modules import Windows-only Win32
APIs and are not expected to load on macOS - that is upstream behaviour, not
a porting regression.

---

## Divergences from the upstream `main` branch

All changes live in the `mac-port` branch.  The upstream `.claude/CLAUDE.md`
rule "Windows-only application - no `sys.platform` checks" is intentionally
relaxed here, scoped strictly to the macOS branches that needed to land for
the port to function.

### `usage_monitor_for_claude/api.py`

Adds a `sys.platform == 'darwin'` branch in `read_access_token()` that reads
the token from the system Keychain via `/usr/bin/security
find-generic-password`.  Supports both the legacy service name
(`Claude Code-credentials`) and the v2.1.52+ hashed variant
(`Claude Code-credentials-<HASH>`) discovered through `security
dump-keychain`.  The resolved service name is cached in memory only - the
token itself is never cached, never written to disk, and never logged.

### `usage_monitor_for_claude/tray_icon.py`

Replaces the Windows-registry theme detection with `defaults read -g
AppleInterfaceStyle`.  Adds a platform-keyed `_ICON_LAYOUT` constant: macOS
uses SF Pro Semibold (via the `SFNS.ttf` variable font and Pillow's
`set_variation_by_name`) at size 32 with the glyph vertically centred in the
area above the two progress bars; Windows keeps Arial Bold and the original
geometry.  Font paths fall back to the macOS system fonts directory.

### `usage_monitor_for_claude/_macos_tray.py` (new)

`install_macos_tray_patch(icon)` monkey-patches `pystray._darwin.Icon`'s
`_assert_image` so the menu bar image is rendered at 2x the status bar
thickness (retina-sharp) and marked as a template image, which makes AppKit
adapt the icon to the menu bar's light/dark appearance automatically.

### `usage_monitor_for_claude/idle.py`

Adds a `sys.platform == 'darwin'` branch using
`CGEventSourceSecondsSinceLastEventType` (Quartz) for idle seconds and
`CGSessionCopyCurrentDictionary` for screen-lock detection.

### `usage_monitor_for_claude/autostart.py`

The Windows registry implementation is now wrapped in `if sys.platform ==
'win32':`.  The macOS branch is currently a no-op stub - Phase 4 will
implement a `LaunchAgent` plist under `~/Library/LaunchAgents`.

### `usage_monitor_for_claude/single_instance.py`

POSIX branch uses an `flock`-based lock file under
`~/.usage-monitor-for-claude.lock` instead of a named Win32 mutex + shared
memory.  The interactive "kill the other instance?" dialog is replaced by a
silent "refuse to start" when the lock is held; the user must quit the
other instance manually.

### `usage_monitor_for_claude/__main__.py`

On macOS, pystray runs on the main thread (AppKit requires `NSStatusItem`
to be created on the main thread), and the pywebview event loop is skipped.
That makes the popup unavailable on macOS until Phase 3 wires it up.
`subprocess.CREATE_NO_WINDOW` is guarded behind `sys.platform == 'win32'`.

### `usage_monitor_for_claude/{claude_cli,command,app}.py`

`CREATE_NO_WINDOW` is replaced with a `_NO_CONSOLE_KWARGS` dict that
expands to nothing on POSIX.  `app.crash_log` writes to `stderr` on non-Windows
instead of calling `MessageBoxW`.  `app.UsageMonitorForClaude.__init__`
installs the tray patch from `_macos_tray.py` when running on macOS.

### `tests/test_api.py`

Existing file-based read tests are now `unittest.skipIf(sys.platform ==
'darwin', ...)`.  New `TestReadAccessTokenMacOS` class adds nine tests
covering legacy + hashed service names, OS error, non-zero exit, empty
output, malformed JSON, missing OAuth key, subprocess timeout, and an
explicit `test_token_never_written_to_disk` assertion.

---

## Roadmap

### Phase 3 - Popup window

Two paths under evaluation:

- **3A.** Reuse pywebview with the Cocoa backend.  AppKit will only allow
  one main-thread runloop, so the popup creation has to be dispatched onto
  the existing pystray loop via `Foundation.NSObject.performSelectorOnMainThread`
  or `dispatch_async`.  The Windows `_tray_position()` (Shell_TrayWnd +
  MonitorFromWindow + GetMonitorInfoW) must be reimplemented against
  `NSStatusItem.button.window.frame` via pyobjc.

- **3B.** Replace the HTML popup with a native `NSPanel` driven by pyobjc.
  Less code surface for malicious changes (no WebKit), but reimplements the
  upstream `popup/popup.{html,css,js}` from scratch.

3A keeps fidelity with the Windows visual; 3B is more native.  Decision
pending until the work starts.

### Phase 4 - Autostart + build

- macOS autostart: write a `LaunchAgent` plist at
  `~/Library/LaunchAgents/com.usage-monitor-for-claude.plist` and load it
  via `launchctl bootstrap gui/$(id -u)`.
- Build script (`build.py`) gets a `darwin` branch producing
  `dist/UsageMonitorForClaude.app` via PyInstaller with
  `--target-arch arm64`, `LSUIElement=true` in `Info.plist`, and hidden
  imports for `pystray._darwin`, `Quartz`, and `_macos_tray`.

### Phase 5 - Validation

- `sudo lsof -i -P -n | grep python` confirms only `api.anthropic.com` and
  `api.github.com` connections.
- `find ~/Library -name "*usage_monitor*"` confirms no on-disk files
  contain credentials (the lock file may exist; the SF Pro variation cache
  inside Pillow does not persist).
- Side-by-side screenshot comparison with the Windows reference image
  stored at `Apps Windows/Usage_Monitor_Windows/`.

---

## Known limitations on macOS today

- **No popup.**  Clicking "Show Claude Usage" does nothing on macOS yet
  (Phase 3).  The number on the menu bar is the only live indicator.
- **No autostart.**  The "Start with Windows" menu item is hidden in the
  unfrozen build and the macOS branch is a stub.
- **App is unsigned.**  Phase 4 produces an unsigned `.app`; macOS Gatekeeper
  will require right-click - Open the first time.  Distributable signed
  builds would require enrolling the developer in Apple's notarization
  programme, which is out of scope for this port.

---

## Reference

- Windows visual reference (popup design): see
  `Apps Windows/Usage_Monitor_Windows/screenshot.png`.
- Upstream repository: <https://github.com/jens-duttke/usage-monitor-for-claude>

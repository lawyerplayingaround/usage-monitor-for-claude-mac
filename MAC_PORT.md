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
| 3 | Detail popup (NSPanel + WKWebView) on click | done |
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
pip install requests Pillow pystray pywebview \
    pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-WebKit \
    pyinstaller
python3 -m usage_monitor_for_claude
```

The menu bar should show `C` (no data yet) and update to the current 5h
session percentage within a second.  Clicking "Show Claude Usage" opens
the HTML popup hosted in a native ``NSPanel``.

To run the tests that work on macOS:

```bash
python3 -m unittest tests.test_api tests.test_popup tests.test_macos_popup
# expected: 113 ok, 19 skipped (Win32-only)
```

To exercise the popup end-to-end without manual clicking:

```bash
python3 scripts/mac_smoke_popup.py
```

The remaining test modules (`test_app`, `test_command`, `test_idle`,
`test_tray_icon`, `test_verbose`, `test_autostart`) still import Windows
APIs at module level and are not expected to load on macOS - that is
upstream behaviour, not a porting regression.

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
to be created on the main thread).  The popup is dispatched onto the same
main runloop via `NSOperationQueue.mainQueue()` from the popup worker
thread; pywebview's `webview.start()` is never called on macOS.
`subprocess.CREATE_NO_WINDOW` is guarded behind `sys.platform == 'win32'`.

### `usage_monitor_for_claude/{claude_cli,command,app}.py`

`CREATE_NO_WINDOW` is replaced with a `_NO_CONSOLE_KWARGS` dict that
expands to nothing on POSIX.  `app.crash_log` writes to `stderr` on non-Windows
instead of calling `MessageBoxW`.  `app.UsageMonitorForClaude.__init__`
installs the tray patch from `_macos_tray.py` when running on macOS.

### `usage_monitor_for_claude/popup.py`

`__init__`, `_on_loaded`, `_show_window`, `_close`, `_update_loop` and
`_resize_and_position` each grew a `sys.platform == 'darwin'` branch that
delegates to a `PopupController` instance instead of pywebview's
`webview.create_window` / `evaluate_js` / `destroy`.  A new
`_on_bridge_message` method bridges incoming WKScriptMessage payloads to
the original `_PopupApi.{close, open_url, report_height}` behaviour.
`_dismiss_watch` (Win32 hook pump) is left untouched but no longer started
on macOS - dismissal there is handled by ``NSEvent`` monitors inside
``_macos_popup``.

### `usage_monitor_for_claude/_macos_popup.py` (new)

Hosts the popup natively on macOS:

* `PopupController` - owns one ``NSPanel`` + ``WKWebView`` lifecycle; safe
  to drive from any thread (every public method dispatches through
  ``NSOperationQueue.mainQueue()``).
* `dispatch_main_async` / `dispatch_main_sync` - thin pyobjc wrappers
  around ``NSOperationQueue.mainQueue().addOperationWithBlock_`` with the
  same-thread fast path on the sync variant to avoid runloop deadlocks.
* `status_item_screen_frame` / `compute_popup_position` - pure helpers
  that convert the status bar button frame (Cocoa screen coords,
  bottom-left origin) into a popup origin centred horizontally on the
  icon, clamped to the owning ``NSScreen.visibleFrame``.
* `_BridgeHandler` (WKScriptMessageHandler), `_WindowDelegate`
  (NSWindowDelegate), `_NavigationDelegate` (WKNavigationDelegate) -
  pyobjc subclasses kept tiny so security review can read them at a
  glance.
* `_PYWEBVIEW_BRIDGE_JS` - a single ``WKUserScript`` injected at
  ``WKUserScriptInjectionTimeAtDocumentStart`` that defines
  ``window.pywebview.api.{close, open_url, report_height}`` so the
  existing ``popup/popup.js`` runs unchanged.

The panel is created at ``NSPopUpMenuWindowLevel`` with
``setHidesOnDeactivate_(False)`` (dismissal is owned by the NSEvent
monitor, not by AppKit's deactivation) and
``NSWindowCollectionBehaviorCanJoinAllSpaces |
NSWindowCollectionBehaviorFullScreenAuxiliary`` so it remains visible
when another app is in fullscreen mode.  The HTML is loaded with
``loadFileURL:allowingReadAccessToURL:`` so the WKWebView is permitted to
fetch sibling ``popup.css`` and ``popup.js``.

### `tests/test_api.py`

Existing file-based read tests are now `unittest.skipIf(sys.platform ==
'darwin', ...)`.  New `TestReadAccessTokenMacOS` class adds nine tests
covering legacy + hashed service names, OS error, non-zero exit, empty
output, malformed JSON, missing OAuth key, subprocess timeout, and an
explicit `test_token_never_written_to_disk` assertion.

### `tests/test_popup.py`

`TestTrayPosition` and `TestResizeAndPosition` are decorated with a new
``_WIN32_ONLY`` skip so the suite stays green on macOS without weakening
the Win32 assertions.  Pure data-transform tests
(`TestUsageEntries`, `TestSnapshotToDict`, `TestInitConfig`) run on both
platforms.

### `tests/test_macos_popup.py` (new)

Six tests for ``compute_popup_position`` (centering, vertical placement
below icon, edge clamping at left/right/top) and ``_color_from_hex``
(hex parse + safe fallback).  Skipped automatically off macOS.

### `scripts/mac_smoke_popup.py` (new)

End-to-end functional smoke test that launches the app, opens the popup,
introspects the live ``WKWebView`` DOM via
``evaluateJavaScript:completionHandler:``, asserts geometry against the
status item frame, exercises a close/re-open cycle, and (optionally)
captures screenshots into ``scripts/screenshots/`` when the parent
process has the Screen Recording permission.  Not part of ``unittest``
because it needs a live AppKit runloop and a real ``NSStatusItem``.

---

## Roadmap

### Phase 3 - Popup window (DONE)

Implemented as a **hybrid** of the two originally-considered paths: the
popup HTML/CSS/JS is reused **unchanged** (3A's fidelity goal), but the
host is a **native ``NSPanel`` + ``WKWebView``** rather than pywebview's
Cocoa backend (3B's auditability goal).  Decision rationale:

* pywebview's Cocoa backend insists on owning ``NSApplication.run()``,
  which pystray already owns - we cannot drive both event loops from the
  same main thread.
* Hosting the HTML in a dedicated ``NSPanel`` keeps the auditable popup
  HTML upstream, gives us full control of dismissal/positioning, and
  avoids pulling in pywebview's Cocoa code path on macOS at all.

A short ``WKUserScript`` injected at ``documentStart`` defines
``window.pywebview.api.{close, open_url, report_height}``, forwarding to
``window.webkit.messageHandlers.bridge`` so ``popup.js`` is platform-
agnostic.

See `_macos_popup.py`, the darwin branches in `popup.py`, the
`compute_popup_position` tests in `tests/test_macos_popup.py`, and the
end-to-end driver `scripts/mac_smoke_popup.py`.

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

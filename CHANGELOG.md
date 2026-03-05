# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Rate-limit errors (HTTP 429) now use exponential backoff instead of the short error interval, preventing the app from making the problem worse by polling faster
- API error messages now include the server's error detail (e.g. "Rate limited.") when available

### Fixed

- Error polling interval (30s) was shorter than normal polling (120s), causing more frequent requests after rate-limit errors instead of fewer

[Show all code changes](https://github.com/jens-duttke/usage-monitor-for-claude/compare/v1.3.0...HEAD)

## [1.3.0] - 2026-03-02

### Added

- Configurable usage alerts when quota exceeds defined thresholds (e.g., 80%, 95%), with separate settings for session and weekly quotas
- Time-aware alert mode (on by default) - suppresses notifications when usage is on track with elapsed time; `alert_time_aware_below` controls up to which threshold this applies, so high thresholds can always fire
- Extra usage section in the detail popup when extra usage is enabled on your account, with automatic currency symbol detection from the system locale (overridable via `currency_symbol` in the settings file)
- Status line in the popup showing when data was last updated and whether a refresh is in progress or failed

### Changed

- Server errors (HTTP 5xx) now show a specific "temporarily unavailable" message instead of the generic HTTP error
- Popup opens immediately with cached data instead of waiting for the API response; errors are shown in the status line while usage bars remain visible
- Popup grows away from the taskbar edge regardless of taskbar position (bottom, top, left, or right)

[Show all code changes](https://github.com/jens-duttke/usage-monitor-for-claude/compare/v1.2.0...v1.3.0)

## [1.2.0] - 2026-03-01

### Added

- Optional settings file (`usage-monitor-settings.json`) to customize polling intervals, popup colors, and icon colors

### Changed

- The code has been split into smaller, focused modules. Running from source now uses `python -m usage_monitor_for_claude`

### Fixed

- No longer sends repeated API requests after a 401 auth error; polls only re-read the credentials file until the token actually changes

[Show all code changes](https://github.com/jens-duttke/usage-monitor-for-claude/compare/v1.1.0...v1.2.0)

## [1.1.0] - 2026-02-28

### Added

- Tray icon supports the Windows light theme
- Session expiry detection with distinct "C!" tray icon when the Anthropic API returns HTTP 401, instead of showing a generic error
- Windows toast notification when quota resets after near-exhaustion (session >95% or weekly >98%), so users know Claude is available again without manually checking
- Adaptive polling that aligns to imminent quota resets for near-immediate feedback when quota refreshes
- Simplified Chinese (zh-CN) and Traditional Chinese (zh-TW) translations

### Changed

- Reassigned tray icon symbols for clearer meaning: "✕" for depleted quota, "!" for errors, "C!" for expired session

### Fixed

- Updated repository URL in setup instructions

[Show all code changes](https://github.com/jens-duttke/usage-monitor-for-claude/compare/v1.0.0...v1.1.0)

## [1.0.0] - 2026-02-26

Initial release.

### Added

- Windows system tray tool displaying live Claude.ai rate-limit usage
- Authentication via Claude Code OAuth token
- Adaptive polling intervals based on current usage levels
- Session (5h) and weekly (7d) limits shown as progress bars in tray icon and detail popup
- Dark-themed detail popup with usage breakdown
- PyInstaller build tooling (spec file + build script)
- 10-language i18n support

[Show all code changes](https://github.com/jens-duttke/usage-monitor-for-claude/releases/tag/v1.0.0)

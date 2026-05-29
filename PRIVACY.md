# Privacy Policy

**Usage Monitor for Claude** is a local desktop application that monitors your Claude API usage.

## Data Collection

This application does **not** collect, store, or transmit any personal data.

## Network Communication

The application communicates exclusively with `api.anthropic.com` to retrieve your current API usage
data. No other network connections are made.

## Credentials

The application reads your existing Claude OAuth token from a platform-appropriate location:

- **Windows:** the local Claude CLI configuration file (`~/.claude/.credentials.json`, or
  `$CLAUDE_CONFIG_DIR/.credentials.json` if set)
- **macOS:** the system Keychain, via `/usr/bin/security find-generic-password`

This token is:

- Used solely in HTTP Authorization headers to authenticate with the Anthropic API
- Cached in memory only for the lifetime of the process
- Never logged, stored elsewhere, copied, or transmitted to any third party

## Local Storage

The application does not write any usage data, credentials, or telemetry to disk. All usage data is
kept in memory only and discarded when the application closes. An optional settings file
(`usage-monitor-settings.json`) is read-only.

Two small bookkeeping files are written outside the credential and usage-data flow, never contain
your token, and exist only to keep a single instance running cleanly:

- **macOS:** a small single-instance lock at `~/.usage-monitor-for-claude.lock` containing only the
  running process's PID and the app version. When you enable autostart from the menu, a LaunchAgent
  plist is written at `~/Library/LaunchAgents/com.usage-monitor-for-claude.plist`; disabling
  autostart deletes it.
- **Windows:** a named mutex and the autostart entry under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` when "Start with Windows" is enabled.

## Third-Party Services

The application does not integrate with any analytics, tracking, advertising, or telemetry services.

## Contact

For questions about this privacy policy, please open an issue at
https://github.com/jens-duttke/usage-monitor-for-claude/issues

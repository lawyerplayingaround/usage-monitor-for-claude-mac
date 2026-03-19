# Privacy Policy

**Usage Monitor for Claude** is a local desktop application that monitors your Claude API usage.

## Data Collection

This application does **not** collect, store, or transmit any personal data.

## Network Communication

The application communicates exclusively with `api.anthropic.com` to retrieve your current API usage
data. No other network connections are made.

## Credentials

The application reads your existing Claude OAuth token from the local Claude CLI configuration file
(`~/.claude/.credentials.json`). This token is:

- Used solely in HTTP Authorization headers to authenticate with the Anthropic API
- Never logged, stored elsewhere, copied, or transmitted to any third party

## Local Storage

The application does not write any files. All usage data is kept in memory only and discarded when
the application closes. An optional settings file (`usage-monitor-settings.json`) is read-only.

## Third-Party Services

The application does not integrate with any analytics, tracking, advertising, or telemetry services.

## Contact

For questions about this privacy policy, please open an issue at
https://github.com/jens-duttke/usage-monitor-for-claude/issues

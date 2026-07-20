# Build notes for this fork

This is a fork of [`jens-duttke/usage-monitor-for-claude`](https://github.com/jens-duttke/usage-monitor-for-claude).
Upstream's repository is the canonical source - their PR template, code
review conventions, and `.claude/CLAUDE.md` apply here too.

The notes below cover only what's specific to **building the fork
distribution** (both the portable `UsageMonitorForClaude.exe` and the
optional Inno Setup installer).

## Prerequisites

| Tool | Version | How to install |
|---|---|---|
| Python | 3.11+ (tested 3.13.7) | https://www.python.org/downloads/ |
| Inno Setup | 6.x | `winget install JRSoftware.InnoSetup` |

Inno Setup is only required if you want to (re)build the installer .exe.
For the portable build, Python alone is enough.


## Tests

Standard unittest, no extra dependencies:

```powershell
python -m unittest discover -s tests
```

This applies to every change (Python module, locale file, settings file)
per upstream's `.claude/CLAUDE.md`.

## Distributing a fork release

Upload BOTH artifacts to a GitHub Releases tag on this fork:

- `UsageMonitorForClaude.exe` (portable; same workflow as upstream)
- `UsageMonitorForClaude-Setup-v<version>.exe` (installer; this fork's addition)

The Release notes should reuse the corresponding `## [<version>]` section
from `CHANGELOG.md`.

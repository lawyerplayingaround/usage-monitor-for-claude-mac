# Configuration

All settings work out of the box - no configuration file is needed. To customize behavior, create a file called `usage-monitor-settings.json` with only the keys you want to change:

```json
{
  "poll_interval": 180,
  "bar_fg": "#00cc66",
  "bar_fg_warn": "#ff6600"
}
```

The app searches for this file in two locations (first match wins):

1. **Next to the EXE** (or project root when running from source)
2. **`~/.claude/usage-monitor-settings.json`**

The app never creates or modifies this file. To start, create an empty file and add keys as needed. Settings are read at startup - after editing the file, use the **Restart** option in the tray context menu to apply changes.

## Alert thresholds

Configure usage percentage thresholds that trigger Windows notifications. Session and weekly quotas have separate thresholds since their time horizons differ significantly. Set to an empty array `[]` to disable alerts for a specific quota type.

| Key | Default | Description |
|-----|---------|-------------|
| `alert_thresholds_five_hour` | `[50, 80, 95]` | Thresholds (%) for Session (5hr) |
| `alert_thresholds_seven_day` | `[95]` | Thresholds (%) for all Weekly quotas (7 day, Sonnet, Opus) |
| `alert_thresholds_extra_usage` | `[50, 80, 95]` | Thresholds (%) for Extra Usage (paid overage) |
| `alert_time_aware` | `true` | Only alert when usage outpaces elapsed time |
| `alert_time_aware_below` | `90` | Time-aware check applies only to thresholds below this value; thresholds at or above always fire |

## Event commands

Run a shell command when a usage event occurs. See [Event Commands](event-commands.md) for examples and available environment variables.

| Key | Default | Description |
|-----|---------|-------------|
| `on_reset_command` | *(none)* | Shell command to run when a quota resets (usage drops) |
| `on_threshold_command` | *(none)* | Shell command to run when usage crosses a configured alert threshold |

## Polling intervals

| Key | Default | Description |
|-----|---------|-------------|
| `poll_interval` | `180` | Seconds between API updates |
| `poll_fast` | `120` | Seconds when usage is actively increasing |
| `poll_fast_extra` | `2` | Extra fast polls after usage stops increasing |
| `poll_error` | `30` | Seconds after a transient error (5xx, network). Rate-limit errors (429) use exponential backoff instead |
| `max_backoff` | `900` | Maximum backoff in seconds for rate-limit errors (15 min) |
| `idle_pause` | `300` | Seconds of inactivity before polling pauses (0 = disable). Polling also pauses when the workstation is locked |

## Language

| Key | Default | Description |
|-----|---------|-------------|
| `language` | *(auto-detected)* | Override the UI language with a language code. Available: `de`, `en`, `es`, `fr`, `hi`, `id`, `it`, `ja`, `ko`, `pt-BR`, `uk`, `zh-CN`, `zh-TW` |

## Currency

The Anthropic API does not include currency information, so the app detects the currency symbol from your Windows locale settings. If your Windows locale currency differs from the currency Anthropic bills you in, you can override just the symbol here. Number formatting (decimal separator, symbol position) always follows your system locale.

| Key | Default | Description |
|-----|---------|-------------|
| `currency_symbol` | *(auto-detected)* | Override the auto-detected currency symbol (e.g., `"$"`, `"€"`, `"¥"`) |

## Tray icon colors

Override individual channels as RGBA arrays `[R, G, B, A]` (0-255). Unspecified keys keep their defaults.

| Key | Default | Description |
|-----|---------|-------------|
| `icon_light` | `{"fg": [255,255,255,255], "fg_half": [255,255,255,80], "fg_dim": [255,255,255,140]}` | Light icons for dark taskbar |
| `icon_dark` | `{"fg": [0,0,0,255], "fg_half": [0,0,0,80], "fg_dim": [0,0,0,140]}` | Dark icons for light taskbar |

## Popup colors

| Key | Default | Description |
|-----|---------|-------------|
| `bg` | `"#1e1e1e"` | Background |
| `fg` | `"#cccccc"` | Text |
| `fg_dim` | `"#888888"` | Dimmed text (labels, reset times) |
| `fg_heading` | `"#ffffff"` | Section headings |
| `bar_bg` | `"#333333"` | Progress bar background |
| `bar_fg` | `"#4a9eff"` | Progress bar fill |
| `bar_fg_warn` | `"#e05050"` | Progress bar fill when usage outpaces elapsed time |

# Migrate SwiftBar Plugins to Linux (Argos)

A skill for migrating **SwiftBar** / **xbar** / **BitBar** plugins to run on Linux via **Argos** — a GNOME Shell extension that supports the same output format.

## Overview

| macOS | Linux counterpart |
|---|---|
| SwiftBar menu bar app | Argos (GNOME Shell extension) |
| `font=Menlo` | `font='Noto Sans Mono'` |
| `font=PingFangSC` | `font='Noto Sans CJK SC'` |
| `pbcopy` / `pbpaste` | `xclip` (X11) / `wl-copy` (Wayland) |
| `osascript` dialog | `zenity --entry` |
| `kimi-webbridge` binary | Must be available for the arch, or use alternative token refresh |

## Steps

### 1. Install Argos

Argos is a GNOME Shell extension that reads scripts from `~/.config/argos/` and displays their output in the top panel.

```bash
# Download and install
curl -L -o /tmp/argos.zip https://github.com/p-e-w/argos/archive/refs/heads/master.zip
cd /tmp && unzip -q argos.zip
mkdir -p ~/.local/share/gnome-shell/extensions
cp -r /tmp/argos-master/argos@pew.worldwidemann.com ~/.local/share/gnome-shell/extensions/

# Enable via gsettings
gsettings set org.gnome.shell enabled-extensions \
  "$(gsettings get org.gnome.shell enabled-extensions | sed "s|]|, 'argos@pew.worldwidemann.com']|")"
```

Then **log out and log back in** for the extension to load.

### 2. Place scripts in `~/.config/argos/`

```bash
mkdir -p ~/.config/argos
cp /path/to/plugin.10m.py ~/.config/argos/
chmod +x ~/.config/argos/*.py
```

Argos uses the same naming convention as BitBar/SwiftBar for refresh intervals:

| Filename pattern | Refresh interval |
|---|---|
| `name.1m.py` | every 1 minute |
| `name.5m.py` | every 5 minutes |
| `name.10m.py` | every 10 minutes |
| `name.1h.py` | every 1 hour |
| `name.1d.py` | every 1 day |

### 3. Replace macOS-specific references

**Fonts** — SwiftBar plugins commonly reference macOS-only fonts:

| SwiftBar font | Linux replacement |
|---|---|
| `Menlo` | `'Noto Sans Mono'` |
| `PingFangSC` | `'Noto Sans CJK SC'` |
| `SF Mono` | `'Noto Sans Mono'` |
| `Helvetica Neue` | `'Noto Sans'` |

Use single quotes inside Python f-strings (avoid syntax error):

```python
# Before
print(f"... | font=Menlo size=13")
# After
print(f"... | font='Noto Sans Mono' size=13")
```

Argos parses attributes via `GLib.shell_parse_argv`, which handles quoting.

**Font sizes** — Conventions used across already-migrated plugins:

| Usage | Font | Size |
|---|---|---|
| Menu bar title | (inherit, no font=) | `10` |
| Detail lines (CJK text) | `Noto Sans CJK SC` | `9` |
| Detail lines (monospaced / numbers) | `Noto Sans Mono` | `9` |
| Key numbers (balance, etc.) | `Noto Sans Mono` | `10` |

**`pbcopy`** — Replace with `xclip` (X11) or `wl-copy` (Wayland):

```python
# Before
subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)

# After (detect Wayland vs X11)
import os
clip = os.environ.get("WAYLAND_DISPLAY") and "wl-copy" or "xclip"
subprocess.Popen([clip], stdin=subprocess.PIPE, text=True)
```

**`osascript` dialog** — Replace with `zenity` (GTK) or `yad`:

```python
# Before
result = subprocess.run(["osascript", "-e", '...'], ...)

# After
result = subprocess.run(["zenity", "--entry", "--text=请输入任务内容"], capture_output=True, text=True, timeout=60)
```

### 4. Test the script directly

```bash
python3 ~/.config/argos/plugin.10m.py
```

Expected: valid Argos output lines (pipe-delimited key=value attributes). No Python syntax errors.

### 5. Verify platform-specific paths

Some SwiftBar plugins reference `~/.kimi-code/` or `~/.kimi-webbridge/`. These binaries may need Linux versions:

| File | Linux status |
|---|---|
| `~/.kimi-code/bin/kimi` | Linux aarch64 binary exists ✓ |
| `~/.kimi-code/credentials/kimi-code.json` | Present ✓ |
| `~/.kimi-webbridge/bin/kimi-webbridge` | Not available on this system — skip |

### 6. Re-login

Argos only loads at GNOME Shell startup. Log out and log back in (or restart GNOME Shell) for the scripts to appear in the top panel.

## Attribute compatibility

Argos supports the following BitBar/SwiftBar output attributes:

| Attribute | Supported | Notes |
|---|---|---|
| `bash=` | Yes | Runs a shell command |
| `param1=` .. `param9=` | Yes | Appended to `bash=` command |
| `terminal=false` | Yes | Runs silently |
| `refresh=true` | Yes | Refreshes script after action |
| `href=` | Yes | Opens URL with default browser |
| `size=` | Yes | Pango font size (pt) |
| `color=` | Yes | Named color or hex |
| `font=` | Yes | Pango font family |
| `image=` | Yes | Base64 PNG image |
| `length=` | Yes | Truncate text to N chars |
| `dropdown=false` | **No** | Ignored — always shows dropdown |
| `tooltip=` | **No** | Ignored |
| ANSI escape codes | Yes | Rendered via Pango markup |
| `:emoji:` | Yes | Custom emoji map |

## SwiftBar metadata comments

Headers like `<swiftbar.hideAbout>true</swiftbar.hideAbout>` are specific to SwiftBar and ignored by Argos. They may be left in place or removed.

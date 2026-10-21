## What's new in v1.0.3

**Fixes**

- `ssh_args` and `extra_ssh_args` written as one string keep Windows backslashes:
  `-i C:\keys\id_ed25519` no longer turns into `C:keysid_ed25519`. Quotes group
  text with spaces; an unbalanced quote no longer breaks the plugin.
- One broken destination no longer hides all the others. Each unusable entry gets
  its own **Destination skipped** row with the reason; press Enter on it to open the
  destinations file.
- A `host` or `user` that starts with `-` is refused, so a config value can no
  longer be read by ssh as an option such as `ProxyCommand`. Aliases may now
  contain spaces and non-Latin letters.
- PowerShell quoting handles the Unicode quote characters PowerShell treats as
  string delimiters, and PowerShell mode refuses an argument that is exactly `--%`,
  which PowerShell drops however it is quoted.
- A refused launch logs which check failed (terminal and character), never the
  argument itself.

**Documentation**

- README corrected: `-F` is passed for every imported alias (so the system-wide
  OpenSSH config is not read for them), `Include` is not followed yet (with a
  workaround), logs restart after a plugin update, Shift+Enter opens the context
  menu.

## SSH Launcher

Launch an SSH session from Flow Launcher by typing `ssh <alias>`.

- Editable JSON destinations, with aliases, hostnames, users, ports, descriptions,
  and optional SSH arguments.
- Import literal aliases from an OpenSSH config while retaining OpenSSH's key,
  proxy and forwarding settings.
- Launch in Windows Terminal, PowerShell or Command Prompt.
- Search by alias, hostname or description; copy the SSH command or open the
  configuration file from the result menu.
- Configuration stored outside the versioned plugin folder so updates preserve it.
- Standard-library-only runtime, bundled icons, no telemetry or credential storage.

### Requirements

Windows 10/11, Flow Launcher 2.0.3+, OpenSSH Client, and Flow's Python 3.11 runtime.
Windows Terminal is required for the default terminal mode.

### Installation

Download `Flow.Launcher.Plugin.SSHLauncher.zip` and use
`pm install <absolute-path-to-the-downloaded-zip>` in Flow Launcher.

The store listing is subject to Flow Launcher maintainer approval. The release ZIP
contains runtime files only; tests, logs and personal configuration are excluded.

MIT license. Author: Vadim Funtikov.

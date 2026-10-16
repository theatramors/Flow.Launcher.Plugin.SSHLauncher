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

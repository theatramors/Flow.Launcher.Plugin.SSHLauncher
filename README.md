# SSH Launcher for Flow Launcher

Open SSH sessions from Flow Launcher using short, editable destination aliases.
No third-party Python packages, credential storage, or background network service.

```text
ssh                List destinations and the configuration shortcut
ssh demo           Find a destination by alias, hostname or description
ssh edit           Find the “Edit destinations file” shortcut
```

**Author:** Vadim Funtikov · **License:** [MIT](LICENSE)

## Requirements and installation

- Windows 10/11 with [Flow Launcher](https://www.flowlauncher.com/) **2.0.3 or newer**.
- Windows OpenSSH Client (`ssh.exe`) installed and available on `PATH`.
- [Windows Terminal](https://aka.ms/terminal) for the default launch mode; PowerShell
  and Command Prompt are alternative terminal modes.
- Flow Launcher's embedded Python **3.11** environment (Flow can install this for you).

Once accepted into the Plugin Store, search for **SSH Launcher** in Flow's plugin
manager. Before the listing is approved, download
`Flow.Launcher.Plugin.SSHLauncher.zip` from this repository's **Releases** page and
install it with:

```text
pm install <absolute-path-to-the-downloaded-zip>
```

Open Flow Launcher, type `ssh`, select a destination, and press **Enter**.
Authentication, passphrase prompts, host-key verification, and interactive input
are handled by OpenSSH in the terminal—not by the plugin.

## Controls

| Action | Default control |
| --- | --- |
| Open the selected connection | Enter |
| Copy its SSH command (PowerShell syntax) | Ctrl+C |
| Open the result context menu | Ctrl+O or Shift+Enter (or your configured context-menu shortcut) |
| Complete `ssh <alias>` | Flow's configured autocomplete shortcut (normally Ctrl+Tab) |

The context menu offers Windows Terminal, PowerShell, Command Prompt, copy command,
and the editable destinations file. Flow's shortcuts can be customized in settings.

## Configuration

Type `ssh edit` and select **Edit destinations file**, or open:

```text
%APPDATA%\FlowLauncher\Settings\Plugins\SSH Launcher\destinations.json
```

The first run creates a template with an inline `_readme` reference. Configuration
changes are picked up on the next query; no plugin restart is needed. The file is
stored outside the versioned plugin directory so updating the plugin preserves it.

A minimal example:

```json
{
  "settings": {
    "terminal": "wt",
    "wt_window": "new",
    "ssh": "ssh",
    "include_ssh_config": true,
    "ssh_config_path": "~/.ssh/config",
    "extra_ssh_args": ["-o", "ServerAliveInterval=30"],
    "editor": ""
  },
  "destinations": [
    {
      "alias": "demo",
      "host": "server.example.com",
      "user": "demo",
      "port": 2222,
      "description": "Example development server"
    }
  ]
}
```

### Global settings

| Setting | Purpose |
| --- | --- |
| `terminal` | `wt` (default), `powershell`, or `cmd` |
| `wt_window` | Optional Windows Terminal window identifier; `new` forces a new window |
| `ssh` | SSH executable name or full path |
| `include_ssh_config` | Discover literal `Host` aliases in the configured OpenSSH file |
| `ssh_config_path` | OpenSSH configuration path; defaults to `~/.ssh/config` |
| `extra_ssh_args` | Array of arguments added to each SSH invocation |
| `editor` | Optional editor executable or full path; empty uses the file association, with Notepad fallback |

### Destination fields

`alias` and `host` are required for JSON-defined destinations. Optional fields:

- `user`, `port`, `description`.
- `ssh_args`: an array of SSH arguments, for example
  `["-i", "C:/Users/YourName/.ssh/id_ed25519"]`.
- `command`: optional remote command; for an interactive session, leave it unset.
- `terminal`: override the global terminal choice for this destination.
- `icon`: optional local icon path or HTTP(S) icon URL. Remote icons are fetched by
  Flow Launcher; omit this setting to use the bundled icon without a remote fetch.

Prefer JSON arrays for argument lists. `ssh_args` and `extra_ssh_args` also accept
a single string: whitespace separates arguments, single or double quotes group text
that contains spaces, and backslashes are ordinary characters, so Windows paths work
unquoted. Use an array when an argument itself contains a quote character, such as
a path with an apostrophe. The copied command uses **PowerShell syntax**,
regardless of the selected terminal.

Entries the plugin cannot use are not dropped silently. Each gets its own
**Destination skipped** row with the reason, shown on the plain `ssh` query and when
your search matches its alias; press Enter on it to open the file. This covers an
entry without an alias or host, a duplicate alias, a `port` that is not a number or
service name, `ssh_args` that is neither an array nor a string, and a `host` or
`user` that starts with `-` or contains whitespace or control characters. The
leading `-` rule is a safety rule: ssh would read the value as an option, and
options such as `ProxyCommand` run local programs. The alias itself is only a
label, so it may contain spaces or non-Latin letters.

For safety, Windows Terminal mode refuses arguments or tab titles containing `;`
(the separator for multiple Terminal actions). Command Prompt mode refuses literal
`%` and double quotes inside arguments, which cannot be passed reliably through its
parser; use PowerShell for those remote commands. PowerShell mode refuses an
argument that is exactly `--%`, which PowerShell drops however it is quoted; the
copied command has the same limitation, so launch such a destination in Windows
Terminal or Command Prompt. CR, LF and NUL characters are rejected in every terminal
mode. A refused or failed launch leaves Flow open and logs which check failed (the
terminal and the offending character), never the argument itself.

Do not put passwords or tokens in this file. Treat configuration from other people as code:
SSH supports options such as `ProxyCommand` that deliberately run local programs.

### OpenSSH aliases

With `include_ssh_config` enabled, the plugin discovers literal aliases such as:

```sshconfig
Host demo
    HostName server.example.com
    User demo
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump bastion.example.com
```

Imported destinations connect using the **alias**, leaving OpenSSH in charge of
identity files, jump hosts, forwards, and other SSH options. The configured
`ssh_config_path` is always passed to OpenSSH with `-F` (the default
`~/.ssh/config` included), so OpenSSH reads exactly that file. As with any `-F`,
the system-wide `%ProgramData%\ssh\ssh_config` is not read for these connections.
JSON-defined destinations take precedence when an alias appears in both sources.

Alias discovery is not a complete OpenSSH parser. Wildcards and conditional blocks
are not expanded into a list of hosts; OpenSSH remains the authority for resolving
the selected connection. `Include` directives are not followed yet, so a host
defined only in an included file is not listed. As a workaround, add a JSON
destination whose `host` is that alias: it runs as plain `ssh <alias>`, which
OpenSSH resolves through your normal config, `Include` lines included. Note that
Windows OpenSSH (checked with 9.6p1) silently ignores `Include` paths that start
with a drive letter, such as `C:/Users/...`; write them relative to `~/.ssh` or as
`~/...` instead.

## Privacy and troubleshooting

- The plugin does not collect telemetry or store SSH credentials.
- It reads your destinations JSON and, when enabled, the specified SSH config.
- Logs are written locally to `logs/ssh-launcher.log` inside the plugin folder.
  Flow installs each plugin version in a new folder, so the log starts over after an
  update. Logs, user configuration and tests are **not included in release ZIPs**.
- Review diagnostics before sharing them: errors can contain local file paths.
- Check that `ssh` works from a terminal first. If Windows Terminal is unavailable,
  set `terminal` to `powershell` or `cmd`.
- Back up `destinations.json` before manual edits. A reset from the plugin's context
  menu preserves the previous file as a uniquely named backup before replacing it.

Report problems using this repository's **Issues** tab. Include your Flow Launcher
version, chosen terminal and a sanitized example—never private keys or credentials.

## Development and releases

Runtime code uses only the Python standard library. From a source checkout:

```text
python -m unittest discover -s tests -p "test_*.py" -v
python tests/drive_rpc.py
python tools/test_package.py
python tools/package.py
python tools/smoke_release.py dist/Flow.Launcher.Plugin.SSHLauncher.zip
```

CI runs on Windows and Linux with Python 3.11, including a smoke test with Flow's
Windows embedded Python 3.11.4 runtime. Tests use synthetic fixtures; they do not
connect to real SSH servers. The optional `tests/windows_live_test.py` opens
terminal windows and exercises the clipboard; it is for manual interactive use,
not unattended CI.

The packager uses an explicit runtime-file allowlist. Pushing a version tag that
matches `plugin.json` (for example, `v1.0.3`) runs tests, builds a ZIP with
`plugin.json` at the root, and publishes it with a SHA-256 checksum. Once the plugin
is listed, Flow's manifest updater can discover subsequent GitHub Releases.

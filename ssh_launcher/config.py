# -*- coding: utf-8 -*-
"""Destination config: where it lives, how it is parsed, how it is created."""

from __future__ import annotations

import json
import os
import shutil
import time

from .arguments import is_safe_endpoint, is_safe_label, is_safe_port, split_arguments

CONFIG_NAME = "destinations.json"
PLUGIN_NAME = "SSH Launcher"
SETTINGS_RELATIVE = os.path.join("FlowLauncher", "Settings", "Plugins", PLUGIN_NAME)

DEFAULT_SETTINGS = {
    "terminal": "wt",
    "wt_window": "",
    "ssh": "ssh",
    "include_ssh_config": True,
    "ssh_config_path": "~/.ssh/config",
    "extra_ssh_args": [],
    "editor": "",
}

README_LINES = [
    "SSH destinations for the Flow Launcher 'ssh' plugin.",
    "Changes are picked up automatically - no restart needed, just type again.",
    "",
    "Settings:",
    "  terminal        default terminal: wt (Windows Terminal), powershell or cmd",
    "  wt_window       Windows Terminal -w value; empty = most recent window (default),",
    "                  'new' = always a new window, '0' = current window",
    "  ssh             ssh executable or full path (default: ssh)",
    "  extra_ssh_args  arguments added to every connection, e.g. ['-o','ServerAliveInterval=30']",
    "  include_ssh_config  also list Hosts from ssh_config_path (their aliases work as-is)",
    "  ssh_config_path path to the ssh config file (default: ~/.ssh/config)",
    "  editor          editor for 'Edit destinations file': empty = default .json handler",
    "",
    "Per destination:",
    "  alias         required - what you type after 'ssh '",
    "  host          required - hostname or IP",
    "  user          optional - login user",
    "  port          optional - non-22 port becomes -p <port>",
    "  description   optional - shown in the result subtitle",
    "  ssh_args      optional - list of extra ssh arguments, e.g. ['-i','C:/keys/id_ed25519']",
    "                  (one string also works: spaces separate, quotes group, \\ is literal)",
    "  command       optional - command or list of arguments to run remotely",
    "  terminal      optional - override the default terminal for this destination",
    "  icon          optional - png/ico path or URL shown instead of the default icon",
    "",
    "Example:",
    '  {"alias": "demo", "host": "server.example.com", "user": "demo", "port": 22,',
    '   "description": "example host", "ssh_args": ["-i", "~/.ssh/id_ed25519"]}',
]


def config_path(plugin_settings_dir=None):
    """Absolute path of destinations.json.

    Flow hands the plugin its own settings folder in the ``initialize`` call
    (``%APPDATA%\\FlowLauncher\\Settings\\Plugins\\SSH Launcher``); the fallback
    mirrors what Flow computes so a manual run still finds the same file.
    """
    if plugin_settings_dir:
        base = plugin_settings_dir
    else:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = os.path.join(appdata, SETTINGS_RELATIVE)
    return os.path.join(base, CONFIG_NAME)


def backup_file(path, log=None):
    """Copy *path* to a unique timestamped sibling and return the backup path.

    The copy is read back and compared before it is accepted, so a failed or
    partial write raises instead of letting the caller destroy the original.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = "%s.%s" % (path, stamp)
    candidate = base + ".bak"
    counter = 1
    while os.path.exists(candidate):
        candidate = "%s.%d.bak" % (base, counter)
        counter += 1
    shutil.copyfile(path, candidate)
    with open(path, "rb") as source, open(candidate, "rb") as copy:
        if source.read() != copy.read():
            raise IOError("backup of %s does not match the original" % CONFIG_NAME)
    if log:
        log.info("backed up the destinations file before overwriting it")
    return candidate


def write_default(path):
    data = {
        "_readme": README_LINES,
        "settings": dict(DEFAULT_SETTINGS),
        "destinations": [],
    }
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return data


def _note(problems, message, alias=""):
    """Record a user-facing problem.

    Kept out of the log on purpose: it names the destination, and the log is
    pasted into public bug reports.  ``alias`` only titles the result row for a
    destination that was skipped.
    """
    if problems is not None:
        problems.append({"alias": str(alias or ""), "message": message})


def _entry_label(alias, index):
    alias = str(alias or "").strip()
    return "'%s'" % alias if alias else "entry #%d" % (index + 1)


def _normalise_destination(item, log=None, problems=None, index=0):
    """Validate one destination.

    Returns the normalised dict, or ``None`` when the entry cannot be used.
    Argument strings are split here, once, so a malformed entry is reported as
    one "skipped" row instead of breaking every other result at query time.
    """
    label = _entry_label(item.get("alias") if isinstance(item, dict) else None, index)
    if not isinstance(item, dict):
        if log:
            # Entry contents may hold hosts and users: keep the log generic.
            log.warn("ignoring destination entry that is not an object")
        _note(problems, "%s in %s is not an object and was skipped" % (label, CONFIG_NAME))
        return None

    dest = dict(item)
    alias = dest.get("alias")
    host = dest.get("host") or dest.get("hostname")
    if not alias or not host:
        if log:
            log.warn("ignoring destination without alias/host")
        _note(problems, "%s in %s has no alias or host and was skipped" % (label, CONFIG_NAME),
              alias)
        return None

    alias = str(alias).strip()
    host = str(host).strip()
    user = str(dest.get("user")).strip() if dest.get("user") else ""
    dest["alias"] = alias
    dest["host"] = host
    if user:
        dest["user"] = user
    else:
        dest.pop("user", None)

    # The alias is only a label for JSON entries (ssh gets user@host), so it
    # may hold spaces or Cyrillic; host and user are real ssh arguments.
    checks = (("alias", alias, is_safe_label), ("host", host, is_safe_endpoint),
              ("user", user, is_safe_endpoint))
    for field, value, is_safe in checks:
        if value and not is_safe(value):
            if log:
                # Field name only: the value may hold a host name or a path.
                log.warn("ignoring a destination with an unsafe %s value" % field)
            _note(
                problems,
                "%s in %s was skipped: the %s value %r contains whitespace or control "
                "characters, or starts with '-', which ssh would read as an option."
                % (label, CONFIG_NAME, field, value),
                alias,
            )
            return None

    port = dest.get("port")
    if port in (None, "", 0, "0"):
        dest["port"] = None
    elif not is_safe_port(port):
        if log:
            log.warn("ignoring a destination with an unsafe port value")
        _note(
            problems,
            "%s in %s was skipped: %r is not a port number or service name."
            % (label, CONFIG_NAME, str(port)),
            alias,
        )
        return None
    else:
        dest["port"] = str(port).strip()

    raw_args = dest.get("ssh_args")
    if raw_args in (None, "", []):
        dest.pop("ssh_args", None)
    elif not isinstance(raw_args, (str, list, tuple)):
        if log:
            log.warn("ignoring a destination whose ssh_args is not a list or string")
        _note(
            problems,
            "%s in %s was skipped: ssh_args must be a list or a string." % (label, CONFIG_NAME),
            alias,
        )
        return None
    else:
        dest["ssh_args"] = split_arguments(raw_args, log)

    command = dest.get("command")
    if isinstance(command, (list, tuple)):
        dest["command"] = [str(part) for part in command if part is not None]
    elif command in (None, ""):
        dest.pop("command", None)
    elif not isinstance(command, str):
        dest["command"] = str(command)

    dest["source"] = "config"
    return dest


def parse_config(data, log=None, problems=None):
    """Return (settings, destinations) from raw config data.

    ``problems`` - when given, a list - collects one human-readable sentence for
    every entry that was skipped, so the plugin can show them as result rows.
    """
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        raw_settings = data.get("settings")
        if isinstance(raw_settings, dict):
            for key in DEFAULT_SETTINGS:
                if key in raw_settings and raw_settings[key] is not None:
                    settings[key] = raw_settings[key]

    raw_destinations = []
    if isinstance(data, dict):
        raw = data.get("destinations")
        if isinstance(raw, list):
            raw_destinations = raw
        elif isinstance(raw, dict):
            raw_destinations = [
                dict(value, alias=value.get("alias", key)) if isinstance(value, dict) else {"alias": key, "host": value}
                for key, value in raw.items()
            ]

    destinations = []
    seen = set()
    for index, item in enumerate(raw_destinations):
        dest = _normalise_destination(item, log, problems, index)
        if dest is None:
            continue
        key = dest["alias"].lower()
        if key in seen:
            if log:
                log.warn("duplicate destination alias ignored")
            _note(problems, "%s appears more than once in %s and was skipped"
                  % (_entry_label(dest["alias"], index), CONFIG_NAME), dest["alias"])
            continue
        seen.add(key)
        destinations.append(dest)
    return settings, destinations


def _split_config_line(line):
    """Split an ssh_config line into (keyword, value).

    OpenSSH accepts both ``Keyword value`` and ``Keyword=value``.  Returns
    ``(None, None)`` for blank/keyword-less lines.
    """
    if "=" in line:
        head, _sep, rest = line.partition("=")
        head = head.strip()
        if head and not any(ch.isspace() for ch in head):
            return head, rest.strip()
    parts = line.split(None, 1)
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1].strip()


def _literal_patterns(value):
    """The Host patterns OpenSSH would match literally (no wildcards)."""
    patterns = []
    for token in value.split():
        if token.startswith("!"):
            continue
        if any(ch in token for ch in "*?!"):
            continue
        if token not in patterns:
            patterns.append(token)
    return patterns


def read_ssh_config(settings, log=None):
    """Destinations declared as literal ``Host`` names in the user's ssh config.

    Only the names are collected; everything else (IdentityFile, ProxyJump,
    Match blocks, wildcard patterns) is deliberately left to OpenSSH itself via
    ``-F <file> <alias>``.  ``host``/``user``/``port`` are best-effort metadata
    for search and display only - they are never injected into the command.
    """
    path = os.path.expanduser(str(settings.get("ssh_config_path") or ""))
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except Exception as exc:
        if log:
            log.warn("cannot read ssh config: %s" % exc)
        return []

    found = []
    block = []  # every destination created by the most recent Host line
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, value = _split_config_line(stripped)
        if key is None:
            continue
        key = key.lower()
        if key == "host":
            block = []
            for pattern in _literal_patterns(value):
                dest = {
                    "alias": pattern,
                    # OpenSSH falls back to the alias itself when no HostName
                    # is given, so that is the best guess for display/search.
                    "host": pattern,
                    "source": "ssh_config",
                    "ssh_config_path": path,
                }
                block.append(dest)
                found.append(dest)
        elif key == "match":
            # A Match block ends the preceding Host block; its directives must
            # not leak into the entries collected above.
            block = []
        elif not block:
            continue
        elif key == "hostname":
            for dest in block:
                dest["host"] = value
        elif key == "user":
            for dest in block:
                dest["user"] = value
        elif key == "port":
            for dest in block:
                dest["port"] = value

    # ssh configs routinely repeat a Host block; keep the first of each alias.
    unique = []
    seen = set()
    for dest in found:
        key = dest["alias"].lower()
        if key in seen:
            continue
        seen.add(key)
        dest["description"] = "from ssh config"
        unique.append(dest)
    return unique


def load(path, log=None, problems=None):
    """Read the config file (creating it when missing).

    Returns (settings, destinations, error_message).  ``problems`` (a list, when
    given) receives one sentence per skipped entry.
    """
    error = None
    if not os.path.isfile(path):
        try:
            data = write_default(path)
            if log:
                log.info("created the default destinations file")
        except Exception as exc:
            if log:
                log.error("cannot create the destinations file: %s" % exc)
            data = {"settings": dict(DEFAULT_SETTINGS), "destinations": []}
            error = "Cannot create %s: %s" % (path, exc)
    else:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except Exception as exc:
            if log:
                log.error("cannot parse the destinations file: %s" % exc)
            return dict(DEFAULT_SETTINGS), [], "%s is not valid JSON: %s" % (CONFIG_NAME, exc)

    settings, destinations = parse_config(data, log, problems)
    return settings, destinations, error

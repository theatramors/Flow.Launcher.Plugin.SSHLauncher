# -*- coding: utf-8 -*-
"""Destination config: where it lives, how it is parsed, how it is created."""

from __future__ import annotations

import json
import os
import shutil
import time

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


def _normalise_destination(item, alias_hint=None, log=None):
    if not isinstance(item, dict):
        if log:
            # Entry contents may hold hosts and users: keep the log generic.
            log.warn("ignoring destination entry that is not an object")
        return None

    dest = dict(item)
    alias = dest.get("alias") or alias_hint
    host = dest.get("host") or dest.get("hostname")
    if not alias or not host:
        if log:
            log.warn("ignoring destination without alias/host")
        return None

    dest["alias"] = str(alias).strip()
    dest["host"] = str(host).strip()
    if dest.get("user"):
        dest["user"] = str(dest["user"]).strip()
    if dest.get("port") in ("", 0):
        dest["port"] = None
    dest["source"] = "config"
    return dest


def parse_config(data, log=None):
    """Return (settings, destinations) from raw config data."""
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
    for item, hint in _iter_with_hints(raw_destinations):
        dest = _normalise_destination(item, hint, log)
        if dest is None:
            continue
        key = dest["alias"].lower()
        if key in seen:
            if log:
                log.warn("duplicate destination alias ignored")
            continue
        seen.add(key)
        destinations.append(dest)
    return settings, destinations


def _iter_with_hints(items):
    for item in items:
        yield item, None


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


def load(path, log=None):
    """Read the config file (creating it when missing).

    Returns (settings, destinations, error_message).
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

    settings, destinations = parse_config(data, log)
    return settings, destinations, error

# -*- coding: utf-8 -*-
"""Query/context-menu logic and the actions Flow Launcher triggers."""

from __future__ import annotations

import os
import traceback

from . import config as config_module
from . import launcher
from . import matcher

DEFAULT_ICON = os.path.join("Images", "ssh.png")
CONFIG_ICON = os.path.join("Images", "settings.png")

EDIT_ROW_TEXT = "edit destinations file settings json config open"
EDIT_ROW_TITLE = "Edit destinations file"
EDIT_ROW_SUBTITLE = "Open %s in your editor" % config_module.CONFIG_NAME

CONFIG_CONTEXT = "!config"


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _get(mapping, *names, default=""):
    """Case-insensitive lookup (Flow serialises with camelCase)."""
    if not isinstance(mapping, dict):
        return default
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lowered:
            value = lowered[name.lower()]
            if value is not None:
                return value
    return default


def search_text(query):
    """The part of the query after the action keyword."""
    query = _as_dict(query)
    text = _get(query, "Search", default="")
    if not isinstance(text, str):
        text = ""
    if not text.strip():
        trimmed = _get(query, "TrimmedQuery", "RawQuery", default="")
        keyword = _get(query, "ActionKeyword", default="") or "ssh"
        if isinstance(trimmed, str):
            text = trimmed.strip()
            if text.lower().startswith(keyword.lower()):
                text = text[len(keyword):]
            elif text.startswith("*"):
                text = text[1:]
    return text.strip()


class Plugin(object):
    def __init__(self, log, plugin_dir):
        self.log = log
        self.plugin_dir = plugin_dir
        self.settings_dir = None
        # (dependencies, settings, destinations, error, problems); dependencies
        # cover destinations.json *and* the ssh config, so an edit to either
        # applies without a restart.
        self._cache = None
        self._ssh_config_path = None
        # {"alias", "message"} for every entry that was skipped; shown as
        # result rows so a broken entry no longer silently disappears.
        self.problems = []

    # ------------------------------------------------------------------ setup

    def initialize(self, context):
        context = _as_dict(context)
        metadata = _as_dict(_get(context, "CurrentPluginMetadata", default={}))
        plugin_dir = _get(metadata, "PluginDirectory", default="") or self.plugin_dir
        if plugin_dir:
            self.plugin_dir = plugin_dir
        settings_dir = _get(metadata, "PluginSettingsDirectoryPath", default="")
        self.settings_dir = settings_dir or None
        # Metadata only: the paths of the install and settings folders are the
        # user's own file system layout and do not belong in a shared log.
        self.log.info("initialized (version=%s)" % _get(metadata, "Version", default="?"))
        self._load(force=True)
        return None

    def path(self):
        return config_module.config_path(self.settings_dir)

    # ------------------------------------------------------------- config I/O

    def _load(self, force=False):
        """Return (settings, destinations, error); the config is re-read when
        destinations.json or the ssh config changed on disk, so edits apply
        without a restart.  Skipped entries land in ``self.problems``."""
        path = self.path()
        dependencies = self._dependencies()
        if not force and self._cache is not None and self._cache[0] == dependencies:
            self.problems = self._cache[4]
            return self._cache[1], self._cache[2], self._cache[3]

        problems = []
        settings, destinations, error = config_module.load(path, self.log, problems)
        self._ssh_config_path = None
        if settings.get("include_ssh_config"):
            configured = {dest["alias"].lower() for dest in destinations}
            for extra in config_module.read_ssh_config(settings, self.log):
                if extra["alias"].lower() not in configured:
                    destinations.append(extra)
            configured_path = str(settings.get("ssh_config_path") or "").strip()
            if configured_path:
                self._ssh_config_path = os.path.expanduser(configured_path)
        # Recompute after loading: the ssh config path may have changed.
        self._cache = (self._dependencies(), settings, destinations, error, problems)
        self.problems = problems
        self.log.info("loaded %d destinations" % len(destinations))
        return settings, destinations, error

    def _dependencies(self):
        """mtime stamps of every file the current result was derived from."""
        candidates = [self.path()]
        if self._ssh_config_path:
            candidates.append(self._ssh_config_path)
        stamps = []
        for candidate in candidates:
            try:
                stamps.append(os.path.getmtime(candidate))
            except OSError:
                stamps.append(None)
        return tuple(stamps)

    def _destination(self, alias):
        _, destinations, _ = self._load()
        wanted = str(alias or "").lower()
        for dest in destinations:
            if dest["alias"].lower() == wanted:
                return dest
        return None

    # ------------------------------------------------------------------ query

    @staticmethod
    def _flatten_args(args):
        """Accept both [a, b] and [[a, b]] shapes StreamJsonRpc may deliver."""
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            args = tuple(args[0])
        return tuple(a for a in args if a is not None)

    def query(self, query, _settings=None):
        try:
            return self._query(query, _settings)
        except Exception:
            self.log.error("query failed:\n%s" % traceback.format_exc())
            return {
                "result": [
                    {
                        "Title": "SSH Launcher error",
                        "SubTitle": "See logs/ssh-launcher.log (Alt+Enter on this row does nothing)",
                        "IcoPath": self.icon(CONFIG_ICON),
                        "Score": 100,
                        "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
                        "ContextData": CONFIG_CONTEXT,
                    }
                ],
                "debugMessage": "",
            }

    def _query(self, query, _settings=None):
        text = search_text(query)
        settings, destinations, error = self._load()

        results = []
        if error:
            results.append(
                {
                    "Title": "SSH destinations: configuration problem",
                    "SubTitle": error,
                    "IcoPath": self.icon(CONFIG_ICON),
                    "Score": 100,
                    "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
                    "ContextData": CONFIG_CONTEXT,
                }
            )
            return {"result": results, "debugMessage": ""}

        matches = []
        for dest in destinations:
            score = matcher.score_destination(text, dest)
            if text and score < matcher.MIN_SCORE:
                continue
            matches.append((score, dest))
        # Stable sort on the score alone: with an empty query (all scores 0) the
        # list keeps the order of the config file, so the file decides the order.
        matches.sort(key=lambda item: -item[0])

        matched = 0
        for score, dest in matches:
            # One unusable destination must not cost the user every other row:
            # it is reported on its own instead of aborting the whole query.
            try:
                results.append(self._result_for(dest, score, settings))
                matched += 1
            except launcher.UnsafeArgumentError:
                self.log.warn("skipped a destination that cannot be launched safely")
                results.append(self._skipped_row(
                    dest.get("alias"),
                    "This destination cannot be launched as configured; press Enter to fix it.",
                ))
            except Exception:
                self.log.error("cannot build a result:\n%s" % traceback.format_exc())
                results.append(self._skipped_row(
                    dest.get("alias"),
                    "The ssh command for this destination could not be built; see the plugin log.",
                ))

        # Skipped entries are listed on the empty query, and on a search that
        # matches their alias - not on every unrelated keystroke.
        for problem in self.problems:
            alias = problem.get("alias") or ""
            if not text or (alias and matcher.score_text(text, alias) >= matcher.MIN_SCORE):
                results.append(self._skipped_row(alias, problem.get("message", "")))

        edit_score = matcher.score_text(text, EDIT_ROW_TEXT)
        edit_shown = not text or edit_score >= 20
        if edit_shown:
            results.append(
                {
                    "Title": EDIT_ROW_TITLE,
                    "SubTitle": EDIT_ROW_SUBTITLE,
                    "IcoPath": self.icon(CONFIG_ICON),
                    "Score": 10 if text else 0,
                    "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
                    "ContextData": CONFIG_CONTEXT,
                }
            )

        if text and not matched and not edit_shown:
            results.append(
                {
                    "Title": "No destination matching \u201c%s\u201d" % text,
                    "SubTitle": "Add it to %s, or press Enter to edit the file" % config_module.CONFIG_NAME,
                    "IcoPath": self.icon(CONFIG_ICON),
                    "Score": 0,
                    "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
                    "ContextData": CONFIG_CONTEXT,
                }
            )
        return {"result": results, "debugMessage": ""}

    def _skipped_row(self, alias, message):
        """A row for an entry that could not be used; Enter opens the file."""
        alias = str(alias or "").strip()
        return {
            "Title": "Destination skipped" + (": %s" % alias if alias else ""),
            "SubTitle": message,
            "IcoPath": self.icon(CONFIG_ICON),
            "Score": 98,
            "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
            "ContextData": CONFIG_CONTEXT,
        }

    def context_menu(self, data):
        try:
            return self._context_menu(data)
        except Exception:
            self.log.error("context_menu failed:\n%s" % traceback.format_exc())
            return []

    def _context_menu(self, data):
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        if isinstance(data, str) and data == CONFIG_CONTEXT:
            return [
                {
                    "Title": "Open plugin folder",
                    "SubTitle": self.plugin_dir,
                    "IcoPath": self.icon(CONFIG_ICON),
                    "JsonRPCAction": {"Method": "open_settings_folder", "Parameters": []},
                },
                {
                    "Title": "Recreate file from template",
                    "SubTitle": "Overwrites %s with the default template" % config_module.CONFIG_NAME,
                    "IcoPath": self.icon(CONFIG_ICON),
                    "JsonRPCAction": {"Method": "reset_config", "Parameters": []},
                },
            ]

        alias = ""
        if isinstance(data, str):
            alias = data
        elif isinstance(data, dict):
            alias = _get(data, "alias", default="")
        dest = self._destination(alias)
        if dest is None:
            return []

        settings, _, _ = self._load()
        default_terminal = launcher.resolve_terminal(settings.get("terminal"), self.log)
        command = launcher.ssh_command_line(launcher.ssh_argv(dest, settings))

        entries = []
        for terminal, label in (
            ("wt", "Windows Terminal"),
            ("powershell", "PowerShell"),
            ("cmd", "Command Prompt"),
        ):
            entries.append(
                {
                    "Title": "Open in %s%s" % (label, "  (default)" if terminal == default_terminal else ""),
                    "SubTitle": label.lower(),
                    "IcoPath": self.icon(dest.get("icon")),
                    "JsonRPCAction": {
                        "Method": "open_destination",
                        "Parameters": [dest["alias"], terminal],
                    },
                    "ContextData": dest["alias"],
                }
            )
        entries.append(
            {
                "Title": "Copy ssh command",
                "SubTitle": command,
                "IcoPath": self.icon(dest.get("icon")),
                "JsonRPCAction": {
                    "Method": "copy_command",
                    "Parameters": [dest["alias"]],
                },
                "ContextData": dest["alias"],
            }
        )
        entries.append(
            {
                "Title": EDIT_ROW_TITLE,
                "SubTitle": EDIT_ROW_SUBTITLE,
                "IcoPath": self.icon(CONFIG_ICON),
                "JsonRPCAction": {"Method": "edit_config", "Parameters": []},
                "ContextData": CONFIG_CONTEXT,
            }
        )
        return entries

    # ---------------------------------------------------------------- actions

    def open_destination(self, *args):
        arguments = self._flatten_args(args)
        alias = arguments[0] if arguments else ""
        terminal = arguments[1] if len(arguments) > 1 and isinstance(arguments[1], str) else ""
        dest = self._destination(alias)
        if dest is None:
            self.log.warn("open_destination: unknown alias")
            return {"hide": False}
        settings, _, _ = self._load()
        chosen = terminal or dest.get("terminal") or settings.get("terminal")
        terminal_name = launcher.resolve_terminal(chosen, self.log)
        try:
            ssh_list = launcher.ssh_argv(dest, settings)
            argv = launcher.terminal_argv(terminal_name, ssh_list, settings, dest["alias"])
            launcher.spawn(argv, launcher._needs_new_console(terminal_name), self.log)
        except launcher.UnsafeArgumentError as exc:
            # Keep the launcher open so the row stays visible.  Log which check
            # failed; the full message is not logged because it quotes the
            # configured command.
            self.log.error("cannot launch destination: %s" % exc.reason)
            return {"hide": False}
        except Exception as exc:
            self.log.error("cannot start terminal: %s" % exc)
            return {"hide": False}
        return {"hide": True}

    def copy_command(self, *args):
        arguments = self._flatten_args(args)
        alias = arguments[0] if arguments else ""
        dest = self._destination(alias)
        if dest is None:
            self.log.warn("copy_command: unknown alias")
            return {"hide": False}
        settings, _, _ = self._load()
        try:
            command = launcher.ssh_command_line(launcher.ssh_argv(dest, settings))
        except launcher.UnsafeArgumentError:
            self.log.error("copy_command: the destination cannot be used safely")
            return {"hide": False}
        if not launcher.set_clipboard(command):
            self.log.warn("clipboard copy failed")
            return {"hide": False}
        self.log.info("copied ssh command to clipboard")
        return {"hide": True}

    def edit_config(self, *args):
        path = self.path()
        if not os.path.isfile(path):
            config_module.write_default(path)
        settings, _, _ = self._load()
        try:
            pid, what = launcher.open_path(path, settings.get("editor"))
            self.log.info("opened the destinations file (pid %s)" % pid)
        except Exception as exc:
            self.log.error("cannot open the destinations file: %s" % exc)
            return {"hide": False}
        return {"hide": True}

    def open_settings_folder(self, *args):
        folder = os.path.dirname(self.path())
        try:
            launcher.open_path(folder, "")
            self.log.info("opened the settings folder")
        except Exception as exc:
            self.log.error("cannot open the settings folder: %s" % exc)
            return {"hide": False}
        return {"hide": True}

    def reset_config(self, *args):
        path = self.path()
        try:
            if os.path.isfile(path):
                # Never overwrite the user's file without a byte-exact copy, and
                # abort the reset if that copy cannot be verified.
                config_module.backup_file(path, self.log)
            config_module.write_default(path)
            self.log.info("destinations file recreated from the template")
        except Exception as exc:
            self.log.error("cannot reset the destinations file: %s" % exc)
            return {"hide": False}
        return {"hide": True}

    # ------------------------------------------------------------------ utils

    def icon(self, value=None):
        candidate = str(value or "").strip()
        if candidate:
            if candidate.lower().startswith(("http://", "https://", "data:image")):
                return candidate
            expanded = os.path.expanduser(candidate)
            if os.path.isabs(expanded) and os.path.isfile(expanded):
                return expanded
            relative = os.path.join(self.plugin_dir, expanded)
            if os.path.isfile(relative):
                return relative
        return os.path.join(self.plugin_dir, DEFAULT_ICON)

    def _result_for(self, dest, score, settings):
        terminal = launcher.resolve_terminal(
            dest.get("terminal") or settings.get("terminal"), self.log
        )
        command = launcher.ssh_command_line(launcher.ssh_argv(dest, settings))
        source = "" if dest.get("source") != "ssh_config" else "  \u00b7  ssh config"
        description = dest.get("description") or ""
        subtitle_parts = [command]
        if description:
            subtitle_parts.append(description)
        subtitle_parts.append(terminal)
        return {
            "Title": dest["alias"],
            "SubTitle": "  \u00b7  ".join(subtitle_parts) + source,
            "IcoPath": self.icon(dest.get("icon")),
            "Score": int(round(score)) + 100,
            "CopyText": command,
            "AutoCompleteText": "ssh %s" % dest["alias"],
            "JsonRPCAction": {"Method": "open_destination", "Parameters": [dest["alias"], ""]},
            "ContextData": dest["alias"],
        }

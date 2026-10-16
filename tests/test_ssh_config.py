# -*- coding: utf-8 -*-
"""ssh_config import: multiple aliases, Host= syntax, Match, wildcards, argv.

Runs on any OS - no ssh binary, no network, no clipboard.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import config as config_module  # noqa: E402
from ssh_launcher import launcher  # noqa: E402
from ssh_launcher import logging_setup  # noqa: E402
from ssh_launcher.plugin import Plugin  # noqa: E402


def write_ssh_config(directory, text, name="ssh_config"):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


class SshConfigParsingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl-cfg-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def read(self, text):
        path = write_ssh_config(self.dir, text)
        return config_module.read_ssh_config({"ssh_config_path": path})

    # --- slice 1: several literal names on one Host line -------------------
    def test_host_line_with_several_literal_names_yields_them_all(self):
        found = self.read(
            "Host alpha beta gamma\n"
            "  HostName shared.example\n"
            "  User admin\n"
            "  Port 2200\n"
        )
        aliases = sorted(dest["alias"] for dest in found)
        self.assertEqual(aliases, ["alpha", "beta", "gamma"])
        for dest in found:
            self.assertEqual(dest["host"], "shared.example")
            self.assertEqual(dest["user"], "admin")
            self.assertEqual(dest["port"], "2200")

    # --- slice 2: OpenSSH also accepts Keyword=value -----------------------
    def test_host_assignment_syntax_is_understood(self):
        found = self.read(
            "Host=jumpbox\n"
            "  HostName=10.9.9.9\n"
            "  User=ops\n"
        )
        self.assertEqual([dest["alias"] for dest in found], ["jumpbox"])
        self.assertEqual(found[0]["host"], "10.9.9.9")
        self.assertEqual(found[0]["user"], "ops")

    # --- slice 3: Match ends the Host block ---------------------------------
    def test_match_terminates_the_host_block(self):
        found = self.read(
            "Host alpha\n"
            "  HostName alpha.example\n"
            "\n"
            "Match host *.example\n"
            "  User should_not_leak\n"
            "  Port 9999\n"
        )
        self.assertEqual([dest["alias"] for dest in found], ["alpha"])
        self.assertEqual(found[0]["host"], "alpha.example")
        self.assertNotIn("user", found[0])
        self.assertNotIn("port", found[0])

    # --- slice 4: wildcard/exclusion patterns are not resolved here ---------
    def test_wildcard_patterns_left_to_openssh_but_literals_kept(self):
        found = self.read(
            "Host prod *.internal !prod-staging backup\n"
            "  HostName 10.1.1.1\n"
        )
        self.assertEqual([dest["alias"] for dest in found], ["prod", "backup"])
        for dest in found:
            self.assertEqual(dest["host"], "10.1.1.1")


class SshConfigArgvTest(unittest.TestCase):
    """A destination imported from ssh_config must be handed to OpenSSH, not
    re-implemented: IdentityFile/ProxyJump/Match/wildcards live in the file."""

    IMPORTED = {
        "alias": "homeserver",
        "host": "10.0.0.5",
        "user": "admin",
        "port": "2222",
        "source": "ssh_config",
        "ssh_config_path": "~/.ssh/config",
    }

    def test_imported_alias_is_passed_with_dash_f_and_no_parsed_overrides(self):
        argv = launcher.ssh_argv(dict(self.IMPORTED), {})
        self.assertEqual(argv, ["ssh", "-F", os.path.expanduser("~/.ssh/config"), "homeserver"])

    def test_global_extra_args_still_apply_to_imported_alias(self):
        argv = launcher.ssh_argv(
            dict(self.IMPORTED), {"extra_ssh_args": ["-o", "ServerAliveInterval=30"]}
        )
        self.assertEqual(
            argv,
            ["ssh", "-o", "ServerAliveInterval=30", "-F",
             os.path.expanduser("~/.ssh/config"), "homeserver"],
        )


class SshConfigCacheTest(unittest.TestCase):
    """The plugin cache must be invalidated by the ssh config too, or an edit
    in that file would only show up after restarting Flow Launcher."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl-cache-")
        self.addCleanup(self._tmp.cleanup)
        self.work = self._tmp.name
        self.settings_dir = os.path.join(self.work, "settings")
        os.makedirs(self.settings_dir)
        self.ssh_config = os.path.join(self.work, "ssh_config")
        self.config_path = os.path.join(self.settings_dir, "destinations.json")

    def _write_ssh_config(self, text):
        with open(self.ssh_config, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def _plugin(self):
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "settings": {"include_ssh_config": True, "ssh_config_path": self.ssh_config},
                    "destinations": [],
                },
                handle,
            )
        log = logging_setup.Log(os.path.join(self.work, "test.log")).open()
        self.addCleanup(log.close)
        plugin = Plugin(log, PLUGIN_DIR)
        plugin.initialize(
            {
                "CurrentPluginMetadata": {
                    "PluginDirectory": PLUGIN_DIR,
                    "PluginSettingsDirectoryPath": self.settings_dir,
                }
            }
        )
        return plugin

    def test_ssh_config_edits_are_picked_up_without_a_restart(self):
        self._write_ssh_config("Host one\n  HostName one.example\n")
        plugin = self._plugin()
        self.assertIn("one", [dest["alias"] for dest in plugin._load()[1]])

        self._write_ssh_config(
            "Host one\n  HostName one.example\n"
            "Host two\n  HostName two.example\n"
        )
        bumped = time.time() + 10
        os.utime(self.ssh_config, (bumped, bumped))

        self.assertIn("two", [dest["alias"] for dest in plugin._load()[1]])

    def test_unchanged_files_are_served_from_cache(self):
        self._write_ssh_config("Host one\n  HostName one.example\n")
        plugin = self._plugin()
        first = plugin._load()
        second = plugin._load()
        self.assertIs(first[1], second[1])

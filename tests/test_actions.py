# -*- coding: utf-8 -*-
"""Plugin actions: failure must be reported, not hidden behind ``hide: true``.

Nothing is really spawned - ``launcher.spawn``/``open_path`` are replaced by
recorders, so this runs identically on Linux and Windows.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import config as config_module  # noqa: E402
from ssh_launcher import launcher  # noqa: E402
from ssh_launcher import logging_setup  # noqa: E402
from ssh_launcher.plugin import Plugin  # noqa: E402


class ActionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl-act-")
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = os.path.join(self._tmp.name, "settings")
        os.makedirs(self.settings_dir)
        self.log = logging_setup.Log(os.path.join(self._tmp.name, "test.log")).open()
        self.addCleanup(self.log.close)

    def make_plugin(self, destinations, settings=None):
        base = {"include_ssh_config": False, "terminal": "wt", "editor": ""}
        base.update(settings or {})
        path = os.path.join(self.settings_dir, config_module.CONFIG_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"settings": base, "destinations": destinations}, handle)
        plugin = Plugin(self.log, PLUGIN_DIR)
        plugin.settings_dir = self.settings_dir
        plugin.initialize(
            {
                "CurrentPluginMetadata": {
                    "PluginDirectory": PLUGIN_DIR,
                    "PluginSettingsDirectoryPath": self.settings_dir,
                }
            }
        )
        return plugin


class OpenDestinationFailureTest(ActionTestCase):
    def test_unknown_alias_reports_failure_instead_of_concealing_it(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        self.assertEqual(plugin.open_destination("nope", ""), {"hide": False})

    def test_unsafe_argument_is_reported_and_nothing_is_spawned(self):
        plugin = self.make_plugin(
            [{"alias": "danger", "host": "host.example", "command": "uptime; calc.exe"}]
        )
        with mock.patch.object(launcher, "spawn") as spawn:
            result = plugin.open_destination("danger", "wt")
        self.assertEqual(result, {"hide": False})
        self.assertFalse(spawn.called, "an unsafe command must not be launched")

    def test_successful_launch_hides_the_launcher(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example", "user": "root"}])
        with mock.patch.object(launcher, "spawn") as spawn:
            result = plugin.open_destination("ok", "wt")
        self.assertEqual(result, {"hide": True})
        self.assertTrue(spawn.called)
        argv = spawn.call_args[0][0]
        self.assertEqual(argv[-1], "root@ok.example")


class CopyCommandResultTest(ActionTestCase):
    def test_clipboard_failure_is_reported(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        with mock.patch.object(launcher, "set_clipboard", return_value=False):
            self.assertEqual(plugin.copy_command("ok"), {"hide": False})

    def test_clipboard_success_hides_the_launcher(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        with mock.patch.object(launcher, "set_clipboard", return_value=True):
            self.assertEqual(plugin.copy_command("ok"), {"hide": True})


class OpenPathResultTest(ActionTestCase):
    def test_editor_launch_failure_is_reported(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        with mock.patch.object(launcher, "open_path", side_effect=OSError("no editor")):
            self.assertEqual(plugin.edit_config(), {"hide": False})

    def test_editor_launch_success_hides_the_launcher(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        with mock.patch.object(launcher, "open_path", return_value=(1, "editor")):
            self.assertEqual(plugin.edit_config(), {"hide": True})

    def test_settings_folder_failure_is_reported(self):
        plugin = self.make_plugin([{"alias": "ok", "host": "ok.example"}])
        with mock.patch.object(launcher, "open_path", side_effect=OSError("no shell")):
            self.assertEqual(plugin.open_settings_folder(), {"hide": False})


class ResetConfigBackupTest(ActionTestCase):
    def _backups(self):
        return sorted(
            name
            for name in os.listdir(self.settings_dir)
            if name.startswith(config_module.CONFIG_NAME + ".") and name.endswith(".bak")
        )

    def _reset(self):
        plugin = self.make_plugin([{"alias": "keep", "host": "keep.example"}])
        return plugin, os.path.join(self.settings_dir, config_module.CONFIG_NAME)

    def test_reset_backs_up_the_old_file_byte_for_byte_before_overwriting(self):
        plugin, path = self._reset()
        with open(path, "rb") as handle:
            original = handle.read()
        self.assertEqual(plugin.reset_config(), {"hide": True})

        backups = self._backups()
        self.assertEqual(len(backups), 1, backups)
        with open(os.path.join(self.settings_dir, backups[0]), "rb") as handle:
            self.assertEqual(handle.read(), original)

        with open(path, "rb") as handle:
            after = handle.read()
        self.assertNotEqual(after, original)
        self.assertEqual(json.loads(after.decode("utf-8"))["destinations"], [])

    def test_reset_aborts_and_keeps_the_file_when_the_backup_fails(self):
        plugin, path = self._reset()
        with open(path, "rb") as handle:
            original = handle.read()
        with mock.patch.object(config_module, "backup_file", side_effect=OSError("disk full")):
            result = plugin.reset_config()
        self.assertEqual(result, {"hide": False})
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(self._backups(), [])

    def test_two_resets_in_the_same_second_do_not_overwrite_the_backup(self):
        plugin, _ = self._reset()
        self.assertEqual(plugin.reset_config(), {"hide": True})
        self.assertEqual(plugin.reset_config(), {"hide": True})
        self.assertEqual(len(self._backups()), 2, self._backups())


class BadEntryIsolationTest(ActionTestCase):
    """One unusable destination must never cost the user every other row."""

    def titles(self, plugin, search=""):
        rows = plugin.query({"Search": search, "ActionKeyword": "ssh"})["result"]
        return [row["Title"] for row in rows]

    def test_a_bad_entry_is_reported_and_the_good_ones_still_list(self):
        plugin = self.make_plugin([
            {"alias": "good", "host": "good.example"},
            {"alias": "bad", "host": "bad.example", "ssh_args": {"not": "a list"}},
        ])
        titles = self.titles(plugin)
        self.assertIn("good", titles)
        self.assertIn("Destination skipped: bad", titles)

    def test_an_unclosed_quote_no_longer_kills_the_query(self):
        plugin = self.make_plugin([
            {"alias": "good", "host": "good.example"},
            {"alias": "quoted", "host": "quoted.example", "ssh_args": "-o 'x"},
        ])
        titles = self.titles(plugin)
        self.assertIn("good", titles)
        self.assertIn("quoted", titles)

    def test_an_option_like_host_is_dropped_and_explained(self):
        plugin = self.make_plugin([{"alias": "trap", "host": "-oProxyCommand=calc.exe"}])
        rows = plugin.query({"Search": ""})["result"]
        skipped = [row for row in rows if row["Title"].startswith("Destination skipped")]
        self.assertEqual(len(skipped), 1, [row["Title"] for row in rows])
        self.assertIn("starts with '-'", skipped[0]["SubTitle"])
        self.assertEqual(skipped[0]["JsonRPCAction"]["Method"], "edit_config")
        # The dropped entry can no longer be launched by alias.
        self.assertEqual(plugin.open_destination("trap", ""), {"hide": False})

    def test_a_string_ssh_args_entry_launches_with_its_backslash_path(self):
        plugin = self.make_plugin(
            [{"alias": "win", "host": "win.example", "ssh_args": r"-i C:\keys\id_rsa"}]
        )
        with mock.patch.object(launcher, "spawn") as spawn:
            self.assertEqual(plugin.open_destination("win", "wt"), {"hide": True})
        argv = spawn.call_args[0][0]
        self.assertEqual(argv[-2:], ["C:\\keys\\id_rsa", "win.example"])


class ReviewRegressionTest(ActionTestCase):
    """Behaviour pinned after reviewing the 1.0.3 validation change."""

    def titles(self, plugin, search=""):
        return [row["Title"] for row in plugin.query({"Search": search})["result"]]

    def test_an_alias_with_spaces_or_cyrillic_is_still_listed(self):
        plugin = self.make_plugin([
            {"alias": "home nas", "host": "nas.example"},
            {"alias": "\u0434\u043e\u043c", "host": "home.example",
             "user": "\u0432\u0430\u0434\u0438\u043c"},
        ])
        titles = self.titles(plugin)
        self.assertIn("home nas", titles)
        self.assertIn("\u0434\u043e\u043c", titles)
        self.assertFalse(any(title.startswith("Destination skipped") for title in titles), titles)

    def test_a_skipped_entry_does_not_follow_every_search(self):
        plugin = self.make_plugin([{"alias": "pve", "host": "pve.example"},
                                   {"alias": "broken"}])
        self.assertEqual(self.titles(plugin, "pve"), ["pve"])
        self.assertIn("Destination skipped: broken", self.titles(plugin, "brok"))
        self.assertIn("Destination skipped: broken", self.titles(plugin, ""))

    def test_searching_for_edit_does_not_add_a_no_match_row(self):
        plugin = self.make_plugin([{"alias": "pve", "host": "pve.example"}])
        self.assertEqual(self.titles(plugin, "edit"), ["Edit destinations file"])

    def test_actions_on_an_option_like_imported_alias_fail_cleanly(self):
        plugin = self.make_plugin([])
        imported = {"alias": "-oProxyCommand=calc.exe", "host": "h",
                    "source": "ssh_config", "ssh_config_path": "~/.ssh/config"}
        with mock.patch.object(plugin, "_destination", return_value=imported), \
                mock.patch.object(launcher, "spawn") as spawn, \
                mock.patch.object(launcher, "set_clipboard") as clipboard:
            self.assertEqual(plugin.open_destination("x", "wt"), {"hide": False})
            self.assertEqual(plugin.copy_command("x"), {"hide": False})
        self.assertFalse(spawn.called)
        self.assertFalse(clipboard.called)


class RefusalLogTest(ActionTestCase):
    """A refused launch must say which check failed - and never the value."""

    def test_the_log_names_terminal_and_character_but_not_the_command(self):
        plugin = self.make_plugin(
            [{"alias": "danger", "host": "host.example", "command": "zzsecret; calc.exe"}]
        )
        plugin.log = mock.Mock()
        with mock.patch.object(launcher, "spawn"):
            self.assertEqual(plugin.open_destination("danger", "wt"), {"hide": False})
        logged = " ".join(str(call.args[0]) for call in plugin.log.error.call_args_list)
        self.assertIn("wt", logged)
        self.assertIn("';'", logged)
        self.assertNotIn("zzsecret", logged)
        self.assertNotIn("calc.exe", logged)

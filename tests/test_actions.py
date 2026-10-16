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

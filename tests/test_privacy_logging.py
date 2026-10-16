# -*- coding: utf-8 -*-
"""The plugin log is shared in bug reports, so it must stay metadata-only.

Exercises the normal paths (initialize, query, open, copy, edit, reset) plus
the malformed-config warnings and asserts that no destination alias/host/user/
command, no search text and no absolute path ever lands in the log.
"""

from __future__ import annotations

import io
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
from ssh_launcher import rpc as rpc_module  # noqa: E402

# Values that must never be echoed into the log.  If you add one, add it to the
# config below as well.
SENTINELS = (
    "zzsecretquery",
    "zzsecretalias",
    "zzsecrethost",
    "zzsecretuser",
    "zzsecretcommand",
    "zzsecretkey",
    "zzsecretdesc",
    "zzsecretsettingsdir",
)


class LogPrivacyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl-log-")
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = os.path.join(self._tmp.name, "zzsecretsettingsdir")
        os.makedirs(self.settings_dir)
        self.log_path = os.path.join(self._tmp.name, "plugin.log")
        self.logfile = logging_setup.Log(self.log_path).open()
        self.addCleanup(self.logfile.close)
        self.config_path = os.path.join(self.settings_dir, config_module.CONFIG_NAME)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "settings": {
                        "include_ssh_config": False,
                        "terminal": "wt",
                        "ssh": "ssh",
                        "extra_ssh_args": ["-i", "/keys/zzsecretkey"],
                    },
                    "destinations": [
                        {
                            "alias": "zzsecretalias",
                            "host": "zzsecrethost.invalid",
                            "user": "zzsecretuser",
                            "command": "zzsecretcommand --flag",
                            "description": "zzsecretdesc",
                        },
                        # malformed entries used to be logged with their content
                        "not-a-dict",
                        {"user": "zzsecretuser", "description": "zzsecretdesc"},
                    ],
                },
                handle,
            )

    def _read_log(self):
        self.logfile.close()
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def _drive(self):
        out = io.BytesIO()
        server = rpc_module.Server(out, self.logfile, PLUGIN_DIR)
        metadata = {
            "PluginDirectory": PLUGIN_DIR,
            "PluginSettingsDirectoryPath": self.settings_dir,
            "Version": "1.0.0",
        }
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": [{"CurrentPluginMetadata": metadata}]},
            {"jsonrpc": "2.0", "id": 2, "method": "query",
             "params": [{"Search": "zzsecretquery"}, {}]},
            {"jsonrpc": "2.0", "id": 3, "method": "context_menu",
             "params": ["zzsecretalias"]},
            {"jsonrpc": "2.0", "id": 4, "method": "open_destination",
             "params": [["zzsecretalias", "wt"]]},
            {"jsonrpc": "2.0", "id": 5, "method": "copy_command",
             "params": [["zzsecretalias"]]},
            {"jsonrpc": "2.0", "id": 6, "method": "edit_config", "params": [[]]},
            {"jsonrpc": "2.0", "id": 7, "method": "open_settings_folder", "params": []},
            {"jsonrpc": "2.0", "id": 8, "method": "reset_config", "params": []},
            {"jsonrpc": "2.0", "id": 9, "method": "reload_data", "params": []},
        ]
        with mock.patch.object(launcher, "spawn"), \
                mock.patch.object(launcher, "set_clipboard", return_value=True), \
                mock.patch.object(launcher, "open_path", return_value=(1, "editor")):
            for request in requests:
                server._handle(dict(request))
        return out.getvalue()

    def test_no_payload_or_absolute_path_reaches_the_log(self):
        self._drive()
        text = self._read_log()
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text, "log leaked %r:\n%s" % (sentinel, text))
        self.assertNotIn(self.settings_dir, text, "log leaked the settings path:\n%s" % text)
        self.assertNotIn(PLUGIN_DIR, text, "log leaked the plugin path:\n%s" % text)

    def test_the_log_still_says_what_happened(self):
        self._drive()
        text = self._read_log()
        self.assertIn("request query", text)
        self.assertIn("destination", text.lower())

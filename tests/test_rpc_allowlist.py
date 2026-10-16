# -*- coding: utf-8 -*-
"""The RPC dispatcher must expose an explicit method list.

Anything not on it (``path``, ``icon``, an arbitrary attribute of the plugin
object) has to answer -32601 instead of running ``getattr(plugin, name)``.
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
from ssh_launcher import logging_setup  # noqa: E402
from ssh_launcher import rpc as rpc_module  # noqa: E402

METHOD_NOT_FOUND = -32601


class RecordingServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl-rpc-")
        self.addCleanup(self._tmp.cleanup)
        self.settings_dir = os.path.join(self._tmp.name, "settings")
        os.makedirs(self.settings_dir)
        with open(os.path.join(self.settings_dir, config_module.CONFIG_NAME),
                  "w", encoding="utf-8") as handle:
            json.dump(
                {"settings": {"include_ssh_config": False},
                 "destinations": [{"alias": "ok", "host": "ok.example"}]},
                handle,
            )
        self.log = logging_setup.Log(os.path.join(self._tmp.name, "test.log")).open()
        self.addCleanup(self.log.close)
        self.server = rpc_module.Server(io.BytesIO(), self.log, PLUGIN_DIR)
        self.server._handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": [
                    {
                        "CurrentPluginMetadata": {
                            "PluginDirectory": PLUGIN_DIR,
                            "PluginSettingsDirectoryPath": self.settings_dir,
                        }
                    }
                ],
            }
        )

    def call(self, method, params=None):
        out = io.BytesIO()
        self.server._out = out
        self.server._handle(
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or []}
        )
        return json.loads(out.getvalue().decode("utf-8"))


class AllowlistTest(RecordingServer):
    def test_plugin_helper_path_is_not_reachable_as_an_rpc_method(self):
        reply = self.call("path")
        self.assertEqual(reply.get("error", {}).get("code"), METHOD_NOT_FOUND, reply)

    def test_plugin_helper_icon_is_not_reachable_as_an_rpc_method(self):
        reply = self.call("icon")
        self.assertEqual(reply.get("error", {}).get("code"), METHOD_NOT_FOUND, reply)

    def test_private_helper_is_not_reachable(self):
        reply = self.call("_load")
        self.assertEqual(reply.get("error", {}).get("code"), METHOD_NOT_FOUND, reply)

    def test_allowlisted_action_is_still_reachable(self):
        with mock.patch.object(self.server.plugin, "open_destination",
                               return_value={"hide": True}) as action:
            reply = self.call("open_destination", [["ok", ""]])
        self.assertEqual(reply.get("result"), {"hide": True}, reply)
        self.assertTrue(action.called)


class ActionErrorReplyTest(RecordingServer):
    def test_a_failing_action_reports_failure_instead_of_pretending_success(self):
        with mock.patch.object(self.server.plugin, "edit_config",
                               side_effect=RuntimeError("boom")):
            reply = self.call("edit_config")
        self.assertEqual(reply.get("result"), {"hide": False}, reply)

    def test_a_failing_query_still_answers_with_an_error(self):
        with mock.patch.object(self.server.plugin, "query", side_effect=RuntimeError("boom")):
            reply = self.call("query", [{"Search": ""}, {}])
        self.assertEqual(reply.get("error", {}).get("code"), rpc_module.INTERNAL_ERROR, reply)

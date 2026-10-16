# -*- coding: utf-8 -*-
"""Windows-only integration test for the terminal command lines.

It takes the exact argv/command line the plugin hands to a terminal, really
runs it, and lets a python stub write ``sys.argv`` to a JSON file - so the
assertion is on what the shell delivered to the program, not on our own idea of
what our quoting means.

Safety: a ``TemporaryDirectory`` under ``TMPDIR`` (never a shared, hard-coded
folder), no network, no clipboard, no scheduled tasks, and ``CREATE_NO_WINDOW``
so nothing flashes on screen.  Skipped everywhere except Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import launcher  # noqa: E402

STUB = (
    "import json, os, sys\n"
    'with open(os.environ["SSHL_ARGS_FILE"], "w", encoding="utf-8") as handle:\n'
    "    json.dump(sys.argv, handle)\n"
)


@unittest.skipUnless(os.name == "nt", "Windows-only: exercises cmd.exe/powershell.exe parsing")
class WindowsTerminalIntegrationTest(unittest.TestCase):
    def setUp(self):
        # A space in the directory name is deliberate: it is what used to get
        # double-escaped.  TemporaryDirectory honours TMPDIR.
        self._tmp = tempfile.TemporaryDirectory(prefix="sshl win ")
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.stub = os.path.join(self.dir, "stub.py")
        self.args_file = os.path.join(self.dir, "argv.json")
        with open(self.stub, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(STUB)

    def _ssh_argv(self):
        """A python stub stands in for the ssh client."""
        return [
            sys.executable,
            self.stub,
            "-o", "ServerAliveInterval=30",
            "-i", os.path.join(self.dir, "my key.pem"),
            "-p", "2222",
            "demo@example.invalid",
        ]

    def _run_and_read(self, argv):
        if os.path.isfile(self.args_file):
            os.remove(self.args_file)
        env = dict(os.environ, SSHL_ARGS_FILE=self.args_file)
        completed = subprocess.run(
            argv,
            env=env,
            timeout=120,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.time() + 60
        while time.time() < deadline and not os.path.isfile(self.args_file):
            time.sleep(0.1)
        self.assertTrue(
            os.path.isfile(self.args_file),
            "the stub never ran (rc=%s, out=%r, err=%r)"
            % (completed.returncode, completed.stdout, completed.stderr),
        )
        with open(self.args_file, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_cmd_command_line_delivers_the_exact_arguments(self):
        argv = self._ssh_argv()
        line = launcher.terminal_argv("cmd", list(argv), {}, "stub")
        # /k keeps the console open; /c runs and exits - the quoting under test
        # is everything after the switch, which is identical.
        run_line = line.replace("/s /k ", "/s /c ", 1)
        self.assertNotIn("/k", run_line)
        delivered = self._run_and_read(run_line)
        self.assertEqual(delivered, argv[1:], "cmd line was %r" % (run_line,))

    def test_powershell_command_delivers_the_exact_arguments(self):
        argv = self._ssh_argv()
        built = launcher.terminal_argv("powershell", list(argv), {}, "stub")
        command = built[3]
        delivered = self._run_and_read(
            ["powershell.exe", "-NoProfile", "-Command", command]
        )
        self.assertEqual(delivered, argv[1:], "powershell command was %r" % (command,))

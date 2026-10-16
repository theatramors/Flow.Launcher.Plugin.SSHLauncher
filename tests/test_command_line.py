# -*- coding: utf-8 -*-
"""Command-line building: raw remote commands, Windows terminal quoting.

Nothing here spawns a process: every assertion is on the exact argv/command
line the plugin would hand to the terminal.  The Windows-only integration
check lives in tests/test_windows_command_line.py.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import launcher  # noqa: E402


class RemoteCommandTest(unittest.TestCase):
    def test_remote_command_string_is_kept_as_one_raw_argument(self):
        dest = {
            "alias": "web",
            "host": "web.example",
            "command": "printf '%s' \"a b\" ; uptime",
        }
        self.assertEqual(
            launcher.ssh_argv(dest, {}),
            ["ssh", "web.example", "printf '%s' \"a b\" ; uptime"],
        )

    def test_remote_command_list_stays_a_list_of_arguments(self):
        dest = {"alias": "web", "host": "web.example", "command": ["ls", "-la"]}
        self.assertEqual(launcher.ssh_argv(dest, {}), ["ssh", "web.example", "ls", "-la"])


SSH_ARGV = [
    "C:\\Tools\\OpenSSH\\ssh.exe",
    "-o",
    "ServerAliveInterval=30",
    "-i",
    "C:\\keys\\my key.pem",
    "-p",
    "2222",
    "demo@example.invalid",
]


class CmdCommandLineTest(unittest.TestCase):
    def test_cmd_receives_one_raw_command_line_not_a_requoted_list(self):
        line = launcher.terminal_argv("cmd", list(SSH_ARGV), {}, "faketest")
        self.assertIsInstance(line, str)
        self.assertEqual(
            line,
            'cmd.exe /d /v:off /s /k "C:\\Tools\\OpenSSH\\ssh.exe'
            " -o ServerAliveInterval=30"
            ' -i "C:\\keys\\my key.pem"'
            ' -p 2222 demo@example.invalid"',
        )


class PowerShellCommandTest(unittest.TestCase):
    def test_quoted_executable_path_is_invoked_with_the_call_operator(self):
        argv = launcher.terminal_argv(
            "powershell",
            ["C:\\Program Files\\OpenSSH\\ssh.exe", "-o", "ServerAliveInterval=30", "host"],
            {},
            "faketest",
        )
        self.assertEqual(
            argv,
            ["powershell.exe", "-NoExit", "-Command",
             "& 'C:\\Program Files\\OpenSSH\\ssh.exe' -o ServerAliveInterval=30 host"],
        )

    def test_plain_executable_path_needs_no_call_operator(self):
        argv = launcher.terminal_argv("powershell", ["ssh", "host"], {}, "faketest")
        self.assertEqual(argv, ["powershell.exe", "-NoExit", "-Command", "ssh host"])


class ClipboardCommandTest(unittest.TestCase):
    def test_copy_text_uses_powershell_not_posix_concatenated_quotes(self):
        line = launcher.ssh_command_line([
            "C:\\Program Files\\OpenSSH\\ssh.exe", "host.example",
            "printf '%s' 'hello world'",
        ])
        self.assertEqual(
            line,
            "& 'C:\\Program Files\\OpenSSH\\ssh.exe' host.example "
            "'printf ''%s'' ''hello world'''",
        )


class UnsafeTokenTest(unittest.TestCase):
    def test_windows_terminal_refuses_a_semicolon_it_would_run_as_a_command(self):
        with self.assertRaises(launcher.UnsafeArgumentError) as ctx:
            launcher.terminal_argv(
                "wt", ["ssh", "web.example", "uptime; calc.exe"], {}, "faketest"
            )
        self.assertIn(";", str(ctx.exception))

    def test_cmd_refuses_a_percent_token_it_cannot_escape(self):
        with self.assertRaises(launcher.UnsafeArgumentError) as ctx:
            launcher.terminal_argv("cmd", ["ssh", "web.example", "%PATH%"], {}, "faketest")
        self.assertIn("%", str(ctx.exception))

    def test_windows_terminal_still_accepts_ordinary_arguments(self):
        argv = launcher.terminal_argv("wt", ["ssh", "web.example"], {"wt_window": "0"}, "web")
        self.assertEqual(argv, ["wt.exe", "-w", "0", "new-tab", "--title", "web",
                                "ssh", "web.example"])


class CmdBackslashTest(unittest.TestCase):
    def test_a_trailing_backslash_does_not_escape_the_closing_quote(self):
        # "C:\keys\" would turn into ...keys\" and swallow the next token.
        line = launcher.terminal_argv("cmd", ["ssh", "-i", "C:\\keys\\"], {}, "t")
        # inner: ssh -i "C:\keys\\"   -> plus the /s wrapper's closing quote.
        self.assertTrue(line.endswith(' -i "C:\\keys\\\\""'), line)


class SpawnLogTest(unittest.TestCase):
    def test_spawn_logs_the_program_it_started(self):
        messages = []
        log = mock.Mock()
        log.info = messages.append
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.pid = 4321
            launcher.spawn('cmd.exe /d /v:off /s /k "ssh host"', False, log)
        self.assertEqual(messages, ["spawned[4321] cmd.exe"])

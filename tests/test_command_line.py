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


class ArgumentStringTest(unittest.TestCase):
    """Config values may be a list (documented) or one string (Windows rules)."""

    def test_string_ssh_args_keep_windows_backslashes(self):
        argv = launcher.ssh_argv(
            {"alias": "a", "host": "h", "ssh_args": r"-i C:\keys\id_ed25519"}, {}
        )
        self.assertEqual(argv, ["ssh", "-i", "C:\\keys\\id_ed25519", "h"])

    def test_quoted_string_arguments_group_a_path_with_spaces(self):
        argv = launcher.ssh_argv(
            {"alias": "a", "host": "h", "ssh_args": '-i "C:\\my keys\\id_rsa"'}, {}
        )
        self.assertEqual(argv, ["ssh", "-i", "C:\\my keys\\id_rsa", "h"])

    def test_an_unbalanced_quote_does_not_break_the_command(self):
        argv = launcher.ssh_argv({"alias": "a", "host": "h", "ssh_args": '-o "x'}, {})
        self.assertEqual(argv, ["ssh", "-o", "x", "h"])

    def test_global_extra_args_accept_a_string_too(self):
        argv = launcher.ssh_argv(
            {"alias": "a", "host": "h"}, {"extra_ssh_args": "-o ServerAliveInterval=30"}
        )
        self.assertEqual(argv, ["ssh", "-o", "ServerAliveInterval=30", "h"])


class OptionLikeDestinationTest(unittest.TestCase):
    """A destination that reads like an ssh option would run a local command."""

    def test_host_that_looks_like_an_option_is_refused(self):
        with self.assertRaises(launcher.UnsafeArgumentError):
            launcher.ssh_argv({"alias": "a", "host": "-oProxyCommand=calc.exe"}, {})

    def test_imported_alias_that_looks_like_an_option_is_refused(self):
        with self.assertRaises(launcher.UnsafeArgumentError):
            launcher.ssh_argv(
                {"alias": "-oProxyCommand=calc.exe", "source": "ssh_config",
                 "ssh_config_path": "~/.ssh/config"}, {}
            )

    def test_user_at_host_is_still_accepted(self):
        self.assertEqual(
            launcher.ssh_argv({"alias": "a", "host": "h.example", "user": "root"}, {}),
            ["ssh", "root@h.example"],
        )


class PowerShellQuoteTest(unittest.TestCase):
    def test_unicode_single_quotes_are_doubled_like_the_ascii_one(self):
        argv = launcher.terminal_argv("powershell", ["ssh", "h", "echo it\u2019s"], {}, "t")
        self.assertEqual(argv[3], "ssh h 'echo it\u2019\u2019s'")

    def test_unicode_double_quotes_are_quoted(self):
        argv = launcher.terminal_argv("powershell", ["ssh", "h", "\u201cx\u201d"], {}, "t")
        self.assertEqual(argv[3], "ssh h '\u201cx\u201d'")

    def test_the_stop_parsing_token_is_refused_because_powershell_drops_it(self):
        with self.assertRaises(launcher.UnsafeArgumentError):
            launcher.terminal_argv("powershell", ["ssh", "--%", "h"], {}, "t")
        # Only the exact token: these reach the program unchanged (verified live).
        argv = launcher.terminal_argv("powershell", ["ssh", "--%x", "x--%", "h"], {}, "t")
        self.assertEqual(argv[3], "ssh --%x x--% h")

    def test_other_terminals_still_pass_the_stop_parsing_token(self):
        argv = launcher.terminal_argv("wt", ["ssh", "--%", "h"], {}, "t")
        self.assertEqual(argv[-3:], ["ssh", "--%", "h"])

    def test_a_leading_at_sign_is_quoted(self):
        argv = launcher.terminal_argv("powershell", ["ssh", "h", "@args"], {}, "t")
        self.assertEqual(argv[3], "ssh h '@args'")

    def test_a_tilde_path_stays_unquoted_so_powershell_expands_it(self):
        argv = launcher.terminal_argv(
            "powershell", ["ssh", "-i", "~/.ssh/id_ed25519", "h"], {}, "t"
        )
        self.assertEqual(argv[3], "ssh -i ~/.ssh/id_ed25519 h")

    def test_the_copied_command_uses_the_same_escaping(self):
        line = launcher.ssh_command_line(["ssh", "h", "echo it\u2019s"])
        self.assertEqual(line, "ssh h 'echo it\u2019\u2019s'")


class SpawnLogTest(unittest.TestCase):
    def test_spawn_logs_the_program_it_started(self):

        messages = []
        log = mock.Mock()
        log.info = messages.append
        with mock.patch.object(launcher.subprocess, "Popen") as popen:
            popen.return_value.pid = 4321
            launcher.spawn('cmd.exe /d /v:off /s /k "ssh host"', False, log)
        self.assertEqual(messages, ["spawned[4321] cmd.exe"])

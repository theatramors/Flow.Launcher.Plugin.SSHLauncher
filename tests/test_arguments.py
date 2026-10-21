# -*- coding: utf-8 -*-
"""Config argument strings and value checks.

A backslash is an ordinary character in a Windows command line: ``shlex.split``
treated it as an escape and turned ``C:\\keys\\id_ed25519`` into
``C:keysid_ed25519``.  These tests pin the Windows behaviour, and the checks that
keep a config value from being read as an ssh option.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import arguments  # noqa: E402


class SplitArgumentsTest(unittest.TestCase):
    def test_missing_value_is_no_argument(self):
        self.assertEqual(arguments.split_arguments(None), [])
        self.assertEqual(arguments.split_arguments(""), [])
        self.assertEqual(arguments.split_arguments("   "), [])

    def test_a_list_is_passed_through(self):
        self.assertEqual(arguments.split_arguments(["-i", "key"]), ["-i", "key"])
        self.assertEqual(arguments.split_arguments(("-o", "A=B")), ["-o", "A=B"])

    def test_none_members_of_a_list_are_dropped_and_numbers_are_stringified(self):
        self.assertEqual(arguments.split_arguments(["-p", None, 2222]), ["-p", "2222"])

    def test_windows_backslashes_are_literal(self):
        self.assertEqual(
            arguments.split_arguments(r"-i C:\keys\id_ed25519"),
            ["-i", r"C:\keys\id_ed25519"],
        )
        self.assertEqual(
            arguments.split_arguments(r"-o ProxyCommand=C:\bin\connect.exe"),
            ["-o", r"ProxyCommand=C:\bin\connect.exe"],
        )

    def test_quotes_group_spaces_and_are_removed(self):
        self.assertEqual(
            arguments.split_arguments('-i "C:\\my keys\\id_rsa" -o A=B'),
            ["-i", "C:\\my keys\\id_rsa", "-o", "A=B"],
        )
        self.assertEqual(arguments.split_arguments("'one two' three"), ["one two", "three"])

    def test_an_empty_quoted_argument_survives(self):
        self.assertEqual(arguments.split_arguments('a "" b'), ["a", "", "b"])

    def test_an_unbalanced_quote_is_taken_literally_instead_of_raising(self):
        log = mock.Mock()
        self.assertEqual(arguments.split_arguments('-o "x', log), ["-o", "x"])
        self.assertTrue(log.warn.called)

    def test_a_value_that_is_not_a_string_or_list_yields_nothing(self):
        self.assertEqual(arguments.split_arguments({"a": 1}), [])


class SafeEndpointTest(unittest.TestCase):
    def test_plain_destinations_are_accepted(self):
        for value in ("host", "host.example", "10.0.0.5", "fe80::1%eth0",
                      "root@host.example", "[::1]"):
            self.assertTrue(arguments.is_safe_endpoint(value), value)

    def test_non_ascii_user_and_host_names_are_accepted(self):
        for value in ("\u0432\u0430\u0434\u0438\u043c", "\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444",
                      "DOMAIN\\\u0432\u0430\u0434\u0438\u043c"):
            self.assertTrue(arguments.is_safe_endpoint(value), value)

    def test_shell_syntax_is_left_to_the_terminal_quoting(self):
        # Not ssh options: quoting (and the wt/cmd refusals) deal with these.
        for value in ("host;calc", "$(calc)", "host&"):
            self.assertTrue(arguments.is_safe_endpoint(value), value)

    def test_a_windows_domain_account_is_accepted(self):
        # Windows OpenSSH takes DOMAIN\user (and user@domain) as a login name.
        self.assertTrue(arguments.is_safe_endpoint(r"DOMAIN\vadim"))
        self.assertTrue(arguments.is_safe_endpoint(r"DOMAIN\vadim@host.example"))

    def test_an_option_like_value_is_refused(self):
        for value in ("-oProxyCommand=calc.exe", "-F/etc/ssh/config", "--help"):
            self.assertFalse(arguments.is_safe_endpoint(value), value)

    def test_whitespace_control_and_empty_values_are_refused(self):
        for value in ("", "   ", "host example", "\thost", "host\n", "ho\x00st", " host"):
            self.assertFalse(arguments.is_safe_endpoint(value), repr(value))


class SafeLabelTest(unittest.TestCase):
    def test_an_alias_may_hold_spaces_and_cyrillic(self):
        for value in ("home nas", "\u0434\u043e\u043c", "pve #2", "-dash-first"):
            self.assertTrue(arguments.is_safe_label(value), value)

    def test_an_empty_or_control_character_alias_is_refused(self):
        for value in ("", "   ", "a\nb", "a\x00"):
            self.assertFalse(arguments.is_safe_label(value), repr(value))


class SafePortTest(unittest.TestCase):
    def test_numbers_and_service_names_are_accepted(self):
        for value in ("2222", 22, "ssh", "http-alt", " 2222 "):
            self.assertTrue(arguments.is_safe_port(value), value)

    def test_an_option_like_or_spaced_port_is_refused(self):
        for value in ("-oProxyCommand=calc.exe", "22 23", "", "-1"):
            self.assertFalse(arguments.is_safe_port(value), value)


if __name__ == "__main__":
    unittest.main()

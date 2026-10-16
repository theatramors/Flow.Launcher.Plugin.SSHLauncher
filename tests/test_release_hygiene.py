# -*- coding: utf-8 -*-
"""Release hygiene: the published source must not carry the author's network.

The repository goes out publicly (MIT), so no private address, no trust-on-
first-use ssh option and no hard-coded shared folder may appear in the sources
- shipped code or tests.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# Built from pieces so this file does not itself contain the forbidden text.
PRIVATE_PATTERNS = (
    re.compile(r"192\.168\.\d{1,3}\.\d{1,3}"),  # RFC1918: the author's LAN
    re.compile("accept" + "-new"),
    re.compile("ssh-launcher" + "-test"),
    re.compile(r"Users[\\/]+Public"),
)

SKIP_DIRS = ("__pycache__", ".git")


def source_files():
    for root, dirs, files in os.walk(PLUGIN_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


class SourceHygieneTest(unittest.TestCase):
    def test_no_private_address_or_shared_temp_folder_in_the_sources(self):
        offenders = []
        for path in source_files():
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            for pattern in PRIVATE_PATTERNS:
                for match in pattern.finditer(text):
                    offenders.append("%s: %r" % (os.path.relpath(path, PLUGIN_DIR), match.group(0)))
        self.assertEqual(offenders, [], "private data in published source: %s" % offenders)

    def test_shipped_plugin_code_has_no_private_range_addresses(self):
        offenders = []
        for path in source_files():
            if os.path.dirname(os.path.relpath(path, PLUGIN_DIR)) != "ssh_launcher":
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                if re.search(r"192\.168\.", handle.read()):
                    offenders.append(os.path.basename(path))
        self.assertEqual(offenders, [], offenders)

    def test_the_live_script_does_not_touch_the_network_or_a_shared_folder(self):
        path = os.path.join(PLUGIN_DIR, "tests", "windows_live_test.py")
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("subprocess.run(", text, "the live script must not run a real ssh")
        self.assertIn("tempfile", text, "the live script must use a private temp dir")


class TemplateExampleTest(unittest.TestCase):
    """The example written into every user's destinations.json is a shop window:
    it must use reserved/example names, never the author's own setup."""

    def setUp(self):
        from ssh_launcher import config as config_module

        self.text = "\n".join(config_module.README_LINES).lower()

    def test_the_shipped_template_example_is_neutral(self):
        self.assertIn("server.example.com", self.text)
        self.assertIn("id_ed25519", self.text)
        self.assertNotIn("proxmox", self.text)
        self.assertNotIn("192.168.", self.text)

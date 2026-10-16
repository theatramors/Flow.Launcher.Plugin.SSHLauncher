# -*- coding: utf-8 -*-
"""Windows live test: really spawn terminals and check what the shell received.

A stub ``ssh`` (a .cmd that records its own arguments) stands in for the real
client, so the test proves the whole chain - config -> command building ->
terminal launch -> the argument vector the shell hands to ssh - without
touching the network.

    <flow embedded python> tests\\windows_live_test.py

This is a *manual* script: it opens real terminal windows and uses the real
clipboard, so it is never part of the automated suite (the CI-safe version of
the command-line check lives in tests/test_windows_command_line.py).  It keeps
its scratch files in a private ``tempfile`` directory under TMPDIR and removes
only that directory - never a shared or hard-coded folder.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_DIR)

FAILURES = []


def check(label, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", label,
                         ("  ->  " + str(detail)) if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def wait_for(path, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path):
            return True
        time.sleep(0.25)
    return False


class LiveTest:
    def __init__(self):
        # A private directory under TMPDIR; nothing shared is ever removed.
        self.work = tempfile.mkdtemp(prefix="ssh-launcher-live-")
        self.settings_dir = os.path.join(self.work, "settings")
        self.args_file = os.path.join(self.work, "argv.txt")
        self.stub = os.path.join(self.work, "fake_ssh.cmd")

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def prepare(self):
        os.makedirs(self.settings_dir)
        with open(self.stub, "w", encoding="ascii", newline="\r\n") as handle:
            handle.write("@echo off\r\n")
            handle.write(">> \"%~dp0argv.txt\" echo %*\r\n")
        config = {
            "settings": {
                "terminal": "wt",
                "wt_window": "new",
                "ssh": self.stub,
                "include_ssh_config": False,
                "extra_ssh_args": ["-o", "ServerAliveInterval=30"],
            },
            "destinations": [
                {
                    "alias": "faketest",
                    "host": "example.invalid",
                    "user": "demo",
                    "port": 2222,
                    "description": "live spawn test",
                    "ssh_args": ["-i", "C:/keys/my key.pem"],
                }
            ],
        }
        with open(os.path.join(self.settings_dir, "destinations.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)

    def clear_args(self):
        """Drop the previous run's marker file so the next wait is meaningful."""
        if os.path.isfile(self.args_file):
            os.remove(self.args_file)


def read_clipboard():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def main():
    from ssh_launcher import launcher
    from ssh_launcher.logging_setup import Log
    from ssh_launcher.plugin import Plugin

    live = LiveTest()
    live.prepare()

    log = Log(os.path.join(PLUGIN_DIR, "logs", "live-test.log")).open()
    try:
        plugin = Plugin(log, PLUGIN_DIR)
        plugin.settings_dir = live.settings_dir
        plugin.initialize({"CurrentPluginMetadata": {"Name": "SSH Launcher",
                                                     "PluginDirectory": PLUGIN_DIR,
                                                     "PluginSettingsDirectoryPath": live.settings_dir,
                                                     "Version": "live-test"}})

        rows = plugin.query({"Search": ""}, {})["result"]
        check("query lists the configured destination and the edit row",
              [r["Title"] for r in rows] == ["faketest", "Edit destinations file"],
              [r["Title"] for r in rows])

        settings, destinations, error = plugin._load()
        destination = destinations[0]
        ssh_list = launcher.ssh_argv(destination, settings)
        check("params inserted before the target and -p used only for non-22 ports",
              ssh_list[1:] == ["-o", "ServerAliveInterval=30", "-i", "C:/keys/my key.pem",
                               "-p", "2222", "demo@example.invalid"], ssh_list)

        # 1. Windows Terminal through the plugin's own action path.
        live.clear_args()
        plugin.open_destination("faketest", "wt")
        got = wait_for(live.args_file)
        check("wt: terminal opened and handed the ssh arguments to the command", got)
        if got:
            with open(live.args_file, "r", encoding="utf-8", errors="replace") as handle:
                line = handle.read().strip()
            check("wt: arguments survived Windows Terminal's command line parsing",
                  "-p 2222" in line and "demo@example.invalid" in line and "my key.pem" in line, line)
            check("wt: global extra args present", "-o ServerAliveInterval=30" in line, line)

        # 2. cmd and powershell - use the plugin's builders, but keep the process
        #    handle so the window can be closed again afterwards.
        for terminal in ("cmd", "powershell"):
            live.clear_args()
            argv = launcher.terminal_argv(terminal, ssh_list, settings, destination["alias"])
            process = launcher.spawn(argv, launcher._needs_new_console(terminal), log)
            got = wait_for(live.args_file)
            check("%s: terminal opened and ran the command" % terminal, got, argv)
            if got:
                with open(live.args_file, "r", encoding="utf-8", errors="replace") as handle:
                    line = handle.read().strip()
                check("%s: arguments arrived intact" % terminal,
                      "-p 2222" in line and "demo@example.invalid" in line and "my key.pem" in line,
                      line)
            time.sleep(2.5)
            try:
                process.kill()
                process.wait(timeout=15)
            except Exception as exc:
                log.warn("could not stop %s test process: %s" % (terminal, exc))

        # 3. Clipboard.
        previous = read_clipboard()
        plugin.copy_command("faketest")
        time.sleep(0.6)
        copied = read_clipboard()
        check("copy_command puts the ssh command line on the clipboard",
              copied is not None and "demo@example.invalid" in copied, copied)
        if previous is not None:
            launcher.set_clipboard(previous)
            restored = read_clipboard()
            check("previous clipboard restored", restored == previous,
                  "%r vs %r" % (restored, previous))
    finally:
        log.info("live test finished: %d failures" % len(FAILURES))
        log.close()
        live.close()

    print()
    if FAILURES:
        print("%d CHECK(S) FAILED: %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

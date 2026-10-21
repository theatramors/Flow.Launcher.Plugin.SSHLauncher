# -*- coding: utf-8 -*-
"""Build the ssh command and launch it in a new terminal."""

from __future__ import annotations

import os
import re
import subprocess

from .arguments import is_safe_endpoint, split_arguments
from .matcher import target_of

TERMINALS = {
    "wt": "wt",
    "windows-terminal": "wt",
    "windowsterminal": "wt",
    "terminal": "wt",
    "powershell": "powershell",
    "pwsh": "powershell",
    "ps": "powershell",
    "cmd": "cmd",
    "cmd.exe": "cmd",
    "conhost": "cmd",
}

_CREATED_FLAG = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_DETACHED_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
)

# Characters PowerShell treats as syntax outside a single-quoted string.  It
# also accepts the Unicode single (U+2018-U+201B) and double (U+201C-U+201E)
# quotes as string delimiters.
_PS_SINGLE_QUOTES = re.compile("['\u2018\u2019\u201a\u201b]")
_PS_SPECIAL = re.compile("[\\s'\"`$&|<>^();,{}\u2018-\u201e]")


def resolve_terminal(value, log=None):
    key = str(value or "").strip().lower()
    if not key:
        return "wt"
    terminal = TERMINALS.get(key)
    if terminal is None:
        if log:
            log.warn("unknown terminal %r, using wt" % value)
        return "wt"
    return terminal


def ssh_argv(dest, settings):
    """The plain ``ssh ...`` argument vector for a destination.

    A destination imported from an ssh config is *not* re-implemented here:
    the parsed user/host/port are only best-effort metadata for search and
    display.  The real command hands OpenSSH the same file (``-F``) and the
    alias, so IdentityFile, ProxyJump, Match blocks and wildcard patterns keep
    working exactly as they do in a plain shell.
    """
    exe = str(settings.get("ssh") or "ssh").strip() or "ssh"
    argv = [exe]
    # Config strings are split with backslashes kept literal; a POSIX split
    # silently ate C:\keys\id_ed25519.
    argv.extend(split_arguments(settings.get("extra_ssh_args")))
    argv.extend(split_arguments(dest.get("ssh_args")))
    if str(dest.get("source") or "") == "ssh_config":
        config_path = str(dest.get("ssh_config_path") or "").strip()
        if config_path:
            argv.extend(["-F", os.path.expanduser(config_path)])
        _reject_option_like(dest.get("alias"), "alias")
        argv.append(str(dest.get("alias") or ""))
        return _append_remote_command(argv, dest)
    port = dest.get("port")
    if port not in (None, "", 0, "0") and str(port) != "22":
        argv.extend(["-p", str(port)])
    _reject_option_like(target_of(dest), "destination")
    argv.append(target_of(dest))
    return _append_remote_command(argv, dest)


def _reject_option_like(value, field):
    """A destination reading like ``-oProxyCommand=...`` must never reach ssh.

    ssh takes any argument starting with ``-`` as an option, so a config value
    could otherwise ask it to run a local command (``ProxyCommand``).  The
    config loader already drops such entries; this is the last line of defence.
    """
    if not is_safe_endpoint(value):
        raise UnsafeArgumentError(
            "refusing to launch: the %s is not a plain host name (it is empty, "
            "starts with '-', or contains whitespace or shell syntax). Fix the "
            "destination in the plugin settings file." % field,
            reason="the %s is not a plain host name" % field,
        )


def _append_remote_command(argv, dest):
    """Append the remote command exactly as the user wrote it.

    ssh joins the remaining arguments with single spaces and passes the result
    to the remote shell, so a *string* command is appended as one argument:
    quoting and shell operators must survive the trip, not be shlex-split
    locally.  A list keeps one argument per element.
    """
    command = dest.get("command")
    if command:
        if isinstance(command, str):
            argv.append(command)
        else:
            argv.extend(str(arg) for arg in command)
    return argv


def ssh_command_line(argv):
    """Render a copyable PowerShell command (the default Windows shell)."""
    quoted = [_powershell_quote(str(arg)) for arg in argv]
    command = " ".join(quoted)
    if quoted and quoted[0] != str(argv[0]):
        command = "& " + command
    return command


def _powershell_quote(arg):
    if arg == "":
        return "''"
    # The Unicode single quotes are doubled like the ASCII one.  A leading
    # '@'/'#' starts special syntax (splat, hash literal, comment) and is
    # quoted for the same reason.
    if _PS_SPECIAL.search(arg) or arg[0] in "@#":
        return "'" + _PS_SINGLE_QUOTES.sub(lambda m: m.group(0) * 2, arg) + "'"
    return arg


def _cmd_quote(arg):
    if arg == "":
        return '""'
    if not re.search(r'[\s&|<>^()"]', arg) and not arg.endswith("\\"):
        return arg
    body = arg.replace('"', '\\"')
    # A trailing backslash would escape the closing quote, so double the run.
    trailing = len(body) - len(body.rstrip("\\"))
    if trailing:
        body = body[:-trailing] + "\\" * (trailing * 2)
    return '"' + body + '"'


class RawCommandLine(str):
    """A complete Windows command line, already quoted.

    ``subprocess.Popen`` passes a *string* straight to ``CreateProcess``; a
    list would be re-quoted by ``list2cmdline``, which double-escapes quotes we
    put in ourselves (paths with spaces broke exactly that way).
    """


class UnsafeArgumentError(ValueError):
    """An argument the target terminal cannot carry without risking injection.

    ``reason`` names the check that failed - terminal and character, or field -
    without the argument value, so it is safe for the shared log.
    """

    def __init__(self, message, reason="unsafe argument"):
        ValueError.__init__(self, message)
        self.reason = reason


# Characters a terminal's *own* command-line parser treats as syntax and that
# cannot be quoted away reliably.  Passing one through could make the terminal
# run a second, local command taken from a config value - so the plugin refuses
# instead of guessing.  (PowerShell is absent: single-quoting escapes it fully.)
_TERMINAL_UNSAFE = {
    "wt": (";",),  # wt separates commands with ';'
    "cmd": ("%", '"'),  # % expands; a literal quote is not reliably escapable
}
_UNSAFE_CONTROL = ("\r", "\n", "\x00")
# Whole arguments a terminal drops or reinterprets no matter how they are
# quoted.  PowerShell (5.1 and 7) removes an argument whose value is exactly
# '--%' (its stop-parsing token) even when quoted or passed from a variable -
# verified with an argv stub in tests/test_windows_command_line.py.
_TERMINAL_UNSAFE_TOKENS = {
    "powershell": ("--%",),
}


def _reject_unsafe(terminal, arguments):
    unsafe = _UNSAFE_CONTROL + _TERMINAL_UNSAFE.get(terminal, ())
    tokens = _TERMINAL_UNSAFE_TOKENS.get(terminal, ())
    for argument in arguments:
        text = str(argument)
        if text in tokens:
            raise UnsafeArgumentError(
                "refusing to launch in %s: that terminal drops the argument %r "
                "however it is quoted. Choose a different terminal for this "
                "destination." % (terminal, text),
                reason="%s drops the argument %r" % (terminal, text),
            )
        for char in unsafe:
            if char in text:
                raise UnsafeArgumentError(
                    "refusing to launch in %s: the argument %r contains %r, which that "
                    "terminal resolves as command-line syntax and which cannot be escaped "
                    "safely. Remove it or choose a different terminal for this "
                    "destination." % (terminal, text, char),
                    reason="%s cannot carry the character %r" % (terminal, char),
                )


def terminal_argv(terminal, ssh_argv_list, settings, title):
    """Argument vector that opens the ssh session in a new terminal."""
    terminal = resolve_terminal(terminal)
    if terminal == "powershell":
        _reject_unsafe("powershell", ssh_argv_list)
        quoted = [_powershell_quote(arg) for arg in ssh_argv_list]
        command = " ".join(quoted)
        if quoted and quoted[0] != str(ssh_argv_list[0]):
            # A quoted executable is just a string expression in PowerShell;
            # the call operator & is what actually runs it.
            command = "& " + command
        return ["powershell.exe", "-NoExit", "-Command", command]
    if terminal == "cmd":
        _reject_unsafe("cmd", ssh_argv_list)
        inner = " ".join(_cmd_quote(arg) for arg in ssh_argv_list)
        # /d skips AutoRun, /v:off disables delayed expansion (! stays literal)
        # and /s makes cmd strip exactly the outer quote pair we add here,
        # handing our command line through unchanged.
        return RawCommandLine('cmd.exe /d /v:off /s /k "' + inner + '"')

    _reject_unsafe("wt", list(ssh_argv_list) + [str(title)])

    argv = ["wt.exe"]
    window = str(settings.get("wt_window") or "").strip()
    if window:
        argv.extend(["-w", window])
    argv.extend(["new-tab", "--title", str(title)])
    argv.extend(ssh_argv_list)
    return argv


def _needs_new_console(terminal):
    return resolve_terminal(terminal) != "wt"


def spawn(argv, new_console, log=None):
    """Start the terminal detached from the plugin process.

    stdin/stdout/stderr all go to DEVNULL: the ssh session must never inherit
    the JSON-RPC pipes Flow Launcher talks to this plugin over.
    """
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _CREATED_FLAG if new_console else _DETACHED_FLAGS
    process = subprocess.Popen(argv, **kwargs)
    if log:
        # A raw command line is a string: argv[0] would be its first character.
        program = argv[0] if isinstance(argv, (list, tuple)) else str(argv).split(None, 1)[0]
        log.info("spawned[%s] %s" % (process.pid, program))
    return process


def set_clipboard(text):
    """Put *text* on the Windows clipboard (no console window involved)."""
    try:
        import ctypes
        from ctypes import wintypes

        cf_unicodetext = 13
        gmem_moveable = 0x0002

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)

        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(gmem_moveable, size)
            if not handle:
                return False
            transferred = False
            try:
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return False
                try:
                    ctypes.memmove(pointer, buffer, size)
                finally:
                    kernel32.GlobalUnlock(handle)
                transferred = bool(user32.SetClipboardData(cf_unicodetext, handle))
                return transferred
            finally:
                # The clipboard takes ownership only when SetClipboardData
                # succeeds.  On every other path the block is still ours, and
                # leaving it allocated would leak on each failed copy.
                if not transferred:
                    kernel32.GlobalFree(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def open_path(path, editor=""):
    """Open *path* in the configured editor or with the default handler."""
    editor = str(editor or "").strip()
    try:
        if editor:
            argv = [editor, path] if not os.path.isfile(editor) else [editor, path]
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=_DETACHED_FLAGS if os.name == "nt" else 0,
            )
            return process.pid, " ".join(argv)
        if hasattr(os, "startfile"):
            os.startfile(path)  # noqa: S606 - user's own file, default handler
            return 0, path
        process = subprocess.Popen(["xdg-open", path])
        return process.pid, "xdg-open " + path
    except Exception:
        process = subprocess.Popen(
            ["notepad.exe", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=_DETACHED_FLAGS if os.name == "nt" else 0,
        )
        return process.pid, "notepad.exe " + path

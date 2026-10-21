# -*- coding: utf-8 -*-
"""Argument handling shared by the config loader and the command builder.

``ssh_args`` (per destination) and ``extra_ssh_args`` (global) may be written as
a list - the documented form - or as a single string.  Windows paths are full of
backslashes, so a string is split with *Windows* rules: a backslash is an
ordinary character (POSIX shells treat it as an escape, which turned
``C:\\keys\\id_ed25519`` into ``C:keysid_ed25519``), whitespace separates
arguments, and single or double quotes group a run of text.

An unbalanced quote is taken literally instead of raising: one mistyped entry
must never take the whole result list down.

The same module holds the value checks that keep a config value from being read
as an ssh *option* (a ``host`` of ``-oProxyCommand=...`` would otherwise run a
local command).
"""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PORT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def split_arguments(value, log=None):
    """Return the argument list for a config value.

    * ``None`` / empty string -> ``[]``
    * list / tuple            -> element-wise ``str()``, ``None`` entries dropped
    * string                  -> Windows-style split (quotes removed, ``\\`` kept)
    * anything else           -> ``[]`` (the caller reports it as a bad entry)
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    if not isinstance(value, str):
        return []

    tokens = []
    current = []
    started = False
    quote = ""
    for char in value:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
            continue
        if char in "\"'":
            quote = char
            started = True
            continue
        if char.isspace():
            if started:
                tokens.append("".join(current))
                current = []
                started = False
            continue
        current.append(char)
        started = True
    if started:
        tokens.append("".join(current))
    if quote and log:
        # No value: the string is the user's own arguments, which may hold
        # paths and key names that do not belong in a shared log.
        log.warn("an argument string has an unbalanced quote; taken literally")
    return tokens


def is_safe_endpoint(value):
    """True when *value* may be used as an ssh destination or user name.

    Only what ssh itself would misread is refused: an empty value, a leading
    ``-`` (an *option* - ``-oProxyCommand=...`` runs a local command),
    whitespace (the value would no longer be one argument) and control
    characters.  Shell syntax is the terminal quoting's job, and non-ASCII
    user and host names (``DOMAIN\\vadim`` in Cyrillic, IDNs) are legitimate.
    """
    text = str(value or "")
    if not text or text.startswith("-"):
        return False
    return not any(char.isspace() for char in text) and not _CONTROL.search(text)


def is_safe_label(value):
    """True for an alias that is only a label (search text, tab title).

    A JSON destination's alias never reaches ssh - ssh gets ``user@host`` -
    so anything printable is fine, spaces and Cyrillic included.  Only an
    empty value and control characters are refused.
    """
    text = str(value or "")
    return bool(text.strip()) and not _CONTROL.search(text)


def is_safe_port(value):
    """True for a port number or a service name ssh would accept.

    The port is passed as one argv element after ``-p``, so a value like
    ``-oProxyCommand=...`` cannot become a separate option - but a value ssh
    would misinterpret still deserves a clear "this entry is wrong" row.
    """
    return _PORT.fullmatch(str(value if value is not None else "").strip()) is not None

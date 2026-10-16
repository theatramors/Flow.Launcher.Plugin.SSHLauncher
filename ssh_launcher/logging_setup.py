# -*- coding: utf-8 -*-
"""Small rotating file log.

The plugin process is long lived and its stdout *is* the JSON-RPC channel to
Flow Launcher, so nothing may ever be printed there.  ``install()`` therefore
points ``sys.stdout`` and ``sys.stderr`` at the log file and returns the raw
stdout handle the RPC loop must use for replies.
"""

from __future__ import annotations

import os
import sys
import threading
import time

_MAX_BYTES = 512 * 1024


class Log(object):
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._fh = None

    def open(self):
        try:
            directory = os.path.dirname(self.path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            self._rotate()
            self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        except Exception:
            self._fh = None
        return self

    def _rotate(self):
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > _MAX_BYTES:
                backup = self.path + ".1"
                if os.path.exists(backup):
                    os.remove(backup)
                os.replace(self.path, backup)
        except Exception:
            pass

    def _write(self, level, message):
        line = "%s [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, message)
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.write(line)
                    self._fh.flush()
                except Exception:
                    pass

    def info(self, message):
        self._write("INFO", message)

    def warn(self, message):
        self._write("WARN", message)

    def error(self, message):
        self._write("ERROR", message)

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    # -- enough of the file API that sys.stdout may be replaced by this object,
    #    so a stray print() lands in the log instead of corrupting the RPC pipe.
    encoding = "utf-8"
    errors = "replace"

    def write(self, text):
        if text and text.strip():
            self._write("STDOUT", text.rstrip("\n"))

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                except Exception:
                    pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("the plugin log has no file descriptor")


def install(log_path):
    """Send stdout/stderr to the log and return (log, raw_stdout)."""
    log = Log(log_path).open()
    raw_stdout = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    sys.stdout = log
    sys.stderr = log
    return log, raw_stdout

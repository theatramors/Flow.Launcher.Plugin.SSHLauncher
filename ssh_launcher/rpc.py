# -*- coding: utf-8 -*-
"""Newline-delimited JSON-RPC 2.0 server - the transport Flow Launcher uses for
``Python_v2`` plugins.

Flow starts this process once, sends ``initialize`` then one ``query`` per
keystroke, and calls methods named in a result's ``JsonRPCAction`` when the user
picks that result.  Replies are single-line JSON objects written to stdout; the
process must never write anything else there.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

from .logging_setup import install
from .plugin import Plugin

METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
PARSE_ERROR = -32700


class Server(object):
    def __init__(self, out_stream, log, plugin_dir):
        self._out = out_stream
        self.log = log
        self.plugin = Plugin(log, plugin_dir)
        self._running = True

    # ------------------------------------------------------------- transport

    def _send(self, payload):
        data = (json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8")
        self._out.write(data)
        self._out.flush()

    def _send_result(self, request_id, result):
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _send_error(self, request_id, code, message, data=None):
        error = {"code": code, "message": str(message)}
        if data:
            error["data"] = str(data)[-2000:]
        self._send({"jsonrpc": "2.0", "id": request_id, "error": error})

    def serve(self):
        self.log.info("SSH Launcher plugin started (pid %d, python %s)" % (os.getpid(), sys.version.split()[0]))
        stdin = sys.stdin.buffer
        while self._running:
            try:
                raw = stdin.readline()
            except Exception as exc:  # pragma: no cover - transport level
                self.log.error("stdin read failed: %s" % exc)
                break
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except Exception as exc:
                # Never echo the payload: it carries the user's search text.
                self.log.error("cannot parse request: %s" % exc)
                self._send_error(None, PARSE_ERROR, "invalid JSON: %s" % exc)
                continue
            self._handle(message)
        self.log.info("SSH Launcher plugin stopped")

    # -------------------------------------------------------------- dispatch

    @staticmethod
    def _normalize_params(params):
        """Undo the two shapes StreamJsonRpc may deliver.

        Flow invokes actions as ``InvokeAsync(method, argument: Parameters)``
        and an empty ``Parameters`` list arrives as a single list argument
        (observed live: ``edit_config() takes 1 positional argument but 2 were
        given``).  Unwrap ``[[a, b]]`` to ``[a, b]`` and drop bare ``[None]``.
        """
        if isinstance(params, list) and len(params) == 1 and isinstance(params[0], list):
            params = params[0]
        if isinstance(params, list) and params and all(p is None for p in params):
            params = []
        return params

    def _handle(self, message):
        if not isinstance(message, dict):
            return
        method = message.get("method")
        if not method:
            return
        request_id = message.get("id")
        params = self._normalize_params(message.get("params"))
        if params is None:
            params = []
        elif isinstance(params, dict):
            params = [params]
        if not isinstance(params, list):
            params = [params]
        # Method name only - the params hold the query text and destination
        # aliases, and this log gets pasted into bug reports.
        self.log.info("request %s" % method)

        if request_id is None:
            # Notification: run it, no reply expected.
            try:
                self._call(method, params)
            except Exception:
                self.log.error("notification %s failed:\n%s" % (method, traceback.format_exc()))
            return

        try:
            result = self._call(method, params)
        except NotImplementedError:
            self._send_error(request_id, METHOD_NOT_FOUND, "unknown method %s" % method)
            return
        except Exception as exc:
            self.log.error("method %s failed:\n%s" % (method, traceback.format_exc()))
            if method in _ACTION_METHODS:
                # An *error* reply for an action blows up on Flow's UI
                # dispatcher (DispatcherUnhandledException, observed live), so
                # report a normal result - but hide:false, because pretending
                # the action succeeded hides the problem from the user.
                self._send_result(request_id, {"hide": False})
            else:
                self._send_error(request_id, INTERNAL_ERROR, "%s: %s" % (type(exc).__name__, exc),
                                 traceback.format_exc())
            return
        self._send_result(request_id, result)

    def _call(self, method, params):
        if method not in _SERVER_METHODS and method not in _ACTION_METHODS:
            # Deliberately no getattr fallback: without an allowlist, any
            # attribute of the plugin object ("path", "icon", ...) could be
            # invoked over the wire and would hand its value back to the caller.
            raise NotImplementedError(method)
        if method == "initialize":
            self.plugin.initialize(params[0] if params else {})
            return None
        if method == "query":
            query = params[0] if params else {}
            settings = params[1] if len(params) > 1 else {}
            return self.plugin.query(query, settings)
        if method == "context_menu":
            data = params[0] if params else ""
            return {"result": self.plugin.context_menu(data), "debugMessage": ""}
        if method == "reload_data":
            self.plugin._load(force=True)
            self.log.info("reload_data requested")
            return None
        if method == "close":
            self._running = False
            self.log.info("close requested")
            return None

        return getattr(self.plugin, method)(*params)


_SERVER_METHODS = frozenset((
    "initialize", "query", "context_menu", "reload_data", "close",
))

_ACTION_METHODS = frozenset((
    "open_destination", "copy_command", "edit_config",
    "open_settings_folder", "reset_config",
))


def serve():
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(plugin_dir, "logs", "ssh-launcher.log")
    log, out_stream = install(log_path)
    try:
        Server(out_stream, log, plugin_dir).serve()
    except Exception:
        log.error("fatal error in server loop:\n%s" % traceback.format_exc())
    finally:
        log.close()

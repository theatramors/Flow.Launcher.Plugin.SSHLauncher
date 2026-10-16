# -*- coding: utf-8 -*-
"""Flow Launcher entry point for the SSH Launcher plugin.

Flow Launcher (Python_v2 plugins) runs this file once with the plugin folder,
``<plugin>/lib`` and ``<plugin>/plugin`` already on ``sys.path`` and then talks
to the process over newline-delimited JSON-RPC 2.0 on stdin/stdout.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ssh_launcher.rpc import serve  # noqa: E402

if __name__ == "__main__":
    serve()

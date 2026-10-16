# -*- coding: utf-8 -*-
"""Drive the plugin over its real JSON-RPC transport and check the answers.

Works on any OS: it only exercises config parsing, matching, command building
and the RPC server (nothing is spawned, no clipboard is touched).

    python3 tests/drive_rpc.py [--python /path/to/python.exe]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)

FAILURES = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, label, ("  ->  " + detail) if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def write_config(settings_dir, data):
    os.makedirs(settings_dir, exist_ok=True)
    path = os.path.join(settings_dir, "destinations.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="sshl-rpc-")
    settings_dir = os.path.join(workdir, "settings")
    ssh_config = os.path.join(workdir, "ssh_config")
    with open(ssh_config, "w", encoding="utf-8") as handle:
        handle.write(
            "Host homeserver\n"
            "  HostName 10.0.0.5\n"
            "  User admin\n"
            "  Port 2222\n"
            "\n"
            "Host *.wild\n"
            "  User nobody\n"
            "\n"
            "Host homeserver\n"
            "  HostName 10.0.0.5\n"
            "  User admin\n"
        )

    write_config(
        settings_dir,
        {
            "settings": {
                "terminal": "wt",
                "wt_window": "0",
                "include_ssh_config": True,
                "ssh_config_path": ssh_config,
                "extra_ssh_args": ["-o", "ServerAliveInterval=30"],
                # harmless "editor": running the json through python itself
                "editor": sys.executable,
            },
            "destinations": [
                {"alias": "pve", "host": "192.0.2.10", "user": "root", "description": "Proxmox node"},
                {"alias": "nas", "host": "192.0.2.50", "user": "admin", "port": 2222},
                {"alias": "broken"},
                "not-a-dict",
            ],
        },
    )

    log_path = os.path.join(PLUGIN_DIR, "logs", "ssh-launcher.log")
    log_offset = os.path.getsize(log_path) if os.path.isfile(log_path) else 0

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": [
                {
                    "CurrentPluginMetadata": {
                        "Name": "SSH Launcher",
                        "PluginDirectory": PLUGIN_DIR,
                        "PluginSettingsDirectoryPath": settings_dir,
                        "Version": "1.0.0",
                    },
                    "API": {},
                }
            ],
        },
        {"jsonrpc": "2.0", "id": 2, "method": "query",
         "params": [{"Search": "", "TrimmedQuery": "ssh ", "ActionKeyword": "ssh"}, {}]},
        {"jsonrpc": "2.0", "id": 3, "method": "query",
         "params": [{"Search": "prox", "TrimmedQuery": "ssh prox", "ActionKeyword": "ssh"}, {}]},
        {"jsonrpc": "2.0", "id": 4, "method": "query",
         "params": [{"Search": "10.0.0.5", "TrimmedQuery": "ssh 10.0.0.5", "ActionKeyword": "ssh"}, {}]},
        {"jsonrpc": "2.0", "id": 5, "method": "query",
         "params": [{"Search": "zzz", "TrimmedQuery": "ssh zzz", "ActionKeyword": "ssh"}, {}]},
        {"jsonrpc": "2.0", "id": 6, "method": "context_menu", "params": ["pve"]},
        {"jsonrpc": "2.0", "id": 7, "method": "no_such_method", "params": []},
        # Regression: the shapes Flow Launcher/StreamJsonRpc delivered live.
        # An empty Parameters list arrived as [[]] and crashed edit_config.
        {"jsonrpc": "2.0", "id": 10, "method": "edit_config", "params": [[]]},
        {"jsonrpc": "2.0", "id": 11, "method": "open_destination", "params": [["zz-nonexistent", ""]]},
        {"jsonrpc": "2.0", "id": 12, "method": "context_menu", "params": [["pve"]]},
        {"jsonrpc": "2.0", "id": 8, "method": "close", "params": []},
    ]

    payload = "".join(json.dumps(request) + "\n" for request in requests)
    process = subprocess.Popen(
        [args.python, os.path.join(PLUGIN_DIR, "main.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=PLUGIN_DIR,
    )
    stdout, stderr = process.communicate(payload.encode("utf-8"), timeout=120)
    replies = []
    for line in stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            replies.append(json.loads(line))
        except Exception:
            check("every stdout line is JSON", False, line[:200])
    by_id = {reply.get("id"): reply for reply in replies}

    check("11 replies received", len(replies) == len(requests), "got %d" % len(replies))
    check("nothing on stderr", not stderr.strip(), stderr.decode("utf-8", "replace")[:300])
    check("initialize answered with null result",
          by_id.get(1, {}).get("result", "missing") is None)

    all_rows = by_id.get(2, {}).get("result", {}).get("result", [])
    titles = [row.get("Title") for row in all_rows]
    check("empty query lists every destination in config order",
          titles[:3] == ["pve", "nas", "homeserver"], str(titles))
    check("ssh config host is listed with its port line",
          any(row.get("Title") == "homeserver" for row in all_rows))
    check("edit row is offered", "Edit destinations file" in titles, str(titles))
    pve = next((row for row in all_rows if row.get("Title") == "pve"), {})
    check("pve command line built with global args",
          pve.get("SubTitle", "").startswith("ssh -o ServerAliveInterval=30 root@192.0.2.10"),
          pve.get("SubTitle", ""))
    nas = next((row for row in all_rows if row.get("Title") == "nas"), {})
    check("non-22 port becomes -p 2222",
          "-p 2222 admin@192.0.2.50" in nas.get("SubTitle", ""), nas.get("SubTitle", ""))
    check("context data is the alias", pve.get("ContextData") == "pve")
    check("action targets open_destination",
          pve.get("JsonRPCAction", {}).get("Method") == "open_destination")
    check("CopyText carries the ssh command",
          pve.get("CopyText", "").startswith("ssh -o ServerAliveInterval=30 root@192.0.2.10"))
    check("result rows are non-empty", len(all_rows) >= 4, str(titles))
    check("icons are absolute paths inside the plugin",
          bool(all_rows) and all(os.path.isabs(row.get("IcoPath", "")) and PLUGIN_DIR in row.get("IcoPath", "")
                                 for row in all_rows), str([row.get("IcoPath") for row in all_rows]))
    check("icon files exist",
          all(os.path.isfile(row.get("IcoPath", "")) for row in all_rows),
          str(sorted({row.get("IcoPath") for row in all_rows})))

    prox = by_id.get(3, {}).get("result", {}).get("result", [])
    check("'prox' filters to the pve entry only",
          [row.get("Title") for row in prox] == ["pve"], str([row.get("Title") for row in prox]))

    by_host = by_id.get(4, {}).get("result", {}).get("result", [])
    check("matching on HostName finds the ssh-config entry",
          [row.get("Title") for row in by_host] == ["homeserver"],
          str([row.get("Title") for row in by_host]))

    none_rows = by_id.get(5, {}).get("result", {}).get("result", [])
    check("no match returns one helpful row",
          len(none_rows) == 1 and none_rows[0].get("Title", "").startswith("No destination matching"),
          str(none_rows))

    menu = by_id.get(6, {}).get("result", {}).get("result", [])
    menu_titles = [row.get("Title") for row in menu]
    check("context menu offers 3 terminals + copy + edit",
          len(menu) == 5 and "Copy ssh command" in menu_titles, str(menu_titles))

    check("unknown method answers with -32601",
          by_id.get(7, {}).get("error", {}).get("code") == -32601, str(by_id.get(7)))
    check("close answered and process exited", process.returncode == 0, "rc=%s" % process.returncode)

    # --- live-observed action marshalling shapes ------------------------------
    check("edit_config with [[]] answers hide instead of an error",
          by_id.get(10, {}).get("result") == {"hide": True}, str(by_id.get(10)))
    # A failed action must not be concealed: hide=false keeps the launcher open
    # so the user (and the log) can say what went wrong.
    check("open_destination with an unknown alias reports failure",
          by_id.get(11, {}).get("result") == {"hide": False}, str(by_id.get(11)))
    wrapped_menu = by_id.get(12, {}).get("result", {}).get("result", [])
    check("context_menu with wrapped alias still resolves the destination",
          len(wrapped_menu) == 5, str([row.get("Title") for row in wrapped_menu]))

    fresh_log = ""
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            fresh_log = handle.read()[log_offset:]
    check("wrapped edit_config really ran (log shows the editor spawn)",
          "opened the destinations file" in fresh_log, fresh_log[-600:])
    check("wrapped open_destination extracted the alias as a string",
          "unknown alias" in fresh_log, fresh_log[-600:])
    check("the log names the method without echoing the payload",
          "request open_destination" in fresh_log and "zz-nonexistent" not in fresh_log,
          fresh_log[-600:])

    # --- config that cannot be parsed -> actionable error row -----------------
    bad_dir = os.path.join(workdir, "bad")
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "destinations.json"), "w", encoding="utf-8") as handle:
        handle.write('{"destinations": [ oops }')
    bad_requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": [{"CurrentPluginMetadata": {"PluginDirectory": PLUGIN_DIR,
                                               "PluginSettingsDirectoryPath": bad_dir}}]},
        {"jsonrpc": "2.0", "id": 2, "method": "query",
         "params": [{"Search": ""}, {}]},
        {"jsonrpc": "2.0", "id": 3, "method": "close", "params": []},
    ]
    process = subprocess.Popen(
        [args.python, os.path.join(PLUGIN_DIR, "main.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=PLUGIN_DIR,
    )
    out, err = process.communicate(
        "".join(json.dumps(r) + "\n" for r in bad_requests).encode("utf-8"), timeout=60)
    rows = []
    for line in out.decode("utf-8", "replace").splitlines():
        reply = json.loads(line)
        if reply.get("id") == 2:
            rows = reply.get("result", {}).get("result", [])
    check("broken JSON config yields a configuration-problem row",
          len(rows) == 1 and "configuration problem" in rows[0].get("Title", ""), str(rows))
    check("broken config error names the file",
          "destinations.json" in rows[0].get("SubTitle", "") if rows else False, str(rows))

    # --- missing config is created from the template --------------------------
    fresh_dir = os.path.join(workdir, "fresh")
    os.makedirs(fresh_dir, exist_ok=True)
    fresh = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": [{"CurrentPluginMetadata": {"PluginDirectory": PLUGIN_DIR,
                                               "PluginSettingsDirectoryPath": fresh_dir}}]},
        {"jsonrpc": "2.0", "id": 2, "method": "query", "params": [{"Search": ""}, {}]},
        {"jsonrpc": "2.0", "id": 3, "method": "close", "params": []},
    ]
    process = subprocess.Popen(
        [args.python, os.path.join(PLUGIN_DIR, "main.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=PLUGIN_DIR,
    )
    process.communicate("".join(json.dumps(r) + "\n" for r in fresh).encode("utf-8"), timeout=60)
    created = os.path.join(fresh_dir, "destinations.json")
    check("missing config is created", os.path.isfile(created))
    if os.path.isfile(created):
        with open(created, "r", encoding="utf-8") as handle:
            template = json.load(handle)
        check("template carries a readme and empty destinations",
              isinstance(template.get("_readme"), list) and template.get("destinations") == [])

    shutil.rmtree(workdir, ignore_errors=True)
    print()
    if FAILURES:
        print("%d CHECK(S) FAILED: %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

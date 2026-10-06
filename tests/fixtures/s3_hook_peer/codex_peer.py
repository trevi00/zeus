#!/usr/local/bin/python3
"""S3b fixture peer (NOT Codex; no provider, no model, no network): an App Server JSON-RPC stand-in.

It answers `initialize`, `hooks/list` (the entry shape observed from the real pinned CLI: top-level
`command`, `currentHash`, camelCase `trustStatus`, `timeoutSec`; a hook is `trusted` only when the startup
`hooks.state` names its current hash), `thread/start` and `turn/start`. On a turn it runs every TRUSTED,
enabled PreToolUse hook as the pinned CLI does: `shlex.split(command)`, the session cwd, one JSON object
on stdin, the configured timeout (process group killed on expiry), and reports `hook/completed`. A hook
that fails or times out fails the turn; the turn completes only when every trusted hook succeeded.
"""
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import tomllib

args = sys.argv[1:]
config = {}
if "-c" in args:
    literal = args[args.index("-c") + 1]
    config = tomllib.loads("hooks = " + literal[len("hooks="):])["hooks"]
state = config.pop("state", {})
enabled = "--enable" in args and args[args.index("--enable") + 1] == "hooks"
SNAKE = {"PreToolUse": "pre_tool_use", "PostToolUse": "post_tool_use", "Stop": "stop", "SessionStart": "session_start"}


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def entries():
    rows = []
    for event, groups in config.items() if enabled else ():
        for g, group in enumerate(groups):
            for h, hook in enumerate(group["hooks"]):
                key = "/<session-flags>/config.toml:%s:%d:%d" % (SNAKE[event], g, h)
                current = "sha256:" + hashlib.sha256(json.dumps([event, group.get("matcher"), hook],
                                                                sort_keys=True).encode()).hexdigest()
                trusted = state.get(key, {}).get("trusted_hash")
                status = "trusted" if trusted == current else ("modified" if trusted else "untrusted")
                rows.append({"key": key, "eventName": event, "command": hook["command"], "currentHash": current,
                             "trustStatus": status, "enabled": True, "timeoutSec": hook["timeout"]})
    return rows


def run_hook(row, cwd):
    event = {"hook_event_name": row["eventName"], "tool_name": "shell", "cwd": cwd}
    child = subprocess.Popen(shlex.split(row["command"]), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, _ = child.communicate(json.dumps(event), timeout=row["timeoutSec"])
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.communicate()
        return {"status": "timedOut", "exitCode": None, "stdout": ""}
    return {"status": "completed" if child.returncode == 0 else "failed", "exitCode": child.returncode,
            "stdout": stdout[-2000:]}


cwd = None
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"id": message["id"], "result": {"codexHome": os.environ.get("CODEX_HOME")}})
    elif method == "hooks/list":
        send({"id": message["id"], "result": {"data": [{"cwd": message["params"]["cwds"][0], "hooks": entries()}]}})
    elif method in ("thread/start", "thread/resume"):
        cwd = message["params"]["cwd"]
        send({"id": message["id"], "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        send({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
        runs = []
        for row in entries():
            if row["eventName"] == "PreToolUse" and row["trustStatus"] == "trusted" and row["enabled"]:
                send({"method": "hook/started", "params": {"threadId": "thread-1", "turnId": "turn-1",
                                                          "key": row["key"]}})
                result = run_hook(row, cwd)
                runs.append(result)
                send({"method": "hook/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
                                                            "key": row["key"], "run": result}})
        if all(run["status"] == "completed" for run in runs):
            answer = json.dumps({"summary": json.dumps({"hooks": runs})})
            send({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
                  "item": {"type": "agentMessage", "id": "a1", "text": answer}}})
            send({"method": "turn/completed", "params": {"threadId": "thread-1",
                  "turn": {"id": "turn-1", "status": "completed"}}})
        else:
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {
                "id": "turn-1", "status": "failed", "error": {"message": "hook " + runs[-1]["status"]}}}})

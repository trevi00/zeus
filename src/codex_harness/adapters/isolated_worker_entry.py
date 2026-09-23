"""INV-ISOLATED-WORKER-001: the trusted in-image entrypoint (`/opt/zeus/bin/python -I -m ...`).

It reads one request from stdin, runs the existing `ClaudeCodeRuntime` with container-native paths
and writes tagged lines to stdout: `entered`, `event`, then exactly one `result` or `refused`. It
owns no policy: schema, session, model, budget and terminal checks are the runtime's. The request
comes from the host adapter only; nothing here reads the candidate for configuration.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
from codex_harness.adapters.isolated_worker import (
    DELIVERY_PROTOCOLS,
    PROTOCOL,
    PROTOCOLS,
    SESSION_PROTOCOLS,
)
from codex_harness.adapters.worker_sessions import EXPORT_DIRECTORY, RESTORE_DIRECTORY
from codex_harness.domain.worker_sessions import MODE_FRESH, MODE_RESUME

MAX_REQUEST_BYTES = 32 * 1024 * 1024


def task_session(request: dict, environment=None) -> tuple:
    """INV-WORKER-SESSION-001: the request's task session, bound to this container's fixed paths.

    The restore and export directories must be exactly the fixed names under the mounted evidence
    root, and the CLI home is this container's own disposable `$HOME/.claude`. Returns (home, binding)."""
    session = request.get("task_session")
    if (request["protocol"] in SESSION_PROTOCOLS) != (session is not None):
        raise ValueError("request protocol and task session disagree")
    if session is None:
        return None, None
    if not isinstance(session, dict) or session.get("mode") not in (MODE_FRESH, MODE_RESUME) \
            or session.get("session_id") != request.get("session_id"):
        raise ValueError("task session is malformed or names another session")
    root = str(request["evidence_root"]).rstrip("/")
    if session.get("export") != root + "/" + EXPORT_DIRECTORY:
        raise ValueError("task session export must be the fixed evidence directory")
    resumed = session["mode"] == MODE_RESUME
    if resumed != (session.get("restore") == root + "/" + RESTORE_DIRECTORY) or resumed != isinstance(session.get("manifest"), dict):
        raise ValueError("task session restore must be the fixed evidence directory with its manifest")
    home = (environment if environment is not None else os.environ).get("HOME")
    if not home or not os.path.isabs(home):
        raise ValueError("task session needs this container's own absolute HOME")
    return str(Path(home) / ".claude"), {key: session.get(key) for key in ("mode", "session_id", "manifest",
                                                                             "restore", "export")}


def serve(stdin, stdout, runtime_factory=ClaudeCodeRuntime) -> int:
    lock = threading.Lock()

    def send(kind: str, **body) -> None:
        line = json.dumps({"protocol": PROTOCOL, "kind": kind, **body}, ensure_ascii=False, separators=(",", ":"))
        with lock:
            stdout.write(line.encode("utf-8") + b"\n")
            stdout.flush()

    try:
        raw = stdin.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds budget")
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict) or request.get("protocol") not in PROTOCOLS:
            raise ValueError("request is not " + PROTOCOL)
        # A delivery request names its own protocol, so an older entry refuses it rather than dropping
        # the host checklist; here the two must agree in both directions before anything is opened.
        delivery = request.get("project_delivery")
        if (request["protocol"] in DELIVERY_PROTOCOLS) != (delivery is not None):
            raise ValueError("request protocol and project delivery disagree")
        home, session = task_session(request)
        runtime = {**(request.get("runtime") or {}), "profile_evidence_root": request["evidence_root"]}
        opened = runtime_factory(model=request["model"], runtime=runtime,
                                 max_budget_usd=request.get("max_budget_usd"),
                                 settings_document=request.get("settings_document"),
                                 **({} if delivery is None else {"project_delivery": delivery}),
                                 **({} if session is None else {"session_home": home}))
        with opened as inner:
            result = inner.run(request["prompt"], request["cwd"], request["schema"], request["timeout"],
                               on_event=lambda event: send("event", event=event),
                               on_enter=lambda: send("entered"), session_id=request["session_id"],
                               **({} if session is None else {"task_session": session}))
    except Exception as exc:  # named to the host; the host decides what an unfinished run means
        send("refused", error_type=type(exc).__name__, message=str(exc)[:500])
        return 1
    # The host already holds every forwarded event; the result line stays bounded without them.
    send("result", result={key: value for key, value in result.items() if key != "events"})
    return 0


if __name__ == "__main__":
    raise SystemExit(serve(sys.stdin.buffer, sys.stdout.buffer))

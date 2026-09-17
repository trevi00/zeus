"""INV-ISOLATED-WORKER-001: the trusted in-image entrypoint (`/opt/zeus/bin/python -I -m ...`).

It reads one request from stdin, runs the existing `ClaudeCodeRuntime` with container-native paths
and writes tagged lines to stdout: `entered`, `event`, then exactly one `result` or `refused`. It
owns no policy: schema, session, model, budget and terminal checks are the runtime's. The request
comes from the host adapter only; nothing here reads the candidate for configuration.
"""
from __future__ import annotations

import json
import sys
import threading

from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
from codex_harness.adapters.isolated_worker import PROTOCOL

MAX_REQUEST_BYTES = 32 * 1024 * 1024


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
        if not isinstance(request, dict) or request.get("protocol") != PROTOCOL:
            raise ValueError("request is not " + PROTOCOL)
        runtime = {**(request.get("runtime") or {}), "profile_evidence_root": request["evidence_root"]}
        opened = runtime_factory(model=request["model"], runtime=runtime,
                                 max_budget_usd=request.get("max_budget_usd"),
                                 settings_document=request.get("settings_document"))
        with opened as inner:
            result = inner.run(request["prompt"], request["cwd"], request["schema"], request["timeout"],
                               on_event=lambda event: send("event", event=event),
                               on_enter=lambda: send("entered"), session_id=request["session_id"])
    except Exception as exc:  # named to the host; the host decides what an unfinished run means
        send("refused", error_type=type(exc).__name__, message=str(exc)[:500])
        return 1
    # The host already holds every forwarded event; the result line stays bounded without them.
    send("result", result={key: value for key, value in result.items() if key != "events"})
    return 0


if __name__ == "__main__":
    raise SystemExit(serve(sys.stdin.buffer, sys.stdout.buffer))

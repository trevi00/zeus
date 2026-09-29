"""Shared S4 pure-unit scenario steps (`execution.units`): provider streams and worker-session policy.

Layer: harness (never shipped)

`streams` is the side's provider_stream module and `ws` its worker_sessions domain module. Every
call reports its value or its refusal (exception type name, message and `reason` when present).
Inputs are fixed literals; nothing here reads the clock, the host or a provider.
"""

from __future__ import annotations

SID = "0f0e0d0c-0b0a-4908-8706-050403020100"
SHA = "a" * 64
REV = "b" * 40
IDENTITY = {"task_id": "task-1", "repository": "repo", "workspace": "ws-1", "provider": "claude",
            "model": "m", "runtime_image": "img", "runtime_digest": "sha256:x", "policy_digest": "p",
            "config_digest": "c"}


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc), "reason": getattr(exc, "reason", None)}


CODEX_EVENTS = [
    {"method": "item/completed", "params": {"item": {"id": "i1", "type": "commandExecution", "status": "completed"}}},
    {"method": "item/completed", "params": {"item": {"id": "i2", "type": "agentMessage"}, "timestamp": 1767225600000}},
    {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"total": {"totalTokens": 5}}}},
    {"method": "turn/completed", "params": {"turn": {"id": "t1", "status": "completed"}}},
    {"method": [], "params": {}},
    {"method": "item/completed", "params": "garbage"},
    {"method": "item/completed", "params": {"item": "garbage"}},
    {"params": {}},
    "not-an-event",
    None,
]
CLAUDE = "claude-code-cli"
CLAUDE_EVENTS = [
    {"type": "session_started", "id": SID, "provider": CLAUDE, "raw_type": "system"},
    {"type": "tool_completed", "id": "tu1", "item_type": "Bash", "status": "completed", "raw_type": "user",
     "provider": CLAUDE, "occurred_at": 1767225600000},
    {"type": "tool_started", "id": "tu2", "item_type": "Read", "status": "started", "raw_type": "assistant",
     "provider": CLAUDE},
    {"type": "permission_denied", "id": "d1", "raw_type": "system", "provider": CLAUDE},
    {"type": "result", "id": SID, "status": "success", "raw_type": "result", "provider": CLAUDE},
    {"type": "assistant", "id": "a1", "raw_type": "assistant", "provider": CLAUDE},
    {"type": "assistant", "id": "a1", "raw_type": "assistant"},
    {"type": 7, "provider": CLAUDE},
    [],
]


def stream_steps(streams) -> dict:
    out = {"constants": {"codex_progress": list(streams.CODEX_PROGRESS),
                         "claude_progress": list(streams.CLAUDE_PROGRESS),
                         "tool_item_types": list(streams.TOOL_ITEM_TYPES)},
           "epoch_millis": [call(streams.epoch_millis, v) for v in (1767225600000, 0, -1, 10**15, "1", True)],
           "stream_for": {}}
    for transport in ("app_server", "claude_cli", "other"):
        chosen = call(streams.stream_for, transport)
        out["stream_for"][transport] = ({"identity": chosen["value"].identity, "transport": chosen["value"].transport}
                                        if "value" in chosen else chosen)
    for name, reader, events in (("codex", streams.CodexStream, CODEX_EVENTS),
                                 ("claude", streams.ClaudeStream, CLAUDE_EVENTS)):
        rows = []
        for event in events:
            row = {"shape": call(reader.shape, event)}
            if row["shape"].get("value") is None and "value" in row["shape"]:
                for method in ("is_progress", "occurrence", "label", "item_type", "item_status", "completed_item"):
                    row[method] = call(getattr(reader, method), event)
                row["event_id"] = call(reader.event_id, event, "sha256:" + SHA)
            rows.append(row)
        out[name] = {"events": rows,
                     "tool_items": call(reader.tool_items, [e for e in events if isinstance(e, dict)])}
    return out


def session_steps(ws) -> dict:
    out = {"states": list(ws.STATES), "resumable": sorted(ws.RESUMABLE), "blocked": sorted(ws.BLOCKED_STATES),
           "modes": [ws.MODE_FRESH, ws.MODE_RESUME], "schema": [ws.SCHEMA, ws.ARCHIVE_SCHEMA, ws.PROMOTION_SCHEMA]}
    out["transitions"] = {str(current): {target: "value" in call(ws.transition, current, target) for target in ws.STATES}
                          for current in (None, *ws.STATES)}
    out["transition_refusal"] = call(ws.transition, ws.CLOSED, ws.ACTIVE)
    out["identity"] = [call(ws.validate_identity, v) for v in (
        IDENTITY, {**IDENTITY, "extra": "x"}, {**IDENTITY, "model": ""}, {**IDENTITY, "model": 7}, "x")]
    out["compare"] = [call(ws.compare_identity, IDENTITY, v) for v in (
        IDENTITY, {**IDENTITY, "workspace": "ws-2"}, {**IDENTITY, "model": "n", "runtime_digest": "y"},
        {**IDENTITY, "task_id": "t2", "model": "n"})]
    out["owner"] = [call(ws.validate_owner, v) for v in (
        {"execution": "e", "generation": 1, "attempt": 1}, {"execution": "", "generation": 1, "attempt": 1},
        {"execution": "e", "generation": "1", "attempt": 1}, {"execution": "e"}, None)]
    out["candidate"] = [call(ws.validate_candidate, v) for v in (
        {"revision": REV, "tree": REV, "base": REV, "extra": 1}, {"revision": "x", "tree": REV, "base": REV}, 3)]
    out["project_key"] = [call(ws.project_key, v) for v in ("/workspace", "C:\\work\\x", "", "x" * 401)]
    out["transcript_path"] = [call(ws.transcript_path, "-workspace", v) for v in (SID, "nope", None)]
    out["allowed_path"] = [ws.allowed_path(v, "-workspace", SID) for v in (
        f"projects/-workspace/{SID}.jsonl", f"projects/-workspace/{SID}/tool-results/a.txt",
        f"projects/-workspace/{SID}/CON.txt", f"projects/-workspace/{SID}/a/b/c/d/e/f/g.txt",
        f"projects/-workspace/{SID}/x.", "/abs", "projects\\x", "c:x", f"projects/other/{SID}.jsonl", 7)]
    transcript = {"path": f"projects/-workspace/{SID}.jsonl", "bytes": 10, "sha256": SHA}
    manifest = {"schema": ws.ARCHIVE_SCHEMA, "session_id": SID, "project": "-workspace", "files": [transcript]}
    out["manifest"] = [call(ws.validate_manifest, v, **k) for v, k in (
        (manifest, {}), (manifest, {"session_id": SID}), (manifest, {"session_id": "other"}),
        ({**manifest, "schema": "x"}, {}), ({**manifest, "files": []}, {}),
        ({**manifest, "files": [transcript, {**transcript, "path": transcript["path"].upper()}]}, {}),
        ({**manifest, "files": [{**transcript, "path": f"projects/-workspace/{SID}/a.txt"}]}, {}),
        ({**manifest, "files": [{**transcript, "bytes": -1}]}, {}),
        ({**manifest, "files": [{**transcript, "sha256": "bad"}]}, {}), ({**manifest, "project": ".."}, {}))]
    base = {"session_id": SID, "raw": {"input_tokens": 5, "output_tokens": 2}}
    out["usage_delta"] = [call(ws.usage_delta, mode=m, session_id=SID, baseline=b, raw=r) for m, b, r in (
        (ws.MODE_FRESH, None, {"input_tokens": 3, "output_tokens": -1, "x": 1}),
        (ws.MODE_RESUME, base, {"input_tokens": 9, "output_tokens": 4}),
        (ws.MODE_RESUME, None, {"input_tokens": 9}),
        (ws.MODE_RESUME, {**base, "session_id": "other"}, {"input_tokens": 9}),
        (ws.MODE_RESUME, base, {"input_tokens": 1}), (ws.MODE_FRESH, None, "x"))]
    candidate = {"revision": REV, "tree": REV, "base": REV}
    review = {"id": "d1", "phase": "review_lead", "status": "succeeded", "input": {"candidate": candidate},
              "result": {"accepted": True, "execution_ref": "sha256:" + SHA}}
    out["review_outcome"] = [call(ws.review_outcome, v, candidate) for v in (
        review, {**review, "phase": "review_conductor"}, {**review, "result": {**review["result"], "accepted": False}},
        {**review, "phase": "diagnose"}, {**review, "status": "failed"},
        {**review, "input": {"candidate": {**candidate, "tree": "c" * 40}}},
        {**review, "result": {"accepted": "yes", "execution_ref": "sha256:" + SHA}},
        {**review, "result": {"accepted": True, "execution_ref": "x"}}, None)]
    archive = {"ref": "sha256:" + SHA, "manifest_sha256": SHA, "transcript_sha256": SHA}
    accepted_row = {"task_id": "task-1", "session_id": SID, "state": ws.ACCEPTED,
                    "candidates": [{**candidate, "archive": archive["ref"], "outcome": "accepted"}],
                    "reviews": [{"outcome": "accepted", "candidate": candidate, "decision_id": "d2",
                                 "execution_ref": "sha256:" + SHA, "phase": "review_conductor"}],
                    "checkpoints": [{"archive": archive}]}
    receipt = call(ws.promotion_receipt, accepted_row, ["sha256:" + "c" * 64, "sha256:" + "c" * 64])
    out["promotion_receipt"] = receipt
    document = receipt.get("value")
    out["validate_promotion"] = [call(ws.validate_promotion, v, accepted_row) for v in (
        document, {**document, "evidence": []}, {**document, "schema": "x"}, {**document, "extra": 1},
        {**document, "candidate": {**document["candidate"], "tree": "d" * 40}})]
    out["accepted_binding"] = [call(ws.accepted_binding, v) for v in (
        {**accepted_row, "state": ws.CHECKPOINTED}, {**accepted_row, "reviews": []},
        {**accepted_row, "checkpoints": [{"archive": {**archive, "ref": "sha256:" + "e" * 64}}]})]
    views = {}
    for state in (*ws.STATES, "mystery"):
        for owner in (None, {"execution": "e", "generation": 1, "attempt": 1}):
            for cleanup in (None, {"state": "failed"}):
                row = {"task_id": "task-1", "state": state, "session_id": SID, "version": 3, "owner": owner,
                       "identity": IDENTITY, "checkpoints": [{"archive": archive}], "cleanup": cleanup,
                       "reviews": [{"decision_id": "d", "phase": "review_lead", "outcome": "rejected", "x": 1}]}
                key = f"{state}|{'owned' if owner else 'free'}|{'failed' if cleanup else 'clean'}"
                views[key] = ws.status_view(row)
    out["status_view"] = views
    return out


def run(streams, ws) -> dict:
    return {"provider_stream": stream_steps(streams), "worker_sessions": session_steps(ws)}

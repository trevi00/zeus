"""Shared S4 scenario steps (`research.hook_effects`): M7 `Harness.record_incident` and `Harness.review`, the
research effects of the review decision unit, run inside a caller-owned transaction (lead decision Option A).

Layer: harness (never shipped)

`api.hooks(store)` is the side's object with `record_incident`/`review`; `api.envelope` is the side's envelope with
its scripted clock and ids; `api.reset()` resets both. Values/refusals, the final store records (by body digest)
and the outbox messages are compared.
"""

from __future__ import annotations

import copy
import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def run(api) -> dict:
    api.reset()
    store = api.MemoryStore()
    h = api.hooks(store)
    out = {}

    def incident(name, message, **kwargs):
        with store.transaction() as tx:
            out[name] = call(h.record_incident, message, transaction=tx, **kwargs)

    def review(name, *args):
        with store.transaction() as tx:
            out[name] = call(h.review, *args, transaction=tx)

    def report(occurrence, root_cause, scope, refs, sender="worker:implementation", recipient="lead:improvement",
               corr="corr-1"):
        return api.envelope("incident.report", sender, recipient, "record_incident",
                            {"occurrence_id": occurrence, "root_cause": root_cause, "scope": scope,
                             "evidence_refs": refs}, corr)

    m1 = report("o1", "rc-1", "s-1", ["e1"])
    incident("first", m1, independent_occurrence="task-1")
    incident("replay", m1, independent_occurrence="task-1")
    changed = copy.deepcopy(m1)
    changed["what"]["details"]["evidence_refs"] = ["e9"]
    incident("reused_id_other_content", changed, independent_occurrence="task-1")
    incident("reused_id_other_occurrence", m1, independent_occurrence="task-9")
    incident("second_creates_hook", report("o2", "rc-1", "s-1", ["e2"]), independent_occurrence="task-2")
    incident("third_not_recreated", report("o3", "rc-1", "s-1", ["e3"]), independent_occurrence="task-3")
    with store.transaction() as tx:
        hooks = [r for r in tx.records() if r["bucket"] == "hooks"]
        hook_id = hooks[0]["id"]
        tx.put("hooks", hook_id, {**hooks[0]["body"], "status": "active"})
    incident("fourth_rerequires_active", report("o4", "rc-1", "s-1", ["e4"]), independent_occurrence="task-4")
    incident("conductor_first", report("c1", "rc-2", "s-2", ["e2"], sender="lead:improvement",
                                       recipient="conductor", corr="corr-2"), independent_occurrence="task-c1")
    incident("conductor_assign", report("c2", "rc-2", "s-2", ["e2"], sender="lead:improvement",
                                        recipient="conductor", corr="corr-2"), independent_occurrence="task-c2")
    incident("occurrence_reused_other_scope", report("o1", "rc-1", "s-other", ["e1"]),
             independent_occurrence="task-5")
    incident("blank_independent", report("o5", "rc-1", "s-1", ["e5"]), independent_occurrence="  ")
    extra = report("o6", "rc-1", "s-1", ["e6"])
    extra["what"]["details"]["extra"] = 1
    incident("extra_key", extra, independent_occurrence="task-6")

    spec = {"kind": "x"}
    sh = api.digest(spec)
    for hid in ("hook-x", "hook-y"):
        with store.transaction() as tx:
            tx.put("hooks", hid, {"id": hid, "status": "candidate", "revision": "rev-1", "spec": spec,
                                  "author": "worker:implementation", "reviews": [], "version": 2, "canary": None})
    review("review_conductor_first", "hook-x", "conductor", "rev-1", sh, True, "ev-0")
    review("review_wrong_lead", "hook-x", "lead:research", "rev-1", sh, True, "ev-0")
    review("review_lead", "hook-x", "lead:improvement", "rev-1", sh, True, "ev-1")
    review("review_lead_again", "hook-x", "lead:improvement", "rev-1", sh, True, "ev-1")
    review("review_stale_revision", "hook-x", "conductor", "rev-0", sh, True, "ev-2")
    review("review_conductor", "hook-x", "conductor", "rev-1", sh, True, "ev-2")
    review("review_rejected", "hook-y", "lead:improvement", "rev-1", sh, False, "ev-3")
    review("review_non_bool", "hook-y", "lead:improvement", "rev-1", sh, "yes", "ev-3")
    review("review_worker", "hook-y", "worker:implementation", "rev-1", sh, True, "ev-3")

    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    out["outbox"] = sorted([r["body"]["message"]["type"], r["body"]["message"]["who"]["sender"],
                            r["body"]["message"]["who"]["recipient"], r["body"]["message"]["what"]["action"]]
                           for r in rows if r["bucket"] == "outbox")
    return out

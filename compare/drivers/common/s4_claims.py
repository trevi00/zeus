"""Shared S4 scenario steps (`coordination.decision_claims`): the decisions_pending claim that M7 `decide_one`
runs before any provider (lead decision Option A: coordination claims, ReviewDecisions receives the lease).

Layer: harness (never shipped)

`api.claim(store, agent, expected=None)` returns the claimed row or None (reference: M7 `Executor.decide_one`
stopped at the provider boundary; target: the coordination claim operation with the same owner id);
`api.fresh()` resets the scripted clock and ids and returns a new store; `api.envelope`; `api.advance`.
Reported: the returned lease fields, refusals and the store records at the provider boundary (by digest).
"""

from __future__ import annotations

import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def summary(row):
    if row is None:
        return None
    return {k: row.get(k) for k in ("id", "status", "attempt", "generation", "owner", "lease_owner", "lease_until",
                                    "execution_deadline", "retry_budget", "execution_clock", "error")}


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def decision(api, did, actor="lead:improvement", **extra):
    """The row without its message: `case` adds the envelope after the scripted clock and ids are reset."""
    return {"id": did, "actor": actor, "phase": "diagnose", "input": {"n": did}, "status": "pending", "attempt": 0,
            **extra}


def case(api, rows, fences=(), expected=None, twice=False):
    store = api.fresh()
    with store.transaction() as tx:
        for row in rows:
            row = {**row, "message": api.envelope("task.assign", "worker:implementation", row["actor"], "diagnose", {},
                                                  "corr-" + row["id"])}
            tx.put("decisions_pending", row["id"], row)
        for key, generation in fences:
            tx.put("execution_fences", "decisions_pending:" + key, {"id": "decisions_pending:" + key,
                   "bucket": "decisions_pending", "row_id": key, "generation": generation, "owner": "old",
                   "at": "2026-01-01T00:00:00+00:00"})
    api.advance(1)
    try:
        first = api.claim(store, "lead:improvement", expected)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200], "records": records(store)}
    out = {"claimed": summary(first), "records": records(store)}
    if twice:
        api.advance(1)
        out["again"] = summary(api.claim(store, "lead:improvement", None))
    return out


def run(api) -> dict:
    ticket = {"id": "tk1", "revision": 2, "content_hash": "0" * 64}
    return {
        "fresh": case(api, [decision(api, "d1")], twice=True),
        "expired_running_reclaimed": case(api, [decision(api, "d1", status="running", attempt=1, generation=1,
                                                         lease_owner="old", owner="old",
                                                         lease_until="2025-12-31T23:00:00+00:00",
                                                         retry_budget={"max_attempts": 3, "bound_at": "x",
                                                                       "version": 1, "origin": "first_claim"})],
                                          fences=[("d1", 1)]),
        "recovery_context_changed": case(api, [decision(api, "d1", recovery_sequence=1)]),
        "ticket_superseded": case(api, [decision(api, "d1", input={"zeus_ticket": ticket})]),
        "invalid_deadline": case(api, [decision(api, "d1", execution_deadline="soon")]),
        "deadline_passed": case(api, [decision(api, "d1", execution_deadline="2025-12-31T00:00:00+00:00")]),
        "budget_exhausted": case(api, [decision(api, "d1", attempt=3, status="retry",
                                                retry_budget={"max_attempts": 3, "bound_at": "x", "version": 1,
                                                              "origin": "first_claim"})]),
        "fence_regressed": case(api, [decision(api, "d1")], fences=[("d1", 5)]),
        "other_actor_only": case(api, [decision(api, "d1", actor="conductor")]),
        "guard_mismatch": case(api, [decision(api, "d1")],
                               expected={"id": "d1", "correlation_id": "other", "statuses": ["pending"]}),
    }

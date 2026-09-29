"""Shared S4 scenario steps (`review.releases_units`): the moved-ahead owner operations Releases.propose/review
(review) and ticket_binding (intake), lead decision Option A.

Layer: harness (never shipped)

`api` supplies MemoryStore, `releases(store)` (the side's Releases bound to the packaged organization and
the side's ticket binding), `ticket_binding(tx, value)`, `TicketSuperseded`, `TicketClosed`. Every step
reports its value (non-identity fields) or its refusal; the final store records are compared by digest.
"""

from __future__ import annotations

import hashlib
import json

REV = "a" * 40


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    if isinstance(value, dict):
        return {"value": {k: value[k] for k in sorted(value) if k not in ("candidate", "policy")}}
    return {"value": value}


def run(api) -> dict:
    out = {}
    store = api.MemoryStore()
    content = {"title": "t"}
    ticket = {"id": "tk1", "revision": 2, "content_hash": canonical_digest(content)}
    with store.transaction() as tx:
        tx.put("tickets", "tk1", {"id": "tk1", "status": "open", "revision": 2, "content_hash": ticket["content_hash"],
                                  "lifecycle_sequence": 0})
        tx.put("ticket_revisions", "tk1:2", {"content": content})
        tx.put("tickets", "tk2", {"id": "tk2", "status": "closed", "revision": 1, "content_hash": "x",
                                  "lifecycle_sequence": 0})
        binding = {
            "none": call(api.ticket_binding, tx, {"a": [{"b": 1}]}),
            "valid": call(api.ticket_binding, tx, {"x": {"zeus_ticket": ticket}}),
            "nested_same": call(api.ticket_binding, tx, [{"zeus_ticket": ticket}, {"y": {"zeus_ticket": dict(ticket)}}]),
            "conflicting": call(api.ticket_binding, tx, [{"zeus_ticket": ticket},
                                                         {"zeus_ticket": {**ticket, "revision": 3}}]),
            "invalid_shape": call(api.ticket_binding, tx, {"zeus_ticket": {"id": "tk1"}}),
            "missing": call(api.ticket_binding, tx, {"zeus_ticket": {**ticket, "id": "tk9"}}),
            "closed": call(api.ticket_binding, tx, {"zeus_ticket": {**ticket, "id": "tk2", "revision": 1}}),
            "changed": call(api.ticket_binding, tx, {"zeus_ticket": {**ticket, "revision": 1}}),
            "lifecycle": call(api.ticket_binding, tx, {"zeus_ticket": {**ticket, "lifecycle_sequence": 1}}),
        }
    out["ticket_binding"] = binding
    out["closed_is_superseded"] = issubclass(api.TicketClosed, api.TicketSuperseded)
    releases = api.releases(store)
    candidate = {"revision": REV, "base": "b" * 40, "tree": "c" * 40, "author": "worker:implementation"}
    policy = {"checks": ["tests"]}
    first = releases.propose(candidate, policy)
    rid = first["id"]
    steps = {
        "propose": call(lambda: first),
        "propose_again": call(releases.propose, candidate, policy),
        "propose_incomplete": call(releases.propose, {**candidate, "tree": ""}, policy),
        "propose_no_checks": call(releases.propose, candidate, {"checks": []}),
        "propose_non_worker_author": call(releases.propose, {**candidate, "author": "conductor"}, policy),
        "propose_ticket_superseded": call(releases.propose, {**candidate, "zeus_ticket": {**ticket, "revision": 1}},
                                          policy),
        "review_no_evidence": call(releases.review, rid, "lead:improvement", REV, True, ""),
        "review_stale": call(releases.review, rid, "lead:improvement", "d" * 40, True, "e"),
        "review_unknown": call(releases.review, "nope", "lead:improvement", REV, True, "e"),
        "review_unauthorized": call(releases.review, rid, "lead:research", REV, True, "e"),
        "conductor_before_lead": call(releases.review, rid, "conductor", REV, True, "e"),
        "lead_accept": call(releases.review, rid, "lead:improvement", REV, True, "e1"),
        "lead_duplicate_same": call(releases.review, rid, "lead:improvement", REV, True, "e1"),
        "lead_duplicate_conflict": call(releases.review, rid, "lead:improvement", REV, False, "e1"),
        "conductor_accept": call(releases.review, rid, "conductor", REV, True, "e2"),
    }
    other = releases.propose({**candidate, "tree": "f" * 40}, policy)
    steps["lead_reject"] = call(releases.review, other["id"], "lead:improvement", REV, False, "e3")
    steps["review_after_reject"] = call(releases.review, other["id"], "conductor", REV, True, "e4")
    with store.transaction() as tx:
        joined = releases.propose({**candidate, "tree": "9" * 40}, policy, transaction=tx)
        steps["propose_in_unit"] = {"status": joined["status"], "reviews": joined["reviews"]}
    out["releases"] = steps
    with store.transaction() as tx:
        rows = tx.records()
    out["records"] = sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)
    return out

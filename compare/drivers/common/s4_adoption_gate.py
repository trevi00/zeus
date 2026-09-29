"""Shared S4 scenario steps (`research.adoption_gate`): the research adoption gate that Workflow.submit and RunTask
admit plan/implement through (M7 `application/audit_gate.py`: binding, require_adoption, inspect_approval), moved
ahead unchanged under Option A.

Layer: harness (never shipped)

`api` holds `MemoryStore`, `digest`, `binding`, `require_adoption` and `inspect_approval`. Each case uses a fresh
store whose rows the harness puts through `tx.put` in its own transaction; every gate call runs inside
`with store.transaction() as tx:`. Values/refusals and the artifacts call log are compared. The gate walks a set of
references, so the order between unrelated references is hash-dependent: the log is reported as the sorted calls
plus the ordering facts that are guaranteed (each inspect precedes its document; a discovered reference is
inspected after the document that declared it).
"""

from __future__ import annotations

REF_A = "sha256:" + "a" * 64
REF_B = "sha256:" + "b" * 64
REF_C = "sha256:" + "c" * 64
REPO = "https://example.invalid/r"
COMMIT = "c" * 40
PROPOSAL = {"source": {"repository": REPO, "commit": COMMIT}}
DETAILS = {"audit_approval": "ap1", "source_url": REPO, "source_revision": COMMIT}


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


class Artifacts:
    """Records every inspect/document call in order; only the a-reference has a structured document."""

    def __init__(self):
        self.log = []

    def inspect(self, ref):
        self.log.append(["inspect", ref])

    def document(self, ref):
        self.log.append(["document", ref])
        if ref == REF_A:
            return {"next_ref": REF_C}
        raise ValueError("plain text")


def chain(api, *, control_status="active", approval_status=None, exit_status=0, only_lead=False, refs=False,
          bad_ref=False, later_rejection=False, stale=False):
    """A store holding a valid approval chain, with at most one deviation."""
    store = api.MemoryStore()
    with store.transaction() as tx:
        receipt = {"audit_id": "a1", "receipt": {"exit_status": exit_status, "inspection_blocked": False,
                                                 "note": "r1"}}
        rk = api.digest(receipt)
        tx.put("research_receipts", rk, receipt)
        tx.put("research_audits", "a1", {"audit_id": "a1", "scope": "s"})
        record = {"receipt_ids": [rk]}
        if refs:
            record["snapshot_ref"] = REF_B
        tx.put("research_paths", "p1", {"audit_id": "a1", "path": "src/x.py", "record": record})
        tx.put("research_subsystems", "s1", {"audit_id": "a1", "name": "core", "record": {"receipt_ids": [rk]}})
        tx.put("research_partitions", "q1", {"audit_id": "a1", "name": "part"})
        tx.put("research_observed_assets", "o1", {"audit_id": "a1", "asset": "asset"})
        tx.put("research_paths", "other", {"audit_id": "a2", "path": "elsewhere", "record": {"receipt_ids": []}})
        tx.put("releases", "rel1", {"status": "active", "policy_hash": "ph1"})
        tx.put("deployment", "active", {"release_id": "rel1", "revision": "rev1"})
        tx.put("research_control", "activation", {"status": control_status, "release_id": "rel1"})
        tx.put("research_control", "graph", {"graph": "g1"})
        bound = api.binding(tx, "a1", PROPOSAL)
        keys = []
        for actor, seq in (("lead:research", 1), ("conductor", 2)):
            review = {"binding": bound, "accepted": True, "actor": actor, "execution_id": rk}
            key = api.digest(review)
            tx.put("research_reviews", key, {"review": review, "sequence": seq, "at": f"2026-01-01T00:00:0{seq}Z"})
            keys.append(key)
        if later_rejection:
            review = {"binding": bound, "accepted": False, "actor": "lead:research", "execution_id": rk}
            tx.put("research_reviews", api.digest(review),
                   {"review": review, "sequence": 3, "at": "2026-01-01T00:00:03Z"})
        approval = {"audit_id": "a1", "proposal": PROPOSAL, "reviews": keys[:1] if only_lead else keys,
                    "binding": bound}
        if approval_status is not None:
            approval["status"] = approval_status
        if refs:
            approval["report_ref"] = REF_A
        if bad_ref:
            approval["report_ref"] = "not-a-ref"
        tx.put("research_approvals", "ap1", approval)
    if stale:
        with store.transaction() as tx:
            tx.put("research_observed_assets", "o2", {"audit_id": "a1", "asset": "late"})
    return store


def gate(api, store, details):
    with store.transaction() as tx:
        return call(api.require_adoption, tx, details)


def order_facts(log):
    inspects = [ref for op, ref in log if op == "inspect"]
    documents = [ref for op, ref in log if op == "document"]
    index = {(op, ref): i for i, (op, ref) in enumerate(map(tuple, log))}
    return {
        "inspects": sorted(inspects), "documents": sorted(documents),
        "inspect_once": len(inspects) == len(set(inspects)),
        "inspect_before_document": all(index[("inspect", r)] < index[("document", r)] for r in documents),
        "c_after_a_document": (index.get(("inspect", REF_C), -1) > index.get(("document", REF_A), 1 << 30)),
    }


def inspect_case(api, store, details):
    artifacts = Artifacts()
    with store.transaction() as tx:
        result = call(api.inspect_approval, tx, details, artifacts)
    return {"result": result, "calls": len(artifacts.log), **order_facts(artifacts.log)}


def run(api) -> dict:
    out = {}
    plain = {"plan": {"objective": "x"}}
    store = api.MemoryStore()
    artifacts = Artifacts()
    with store.transaction() as tx:
        out["plain"] = {"require": call(api.require_adoption, tx, plain),
                        "inspect": call(api.inspect_approval, tx, plain, artifacts),
                        "artifacts_calls": artifacts.log}
    out["proposal_no_approval"] = gate(api, api.MemoryStore(), {"proposal": {}})
    out["two_approvals"] = gate(api, api.MemoryStore(), {
        "proposal": {}, "first": {"audit_approval": "ap1"}, "second": [{"audit_approval": "ap2"}]})

    store = chain(api)
    with store.transaction() as tx:
        valid = call(api.require_adoption, tx, DETAILS)
        approval = valid.get("value")
        out["valid"] = {"result": valid,
                        "keys": sorted(approval) if approval is not None else None,
                        "binding_equal": (approval is not None and approval["binding"]
                                          == api.binding(tx, approval["audit_id"], approval["proposal"]))}
    variants = {
        "paused": dict(control_status="paused"),
        "revoked": dict(approval_status="revoked"),
        "later_rejection": dict(later_rejection=True),
        "receipt_changed": dict(exit_status=1),
        "reviews_incomplete": dict(only_lead=True),
        "provenance_changed": dict(),
        "stale_binding": dict(stale=True),
    }
    for name, options in variants.items():
        details = dict(DETAILS, source_revision="d" * 40) if name == "provenance_changed" else DETAILS
        out[name] = gate(api, chain(api, **options), details)

    out["inspect_valid"] = inspect_case(api, chain(api, refs=True), DETAILS)
    out["inspect_no_refs"] = inspect_case(api, chain(api), DETAILS)
    out["inspect_invalid_ref"] = inspect_case(api, chain(api, bad_ref=True), DETAILS)
    return out

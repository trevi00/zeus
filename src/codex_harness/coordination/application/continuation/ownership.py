"""Explicit successor ownership reconciliation.

Layer: application
Context: coordination
Owns: no bucket of its own
Does not own: portfolio_bindings (intake, through Successors.inherit)
Entry points: OwnershipReconciliation
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import (
    BUCKET_INTENTS,
    BUCKET_POLICIES,
    FLEET_JOBS,
)
from codex_harness.coordination.domain.continuation import (
    ADMITTED,
    COMPLETED,
    RETURNED,
    SUCCESSOR_ROUTES,
    refuse,
    successor_id,
)


class OwnershipReconciliation:
    """The owner's explicit reconciliation of one admitted successor's Portfolio ownership."""

    def __init__(self, store, *, successors=None):
        self.store = store
        self.successors = successors

    # ----- explicit ownership reconciliation ----------------------------------------------
    def reconcile_ownership(self, intent_id: str) -> dict:
        """The owner's explicit reconciliation of ONE already admitted successor admitted before
        ownership was inherited. Proven only from the persisted exact parent/successor intent and both
        Fleet rows (the successor row carries the intent's own manifest on its lane; the origin row is
        the job the intent was authorized on), never from arbitrary job ids, names or text. It asserts
        PRESENT ownership only: no dispatch snapshot, capture or failure verdict is touched, and the
        intent itself is not moved. One transaction; identical replays are cached."""
        refuse(type(intent_id) is str and bool(intent_id), "ownership_intent_invalid", "operator", "intent_id")
        with self.store.transaction() as tx:
            intent = tx.get(BUCKET_INTENTS, intent_id)
            refuse(isinstance(intent, dict) and intent.get("route") in SUCCESSOR_ROUTES
                   and intent.get("state") in {ADMITTED, RETURNED, COMPLETED}
                   and type(intent.get("successor_job")) is str, "ownership_intent_invalid", "operator", "intent_id")
            refuse(tx.get(BUCKET_POLICIES, intent.get("policy_id")) is not None, "policy_unregistered", "operator",
                   "policy_id")
            successor = tx.get(FLEET_JOBS, intent["successor_job"])
            origin = tx.get(FLEET_JOBS, intent["origin_job"])
            source = (intent.get("authorization") or {}).get("source") or {}
            predecessor = (intent.get("binding") or {}).get("predecessor") or {}
            refuse(isinstance(successor, dict) and successor_id(intent["id"]) == intent["successor_job"]
                   and successor.get("id") == intent["successor_job"] and successor.get("lane") == intent.get("lane")
                   and successor.get("manifest") == intent.get("manifest")
                   and successor.get("manifest_sha256") is not None
                   and (intent.get("binding") or {}).get("operation_id") == intent["successor_job"],
                   "ownership_lineage_unproven", "operator", "successor_job")
            refuse(isinstance(origin, dict) and origin.get("lane") == intent.get("lane")
                   and source.get("job") == intent["origin_job"] == predecessor.get("job_id")
                   and source.get("manifest_sha256") == origin.get("manifest_sha256") is not None,
                   "ownership_lineage_unproven", "operator", "origin_job")
            ownership, cached = self.successors.inherit(tx, intent)
            refuse(ownership["state"] == "inherited", "ownership_origin_unbound", "portfolio", "origin_job")
        return {"reconciled": True, "cached": cached, "intent_id": intent_id, "successor_job": intent["successor_job"], "origin_job": intent["origin_job"],
                **{k: ownership[k] for k in ("project_id", "criterion_id")},
                "authority": "present ownership through continuation lineage; not historical capture membership"}

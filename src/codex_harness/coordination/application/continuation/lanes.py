"""One lane store's decisive evidence (LaneEvidence), one tick's runtime view, and the verified migration
chain of a conductor's release.

Layer: application
Context: coordination
Owns: bucket continuation_bindings (the lane store's; LaneEvidence.bind)
Does not own: the lane's other buckets (read only)
Entry points: LaneEvidence, LaneRuntime
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import LANE_BINDINGS, MARKERS
from codex_harness.coordination.domain.continuation import (
    DELIVERY_BOUND,
    ContinuationRefused,
    bind_delivery,
    refuse,
    validate_binding,
)


class LaneRuntime:
    """One tick's view of `runtime(lane_id)`: each lane's identity is read once, and a failed read is
    remembered, so an unreadable runtime is one lane-wide outage for the tick, not a slot per job."""

    def __init__(self, port):
        self.port, self.seen = port, {}

    def __call__(self, lane_id: str):
        if lane_id not in self.seen:
            try:
                self.seen[lane_id] = (self.port(lane_id), None)
            except Exception as exc:
                self.seen[lane_id] = (None, exc)
        value, error = self.seen[lane_id]
        if error is not None:
            raise error
        return value

    def failed(self, lane_id: str) -> bool:
        return self.seen.get(lane_id, (None, None))[1] is not None


# INV-RELEASE-ENVIRONMENT-REVERIFY-001: at most two migration edges (evaluator migration, then one
# environment reverification of its successor) are ever followed from the conductor's release.
MAX_MIGRATION_HOPS = 2


def _migrated_delivery(tx, deliveries: list, target, release_id: str, revision, release) -> dict | None:
    """INV-OWNER-ACTIONS-MIGRATION-001 / INV-RELEASE-ENVIRONMENT-REVERIFY-001: the delivery of the
    conductor's release after ACTIVE migrations superseded it, following ONLY a verified CHAIN of
    immutable lane edges; None keeps today's binding.

    Each hop from the current release R requires: R's delivery of this target `withdrawn`/
    `release_rejected_superseded` naming exactly the ONE lane migration record sourced at R (two records
    are a branch), that record `active`, the successor release carrying the candidate (revision, tree,
    base) identical to the ORIGINAL release, and no revisit (cycle). A missing edge or a non-active
    (staged/registered/held/stopped) record ends the walk at R, as today. A branch, a mismatched edge
    or candidate, a cycle or a hop beyond `MAX_MIGRATION_HOPS` refuses the whole chain (None). The
    walk's final release R != the original must have its one delivery bound to the last followed
    record's plan. The binding keeps the conductor's `release_id` (provenance), names the final release
    as `effective_release_id`, the last edge as `migration` and every edge in `hops`."""
    if not isinstance(release, dict):
        return None
    origin = release.get("candidate") or {}
    if origin.get("revision") != revision or any(origin.get(key) is None for key in ("revision", "tree", "base")):
        return None
    records = [row for row in tx.scan("host_delivery_migrations") if row.get("target_id") == target]
    current, rows, visited, hops, last = release_id, deliveries, {release_id}, [], None
    while True:
        superseded = [row for row in rows if row.get("target_id") == target and row.get("stage") == "withdrawn"
                      and row.get("reason_code") == "release_rejected_superseded"]
        sourced = [row for row in records if row.get("source_release_id") == current]
        if not superseded or not sourced:
            break                                   # no edge from here: the walk ends at `current`
        if len(sourced) != 1 or len(hops) >= MAX_MIGRATION_HOPS:
            return None                             # a branch, or a hop beyond the bounded depth
        record = sourced[0]
        if record.get("state") != "active":
            break                                   # a held/stopped hop is never followed (as today)
        edge = [row for row in superseded if (row.get("plan_id") or row.get("id")) == record.get("id")
                and (row.get("supersession") or {}).get("migration_id") == record.get("migration_id")
                and (row.get("supersession") or {}).get("successor_release_id") == record.get("successor_release_id")]
        successor = tx.get("releases", record.get("successor_release_id")) if len(edge) == 1 else None
        if not isinstance(successor, dict) or successor.get("id") in visited:
            return None                             # an unverifiable edge or a cycle
        moved = successor.get("candidate") or {}
        if any(origin.get(key) != moved.get(key) for key in ("revision", "tree", "base")):
            return None
        visited.add(successor["id"])
        hops.append({"migration_id": record["migration_id"], "source_release_id": current,
                     "successor_release_id": successor["id"], "old_plan_id": record["id"],
                     "plan_id": record.get("plan_id")})
        current, last, final = successor["id"], record, successor
        rows = [row for row in tx.scan("host_delivery_intents") if row.get("release_id") == current]
    if not hops:
        return None
    bound = bind_delivery(rows, target, current, revision, final)
    if bound["binding"] != DELIVERY_BOUND or (bound["plan_id"], bound["plan_sha256"]) != (
            last.get("plan_id"), last.get("plan_sha256")):
        return None
    return {**bound, "release_id": release_id, "effective_release_id": current, "migration": hops[-1],
            "hops": hops}


# ---- one lane store -----------------------------------------------------------------------------
class LaneEvidence:
    """Reads and the two narrow effects on ONE lane store. Every method is its own short
    transaction; `sessions` is the lane's `WorkerSessions` owner (None: no session effect)."""

    def __init__(self, store, sessions=None):
        self.store, self.sessions = store, sessions

    def read(self, job: dict, target: str | None = None) -> dict:
        """The decisive lane evidence of one terminal job, from store reads only. `target` is the
        policy's delivery target: only ITS HostDelivery intent for the exact release and candidate
        is delivery evidence (`bind_delivery`); a plan of another target is foreign."""
        with self.store.transaction() as tx:
            operation = tx.get("operations", job["operation_id"])
            binding = tx.get(LANE_BINDINGS, job["operation_id"])
            evidence = {"operation": operation, "binding": binding, "task": None, "lead": None,
                        "conductor": None, "delivery": None, "session": None, "markers": []}
            if not isinstance(operation, dict):
                return evidence
            # An evidence-refused operation names its candidate task only in its owner handoff.
            handoff = operation.get("owner_handoff") if isinstance(operation.get("owner_handoff"), dict) else {}
            task_id = operation.get("task_id") or handoff.get("task_id")
            decision_id = operation.get("decision_id")
            if isinstance(task_id, str):
                evidence["task"] = tx.get("tasks", task_id)
            if isinstance(decision_id, str):
                evidence["lead"] = tx.get("decisions_pending", decision_id)
            owned = {task_id, decision_id} - {None}
            evidence["markers"] = sorted(
                record.get("record_id") or record.get("task_id") for record in tx.scan("observation_terminations")
                if isinstance(record, dict) and record.get("status") in MARKERS and record.get("task_id") in owned)
            if operation.get("status") == "accepted" and isinstance(decision_id, str):
                conductor = [row for row in tx.scan("decisions_pending")
                             if row.get("phase") == "review_conductor"
                             and ((row.get("message") or {}).get("what") or {}).get("details", {}).get(
                                 "decision_id") == decision_id]
                evidence["conductor"] = conductor[0] if conductor else None
                result = (evidence["conductor"] or {}).get("result") or {}
                release_id = (result.get("deployment") or {}).get("release_id") or result.get("release_id")
                if isinstance(release_id, str):
                    deliveries = [row for row in tx.scan("host_delivery_intents") if row.get("release_id") == release_id]
                    task = evidence["task"] if isinstance(evidence["task"], dict) else {}
                    candidate = (task.get("result") or {}).get("candidate") or {}
                    release = tx.get("releases", release_id)
                    evidence["delivery"] = _migrated_delivery(tx, deliveries, target, release_id,
                                                              candidate.get("revision"), release) \
                        or bind_delivery(deliveries, target, release_id, candidate.get("revision"), release)
            session = (binding or {}).get("session") if isinstance(binding, dict) else None
            if isinstance(session, dict):
                evidence["session"] = tx.get("worker_sessions", session["task_id"])
        return evidence

    def bind(self, document: dict) -> dict:
        """Write the trusted binding once; the identical document replays, any other refuses."""
        document = validate_binding(document)
        with self.store.transaction() as tx:
            old = tx.get(LANE_BINDINGS, document["operation_id"])
            if old is not None:
                refuse(old == document, "binding_conflict", field="operation_id")
                return {"bound": True, "cached": True}
            if tx.get("operations", document["operation_id"]) is not None:
                # The operation already claimed without this binding: it cannot be attached late.
                raise ContinuationRefused("operation_already_claimed", "operator", "operation_id")
            tx.put(LANE_BINDINGS, document["operation_id"], document)
        return {"bound": True, "cached": False}

    def bound(self, operation_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(LANE_BINDINGS, operation_id)

    def delivery_intent(self, plan_id: str) -> dict | None:
        """The lane's HostDelivery intent of one plan (its stage and the owner's withdrawal); read only."""
        with self.store.transaction() as tx:
            return tx.get("host_delivery_intents", plan_id)

    def release(self, release_id: str) -> dict | None:
        """The lane's immutable Releases record of one release; read only."""
        with self.store.transaction() as tx:
            return tx.get("releases", release_id)

    def record_review(self, task_id: str, decision_id: str) -> dict | None:
        """The session owner reads the committed decision row itself; a duplicate is a no-op."""
        if self.sessions is None:
            return None
        return self.sessions.record_review(task_id, decision_id)

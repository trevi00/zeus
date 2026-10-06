"""The owner's evidence-repair capacity grant.

Layer: application
Context: coordination
Owns: bucket continuation_capacity_grants
Does not own: the intent rows (IntentStore)
Entry points: CapacityGrants
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.lanes import LaneRuntime
from codex_harness.coordination.application.continuation.state import (
    BUCKET_CAPACITY_GRANTS,
    BUCKET_INTENTS,
    BUCKET_POLICIES,
    BUCKET_RESEARCH_RECEIPTS,
    FLEET_JOBS,
    FLEET_UNITS,
    policy_frame,
)
from codex_harness.coordination.domain.continuation import (
    CAPACITY_AUTHORIZED,
    CAPACITY_EXTRA,
    CAPACITY_GRANT_SCHEMA,
    EVIDENCE_REPAIR,
    INTENDED,
    MAX_HISTORY,
    REFUSED,
    RESEARCH,
    ROUTE_OWNERS,
    ContinuationRefused,
    authorization,
    capacity_count,
    capacity_view,
    check_authorization,
    check_capacity_family,
    check_capacity_refusal,
    check_capacity_source,
    check_scope,
    classify,
    owners,
    refuse,
    successor_id,
    validate_capacity_grant,
)
from codex_harness.coordination.domain.fleet import UNIT_CONDUCTOR, held_units
from codex_harness.kernel.ids import digest, utcnow


class CapacityGrants:
    """The owner's evidence-repair capacity grant: one unit records the grant and reserves its
    successor intent; every later effect rechecks it."""

    def __init__(self, store, *, clock=utcnow, lanes=None, intents=None, research=None, successors=None):
        self.store = store
        self.clock = clock
        self.lanes = lanes
        self.intents = intents
        self.research = research
        self.successors = successors

    # ----- owner evidence-repair capacity grant -------------------------------------------
    def grant_capacity(self, document, *, pin_sha256: str | None = None, runtime=None) -> dict:
        """Record the owner's one-use capacity grant for ONE exact `evidence_repair` intent refused for
        `correction_budget_exhausted` (SPEC "Exact evidence-repair capacity authorization").

        Verified first against authoritative reads (`_grant_bindings`): the registered policy and the
        re-read pin, the intent refused at creation, the current runtime/frame authorization, the origin
        job's unchanged lane evidence, inspection and retained candidate, the family's latest research
        completed by exactly the pinned receipt (every consumption check rerun) and the rationale bytes.
        Then ONE control-store transaction stores the grant and moves THAT intent `refused -> intended`
        with the successor it always derived (compare-and-swap on its version), keeping the refusal as a
        snapshot and in the history. Nothing external happens here: the next tick binds and admits
        through the existing path, rechecking the grant before each new effect. The identical grant
        replays (`cached`); any other grant for the same intent is `capacity_grant_conflict`, and a
        reserved successor stays charged whatever its outcome."""
        grant = validate_capacity_grant(document)
        with self.store.transaction() as tx:
            stored = tx.get(BUCKET_CAPACITY_GRANTS, grant["intent_id"])
            row = tx.get(BUCKET_POLICIES, grant["policy_id"])
            intent = tx.get(BUCKET_INTENTS, grant["intent_id"])
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
            framed = policy_frame(tx, row)
        if stored is not None:
            refuse(stored.get("grant") == grant, "capacity_grant_conflict", "operator", "intent_id")
            return self._grant_result(stored, intent, cached=True)
        refuse(pin_sha256 is not None and runtime is not None, "capacity_policy_unverified", "operator", "pin")
        refuse(isinstance(row, dict) and row["policy_sha256"] == grant["policy_sha256"] and row["policy"]["enabled"]
               and row["pin"].get("sha256") == pin_sha256, "capacity_policy_foreign", "operator", "policy")
        check_capacity_refusal(grant, intent)
        ctx = {"policy": framed, "sha": row["policy_sha256"], "pin": row["pin"].get("sha256"),
               "runtime": LaneRuntime(runtime), "jobs": jobs}
        job = jobs.get(intent["origin_job"])
        refuse(isinstance(job, dict), "capacity_source_changed", "operator", "source.job")
        current = ctx["runtime"](job["lane"])
        check_scope(ctx["policy"], job, current)
        check_authorization(intent["authorization"], authorization(ctx["sha"], ctx["pin"], job, current))
        bound = self._grant_bindings(ctx, grant, intent)
        job = bound["job"]   # the source row the bindings verified, compared again at commit
        plan = self.successors.successor_plan(ctx["sha"], grant["family"], job, bound["evidence"], EVIDENCE_REPAIR,
                                    classify(job, bound["evidence"]), intent["id"], self.lanes(job["lane"]),
                                    self.successors.research_handoff(grant["policy_id"], grant["family"], intent["id"]))
        refuse(plan is not None, "capacity_successor_refused", "operator", "manifest")
        grant_sha, now = digest(grant), self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_CAPACITY_GRANTS, grant["intent_id"])
            if old is not None:
                refuse(old.get("grant") == grant, "capacity_grant_conflict", "operator", "intent_id")
                return self._grant_result(old, tx.get(BUCKET_INTENTS, grant["intent_id"]), cached=True)
            # Nothing the verification read moved: same intent version, policy row, source row and receipt.
            current = tx.get(BUCKET_INTENTS, intent["id"])
            refuse(current == intent, "capacity_intent_changed", "operator", "intent_id")
            refuse(tx.get(BUCKET_POLICIES, grant["policy_id"]) == row, "capacity_policy_foreign", "operator", "policy")
            refuse(tx.get(FLEET_JOBS, job["id"]) == job, "capacity_source_changed", "operator", "source.job")
            refuse(tx.get(BUCKET_RESEARCH_RECEIPTS, bound["research"]["id"]) == bound["receipt"],
                   "capacity_research_mismatch", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
            refuse(tx.get(FLEET_JOBS, plan["successor_job"]) is None, "capacity_successor_exists", "fleet",
                   "successor_job")
            every = tx.scan(BUCKET_INTENTS)
            check_capacity_family(grant, current, every, {j["id"]: j for j in tx.scan(FLEET_JOBS)})
            # A distinct owner decision per grant: an earlier grant's rationale never authorizes another.
            refuse(not any((other.get("grant") or {}).get("rationale_ref") == grant["rationale_ref"]
                           for other in tx.scan(BUCKET_CAPACITY_GRANTS)), "capacity_rationale_reused", "operator",
                   "rationale_ref")
            refusal = {key: current.get(key) for key in ("state", "reason_code", "next_owner", "evidence_sha256",
                                                          "version", "created_at", "updated_at")}
            refusal["history"] = list(current.get("history") or [])
            stored = {"id": intent["id"], "schema": CAPACITY_GRANT_SCHEMA, "grant": grant, "grant_sha256": grant_sha,
                      "successor_job": plan["successor_job"], "research_intent": bound["research"]["id"],
                      "capacity": {"max_corrections": ctx["policy"]["max_corrections"],
                                   "counted": capacity_count(every, grant["policy_id"], grant["family"]),
                                   "extra": CAPACITY_EXTRA},
                      "refusal": refusal, "recorded_at": now, "recorded_by": "owner"}
            # The one explicit authorization transition of this intent (never a TRANSITIONS edge).
            current.update(state=INTENDED, reason_code=CAPACITY_AUTHORIZED, next_owner=ROUTE_OWNERS[EVIDENCE_REPAIR],
                           capacity_grant=grant_sha, refusal=refusal, version=current["version"] + 1, updated_at=now,
                           **plan)
            current["history"] = current["history"][-(MAX_HISTORY - 1):] + [
                {"state": INTENDED, "previous": REFUSED, "reason_code": CAPACITY_AUTHORIZED, "error_type": None,
                 "grant": grant_sha, "at": now}]
            tx.put(BUCKET_CAPACITY_GRANTS, stored["id"], stored)
            tx.put(BUCKET_INTENTS, current["id"], current)
        self.intents.emit(REFUSED, current)
        return self._grant_result(stored, current, cached=False)

    @staticmethod
    def _grant_result(row: dict, intent, cached: bool) -> dict:
        return {"granted": True, "cached": cached, **capacity_view(row, intent)}

    def _grant_bindings(self, ctx, grant: dict, intent: dict) -> dict:
        """What a grant is bound to, re-read now outside any transaction: this policy's scope, no active
        or unknown family work (Fleet jobs and units included), the origin's lane evidence, the latest
        family research and its stored receipt rechecked as at consumption, and the rationale bytes.
        Fleet rows are read here too, never taken from a tick-entry snapshot: a source row that moved
        between two effects of one tick (lane binding, then admission) refuses the second.
        Returns {evidence, research, receipt, job}; the first gap refuses by name."""
        with self.store.transaction() as tx:
            every = tx.scan(BUCKET_INTENTS)
            units = [row for row in tx.scan(FLEET_UNITS) if row.get("kind") == UNIT_CONDUCTOR]
            jobs = {row["id"]: row for row in tx.scan(FLEET_JOBS)}
        refuse(intent["origin_job"] not in owners(every, grant["policy_id"]), "capacity_scope_foreign", "operator",
               "source.job")
        family = {row["id"] for row in every if row.get("policy_id") == grant["policy_id"]
                  and row.get("family") == grant["family"]}
        refuse(not held_units(unit for unit in units if unit.get("subject") in family), "capacity_family_active",
               "operator", "family")
        research = check_capacity_family(grant, intent, every, jobs)
        job = jobs.get(intent["origin_job"])
        evidence = self.lanes(intent["lane"]).read(job, ctx["policy"]["delivery_target"])
        check_capacity_source(grant, intent, job, evidence)
        with self.store.transaction() as tx:
            receipt = tx.get(BUCKET_RESEARCH_RECEIPTS, research["id"])
        refuse(isinstance(receipt, dict), "capacity_research_mismatch", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
        self.research.recheck_receipt(grant["policy_id"], grant["policy_sha256"], research, receipt, consumed=True)
        try:
            self.research.verify_evidence([grant["rationale_ref"]])
        except ContinuationRefused as exc:
            raise ContinuationRefused(exc.reason_code.replace("research_evidence", "capacity_rationale", 1), "operator",
                                      "rationale_ref") from None
        return {"evidence": evidence, "research": research, "receipt": receipt, "job": job}

    def check(self, ctx, intent: dict) -> None:
        """Before a granted intent's NEW effect: its stored grant, intact and naming this intent and
        successor under the current policy, and every binding re-read (`_grant_bindings`)."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_CAPACITY_GRANTS, intent["id"])
        refuse(isinstance(row, dict), "capacity_grant_missing", "operator", "capacity_grant")
        grant = row.get("grant")
        refuse(isinstance(grant, dict) and row.get("grant_sha256") == digest(grant) == intent["capacity_grant"]
               and grant.get("intent_id") == intent["id"] and row.get("successor_job") == intent.get("successor_job")
               == successor_id(intent["id"]), "capacity_grant_corrupt", "operator", "capacity_grant")
        refuse(grant["policy_id"] == ctx["policy"]["id"] and grant["policy_sha256"] == ctx["sha"],
               "capacity_policy_foreign", "operator", "policy")
        self._grant_bindings(ctx, grant, intent)

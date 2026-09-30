"""The owner's resume and the shared owner-command replay.

Layer: application
Context: delivery
Owns: no bucket of its own
Does not own: review's releases and release_queue rows (the ReleaseAuthority/ReleaseClaims/ReleaseSettlement ports), the ticket binding (intake, injected)
Entry points: Resumption
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from datetime import datetime

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_INTENTS,
    BUCKET_PLANS,
    LOGGER,
    predecessor_in,
)
from codex_harness.delivery.domain.host_delivery import (
    AUTHORITY,
    EVENT_STAGE,
    EVIDENCE_REF,
    MERGED,
    OUTCOME_PROGRESSED,
    RECOVERY_CONSUMPTION_REARM,
    RECOVERY_CONSUMPTION_RETRY,
    RECOVERY_GENERATION_RESTART,
    RECOVERY_VERIFICATION_MISSING,
    VERIFYING,
    DeliveryRefused,
    consumption_rearm_exhausted,
    consumption_retry_exhausted,
    first_activation_resumable,
    recoveries_of,
    release_gate,
    resumable,
    stage_next_action,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow


def resume_gate(gate: dict) -> None:
    if gate["state"] == "approved" and gate["status"] in {"reviewed", "verified"}:
        return
    code = gate.get("reason_code") or "release_" + str(gate.get("status"))
    raise DeliveryRefused("resume_" + (code if code.startswith("release_") else "release_" + code),
                          "release_id")


def replay_of(intent, evidence_ref: str, kind: str = RECOVERY_VERIFICATION_MISSING) -> bool:
    """True for this evidence's own recorded recovery of `kind`; another evidence is refused. Pure.

    Per kind (INV-HOST-DELIVERY-FIRST-ACTIVATION-001): one recovery of EACH kind per delivery, so a
    verification recovery never makes a first-activation binding a conflict, or the reverse."""
    recorded = recoveries_of(intent, kind)
    if not recorded:
        return False
    if any(row.get("evidence_ref") == evidence_ref for row in recorded):
        return True
    # One recovery of this kind per delivery: halted again in the same shape is exhausted.
    if kind == RECOVERY_GENERATION_RESTART:
        raise DeliveryRefused("resume_conflict", "evidence")
    if kind == RECOVERY_CONSUMPTION_RETRY:
        if consumption_retry_exhausted(intent):
            raise DeliveryRefused("resume_exhausted", "evidence")
        raise DeliveryRefused("resume_conflict", "evidence")
    if kind == RECOVERY_CONSUMPTION_REARM:
        if consumption_rearm_exhausted(intent):
            raise DeliveryRefused("resume_exhausted", "evidence")
        raise DeliveryRefused("resume_conflict", "evidence")
    shape = resumable if kind == RECOVERY_VERIFICATION_MISSING else first_activation_resumable
    if shape({**intent, "recoveries": []}):
        raise DeliveryRefused("resume_exhausted", "evidence")
    raise DeliveryRefused("resume_conflict", "evidence")


class Resumption:
    """The owner's resume of a halted delivery, and the replay/record helpers every owner command shares."""

    def __init__(self, store, *, clock=utcnow, github=None, claims=None, ticket_binding, state=None):
        self.store = store
        self.clock = clock
        self.github = github
        self.claims = claims
        self.ticket_binding = ticket_binding
        self.state = state

    # ----- owner resume of a merged, never verified delivery (INV-HOST-DELIVERY-VERIFY-001) ------
    def resume(self, plan_id: str, plan_sha256: str, evidence_ref: str) -> dict:
        """Move exactly the legacy `release_not_verified`-at-`merged` shape back to `verifying`.

        Read-only first: the plan and its digest, the resumable shape, the release gate, GitHub's
        merge of exactly the recorded revision and the merge owner's own tree qualification. Then
        ONE store transaction - rolled back as a whole on any refusal - re-checks the intent (CAS),
        the controller lease, the queue row, the predecessor, the exact release identity and its
        ticket binding, re-arms a stopped queue row through `ReleaseQueue.retry` (one
        `manual_retries` entry) and writes `verifying` with the original halt copied into the
        recovery record. No claim, lease or generation is created, reset or finished here: the next
        ordinary tick claims the row and verifies.

        The same evidence is recognized as a replay from the durable recovery record at ANY later
        stage and answers `cached` with no write; a different evidence is refused.
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        replayed = self.resume_replay(plan, intent, evidence_ref)
        if replayed is not None:
            return replayed
        if not resumable(intent):
            raise DeliveryRefused("resume_not_applicable", "stage")
        try:
            gate = self.state.gate(plan)
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        resume_gate(gate)
        observed = self._resume_merge(plan, intent)
        now = self.clock()
        recovery = {"kind": RECOVERY_VERIFICATION_MISSING, "evidence_ref": evidence_ref,
                    "halted": {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code",
                                                                "outcome", "attempts", "error_type",
                                                                "updated_at")},
                    "observed": {**observed, "tree_qualified": True, "predecessor": "held"}, "at": now}
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                settled = (None if replay_of(current, evidence_ref)
                           else self._resume_in(tx, row, intent, queued, current, recovery, now))
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if settled is None:
            # A concurrent same-evidence resume committed first: its record answers, nothing written.
            return self.resumed(plan, current, cached=True, evidence_ref=evidence_ref)
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": VERIFYING, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery resumed plan=%s from=%s reason=%s", plan["plan_id"], intent["stage"],
                       intent.get("reason_code"))
        return self.resumed(plan, settled, cached=False)

    def _resume_in(self, tx, row: dict, intent: dict, queued, current, recovery: dict, now: str) -> dict:
        """Phase 2, inside the one transaction; any refusal raised here rolls every write back."""
        plan = row["plan"]
        if current != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
            raise DeliveryRefused("resume_intent_changed", "plan_id")
        lock = tx.get("deployment_locks", "controller") or {}
        if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self.state.now():
            raise DeliveryRefused("resume_controller_running", "release_id")
        if tx.get("release_queue", plan["release_id"]) != queued:
            raise DeliveryRefused("resume_queue_changed", "release_id")
        predecessor = predecessor_in(tx, plan)
        if predecessor != "held":
            raise DeliveryRefused("resume_predecessor_" + predecessor, "target_id")
        # The exact immutable release identity and its ticket binding, whatever the queue shows.
        record = tx.get("releases", plan["release_id"])
        resume_gate(release_gate(record, plan, self.state.parent(record)))
        try:
            self.ticket_binding(tx, record["candidate"])
        except ContractError as exc:
            raise DeliveryRefused("resume_release_ticket_changed", "release_id") from exc
        status = (queued or {}).get("status")
        if status in {"blocked", "failed"}:
            try:
                self.claims.retry(plan["release_id"], "host delivery resume " + plan["plan_id"] + " "
                                 + recovery["evidence_ref"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        elif not (queued is None or status in {"queued", "retry"}
                  or (status == "running" and not self.state.leased(queued))):
            raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        settled = {**current, "stage": VERIFYING, "previous_stage": current["stage"],
                   "outcome": OUTCOME_PROGRESSED, "reason_code": None, "error_type": None, "attempts": 0,
                   "after_verification": MERGED,
                   "recoveries": [*(current.get("recoveries") or []), recovery],
                   "stage_entered_at": now, "updated_at": now}
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    def _resume_merge(self, plan: dict, intent: dict) -> dict:
        """GitHub merged exactly the recorded revision, and it carries the reviewed tree. Read-only
        for the store; the qualification may refresh fetched refs, exactly as `_merge` does."""
        port = self.github
        qualify = getattr(port, "qualify", None)
        if port is None or qualify is None:
            raise DeliveryRefused("resume_unobservable", "github")
        try:
            candidate = self.state.candidate(plan)
            state = port.merge_state(candidate, port.observe(candidate))
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "github") from exc
        if state.get("state") != "merged" or state.get("merged_revision") != intent["merged_revision"]:
            raise DeliveryRefused("resume_merge_mismatch", "merged_revision")
        try:
            qualify(candidate, intent["merged_revision"])
        except ContractError as exc:
            raise DeliveryRefused("resume_tree_mismatch", "merged_revision") from exc
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "github") from exc
        return {"main": state.get("main"), "merged_revision": intent["merged_revision"]}

    def resume_replay(self, plan: dict, intent, evidence_ref: str, kind: str = RECOVERY_VERIFICATION_MISSING):
        """The durable recovery record decides a repeated call, at whatever stage it now is."""
        if not replay_of(intent, evidence_ref, kind):
            return None
        # The verification kind keeps its exact original call; only the new kind names itself.
        named = {} if kind == RECOVERY_VERIFICATION_MISSING else {"kind": kind}
        return self.resumed(plan, intent, cached=True, evidence_ref=evidence_ref, **named)

    def resumed(self, plan: dict, intent: dict, *, cached: bool, evidence_ref=None,
                 kind: str = RECOVERY_VERIFICATION_MISSING) -> dict:
        recorded = [row for row in recoveries_of(intent, kind)
                    if evidence_ref is None or row.get("evidence_ref") == evidence_ref][-1]
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"]) or {}
        return {"resumed": True, "cached": cached, "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": intent["stage"],
                "after_verification": intent.get("after_verification"),
                "recovery": {"kind": recorded["kind"], "evidence_ref": recorded["evidence_ref"],
                             "halted_reason_code": (recorded.get("halted") or {}).get("reason_code"),
                             "at": recorded.get("at"),
                             **({"binding": dict(recorded["binding"])} if "binding" in recorded else {})},
                "queue": {"status": queued.get("status"),
                          "manual_retries": len(queued.get("manual_retries") or [])},
                "next_action": stage_next_action(intent["stage"], intent.get("outcome")),
                "authority": AUTHORITY}

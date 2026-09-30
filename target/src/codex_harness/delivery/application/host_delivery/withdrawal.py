"""The owner's withdrawal.

Layer: application
Context: delivery
Owns: no bucket of its own (the intent through DeliveryState)
Does not own: review's releases and release_queue rows (the ReleaseAuthority/ReleaseClaims/ReleaseSettlement ports)
Entry points: Withdrawal
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    LOGGER,
)
from codex_harness.delivery.domain.host_delivery import (
    AUTHORITY,
    BLOCKED,
    EVENT_STAGE,
    EVIDENCE_REF,
    FAILED,
    REGISTERED,
    STOPPED_STAGES,
    WITHDRAW_REASONS,
    WITHDRAWABLE_STAGES,
    WITHDRAWN,
    DeliveryRefused,
    descriptor_digest,
    new_intent,
    stage_next_action,
    unresolved_attempts,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow


def withdrawable(intent, reason: str) -> None:
    """The host was never touched: no descriptor bound, at a stage before the host is reached."""
    stage = (intent or {}).get("stage") or REGISTERED
    if (intent or {}).get("held"):
        # INV-HOST-DELIVERY-MIGRATION-001: a held migration successor is never claimed or queued,
        # not even to be withdrawn; its handoff is resolved by its own owners.
        raise DeliveryRefused("withdraw_migration_held", "stage")
    if stage not in WITHDRAWABLE_STAGES or (intent or {}).get("descriptor") is not None:
        raise DeliveryRefused("withdraw_host_touched", "stage")
    if unresolved_attempts(intent):
        # INV-HOST-DELIVERY-VERIFY-001: a withdrawal never orphans verification ownership debt.
        raise DeliveryRefused("withdraw_verification_unresolved", "stage")
    recorded = stage in {BLOCKED, FAILED} and intent.get("reason_code") == "merged_tree_mismatch"
    if (reason == "merged_tree_mismatch") != recorded:
        # A recorded merge is retired only under its own reason, and that reason needs one.
        raise DeliveryRefused("withdraw_merge_observed" if recorded else "withdraw_not_stale", "reason")


class Withdrawal:
    """The owner's withdrawal of a stale, untouched delivery under the same fence a tick takes."""

    def __init__(self, store, *, clock=utcnow, github=None, claims=None, settlement=None, state=None):
        self.store = store
        self.clock = clock
        self.github = github
        self.claims = claims
        self.settlement = settlement
        self.state = state

    # ----- owner withdrawal of a stale, untouched delivery ---------------------------------------
    def withdraw(self, plan_id: str, plan_sha256: str, reason: str, evidence_ref: str) -> dict:
        """Retire ONE registered delivery whose reviewed base or expected predecessor no longer holds.

        Allowed only while the host was never touched (no descriptor bound), and only on staleness
        observed NOW, never on a claim: `reviewed_base_moved` needs the remote main to be neither the
        reviewed base nor carrying this candidate, `descriptor_predecessor_moved` needs the target's
        descriptor to differ from the plan's expected one with no other delivery unsettled on it, and
        `merged_tree_mismatch` retires a delivery whose recorded merge is still exactly what main
        shows (its merge stays in the record as `main_effect: merged`). A merge observed for any other
        reason is `withdraw_merge_observed`; an unreadable GitHub or store is `withdraw_unobservable`
        and writes nothing. An open stage is fenced exactly as a tick is - the release's queue row is
        claimed, the intent written in the transaction that re-checks the claim, the row finished as
        `withdrawn` - so no controller can publish or merge in between.

        The plan row, its owner action, its canary request and any PR are never modified. The
        identical replay is `cached` (and finishes a queue row a crash left runnable, with no other
        effect); a different reason or evidence for a withdrawn plan is `withdrawal_conflict`.
        """
        if reason not in WITHDRAW_REASONS:
            raise DeliveryRefused("withdraw_reason_unsupported", "reason")
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("withdraw_evidence_invalid", "evidence")
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
            intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("withdraw_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if (intent or {}).get("stage") == WITHDRAWN:
            recorded = intent.get("withdrawal") or {}
            if (recorded.get("reason_code"), recorded.get("evidence_ref")) != (reason, evidence_ref):
                raise DeliveryRefused("withdrawal_conflict", "reason")
            return self._withdrawn(plan, intent, cached=True, queue=self._finish_withdrawn(plan))
        # Read-only first: an unobservable, fresh or merged delivery is refused with nothing written.
        withdrawable(intent, reason)
        self._stale_now(plan, intent, reason)
        claim = None
        if ((intent or {}).get("stage") or REGISTERED) not in STOPPED_STAGES:
            claim = self._withdraw_claim(plan)
        try:
            # Again under the fence, from the intent as it is now: what is written is what was proven.
            with self.store.transaction() as tx:
                intent = tx.get(BUCKET_INTENTS, plan_id)
            withdrawable(intent, reason)
            observed = self._stale_now(plan, intent, reason)
            settled = self._commit_withdrawal(row, intent, reason, evidence_ref, observed, claim)
        except Exception as exc:
            if claim is not None:
                try:
                    # Not an attempt of the release: the lease goes back with nothing else changed.
                    self.settlement.defer(claim, {"status": "withdraw_refused",
                                             "reason": getattr(exc, "reason_code", None) or type(exc).__name__},
                                     resume_after_seconds=0, now=self.state.now())
                except ContractError:
                    pass
            raise
        queue = None
        if claim is not None:
            try:
                queue = self.settlement.finish(claim, {"status": WITHDRAWN, "reason": reason}, self.state.now())["status"]
            except ContractError:
                queue = "controller_stale"   # the withdrawal is durable; a replay finishes the row
        self.state.emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": WITHDRAWN, "previous_stage": settled["previous_stage"]})
        LOGGER.warning("host delivery withdrawn plan=%s reason=%s previous_stage=%s", plan["plan_id"], reason,
                       settled["previous_stage"])
        return self._withdrawn(plan, settled, cached=False, queue=queue)

    def _stale_now(self, plan: dict, intent, reason: str) -> dict:
        """Observe GitHub, the remote main and the target now; raise the named refusal, or return
        what was observed. Unavailable is not absent: any failure to observe refuses."""
        port = self.github
        try:
            if port is None:
                raise DeliveryRefused("github_port_unavailable")
            candidate = self.state.candidate(plan)
            observed = port.observe(candidate)
            state = port.merge_state(candidate, observed)
            predecessor = self.state.predecessor(plan)
            with self.store.transaction() as tx:
                current = (tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) or {}).get("descriptor")
        except Exception as exc:
            raise DeliveryRefused("withdraw_unobservable", "github") from exc
        facts = {"main": state.get("main"), "merge_state": state["state"],
                 "pr_state": (observed or {}).get("state"), "pr_head": (observed or {}).get("head"),
                 "pr_number": (observed or {}).get("number"),
                 "descriptor_sha256": None if current is None else descriptor_digest(current)}
        if state["state"] == "merged":
            if reason != "merged_tree_mismatch" or state["merged_revision"] != (intent or {}).get("merged_revision"):
                raise DeliveryRefused("withdraw_merge_observed", "reason")
            return {"main_effect": "merged", "observed": facts}
        if reason == "merged_tree_mismatch":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        if reason == "reviewed_base_moved" and state["state"] != "base_moved":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        if reason == "descriptor_predecessor_moved" and predecessor != "moved":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        return {"main_effect": "none", "observed": facts}

    def _withdraw_claim(self, plan: dict):
        """The same fence a tick takes for this release; refused with the tick's own reason codes."""
        try:
            self.claims.enqueue(plan["release_id"], "host delivery withdrawal " + plan["plan_id"])
            claim = self.claims.claim(now=self.state.now(), eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            raise DeliveryRefused("withdraw_queue_refused", "release_id") from exc
        if claim is None:
            raise DeliveryRefused(self.state.unclaimed(plan), "release_id")
        return claim

    def _commit_withdrawal(self, row: dict, intent, reason: str, evidence_ref: str, observed: dict,
                           claim) -> dict:
        """One transaction: the fence (when claimed) and an unchanged intent, then the terminal row.
        An absent intent is created and withdrawn together, so nothing ever runs in between."""
        plan, now = row["plan"], self.clock()
        base = intent if intent is not None else new_intent(plan, row["plan_sha256"], now)
        withdrawal = {"reason_code": reason, "evidence_ref": evidence_ref, "previous_stage": base["stage"],
                      "main_effect": observed["main_effect"], "merged_revision": base.get("merged_revision"),
                      "observed": observed["observed"], "at": now}
        settled = {**base, "stage": WITHDRAWN, "previous_stage": base["stage"], "outcome": WITHDRAWN,
                   "reason_code": reason, "error_type": None, "stage_deadline": None, "withdrawal": withdrawal,
                   "updated_at": now}
        with self.store.transaction() as tx:
            if claim is not None:
                self.claims.owned(tx, claim, self.state.now())
            if tx.get(BUCKET_INTENTS, plan["plan_id"]) != intent:
                raise DeliveryRefused("withdraw_intent_changed", "plan_id")
            tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    def _finish_withdrawn(self, plan: dict) -> str | None:
        """A withdrawal whose queue row a crash left runnable: finish that row, and nothing else."""
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"])
        if not isinstance(queued, dict) or queued.get("status") not in {"queued", "retry", "running"}:
            return None if queued is None else queued.get("status")
        claim = self.claims.claim(now=self.state.now(), eligible=lambda row: row["id"] == plan["release_id"])
        if claim is None:
            return self.state.unclaimed(plan)
        return self.settlement.finish(claim, {"status": WITHDRAWN, "reason": "withdrawal_replayed"}, self.state.now())["status"]

    def _withdrawn(self, plan: dict, intent: dict, *, cached: bool, queue) -> dict:
        return {"withdrawn": True, "cached": cached, "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": WITHDRAWN, "queue": queue,
                "withdrawal": dict(intent.get("withdrawal") or {}),
                "next_action": stage_next_action(WITHDRAWN), "authority": AUTHORITY}

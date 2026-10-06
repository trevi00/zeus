"""C1 delivery requalification.

Layer: application
Context: coordination
Owns: no bucket of its own (the per-family slot through ActionStore)
Does not own: the withdrawal (the lane's HostDelivery, S7), the requalification (Continuation)
Entry points: RequalifyFamily
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    CONTINUATION_INTENTS,
    REQUALIFY_WAITS,
    ActionChanged,
)
from codex_harness.coordination.domain.continuation import (
    DELIVERY,
    REQUALIFICATION_REQUALIFIABLE,
    ContinuationRefused,
)
from codex_harness.coordination.domain.owner_actions import (
    COMPLETED,
    DELIVERY_REQUALIFY,
    INTENDED,
    REFUSED,
    REQUALIFY_REASON,
    REQUALIFYING,
    WITHDRAWING,
    OwnerActionRefused,
    moved,
    requalification_document,
    requalification_policy,
    requalification_rationale,
    requalify_binding,
    requalify_slots,
)
from codex_harness.delivery.domain.host_delivery import BLOCKED, DeliveryRefused
from codex_harness.kernel.ids import canonical, digest, utcnow


class RequalifyFamily:
    """C1: a completed plan the lane blocked as `reviewed_base_moved`, withdrawn and requalified once."""

    def __init__(self, store, *, artifacts=None, clock=utcnow, continuation=None, deliveries=None,
                 mainline=None, requalify=None, withdrawals=None, actions=None):
        self.store = store
        self.artifacts = artifacts
        self.clock = clock
        self.continuation = continuation
        self.deliveries = deliveries
        self.mainline = mainline
        self.requalify = requalify
        self.withdrawals = withdrawals
        self.actions = actions

    # ===== C1: policy-triggered requalification of a stale reviewed base ===========================
    def discover(self, row: dict, block: dict, plan: dict) -> list:
        """Owed only for a completed plan of THIS policy whose delivery the controller blocked for exactly
        an authorized reason, while its continuation intent can still be requalified. Nothing else."""
        lane = plan["subject"]["lane"]
        delivery = self.deliveries(lane)
        with delivery.store.transaction() as tx:
            observed = tx.get("host_delivery_intents", plan["plan_id"])
        if not (isinstance(observed, dict) and observed.get("stage") == BLOCKED
                and observed.get("reason_code") in block["reasons"]
                and observed.get("plan_sha256") == plan["plan_sha256"]):
            return []
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, plan["subject"]["intent_id"])
        if not (isinstance(intent, dict) and intent.get("route") == DELIVERY
                and intent.get("state") in REQUALIFICATION_REQUALIFIABLE):
            return []
        return self.actions.create(row, DELIVERY_REQUALIFY, requalify_binding(plan, intent, observed),
                            {"intent_id": intent["id"], "lane": lane})

    def advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state = action["state"]
        if state == INTENDED:
            return self._take_slot(policy_row, continuation, action)
        if state == WITHDRAWING:
            return self._withdraw(action)
        if state == REQUALIFYING:
            return self.requalify_intent(continuation, action)
        return None

    def _take_slot(self, policy_row: dict, continuation: dict, action: dict) -> dict:
        """Before any effect: the action is still owed, its rationale is in the trusted store, and ONE cap
        slot is taken in the transaction that moves it - the count, the check and the move commit together
        (`Store.transaction` serializes writers), so two coordinators can never overshoot the family cap."""
        binding = action["binding"]
        block = requalification_policy(policy_row["policy"])
        if block is None or binding["reason"] not in block["reasons"]:
            return self.actions.effect(self.actions.move(action, REFUSED, "requalification_policy_disabled"))
        if binding["continuation_policy"] != continuation["id"]:
            return self.actions.effect(self.actions.move(action, REFUSED, "requalification_policy_foreign"))
        if self.withdrawals is None or self.requalify is None or self.mainline is None or self.artifacts is None:
            raise OwnerActionRefused("requalify_ports_unconfigured", "withdrawals")
        lane = action["subject"]["lane"]
        with self.deliveries(lane).store.transaction() as tx:
            observed = tx.get("host_delivery_intents", binding["plan_id"])
        if not (isinstance(observed, dict) and observed.get("stage") == BLOCKED
                and observed.get("reason_code") == binding["reason"]
                and observed.get("plan_sha256") == binding["plan_sha256"]):
            return self.actions.effect(self.actions.move(action, REFUSED, "requalification_delivery_moved"))
        rationale = requalification_rationale(action, observed)
        reference = self.artifacts.put(canonical(rationale), "owner-requalification-rationale")["ref"]
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_ACTIONS, action["id"])
            if not (isinstance(current, dict) and current.get("version") == action.get("version")):
                raise ActionChanged(action["id"])
            taken = requalify_slots(tx.scan(BUCKET_ACTIONS), binding, action["id"])
            if taken >= block["max_per_family"]:
                row = moved(current, REFUSED, self.clock(), "requalification_exhausted", slots_taken=taken)
            else:
                row = moved(current, WITHDRAWING, self.clock(), "requalification_slot_taken", cap_slot=taken + 1,
                            max_per_family=block["max_per_family"], rationale_ref=reference,
                            rationale_sha256=digest(rationale))
            tx.put(BUCKET_ACTIONS, row["id"], row)
        if row["state"] == REFUSED:
            return self.actions.effect(row)
        return self._withdraw(row)

    def _withdraw(self, action: dict) -> dict:
        """The lane's own GitHub-capable withdrawal, citing the stored rationale. Its identical replay is
        cached; an unobservable GitHub or store raises (the row waits and the blocked plan keeps the target
        busy: that debt stays owned); a definite refusal is named."""
        binding = action["binding"]
        try:
            result = self.withdrawals(action["subject"]["lane"]).withdraw(
                binding["plan_id"], binding["plan_sha256"], REQUALIFY_REASON, action["rationale_ref"])
        except DeliveryRefused as exc:
            if exc.reason_code == "withdraw_unobservable":
                raise
            return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
        withdrawal = result.get("withdrawal") or {}
        row = self.actions.move(action, REQUALIFYING, "delivery_withdrawn",
                         withdrawal={"cached": result.get("cached"), "previous_stage": withdrawal.get("previous_stage"),
                                     "main_effect": withdrawal.get("main_effect"),
                                     "observed_main": (withdrawal.get("observed") or {}).get("main")})
        return self.requalify_intent(None, row)

    def requalify_intent(self, continuation, action: dict) -> dict:
        """The owner document is built ONCE on the main observed now and persisted before the call; every
        later attempt replays exactly those bytes (the existing API answers an identical one `cached`)."""
        binding = action["binding"]
        row = action
        if action.get("document") is None:
            policy = self.continuation.policy(binding["continuation_policy"]) if continuation is None else continuation
            if policy is None:
                raise OwnerActionRefused("continuation_policy_unregistered", "continuation_policy")
            lane = action["subject"]["lane"]
            with self.deliveries(lane).store.transaction() as tx:
                release = tx.get("releases", binding["release_id"])
            if not isinstance(release, dict):
                raise OwnerActionRefused("release_missing", "release_id")
            try:
                main = self.mainline(lane).remote_main()
            except Exception as exc:
                raise OwnerActionRefused("requalification_main_unreadable", "main_revision") from exc
            document = requalification_document(action, policy, release.get("candidate") or {}, main)
            row = self.actions.move(action, REQUALIFYING, "requalification_document_persisted", document=document,
                             document_sha256=digest(document))
        try:
            result = self.requalify(row["document"])
        except ContinuationRefused as exc:
            if exc.reason_code in REQUALIFY_WAITS:
                raise
            return self.actions.effect(self.actions.move(row, REFUSED, exc.reason_code))
        return self.actions.effect(self.actions.move(row, COMPLETED, "requalification_recorded",
                                       requalified={"cached": result.get("cached"),
                                                    "requalification_intent": result.get("requalification_intent"),
                                                    "successor_job": result.get("successor_job")}))

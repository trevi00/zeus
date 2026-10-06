"""Owner migration requests.

Layer: application
Context: coordination
Owns: buckets owner_action_migrations, continuation_effective_bindings; the resumed continuation intent
    row is computed here (`migration_resume`) and written through `IntentStore.replace` inside the same
    completing transaction (S7 carry, golden coordination.owner_actions_migration)
Does not own: the lane stage/registration/finalization (the lane's HostDelivery, S7)
Entry points: MigrationRequestFamily
Contracts: INV-OWNER-ACTIONS-MIGRATION-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.intents import IntentStore
from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_MIGRATIONS,
    BUCKET_POLICIES,
    CONTINUATION_BINDINGS,
    CONTINUATION_INTENTS,
    ENVIRONMENT_REVERIFICATION,
    EVALUATOR_MIGRATION,
    LANE_MIGRATIONS,
    M_BOUND,
    M_PLANNING,
    M_STAGED,
    MIGRATION_RETRYABLE,
    MIGRATION_TRANSITIONS,
    ActionChanged,
    _check_environment_source,
    _check_migration_source,
    _kind,
    _migration_document,
    _migration_view,
    _request_of,
    _source_unchanged,
    _stage_receipt,
    lineage_of,
    migration_ack,
)
from codex_harness.coordination.domain.continuation import AWAITING_OWNER, migration_resume, migration_source
from codex_harness.coordination.domain.owner_actions import (
    COMPLETED,
    DELIVERY_PLAN,
    INTENDED,
    MAX_ACTIONS_PER_TICK,
    REFUSED,
    REJECTED,
    TERMINAL,
    UNKNOWN,
    OwnerActionRefused,
    action_id,
    new_action,
    plan_id_for,
)
from codex_harness.delivery.domain.host_delivery import (
    CANARY_FLEET,
    MIGRATION_ACTIVE,
    MIGRATION_REGISTERED,
    DeliveryRefused,
    migration_request_id,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest, utcnow


class MigrationRequestFamily:
    """The owner's evaluator migration / environment reverification request, advanced through its
    control states to the resumed continuation intent."""

    def __init__(self, store, *, clock=utcnow, deliveries=None, publisher=None, targets=None,
                 delivery_plan=None):
        self.store = store
        self.clock = clock
        self.deliveries = deliveries
        self.publisher = publisher
        self.targets = targets
        self.delivery_plan = delivery_plan

    # ===== H1: the owner's evaluator migration of a rejected, merged delivery ========================
    # INV-OWNER-ACTIONS-MIGRATION-001: an ordered durable outbox across the control store and the lane
    # store, never one transaction across both. Each step re-reads its durable inputs, calls one
    # idempotent lane/control effect and records its receipt by a version CAS; a lost response or a
    # restart replays the same step. A lane refusal is REFUSED with the lane's reason; an outage waits.
    def request_migration(self, document) -> dict:
        """Record ONE owner-only migration request per rejected source release (control store).

        The document is validated against the control records: the owner policy, the continuation
        delivery intent naming exactly this release/target/lane, and the ORIGINAL completed DELIVERY_PLAN
        action of `old_plan_id` (kept untouched as history). The identical document replays; any other
        document for the same source refuses `migration_conflict`."""
        document = _migration_document(document)
        source, kind = document["source_release_id"], _kind(document)
        request = {"old_plan_id": document["old_plan_id"], "old_plan_sha256": document["old_plan_sha256"],
                   "source_release_id": source, "source_policy_hash": document["source_policy_hash"],
                   "candidate_revision": document["candidate_revision"], "target_id": document["target_id"],
                   "actor": document["actor"], "approval": document["approval"]}
        if kind != EVALUATOR_MIGRATION:
            request["kind"] = kind      # absent for the evaluator kind: its request identity is unchanged
        request = {"migration_id": migration_request_id(request), **request}
        controller = None
        if kind == ENVIRONMENT_REVERIFICATION:
            with self.store.transaction() as tx:
                known = tx.get(BUCKET_MIGRATIONS, source) is not None
            if not known:
                controller = self._require_controller_code(document)
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_MIGRATIONS, source)
            if old is not None:
                if old.get("document") != document:
                    raise OwnerActionRefused("migration_conflict", "source_release_id")
                return {**_migration_view(old), "cached": True}
            policy_row = tx.get(BUCKET_POLICIES, document["policy_id"])
            intent = tx.get(CONTINUATION_INTENTS, document["intent_id"])
            plans = [r for r in tx.scan(BUCKET_ACTIONS)
                     if r.get("kind") == DELIVERY_PLAN and r.get("plan_id") == document["old_plan_id"]]
            _check_migration_source(document, policy_row, intent, plans)
            if kind == ENVIRONMENT_REVERIFICATION:
                _check_environment_source(document, intent, tx.get(CONTINUATION_BINDINGS, document["intent_id"]),
                                          tx.get)
            identity = digest(["owner-action", kind, {"source_release_id": source}])
            row = {"id": source, "action_id": identity, "kind": kind, "state": INTENDED,
                   "document": document, "document_sha256": digest(document), "request": request,
                   "migration_id": request["migration_id"], "policy_id": document["policy_id"],
                   "old_action_id": plans[0]["id"],
                   # The exact source intent (policy, lane, target, release, route, state, version) every
                   # later step re-checks; only the finalizing step may resume it, and only this snapshot.
                   "source_intent": migration_source(intent),
                   "subject": {"intent_id": document["intent_id"], "lane": document["lane"],
                               "source_release_id": source, "old_plan_id": document["old_plan_id"]},
                   "reason_code": None, "created_at": now, "updated_at": now, "version": 1,
                   "history": [{"state": INTENDED, "at": now, "reason_code": None}]}
            if controller is not None:
                row["controller_code"] = controller      # the preflight's resolution, not the request's
            tx.put(BUCKET_MIGRATIONS, source, row)
        return {**_migration_view(row), "cached": False}

    def _require_controller_code(self, document: dict) -> str:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001 creation preflight at the owner/lane boundary, before the
        request row exists: the lane's trusted port resolves the ACTUAL running controller code and it
        must be the approved revision. A refusal writes nothing, so the source, its intent and the one
        source-keyed request identity stay unused for the approved deployed code."""
        if self.deliveries is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        try:
            return self.deliveries(document["lane"]).require_controller_code(
                document["approval"]["controller_revision"])
        except DeliveryRefused as exc:
            raise OwnerActionRefused(exc.reason_code, "controller_revision") from exc

    def migration(self, source_release_id: str) -> dict | None:
        """Read-only projection of one migration row; None when absent."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_MIGRATIONS, source_release_id)
        return None if row is None else _migration_view(row)

    def advance(self, policy_row: dict, continuation: dict, waits: dict) -> list:
        with self.store.transaction() as tx:
            rows = sorted((r for r in tx.scan(BUCKET_MIGRATIONS)
                           if r.get("policy_id") == policy_row["id"] and r["state"] not in TERMINAL),
                          key=lambda r: (str(r.get("created_at")), r["id"]))
        effects = []
        for row in rows[:MAX_ACTIONS_PER_TICK]:
            try:
                effect = self._advance_migration(policy_row, row)
            except ActionChanged:
                effect = None
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[row["action_id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
                effect = None
            if effect is not None:
                effects.append(effect)
        return effects

    def _migration_move(self, row: dict, target: str, reason_code: str | None = None, *, extra=None,
                        **fields) -> dict:
        """Compare-and-swap on the migration row's version, under its own transition table."""
        if target not in MIGRATION_TRANSITIONS.get(row["state"], set()):
            raise OwnerActionRefused("invalid_transition", row["state"] + "->" + target)
        now = self.clock()
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_MIGRATIONS, row["id"])
            if not (isinstance(current, dict) and current.get("version") == row.get("version")):
                raise ActionChanged(row["id"])
            history = (list(current.get("history") or []) + [{"state": target, "at": now,
                                                               "reason_code": reason_code}])[-32:]
            moved_row = {**current, **fields, "state": target, "reason_code": reason_code, "updated_at": now,
                         "version": int(current.get("version") or 0) + 1, "history": history}
            if extra is not None:
                extra(tx)
            tx.put(BUCKET_MIGRATIONS, moved_row["id"], moved_row)
        return moved_row

    @staticmethod
    def effect(row: dict) -> dict:
        return {"action": row["action_id"], "kind": _kind(row), "state": row["state"],
                "reason_code": row["reason_code"]}

    def _lane_refused(self, row: dict, exc: DeliveryRefused) -> dict:
        if exc.reason_code in MIGRATION_RETRYABLE:
            raise exc
        return self.effect(self._migration_move(row, REFUSED, exc.reason_code))

    def _advance_migration(self, policy_row: dict, row: dict) -> dict | None:
        if self.deliveries is None or self.publisher is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        state, lane = row["state"], row["subject"]["lane"]
        delivery = self.deliveries(lane)
        if state == INTENDED:
            try:
                record = delivery.stage_migration(row["request"])
            except DeliveryRefused as exc:
                return self._lane_refused(row, exc)
            receipt = _stage_receipt(row, record)
            if receipt is None:
                return self.effect(self._migration_move(row, UNKNOWN, "migration_receipt_mismatch"))
            return self.effect(self._migration_move(
                row, M_STAGED, "migration_staged", lane_receipt=receipt, lane_receipt_sha256=digest(receipt),
                successor_release_id=receipt["successor_release_id"]))
        if state == M_STAGED:
            return self._plan_successor(policy_row, row)
        if state == M_PLANNING:
            return self._bind_successor(row, delivery)
        if state == M_BOUND:
            return self._finalize(row, delivery)
        return None

    def _current_intent(self, row: dict) -> dict:
        """The continuation intent, re-read; it must still be exactly the recorded source snapshot
        (policy, lane, target, release, route, state AND version)."""
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
        if not _source_unchanged(row, intent):
            raise OwnerActionRefused("migration_intent_changed", "intent_id")
        return intent

    def _plan_successor(self, policy_row: dict, row: dict) -> dict:
        """Create the migration's successor DELIVERY_PLAN action in the SAME control transaction that
        records it on the migration row: both or neither."""
        try:
            intent = self._current_intent(row)
        except OwnerActionRefused as exc:
            return self.effect(self._migration_move(row, REFUSED, exc.reason_code))
        migration = {"migration_id": row["migration_id"], "successor_release_id": row["successor_release_id"]}
        binding = self.delivery_plan.plan_binding(policy_row, intent, migration=migration)
        if binding is None:
            return self.effect(self._migration_move(row, UNKNOWN, "migration_plan_not_owed"))
        identity = action_id(DELIVERY_PLAN, binding)
        subject = {"intent_id": intent["id"], "lane": row["subject"]["lane"],
                   "migration": {"migration_action_id": row["action_id"], "migration_id": row["migration_id"],
                                 "source_release_id": row["id"],
                                 "successor_release_id": row["successor_release_id"]}}
        now = self.clock()

        def create(tx):
            existing = tx.get(BUCKET_ACTIONS, identity)
            if existing is None:
                tx.put(BUCKET_ACTIONS, identity, new_action(DELIVERY_PLAN, binding, policy_row, subject, now))
            elif existing.get("subject") != subject:
                raise OwnerActionRefused("migration_plan_conflict", "plan_id")

        return self.effect(self._migration_move(
            row, M_PLANNING, "successor_plan_intended", extra=create, plan_action_id=identity,
            plan_id=plan_id_for(identity)))

    def _bind_successor(self, row: dict, delivery) -> dict | None:
        """Once the successor plan is published, read back, its canary request filed and its registration
        HELD in the lane, record the continuation's effective binding (CAS on the intent)."""
        with self.store.transaction() as tx:
            plan_action = tx.get(BUCKET_ACTIONS, row["plan_action_id"])
        if not isinstance(plan_action, dict):
            return self.effect(self._migration_move(row, UNKNOWN, "migration_plan_action_missing"))
        if plan_action["state"] in {REFUSED, UNKNOWN, REJECTED}:
            target = REFUSED if plan_action["state"] == REFUSED else UNKNOWN
            return self.effect(self._migration_move(
                row, target, "successor_plan_" + str(plan_action.get("reason_code") or plan_action["state"])))
        if plan_action["state"] != COMPLETED:
            return None     # the existing tick is publishing/registering it
        with delivery.store.transaction() as tx:
            record = tx.get(LANE_MIGRATIONS, row["subject"]["old_plan_id"])
            target = tx.get("host_delivery_targets", row["document"]["target_id"])
        if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
                and record.get("state") in {MIGRATION_REGISTERED, MIGRATION_ACTIVE}
                and record.get("plan_id") == plan_action["plan_id"]
                and record.get("plan_sha256") == plan_action["plan_sha256"]
                and record.get("successor_release_id") == row["successor_release_id"]):
            raise OwnerActionRefused("migration_registration_unobserved", "plan_id")
        if plan_action["plan"]["canary_check_id"] == CANARY_FLEET and (
                self.targets is None or target is None
                or self.targets.request(target, plan_action["plan_id"]) != _request_of(plan_action)):
            raise OwnerActionRefused("migration_canary_request_missing", "plan_id")
        try:
            self._current_intent(row)
        except OwnerActionRefused as exc:
            return self.effect(self._migration_move(row, REFUSED, exc.reason_code))
        effective = {"intent_id": row["subject"]["intent_id"], "source_release_id": row["id"],
                     "successor_release_id": row["successor_release_id"], "old_plan_id": row["subject"]["old_plan_id"],
                     "plan_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
                     "plan_sha256": plan_action["plan_sha256"], "migration_id": row["migration_id"],
                     "migration_action_id": row["action_id"], "revision": row["document"]["candidate_revision"],
                     "target_id": row["document"]["target_id"]}

        def bind(tx):
            intent = tx.get(CONTINUATION_INTENTS, effective["intent_id"])
            if not _source_unchanged(row, intent):
                raise OwnerActionRefused("migration_intent_changed", "intent_id")
            old = tx.get(CONTINUATION_BINDINGS, effective["intent_id"])
            if old is None and _kind(row) == EVALUATOR_MIGRATION:
                tx.put(CONTINUATION_BINDINGS, effective["intent_id"], {
                    "id": effective["intent_id"], "binding": effective, "binding_sha256": digest(effective),
                    "at": self.clock()})
            elif isinstance(old, dict) and old.get("binding") == effective:
                return
            elif (_kind(row) == ENVIRONMENT_REVERIFICATION and isinstance(old, dict)
                  and (old.get("binding") or {}).get("successor_release_id") == row["id"]
                  and (old.get("binding") or {}).get("plan_id") == row["subject"]["old_plan_id"]):
                # INV-RELEASE-ENVIRONMENT-REVERIFY-001: the second hop replaces exactly the binding whose
                # successor is this source; the replaced binding is kept (digest + body) as the prior hop.
                tx.put(CONTINUATION_BINDINGS, effective["intent_id"], {
                    "id": effective["intent_id"], "binding": effective, "binding_sha256": digest(effective),
                    "previous": {"binding": old.get("binding"), "binding_sha256": old.get("binding_sha256")},
                    "at": self.clock()})
            else:
                raise OwnerActionRefused("migration_binding_conflict", "intent_id")

        return self.effect(self._migration_move(
            row, M_BOUND, "continuation_bound", extra=bind, effective=effective,
            effective_sha256=digest(effective)))

    def _finalize(self, row: dict, delivery) -> dict:
        """The durable readiness acknowledgement (INV-OWNER-ACTIONS-MIGRATION-001). The step FIRST
        re-observes the whole ready record, each from its own owner and never inside a control-store
        transaction: the successor DELIVERY_PLAN action (completed, the recorded plan id/hash), the
        effective binding and the exact source intent snapshot, the lane migration record (registered,
        same plan id/hash), the published Git pin (the action's plan and bytes hash) and the plan-scoped
        canary request (`not_requested` for a non-fleet canary). Anything missing, unreadable, replaced
        or mismatched is a named `migration_readiness_*` wait: the row stays `bound` and no ack is sent.
        A lane record already active with the identical ack (a lost finalize response) completes without
        any further readiness read or effect."""
        with self.store.transaction() as tx:
            plan_action = tx.get(BUCKET_ACTIONS, row["plan_action_id"])
            bound = tx.get(CONTINUATION_BINDINGS, row["subject"]["intent_id"])
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
        effective = row["effective"]
        if not (isinstance(plan_action, dict) and plan_action.get("state") == COMPLETED
                and plan_action.get("id") == effective["plan_action_id"]
                and plan_action.get("plan_id") == effective["plan_id"]
                and plan_action.get("plan_sha256") == effective["plan_sha256"]):
            raise OwnerActionRefused("migration_readiness_plan_action", "plan_id")
        if not (isinstance(bound, dict) and bound.get("binding") == effective):
            raise OwnerActionRefused("migration_readiness_binding", "intent_id")
        if not _source_unchanged(row, intent):
            raise OwnerActionRefused("migration_readiness_source_intent", "intent_id")
        ack = migration_ack(row, plan_action)
        with delivery.store.transaction() as tx:
            record = tx.get(LANE_MIGRATIONS, row["subject"]["old_plan_id"])
            target = tx.get("host_delivery_targets", row["document"]["target_id"])
        if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
                and record.get("plan_id") == plan_action["plan_id"]
                and record.get("plan_sha256") == plan_action["plan_sha256"]
                and record.get("successor_release_id") == row["successor_release_id"]
                and record.get("state") in {MIGRATION_REGISTERED, MIGRATION_ACTIVE}):
            raise OwnerActionRefused("migration_readiness_lane_record", "plan_id")
        if record["state"] == MIGRATION_ACTIVE:
            if record.get("ack") != ack:
                raise OwnerActionRefused("migration_readiness_ack_conflict", "ack")
            return self._complete(row, plan_action, ack, {"cached": True, "state": MIGRATION_ACTIVE}, None)
        ready = {"plan_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
                 "plan_sha256": plan_action["plan_sha256"], "bytes_sha256": self._observe_pin(row, plan_action),
                 "canary_request_id": self._observe_request(plan_action, target),
                 "binding_sha256": digest(effective), "source_intent": row["source_intent"],
                 "lane_record": {"state": record["state"], "request_sha256": record.get("request_sha256")}}
        if ready["canary_request_id"] != ack["canary_request_id"]:
            raise OwnerActionRefused("migration_readiness_canary_request_replaced", "plan_id")
        try:
            result = delivery.finalize_migration(row["migration_id"], ack)
        except DeliveryRefused as exc:
            return self._lane_refused(row, exc)
        if not (isinstance(result, dict) and result.get("state") == MIGRATION_ACTIVE
                and result.get("plan_id") == ack["plan_id"] and result.get("plan_sha256") == ack["plan_sha256"]):
            return self.effect(self._migration_move(row, UNKNOWN, "migration_ack_unconfirmed"))
        return self._complete(row, plan_action, ack, {"cached": result.get("cached"), "state": result.get("state")},
                              ready)

    def _observe_pin(self, row: dict, plan_action: dict) -> str:
        """The published pin, read back now: exactly the action's plan and bytes hash."""
        try:
            loaded = self.publisher(row["subject"]["lane"]).load(plan_action["commit"], plan_action["path"])
        except (ContractError, OSError, RuntimeError, ValueError, KeyError, TypeError):
            raise OwnerActionRefused("migration_readiness_pin_unreadable", "plan_id") from None
        if not (isinstance(loaded, dict) and loaded.get("plan") == plan_action["plan"]
                and (loaded.get("pin") or {}).get("sha256") == plan_action["bytes_sha256"]):
            raise OwnerActionRefused("migration_readiness_pin_mismatch", "plan_id")
        return plan_action["bytes_sha256"]

    def _observe_request(self, plan_action: dict, target) -> str:
        """The plan-scoped canary request, read now; `not_requested` only for a non-fleet canary."""
        if plan_action["plan"]["canary_check_id"] != CANARY_FLEET:
            return "not_requested"
        if self.targets is None or not isinstance(target, dict):
            raise OwnerActionRefused("migration_readiness_canary_unconfigured", "targets")
        try:
            observed = self.targets.request(target, plan_action["plan_id"])
        except (ContractError, OSError, RuntimeError, ValueError):
            raise OwnerActionRefused("migration_readiness_canary_request_unreadable", "plan_id") from None
        if observed is None:
            raise OwnerActionRefused("migration_readiness_canary_request_missing", "plan_id")
        if observed != _request_of(plan_action):
            raise OwnerActionRefused("migration_readiness_canary_request_replaced", "plan_id")
        return digest(observed)

    def _complete(self, row: dict, plan_action: dict, ack: dict, finalized: dict, ready) -> dict:
        """bound -> completed, and in the SAME control transaction the one authorized resume of exactly
        the recorded source intent (PAUSED -> the delivery-observing state); a moved source refuses
        `migration_source_changed` inside it and nothing is written (the row stays bound, a wait)."""
        lineage = lineage_of(row, plan_action)
        now = self.clock()

        def resume(tx):
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
            resumed = migration_resume(intent, row["source_intent"],
                                       {"migration_action_id": row["action_id"], **lineage}, now)
            if resumed is not None:
                # INV-CONTINUATION-001: through IntentStore, inside this same transaction (the atomic unit is unchanged).
                IntentStore.replace(tx, intent, resumed)

        return self.effect(self._migration_move(
            row, COMPLETED, "migration_finalized", extra=resume, ack=ack, lineage=lineage, finalized=finalized,
            readiness=ready, source_resumed=row["source_intent"].get("state") != AWAITING_OWNER))

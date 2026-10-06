"""The host target registry and the delivery plans.

Layer: application
Context: delivery
Owns: buckets host_delivery_targets, host_delivery_plans
Does not own: the intents and migrations (DeliveryState, DeliveryMigration)
Entry points: DeliveryRegistry
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
    maintenance_hold_in,
)
from codex_harness.delivery.domain.host_delivery import (
    AUTHORITY,
    MIGRATION_RESERVING,
    OUTCOME_UNREGISTERED,
    REGISTERED,
    STATUS_SCHEMA,
    DeliveryRefused,
    delivery_status,
    first_activation_unbound,
    plan_digest,
    validate_pin,
    validate_plan,
    validate_targets,
)
from codex_harness.kernel.ids import utcnow


def reservation_in(tx, target_id: str):
    """The unfinished migration (`staged`/`registered`) holding this target, or None."""
    for record in tx.scan(BUCKET_MIGRATIONS):
        if record.get("target_id") == target_id and record.get("state") in MIGRATION_RESERVING:
            return record
    return None


class DeliveryRegistry:
    """The owner's host target registry and the Git-pinned delivery plans, with their read-only projections
    (M7 `HostDelivery` registry part)."""

    def __init__(self, store, *, clock=utcnow, enabled=False, state=None):
        self.store = store
        self.clock = clock
        self.enabled = bool(enabled)
        self.state = state

    # ----- registry -----------------------------------------------------------------------
    def register_targets(self, document) -> dict:
        """Register the owner's authorized host target registry; the identical document is cached."""
        registry = validate_targets(document)
        now = self.clock()
        with self.store.transaction() as tx:
            for target in registry["targets"]:
                old = tx.get(BUCKET_TARGETS, target["target_id"]) or {}
                tx.put(BUCKET_TARGETS, target["target_id"],
                       {"id": target["target_id"], **target,
                        "registered_at": old.get("registered_at") or now, "updated_at": now})
        return {"registered": True, "targets": [t["target_id"] for t in registry["targets"]],
                "authority": AUTHORITY}

    def register(self, document, pin) -> dict:
        """Register one validated delivery plan read at an explicit commit.

        The target must already exist in the owner's registry, so a plan can never introduce one.
        The identical plan at the identical pin is cached. A plan whose delivery has already left
        `registered` may not be edited at all: a changed release, revision, tree, evaluator hash,
        target or descriptor refuses the whole registration and writes nothing, so no in-flight
        delivery is ever re-pointed at another candidate.
        """
        plan = validate_plan(document)
        pin = validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            cached = self.register_in(tx, plan, pin, sha, now)
        return {"registered": True, "cached": cached, "plan_id": plan["plan_id"], "plan_sha256": sha,
                "pin": pin, "target_id": plan["target_id"], "release_id": plan["release_id"],
                "authority": AUTHORITY}

    def register_in(self, tx, plan: dict, pin: dict, sha: str, now: str, *, migration=None) -> bool:
        """`register` inside a caller's transaction; True for the identical cached registration.

        A target reserved by an unfinished evaluator migration (INV-HOST-DELIVERY-MIGRATION-001)
        admits no NEW plan except that migration's own one, so terminalizing the rejected source
        never frees its target for another delivery before the successor is registered."""
        if tx.get(BUCKET_TARGETS, plan["target_id"]) is None:
            raise DeliveryRefused("target_unregistered", "target_id")
        old = tx.get(BUCKET_PLANS, plan["plan_id"])
        intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
        if old is not None:
            if old["plan_sha256"] == sha and old["pin"] == pin:
                return True
            if intent is not None and intent.get("stage") != REGISTERED:
                raise DeliveryRefused("delivery_in_flight", "plan_id")
        if maintenance_hold_in(tx, plan["target_id"]) is not None:
            # INV-HOST-DELIVERY-MAINTENANCE-001: an open (or failed) maintenance holds its target for every
            # other registration, including a migration's own successor.
            raise DeliveryRefused("maintenance_target_busy", "target_id")
        if first_activation_unbound(plan):
            # INV-HOST-DELIVERY-FIRST-ACTIVATION-001: a NEW plan that expects no predecessor yet says
            # `unchanged` could never resolve; only the identical, already stored plan replays above.
            raise DeliveryRefused("first_activation_unbound", "target_descriptor")
        reserved = reservation_in(tx, plan["target_id"])
        if reserved is not None and (migration is None or reserved["id"] != migration["id"]):
            raise DeliveryRefused("target_reserved_by_migration", "target_id")
        row = {"id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan,
               "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
               "registered_at": (old or {}).get("registered_at") or now, "updated_at": now}
        tx.put(BUCKET_PLANS, plan["plan_id"], row)
        return False

    def approval(self, document) -> dict:
        """What the EXISTING release record says about one plan document, before it is registered: the
        same read-only gate a tick applies (`release_gate`). A server owner publishing a plan uses it to
        publish only an approved exact candidate (INV-OWNER-ACTIONS-001); it approves nothing."""
        return self.state.gate(validate_plan(document))

    def plan(self, plan_id: str):
        with self.store.transaction() as tx:
            return tx.get(BUCKET_PLANS, plan_id)

    def status(self, plan_id: str | None = None) -> dict:
        """The durable bounded projection of one plan or of every registered plan. Store reads only:
        no git, GitHub, process, descriptor file, provider or host observation happens here."""
        with self.store.transaction() as tx:
            rows = (tx.scan(BUCKET_PLANS) if plan_id is None
                    else [row for row in [tx.get(BUCKET_PLANS, plan_id)] if row])
            intents = {row["plan_id"]: row for row in tx.scan(BUCKET_INTENTS)}
            descriptors = {row["target_id"]: row for row in tx.scan(BUCKET_DESCRIPTORS)}
            migrations = tx.scan(BUCKET_MIGRATIONS)
        # INV-HOST-DELIVERY-MIGRATION-001: each migration's phase and its successor's hold, read only.
        shown = sorted(({"old_plan_id": m.get("id"), "migration_id": m.get("migration_id"),
                         "kind": m.get("kind", "evaluator_migration"), "state": m.get("state"),
                         "held": (intents.get(m.get("plan_id")) or {}).get("held") if m.get("plan_id") else None,
                         "successor_release_id": m.get("successor_release_id"), "plan_id": m.get("plan_id"),
                         "target_id": m.get("target_id"), "at": m.get("at")}
                        for m in migrations if plan_id is None or plan_id in {m.get("id"), m.get("plan_id")}),
                       key=lambda m: (str(m["old_plan_id"]), str(m["migration_id"])))
        # The migration projection is additive: a store with no registered plan and no migration keeps
        # the exact unregistered envelope it always had (INV-HOST-DELIVERY-MIGRATION-001).
        projected = {"migrations": shown} if rows or migrations else {}
        if plan_id is not None and not rows:
            return {"schema": STATUS_SCHEMA, "plan_id": plan_id, "registered": False,
                    "enabled": self.enabled, "outcome": OUTCOME_UNREGISTERED, "deliveries": [],
                    "next_action": "register_plan", "targets": sorted(descriptors),
                    **projected, "authority": AUTHORITY}
        return {**delivery_status(rows, intents, descriptors, enabled=self.enabled), **projected}

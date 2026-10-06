"""G2 delivery plan publication and registration.

Layer: application
Context: coordination
Owns: no bucket of its own
Does not own: the Git publication (publisher), the registration (the lane's HostDelivery, S7)
Entry points: DeliveryRegistrationFamily
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import (
    LANE_MIGRATIONS,
    _request_of,
    digest_bytes,
    plan_json,
)
from codex_harness.coordination.domain.continuation import (
    DELIVERY_ABSENT,
    DELIVERY_BOUND,
    DELIVERY_STALE,
    bind_delivery,
)
from codex_harness.coordination.domain.owner_actions import (
    COMPLETED,
    DELIVERY_PLAN,
    INTENDED,
    PUBLISHED,
    PUBLISHING,
    REFUSED,
    UNKNOWN,
    OwnerActionRefused,
    action_id,
    build_plan,
    first_activation_tuple,
    plan_binding,
    plan_path,
    plan_ref,
)
from codex_harness.delivery.domain.host_delivery import (
    CANARY_FLEET,
    MIGRATION_RESERVING,
    TERMINAL_STAGES,
    DeliveryRefused,
    descriptor_digest,
    plan_digest,
)
from codex_harness.kernel.errors import ContractError


class DeliveryRegistrationFamily:
    """G2: the exact approved delivery plan, published to Git and registered with the lane's HostDelivery."""

    def __init__(self, store, *, deliveries=None, first_activation=None, publisher=None, targets=None,
                 actions=None):
        self.store = store
        self.deliveries = deliveries
        self.first_activation = first_activation
        self.publisher = publisher
        self.targets = targets
        self.actions = actions

    # ===== G2: exact approved delivery-plan publication ===============================================
    def lane_rows(self, lane_id: str, target_id: str, release_id: str | None) -> dict:
        delivery = self.deliveries(lane_id)
        with delivery.store.transaction() as tx:
            return {"delivery": delivery, "release": tx.get("releases", release_id) if release_id else None,
                    "intents": tx.scan("host_delivery_intents"), "plans": tx.scan("host_delivery_plans"),
                    "descriptor": tx.get("host_delivery_descriptors", target_id),
                    "target": tx.get("host_delivery_targets", target_id),
                    "migrations": tx.scan(LANE_MIGRATIONS)}

    def plan_binding(self, row: dict, intent: dict, *, migration: dict | None = None) -> dict | None:
        """A plan is owed only for a conducted delivery intent whose release is approved for exactly this
        target and has no delivery yet, while no other delivery is in flight on that target.

        `migration` (the control migration row, INV-OWNER-ACTIONS-MIGRATION-001) binds the plan to that
        migration's staged SUCCESSOR release instead of the conductor's release; only that migration's
        own lane reservation does not make the target busy for it."""
        if self.deliveries is None or self.publisher is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        policy = row["policy"]
        target_id = policy["delivery"]["target_id"]
        if intent.get("delivery_target") != target_id:
            return None
        release_id = intent.get("release_id") if migration is None else migration["successor_release_id"]
        rows = self.lane_rows(intent["lane"], target_id, release_id)
        release = rows["release"]
        if not isinstance(release, dict):
            raise OwnerActionRefused("release_missing", "release_id")
        candidate = release.get("candidate") or {}
        # The superseded source intent carries the same candidate revision: a successor binds only the
        # deliveries of its own release.
        scope = rows["intents"] if migration is None else [
            r for r in rows["intents"] if r.get("release_id") == release.get("id")]
        bound = bind_delivery(scope, target_id, release.get("id"), candidate.get("revision"), release)
        if bound["binding"] == DELIVERY_BOUND:
            return None     # this exact candidate already has its delivery: nothing is owed
        if bound["binding"] not in {DELIVERY_ABSENT, DELIVERY_STALE}:
            # Ambiguous, mismatched or unknown delivery evidence is the continuation's named wait too.
            raise OwnerActionRefused("delivery_" + bound["binding"], "release_id")
        # `stale` only says the target has deliveries of OTHER revisions; none exists for this candidate.
        if rows["target"] is None:
            raise OwnerActionRefused("target_unregistered", "target_id")
        # SPEC s14.3 "no in-progress delivery on the target": every REGISTERED plan of the target counts,
        # including one no tick has given an intent yet, so a successor binds its expected predecessor
        # only after the delivery before it is terminal. Terminal is not safe-to-switch evidence; the
        # delivery's own pre-merge and switch checks still decide that (INV-OWNER-ACTIONS-001).
        stages = {r.get("plan_id") or r.get("id"): r.get("stage") for r in rows["intents"]}
        mine = [p for p in rows["plans"] if p.get("target_id") == target_id]
        if any((p.get("plan") or {}).get("release_id") == release.get("id")
               and (p.get("plan") or {}).get("revision") == candidate.get("revision") for p in mine):
            return None     # this exact candidate is already planned; its delivery is simply not started
        if any(stages.get(p.get("plan_id")) not in TERMINAL_STAGES for p in mine) or any(
                r.get("target_id") == target_id and r.get("stage") not in TERMINAL_STAGES for r in rows["intents"]):
            raise OwnerActionRefused("delivery_target_busy", "target_id")
        # A staged/registered lane migration reserves its target for every plan but its own successor.
        own = None if migration is None else migration["migration_id"]
        if any(m.get("target_id") == target_id and m.get("state") in MIGRATION_RESERVING
               and m.get("migration_id") != own for m in rows["migrations"]):
            raise OwnerActionRefused("delivery_target_busy", "target_id")
        current = (rows["descriptor"] or {}).get("descriptor")
        # INV-HOST-DELIVERY-001: `unchanged` resolves only against a current descriptor. A first activation
        # binds the concrete tuple here, BEFORE any action row exists; an upgrade never consults the port.
        facts = None if current is not None else self._first_activation_facts(intent["lane"],
                                                                                 candidate.get("revision"))
        binding = plan_binding(row, intent, release, None if current is None else descriptor_digest(current),
                               first_activation=facts)
        plan = build_plan(policy, binding, action_id(DELIVERY_PLAN, binding), first_activation=facts)
        gate = rows["delivery"].approval(plan)
        if gate.get("state") != "approved":
            raise OwnerActionRefused(gate.get("reason_code") or "release_not_approved", "release_id")
        return binding

    def _first_activation_facts(self, lane_id: str, revision) -> dict:
        """The first-activation tuple from the lane boundary's trusted port, validated. No port, a port
        failure or malformed facts is a named refusal raised before any action row or publication: the
        caller's discovery (or migration step) records it as a wait and writes nothing."""
        if self.first_activation is None:
            raise OwnerActionRefused("first_activation_unconfigured", "first_activation")
        try:
            facts = self.first_activation(lane_id, revision)
        except ContractError as exc:
            raise OwnerActionRefused(getattr(exc, "reason_code", None) or "first_activation_unavailable",
                                     "first_activation") from None
        except Exception:  # an adapter outage of any type is a wait, never an unbound plan
            raise OwnerActionRefused("first_activation_unavailable", "first_activation") from None
        return first_activation_tuple(facts)

    def advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state, lane = action["state"], action["subject"]["lane"]
        if state == INTENDED:
            try:
                # The tuple bound at discovery is the one published; the port is not consulted again.
                plan = build_plan(policy_row["policy"], action["binding"], action["id"],
                                  first_activation=action["binding"].get("first_activation"))
            except OwnerActionRefused as exc:
                if exc.reason_code != "first_activation_unbound":
                    raise
                # A row recorded before first activations were bound: refused before any publication.
                return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
            data = plan_json(plan)
            return self.actions.effect(self.actions.move(action, PUBLISHING, "plan_intended", plan=plan, plan_id=plan["plan_id"],
                                           plan_sha256=plan_digest(plan), path=plan_path(plan["plan_id"]),
                                           ref=plan_ref(plan["plan_id"]), bytes_sha256=digest_bytes(data),
                                           published_at=action["created_at"]))
        if state == PUBLISHING:
            data = plan_json(action["plan"])
            published = self.publisher(lane).publish(data, action["path"], action["ref"], action["published_at"])
            if published.get("conflict"):
                # The ref already names other content: another owner or a hand edit. Held, never overwritten.
                return self.actions.effect(self.actions.move(action, UNKNOWN, "plan_ref_conflict"))
            return self.actions.effect(self.actions.move(action, PUBLISHED, "plan_published", commit=published["revision"]))
        if state == PUBLISHED:
            return self._register(action, lane)
        return None

    def _register(self, action: dict, lane: str) -> dict:
        loaded = self.publisher(lane).load(action["commit"], action["path"])
        if loaded["plan"] != action["plan"] or loaded["pin"]["sha256"] != action["bytes_sha256"]:
            return self.actions.effect(self.actions.move(action, UNKNOWN, "plan_content_mismatch"))
        delivery = self.deliveries(lane)
        if action["plan"]["canary_check_id"] == CANARY_FLEET:
            # Filed BEFORE registration: the incumbent canary check then waits for the owner's actual
            # canary of exactly this plan, and only until the delivery's own consumption deadline.
            with delivery.store.transaction() as tx:
                target = tx.get("host_delivery_targets", action["plan"]["target_id"])
            if self.targets is None or target is None:
                raise OwnerActionRefused("canary_targets_unconfigured", "targets")
            self.targets.write_request(target, action["plan_id"], _request_of(action))
        migration = (action.get("subject") or {}).get("migration")
        try:
            if isinstance(migration, dict):
                # The migration's own successor plan registers HELD until the control acknowledgement.
                registered = delivery.register_migration_plan(loaded["plan"], loaded["pin"],
                                                              migration["migration_id"])
            else:
                registered = delivery.register(loaded["plan"], loaded["pin"])
        except DeliveryRefused as exc:
            return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
        return self.actions.effect(self.actions.move(action, COMPLETED, "plan_registered",
                                       registration={"plan_sha256": registered["plan_sha256"],
                                                     "cached": registered["cached"], "pin": loaded["pin"]}))

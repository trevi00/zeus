"""The lane half of a release migration.

Layer: application
Context: delivery
Owns: bucket host_delivery_migrations
Does not own: the successor release (review's Releases migration requests)
Entry points: DeliveryMigration
Contracts: INV-HOST-DELIVERY-MIGRATION-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

from datetime import datetime

from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_INTENTS,
    BUCKET_MIGRATIONS,
    BUCKET_PLANS,
    LOGGER,
    maintenance_hold_in,
    predecessor_in,
)
from codex_harness.delivery.domain.host_delivery import (
    AUTHORITY,
    EVENT_STAGE,
    MERGED,
    MIGRATION_ACTIVE,
    MIGRATION_HELD,
    MIGRATION_KIND_ENVIRONMENT,
    MIGRATION_REGISTERED,
    MIGRATION_RESERVING,
    MIGRATION_STAGED,
    OUTCOME_PROGRESSED,
    REGISTERED,
    TERMINAL_STAGES,
    VERIFYING,
    WITHDRAWN,
    DeliveryRefused,
    migration_kind,
    migration_lineage_digest,
    migration_rejected_source,
    new_intent,
    plan_digest,
    release_gate,
    validate_migration_ack,
    validate_migration_request,
    validate_pin,
    validate_plan,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.review.domain.releases import (
    EnvironmentReverificationRefused,
    expected_evaluator_pin,
    require_controller_code,
)


def migration_in(tx, migration_id) -> dict:
    for record in tx.scan(BUCKET_MIGRATIONS):
        if type(migration_id) is str and record.get("migration_id") == migration_id:
            return record
    raise DeliveryRefused("migration_unknown", "migration_id")


def migration_view(record: dict, *, cached: bool) -> dict:
    return {"migration": True, "cached": cached, "kind": record.get("kind", "evaluator_migration"),
            **{name: record.get(name) for name in ("migration_id", "state", "request_sha256",
                                                   "source_release_id", "successor_release_id", "target_id",
                                                   "plan_id", "plan_sha256")},
            "old_plan_id": record.get("id"), "acknowledged": record.get("ack") is not None,
            "authority": AUTHORITY}


class DeliveryMigration:
    """The lane half of a release migration: stage, register, finalize, and the running controller code
    (INV-HOST-DELIVERY-MIGRATION-001)."""

    def __init__(self, store, *, clock=utcnow, releases=None, claims=None, evaluator_pins=None,
                 controller_code=None, registry=None, state=None):
        self.store = store
        self.clock = clock
        self.releases = releases
        self.claims = claims
        self.evaluator_pins = evaluator_pins
        self.controller_code = controller_code
        self.registry = registry
        self.state = state

    # ----- evaluator migration of a rejected, merged delivery (INV-HOST-DELIVERY-MIGRATION-001) ---
    # The lane half of an ordered control/lane handoff; each step is ONE lane transaction and a
    # crash between steps leaves a named `staged`/`registered` record that reserves the target and
    # holds its successor, never a free target or an unowned runnable delivery.
    def stage_migration(self, request: dict) -> dict:
        """Step 1: supersede the exact rejected, merged, host-untouched source and reserve its target.

        Read-only validation first; then ONE transaction re-checks the source intent and plan (CAS),
        the controller lease, the source queue row and the target, creates the reviewed successor
        release through `Releases.request_evaluator_migration` in that same transaction, terminalizes
        the old intent truthfully (`withdrawn`/`release_rejected_superseded`, its halt copied) and
        writes the `staged` record. Nothing is enqueued. The identical request replays `cached`
        with no write; any other request for the same source is `migration_conflict`.
        """
        request = validate_migration_request(request)
        sha, key = digest(request), request["old_plan_id"]
        try:
            with self.store.transaction() as tx:
                record = tx.get(BUCKET_MIGRATIONS, key)
                row = tx.get(BUCKET_PLANS, key)
                intent = tx.get(BUCKET_INTENTS, key)
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        if record is not None:
            return self._migration_replay(record, sha)
        if row is None:
            raise DeliveryRefused("plan_unregistered", "old_plan_id")
        if row["plan_sha256"] != request["old_plan_sha256"]:
            raise DeliveryRefused("migration_plan_mismatch", "old_plan_sha256")
        refusal = migration_rejected_source(intent, row["plan"], request)
        if refusal is not None:
            raise DeliveryRefused(refusal, "old_plan_id")
        controller = None
        if migration_kind(request) == MIGRATION_KIND_ENVIRONMENT:
            controller = self.require_controller_code(request["approval"]["controller_revision"])
            resolved = self._resolve_source_pin(request["source_release_id"])
        else:
            resolved = self._resolve_evaluator_pin(request["approval"])
        now = self.clock()
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_MIGRATIONS, key)
                staged = None if current is not None else self._stage_in(tx, row, intent, request, sha, now,
                                                                         resolved, controller)
        except DeliveryRefused:
            raise
        except ContractError as exc:
            raise DeliveryRefused("migration_release_refused", "source_release_id") from exc
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        if staged is None:
            # A concurrent request committed first: its record decides, nothing was written here.
            return self._migration_replay(current, sha)
        self.state.emit(EVENT_STAGE, "observed", row["plan"], attributes={
            "plan_id": key, "release_id": row["plan"]["release_id"], "target_id": row["plan"]["target_id"],
            "stage": WITHDRAWN, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery migration staged plan=%s successor=%s", key, staged["successor_release_id"])
        return migration_view(staged, cached=False)

    def _resolve_evaluator_pin(self, approval: dict) -> dict:
        """Derive the approved evaluator pin from the repository BEFORE any write and outside every
        store transaction (INV-RELEASE-EVALUATOR-MIGRATION-001). An absent or failing resolver is
        `migration_pin_unavailable`; any disagreement with the approval is `migration_pin_mismatch`.
        Either refusal leaves the source release, the migration identity and the old intent untouched."""
        if self.evaluator_pins is None:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision")
        try:
            resolved = self.evaluator_pins(approval["evaluator_revision"], approval["base"])
        except Exception as exc:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision") from exc
        if resolved != expected_evaluator_pin(approval):
            raise DeliveryRefused("migration_pin_mismatch", "approval")
        return resolved

    def require_controller_code(self, expected: str) -> str:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001 creation preflight, outside every store transaction:
        resolve the ACTUAL running controller code through the trusted port and require the approved
        revision. The approval's own string is never evidence. Unknown code refuses
        `migration_controller_code_unavailable`, other code `migration_controller_code_mismatch`;
        nothing is read from or written to the stores, so the source, its intent and the one successor
        identity stay unused and the approved deployed code can stage later."""
        if self.controller_code is None:
            raise DeliveryRefused("migration_controller_code_unavailable", "controller_revision")
        try:
            resolved = self.controller_code()
        except Exception as exc:
            raise DeliveryRefused("migration_controller_code_unavailable", "controller_revision") from exc
        try:
            return require_controller_code(resolved, expected)
        except EnvironmentReverificationRefused as exc:
            reason = ("migration_controller_code_mismatch" if exc.reason_code.endswith("_mismatch")
                      else "migration_controller_code_unavailable")
            raise DeliveryRefused(reason, "controller_revision") from exc

    def _resolve_source_pin(self, release_id: str) -> dict:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001: re-derive the migrated source's OWN evaluator pin
        (its recorded E and base) from the repository, outside every store transaction. The release
        service compares it with the source's receipt again inside the staging transaction."""
        try:
            with self.store.transaction() as tx:
                source = tx.get("releases", release_id)
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        receipt = (source or {}).get("evaluator_migration")
        if not isinstance(receipt, dict):
            raise DeliveryRefused("migration_release_refused", "source_release_id")
        if self.evaluator_pins is None:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision")
        try:
            resolved = self.evaluator_pins(receipt["evaluator_revision"], receipt["base"])
        except Exception as exc:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision") from exc
        if resolved != expected_evaluator_pin(receipt):
            raise DeliveryRefused("migration_pin_mismatch", "approval")
        return resolved

    def _stage_in(self, tx, row: dict, intent: dict, request: dict, sha: str, now: str,
                  resolved_pin: dict, controller: str | None) -> dict:
        """Phase 2 of `stage_migration`, inside its one transaction; any refusal rolls back all."""
        plan, key = row["plan"], row["plan_id"]
        if tx.get(BUCKET_PLANS, key) != row or tx.get(BUCKET_INTENTS, key) != intent:
            raise DeliveryRefused("migration_intent_changed", "old_plan_id")
        if maintenance_hold_in(tx, plan["target_id"]) is not None:
            raise DeliveryRefused("maintenance_target_busy", "target_id")   # INV-HOST-DELIVERY-MAINTENANCE-001
        lock = tx.get("deployment_locks", "controller") or {}
        if (lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self.state.now()) \
                or (tx.get("release_queue", plan["release_id"]) or {}).get("status") == "running":
            raise DeliveryRefused("migration_controller_running", "release_id")
        for other in tx.scan(BUCKET_MIGRATIONS):
            if other.get("source_release_id") == request["source_release_id"]:
                raise DeliveryRefused("migration_conflict", "source_release_id")
            if other.get("target_id") == plan["target_id"] and other.get("state") in MIGRATION_RESERVING:
                raise DeliveryRefused("migration_target_busy", "target_id")
        stages = {other["plan_id"]: other.get("stage") for other in tx.scan(BUCKET_INTENTS)}
        if any(other["target_id"] == plan["target_id"] and other["plan_id"] != key
               and stages.get(other["plan_id"]) not in TERMINAL_STAGES for other in tx.scan(BUCKET_PLANS)):
            # Every other plan of the target, including one no tick has given an intent yet.
            raise DeliveryRefused("migration_target_busy", "target_id")
        kind = migration_kind(request)
        successor_of, extra = self.releases.request_evaluator_migration, {}
        if kind == MIGRATION_KIND_ENVIRONMENT:
            # The resolved controller code travels into the same transaction and is recorded there.
            successor_of, extra = self.releases.request_environment_reverification, {"resolved_controller": controller}
        successor = successor_of(
            request["source_release_id"], request["actor"], expected_revision=request["candidate_revision"],
            expected_policy_hash=request["source_policy_hash"], approval=request["approval"],
            resolved_pin=resolved_pin, now=self.state.now(), transaction=tx, **extra)
        if successor.get("status") != "reviewed" or successor.get("checks"):
            raise DeliveryRefused("migration_successor_advanced", "successor_release_id")
        if tx.get("release_queue", successor["id"]) is not None:
            raise DeliveryRefused("migration_successor_queued", "successor_release_id")
        original = {name: intent.get(name) for name in ("stage", "previous_stage", "reason_code", "outcome",
                                                        "attempts", "error_type", "updated_at")}
        tx.put(BUCKET_INTENTS, key, {
            **intent, "stage": WITHDRAWN, "previous_stage": intent["stage"], "outcome": WITHDRAWN,
            "reason_code": "release_rejected_superseded", "error_type": None, "stage_deadline": None,
            "main_effect": "merged",
            "supersession": {"migration_id": request["migration_id"], "successor_release_id": successor["id"],
                             "original_halt": original},
            "updated_at": now})
        record = {"id": key, "migration_id": request["migration_id"], "kind": kind, "request": request,
                  "request_sha256": sha, "state": MIGRATION_STAGED, "successor_release_id": successor["id"],
                  "source_release_id": request["source_release_id"], "target_id": plan["target_id"],
                  "plan_id": None, "plan_sha256": None, "ack": None, "at": now}
        tx.put(BUCKET_MIGRATIONS, key, record)
        return record

    def register_migration_plan(self, document, pin, migration_id: str) -> dict:
        """Step 2: register ONLY this migration's exact successor plan, HELD at `verifying`.

        The plan must name the staged successor release, the source's target and candidate
        revision, and a predecessor the target still holds. It is registered through the same
        `_register_in` as every plan; its intent keeps the source's observed merge (`verifying` then
        `merged`, never a second publication) and stays `held` until `finalize_migration`. Nothing
        is enqueued. The identical plan and pin replay `cached`; any other plan is a conflict.
        """
        plan, pin = validate_plan(document), validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            record = migration_in(tx, migration_id)
            if record["state"] != MIGRATION_STAGED:
                registered = tx.get(BUCKET_PLANS, plan["plan_id"]) or {}
                if (record["plan_id"], record["plan_sha256"], registered.get("pin")) == (plan["plan_id"], sha, pin):
                    return migration_view(record, cached=True)
                raise DeliveryRefused("migration_conflict", "plan_id")
            request = record["request"]
            if (plan["release_id"], plan["target_id"], plan["revision"]) != (
                    record["successor_release_id"], record["target_id"], request["candidate_revision"]):
                raise DeliveryRefused("migration_plan_mismatch", "plan_id")
            old = tx.get(BUCKET_INTENTS, record["id"]) or {}
            if old.get("stage") != WITHDRAWN or (old.get("supersession") or {}).get("migration_id") != migration_id:
                raise DeliveryRefused("migration_predecessor_changed", "old_plan_id")
            if tx.get(BUCKET_PLANS, plan["plan_id"]) is not None or tx.get(BUCKET_INTENTS, plan["plan_id"]):
                raise DeliveryRefused("migration_plan_exists", "plan_id")
            release = tx.get("releases", plan["release_id"])
            if release_gate(release, plan, self.state.parent(release))["state"] != "approved":
                raise DeliveryRefused("migration_release_not_approved", "release_id")
            if tx.get("release_queue", plan["release_id"]) is not None:
                raise DeliveryRefused("migration_successor_queued", "release_id")
            predecessor = predecessor_in(tx, plan)
            if predecessor != "held":
                raise DeliveryRefused("migration_predecessor_" + predecessor, "target_id")
            self.registry.register_in(tx, plan, pin, sha, now, migration=record)
            tx.put(BUCKET_INTENTS, plan["plan_id"], {
                **new_intent(plan, sha, now), "stage": VERIFYING, "previous_stage": REGISTERED,
                "outcome": OUTCOME_PROGRESSED, "after_verification": MERGED,
                **{name: old.get(name) for name in ("merged_revision", "head", "pr_number", "pr_url",
                                                    "last_check_state")},
                "migration": {"migration_id": migration_id, "predecessor_plan_id": record["id"],
                              "source_release_id": record["source_release_id"]},
                "held": MIGRATION_HELD})
            record = {**record, "state": MIGRATION_REGISTERED, "plan_id": plan["plan_id"], "plan_sha256": sha}
            tx.put(BUCKET_MIGRATIONS, record["id"], record)
        return migration_view(record, cached=False)

    def finalize_migration(self, migration_id: str, ack: dict) -> dict:
        """Step 3: the explicit durable control acknowledgement releases the held successor.

        The acknowledgement must name exactly the registered plan id and digest and the staged
        request digest. In ONE transaction the hold is cleared, the ack recorded, the record made
        `active` and the successor release queued; only then may an ordinary tick claim and verify
        it. The identical ack replays `cached`; another ack for an active migration conflicts.
        """
        ack = validate_migration_ack(ack)
        with self.store.transaction() as tx:
            record = migration_in(tx, migration_id)
            if record["state"] == MIGRATION_ACTIVE:
                if record["ack"] == ack:
                    return migration_view(record, cached=True)
                raise DeliveryRefused("migration_conflict", "ack")
            if record["state"] != MIGRATION_REGISTERED:
                raise DeliveryRefused("migration_not_registered", "migration_id")
            if (ack["plan_id"], ack["plan_sha256"], ack["request_sha256"]) != (
                    record["plan_id"], record["plan_sha256"], record["request_sha256"]):
                raise DeliveryRefused("migration_ack_mismatch", "ack")
            if ack["lineage_sha256"] != migration_lineage_digest(
                    record["source_release_id"], record["successor_release_id"], record["id"],
                    record["plan_id"], record["migration_id"]):
                raise DeliveryRefused("migration_ack_mismatch", "lineage_sha256")
            intent = tx.get(BUCKET_INTENTS, record["plan_id"]) or {}
            if (intent.get("held") != MIGRATION_HELD or intent.get("stage") != VERIFYING
                    or (intent.get("migration") or {}).get("migration_id") != migration_id
                    or (tx.get(BUCKET_PLANS, record["plan_id"]) or {}).get("plan_sha256") != record["plan_sha256"]):
                raise DeliveryRefused("migration_intent_changed", "plan_id")
            try:
                queued = self.claims.enqueue(record["successor_release_id"],
                                            "host delivery migration " + record["plan_id"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("migration_queue_refused", "release_id") from exc
            if queued.get("status") != "queued" or queued.get("attempt"):
                # A row someone else created while held is never adopted as this successor's start.
                raise DeliveryRefused("migration_queue_refused", "release_id")
            tx.put(BUCKET_INTENTS, record["plan_id"], {**intent, "held": None, "updated_at": self.clock()})
            record = {**record, "state": MIGRATION_ACTIVE, "ack": ack}
            tx.put(BUCKET_MIGRATIONS, record["id"], record)
        return migration_view(record, cached=False)

    def _migration_replay(self, record: dict, sha: str) -> dict:
        if record.get("request_sha256") != sha:
            raise DeliveryRefused("migration_conflict", "request")
        return migration_view(record, cached=True)

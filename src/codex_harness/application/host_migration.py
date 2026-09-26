"""Resumable host migration coordinator over the existing document store (INV-HOST-MIGRATION-001).

@invariant INV-HOST-MIGRATION-001

One `migration_id` is one row: the validated manifest, its digest, the current state and the
ordered transition history. Every write is one store transaction (the PostgreSQL advisory lock
serializes it), so two coordinators cannot both advance the same migration. The coordinator never
touches Fleet, HostDelivery, Redis, Docker or a file: it RECORDS what the adapters observed, and
the Fleet registry itself still moves only through `Fleet.relocate` (INV-FLEET-001).

* `plan` is idempotent on the identical manifest; a different manifest under the same id refuses.
* `advance` is compare-and-swap on the stated `from` state and the manifest digest; the identical
  transition replays from its record and a stale or different one refuses.
* `checkpoint` records one restore step's input and output digests. The same step over the same
  input replays; over a different input it refuses, so a resumed restore never restores twice.
* `intend_activation` records the durable activation intent in `restored_paused`, BEFORE the
  adapter writes the launcher's `host-activation.json` or starts any target writer. From then on
  the rollback mode is R1, including after an interruption before `limited_active` was recorded.
* `record_successor` records a successor activation of the EFFECTIVE activation in
  `restored_paused`: one successor per exact predecessor, the intent itself never rewritten.
* `activation_switch` selects the effective head and hands it to the adapter's file effect INSIDE
  the same store transaction `record_successor` takes, so a switch and a successor record (or two
  switches) are serialized and a stale head can never be written after a newer one.
* `limited_active` needs the host-activation receipt bound to the effective activation and a
  service startup receipt whose revision/image/profile are the effective activation's;
  `rolled_back` needs the gate receipt of the recorded mode and, under R1, every reverse step's
  checkpoint.

The row is a receipt record. Its state is never, by itself, proof that a source was fenced, a
target activated or an acceptance passed (`authority` in every view says so).
"""
from __future__ import annotations

from codex_harness.domain.host_migration import (
    FAILED,
    LIMITED_ACTIVE,
    PLANNED,
    RESTORED_PAUSED,
    REVERSE_STEPS,
    ROLLBACK_R1,
    ROLLBACK_REQUIRED,
    ROLLED_BACK,
    MigrationRefused,
    activation_id,
    activation_receipt,
    allowed,
    effective_activation,
    intent_id,
    manifest_digest,
    resume_state,
    reverse_maps,
    rollback_mode,
    step_allowed,
    successor_allowed,
    successor_id,
    transition_id,
    validate_checkpoint,
    validate_intent,
    validate_manifest,
    validate_successor,
    validate_transition,
)

BUCKET = "host_migrations"
BUCKET_TRANSITIONS = "host_migration_transitions"
BUCKET_CHECKPOINTS = "host_migration_checkpoints"
AUTHORITY = ("receipt recorder; a recorded state is not proof of source fencing, target activation, "
             "runtime consumption or live acceptance")
ACTIVATION_STATES = (RESTORED_PAUSED, LIMITED_ACTIVE, "qualified")


class HostMigrations:
    def __init__(self, store):
        self.store = store

    def plan(self, document) -> dict:
        manifest = validate_manifest(document)
        sha = manifest_digest(manifest)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, manifest["migration_id"])
            if row is not None:
                if row["manifest_sha256"] != sha:
                    raise MigrationRefused("manifest_conflict", "migration_id")
                return {**self._view(row), "cached": True}
            row = {"migration_id": manifest["migration_id"], "manifest": manifest, "manifest_sha256": sha,
                   "state": PLANNED, "history": [], "checkpoints": {}}
            tx.put(BUCKET, manifest["migration_id"], row)
        return {**self._view(row), "cached": False}

    def status(self, migration_id: str) -> dict:
        return self._view(self._row(migration_id))

    def manifest(self, migration_id: str) -> dict:
        return self._row(migration_id)["manifest"]

    def advance(self, document) -> dict:
        transition = validate_transition(document)
        key = transition_id(transition)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, transition["migration_id"])
            if row is None:
                raise MigrationRefused("migration_unknown", "migration_id")
            recorded = tx.get(BUCKET_TRANSITIONS, key)
            if recorded is not None:
                if recorded != transition:
                    raise MigrationRefused("transition_conflict", "transition")
                return {**self._view(row), "cached": True}
            if transition["manifest_sha256"] != row["manifest_sha256"]:
                raise MigrationRefused("manifest_stale", "manifest_sha256")
            if transition["from"] != row["state"]:
                raise MigrationRefused("state_stale", "from")
            resumable = row["state"] == FAILED and transition["to"] == resume_state(row["history"])
            if not (allowed(row["state"], transition["to"]) or resumable):
                raise MigrationRefused("transition_not_allowed", "to")
            if transition["to"] == LIMITED_ACTIVE:
                self._require_activation(row, transition)
            if transition["to"] == ROLLED_BACK:
                self._require_rollback(row, transition)
            tx.put(BUCKET_TRANSITIONS, key, transition)
            row["history"].append({"id": key, "from": transition["from"], "to": transition["to"],
                                   "at": transition["at"], "actor": transition["actor"],
                                   "host": transition["host"], "reason_code": transition["reason_code"]})
            row["state"] = transition["to"]
            tx.put(BUCKET, row["migration_id"], row)
        return {**self._view(row), "cached": False}

    @staticmethod
    def _require_activation(row: dict, transition: dict) -> None:
        """The target writer may be recorded active only against the EFFECTIVE activation that
        enabled it: after a successor, receipts bound to the superseded intent are refused."""
        intent = row.get("activation_intent")
        if intent is None:
            raise MigrationRefused("activation_intent_missing", "activation_intent")
        head = effective_activation(intent, row.get("activation_successors") or [])
        activation, key = head["activation"], head["id"]
        if any(receipt["subject"] != key for receipt in transition["evidence"]["host_activation"]):
            raise MigrationRefused("activation_receipt_unbound", "evidence.host_activation")
        consumed = "revision=" + activation["release_revision"]
        if any(receipt["subject"] != consumed for receipt in transition["evidence"]["service_consumption"]):
            # `systemctl is-active` is not consumption: the startup receipt must name the revision.
            raise MigrationRefused("service_consumption_unbound", "evidence.service_consumption")
        identity = transition["identity"]
        if (identity["commit"], identity["image"], identity["profile_sha256"]) != \
                (activation["release_revision"], activation["image"], activation["profile_sha256"]):
            raise MigrationRefused("activation_identity_mismatch", "identity")

    @staticmethod
    def _require_rollback(row: dict, transition: dict) -> None:
        mode = rollback_mode(row["history"])
        wanted = "gate-r1" if mode == ROLLBACK_R1 else "gate-r0"
        if any(receipt["check"] != wanted for receipt in transition["evidence"]["rollback_gate"]):
            raise MigrationRefused("rollback_gate_mode", "evidence.rollback_gate")
        if mode == ROLLBACK_R1:
            missing = [step for step in REVERSE_STEPS if step not in row["checkpoints"]]
            if missing:
                raise MigrationRefused("reverse_step_missing", missing[0])

    def intend_activation(self, document) -> dict:
        """Record the activation intent before any target writer exists; idempotent, CAS on state."""
        intent = validate_intent(document)
        key = intent_id(intent)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, intent["migration_id"])
            if row is None:
                raise MigrationRefused("migration_unknown", "migration_id")
            existing = row.get("activation_intent")
            if existing is not None:
                if intent_id(existing) != key:
                    raise MigrationRefused("activation_intent_conflict", "activation_intent")
                return {"recorded": False, "cached": True, "intent_id": key}
            if row["state"] != RESTORED_PAUSED:
                raise MigrationRefused("activation_state", "state")
            row["activation_intent"] = intent
            row["history"].append({"event": "activation_intent", "intent_id": key, "at": intent["at"],
                                   "actor": intent["actor"]})
            tx.put(BUCKET, row["migration_id"], row)
        return {"recorded": True, "cached": False, "intent_id": key}

    def record_successor(self, document) -> dict:
        """Record a successor of the effective activation; CAS on the exact predecessor.

        One store transaction under the coordinator lock. The identical successor replays; a
        second successor of the same predecessor conflicts and a successor of a superseded head is
        stale. The intent, state, manifest, transitions and checkpoints are never touched.
        """
        successor = validate_successor(document)
        key = successor_id(successor)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, successor["migration_id"])
            if row is None:
                raise MigrationRefused("migration_unknown", "migration_id")
            intent = row.get("activation_intent")
            if intent is None:
                raise MigrationRefused("activation_intent_missing", "activation_intent")
            successors = row.get("activation_successors") or []
            if any(successor_id(existing) == key for existing in successors):
                return {"recorded": False, "cached": True, "successor_id": key,
                        "predecessor_id": successor["predecessor_id"]}
            if row["state"] != RESTORED_PAUSED:
                raise MigrationRefused("activation_state", "state")
            chain = [intent, *successors]
            if any(activation_id(existing) == successor["predecessor_id"] for existing in chain[:-1]):
                # Exactly one successor per head: this predecessor already has one.
                raise MigrationRefused("activation_successor_conflict", "predecessor_id")
            head = effective_activation(intent, successors)
            if successor["predecessor_id"] != head["id"]:
                raise MigrationRefused("activation_predecessor_stale", "predecessor_id")
            successor_allowed(head["activation"], successor)
            row["activation_successors"] = [*successors, successor]
            row["history"].append({"event": "activation_successor", "successor_id": key,
                                   "predecessor_id": successor["predecessor_id"],
                                   "release_revision": successor["release_revision"],
                                   "at": successor["at"], "actor": successor["actor"]})
            tx.put(BUCKET, row["migration_id"], row)
        return {"recorded": True, "cached": False, "successor_id": key,
                "predecessor_id": successor["predecessor_id"]}

    def activation_document(self, migration_id: str) -> dict:
        """The launcher's `host-activation.json` for the current state, derived from the effective
        activation (the intent until a successor is recorded)."""
        return self._activation_plan(self._row(migration_id))["effective"]

    def activation_switch(self, migration_id: str, effect, *, expected_id: str | None = None):
        """Run the adapter's file `effect(plan)` while holding this coordinator's transaction.

        The effective head is selected, the caller's expected head is rechecked and the effect
        classifies and writes the launcher files, all inside ONE store transaction: the same
        advisory lock `record_successor` takes. A successor recorded meanwhile, or a second
        switch, cannot run between the head selection and the writes: it waits for this
        transaction and then sees the files it left. The coordinator itself still touches no file:
        `effect` is the adapter's port and is given pure data only.

        The wait is bounded on PostgreSQL. `PostgresStore.transaction` sets `lock_timeout = '10s'`
        before `pg_advisory_xact_lock(734219)`, so a transaction on another connection waits at most
        10 s for the lock, then fails with `LockNotAvailable` having written nothing: it is refused,
        never interleaved, and it is not retried here. The timeout bounds only the waiter, not this
        effect. The lock is database-wide, so every other store writer of that database waits the
        same way. `MemoryStore` waits without a bound. `effect` must not open another store
        transaction: that is a new connection, which would wait on the lock this one holds (a
        repeated request inside the same session would succeed; a second connection does not).
        """
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, migration_id)
            if row is None:
                raise MigrationRefused("migration_unknown", "migration_id")
            plan = self._activation_plan(row)
            if expected_id is not None and expected_id != plan["effective_id"]:
                raise MigrationRefused("activation_head_moved", "expected_id")
            return effect(plan)

    @staticmethod
    def _activation_plan(row: dict) -> dict:
        intent = row.get("activation_intent")
        if intent is None:
            raise MigrationRefused("activation_intent_missing", "activation_intent")
        if row["state"] not in ACTIVATION_STATES:
            # A failed or rolling-back migration never re-issues an activation; the host is fenced.
            raise MigrationRefused("activation_state", "state")
        head = effective_activation(intent, row.get("activation_successors") or [])
        predecessor = head["predecessor"]
        return {"migration_id": row["migration_id"], "effective_id": head["id"], "kind": head["kind"],
                "effective": activation_receipt(head["activation"], row["manifest_sha256"], row["state"]),
                "predecessor": None if predecessor is None
                else activation_receipt(predecessor, row["manifest_sha256"], row["state"])}

    def checkpoint(self, document) -> dict:
        checkpoint = validate_checkpoint(document)
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, checkpoint["migration_id"])
            if row is None:
                raise MigrationRefused("migration_unknown", "migration_id")
            existing = row["checkpoints"].get(checkpoint["step"])
            if existing is not None:
                if existing["input_sha256"] != checkpoint["input_sha256"]:
                    # The step already ran over another snapshot; restoring again would mix two.
                    raise MigrationRefused("checkpoint_conflict", "input_sha256")
                if existing["output_sha256"] != checkpoint["output_sha256"]:
                    raise MigrationRefused("checkpoint_output_conflict", "output_sha256")
                return {"recorded": False, "cached": True, "checkpoint": existing}
            if not step_allowed(checkpoint["step"], row["state"], row["history"]):
                raise MigrationRefused("step_not_allowed", "step")
            row["checkpoints"][checkpoint["step"]] = checkpoint
            tx.put(BUCKET_CHECKPOINTS, checkpoint["migration_id"] + ":" + checkpoint["step"], checkpoint)
            tx.put(BUCKET, row["migration_id"], row)
        return {"recorded": True, "cached": False, "checkpoint": checkpoint}

    def completed_step(self, migration_id: str, step: str, input_sha256: str) -> dict | None:
        """The recorded checkpoint of this step over this input, for a resuming adapter to skip."""
        existing = self._row(migration_id)["checkpoints"].get(step)
        if existing is None:
            return None
        if existing["input_sha256"] != input_sha256:
            raise MigrationRefused("checkpoint_conflict", "input_sha256")
        return existing

    def rollback_plan(self, migration_id: str) -> dict:
        """What a rollback of this migration must be, decided from its own recorded history."""
        row = self._row(migration_id)
        mode = rollback_mode(row["history"])
        plan = {"migration_id": migration_id, "state": row["state"], "mode": mode,
                "rollback_required": row["state"] == ROLLBACK_REQUIRED}
        if mode == ROLLBACK_R1:
            plan["reverse"] = reverse_maps(row["manifest"])
            plan["forbidden"] = ["restart_source_from_original_snapshot"]
            plan["steps"] = list(REVERSE_STEPS)
            plan["completed"] = [step for step in REVERSE_STEPS if step in row["checkpoints"]]
            plan["gate"] = "gate-r1"
        else:
            plan["steps"] = []
            plan["gate"] = "gate-r0"
        return plan

    def _row(self, migration_id: str) -> dict:
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, migration_id)
        if row is None:
            raise MigrationRefused("migration_unknown", "migration_id")
        return row

    @staticmethod
    def _view(row: dict) -> dict:
        return {"migration_id": row["migration_id"], "manifest_sha256": row["manifest_sha256"],
                "state": row["state"], "transitions": len(row["history"]),
                "history": list(row["history"]), "checkpoints": sorted(row["checkpoints"]),
                "rollback_mode": rollback_mode(row["history"]),
                "activation_intent": None if row.get("activation_intent") is None
                else intent_id(row["activation_intent"]),
                **HostMigrations._chain_view(row),
                "authority": AUTHORITY}

    @staticmethod
    def _chain_view(row: dict) -> dict:
        """`activation_intent` stays the original id; the effective head and chain are shown beside
        it so the original is never confused with what the receipt currently names."""
        intent = row.get("activation_intent")
        if intent is None:
            return {"activation_current": None, "activation_chain": []}
        chain = [intent, *(row.get("activation_successors") or [])]
        return {"activation_current": activation_id(chain[-1]),
                "activation_chain": [{"id": activation_id(item), "release_revision": item["release_revision"],
                                      "kind": "successor" if index else "intent",
                                      "predecessor_id": item.get("predecessor_id")}
                                     for index, item in enumerate(chain)]}


__all__ = ["BUCKET", "BUCKET_CHECKPOINTS", "BUCKET_TRANSITIONS", "HostMigrations"]

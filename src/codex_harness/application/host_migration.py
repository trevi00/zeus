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
"""
from __future__ import annotations

from codex_harness.domain.host_migration import (
    FAILED,
    PLANNED,
    ROLLBACK_REQUIRED,
    MigrationRefused,
    allowed,
    manifest_digest,
    resume_state,
    reverse_maps,
    rollback_mode,
    step_allowed,
    transition_id,
    validate_checkpoint,
    validate_manifest,
    validate_transition,
)

BUCKET = "host_migrations"
BUCKET_TRANSITIONS = "host_migration_transitions"
BUCKET_CHECKPOINTS = "host_migration_checkpoints"


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
            tx.put(BUCKET_TRANSITIONS, key, transition)
            row["history"].append({"id": key, "from": transition["from"], "to": transition["to"],
                                   "at": transition["at"], "actor": transition["actor"],
                                   "host": transition["host"], "reason_code": transition["reason_code"]})
            row["state"] = transition["to"]
            tx.put(BUCKET, row["migration_id"], row)
        return {**self._view(row), "cached": False}

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
        if mode == "R1":
            plan["reverse"] = reverse_maps(row["manifest"])
            plan["forbidden"] = ["restart_source_from_original_snapshot"]
            plan["steps"] = ["reverse_pg_restore", "reverse_redis_restore", "reverse_artifact_copy"]
        else:
            plan["steps"] = []
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
                "rollback_mode": rollback_mode(row["history"])}


__all__ = ["BUCKET", "BUCKET_CHECKPOINTS", "BUCKET_TRANSITIONS", "HostMigrations"]

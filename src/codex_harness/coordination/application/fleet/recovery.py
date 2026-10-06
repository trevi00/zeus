"""Owner recovery of an interrupted Fleet job, lane relocation and host migration, each on a re-read
cross-store observation with an immutable receipt.

Layer: application
Context: coordination
Owns: buckets fleet_recovery_receipts, fleet_relocations, fleet_host_migrations, and the
fleet_registry config rebind and fleet_jobs interrupted_unknown settlement they commit
Does not own: the host observation collectors (S7 adapters)
Entry points: FleetRecovery.reconcile_interrupted, .recovery, .relocate, .migrate_host, .relocations
Contracts: INV-FLEET-001, INV-HOST-MIGRATION-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import (
    BUCKET_HOST_MIGRATION,
    BUCKET_JOBS,
    BUCKET_RECOVERY,
    BUCKET_REGISTRY,
    BUCKET_RELOCATION,
    BUCKET_UNITS,
)
from codex_harness.coordination.domain.fleet import (
    FAILED,
    QUEUED,
    RESERVING,
    FleetRefused,
    held_units,
    sanitized_config,
)
from codex_harness.coordination.domain.fleet_recovery import (
    INTERRUPTED,
    check_host_migration_proof,
    check_recovery_proof,
    check_relocation_proof,
    host_migrated_config,
    host_migration_receipt,
    host_migration_receipt_id,
    host_migration_view,
    proof_binding,
    recovery_receipt,
    recovery_receipt_id,
    recovery_view,
    relocated_config,
    relocation_receipt,
    relocation_receipt_id,
    relocation_view,
    validate_host_migration_request,
    validate_recovery_evidence,
    validate_relocation_request,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow


class FleetRecovery:
    """Owner recovery, relocation and host migration (M7 `Fleet`, recovery part)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    def _recovery_replay(self, document: dict) -> dict | None:
        """The committed answer for this evidence, read BEFORE anything is observed.

        A recovery that already committed is finished: its receipt is the durable fact, and asking
        Docker, the lane store or the machine ledger about a container, a schema or a slot that has
        since been removed would turn a settled job into a refusal. Identical evidence therefore
        replays from the receipt alone; any other evidence for that job still conflicts here.
        """
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_RECOVERY, document["job_id"])
            if old is None:
                return None
            if old["evidence"] != document:
                raise FleetRefused("recovery_conflict")
            return {"reconciled": True, "cached": True, "receipt": recovery_view(old),
                    "job": state.view(tx.get(BUCKET_JOBS, document["job_id"]) or {})}

    def reconcile_interrupted(self, evidence, proof=None, *, observe=None, reread=None) -> dict:
        """Settle ONE interrupted job whose external effects the owner proved dead (trusted CLI).

        The committed receipt is consulted first: an identical replay is answered from it without
        observing anything, so a vanished container or an unreachable lane store cannot withdraw a
        recovery that already happened, and a conflicting document for the same job refuses just as
        early. Only when no receipt exists is the observation taken - supply it as `proof`, or as
        `observe()` for a caller that must not pay for it on a replay.

        The fleet must be paused, the registered configuration must still be the one the evidence
        names, and the job must still be the exact reservation it names (status, owner token,
        lane, operation id). `proof` is the adapter's cross-store observation; `reread()` is the
        same observation taken again inside this transaction, directly before the write, so a
        container, reservation or task that changed in between refuses instead of committing. That
        re-read is an owner-controlled recovery step with the worker services stopped, not a
        distributed atomic transaction, and the receipt says so; it does cross-store reads while
        this transaction is open, which is accepted because this is a paused, owner-only operation
        that runs once, never on the dispatcher's path.

        The job becomes terminal `failed` with the fixed `interrupted_unknown` reason, which clears
        that one reservation. Nothing is retried, resumed, relaunched or credited: the frozen
        manifest, goal, dependencies, exit code and call counts stay exactly as they were and the
        unknown usage stays unknown. The identical evidence replays idempotently; any other
        evidence for the same job is refused and nothing is overwritten.
        """
        document = validate_recovery_evidence(evidence)
        require(proof is not None or observe is not None, "Fleet recovery needs an observation")
        replay = self._recovery_replay(document)
        if replay is not None:
            return replay
        if proof is None:
            proof = observe()
        check_recovery_proof(document, proof)
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_RECOVERY, document["job_id"])
            if old is not None:
                # A second owner committed between the read above and this transaction; the
                # reservation is already cleared, so the durable receipt is still the answer.
                if old["evidence"] != document:
                    raise FleetRefused("recovery_conflict")
                return {"reconciled": True, "cached": True, "receipt": recovery_view(old),
                        "job": state.view(tx.get(BUCKET_JOBS, document["job_id"]) or {})}
            if not bool(state.control(tx).get("paused")):
                raise FleetRefused("fleet_not_paused")
            if registry["config_sha256"] != document["expected"]["config_sha256"]:
                raise FleetRefused("config_expected_mismatch", "expected.config_sha256")
            job = tx.get(BUCKET_JOBS, document["job_id"])
            if job is None:
                raise FleetRefused("job_unknown")
            if job["status"] not in RESERVING or job["status"] != document["expected"]["status"]:
                raise FleetRefused("job_not_interrupted", "expected.status")
            if not job.get("owner_token") or job["owner_token"] != document["expected"]["owner_token"]:
                raise FleetRefused("owner_mismatch", "expected.owner_token")
            if job["lane"] != document["expected"]["lane"]:
                raise FleetRefused("lane_mismatch", "expected.lane")
            if job["operation_id"] != document["lane_operation"]["id"]:
                raise FleetRefused("operation_mismatch", "lane_operation.id")
            fresh = proof if reread is None else reread()
            check_recovery_proof(document, fresh)
            if proof_binding(fresh) != proof_binding(proof):
                raise FleetRefused("proof_changed")
            now = self.clock()
            receipt = recovery_receipt(document, fresh, registry["id"], registry["config_sha256"], now)
            require(recovery_receipt_id(document) == receipt["id"], "Fleet recovery receipt identity mismatch")
            tx.put(BUCKET_RECOVERY, document["job_id"], receipt)
            job.update(status=FAILED, reason_code=INTERRUPTED, owner_token=None, updated_at=now,
                       finished_at=now, recovery={"receipt_id": receipt["id"], "operator": document["operator"],
                                                  "recorded_at": now})
            tx.put(BUCKET_JOBS, job["id"], job)
        return {"reconciled": True, "cached": False, "receipt": recovery_view(receipt), "job": state.view(job)}

    def recovery(self, job_id: str) -> dict | None:
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_RECOVERY, job_id)
        return recovery_view(row) if row is not None else None

    def _relocation_replay(self, document: dict) -> dict | None:
        """The committed answer for this exact request, read BEFORE anything is observed.

        A relocation that already committed is finished, and the old source paths it moved away
        from may well be gone; re-observing them would refuse a request the registry has already
        satisfied. The identical request therefore replays from its receipt, and a different
        request against the same expected digest conflicts here rather than after a host read.
        """
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_RELOCATION, relocation_receipt_id(document))
            if old is not None:
                return {"relocated": True, "cached": True, "receipt": relocation_view(old),
                        "config": sanitized_config(registry["config"]),
                        "config_sha256": registry["config_sha256"]}
            if any(row["request"]["expected_config_sha256"] == document["expected_config_sha256"]
                   for row in tx.scan(BUCKET_RELOCATION)):
                raise FleetRefused("relocation_conflict")
            return None

    def relocate(self, request, proof=None, *, observe=None, reread=None) -> dict:
        """Move lane repository and runtime PATHS to already-copied targets (trusted owner CLI).

        The committed receipt is consulted first: the identical request replays from it without
        observing the host, and a conflicting request against the same expected digest refuses
        there. Only when neither applies is the observation taken - supply it as `proof`, or as
        `observe()` for a caller that must not pay for it on a replay.

        One transaction, compare-and-swap on the registered configuration digest: the fleet must be
        paused, hold no dispatching or unknown reservation, and the adapter's host observation must
        show the runner stopped, no active lane run, verified copied evidence and target checkouts
        that carry every queued job's pinned base and goal. Only the stated paths change; the lane
        id, team, schema, Redis namespace, concurrency, budget and provider authority are compared
        and must be identical.

        Frozen job rows, manifests, goals, operation identities and delivery or recovery receipts
        are never rewritten: the immutable relocation receipt keeps the prior configuration and its
        digest, and admission resolves the old repository identities through it. The identical
        request replays idempotently; a different request against the same expected digest is
        refused.
        """
        document = validate_relocation_request(request)
        require(proof is not None or observe is not None, "Fleet relocation needs an observation")
        replay = self._relocation_replay(document)
        if replay is not None:
            return replay
        if proof is None:
            proof = observe()
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            receipt_id = relocation_receipt_id(document)
            old = tx.get(BUCKET_RELOCATION, receipt_id)
            if old is not None:
                return {"relocated": True, "cached": True, "receipt": relocation_view(old),
                        "config": sanitized_config(registry["config"]), "config_sha256": registry["config_sha256"]}
            if any(row["expected_config_sha256"] == document["expected_config_sha256"]
                   for row in (r["request"] for r in tx.scan(BUCKET_RELOCATION))):
                raise FleetRefused("relocation_conflict")
            if registry["id"] != document["fleet"]:
                raise FleetRefused("fleet_mismatch", "fleet")
            if not bool(state.control(tx).get("paused")):
                raise FleetRefused("fleet_not_paused")
            if registry["config_sha256"] != document["expected_config_sha256"]:
                raise FleetRefused("config_expected_mismatch", "expected_config_sha256")
            jobs = tx.scan(BUCKET_JOBS)
            if any(row["status"] in RESERVING for row in jobs) or held_units(tx.scan(BUCKET_UNITS)):
                raise FleetRefused("fleet_not_idle")
            new = relocated_config(registry["config"], document)
            queued = {move["lane"]: sorted(row["id"] for row in jobs
                                           if row["status"] == QUEUED and row["lane"] == move["lane"])
                      for move in document["moves"]}
            check_relocation_proof(document, proof, queued)
            fresh = proof if reread is None else reread()
            check_relocation_proof(document, fresh, queued)
            if proof_binding(fresh) != proof_binding(proof):
                raise FleetRefused("proof_changed")
            now = self.clock()
            receipt = relocation_receipt(document, fresh, registry, new, now)
            tx.put(BUCKET_RELOCATION, receipt["id"], receipt)
            # The registry row keeps its identity and registration time; only the lane paths and the
            # digest that pins them move, and the prior pair lives on in the immutable receipt.
            tx.put(BUCKET_REGISTRY, registry["id"], {**registry, "config": new,
                                                     "config_sha256": receipt["config_sha256"],
                                                     "relocated_at": now, "relocation_id": receipt["id"]})
        return {"relocated": True, "cached": False, "receipt": relocation_view(receipt),
                "config": sanitized_config(new), "config_sha256": receipt["config_sha256"]}

    def migrate_host(self, request, proof=None, *, observe=None, reread=None) -> dict:
        """Rebind EVERY lane's repository, runtime and schema to the target host (trusted owner CLI).

        INV-HOST-MIGRATION-001: the restored registry of the source moves to the target host's
        paths and renamed schemas. The same guards as `relocate` apply - paused fleet, nothing
        dispatching or held, compare-and-swap on the registered digest, the observation taken
        twice and compared - with a target-host proof: the checkout is the source repository by
        root commits, queued jobs' bases are present, runtimes are writable and every target
        schema is provisioned. Lane/team ids and Redis namespaces stay. Frozen job rows,
        manifests and history keep their original paths; the receipt keeps the prior config and
        its digest, and admission resolves old repository identities through its aliases.
        """
        document = validate_host_migration_request(request)
        require(proof is not None or observe is not None, "Fleet host migration needs an observation")
        receipt_id = host_migration_receipt_id(document)
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_HOST_MIGRATION, receipt_id)
            if old is not None:
                return {"migrated": True, "cached": True, "receipt": host_migration_view(old),
                        "config_sha256": old["config_sha256"]}
            if any(row["request"]["expected_config_sha256"] == document["expected_config_sha256"]
                   for row in tx.scan(BUCKET_HOST_MIGRATION)):
                raise FleetRefused("host_migration_conflict")
        if proof is None:
            proof = observe()
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if tx.get(BUCKET_HOST_MIGRATION, receipt_id) is not None:
                raise FleetRefused("host_migration_conflict")
            if registry["id"] != document["fleet"]:
                raise FleetRefused("fleet_mismatch", "fleet")
            if not bool(state.control(tx).get("paused")):
                raise FleetRefused("fleet_not_paused")
            if registry["config_sha256"] != document["expected_config_sha256"]:
                raise FleetRefused("config_expected_mismatch", "expected_config_sha256")
            jobs = tx.scan(BUCKET_JOBS)
            if any(row["status"] in RESERVING for row in jobs) or held_units(tx.scan(BUCKET_UNITS)):
                raise FleetRefused("fleet_not_idle")
            new = host_migrated_config(registry["config"], document)
            queued = {row["lane"]: sorted(job["id"] for job in jobs
                                          if job["status"] == QUEUED and job["lane"] == row["lane"])
                      for row in document["lanes"]}
            check_host_migration_proof(document, proof, queued)
            fresh = proof if reread is None else reread()
            check_host_migration_proof(document, fresh, queued)
            if proof_binding(fresh) != proof_binding(proof):
                raise FleetRefused("proof_changed")
            now = self.clock()
            receipt = host_migration_receipt(document, fresh, registry, new, now)
            tx.put(BUCKET_HOST_MIGRATION, receipt["id"], receipt)
            tx.put(BUCKET_REGISTRY, registry["id"], {**registry, "config": new,
                                                     "config_sha256": receipt["config_sha256"],
                                                     "host_migrated_at": now, "host_migration_id": receipt["id"]})
        return {"migrated": True, "cached": False, "receipt": host_migration_view(receipt),
                "config": sanitized_config(new), "config_sha256": receipt["config_sha256"]}

    def relocations(self) -> list[dict]:
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_RELOCATION)
        return [relocation_view(row) for row in sorted(rows, key=lambda r: (r["recorded_at"], r["id"]))]

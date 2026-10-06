"""The Fleet registry: registration, job enqueue, owner delivery records and the status projection.

Layer: application
Context: coordination
Owns: buckets fleet_registry (registration), fleet_jobs (enqueue), fleet_delivery
Does not own: admission and finalization (fleet.admission), pause and grants (fleet.pause), owner recovery (fleet.recovery)
Entry points: FleetRegistry.register, .registered, .enqueue, .record_delivery, .delivery, .reconciliation_required, .status
Contracts: INV-FLEET-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import (
    BUCKET_CONTROL,
    BUCKET_DELIVERY,
    BUCKET_JOBS,
    BUCKET_MAINTENANCE,
    BUCKET_REGISTRY,
    CONTROL_KEY,
)
from codex_harness.coordination.domain.fleet import (
    ACCEPTED,
    RESERVING,
    FleetRefused,
    binding,
    config_digest,
    delivery_view,
    effective_config,
    lane_of,
    new_job,
    projection,
    sanitized_config,
    validate_config,
    validate_delivery,
    validate_job_manifest,
)
from codex_harness.coordination.domain.fleet_maintenance import permit_view
from codex_harness.coordination.domain.operation import manifest_digest
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow


class FleetRegistry:
    """The fleet registration, its jobs and their delivery records (M7 `Fleet`, registry part)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    def register(self, document) -> dict:
        """Idempotent for the identical canonical configuration; any other configuration while
        one is registered is refused (no mutation, no replacement, no second fleet)."""
        config = validate_config(document)
        sha = config_digest(config)
        with self.store.transaction() as tx:
            existing = state.registry(tx)
            if existing is not None:
                if existing["config_sha256"] == sha:
                    return {"registered": True, "cached": True, "id": existing["id"],
                            "config_sha256": sha, "config": sanitized_config(existing["config"])}
                raise FleetRefused("registration_conflict")
            row = {"id": config["id"], "schema": config["schema"], "config_sha256": sha, "config": config,
                   "registered_at": self.clock()}
            tx.put(BUCKET_REGISTRY, config["id"], row)
            if tx.get(BUCKET_CONTROL, CONTROL_KEY) is None:
                tx.put(BUCKET_CONTROL, CONTROL_KEY, {"paused": False, "budget": dict(config["budget"]),
                                                     "updated_at": self.clock()})
        return {"registered": True, "cached": False, "id": config["id"], "config_sha256": sha,
                "config": sanitized_config(config)}

    def registered(self) -> dict:
        """The registry row with `config` carrying the effective ceilings (a grant replaces the
        registered budget for new work); `config_sha256` stays the original registration digest."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            control = state.control(tx)
        if registry is None:
            raise FleetRefused("unregistered")
        return {**registry, "config": effective_config(registry["config"], control)}

    # ----- enqueue ------------------------------------------------------------------------
    def enqueue(self, lane_id: str, manifest: dict, goal: dict, dependencies) -> dict:
        """`manifest` is the canonical validated operation manifest and `goal` its binding at the
        lane repository's base (both produced by the existing operate adapter)."""
        dependencies = list(dependencies or [])
        require(all(type(d) is str and d for d in dependencies) and len(set(dependencies)) == len(dependencies),
                "Fleet dependencies must be distinct job ids")
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            config = effective_config(registry["config"], state.control(tx))
            lane = lane_of(config, lane_id)
            validate_job_manifest(manifest, config)  # the effective ceilings, never a stale budget
            job = new_job(manifest, manifest_digest(manifest), lane, goal, dependencies, self.clock())
            if job["id"] in dependencies:
                raise FleetRefused("dependency_self")
            for dependency in dependencies:
                if tx.get(BUCKET_JOBS, dependency) is None:
                    raise FleetRefused("dependency_missing")
            old = tx.get(BUCKET_JOBS, job["id"])
            if old is not None:
                if binding(old) != binding(job):
                    raise FleetRefused("binding_conflict")
                return {"job": state.view(old), "cached": True}
            tx.put(BUCKET_JOBS, job["id"], job)
        return {"job": state.view(job), "cached": False}

    # ----- owner delivery records ---------------------------------------------------------
    def record_delivery(self, job_id: str, document) -> dict:
        """Record one immutable owner-reported delivery for an ACCEPTED job (trusted owner CLI only).

        The complete document replays idempotently; any other document for the same job is refused
        and nothing is overwritten. No web request and no model run reaches this method. The job's
        status, review verdict and authority are untouched: this record is delivery VISIBILITY, not
        a release approval gate, and it is not an independent GitHub or network verification.
        """
        record = validate_delivery(document)
        if record["job_id"] != job_id:
            raise FleetRefused("delivery_job_mismatch", "job_id")
        with self.store.transaction() as tx:
            job = tx.get(BUCKET_JOBS, job_id)
            if job is None:
                raise FleetRefused("job_unknown")
            if job["status"] != ACCEPTED:
                raise FleetRefused("job_not_accepted")
            old = tx.get(BUCKET_DELIVERY, job_id)
            if old is not None:
                if old["document"] != record:
                    raise FleetRefused("delivery_conflict")
                return {"recorded": True, "cached": True, "delivery": delivery_view(old)}
            row = {"id": job_id, "job_id": job_id, "document": record, "source": "owner_cli",
                   "authority": "owner_recorded", "recorded_by": "owner", "created_at": self.clock()}
            tx.put(BUCKET_DELIVERY, job_id, row)
        return {"recorded": True, "cached": False, "delivery": delivery_view(row)}

    def delivery(self, job_id: str) -> dict | None:
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_DELIVERY, job_id)
        return delivery_view(row) if row is not None else None

    # ----- read-only ----------------------------------------------------------------------
    def reconciliation_required(self) -> list[str]:
        """Dispatching/unknown jobs: never relaunched, never cleared by an operator command here."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_JOBS)
        return sorted(row["id"] for row in rows if row["status"] in RESERVING)

    def status(self) -> dict:
        """The `urn:zeus:fleet-status:1` projection from PG reads only.

        A job with an owner delivery record carries its safe `delivery` projection; a job without
        one is unchanged, and its delivery stays unknown."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            control = state.control(tx)
            rows = tx.scan(BUCKET_JOBS)
            deliveries = {row["job_id"]: row for row in tx.scan(BUCKET_DELIVERY)}
            permits = tx.scan(BUCKET_MAINTENANCE)
        if registry is not None:
            registry = {**registry, "config": effective_config(registry["config"], control)}
        view = projection(registry, bool(control.get("paused")), rows, deliveries)
        # A job whose lane operation was refused on evidence carries its already-safe counts-only
        # handoff here too, so `pending_owner` is visible in the status a reader actually polls. A
        # job without one keeps its exact previous shape.
        handoffs = {row["id"]: row.get("owner_handoff") for row in rows if row.get("owner_handoff")}
        view = {**view, "jobs": [job if job["id"] not in handoffs else {**job, "owner_handoff": handoffs[job["id"]]}
                                 for job in view["jobs"]]}
        if permits:
            # INV-FLEET-001 maintenance amendment: permits are visible (safe view, never an owner
            # token); a fleet that never held one keeps its exact previous status shape.
            view["maintenance"] = [permit_view(row) for row in sorted(
                permits, key=lambda r: (str(r.get("granted_at") or r.get("closed_at")), r["id"]))]
        return view

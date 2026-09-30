"""Admit at most one queued Fleet job per call under capacity, pause and budget gates; reserve and settle
shared execution units; record the dispatching owner's terminal fact.

Layer: application
Context: coordination
Owns: buckets fleet_jobs (dispatch, reasons, terminal), fleet_units
Does not own: job registry (fleet.registry), lane processes (the LaneLauncher port)
Entry points: AdmissionControl.admit_one, .reserve_unit, .settle_unit, .units, .held_units, .finalize
Contracts: INV-FLEET-001, INV-CONTINUATION-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS, BUCKET_UNITS, owner_handoff_view
from codex_harness.coordination.domain.fleet import (
    DISPATCHING,
    RESERVING,
    TERMINAL,
    UNIT_RELEASED,
    FleetRefused,
    check_unit_proof,
    effective_config,
    held_units,
    lane_of,
    new_unit,
    safe_code,
    select_admission,
    unit_binding,
    unit_view,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow


class AdmissionControl:
    """Serialized admission of Fleet jobs and shared execution units (M7 `Fleet`, admission part)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    def admit_one(self, budget_exhausted: bool = False) -> dict:
        """One transaction: choose the oldest admissible queued job and claim it as dispatching
        with a fresh owner token. Returns `job` None with the blocking reasons when nothing fits.
        Every observed reason (paused, budget_exhausted, budget_stale, capacity, lane_busy,
        dependency_*, path_conflict) is persisted on its queued job in this transaction; the row
        and its `updated_at` change only when the reason differs from the recorded one."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            config = effective_config(registry["config"], control)  # refreshed every admission
            jobs = {row["id"]: row for row in tx.scan(BUCKET_JOBS)}
            # Held execution units (a reserved, running or cleanup-unknown conductor) take the same
            # `max_parallel` slots, read in this same serialized transaction.
            decision = select_admission(config, bool(control.get("paused")), jobs, budget_exhausted,
                                        state.repository_aliases(tx), units=len(held_units(tx.scan(BUCKET_UNITS))))
            job = decision["job"]
            now = self.clock()
            if job is not None:
                job.update(status=DISPATCHING, owner_token=self.token(), dispatched_at=now, updated_at=now,
                           reason_code=None)
                tx.put(BUCKET_JOBS, job["id"], job)
            for job_id, reason in decision["blocked"].items():
                blocked = jobs[job_id]
                if blocked.get("reason_code") != reason:
                    blocked.update(reason_code=reason, updated_at=now)
                    tx.put(BUCKET_JOBS, job_id, blocked)
        return {**decision, "job": job}

    # ----- shared execution units: reserve before spawn, release only on exact proof ------
    def reserve_unit(self, unit_id: str, kind: str, lane_id: str, subject: str, *, within=None) -> dict:
        """Reserve one non-job execution unit (a conductor decision) BEFORE anything is spawned.

        One transaction under the same serialization as `admit_one` (PostgresStore's control advisory
        lock; MemoryStore's lock), so every controller and a standalone tick compete for the same
        `max_parallel` slots as worker jobs: reserving jobs plus held units must stay below it. A
        paused fleet reserves nothing. `within(tx, unit)` runs inside this transaction before the
        commit - the caller's write-ahead record (the `dispatched` intent carrying the unit's token)
        commits with the reservation or not at all. The same unit id replays its reservation
        (`cached`, `within` not run); a different binding under that id is `unit_conflict`."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_UNITS, unit_id)
            config = effective_config(registry["config"], state.control(tx))
            unit = new_unit(unit_id, kind, lane_of(config, lane_id), subject, self.token(), self.clock())
            if old is not None:
                if unit_binding(old) != unit_binding(unit):
                    raise FleetRefused("unit_conflict", "id")
                return {"unit": unit_view(old), "token": old["token"], "cached": True}
            if bool(state.control(tx).get("paused")):
                raise FleetRefused("paused")
            reserving = sum(1 for row in tx.scan(BUCKET_JOBS) if row["status"] in RESERVING)
            if reserving + len(held_units(tx.scan(BUCKET_UNITS))) >= config["max_parallel"]:
                raise FleetRefused("capacity")
            if within is not None:
                within(tx, dict(unit))
            tx.put(BUCKET_UNITS, unit_id, unit)
        return {"unit": unit_view(unit), "token": unit["token"], "cached": False}

    def settle_unit(self, unit_id: str, token: str, proof, *, within=None) -> dict:
        """Release one unit on its exact proof (`domain.fleet.check_unit_proof`), in one transaction
        with the caller's settlement write (`within(tx, unit)`, e.g. the intent leaving `dispatched`).

        The token must be the reservation's; the proof must name this unit id (and, for a cleanup
        receipt, this token) and confirm the parent AND the tree. A failed commit leaves the unit
        held and the local proof intact, so the next pass settles it exactly once; an identical
        replay after a lost response is `cached` (`within` not run); a different proof for a
        released unit is `settlement_conflict`."""
        with self.store.transaction() as tx:
            unit = tx.get(BUCKET_UNITS, unit_id)
            if unit is None:
                raise FleetRefused("unit_unknown")
            if not token or unit.get("token") != token:
                raise FleetRefused("owner_mismatch", "token")
            settlement = check_unit_proof(unit, proof)
            if unit["state"] == UNIT_RELEASED:
                if (unit.get("settlement") or {}).get("proof_sha256") != settlement["proof_sha256"]:
                    raise FleetRefused("settlement_conflict")
                return {"unit": unit_view(unit), "cached": True}
            if within is not None:
                within(tx, dict(unit))
            now = self.clock()
            unit.update(state=UNIT_RELEASED, released_at=now, settlement=settlement)
            tx.put(BUCKET_UNITS, unit_id, unit)
        return {"unit": unit_view(unit), "cached": False}

    def units(self) -> list[dict]:
        """Every execution unit's safe view (no token), held ones first."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_UNITS)
        return [unit_view(row) for row in sorted(rows, key=lambda r: (r.get("state") == UNIT_RELEASED,
                                                                       str(r.get("reserved_at")), r["id"]))]

    def held_units(self) -> list[str]:
        """Units still consuming capacity: reserved, running or with unproven cleanup."""
        with self.store.transaction() as tx:
            return held_units(tx.scan(BUCKET_UNITS))

    def finalize(self, job_id: str, owner_token: str, outcome: dict) -> dict:
        """Only the dispatching owner records the terminal fact. `unknown` stays reserving."""
        status = outcome.get("status")
        require(status in TERMINAL, "Fleet outcome must be terminal")
        with self.store.transaction() as tx:
            job = tx.get(BUCKET_JOBS, job_id)
            if job is None:
                raise FleetRefused("job_unknown")
            if job["status"] != DISPATCHING:
                raise FleetRefused("not_dispatching")
            if not owner_token or job.get("owner_token") != owner_token:
                raise FleetRefused("owner_mismatch")
            now = self.clock()
            calls = outcome.get("calls") if isinstance(outcome.get("calls"), dict) else {}
            # INV-OPERATION-001: an evidence-refused lane operation hands its bounded owner request up
            # with the job, so `pending_owner` is visible here instead of looking like finished work.
            handoff = owner_handoff_view(outcome.get("owner_handoff"))
            job.update(status=status, reason_code=safe_code(outcome.get("reason_code")),
                       exit_code=outcome.get("exit_code") if type(outcome.get("exit_code")) is int else None,
                       calls={"reserved": calls.get("reserved"), "settled": calls.get("settled")},
                       owner_handoff=handoff,
                       receipt={"operation_status": outcome.get("operation_status"), "owner_handoff": handoff},
                       error_type=outcome.get("error_type") if isinstance(outcome.get("error_type"), str) else None,
                       updated_at=now, finished_at=now)
            tx.put(BUCKET_JOBS, job_id, job)
        return state.view(job)

"""The one-job maintenance permit of an active-generation maintenance: grant, admit, close and the permit/job reads
(INV-FLEET-001 maintenance amendment, INV-HOST-DELIVERY-MAINTENANCE-001).

Layer: application
Context: coordination
Owns: bucket fleet_maintenance_admissions (the permits), and the one claim of a permit's queued job in fleet_jobs
Does not own: ordinary admission (fleet.admission), pause, resume and holds (fleet.pause), launching the claimed job (fleet.runner)
Entry points: FleetMaintenance.grant_maintenance_canary, .admit_maintenance_canary, .close_maintenance_canary, .maintenance_permit, .job
Contracts: INV-FLEET-001, INV-HOST-DELIVERY-MAINTENANCE-001

Ported from PR-3 (`feat/host-delivery-maintain-pr3`, e6e15f00 `application/fleet.py`, M7 `Fleet` methods of the same
names); the method bodies are PR-3's. Each method is ONE control-store transaction and every refusal is a fixed
`FleetRefused` with nothing written. The Fleet stays owner-paused throughout: nothing here pauses, resumes or
releases a hold, and the ordinary dispatcher (`AdmissionControl.admit_one`, `reserve_unit`, `FleetRunner.run`) gains
no authority. The debt reads shared with `FleetPause` are `state.open_permits` and `state.maintenance_debt`.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.state import (
    ACTIVATION_HOLD,
    BUCKET_BACKLOG_PLANS,
    BUCKET_JOBS,
    BUCKET_MAINTENANCE,
    BUCKET_UNITS,
)
from codex_harness.coordination.domain.fleet import (
    DISPATCHING,
    FAILED,
    QUEUED,
    RESERVING,
    FleetRefused,
    effective_config,
    held_units,
    select_admission,
)
from codex_harness.coordination.domain.fleet_maintenance import (
    ADMITTED,
    CLOSE_REASONS,
    CLOSED,
    FORWARD_CANDIDATE,
    GRANTED,
    MAINTENANCE_EXPIRED,
    MAINTENANCE_ID,
    OWNER_ACTIONS_BUCKET,
    UNLAUNCHED_REASONS,
    check_backlog_item,
    check_canary_job,
    check_forward_job,
    check_owner_action,
    deadline_passed,
    kind_of,
    owner_action_matches,
    permit_view,
    validate_permit,
    validate_proof,
)
from codex_harness.kernel.ids import digest, utcnow


def claim_queued_job(tx, registry: dict, control: dict, job: dict, *, now: str, token, budget_exhausted: bool,
                     debt_code: str, refused_code: str) -> dict:
    """Claim exactly `job` as `dispatching` inside the caller's open transaction: the one claim shared by the PR-3
    maintenance permit and the FA admission permit (INV-FLEET-001, factored out of `admit_maintenance_canary`).

    No reserving job and no held execution unit may exist (`debt_code`). The ordinary selection then decides over a
    one-job candidate set with ONLY the pause lifted: budget, stale ceilings, capacity, lane, path and dependency
    blockers all still refuse (`refused_code`, the blocker as its field). The claim takes a fresh owner token exactly
    as `admit_one`. Every other queued job is neither read-modified nor written; a refusal writes nothing."""
    jobs = {other["id"]: other for other in tx.scan(BUCKET_JOBS)}
    units = held_units(tx.scan(BUCKET_UNITS))
    if units or any(other["status"] in RESERVING for other in jobs.values()):
        raise FleetRefused(debt_code, "fleet")
    config = effective_config(registry["config"], control)
    candidates = {job["id"]: job, **{key: other for key, other in jobs.items() if other["status"] != QUEUED}}
    # The ONLY exception to ordinary admission: `paused=False` for this one candidate.
    decision = select_admission(config, False, candidates, bool(budget_exhausted),
                                state.repository_aliases(tx), units=len(units))
    if decision["job"] is None or decision["job"]["id"] != job["id"]:
        raise FleetRefused(refused_code, decision["blocked"].get(job["id"], "capacity"))
    job.update(status=DISPATCHING, owner_token=token(), dispatched_at=now, updated_at=now, reason_code=None)
    tx.put(BUCKET_JOBS, job["id"], job)
    return job


def fail_unlaunched_job(tx, job: dict, reason: str, now: str, **marker) -> None:
    """The queued job becomes terminal `failed` with `reason` and `marker` recorded: nothing was ever claimed or
    spawned (shared by the PR-3 close and the FA close)."""
    job.update(status=FAILED, reason_code=reason, updated_at=now, finished_at=now, **marker)
    tx.put(BUCKET_JOBS, job["id"], job)


class FleetMaintenance:
    """The one-job canary and forward-candidate permits (PR-3 `Fleet`, maintenance part)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    @staticmethod
    def _owner_paused(control: dict) -> None:
        """An OWNER pause: paused, and not merely a managed runtime's activation hold."""
        if not (control.get("paused") is True and control.get(ACTIVATION_HOLD) is None):
            raise FleetRefused("maintenance_pause_required", "fleet")

    @staticmethod
    def _job_is_permits(permit: dict, action, job) -> bool:
        """The stored job belongs to this permit: the real owner action for a canary, the bound lane for a
        forward candidate (its digest already matched)."""
        if kind_of(permit) == FORWARD_CANDIDATE:
            return isinstance(job, dict) and job.get("lane") == permit["lane"]
        return owner_action_matches(permit, action)

    @staticmethod
    def _history(row: dict, new_state: str, now: str, reason: str | None) -> list:
        return list(row.get("history") or []) + [{"state": new_state, "at": now, "reason": reason}]

    def grant_maintenance_canary(self, permit) -> dict:
        """Record the one-job permit of one maintenance generation (lane request -> THIS grant -> lane
        acknowledgement, DN-4), before owner-actions can queue the job, so a stranded canary always
        has an open permit that blocks every ordinary resume.

        The Fleet must be owner-paused and the deadline fresh; another maintenance's unsettled permit
        conflicts. The same id replays `cached` in any state only for the identical permit digest; any
        other permit under that id is `maintenance_conflict`. It admits and launches nothing."""
        permit = validate_permit(permit)
        sha, mid = digest(permit), permit["maintenance_id"]
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            self._owner_paused(state.control(tx))
            now = self.clock()
            if deadline_passed(permit["deadline"], now):
                raise FleetRefused("maintenance_expired", "deadline")
            if kind_of(permit) == FORWARD_CANDIDATE:
                # G1-04c issuance gate: never while a maintenance generation (a canary permit) is open;
                # the owner registered the item before this permit, and nothing of maintenance is touched.
                open_ids = state.open_permits(tx)
                if any(kind_of(tx.get(BUCKET_MAINTENANCE, other)["permit"]) != FORWARD_CANDIDATE
                       for other in open_ids):
                    raise FleetRefused("maintenance_open", "maintenance")
                check_backlog_item(permit, tx.scan(BUCKET_BACKLOG_PLANS), "maintenance_invalid")
            if any(other != mid for other in state.open_permits(tx)):
                raise FleetRefused("maintenance_conflict", "maintenance_id")
            old = tx.get(BUCKET_MAINTENANCE, mid)
            if old is not None:
                if old["permit_sha256"] != sha:
                    raise FleetRefused("maintenance_conflict", "permit")
                return {"granted": True, "cached": True, "maintenance_id": mid, "permit_sha256": sha,
                        "state": old["state"]}
            row = {"id": mid, "maintenance_id": mid, "permit": permit, "permit_sha256": sha, "state": GRANTED,
                   "granted_at": now, "lane": None, "manifest_sha256": None, "owner_token": None,
                   "admitted_at": None, "lane_ack": None, "closed_at": None, "close_reason": None,
                   "job_status": None, "launched": None, "history": [{"state": GRANTED, "at": now, "reason": None}]}
            tx.put(BUCKET_MAINTENANCE, mid, row)
        return {"granted": True, "cached": False, "maintenance_id": mid, "permit_sha256": sha, "state": GRANTED}

    def admit_maintenance_canary(self, maintenance_id: str, *, permit_sha256: str, proof: dict,
                                 budget_exhausted: bool) -> dict:
        """Claim exactly this permit's owner canary job as `dispatching`, in ONE transaction.

        Required together: an owner-paused Fleet, the granted (never admitted) permit under the same
        digest, the lane's acknowledged ARMED-generation proof, a fresh deadline, the REAL owner action
        still REQUESTED under the permit's binding, its canary job still QUEUED, no reserving job and no
        held execution unit. The ordinary selection then decides over a one-job candidate set with ONLY
        the pause lifted: budget, stale ceilings, capacity, lane, path and dependency blockers all still
        refuse. The claim takes a fresh owner token exactly as `admit_one`, and the permit is spent in
        the same transaction. Other queued jobs are not read-modified. Any refusal writes nothing."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            self._owner_paused(control)
            valid_id = type(maintenance_id) is str and MAINTENANCE_ID.fullmatch(maintenance_id) is not None
            row = tx.get(BUCKET_MAINTENANCE, maintenance_id) if valid_id else None
            if row is None:
                raise FleetRefused("maintenance_admission_refused", "permit")
            if type(permit_sha256) is not str or row["permit_sha256"] != permit_sha256:
                raise FleetRefused("maintenance_conflict", "permit")
            if row["state"] != GRANTED:
                raise FleetRefused("maintenance_already_used", "state")
            permit = row["permit"]
            proof = validate_proof(proof, permit, permit_sha256)
            now = self.clock()
            if deadline_passed(permit["deadline"], now):
                raise FleetRefused("maintenance_expired", "deadline")
            forward = kind_of(permit) == FORWARD_CANDIDATE
            if forward:
                check_backlog_item(permit, tx.scan(BUCKET_BACKLOG_PLANS))
                job = state.permit_job(tx, permit)
                check_forward_job(permit, job)
            else:
                check_owner_action(permit, tx.get(OWNER_ACTIONS_BUCKET, permit["action_id"]))
                job = tx.get(BUCKET_JOBS, permit["job_id"])
                check_canary_job(permit, job)
            job = claim_queued_job(tx, registry, control, job, now=now, token=self.token, budget_exhausted=budget_exhausted,
                                   debt_code="maintenance_debt_unsettled", refused_code="maintenance_admission_refused")
            row.update(state=ADMITTED, admitted_at=now, lane=job["lane"], manifest_sha256=job["manifest_sha256"],
                       owner_token=job["owner_token"], lane_ack={"proof_sha256": digest(proof), "at": now},
                       history=self._history(row, ADMITTED, now, None))
            if forward:
                row["job_id"] = job["id"]
            tx.put(BUCKET_MAINTENANCE, row["id"], row)
        return {"admitted": True, "maintenance_id": row["id"], "job": dict(job)}

    def close_maintenance_canary(self, permit, reason: str) -> dict:
        """Close one permit, in ONE transaction; never a general Fleet cancel.

        `maintenance_expired` (only at or after the deadline) and `maintenance_cancelled` apply to an
        UNADMITTED permit: its still-queued canary job - verified against the stored owner action, a
        foreign job is `maintenance_conflict` - becomes terminal `failed` with that reason and a record
        that no process was launched. Admitted or reserving work is never expired: it is
        `maintenance_reconciliation_required` until it settles. `maintenance_settled` needs the
        admitted permit and its job finalized (not reserving). A missing permit row is created closed;
        a closed one replays `cached` with its recorded reason, and a canary job queued after an
        unlaunched close is failed by that replay too, so no stale canary survives to a resume."""
        permit = validate_permit(permit)
        if type(reason) is not str or reason not in CLOSE_REASONS:
            raise FleetRefused("maintenance_invalid", "reason")
        sha, mid = digest(permit), permit["maintenance_id"]
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            row = tx.get(BUCKET_MAINTENANCE, mid)
            if row is not None and row["permit_sha256"] != sha:
                raise FleetRefused("maintenance_conflict", "permit")
            job = state.permit_job(tx, permit)
            action = None if kind_of(permit) == FORWARD_CANDIDATE else tx.get(OWNER_ACTIONS_BUCKET, permit["action_id"])
            now = self.clock()
            if row is not None and row["state"] == CLOSED:
                if row.get("close_reason") in UNLAUNCHED_REASONS and job is not None and job["status"] == QUEUED:
                    if not self._job_is_permits(permit, action, job):
                        raise FleetRefused("maintenance_conflict", "job")
                    self._fail_unlaunched(tx, job, mid, row["close_reason"], now)
                    row.update(job_status=job["status"],
                               history=self._history(row, CLOSED, now, "stale_canary_failed"))
                    tx.put(BUCKET_MAINTENANCE, mid, row)
                return {"closed": True, "cached": True, "maintenance_id": mid, "close_reason": row["close_reason"],
                        "job_status": row.get("job_status"), "launched": row.get("launched")}
            if reason in UNLAUNCHED_REASONS:
                if (row is not None and row["state"] == ADMITTED) or (job is not None and job["status"] in RESERVING):
                    raise FleetRefused("maintenance_reconciliation_required", "job")
                if reason == MAINTENANCE_EXPIRED and not deadline_passed(permit["deadline"], now):
                    raise FleetRefused("maintenance_stale", "deadline")
                if job is not None:
                    # Only the exact queued canary of this permit's owner action; a job that is already
                    # terminal was never this permit's to close.
                    if job["status"] != QUEUED or not self._job_is_permits(permit, action, job):
                        raise FleetRefused("maintenance_conflict", "job")
                    self._fail_unlaunched(tx, job, mid, reason, now)
                launched = False
            else:
                if row is None or row["state"] != ADMITTED or job is None or job["status"] in RESERVING \
                        or job["status"] == QUEUED:
                    raise FleetRefused("maintenance_reconciliation_required", "job")
                launched = True
            if row is None:
                row = {"id": mid, "maintenance_id": mid, "permit": permit, "permit_sha256": sha, "state": CLOSED,
                       "granted_at": None, "lane": None, "manifest_sha256": None, "owner_token": None,
                       "admitted_at": None, "lane_ack": None, "history": []}
            row.update(state=CLOSED, closed_at=now, close_reason=reason,
                       job_status=job["status"] if job is not None else None, launched=launched,
                       history=self._history(row, CLOSED, now, reason))
            tx.put(BUCKET_MAINTENANCE, mid, row)
        return {"closed": True, "cached": False, "maintenance_id": mid, "close_reason": reason,
                "job_status": row["job_status"], "launched": launched}

    @staticmethod
    def _fail_unlaunched(tx, job: dict, maintenance_id: str, reason: str, now: str) -> None:
        """The queued canary becomes terminal without any process: nothing was ever claimed or spawned."""
        fail_unlaunched_job(tx, job, reason, now,
                            maintenance={"maintenance_id": maintenance_id, "launched": False, "reason": reason})

    def maintenance_permit(self, maintenance_id: str) -> dict | None:
        """The safe view of one permit (never its owner token), or None."""
        if type(maintenance_id) is not str:
            return None
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_MAINTENANCE, maintenance_id)
        return permit_view(row) if row is not None else None

    def job(self, job_id: str) -> dict | None:
        """One job's safe view (no owner token), or None."""
        if type(job_id) is not str:
            return None
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_JOBS, job_id)
        return state.view(row) if row is not None else None

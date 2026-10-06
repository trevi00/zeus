"""The typed one-use Fleet admission permit: grant (with its acknowledgement), admit, close and the permit/job reads
(INV-FLEET-001; FA-SPEC + Amendment A).

Layer: application
Context: coordination
Owns: bucket fleet_admission_permits (the permits), and the one claim of a permit's queued job in fleet_jobs
Does not own: the PR-3 maintenance permits (fleet.maintenance), ordinary admission (fleet.admission), pause, resume and holds (fleet.pause), launching the claimed job (fleet.runner)
Entry points: FleetAdmissionPermits.grant_admission_permit, .admit_admission_permit, .close_admission_permit, .admission_permit, .job
Contracts: INV-FLEET-001

A separate permit beside `FleetMaintenance`, never a generalization of it: the claim is the one `maintenance.claim_queued_job`
and the unlaunched failure the one `maintenance.fail_unlaunched_job`, called with this permit's own refusal codes. Each method
is ONE control-store transaction and every refusal is a fixed `FleetRefused` with nothing written. The Fleet stays
owner-paused throughout and its control row is never written: nothing here pauses, resumes or releases a hold, no
`fleet_maintenance_admissions` row is written, and the ordinary dispatcher gains no authority.
"""

from __future__ import annotations

from uuid import uuid4

from codex_harness.coordination.application.fleet import state
from codex_harness.coordination.application.fleet.maintenance import claim_queued_job, fail_unlaunched_job
from codex_harness.coordination.application.fleet.state import (
    ACTIVATION_HOLD,
    BUCKET_JOBS,
    BUCKET_MAINTENANCE,
    BUCKET_PERMITS,
)
from codex_harness.coordination.domain.fleet import QUEUED, RESERVING, FleetRefused
from codex_harness.coordination.domain.fleet_admission_permit import (
    ACKNOWLEDGED,
    ADMITTED,
    CLOSE_REASONS,
    CLOSED,
    GRANTED,
    PERMIT_EXPIRED,
    PERMIT_ID,
    UNLAUNCHED_REASONS,
    VERIFICATION_JOB,
    build_permit,
    build_verification_permit,
    consumption_deadline,
    expired,
    permit_id_of,
    permit_names_job,
    permit_view,
    validate_permit,
    validate_template,
)
from codex_harness.coordination.domain.fleet_maintenance import OWNER_ACTIONS_BUCKET, owner_action_matches
from codex_harness.coordination.domain.owner_actions import DELIVERY_CANARY, REQUESTED
from codex_harness.kernel.ids import digest, utcnow

# The delivery lane's consumption record (`host_delivery_intents`, keyed by plan id) is READ here, as the lane
# continuation read does; the deadline of a permit comes from its `stage_deadline` (Amendment A2).
BUCKET_DELIVERY_INTENTS = "host_delivery_intents"


def store_consumption(store):
    """The default consumption reader: the delivery intent of a plan in `store`, read in its own transaction."""
    def read(plan_id: str):
        with store.transaction() as tx:
            return tx.get(BUCKET_DELIVERY_INTENTS, plan_id)
    return read


class FleetAdmissionPermits:
    """The one-job `delivery_canary` admission permit (FA-SPEC; the PR-3 permit is `FleetMaintenance`)."""

    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex, consumption=None):
        self.store, self.clock, self.token = store, clock, token
        self.consumption = consumption or store_consumption(store)

    @staticmethod
    def _owner_paused(control: dict) -> None:
        """An OWNER pause: paused, and not merely a managed runtime's activation hold."""
        if not (control.get("paused") is True and control.get(ACTIVATION_HOLD) is None):
            raise FleetRefused("permit_pause_required", "fleet")

    @staticmethod
    def _history(row: dict, new_state: str, now: str, reason: str | None) -> list:
        return list(row.get("history") or []) + [{"state": new_state, "at": now, "reason": reason}]

    @staticmethod
    def _maintenance_names(tx, job_id: str, action_ids) -> bool:
        """A PR-3 permit (any kind) already names this job: FA never admits a `maintenance_canary` or
        `forward_candidate` job. The PR-3 bucket is only READ."""
        return any(permit_names_job(row, job_id, action_ids) for row in tx.scan(BUCKET_MAINTENANCE))

    @staticmethod
    def _cached(row: dict) -> dict:
        return {"granted": True, "cached": True, "permit_id": row["id"], "permit_sha256": row["permit_sha256"],
                "state": row["state"]}

    def grant_admission_permit(self, template_digest: str, template) -> dict:
        """Grant AND acknowledge the permit of the one owner canary the template names, in ONE transaction.

        The template (digest-bound, validated before anything is read) carries the window-independent fields. The
        binding comes from the owner `delivery_canary` action in REQUESTED state under the template's plan, target and
        plan digest (exactly one must exist); the lane and manifest digest from its queued job; the deadline from the
        consumption record (read outside the transaction). The Fleet must be owner-paused. The same id replays `cached`
        only for the identical permit digest; any other permit under it, or another unsettled permit, conflicts."""
        template = validate_template(template)
        if type(template_digest) is not str or digest(template) != template_digest:
            raise FleetRefused("permit_invalid", "template")
        if template["kind"] == VERIFICATION_JOB:
            return self._grant_verification(template, template_digest)
        intent = self.consumption(template["plan_id"])
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            self._owner_paused(state.control(tx))
            now = self.clock()
            matching = [row for row in tx.scan(OWNER_ACTIONS_BUCKET)
                        if row.get("kind") == DELIVERY_CANARY and isinstance(row.get("binding"), dict)
                        and row["binding"].get("plan_id") == template["plan_id"]
                        and row["binding"].get("plan_sha256") == template["plan_sha256"]
                        and row["binding"].get("target_id") == template["target_id"]]
            actions = [row for row in matching if row.get("state") == REQUESTED]
            if len(actions) == 0:
                # Response loss after the canary finished: a spent permit of exactly this template replays cached.
                spent = [old for old in (tx.get(BUCKET_PERMITS, permit_id_of(row["id"])) for row in matching)
                         if old is not None and old["state"] in {ADMITTED, CLOSED}
                         and old["ack"]["template_sha256"] == template_digest]
                if len(spent) == 1:
                    return self._cached(spent[0])
            if len(actions) != 1:
                raise FleetRefused("permit_refused", "action")
            action = actions[0]
            spent = tx.get(BUCKET_PERMITS, permit_id_of(action["id"]))
            if spent is not None and spent["state"] in {ADMITTED, CLOSED}:
                # An admitted or settled row is immutable: only its own template replays, as cached.
                if spent["ack"]["template_sha256"] != template_digest:
                    raise FleetRefused("permit_conflict", "permit")
                return self._cached(spent)
            job = tx.get(BUCKET_JOBS, action.get("job_id")) if type(action.get("job_id")) is str else None
            if not (isinstance(job, dict) and job.get("status") == QUEUED and job.get("lane") == template["lane"]):
                raise FleetRefused("permit_refused", "job")
            deadline = consumption_deadline(intent, action["binding"], now)
            permit = build_permit(template, template_digest, action, job, deadline)
            if not owner_action_matches(permit, action):
                raise FleetRefused("permit_refused", "action")
            sha, pid = digest(permit), permit["permit_id"]
            if self._maintenance_names(tx, permit["job_id"], {permit["action_id"]}):
                raise FleetRefused("permit_conflict", "maintenance")
            if any(row["id"] != pid and row.get("state") != CLOSED for row in tx.scan(BUCKET_PERMITS)):
                raise FleetRefused("permit_conflict", "permit_id")
            old = tx.get(BUCKET_PERMITS, pid)
            if old is not None:
                if old["permit_sha256"] != sha:
                    raise FleetRefused("permit_conflict", "permit")
                return self._cached(old)
            row = self._row(permit, sha, template_digest, now)
            tx.put(BUCKET_PERMITS, pid, row)
        return {"granted": True, "cached": False, "permit_id": pid, "permit_sha256": sha, "state": ACKNOWLEDGED}

    def _grant_verification(self, template: dict, template_digest: str) -> dict:
        """The `verification_job` grant (Amendment A4), in ONE transaction: the owner-paused Fleet, the template's own
        enumerated job still QUEUED under exactly its lane and manifest digest, a fresh deadline, and no owner canary
        action naming that job. The FA-VPLAN row id and digest are bound as recorded, never read."""
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            self._owner_paused(state.control(tx))
            now = self.clock()
            job = tx.get(BUCKET_JOBS, template["job_id"])
            if not (isinstance(job, dict) and job.get("status") == QUEUED and job.get("lane") == template["lane"]
                    and job.get("manifest_sha256") == template["manifest_sha256"]):
                raise FleetRefused("permit_refused", "job")
            if any(row.get("job_id") == job["id"] for row in tx.scan(OWNER_ACTIONS_BUCKET)):
                raise FleetRefused("permit_refused", "action")
            permit = build_verification_permit(template, template_digest, now)
            sha, pid = digest(permit), permit["permit_id"]
            if self._maintenance_names(tx, permit["job_id"], set()):
                raise FleetRefused("permit_conflict", "maintenance")
            if any(row["id"] != pid and row.get("state") != CLOSED for row in tx.scan(BUCKET_PERMITS)):
                raise FleetRefused("permit_conflict", "permit_id")
            old = tx.get(BUCKET_PERMITS, pid)
            if old is not None:
                if old["permit_sha256"] != sha and old["state"] not in {ADMITTED, CLOSED}:
                    raise FleetRefused("permit_conflict", "permit")
                return self._cached(old)
            tx.put(BUCKET_PERMITS, pid, self._row(permit, sha, template_digest, now))
        return {"granted": True, "cached": False, "permit_id": pid, "permit_sha256": sha, "state": ACKNOWLEDGED}

    @staticmethod
    def _row(permit: dict, sha: str, template_digest: str, now: str) -> dict:
        return {"id": permit["permit_id"], "permit": permit, "permit_sha256": sha, "state": ACKNOWLEDGED,
                "granted_at": now, "acknowledged_at": now, "lane": permit["lane"],
                "manifest_sha256": permit["manifest_sha256"], "owner_token": None, "admitted_at": None,
                "closed_at": None, "close_reason": None, "job_status": None, "launched": None,
                "ack": {"template_sha256": template_digest, "at": now},
                "history": [{"state": GRANTED, "at": now, "reason": None},
                            {"state": ACKNOWLEDGED, "at": now, "reason": None}]}

    def admit_admission_permit(self, permit_id: str, *, budget_exhausted: bool, permit_sha256: str | None = None) -> dict:
        """Claim exactly this permit's owner canary job as `dispatching`, in ONE transaction.

        Required together: an owner-paused Fleet, the acknowledged (never admitted or closed) permit, a valid kind and
        binding, a fresh deadline, the REAL owner action still REQUESTED under exactly the permit's binding, its job
        still QUEUED with the permit's lane and manifest digest, and no PR-3 permit naming that job. The unchanged claim
        then decides with ONLY the pause lifted: budget, capacity, lane, path, dependency and debt blockers all still
        refuse, and no other queued job is touched. The Fleet control row is not written. Any refusal writes nothing;
        a replay of an admitted or closed permit is `permit_already_used`, never a second claim."""
        with self.store.transaction() as tx:
            registry = state.registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = state.control(tx)
            self._owner_paused(control)
            valid_id = type(permit_id) is str and PERMIT_ID.fullmatch(permit_id) is not None
            row = tx.get(BUCKET_PERMITS, permit_id) if valid_id else None
            if row is None:
                raise FleetRefused("permit_refused", "permit")
            if permit_sha256 is not None and (type(permit_sha256) is not str or row["permit_sha256"] != permit_sha256):
                raise FleetRefused("permit_conflict", "permit")
            if row["state"] in {ADMITTED, CLOSED}:
                raise FleetRefused("permit_already_used", "state")
            if row["state"] != ACKNOWLEDGED:
                raise FleetRefused("permit_unacknowledged", "state")
            permit = validate_permit(row["permit"])
            if digest(permit) != row["permit_sha256"] or permit["permit_id"] != permit_id:
                raise FleetRefused("permit_conflict", "permit")
            now = self.clock()
            if expired(permit["deadline"], now):
                raise FleetRefused("permit_expired", "deadline")
            canary = permit["kind"] == DELIVERY_CANARY
            if canary:
                action = tx.get(OWNER_ACTIONS_BUCKET, permit["action_id"])
                if not (owner_action_matches(permit, action) and action.get("state") == REQUESTED):
                    raise FleetRefused("permit_refused", "action")
            job = tx.get(BUCKET_JOBS, permit["job_id"])
            if not (isinstance(job, dict) and job.get("id") == permit["job_id"] and job.get("status") == QUEUED
                    and job.get("lane") == permit["lane"] and job.get("manifest_sha256") == permit["manifest_sha256"]):
                raise FleetRefused("permit_refused", "job")
            if self._maintenance_names(tx, job["id"], {permit["action_id"]} if canary else set()):
                raise FleetRefused("permit_refused", "maintenance")
            job = claim_queued_job(tx, registry, control, job, now=now, token=self.token,
                                   budget_exhausted=budget_exhausted, debt_code="permit_debt_unsettled",
                                   refused_code="permit_refused")
            row.update(state=ADMITTED, admitted_at=now, owner_token=job["owner_token"],
                       history=self._history(row, ADMITTED, now, None))
            tx.put(BUCKET_PERMITS, permit_id, row)
        return {"admitted": True, "permit_id": row["id"], "job": dict(job)}

    def close_admission_permit(self, permit_id: str, reason: str) -> dict:
        """Close one permit, in ONE transaction; never a general Fleet cancel.

        `permit_expired` (only at or after the deadline) and `permit_cancelled` apply to an UNADMITTED permit: its
        still-queued job - verified against the stored owner action - becomes terminal `failed` with that reason and
        a record that no process was launched. An admitted or reserving job is never expired: it is
        `permit_reconciliation_required` until it settles, and an unknown dispatch is never relaunched.
        `permit_settled` needs the admitted permit and its job finalized (not reserving, not queued). A closed permit
        replays `cached` with its recorded reason."""
        if type(reason) is not str or reason not in CLOSE_REASONS:
            raise FleetRefused("permit_invalid", "reason")
        with self.store.transaction() as tx:
            if state.registry(tx) is None:
                raise FleetRefused("unregistered")
            valid_id = type(permit_id) is str and PERMIT_ID.fullmatch(permit_id) is not None
            row = tx.get(BUCKET_PERMITS, permit_id) if valid_id else None
            if row is None:
                raise FleetRefused("permit_refused", "permit")
            if row["state"] == CLOSED:
                return {"closed": True, "cached": True, "permit_id": permit_id, "close_reason": row["close_reason"],
                        "job_status": row.get("job_status"), "launched": row.get("launched")}
            permit = validate_permit(row["permit"])
            job = tx.get(BUCKET_JOBS, permit["job_id"])
            now = self.clock()
            if reason in UNLAUNCHED_REASONS:
                if row["state"] == ADMITTED or (job is not None and job["status"] in RESERVING):
                    raise FleetRefused("permit_reconciliation_required", "job")
                if reason == PERMIT_EXPIRED and not expired(permit["deadline"], now):
                    raise FleetRefused("permit_stale", "deadline")
                if job is not None:
                    # Only the exact queued job of this permit's owner action; a terminal job was never its to close.
                    if job["status"] != QUEUED or not (permit["kind"] != DELIVERY_CANARY or owner_action_matches(
                            permit, tx.get(OWNER_ACTIONS_BUCKET, permit["action_id"]))):
                        raise FleetRefused("permit_conflict", "job")
                    fail_unlaunched_job(tx, job, reason, now,
                                        admission_permit={"permit_id": permit_id, "launched": False, "reason": reason})
                launched = False
            else:
                if row["state"] != ADMITTED or job is None or job["status"] in RESERVING \
                        or job["status"] == QUEUED:
                    raise FleetRefused("permit_reconciliation_required", "job")
                launched = True
            row.update(state=CLOSED, closed_at=now, close_reason=reason,
                       job_status=job["status"] if job is not None else None, launched=launched,
                       history=self._history(row, CLOSED, now, reason))
            tx.put(BUCKET_PERMITS, permit_id, row)
        return {"closed": True, "cached": False, "permit_id": permit_id, "close_reason": reason,
                "job_status": row["job_status"], "launched": launched}

    def admission_permit(self, permit_id: str) -> dict | None:
        """The safe view of one permit (never its owner token), or None."""
        if type(permit_id) is not str:
            return None
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_PERMITS, permit_id)
        return permit_view(row) if row is not None else None

    def job(self, job_id: str) -> dict | None:
        """One job's safe view (no owner token), or None."""
        if type(job_id) is not str:
            return None
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_JOBS, job_id)
        return state.view(row) if row is not None else None

"""Fleet control plane: registry, enqueue, atomic admission, finalization and the runner (INV-FLEET-001).

Every admission is one existing store transaction (PostgresStore serializes it with the control
advisory lock; MemoryStore with its lock): at most `max_parallel` reserving jobs, one per lane,
no allowed-path conflict within a repository, all dependencies accepted, no pause and no exhausted
machine ledger. Every observed blocking reason of a queued job is persisted in that same
transaction (timestamps move only when the reason changes) and cleared on admission. The claim is
durable as `dispatching` with a fresh owner token before any process exists; only that owner
finalizes. The runner waits on children outside every transaction, never relaunches a
dispatching/unknown job after a restart, never retries or merges. The only ceiling change is the
explicit operator `authorize_budget` (compare-and-swap, idle fleet only, immutable grant record);
the dispatcher and the model never invoke it. Execution itself is the existing `zeus operate run`
in a lane environment, behind a launcher port.
"""
from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from codex_harness.application.operation import HANDOFF_SCHEMA
from codex_harness.domain.fleet import (
    ACCEPTED,
    DISPATCHING,
    FAILED,
    QUEUED,
    RESERVING,
    TERMINAL,
    UNKNOWN,
    FleetRefused,
    binding,
    config_digest,
    delivery_view,
    effective_config,
    lane_of,
    new_job,
    projection,
    safe_code,
    sanitized_config,
    select_admission,
    validate_config,
    validate_delivery,
    validate_grant,
    validate_job_manifest,
)
from codex_harness.domain.model import require, utcnow
from codex_harness.domain.operation import manifest_digest
from codex_harness.domain.usage_policy import MODES, SUBSCRIPTION, accounting_mode

BUCKET_REGISTRY, BUCKET_CONTROL, BUCKET_JOBS = "fleet_registry", "fleet_control", "fleet_jobs"
BUCKET_GRANTS = "fleet_budget_grants"
BUCKET_DELIVERY = "fleet_delivery"
CONTROL_KEY = "admission"
LOGGER = logging.getLogger("zeus.fleet.runner")


SAFE_HANDOFF_VALUE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")


def _safe_value(value):
    """A short identifier or code, or None. Unlike `safe_code` nothing is truncated at a colon: an
    owner (`lead:improvement`) and a digest id keep their whole value or are dropped entirely."""
    return value if type(value) is str and SAFE_HANDOFF_VALUE.fullmatch(value) else None


def owner_handoff_view(record) -> dict | None:
    """The fleet-visible projection of a lane operation's owner handoff, or None.

    Identities, codes, a bound flag and counts only: no check items, causes, output or manifest
    text cross this boundary, and an unrecognized document is dropped rather than relayed. It is
    delivery VISIBILITY - the job's status, verdict and authority are untouched by it.

    Progress counts are relayed only when the record states BOTH `bound` and `known` as exactly
    true. This check is independent of the writer: a retained older handoff that carries populated
    item lists beside an unbound or unknown inspection shows null progress here, so foreign or
    unidentified evidence cannot be read as work this job completed.
    """
    if not isinstance(record, dict) or record.get("schema") != HANDOFF_SCHEMA:
        return None
    inspection = record.get("inspection") if isinstance(record.get("inspection"), dict) else {}
    credited = inspection.get("bound") is True and inspection.get("known") is True
    counted = lambda key: len(inspection[key]) if credited and isinstance(inspection.get(key), list) else None  # noqa: E731
    return {"schema": HANDOFF_SCHEMA, "id": _safe_value(record.get("id")), "status": _safe_value(record.get("status")),
            "owner": _safe_value(record.get("owner")), "next_action": _safe_value(record.get("next_action")),
            "reason_code": _safe_value(record.get("reason_code")),
            "operation_id": _safe_value(record.get("operation_id")),
            "inspection_id": _safe_value(inspection.get("id")),
            "inspection_bound": inspection.get("bound") is True,
            "inspection_known": inspection.get("known") is True,
            "inspection_reason_code": _safe_value(inspection.get("reason_code")),
            "passed": counted("passed"), "remaining": counted("remaining"),
            "authority": "owner_handoff; visibility only, never a retry, acceptance or release"}


class LaunchRefused(FleetRefused):
    """A definite refusal before any process was created; the job may end `failed`."""


class Fleet:
    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
        self.store, self.clock, self.token = store, clock, token

    # ----- registry -----------------------------------------------------------------------
    @staticmethod
    def _registry(tx) -> dict | None:
        rows = tx.scan(BUCKET_REGISTRY)
        require(len(rows) <= 1, "Fleet registry holds more than one fleet")
        return rows[0] if rows else None

    def register(self, document) -> dict:
        """Idempotent for the identical canonical configuration; any other configuration while
        one is registered is refused (no mutation, no replacement, no second fleet)."""
        config = validate_config(document)
        sha = config_digest(config)
        with self.store.transaction() as tx:
            existing = self._registry(tx)
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

    @staticmethod
    def _control(tx) -> dict:
        """Pause flag and effective budget; an older row without a budget keeps the registered one."""
        return tx.get(BUCKET_CONTROL, CONTROL_KEY) or {"paused": False}

    def registered(self) -> dict:
        """The registry row with `config` carrying the effective ceilings (a grant replaces the
        registered budget for new work); `config_sha256` stays the original registration digest."""
        with self.store.transaction() as tx:
            registry = self._registry(tx)
            control = self._control(tx)
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
            registry = self._registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            config = effective_config(registry["config"], self._control(tx))
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
                return {"job": self._view(old), "cached": True}
            tx.put(BUCKET_JOBS, job["id"], job)
        return {"job": self._view(job), "cached": False}

    @staticmethod
    def _view(job: dict) -> dict:
        keys = ("id", "operation_id", "lane", "team", "status", "reason_code", "manifest_sha256", "goal",
                "dependencies", "calls", "exit_code", "error_type", "owner_handoff", "created_at", "updated_at",
                "dispatched_at", "finished_at")
        return {k: job.get(k) for k in keys}

    # ----- admission control --------------------------------------------------------------
    def _set_paused(self, paused: bool) -> dict:
        with self.store.transaction() as tx:
            if self._registry(tx) is None:
                raise FleetRefused("unregistered")
            # Only the flag changes: a granted effective budget survives pause/resume.
            row = {**self._control(tx), "paused": paused, "updated_at": self.clock()}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, row)
        return row

    def pause(self) -> dict:
        """Stops NEW admissions durably; dispatching work is allowed to finish."""
        return self._set_paused(True)

    def resume(self) -> dict:
        return self._set_paused(False)

    def authorize_budget(self, per_host, total, expected_total, mode=None) -> dict:
        """Explicit operator grant over the effective budget, one transaction: the expected total
        must equal the current effective total, numbers valid and nondecreasing, either a number
        increases or the accounting `mode` changes (None keeps the current mode; unknown modes
        refuse), and no queued/dispatching/unknown job (queued work carries frozen budgets;
        reserving work holds the machine ledger). The registered config and digest stay immutable;
        the control row takes the new budget beside the untouched pause flag and an immutable
        `fleet_budget_grants` record keeps prior/new budget, both modes and time. No resume, and
        nothing here is called by the dispatcher or a model run."""
        with self.store.transaction() as tx:
            registry = self._registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = self._control(tx)
            prior = effective_config(registry["config"], control)["budget"]
            requested = {"per_host": per_host, "total": total}
            if mode is None:
                mode = accounting_mode(prior)
            if type(mode) is not str or mode not in MODES:
                raise FleetRefused("config_invalid", "mode")
            if mode == SUBSCRIPTION:
                requested["mode"] = mode
            budget = validate_grant(prior, requested, expected_total)
            if any(row["status"] == QUEUED or row["status"] in RESERVING for row in tx.scan(BUCKET_JOBS)):
                raise FleetRefused("fleet_not_idle")
            now = self.clock()
            grant_id = "grant-%08d" % (len(tx.scan(BUCKET_GRANTS)) + 1)
            require(tx.get(BUCKET_GRANTS, grant_id) is None, "Fleet budget grant record already exists")
            grant = {"id": grant_id, "fleet": registry["id"], "config_sha256": registry["config_sha256"],
                     "prior": dict(prior), "budget": budget, "expected_total": expected_total,
                     "prior_mode": accounting_mode(prior), "mode": accounting_mode(budget), "granted_at": now}
            tx.put(BUCKET_GRANTS, grant_id, grant)
            row = {**control, "paused": bool(control.get("paused")), "budget": budget, "updated_at": now}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, row)
        return {"granted": True, "grant_id": grant_id, "prior": grant["prior"], "budget": dict(budget),
                "prior_mode": grant["prior_mode"], "mode": grant["mode"], "paused": row["paused"], "granted_at": now}

    def budget_grants(self) -> list[dict]:
        with self.store.transaction() as tx:
            return tx.scan(BUCKET_GRANTS)

    def admit_one(self, budget_exhausted: bool = False) -> dict:
        """One transaction: choose the oldest admissible queued job and claim it as dispatching
        with a fresh owner token. Returns `job` None with the blocking reasons when nothing fits.
        Every observed reason (paused, budget_exhausted, budget_stale, capacity, lane_busy,
        dependency_*, path_conflict) is persisted on its queued job in this transaction; the row
        and its `updated_at` change only when the reason differs from the recorded one."""
        with self.store.transaction() as tx:
            registry = self._registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = self._control(tx)
            config = effective_config(registry["config"], control)  # refreshed every admission
            jobs = {row["id"]: row for row in tx.scan(BUCKET_JOBS)}
            decision = select_admission(config, bool(control.get("paused")), jobs, budget_exhausted)
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
        return self._view(job)

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
            registry = self._registry(tx)
            control = self._control(tx)
            rows = tx.scan(BUCKET_JOBS)
            deliveries = {row["job_id"]: row for row in tx.scan(BUCKET_DELIVERY)}
        if registry is not None:
            registry = {**registry, "config": effective_config(registry["config"], control)}
        view = projection(registry, bool(control.get("paused")), rows, deliveries)
        # A job whose lane operation was refused on evidence carries its already-safe counts-only
        # handoff here too, so `pending_owner` is visible in the status a reader actually polls. A
        # job without one keeps its exact previous shape.
        handoffs = {row["id"]: row.get("owner_handoff") for row in rows if row.get("owner_handoff")}
        return {**view, "jobs": [job if job["id"] not in handoffs else {**job, "owner_handoff": handoffs[job["id"]]}
                                 for job in view["jobs"]]}


class FleetRunner:
    """Bounded dispatcher over a launcher port: `launch(job) -> handle`, `wait(handles, seconds)
    -> finished handles`, `outcome(handle, job) -> outcome`, `budget_exhausted(budget) -> bool`.
    Children are bounded by `max_parallel`, waited for outside transactions, and every claimed
    job this process launched is finalized by it even if another runner races."""

    def __init__(self, fleet: Fleet, launcher, sleep=time.sleep, interval: float = 5.0, reconcile=None):
        self.fleet, self.launcher, self.sleep, self.interval = fleet, launcher, sleep, interval
        # Optional bounded read/group pass run once per tick BEFORE admission, in its own
        # transaction (the adapter supplies it, so this layer keeps no portfolio dependency).
        self.reconcile = reconcile
        # Last logged reconciliation state, so repeated identical failures stay silent and only a
        # real transition is written.
        self.reconciliation_state = None
        self.children: dict[str, tuple[dict, object]] = {}
        self.stopping = False

    def stop(self) -> None:
        """Graceful stop: close admission and drain owned children; nothing is killed."""
        self.stopping = True

    def run(self, once: bool) -> dict:
        self.fleet.registered()  # refuse early when unregistered; ceilings are re-read per scan
        summary = {"admitted": [], "finalized": [], "finalize_failures": [], "blocked": {}, "stopped": False,
                   "reconciliation": {"state": "disabled", "error_type": None}}
        while True:
            self._reconcile(summary)
            progressed = self._admit(summary)
            progressed = self._reap(summary) or progressed
            if self.children or progressed:
                continue
            if once or self.stopping:
                break
            self.sleep(self.interval)
        summary["stopped"] = self.stopping
        summary["reconciliation_required"] = self.fleet.reconciliation_required()
        return summary

    def _reconcile(self, summary: dict) -> None:
        """One bounded reconciliation per tick, before admission and outside every other
        transaction. It never admits, launches, finalizes or retries anything, and its failure is
        recorded as a fixed `unavailable` state with the exception TYPE only: unrelated Fleet
        admission and finalization keep running.

        A long-running service only returns its summary when it stops, so each state TRANSITION is
        also logged once: a fixed message on entering `unavailable` and one on recovery. Repeated
        identical failures stay silent, and no traceback, exception text or message is logged."""
        if self.reconcile is None:
            return
        try:
            self.reconcile()
        except Exception as exc:
            summary["reconciliation"] = {"state": "unavailable", "error_type": type(exc).__name__}
            if self.reconciliation_state != "unavailable":
                LOGGER.warning("portfolio reconciliation unavailable; fleet admission continues")
            self.reconciliation_state = "unavailable"
        else:
            summary["reconciliation"] = {"state": "ok", "error_type": None}
            if self.reconciliation_state == "unavailable":
                LOGGER.info("portfolio reconciliation recovered")
            self.reconciliation_state = "ok"

    def _admit(self, summary: dict) -> bool:
        progressed = False
        # Effective ceilings are refreshed before every admission scan: a grant made while this
        # service sleeps applies to the next scan without a restart and without any hidden reset.
        config = self.fleet.registered()["config"]
        while not self.stopping and len(self.children) < config["max_parallel"]:
            exhausted = bool(self.launcher.budget_exhausted(config["budget"]))
            decision = self.fleet.admit_one(budget_exhausted=exhausted)
            summary["blocked"] = decision["blocked"]
            job = decision["job"]
            if job is None:
                break
            progressed = True
            summary["admitted"].append(job["id"])
            try:
                handle = self.launcher.launch(job)
            except LaunchRefused as exc:
                self._finalize(job, {"status": FAILED, "reason_code": exc.reason_code}, summary)
            except Exception as exc:
                # The process may or may not exist: the claim, lane and paths stay reserved.
                self._finalize(job, {"status": UNKNOWN, "reason_code": "spawn_uncertain",
                                     "error_type": type(exc).__name__}, summary)
            else:
                self.children[job["id"]] = (job, handle)
        return progressed

    def _reap(self, summary: dict) -> bool:
        if not self.children:
            return False
        finished = self.launcher.wait([handle for _, handle in self.children.values()], self.interval)
        progressed = False
        for handle in finished:
            job, _ = self.children.pop(handle["job_id"])
            try:
                outcome = self.launcher.outcome(handle, job)
            except Exception as exc:
                outcome = {"status": UNKNOWN, "reason_code": "outcome_uncertain", "error_type": type(exc).__name__}
            self._finalize(job, outcome, summary)
            progressed = True
        return progressed

    def _finalize(self, job: dict, outcome: dict, summary: dict) -> None:
        try:
            row = self.fleet.finalize(job["id"], job["owner_token"], outcome)
        except Exception as exc:
            # The row stays dispatching and is reported as reconciliation_required; no retry here.
            summary["finalize_failures"].append({"id": job["id"], "error_type": type(exc).__name__})
            return
        summary["finalized"].append({"id": row["id"], "status": row["status"], "reason_code": row["reason_code"]})


__all__ = ["BUCKET_CONTROL", "BUCKET_DELIVERY", "BUCKET_GRANTS", "BUCKET_JOBS", "BUCKET_REGISTRY",
           "Fleet", "FleetRunner", "LaunchRefused", "QUEUED"]

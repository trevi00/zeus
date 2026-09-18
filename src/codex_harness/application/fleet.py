"""Fleet control plane: registry, enqueue, atomic admission, finalization and the runner (INV-FLEET-001).

Every admission is one existing store transaction (PostgresStore serializes it with the control
advisory lock; MemoryStore with its lock): at most `max_parallel` reserving jobs, one per lane,
no allowed-path conflict within a repository, all dependencies accepted, no pause and no exhausted
machine ledger. The claim is durable as `dispatching` with a fresh owner token before any process
exists; only that owner finalizes. The runner waits on children outside every transaction, never
relaunches a dispatching/unknown job after a restart, never retries, merges or raises a ceiling.
Execution itself is the existing `zeus operate run` in a lane environment, behind a launcher port.
"""
from __future__ import annotations

import time
from uuid import uuid4

from codex_harness.domain.fleet import (
    DISPATCHING,
    FAILED,
    QUEUED,
    RESERVING,
    TERMINAL,
    UNKNOWN,
    FleetRefused,
    binding,
    config_digest,
    lane_of,
    new_job,
    projection,
    safe_code,
    sanitized_config,
    select_admission,
    validate_config,
    validate_job_manifest,
)
from codex_harness.domain.model import require, utcnow
from codex_harness.domain.operation import manifest_digest

BUCKET_REGISTRY, BUCKET_CONTROL, BUCKET_JOBS = "fleet_registry", "fleet_control", "fleet_jobs"
CONTROL_KEY = "admission"


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
                tx.put(BUCKET_CONTROL, CONTROL_KEY, {"paused": False, "updated_at": self.clock()})
        return {"registered": True, "cached": False, "id": config["id"], "config_sha256": sha,
                "config": sanitized_config(config)}

    def registered(self) -> dict:
        with self.store.transaction() as tx:
            registry = self._registry(tx)
        if registry is None:
            raise FleetRefused("unregistered")
        return registry

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
            lane = lane_of(registry["config"], lane_id)
            validate_job_manifest(manifest, registry["config"])
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
                "dependencies", "calls", "exit_code", "error_type", "created_at", "updated_at",
                "dispatched_at", "finished_at")
        return {k: job.get(k) for k in keys}

    # ----- admission control --------------------------------------------------------------
    def _set_paused(self, paused: bool) -> dict:
        with self.store.transaction() as tx:
            if self._registry(tx) is None:
                raise FleetRefused("unregistered")
            row = {"paused": paused, "updated_at": self.clock()}
            tx.put(BUCKET_CONTROL, CONTROL_KEY, row)
        return row

    def pause(self) -> dict:
        """Stops NEW admissions durably; dispatching work is allowed to finish."""
        return self._set_paused(True)

    def resume(self) -> dict:
        return self._set_paused(False)

    def admit_one(self, budget_exhausted: bool = False) -> dict:
        """One transaction: choose the oldest admissible queued job and claim it as dispatching
        with a fresh owner token. Returns `job` None with the blocking reasons when nothing fits."""
        with self.store.transaction() as tx:
            registry = self._registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            control = tx.get(BUCKET_CONTROL, CONTROL_KEY) or {"paused": False}
            jobs = {row["id"]: row for row in tx.scan(BUCKET_JOBS)}
            decision = select_admission(registry["config"], bool(control.get("paused")), jobs, budget_exhausted)
            job = decision["job"]
            if job is not None:
                now = self.clock()
                job.update(status=DISPATCHING, owner_token=self.token(), dispatched_at=now, updated_at=now,
                           reason_code=None)
                tx.put(BUCKET_JOBS, job["id"], job)
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
            job.update(status=status, reason_code=safe_code(outcome.get("reason_code")),
                       exit_code=outcome.get("exit_code") if type(outcome.get("exit_code")) is int else None,
                       calls={"reserved": calls.get("reserved"), "settled": calls.get("settled")},
                       receipt={"operation_status": outcome.get("operation_status")},
                       error_type=outcome.get("error_type") if isinstance(outcome.get("error_type"), str) else None,
                       updated_at=now, finished_at=now)
            tx.put(BUCKET_JOBS, job_id, job)
        return self._view(job)

    # ----- read-only ----------------------------------------------------------------------
    def reconciliation_required(self) -> list[str]:
        """Dispatching/unknown jobs: never relaunched, never cleared by an operator command here."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_JOBS)
        return sorted(row["id"] for row in rows if row["status"] in RESERVING)

    def status(self) -> dict:
        """The `urn:zeus:fleet-status:1` projection from PG reads only."""
        with self.store.transaction() as tx:
            registry = self._registry(tx)
            control = tx.get(BUCKET_CONTROL, CONTROL_KEY) or {}
            rows = tx.scan(BUCKET_JOBS)
        return projection(registry, bool(control.get("paused")), rows)


class FleetRunner:
    """Bounded dispatcher over a launcher port: `launch(job) -> handle`, `wait(handles, seconds)
    -> finished handles`, `outcome(handle, job) -> outcome`, `budget_exhausted(budget) -> bool`.
    Children are bounded by `max_parallel`, waited for outside transactions, and every claimed
    job this process launched is finalized by it even if another runner races."""

    def __init__(self, fleet: Fleet, launcher, sleep=time.sleep, interval: float = 5.0):
        self.fleet, self.launcher, self.sleep, self.interval = fleet, launcher, sleep, interval
        self.children: dict[str, tuple[dict, object]] = {}
        self.stopping = False

    def stop(self) -> None:
        """Graceful stop: close admission and drain owned children; nothing is killed."""
        self.stopping = True

    def run(self, once: bool) -> dict:
        config = self.fleet.registered()["config"]
        summary = {"admitted": [], "finalized": [], "finalize_failures": [], "blocked": {}, "stopped": False}
        while True:
            progressed = self._admit(config, summary)
            progressed = self._reap(summary) or progressed
            if self.children or progressed:
                continue
            if once or self.stopping:
                break
            self.sleep(self.interval)
        summary["stopped"] = self.stopping
        summary["reconciliation_required"] = self.fleet.reconciliation_required()
        return summary

    def _admit(self, config: dict, summary: dict) -> bool:
        progressed = False
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


__all__ = ["BUCKET_CONTROL", "BUCKET_JOBS", "BUCKET_REGISTRY", "Fleet", "FleetRunner", "LaunchRefused", "QUEUED"]

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
from codex_harness.domain.fleet_backlog import runner_state
from codex_harness.domain.fleet_backlog import safe_error_type as safe_backlog_error_type
from codex_harness.domain.fleet_recovery import (
    INTERRUPTED,
    canonical_repositories,
    check_recovery_proof,
    check_relocation_proof,
    proof_binding,
    recovery_receipt,
    recovery_receipt_id,
    recovery_view,
    relocated_config,
    relocation_receipt,
    relocation_receipt_id,
    relocation_view,
    validate_recovery_evidence,
    validate_relocation_request,
)
from codex_harness.domain.model import require, utcnow
from codex_harness.domain.operation import manifest_digest
from codex_harness.domain.usage_policy import MODES, SUBSCRIPTION, accounting_mode

BUCKET_REGISTRY, BUCKET_CONTROL, BUCKET_JOBS = "fleet_registry", "fleet_control", "fleet_jobs"
BUCKET_GRANTS = "fleet_budget_grants"
BUCKET_DELIVERY = "fleet_delivery"
BUCKET_RECOVERY = "fleet_recovery_receipts"
BUCKET_RELOCATION = "fleet_relocations"
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
            decision = select_admission(config, bool(control.get("paused")), jobs, budget_exhausted,
                                        self._repository_aliases(tx))
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

    # ----- owner recovery and relocation (storage-recovery-001) ---------------------------
    @staticmethod
    def _repository_aliases(tx) -> dict:
        """Every repository identity this fleet has used -> the one canonical identity of its
        repository, folded from the immutable relocation receipts in their recorded order.

        Job rows are never rewritten, so this map is how a job frozen before a move is still
        compared against the repository it belongs to. Folding the receipts' edges into one
        equivalence class per repository (`canonical_repositories`) is what keeps that true after
        repeated moves and after a rollback: A->B->A is a cycle, and a plain chain walk over it
        would answer differently depending on which identity a job happens to carry."""
        return canonical_repositories(row.get("repository_aliases") or {}
                                      for row in sorted(tx.scan(BUCKET_RELOCATION),
                                                        key=lambda r: (r["recorded_at"], r["id"])))

    def _recovery_replay(self, document: dict) -> dict | None:
        """The committed answer for this evidence, read BEFORE anything is observed.

        A recovery that already committed is finished: its receipt is the durable fact, and asking
        Docker, the lane store or the machine ledger about a container, a schema or a slot that has
        since been removed would turn a settled job into a refusal. Identical evidence therefore
        replays from the receipt alone; any other evidence for that job still conflicts here.
        """
        with self.store.transaction() as tx:
            if self._registry(tx) is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_RECOVERY, document["job_id"])
            if old is None:
                return None
            if old["evidence"] != document:
                raise FleetRefused("recovery_conflict")
            return {"reconciled": True, "cached": True, "receipt": recovery_view(old),
                    "job": self._view(tx.get(BUCKET_JOBS, document["job_id"]) or {})}

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
            registry = self._registry(tx)
            if registry is None:
                raise FleetRefused("unregistered")
            old = tx.get(BUCKET_RECOVERY, document["job_id"])
            if old is not None:
                # A second owner committed between the read above and this transaction; the
                # reservation is already cleared, so the durable receipt is still the answer.
                if old["evidence"] != document:
                    raise FleetRefused("recovery_conflict")
                return {"reconciled": True, "cached": True, "receipt": recovery_view(old),
                        "job": self._view(tx.get(BUCKET_JOBS, document["job_id"]) or {})}
            if not bool(self._control(tx).get("paused")):
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
        return {"reconciled": True, "cached": False, "receipt": recovery_view(receipt), "job": self._view(job)}

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
            registry = self._registry(tx)
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
            registry = self._registry(tx)
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
            if not bool(self._control(tx).get("paused")):
                raise FleetRefused("fleet_not_paused")
            if registry["config_sha256"] != document["expected_config_sha256"]:
                raise FleetRefused("config_expected_mismatch", "expected_config_sha256")
            jobs = tx.scan(BUCKET_JOBS)
            if any(row["status"] in RESERVING for row in jobs):
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

    def relocations(self) -> list[dict]:
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET_RELOCATION)
        return [relocation_view(row) for row in sorted(rows, key=lambda r: (r["recorded_at"], r["id"]))]

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

    def __init__(self, fleet: Fleet, launcher, sleep=time.sleep, interval: float = 5.0, reconcile=None,
                 backlog=None):
        self.fleet, self.launcher, self.sleep, self.interval = fleet, launcher, sleep, interval
        # Optional bounded read/group pass run once per tick BEFORE admission, in its own
        # transaction (the adapter supplies it, so this layer keeps no portfolio dependency).
        self.reconcile = reconcile
        # Optional bounded approved-backlog tick (INV-FLEET-BACKLOG-001), also supplied by the
        # adapter and also in its own transactions. None - the default - keeps this runner's exact
        # previous behaviour: it invents no successor, no retry and no merge.
        self.backlog = backlog
        # Last logged reconciliation state, so repeated identical failures stay silent and only a
        # real transition is written.
        self.reconciliation_state = None
        self.backlog_state = None
        self.children: dict[str, tuple[dict, object]] = {}
        self.stopping = False

    def stop(self) -> None:
        """Graceful stop: close admission and drain owned children; nothing is killed."""
        self.stopping = True

    def run(self, once: bool) -> dict:
        self.fleet.registered()  # refuse early when unregistered; ceilings are re-read per scan
        summary = {"admitted": [], "finalized": [], "finalize_failures": [], "blocked": {}, "stopped": False,
                   "reconciliation": {"state": "disabled", "error_type": None},
                   "backlog": {"state": "disabled", "outcome": None, "reason_code": None,
                               "error_type": None}}
        while True:
            self._reconcile(summary)
            self._backlog(summary)
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

    def _backlog(self, summary: dict) -> None:
        """One bounded approved-backlog tick per cycle, before admission and outside every other
        transaction. Disabled unless the adapter wired one, and skipped once a graceful stop has
        begun, so a stopping runner admits no new work.

        It selects at most one already approved item and hands it to the ordinary `Fleet.enqueue`;
        it never admits, launches, finalizes, retries or merges anything.

        A tick that RETURNS a failure is a failure of that tick, exactly like one that raises: an
        `unavailable`, `refused`, `conflict` or `plan_unregistered` answer is reported with its own
        fixed reason code and exception TYPE, never as `ok` merely because the call returned. Idle,
        blocked and both pauses are healthy. Unrelated admission and finalization keep running, and
        only a state TRANSITION is logged - repeated identical failures, repeated idle polls, raw
        exception text and raw messages never reach a log line.
        """
        if self.backlog is None or self.stopping:
            return
        try:
            result = self.backlog()
        except Exception as exc:
            self._backlog_state(summary, "unavailable", None, None, type(exc).__name__)
        else:
            row = result if isinstance(result, dict) else {}
            outcome = row.get("outcome")
            self._backlog_state(summary, runner_state(outcome), outcome, row.get("reason_code"),
                                row.get("error_type"))

    def _backlog_state(self, summary: dict, state: str, outcome, reason_code, error_type) -> None:
        summary["backlog"] = {"state": state, "outcome": outcome,
                              "reason_code": safe_code(reason_code) if reason_code is not None else None,
                              "error_type": safe_backlog_error_type(error_type)}
        if state == self.backlog_state:
            return
        if state == "unavailable":
            LOGGER.warning("approved backlog unavailable; fleet admission continues")
        elif state != "ok":
            LOGGER.warning("approved backlog %s; fleet admission continues reason=%s", state,
                           summary["backlog"]["reason_code"])
        elif self.backlog_state is not None:
            LOGGER.info("approved backlog recovered")
        self.backlog_state = state

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


__all__ = ["BUCKET_CONTROL", "BUCKET_DELIVERY", "BUCKET_GRANTS", "BUCKET_JOBS", "BUCKET_RECOVERY",
           "BUCKET_REGISTRY", "BUCKET_RELOCATION", "Fleet", "FleetRunner", "LaunchRefused", "QUEUED"]

"""`zeus audit-service run|status`: the one host entry point that connects the existing source
audit scheduler to this host (INV-AUDIT-SERVICE-001).

Thin wiring of owners that already exist: `Releases` keeps release activation, `schedule_audits`
keeps the generation deduplication, the outbox and the Redis stream keep delivery, `Workflow` keeps
acceptance, the claim guard and completion, `AuditExecution` keeps the analysis, and the observer
keeps the logs. There is no second analysis engine, source reader, scheduler, promotion authority
or budget ledger here. This command never activates a release, merges, deploys, retries a failed
attempt, executes source code or runs an audit action other than `audit_partition`.

The durable authority stays where it is: the `schedule`, `tasks` and `research_partitions` rows say
what exists and how far the scope got. The narrow `audit_service` row this module owns holds only
the current owner, the task it bound, the last result and the stop reason, so a restart reconciles
against the records instead of inferring permission to repeat an attempt.

Goal progress is observed here and decided nowhere here: before the first admission and after each
terminal settlement this service asks the existing progress observer for ONE reading of the audit's
own records and records the bounded facts it returned. That observation never admits, blocks,
retries or reinterprets an execution, an observation failure is reported as `degraded` beside an
unchanged execution result, and the research candidate it may record is an unverified symptom for
the existing research program, never an audit verdict.

A rejected draft may also gain ONE opted-in corrective successor: each tick asks the bounded repair
owner (INV-AUDIT-REPAIR-001) to reconcile its open lineages from terminal task evidence and to admit
at most one ordinary `audit_partition` assignment for a diagnosed rejection. That assignment is not
special here - it takes its turn through the same relay, delivery, claim guard, fence, executor and
validators as any other queued one - and a repair failure is a bounded recorded fact, never an
execution outcome, a stop reason or permission to repeat an attempt.

What an execution DID and what its content was JUDGED to be are reported as two separate facts. A
draft the typed content boundary refused is a completed execution that retained its work
(`analysis_rejected`): it holds its own partition at the generation it was assigned, lets another
partition run, counts against `--max-tasks`, and is never retried, reassigned or credited here. A
checkpoint is partial progress (`analysis_checkpointed`), not semantic acceptance, and a result
carrying no such marker stays unclassified. Evidence, receipt, ownership, transport and store
failures are unchanged: they are execution failures and they still stop admission.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict
from uuid import uuid4

from codex_harness.adapters.operation_cli import refusal
from codex_harness.application.audit_progress import BUCKET_STATE as PROGRESS_BUCKET
from codex_harness.application.audit_progress import status_view as progress_view
from codex_harness.application.audit_repair import BUCKET_ACTIVATION as REPAIR_ACTIVATION
from codex_harness.application.audit_repair import BUCKET_CORRECTIONS as REPAIR_CORRECTIONS
from codex_harness.application.audit_repair import repair_view
from codex_harness.application.scheduling import schedule_audits
from codex_harness.application.workflow import ClaimGuardRefused
from codex_harness.domain.audit_progress import (
    BASELINE,
    CLOSED,
    DEGRADED,
    OBSERVED,
    VERDICTS,
)
from codex_harness.domain.audit_repair import (
    DIAGNOSES,
    NOT_ADMITTED_REASONS,
    SETTLEMENT_REASONS,
    STATES,
)
from codex_harness.domain.model import ContractError, digest, utcnow
from codex_harness.domain.observation import (
    ANALYSIS_OUTCOMES,
    ANALYSIS_REJECTED,
    NO_ANALYSIS,
    analysis_facts,
    safe_code,
)

__all__ = ["AuditServiceRefused", "AuditServiceRunner", "activation", "add_parser",
           "analysis_facts", "block_reason", "execute", "progress_facts",
           "repair_admission_facts", "repair_reason", "repair_settlement_facts", "refusal", "run",
           "status"]

AGENT = "worker:github"
ACTION = "audit_partition"
STATE_BUCKET = "audit_service"
# One tick reads at most this many stream entries while looking for its own assignment. A foreign
# entry is read into THIS consumer's pending list, counted and left unacknowledged there, so the
# existing consumer-group recovery returns it to its owner: never acknowledged, dead-lettered or
# handled here.
DELIVERY_READS = 8
IDLE_SECONDS = 5.0
MAX_TASKS_CEILING = 100
SUMMARY_STEPS = 50
# A task status this service can name, so a stop reason is always a declared code.
STOP_BY_STATUS = {"failed": "task_failed", "retry": "task_retry", "blocked": "task_blocked",
                  "expired": "task_expired", "cancelled": "task_cancelled",
                  "superseded": "task_superseded", "running": "task_unresolved",
                  "queued": "task_unresolved"}
# A settled execution says what its content was judged to be; a result that carries no such marker,
# every historical row included, stays unclassified and is never promoted to either outcome.
# `domain.observation` owns that projection (`analysis_facts`) and its vocabularies; this module and
# the repair owner both read it there rather than each deciding what a stored marker means.
SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
# The goal-progress observation this service records and logs (self-improvement-reference-001).
# Only these attributes reach a log or the durable row, and only these fixed codes are declared:
# anything else a future observer returns is `unknown`, never a new Zeus code.
PROGRESS_DEGRADED = DEGRADED
PROGRESS_STATUSES = (BASELINE, OBSERVED, CLOSED, DEGRADED)
PROGRESS_REASONS = ("unknown_audit", "audit_not_partitioned", "state_changed", "observation_failed",
                    "observer_failed", "unreadable_evidence", "malformed_evidence")
PROGRESS_ATTRIBUTES = ("audit_id", "epoch", "status", "verdict", "window_index", "window_executions",
                       "new_executions", "semantic_delta", "ranges_delta", "streak", "candidate",
                       "candidate_created", "unknown", "error_type")
# self-improvement-reference-001 bounded repair (INV-AUDIT-REPAIR-001): the lineage facts this
# service logs and records. Identifiers, fixed codes and counts only - the refused draft, the
# validator's message, source text and every exception text stay in the immutable artifact that the
# lineage merely names. A foreign code a future owner returns is `unknown`, never a new Zeus code.
REPAIR_UNAVAILABLE = "repair_unavailable"
REPAIR_REASONS = (*NOT_ADMITTED_REASONS, *SETTLEMENT_REASONS, REPAIR_UNAVAILABLE)
REPAIR_ADMITTED_ATTRIBUTES = ("audit_id", "correction_id", "source_task_id", "partition_id",
                              "partition_generation", "diagnosis", "successor_task_id", "admitted",
                              "published", "error_type")
REPAIR_SETTLED_ATTRIBUTES = ("audit_id", "correction_id", "source_task_id", "successor_task_id",
                             "state", "diagnosis", "analysis_outcome", "target_subsystems",
                             "corrected_subsystems", "remaining_targets", "checkpoint_generation",
                             "attempts", "notice_id", "notice_published", "error_type")


def _count(value):
    """An integer count, or None. A boolean is not a count and a foreign type is unknown."""
    return value if type(value) is int else None


def _identity(value):
    return value if type(value) is str and SAFE_IDENTIFIER.fullmatch(value) else None


def progress_facts(observation) -> dict:
    """The allow-listed facts of ONE goal-progress observation.

    The observation is data this service reads, never an instruction: a status or verdict outside
    the declared vocabularies is a fixed code, an identifier that is not an identifier is dropped,
    and a count that is not an integer is `null` rather than zero. A window delta is arithmetic over
    the audit's own records, never a semantic or review credit, and a `degraded` observation says
    nothing at all about the execution that preceded it.
    """
    row = observation if isinstance(observation, dict) else {}
    window = row.get("window") if isinstance(row.get("window"), dict) else {}
    delta = window.get("delta") if isinstance(window.get("delta"), dict) else {}
    # An absent or foreign status is not an observation this service can report as one: it reads as
    # degraded, so an unreadable reading can never be logged as a clean observation.
    status = safe_code(row.get("status"), PROGRESS_STATUSES, absent=PROGRESS_DEGRADED)
    status = PROGRESS_DEGRADED if status not in PROGRESS_STATUSES else status
    unknown = row.get("reason_code") or row.get("unknown")
    return {"audit_id": str(row.get("audit_id") or ""), "status": status,
            "epoch": _identity(row.get("epoch")),
            "verdict": safe_code(row.get("verdict"), VERDICTS, absent=None),
            "window_index": _count(row.get("window_index")),
            "window_executions": _count(window.get("executions")),
            "new_executions": _count(row.get("new_executions")),
            "semantic_delta": _count(delta.get("semantic_total")),
            "ranges_delta": _count(delta.get("distinct_ranges")),
            "streak": _count(row.get("streak")), "candidate": _identity(row.get("candidate")),
            "candidate_created": bool(row.get("candidate_created")),
            "unknown": None if unknown is None else safe_code(unknown, PROGRESS_REASONS, absent=None),
            "error_type": _identity(row.get("error_type"))}


def repair_admission_facts(admission, audit_id: str) -> dict:
    """The allow-listed facts of ONE repair admission attempt.

    The owner's result is data this service reads, never an instruction: a diagnosis or reason
    outside the declared vocabularies is a fixed code, an identifier that is not an identifier is
    dropped, and `admitted` false always carries the reason it was not.
    """
    row = admission if isinstance(admission, dict) else {}
    return {"audit_id": audit_id, "correction_id": _identity(row.get("correction_id")),
            "source_task_id": _identity(row.get("source_task_id")),
            "partition_id": _identity(row.get("partition_id")),
            "partition_generation": _count(row.get("partition_generation")),
            "diagnosis": safe_code(row.get("diagnosis"), DIAGNOSES, absent=None),
            "successor_task_id": _identity(row.get("successor_task_id")),
            "admitted": bool(row.get("admitted")), "published": bool(row.get("published")),
            "error_type": _identity(row.get("error_type"))}


def repair_settlement_facts(settled, audit_id: str, notice=None) -> dict:
    """The allow-listed facts of ONE settled lineage. A checkpoint generation and the target,
    corrected and remaining counts are arithmetic over the successor's own records against the
    originally diagnosed target set, never a semantic credit; a notice identity is a delivered
    question, reported separately from the settlement it names and never a repaired subsystem."""
    row = settled if isinstance(settled, dict) else {}
    notice = notice if isinstance(notice, dict) else {}
    published = notice.get("published")
    return {"audit_id": audit_id, "correction_id": str(row.get("correction_id") or ""),
            "source_task_id": _identity(row.get("source_task_id")),
            "successor_task_id": _identity(row.get("successor_task_id")),
            "state": safe_code(row.get("state"), STATES, absent="unknown"),
            "diagnosis": safe_code(row.get("diagnosis"), DIAGNOSES, absent=None),
            "analysis_outcome": safe_code(row.get("analysis_outcome"), ANALYSIS_OUTCOMES, absent=None),
            "target_subsystems": _count(row.get("target_subsystems")),
            "corrected_subsystems": _count(row.get("corrected_subsystems")),
            "remaining_targets": _count(row.get("remaining_targets")),
            "checkpoint_generation": _count(row.get("checkpoint_generation")),
            "attempts": _count(row.get("attempts")) or 0,
            "notice_id": _identity(notice.get("notice_id")),
            "notice_published": None if published is None else bool(published),
            "error_type": None}


def repair_reason(value):
    """A declared repair reason code, or None. A foreign value is `unknown`, never free text."""
    return None if value is None else safe_code(value, REPAIR_REASONS, absent=None)


class AuditServiceRefused(ContractError):
    """A refusal that names its fixed code; the CLI prints the code and the type, never a value."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def add_parser(commands) -> None:
    service = commands.add_parser("audit-service", help="Run ONE selected source audit through the "
                                  "existing scheduler, Workflow and executor; no release activation")
    sub = service.add_subparsers(dest="audit_service_command", required=True)
    run_command = sub.add_parser("run", help="Own this runtime and execute the selected audit's "
                                 "partition assignments one at a time")
    run_command.add_argument("--audit-id", required=True, dest="audit_id",
                             help="The explicitly selected audit; unrelated audits are never executed")
    run_command.add_argument("--max-tasks", type=int, default=None, dest="max_tasks",
                             help="Finite acceptance mode: stop after N successful task completions "
                                  "(1..100). Not a subscription call cap; queued successors are kept")
    run_command.add_argument("--once", action="store_true",
                             help="Do the work that is ready now, then exit instead of waiting")
    status_command = sub.add_parser("status", help="Read the service state and the durable audit "
                                    "records; store read only")
    status_command.add_argument("--audit-id", required=True, dest="audit_id")


def _stop_code(status) -> str:
    return STOP_BY_STATUS.get(status, "task_unknown") if type(status) is str else "task_unknown"


def block_reason(state: dict, task) -> dict | None:
    """Why a new admission is blocked, from the durable records alone, or None.

    A recorded predecessor that did not succeed blocks until its own row says the operator acted:
    it succeeded, or its execution generation advanced (existing recovery or cancellation). This
    service never moves that row itself and never repeats the attempt.
    """
    last = (state or {}).get("last_task")
    if not last or last.get("status") == "succeeded":
        return None
    if not isinstance(task, dict):
        return {"task_id": last.get("task_id"), "reason_code": "unknown_execution"}
    if task.get("status") == "succeeded" or task.get("generation") != last.get("task_generation"):
        return None
    return {"task_id": last.get("task_id"), "reason_code": _stop_code(task.get("status"))}


def _default_state(audit_id: str) -> dict:
    return {"id": audit_id, "audit_id": audit_id, "owner": None, "current_task": None,
            "last_task": None, "stop_reason": None, "completed_tasks": 0, "last_collection": None,
            "last_progress": None, "last_repair": None, "started_at": None, "updated_at": None}


def current_revision() -> str:
    """The revision of THIS repository checkout, read with git argv through the existing workspace."""
    from codex_harness.adapters.configuration import repository_root, runtime_dir
    from codex_harness.adapters.git import GitWorkspace

    return GitWorkspace(str(repository_root()), str(runtime_dir() / "workspaces"))._git("rev-parse", "HEAD")


def activation(store, org, audit_id: str, revision: str) -> dict:
    """The read-only run gate: an active research activation that belongs to the CURRENT active
    release and to this repository revision and organization graph, plus a partitioned audit that
    the operator selected by id. Nothing here promotes, reconciles or writes; a refusal happens
    before any observer, executor, transport or provider exists."""
    if type(audit_id) is not str or not audit_id.strip():
        raise AuditServiceRefused("audit_id_invalid")
    with store.transaction() as tx:
        control = tx.get("research_control", "activation") or {}
        active = tx.get("deployment", "active") or {}
        graph = tx.get("research_control", "graph") or {}
        audit = tx.get("research_audits", audit_id)
        partitions = [p for p in tx.scan("research_partitions") if p["audit_id"] == audit_id]
    if control.get("status") != "active":
        raise AuditServiceRefused("activation_inactive")
    if not control.get("release_id") or control.get("release_id") != active.get("release_id"):
        raise AuditServiceRefused("activation_stale")
    if not revision or control.get("revision") != revision or graph.get("revision") != revision:
        raise AuditServiceRefused("revision_mismatch")
    if graph.get("organization") != digest({k: asdict(v) for k, v in org.agents.items()}):
        raise AuditServiceRefused("graph_mismatch")
    if audit is None:
        raise AuditServiceRefused("unknown_audit")
    if not partitions:
        raise AuditServiceRefused("audit_not_partitioned")
    return {"release_id": control["release_id"], "revision": revision, "partitions": len(partitions),
            "remaining_partitions": sum(1 for p in partitions if p["remaining_paths"]
                                        or p["remaining_subsystems"] or p["open_questions"])}


class AuditServiceRunner:
    """One audit, one task at a time, over the existing durable records.

    Every collaborator is injected, so the caller owns the host lock, the executor, the transport,
    the observer and the collector; a contract test drives the real store, scheduler and Workflow
    without entering a provider. The runner never claims work it did not select, never acknowledges
    a message that is not its own assignment and never starts a second attempt of anything.

    Admission is guarded at every new admission and again immediately before the executor, not only
    at startup: `_admission_gate` re-reads the observed stop and the same activation/release/graph
    gate, so a release paused mid-run and a stop observed during delivery both start zero work.
    """

    def __init__(self, service, audit_id: str, *, executor=None, bus=None, workflow=None,
                 observer=None, collector=None, progress=None, repair=None, max_tasks=None,
                 revision=None, release_id=None, partitions=None, owner=None, sleep=time.sleep,
                 interval: float = IDLE_SECONDS, schedule=schedule_audits):
        if type(audit_id) is not str or not audit_id.strip():
            raise AuditServiceRefused("audit_id_invalid")
        if max_tasks is not None and (type(max_tasks) is not int or isinstance(max_tasks, bool)
                                      or not 1 <= max_tasks <= MAX_TASKS_CEILING):
            raise AuditServiceRefused("max_tasks_invalid")
        self.service, self.audit_id = service, audit_id
        self.executor, self.bus, self.workflow = executor, bus, workflow
        self.observer, self.collector, self.progress = observer, collector, progress
        # The bounded repair owner, or None: an unwired owner admits nothing and changes nothing.
        self.repair = repair
        self.max_tasks, self.revision, self.release_id = max_tasks, revision, release_id
        self.partitions = partitions
        self.owner = owner or ("audit-service:" + uuid4().hex)
        self.sleep, self.interval, self.schedule = sleep, interval, schedule
        self.stopping = False
        self.stop_reason: str | None = None
        self.completed = 0
        # Settled executions of THIS run by analysis outcome; the durable rows stay the authority.
        self.analysis: dict = {}
        # The last progress observation of this run, as observed facts only; it never decides
        # admission, never stops this service and never changes an execution's own outcome.
        self.last_progress: dict | None = None
        # The last repair tick of this run, as bounded facts only; like the observation above it
        # decides no admission, stops nothing and reinterprets no execution.
        self.last_repair: dict | None = None

    def stop(self) -> None:
        """Interrupt shutdown: no new assignment is bound; a bound task keeps its own record."""
        self.stopping = True

    # ----- durable narrow state ---------------------------------------------------------------
    def state(self) -> dict:
        with self.service.store.transaction() as tx:
            return tx.get(STATE_BUCKET, self.audit_id) or _default_state(self.audit_id)

    def _write(self, *, count: bool = False, **changes) -> dict:
        with self.service.store.transaction() as tx:
            row = tx.get(STATE_BUCKET, self.audit_id) or _default_state(self.audit_id)
            row.update(changes)
            if count:
                row["completed_tasks"] = int(row.get("completed_tasks") or 0) + 1
            row["updated_at"] = utcnow()
            tx.put(STATE_BUCKET, self.audit_id, row)
            return row

    # ----- startup ----------------------------------------------------------------------------
    def reconcile(self) -> dict:
        """Startup reconciliation against the durable task rows, never an inferred repeat.

        A bound task is settled here ONLY when the stored row succeeded and still carries this
        assignment's correlation. A running, queued, retried, failed or unreadable attempt keeps
        its evidence and stops admission: repeating it is an operator decision, not this service's.
        A recorded predecessor that did not succeed blocks the next admission until the durable
        record itself shows the operator acted - the row succeeded, or its execution generation
        advanced through the existing recovery or cancellation path.
        """
        current = self.state().get("current_task")
        settled = None
        if current:
            with self.service.store.transaction() as tx:
                task = tx.get("tasks", current["task_id"])
            bound = (isinstance(task, dict) and (task.get("message") or {}).get("correlation_id")
                     == current.get("correlation_id"))
            status = task.get("status") if isinstance(task, dict) else None
            if not (bound and status == "succeeded"):
                return {"status": "reconciliation_required", "task_id": current["task_id"],
                        "reason_code": "unknown_execution" if not bound else _stop_code(status)}
            facts = self._checkpoint_facts(current.get("partition_id"))
            # The outcome comes from the durable result of the attempt itself, never from this
            # process's memory: a restart re-reads what the execution recorded and repeats nothing.
            analysis = analysis_facts(task.get("result"))
            self._write(current_task=None, count=True,
                        last_task={**current, "status": status, "task_generation": task.get("generation"),
                                   "settled_at": utcnow(), **facts, **analysis})
            settled = {"status": "settled", "task_id": current["task_id"], **facts, **analysis}
        blocked = self._predecessor_block()
        if blocked is not None:
            return {"status": "reconciliation_required", **blocked}
        return settled or {"status": "clear"}

    def _predecessor_block(self) -> dict | None:
        """The recorded predecessor must have succeeded before anything new is admitted."""
        state = self.state()
        with self.service.store.transaction() as tx:
            task = tx.get("tasks", (state.get("last_task") or {}).get("task_id") or "")
        return block_reason(state, task)

    # ----- the loop ---------------------------------------------------------------------------
    def run(self, once: bool = False) -> dict:
        recovered = self.reconcile()
        summary = {"audit_id": self.audit_id, "owner": self.owner, "revision": self.revision,
                   "release_id": self.release_id, "reconciliation": recovered, "steps": [],
                   "step_count": 0, "omitted_steps": 0, "completed_tasks": 0, "analysis": {},
                   "progress": None, "repair": None, "stop_reason": None, "stopped": False}
        if recovered["status"] == "reconciliation_required":
            # No admission at all: the previous attempt's outcome is not this run's to decide.
            self._stop(recovered["reason_code"])
        else:
            self._write(owner=self.owner, stop_reason=None, started_at=utcnow())
            self._emit("operations.audit_service_started", "started",
                       attributes={"audit_id": self.audit_id, "release_id": str(self.release_id or ""),
                                   "revision": str(self.revision or ""), "max_tasks": self.max_tasks,
                                   "partitions": int(self.partitions or 0)})
            # The baseline is taken before the first admission, so every execution that already
            # settled is excluded from future strike credit (self-improvement-reference-001).
            self._observe_progress()
        while not self.stopping:
            step = self.step()
            if step["action"] != "idle":
                self._record(summary, step)
                continue
            if once:
                break
            self.sleep(self.interval)
        summary.update(completed_tasks=self.completed, analysis=dict(self.analysis),
                       progress=self.last_progress, repair=self.last_repair,
                       stop_reason=self.stop_reason, stopped=self.stopping)
        self._emit("operations.audit_service_stopped", "blocked" if self.stop_reason else "observed",
                   reason_code=self.stop_reason,
                   attributes={"audit_id": self.audit_id, "completed_tasks": self.completed,
                               "error_type": None})
        return summary

    @staticmethod
    def _record(summary: dict, step: dict) -> None:
        summary["step_count"] += 1
        summary["steps"].append(step)
        while len(summary["steps"]) > SUMMARY_STEPS:
            summary["steps"].pop(0)
            summary["omitted_steps"] += 1

    # ----- the admission guard ------------------------------------------------------------------
    def _admission_gate(self) -> dict | None:
        """Why nothing new may be admitted right now, or None.

        The one guard for every new admission, re-read from the durable records each time instead
        of trusted from startup: an observed stop, and the SAME read-only activation/release/graph
        gate that admitted this run. A paused, stale, foreign or unreadable gate is not permission
        to start work, and an unreadable one is unknown rather than clear. Nothing here writes,
        retries, acknowledges or cancels: queued work keeps its durable record, and an attempt that
        was already admitted keeps running under its own binding.
        """
        if self.stopping:
            return {"reason_code": self.stop_reason or "service_stopped"}
        try:
            activation(self.service.store, self.service.org, self.audit_id, self.revision)
        except AuditServiceRefused as exc:
            return {"reason_code": exc.reason_code}
        except Exception as exc:
            return {"reason_code": "activation_unavailable", "error_type": type(exc).__name__}
        return None

    def _stop_admission(self, gate: dict, **facts) -> dict:
        return self._stopped_step(gate["reason_code"], **facts,
                                  **{k: v for k, v in gate.items() if k != "reason_code"})

    def step(self) -> dict:
        gate = self._admission_gate()
        if gate is not None:
            return self._stop_admission(gate)
        # ONE bounded repair tick under the SAME admission gate: it may add at most one ordinary
        # assignment to the existing outbox and schedule, which the scheduler, the relay, the
        # delivery and the claim guard below then treat exactly like any other queued assignment.
        repair = self._repair_tick()
        try:
            created = self.schedule(self.service, audit_id=self.audit_id)
            pending = self._pending()
        except Exception as exc:
            return self._stopped_step("scheduler_unavailable", error_type=type(exc).__name__)
        if pending and self.state().get("current_task"):
            # A duplicate tick (or a lost attempt) cannot double-run: the durable binding is here.
            return self._stopped_step("unresolved_execution")
        assignment = pending[0] if pending else None
        delivery = None
        if assignment is not None and assignment["task"] is None:
            published = self._flush(assignment["correlation_id"])
            delivery = ({"reason_code": "publication_incomplete", "foreign_messages": 0}
                        if published is not None and not published["complete"]
                        else self._deliver(assignment))
        if created or pending:
            self._emit("operations.audit_service_scheduled", "observed",
                       attributes={"audit_id": self.audit_id, "created": int(created),
                                   "pending": len(pending),
                                   "foreign_messages": int((delivery or {}).get("foreign_messages") or 0)})
        if assignment is None:
            return {"action": "idle", "created": created, "pending": 0, "repair": repair}
        if delivery is not None and delivery["reason_code"] is not None:
            return self._stopped_step(delivery["reason_code"], task_id=assignment["task_id"],
                                      **{k: v for k, v in delivery.items() if k != "reason_code"})
        # Delivery blocks, so the gate is read again immediately before the executor: a stop or a
        # paused release observed while the message was in flight binds and executes nothing. The
        # assignment stays queued with its own record for the next admission.
        gate = self._admission_gate()
        if gate is not None:
            return self._stop_admission(gate, task_id=assignment["task_id"])
        return self._execute(assignment)

    def _execute(self, assignment: dict) -> dict:
        self._write(current_task={"task_id": assignment["task_id"], "partition_id": assignment["partition_id"],
                                  "correlation_id": assignment["correlation_id"], "bound_at": utcnow()})
        self._emit_task("started", assignment, status="bound")
        try:
            row = self.executor.execute_one(AGENT, expected={
                "id": assignment["task_id"], "correlation_id": assignment["correlation_id"],
                "statuses": {"queued"}})
        except ClaimGuardRefused as exc:
            # The claim policy would have taken another row: nothing was claimed and no provider
            # was entered. Unrelated work stays exactly where it is and this service stops.
            self._write(current_task=None)
            return self._stopped_step("claim_guard_refused", task_id=assignment["task_id"],
                                      error_type=type(exc).__name__)
        except Exception as exc:
            # The outcome of this attempt is unknown here; the durable binding stays so the next
            # start is explicit reconciliation rather than a repeat.
            return self._stopped_step("executor_exception", task_id=assignment["task_id"],
                                      error_type=type(exc).__name__)
        if row is None:
            self._write(current_task=None)
            return {"action": "idle", "reason_code": "not_claimed", "task_id": assignment["task_id"]}
        return self._settle(assignment, row)

    def _settle(self, assignment: dict, row) -> dict:
        status = row.get("status") if isinstance(row, dict) else None
        facts = self._checkpoint_facts(assignment["partition_id"])
        succeeded = status == "succeeded"
        # What the EXECUTION did and what its CONTENT was judged to be are two separate facts. An
        # execution that did not succeed has no analysis outcome at all; a settled one carries the
        # outcome its own durable result states, including unclassified.
        analysis = analysis_facts(row.get("result")) if succeeded else dict(NO_ANALYSIS)
        # `generation` is the partition checkpoint's own generation; `task_generation` is the
        # execution fence of the attempt, which only the operator's recovery or cancellation moves.
        record = {"task_id": assignment["task_id"], "partition_id": assignment["partition_id"],
                  "correlation_id": assignment["correlation_id"], "status": status or "unknown",
                  "task_generation": row.get("generation") if isinstance(row, dict) else None,
                  "settled_at": utcnow(), **facts, **analysis}
        published = self._flush(assignment["correlation_id"])
        record["published"] = None if published is None else bool(published["complete"])
        self._write(current_task=None, last_task=record, count=succeeded)
        self._emit_task("succeeded" if succeeded else "failed", assignment, status=record["status"],
                        reason_code=analysis["analysis_reason"],
                        analysis_outcome=analysis["analysis_outcome"], **facts)
        collection = self._collect()
        # One observation of THIS audit's own records after a terminal settlement. It reads only;
        # it never retries this execution, never changes its result and never stops the service.
        progress = self._observe_progress()
        # The repair lineage is reconciled from the SAME terminal evidence, so a successor that has
        # just settled reaches its truthful state even if this run stops before the next tick.
        repair = self._repair_tick()
        step = {"action": "task", **record, "collection": collection, "progress": progress,
                "repair": repair}
        if not succeeded:
            self._stop(_stop_code(status))
            return {**step, "stop_reason": self.stop_reason}
        # Finite acceptance counts every settled execution, a rejected draft included, so a run
        # cannot evade its own bound by producing content the typed boundary refuses.
        self.completed += 1
        outcome = analysis["analysis_outcome"]
        self.analysis[outcome] = self.analysis.get(outcome, 0) + 1
        if record["published"] is False:
            self._stop("publication_incomplete")
        elif self.max_tasks is not None and self.completed >= self.max_tasks:
            # Finite acceptance mode: the queued successor stays queued and keeps its evidence.
            self._stop("max_tasks_reached")
        return {**step, "stop_reason": self.stop_reason}

    # ----- durable records this service reads --------------------------------------------------
    def _pending(self) -> list[dict]:
        """This audit's own admissible assignments, oldest first.

        Only a `schedule` row of one of this audit's partitions counts, and only while its task is
        still queued or has not been submitted yet. A running, retried, failed or blocked row is
        never admitted here: the scheduler already refuses to overlap it, and this service never
        retries one.
        """
        with self.service.store.transaction() as tx:
            partitions = {p["partition_id"] for p in tx.scan("research_partitions")
                          if p["audit_id"] == self.audit_id}
            rows = []
            for row in tx.scan("schedule"):
                if row.get("partition_id") not in partitions or not row.get("task_id"):
                    continue
                task = tx.get("tasks", row["task_id"])
                if task is not None and task.get("status") != "queued":
                    continue
                correlation = ((task or {}).get("message") or {}).get("correlation_id") or row["id"]
                if task is not None and (task["message"]["what"]["action"] != ACTION
                                         or task["message"]["what"]["details"].get("audit_id") != self.audit_id):
                    continue
                rows.append({"key": row["id"], "task_id": row["task_id"], "task": task,
                             "partition_id": row["partition_id"], "correlation_id": correlation,
                             # The same order the claim policy uses once a row exists, so the
                             # guarded selection and the policy's own choice agree.
                             "at": (task or {}).get("created_at") or row.get("at") or ""})
        return sorted(rows, key=lambda r: (r["at"], r["task_id"]))

    def _checkpoint_facts(self, partition_id) -> dict:
        """Counts from the partition record itself; never a reviewed or semantic credit."""
        with self.service.store.transaction() as tx:
            partition = tx.get("research_partitions", partition_id or "")
        if not isinstance(partition, dict):
            return {"generation": None, "remaining_paths": None, "remaining_subsystems": None,
                    "open_questions": None}
        return {"generation": partition.get("generation"),
                "remaining_paths": len(partition.get("remaining_paths") or []),
                "remaining_subsystems": len(partition.get("remaining_subsystems") or []),
                "open_questions": len(partition.get("open_questions") or [])}

    # ----- transport ----------------------------------------------------------------------------
    def _flush(self, correlation_id: str):
        """Publish only THIS assignment's own outbox records; the global queue keeps its cursor."""
        if self.bus is None:
            return None
        audit = self.observer.audit_system if self.observer is not None else None
        return self.service.flush_outbox(self.bus, audit=audit, correlation_id=correlation_id)

    def _deliver(self, assignment: dict) -> dict | None:
        """Receive ONLY this assignment's own message from the existing agent stream.

        A foreign entry a read hands to this consumer is counted and left unacknowledged in this
        consumer's pending list, so the existing consumer-group recovery returns it to its owner:
        it is never acknowledged, dead-lettered, submitted or rewritten here. A `reason_code` that
        is not None stops the tick.
        """
        if self.bus is None or self.workflow is None:
            return None
        foreign = 0
        for _ in range(DELIVERY_READS):
            entry = self.bus.receive(AGENT, self.owner)
            if not entry:
                return {"reason_code": "message_missing", "foreign_messages": foreign}
            entry_id, fields = entry
            try:
                message = self.bus.decode(fields)
                mine = (message["message_id"] == assignment["task_id"]
                        and message["correlation_id"] == assignment["correlation_id"]
                        and message["who"]["recipient"] == AGENT
                        and message["what"]["action"] == ACTION
                        and message["what"]["details"].get("audit_id") == self.audit_id)
            except Exception as exc:
                return {"reason_code": "message_invalid", "error_type": type(exc).__name__,
                        "foreign_messages": foreign}
            if not mine:
                foreign += 1
                continue
            try:
                self.service.org.authorize(message)
                self.workflow.handle(message)
            except Exception as exc:
                return {"reason_code": "message_refused", "error_type": type(exc).__name__,
                        "foreign_messages": foreign}
            self.bus.ack(AGENT, entry_id)
            return {"reason_code": None, "foreign_messages": foreign}
        return {"reason_code": "message_not_delivered", "foreign_messages": foreign}

    # ----- observation --------------------------------------------------------------------------
    def _collect(self) -> dict | None:
        """Drain this process's own observation spool; a collection failure is reported, not raised."""
        if self.collector is None:
            return None
        try:
            summary = self.collector.collect()
            health = {key: summary.get(key) for key in
                      ("files", "records", "inserted", "sink_failures", "corrupt", "refused")}
        except Exception as exc:
            health = {"error_type": type(exc).__name__}
        self._write(last_collection=health)
        return health

    def _observe_progress(self) -> dict | None:
        """One goal-progress observation, or None when no observer is wired.

        The observer owns its own reads, its own state and its own degradation: this service only
        records what it returned and logs the bounded facts. An observation failure is reported as
        `degraded` and is explicitly separate from the audit execution's own success - it never
        increments a strike, never fails or retries a completed provider execution, never changes
        the stop reason and never blocks the next admission.
        """
        if self.progress is None:
            return None
        try:
            observation = self.progress.observe(self.audit_id, release_id=self.release_id,
                                                revision=self.revision)
            facts = progress_facts(observation)
        except Exception as exc:
            observation = {"status": PROGRESS_DEGRADED, "audit_id": self.audit_id,
                           "reason_code": "observer_failed", "error_type": type(exc).__name__}
            facts = progress_facts(observation)
        self.last_progress = facts
        try:
            self._write(last_progress=facts)
        except Exception as exc:      # the durable note is not the observation's authority
            facts = {**facts, "error_type": facts.get("error_type") or type(exc).__name__}
            self.last_progress = facts
        degraded = facts["status"] == PROGRESS_DEGRADED
        try:
            self._emit("operations.audit_progress_observed", "blocked" if degraded else "observed",
                       reason_code=facts["unknown"] if degraded else None,
                       attributes={key: facts[key] for key in PROGRESS_ATTRIBUTES})
        except Exception as exc:      # a refused or unavailable log never fails the audit run
            self.last_progress = {**facts, "error_type": facts.get("error_type") or type(exc).__name__}
        return self.last_progress

    # ----- the bounded repair lineage -------------------------------------------------------------
    def _repair_tick(self) -> dict | None:
        """ONE repair tick, or None when no repair owner is wired.

        The owner settles its open lineages from terminal task evidence and then admits at most one
        corrective successor, which is an ORDINARY `audit_partition` assignment in the existing
        outbox and schedule. This service does not claim, publish, prioritize or retry anything
        differently because of it: the queued successor takes its turn through the same relay,
        delivery, claim guard and fence as any other assignment. A repair failure is recorded as a
        bounded fact and is never an execution outcome, a stop reason or permission to repeat an
        attempt - a lineage this service could not reconcile stays exactly as the records say.
        """
        if self.repair is None:
            return None
        try:
            result = self.repair.tick(self.audit_id)
            settled = result.get("settled") or []
            notices = result.get("notices") or []
            admission = result.get("admission") or {}
        except Exception as exc:
            facts = {"admitted": False, "reason_code": REPAIR_UNAVAILABLE, "correction_id": None,
                     "diagnosis": None, "settled": 0, "notices": 0, "notices_published": 0,
                     "error_type": type(exc).__name__}
            self._emit("operations.audit_repair_admitted", "blocked", reason_code=REPAIR_UNAVAILABLE,
                       attributes={**repair_admission_facts({}, self.audit_id),
                                   "error_type": type(exc).__name__})
            self._write_repair(facts)
            return facts
        # The lead notice of a second refused draft is already durable with its own outbox record;
        # publishing it is the SAME correlation-scoped relay every assignment uses. A notice that
        # stays unsent keeps its record and is retried by the next tick, here or after a restart.
        published, notice_error = self._publish_notices(notices)
        by_correction = {row.get("correction_id"): row for row in notices if isinstance(row, dict)}
        for row in settled:
            self._emit_repair_settled(row, by_correction.get((row or {}).get("correction_id")))
        attributes = repair_admission_facts(admission, self.audit_id)
        reason = repair_reason(admission.get("reason_code"))
        self._emit("operations.audit_repair_admitted",
                   "succeeded" if attributes["admitted"] else "observed",
                   reason_code=None if attributes["admitted"] else reason,
                   correlation_id=attributes["correction_id"],
                   causation_id=attributes["source_task_id"], attributes=attributes)
        facts = {"admitted": attributes["admitted"], "reason_code": reason,
                 "correction_id": attributes["correction_id"],
                 "diagnosis": attributes["diagnosis"], "settled": len(settled),
                 "notices": len(notices), "notices_published": published,
                 "error_type": notice_error}
        self._write_repair(facts)
        return facts

    def _publish_notices(self, notices) -> tuple:
        """Publish the lead notices this audit still owes, through the existing scoped relay.

        Each notice is published under its own lineage correlation, so the relay reaches it even
        when no further worker assignment exists there. A transport failure is a bounded recorded
        fact: the notice record stays unsent for the next tick, and nothing about the settlement,
        the executions or the stop reason changes.
        """
        published, error = 0, None
        for row in notices if isinstance(notices, list) else []:
            row = row if isinstance(row, dict) else {}
            if row.get("published"):
                published += 1
                continue
            correlation = row.get("correlation_id")
            if type(correlation) is not str:
                continue
            try:
                relayed = self._flush(correlation)
            except Exception as exc:
                error = error or type(exc).__name__
                continue
            if relayed is not None and relayed["complete"]:
                published += 1
        return published, error

    def _emit_repair_settled(self, settled: dict, notice=None) -> None:
        """What ONE lineage achieved, with its immutable evidence attached and nothing else.

        `repaired` is every diagnosed target corrected with a justified test disposition; `deferred`
        is resumed partial work - including a corrected SUBSET of those targets - which is NOT
        subsystem acceptance; `research_required` is the second refused draft of this family,
        reported once with the notice that carried it to the lead and no third attempt started here;
        `reconciliation_required` is unknown or failed execution, which is not a strike either.
        """
        attributes = repair_settlement_facts(settled, self.audit_id, notice)
        state = attributes["state"]
        outcome = ("succeeded" if state == "repaired"
                   else "blocked" if state in {"research_required", "reconciliation_required"}
                   else "observed")
        refs = [ref for ref in ((settled or {}).get("source_execution_ref"),
                                (settled or {}).get("successor_execution_ref"))
                if type(ref) is str]
        self._emit("operations.audit_repair_settled", outcome,
                   reason_code=repair_reason((settled or {}).get("reason_code")),
                   correlation_id=attributes["correction_id"] or None,
                   causation_id=attributes["successor_task_id"], evidence_refs=refs,
                   attributes=attributes)

    def _write_repair(self, facts: dict) -> None:
        self.last_repair = facts
        try:
            self._write(last_repair=facts)
        except Exception as exc:      # the durable note is not the lineage's authority
            self.last_repair = {**facts, "error_type": facts.get("error_type") or type(exc).__name__}

    def _emit(self, event_type: str, outcome: str, *, reason_code=None, attributes=None,
              correlation_id=None, causation_id=None, evidence_refs=()) -> None:
        if self.observer is None:
            return
        self.observer.emit(event_type, outcome, reason_code=reason_code, attributes=attributes,
                           correlation_id=correlation_id, causation_id=causation_id,
                           evidence_refs=evidence_refs,
                           severity="warning" if outcome in {"failed", "blocked"} else "info")

    def _emit_task(self, outcome: str, assignment: dict, *, status: str, generation=None,
                   remaining_paths=None, remaining_subsystems=None, open_questions=None,
                   analysis_outcome=None, reason_code=None) -> None:
        self._emit("operations.audit_service_task", outcome, reason_code=reason_code,
                   correlation_id=assignment["correlation_id"], causation_id=assignment["task_id"],
                   attributes={"audit_id": self.audit_id, "task_id": assignment["task_id"],
                               "partition_id": assignment["partition_id"], "generation": generation,
                               "status": status, "remaining_paths": remaining_paths,
                               "remaining_subsystems": remaining_subsystems,
                               "open_questions": open_questions,
                               "analysis_outcome": analysis_outcome})

    # ----- stopping -----------------------------------------------------------------------------
    def _stop(self, reason_code: str) -> None:
        """Close admission with a declared reason; nothing is retried and no record is rewritten."""
        self.stopping = True
        self.stop_reason = self.stop_reason or reason_code
        self._write(stop_reason=self.stop_reason)

    def _stopped_step(self, reason_code: str, **facts) -> dict:
        self._stop(reason_code)
        return {"action": "stopped", "reason_code": reason_code, **facts}


# ----- entry points -------------------------------------------------------------------------------
def build_runner(service, args, observer, gate: dict):
    """Wire the real services around an ALREADY built observer, so the caller can release it even
    when this wiring fails. The executor is the existing one, with its existing audit runner, and
    the goal-progress observer reads the same store and the same host artifact root - it starts no
    process, enters no provider and owns no scheduler of its own."""
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.audit_repair import build_repair
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.adapters.configuration import runtime_dir
    from codex_harness.application.audit_progress import AuditProgress
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import build_collector, build_executor, redis_url

    executor = build_executor(service, observer=observer)
    artifacts = FileArtifacts(str(runtime_dir() / "artifacts"))
    progress = AuditProgress(service.store, artifacts)
    # The repair owner reads the same store and the same host artifact root. It admits nothing
    # unless the operator durably enabled THIS audit through `zeus audit-repair enable`.
    return AuditServiceRunner(service, args.audit_id, executor=executor, bus=RedisBus(redis_url()),
                              workflow=Workflow(service.store, service.org), observer=observer,
                              collector=build_collector(service.store, observer), progress=progress,
                              repair=build_repair(service, artifacts),
                              max_tasks=args.max_tasks, revision=gate["revision"],
                              release_id=gate["release_id"], partitions=gate["partitions"])


def run(service, args) -> dict:
    """One host owner per configured runtime. The lock and the read-only activation gate come
    first: a duplicate owner, an inactive or stale activation and a foreign revision all return
    before an observer, an executor, a transport or any provider exists."""
    import signal
    from contextlib import suppress

    from filelock import FileLock, Timeout

    from codex_harness.adapters.configuration import runtime_dir
    from codex_harness.bootstrap import build_observer

    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(runtime / "audit-service.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {"status": "refused", "reason_code": "audit_service_lock_busy", "exit_code": 1}
    observer = None
    try:
        gate = activation(service.store, service.org, args.audit_id, current_revision())
        observer = build_observer(service.store, "cli.audit-service", role=AGENT)
        runner = build_runner(service, args, observer, gate)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                # Graceful stop: no new assignment is bound; existing process-tree ownership
                # handles children and nothing lost is restarted here.
                signal.signal(getattr(signal, name), lambda *_: runner.stop())
        summary = runner.run(once=bool(args.once))
    finally:
        if observer is not None:
            with suppress(Exception):  # a close failure never replaces the original outcome
                observer.close()
        lock.release()
    # The gate's own reads win over the runner's constructor values: the receipt reports what the
    # store actually said about the activation this run was admitted under.
    # `service_stopped` is the operator's own interrupt observed at an admission point, exactly the
    # stop a signal between two ticks already exits 0 with; it is a shutdown, not a failed run.
    return {"audit_service": ACTION, **summary, **gate,
            "exit_code": 1 if summary["stop_reason"] not in
            (None, "max_tasks_reached", "service_stopped") else 0}


def status(service, args) -> dict:
    """Store read only: no executor, observer, bus, collector or provider is built."""
    audit_id = args.audit_id
    with service.store.transaction() as tx:
        state = tx.get(STATE_BUCKET, audit_id) or _default_state(audit_id)
        control = tx.get("research_control", "activation") or {}
        audit = tx.get("research_audits", audit_id)
        predecessor = tx.get("tasks", (state.get("last_task") or {}).get("task_id") or "")
        progress_state = tx.get(PROGRESS_BUCKET, audit_id)
        repair_activation = tx.get(REPAIR_ACTIVATION, audit_id)
        repair_rows = [row for row in tx.scan(REPAIR_CORRECTIONS)
                       if isinstance(row, dict) and row.get("audit_id") == audit_id]
        partitions = [p for p in tx.scan("research_partitions") if p["audit_id"] == audit_id]
        known = {p["partition_id"]: p for p in partitions}
        assignments, outcomes, held = {}, {}, []
        for row in tx.scan("schedule"):
            if row.get("partition_id") not in known or not row.get("task_id"):
                continue
            task = tx.get("tasks", row["task_id"])
            name = task.get("status", "queued") if isinstance(task, dict) else "not_submitted"
            assignments[name] = assignments.get(name, 0) + 1
            if name != "succeeded":
                continue
            facts = analysis_facts(task.get("result"))
            outcome = facts["analysis_outcome"]
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            # A rejected draft whose partition still stands at the generation it was assigned is
            # HELD: its scope is intact and waiting for an explicit, reviewed decision. This read
            # states that fact; it never retries, reassigns, completes or rewrites the history.
            if outcome == ANALYSIS_REJECTED and (
                    known[row["partition_id"]].get("generation") == facts["analysis_generation"]):
                held.append({"partition_id": row["partition_id"], "task_id": task["id"],
                             "partition_generation": facts["analysis_generation"],
                             "execution_ref": facts["analysis_ref"],
                             "reason_code": facts["analysis_reason"]})
    scope = {"total": len(partitions),
             "with_remaining_work": sum(1 for p in partitions if p["remaining_paths"]
                                        or p["remaining_subsystems"] or p["open_questions"]),
             "remaining_paths": sum(len(p["remaining_paths"]) for p in partitions),
             "remaining_subsystems": sum(len(p["remaining_subsystems"]) for p in partitions),
             "open_questions": sum(len(p["open_questions"]) for p in partitions),
             "max_generation": max((p["generation"] for p in partitions), default=None)}
    analysis = {"outcomes": outcomes, "held_partitions": len(held),
                "held": sorted(held, key=lambda row: (row["partition_id"], row["task_id"]))}
    return {"audit_service": ACTION, "audit_id": audit_id, "known_audit": audit is not None,
            "activation": {key: control.get(key) for key in ("status", "release_id", "revision")},
            "supported_actions": [ACTION], "partitions": scope, "assignments": assignments,
            "analysis": analysis,
            # The observer's own durable state, read only: a dated observation of this audit's
            # records, never a completion, a cause or a promise about the current run.
            "progress": progress_view(progress_state),
            # The bounded repair lineage, read only: the opt-in, each source task -> diagnosis ->
            # successor -> settlement, and the separate counts. A held rejection above stays held
            # until a lineage of its own reports `repaired`; nothing here rewrites that history.
            "repair": repair_view(repair_activation, repair_rows),
            "admission_blocked": block_reason(state, predecessor),
            **{key: state.get(key) for key in ("owner", "current_task", "last_task", "stop_reason",
                                               "completed_tasks", "last_collection", "last_progress",
                                               "last_repair", "started_at", "updated_at")},
            "exit_code": 0}


def execute(service, args) -> dict:
    try:
        if args.audit_service_command == "run":
            return run(service, args)
        return status(service, args)
    except Exception as exc:
        return refusal(exc)

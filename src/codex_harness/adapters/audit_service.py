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
"""
from __future__ import annotations

import time
from dataclasses import asdict
from uuid import uuid4

from codex_harness.adapters.operation_cli import refusal
from codex_harness.application.scheduling import schedule_audits
from codex_harness.application.workflow import ClaimGuardRefused
from codex_harness.domain.model import ContractError, digest, utcnow

__all__ = ["AuditServiceRefused", "AuditServiceRunner", "activation", "add_parser", "block_reason",
           "execute", "refusal", "run", "status"]

AGENT = "worker:github"
ACTION = "audit_partition"
STATE_BUCKET = "audit_service"
# One tick reads at most this many stream entries while looking for its own assignment. A foreign
# entry is counted and left pending for its owner: never acknowledged, dead-lettered or handled.
DELIVERY_READS = 8
IDLE_SECONDS = 5.0
MAX_TASKS_CEILING = 100
SUMMARY_STEPS = 50
# A task status this service can name, so a stop reason is always a declared code.
STOP_BY_STATUS = {"failed": "task_failed", "retry": "task_retry", "blocked": "task_blocked",
                  "expired": "task_expired", "cancelled": "task_cancelled",
                  "superseded": "task_superseded", "running": "task_unresolved",
                  "queued": "task_unresolved"}


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
            "started_at": None, "updated_at": None}


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
    """

    def __init__(self, service, audit_id: str, *, executor=None, bus=None, workflow=None,
                 observer=None, collector=None, max_tasks=None, revision=None, release_id=None,
                 partitions=None, owner=None, sleep=time.sleep, interval: float = IDLE_SECONDS,
                 schedule=schedule_audits):
        if type(audit_id) is not str or not audit_id.strip():
            raise AuditServiceRefused("audit_id_invalid")
        if max_tasks is not None and (type(max_tasks) is not int or isinstance(max_tasks, bool)
                                      or not 1 <= max_tasks <= MAX_TASKS_CEILING):
            raise AuditServiceRefused("max_tasks_invalid")
        self.service, self.audit_id = service, audit_id
        self.executor, self.bus, self.workflow = executor, bus, workflow
        self.observer, self.collector = observer, collector
        self.max_tasks, self.revision, self.release_id = max_tasks, revision, release_id
        self.partitions = partitions
        self.owner = owner or ("audit-service:" + uuid4().hex)
        self.sleep, self.interval, self.schedule = sleep, interval, schedule
        self.stopping = False
        self.stop_reason: str | None = None
        self.completed = 0

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
            self._write(current_task=None, count=True,
                        last_task={**current, "status": status, "task_generation": task.get("generation"),
                                   "settled_at": utcnow(), **facts})
            settled = {"status": "settled", "task_id": current["task_id"], **facts}
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
                   "step_count": 0, "omitted_steps": 0, "completed_tasks": 0, "stop_reason": None,
                   "stopped": False}
        if recovered["status"] == "reconciliation_required":
            # No admission at all: the previous attempt's outcome is not this run's to decide.
            self._stop(recovered["reason_code"])
        else:
            self._write(owner=self.owner, stop_reason=None, started_at=utcnow())
            self._emit("operations.audit_service_started", "started",
                       attributes={"audit_id": self.audit_id, "release_id": str(self.release_id or ""),
                                   "revision": str(self.revision or ""), "max_tasks": self.max_tasks,
                                   "partitions": int(self.partitions or 0)})
        while not self.stopping:
            step = self.step()
            if step["action"] != "idle":
                self._record(summary, step)
                continue
            if once:
                break
            self.sleep(self.interval)
        summary.update(completed_tasks=self.completed, stop_reason=self.stop_reason,
                       stopped=self.stopping)
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

    def step(self) -> dict:
        if self.stopping:
            return {"action": "idle"}
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
            return {"action": "idle", "created": created, "pending": 0}
        if delivery is not None and delivery["reason_code"] is not None:
            return self._stopped_step(delivery["reason_code"], task_id=assignment["task_id"],
                                      **{k: v for k, v in delivery.items() if k != "reason_code"})
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
        # `generation` is the partition checkpoint's own generation; `task_generation` is the
        # execution fence of the attempt, which only the operator's recovery or cancellation moves.
        record = {"task_id": assignment["task_id"], "partition_id": assignment["partition_id"],
                  "correlation_id": assignment["correlation_id"], "status": status or "unknown",
                  "task_generation": row.get("generation") if isinstance(row, dict) else None,
                  "settled_at": utcnow(), **facts}
        published = self._flush(assignment["correlation_id"])
        record["published"] = None if published is None else bool(published["complete"])
        self._write(current_task=None, last_task=record, count=succeeded)
        self._emit_task("succeeded" if succeeded else "failed", assignment, status=record["status"],
                        **facts)
        collection = self._collect()
        step = {"action": "task", **record, "collection": collection}
        if not succeeded:
            self._stop(_stop_code(status))
            return {**step, "stop_reason": self.stop_reason}
        self.completed += 1
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

        A foreign entry is counted and left pending for its owner: it is never acknowledged,
        dead-lettered, submitted or rewritten here. A `reason_code` that is not None stops the tick.
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

    def _emit(self, event_type: str, outcome: str, *, reason_code=None, attributes=None,
              correlation_id=None, causation_id=None) -> None:
        if self.observer is None:
            return
        self.observer.emit(event_type, outcome, reason_code=reason_code, attributes=attributes,
                           correlation_id=correlation_id, causation_id=causation_id,
                           severity="warning" if outcome in {"failed", "blocked"} else "info")

    def _emit_task(self, outcome: str, assignment: dict, *, status: str, generation=None,
                   remaining_paths=None, remaining_subsystems=None, open_questions=None) -> None:
        self._emit("operations.audit_service_task", outcome,
                   correlation_id=assignment["correlation_id"], causation_id=assignment["task_id"],
                   attributes={"audit_id": self.audit_id, "task_id": assignment["task_id"],
                               "partition_id": assignment["partition_id"], "generation": generation,
                               "status": status, "remaining_paths": remaining_paths,
                               "remaining_subsystems": remaining_subsystems,
                               "open_questions": open_questions})

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
    when this wiring fails. The executor is the existing one, with its existing audit runner."""
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import build_collector, build_executor, redis_url

    executor = build_executor(service, observer=observer)
    return AuditServiceRunner(service, args.audit_id, executor=executor, bus=RedisBus(redis_url()),
                              workflow=Workflow(service.store, service.org), observer=observer,
                              collector=build_collector(service.store, observer),
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
    return {"audit_service": ACTION, **summary, **gate,
            "exit_code": 1 if summary["stop_reason"] not in (None, "max_tasks_reached") else 0}


def status(service, args) -> dict:
    """Store read only: no executor, observer, bus, collector or provider is built."""
    audit_id = args.audit_id
    with service.store.transaction() as tx:
        state = tx.get(STATE_BUCKET, audit_id) or _default_state(audit_id)
        control = tx.get("research_control", "activation") or {}
        audit = tx.get("research_audits", audit_id)
        predecessor = tx.get("tasks", (state.get("last_task") or {}).get("task_id") or "")
        partitions = [p for p in tx.scan("research_partitions") if p["audit_id"] == audit_id]
        known = {p["partition_id"] for p in partitions}
        assignments: dict = {}
        for row in tx.scan("schedule"):
            if row.get("partition_id") not in known or not row.get("task_id"):
                continue
            task = tx.get("tasks", row["task_id"])
            name = task.get("status", "queued") if isinstance(task, dict) else "not_submitted"
            assignments[name] = assignments.get(name, 0) + 1
    scope = {"total": len(partitions),
             "with_remaining_work": sum(1 for p in partitions if p["remaining_paths"]
                                        or p["remaining_subsystems"] or p["open_questions"]),
             "remaining_paths": sum(len(p["remaining_paths"]) for p in partitions),
             "remaining_subsystems": sum(len(p["remaining_subsystems"]) for p in partitions),
             "open_questions": sum(len(p["open_questions"]) for p in partitions),
             "max_generation": max((p["generation"] for p in partitions), default=None)}
    return {"audit_service": ACTION, "audit_id": audit_id, "known_audit": audit is not None,
            "activation": {key: control.get(key) for key in ("status", "release_id", "revision")},
            "supported_actions": [ACTION], "partitions": scope, "assignments": assignments,
            "admission_blocked": block_reason(state, predecessor),
            **{key: state.get(key) for key in ("owner", "current_task", "last_task", "stop_reason",
                                               "completed_tasks", "last_collection", "started_at",
                                               "updated_at")},
            "exit_code": 0}


def execute(service, args) -> dict:
    try:
        if args.audit_service_command == "run":
            return run(service, args)
        return status(service, args)
    except Exception as exc:
        return refusal(exc)

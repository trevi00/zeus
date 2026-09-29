"""The durable, fenced task graph (the part S4 moved ahead: guards and the execution-identity helpers).

Layer: application
Context: coordination
Owns: ClaimGuardRefused, check_expected, require_expected, CONTAINED_PROVIDER_CAUSES and the static
    `Workflow._attempt_outcome` / `Workflow._same_execution` (M7 `application/workflow.py`, moved ahead in S4
    unchanged: lead decision Option A; execution_time's deadline containment records the attempt outcome)
    and the lease operations claim, _owned, contain_time, heartbeat, remaining_seconds, complete, fail_execution,
    fail, _next and snapshot (S4, lead decision Option A: the owner operations RunTask/ReviewDecisions write)
Does not own: submit, cancel, request_rebase, handle and context (S5: submit and handle park terminal
    operations), intake's ticket binding and the research adoption gate (injected), the clocks (injected)
Entry points: ClaimGuardRefused, check_expected, require_expected, CONTAINED_PROVIDER_CAUSES, Workflow
Contracts: INV-LOCAL-CYCLE-001, INV-METRIC-001, INV-EXECUTION-IDENTITY-001
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta

from codex_harness.coordination.application.execution_budget import (
    aware_time,
    block_execution,
    deadline_time,
    positive_integer,
    retry_limit,
)
from codex_harness.coordination.application.execution_fence import advance as advance_fence
from codex_harness.coordination.application.execution_fence import require_current as require_current_fence
from codex_harness.coordination.application.execution_notices import record as execution_notice
from codex_harness.coordination.application.execution_time import (
    CLOCK_TOLERANCE_SECONDS,
    ExecutionTimeError,
    active,
    check_clock,
    contain_with_notice,
    deadline,
    observe_domain,
    pin_clock,
    running,
)
from codex_harness.kernel.errors import ContractError, ExecutionFailure, require
from codex_harness.kernel.ids import SYSTEM_IDS, digest, utcnow
from codex_harness.kernel.message import envelope
from codex_harness.kernel.policy import POLICY


class ClaimGuardRefused(ContractError):
    """The row the claim policy would take is not the one the caller pre-selected."""


def check_expected(tx, bucket: str, expected: dict | None) -> None:
    """INV-LOCAL-CYCLE-001: an optional execution guard, validated inside the claim transaction
    before any row is claimed. `expected` names the row (`id`), its `correlation_id` and the
    `statuses` it may still be in. Unguarded callers (`expected is None`) keep the existing policy."""
    if expected is None:
        return
    require(isinstance(expected, dict) and isinstance(expected.get("id"), str)
            and isinstance(expected.get("correlation_id"), str)
            and isinstance(expected.get("statuses"), (set, frozenset, list, tuple)), "Invalid execution guard")
    row = tx.get(bucket, expected["id"])
    if row is None:
        raise ClaimGuardRefused("Expected execution missing: " + expected["id"])
    message = row.get("message")
    correlation = message.get("correlation_id") if isinstance(message, dict) else None
    if correlation != expected["correlation_id"]:
        raise ClaimGuardRefused("Expected execution correlation changed: " + expected["id"])
    if row.get("status") not in set(expected["statuses"]):
        raise ClaimGuardRefused("Expected execution status changed: " + expected["id"] + " is " + str(row.get("status")))


def require_expected(row: dict, expected: dict | None) -> None:
    """The row about to be claimed must be the guarded one; anything else is refused unclaimed."""
    if expected is not None and row["id"] != expected["id"]:
        raise ClaimGuardRefused("Claim policy selected " + str(row["id"]) + " instead of " + expected["id"])


# Provider refusals of the execution's own credential (INV-RECURRENCE-001 containment; never a retry).
# A read-only profile breach is contained as well: the model reached for a tool outside its read-only
# profile, and replaying the task would spend another real call on the same breach (INV-CLAUDE-WORKER-001).
CONTAINED_PROVIDER_CAUSES = frozenset({"codex-provider-usage-limit-exceeded", "claude-provider-usage-limit-exceeded",
                                       "claude-provider-authentication-failed",
                                       "claude-provider-read-only-violation"})


class Workflow:
    """Durable, fenced task graph. External work never holds a database transaction.

    Target (§2.4, §5.2 R-D): intake's `ticket_binding` (with its `TicketSuperseded` type) and the research
    adoption gate `adoption(tx, details)` are injected, as are the clock, the id source and the monotonic clock."""

    def __init__(self, store, organization, *, ticket_binding, TicketSuperseded, adoption, clock=None, ids=None,
                 monotonic=None):
        self.store, self.org = store, organization
        self.ticket_binding, self.TicketSuperseded, self.adoption = ticket_binding, TicketSuperseded, adoption
        self.clock, self.ids, self.monotonic = clock, ids, monotonic

    @staticmethod
    def _attempt_outcome(task, status, at, error=None):
        # INV-METRIC-001: retain failures across retries; never invent legacy outcomes.
        if task['attempt'] and not any(r['attempt'] == task['attempt']
                                      for r in task.get('attempt_outcomes', [])):
            task.setdefault('attempt_outcomes', []).append(
                {'attempt': task['attempt'], 'status': status, 'at': at, 'error': error})

    def claim(self, agent: str, owner: str, lease_seconds: int = POLICY.task_lease_seconds,
              max_attempts: int | None = None, now: datetime | None = None,
              expected: dict | None = None) -> dict | None:
        self.org.actor(agent)
        positive_integer(lease_seconds, "Lease duration")
        if max_attempts is not None:
            positive_integer(max_attempts, "Retry limit")
        require(isinstance(owner, str) and bool(owner.strip()), "Execution owner required")
        requested_now = now
        now = aware_time(now, self.clock)
        require(requested_now is None or abs((now - aware_time(clock=self.clock)).total_seconds()) <= CLOCK_TOLERANCE_SECONDS,
                'Injected execution time differs from host clock')
        try:
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self.store.transaction() as tx:
            check_expected(tx, "tasks", expected)
            live = running(tx, self.org, requested_now, clock=self.clock, monotonic=self.monotonic)
            if len(live) >= POLICY.max_active_executions or any(row.get("agent", row.get("actor")) == agent for row in live):
                return None
            candidates = []
            for row in tx.scan('tasks'):
                if row.get('status') not in {'queued', 'running', 'retry'}:
                    continue
                try:
                    created = deadline_time(row.get('created_at'))
                    require(created is not None, 'Creation time required')
                except ContractError:
                    block_execution(tx, row, 'tasks', 'InvalidExecutionOrder', aware_time(requested_now, self.clock), self.org)
                    continue
                candidates.append((created, row['id'], row))
            for _, _, task in sorted(candidates, key=lambda item: item[:2]):
                if task["agent"] != agent or task["status"] not in {"queued", "running", "retry"}:
                    continue
                now = aware_time(requested_now, self.clock)
                if task['status'] == 'running':
                    try:
                        if active(task, 'tasks', now, monotonic=self.monotonic):
                            continue
                    except ExecutionTimeError as exc:
                        contain_with_notice(tx, self.org, task, 'tasks', exc.reason, now, exc.observation)
                        continue
                try:
                    self.ticket_binding(tx, task["message"]["what"]["details"])
                except ContractError as exc:
                    task.update(status="blocked", error=str(exc))
                    tx.put("tasks", task["id"], task)
                    execution_notice(tx, self.org, task, 'tasks', 'ticket_binding_changed', now.isoformat())
                    continue
                if task["message"]["what"]["action"] in {"plan", "implement"}:
                    try:
                        self.adoption(tx, task["message"]["what"]["details"])
                    except ContractError:
                        continue
                if task["status"] == "running":
                    self._attempt_outcome(task, "lease_expired", now.isoformat())
                try:
                    deadline = deadline_time(task.get("execution_deadline", task["message"]["when"]["deadline"]))
                except ContractError:
                    block_execution(tx, task, "tasks", "InvalidExecutionDeadline", now, self.org)
                    continue
                dependencies = [tx.get("tasks", dep) for dep in task["message"]["when"]["after"]]
                terminal_dependency = any(d["status"] in {"failed", "cancelled", "expired"}
                                          for d in dependencies)
                if deadline and deadline <= now:
                    task.update(status="expired", error="deadline exceeded")
                elif terminal_dependency:
                    task.update(status="cancelled", error="dependency did not succeed")
                elif any(d["status"] != "succeeded" for d in dependencies):
                    continue
                else:
                    try:
                        limit = retry_limit(tx, task, "tasks", max_attempts, now, self.org)
                    except ContractError:
                        block_execution(tx, task, "tasks", "InvalidRetryBudget", now, self.org)
                        continue
                    if limit is None:
                        continue
                    if task["attempt"] >= limit:
                        task.update(status="failed", error="attempt budget exhausted")
                        tx.put("tasks", task["id"], task)
                        execution_notice(tx, self.org, task, 'tasks', 'budget_exhausted', now.isoformat())
                        continue
                    now = aware_time(requested_now, self.clock)
                    if deadline is not None and deadline <= now:
                        contain_with_notice(tx, self.org, task, 'tasks', 'deadline_exceeded', now)
                        continue
                    lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
                    require_expected(task, expected)  # before the fence, the lease and any provider entry
                    try:
                        advance_fence(tx, "tasks", task["id"], task["generation"] + 1, owner, clock=self.clock)
                    except ContractError:
                        block_execution(tx, task, "tasks", "ExecutionGenerationRegressed", now, self.org)
                        continue
                    task.update(status="running", attempt=task["attempt"] + 1,
                                generation=task["generation"] + 1, lease_owner=owner,
                                lease_until=min(datetime.fromisoformat(lease_until), deadline).isoformat()
                                if deadline else lease_until)
                    pin_clock(task, 'tasks', now, datetime.fromisoformat(task['lease_until']), clock=self.clock,
                              monotonic=self.monotonic)
                    tx.put("tasks", task["id"], task)
                    return task
                tx.put("tasks", task["id"], task)
                execution_notice(tx, self.org, task, 'tasks',
                                 'deadline_exceeded' if task['status'] == 'expired' else 'dependency_failed', now.isoformat())
        return None

    @staticmethod
    def _same_execution(current, task):
        keys = ('id', 'generation', 'attempt', 'lease_owner', 'agent', 'actor', 'recovery_sequence')
        for key in keys:
            default = 0 if key == 'recovery_sequence' else None
            left, right = current.get(key, default), task.get(key, default)
            if type(left) is not type(right) or left != right:
                return False
        return True

    def _owned(self, tx, task: dict, now: datetime | None = None) -> dict:
        bucket = task.get("_bucket", "tasks")
        require(bucket in {"tasks", "decisions_pending"}, "Invalid execution aggregate")
        current = tx.get(bucket, task["id"])
        now = aware_time(now, self.clock)
        require(current is not None and current["status"] == "running"
                and self._same_execution(current, task),
                "Stale or expired task execution")
        # INV-EXECUTION-IDENTITY-001: the row itself is checked against the durable fence on every
        # write, so a row restored to an older running generation cannot re-arm its old holder.
        require_current_fence(tx, bucket, current["id"], current.get("generation"), current.get("lease_owner"))
        require(active(current, bucket, now, monotonic=self.monotonic), "Stale or expired task execution")
        observe_domain(tx, current, bucket, now)
        return current

    def contain_time(self, task, error):
        if not isinstance(error, ExecutionTimeError):
            return None
        bucket = task.get('_bucket', 'tasks')
        require(bucket in {'tasks', 'decisions_pending'}, 'Invalid execution aggregate')
        with self.store.transaction() as tx:
            row = tx.get(bucket, task['id'])
            if not row or not self._same_execution(row, task):
                return None
            if row['status'] != 'running':
                return row if row['status'] in {'expired', 'blocked'} else None
            # Re-evaluate after business rollback; never apply an old observation to repaired state.
            now = aware_time(clock=self.clock)
            try:
                active(row, bucket, now, monotonic=self.monotonic)
            except ExecutionTimeError as current_error:
                return contain_with_notice(tx, self.org, row, bucket, current_error.reason, now,
                                           current_error.observation)
            return None

    @contextmanager
    def _execution_transaction(self, task):
        try:
            with self.store.transaction() as tx:
                yield tx
        except ExecutionTimeError as exc:
            self.contain_time(task, exc)
            raise

    def heartbeat(self, task: dict, seconds: int = POLICY.task_lease_seconds) -> None:
        positive_integer(seconds, "Lease duration")
        try:
            lease_until = (aware_time(clock=self.clock) + timedelta(seconds=seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self._execution_transaction(task) as tx:
            current = self._owned(tx, task)
            now = aware_time(clock=self.clock)
            lease_until = (now + timedelta(seconds=seconds)).isoformat()
            due = deadline(current, task.get('_bucket', 'tasks'))
            if due is not None:
                lease_until = min(datetime.fromisoformat(lease_until), due).isoformat()
            current["lease_until"] = lease_until
            pin_clock(current, task.get('_bucket', 'tasks'), now, datetime.fromisoformat(lease_until), renew=True,
                      clock=self.clock, monotonic=self.monotonic)
            tx.put(task.get("_bucket", "tasks"), task["id"], current)
            return current

    def remaining_seconds(self, task, maximum):
        from codex_harness.coordination.application.execution_time import DOMAIN
        with self._execution_transaction(task) as tx:
            row = self._owned(tx, task)
            now = aware_time(clock=self.clock)
            due = deadline(row, task.get('_bucket', 'tasks'))
            remaining = min(maximum, (due - now).total_seconds()) if due is not None else maximum
            elapsed, pin = check_clock(row, now, (self.monotonic or time.monotonic)(), DOMAIN)
            if elapsed is not None and pin.get('deadline_remaining') is not None:
                remaining = min(remaining, pin['deadline_remaining'] - elapsed)
            if remaining <= 0:
                raise ExecutionTimeError('deadline_exceeded')
            return remaining

    def complete(self, task: dict, result: dict, commands: list[dict] | None = None, accept=None) -> dict:
        """`accept(tx, current)` runs inside the same transaction that durably records the outcome
        (INV-OBSERVATION-001): the execution's unconfirmed marker is cleared only with the acceptance."""
        require(isinstance(result, dict), "Task result must be an object")
        with self._execution_transaction(task) as tx:
            current = self._owned(tx, task)
            try:
                self.ticket_binding(tx, task["message"]["what"]["details"])
            except self.TicketSuperseded as exc:
                self._attempt_outcome(current, "superseded", utcnow(self.clock))
                current.update(status="superseded", result=result, error=str(exc), completed_at=utcnow(self.clock))
                tx.put("tasks", task["id"], current)
                execution_notice(tx, self.org, current, 'tasks', 'ticket_superseded', utcnow(self.clock))
                if accept is not None:
                    accept(tx, current)
                return current
            self._attempt_outcome(current, "succeeded", utcnow(self.clock))
            current.update(status="succeeded", result=result, completed_at=utcnow(self.clock))
            tx.put("tasks", task["id"], current)
            if accept is not None:
                accept(tx, current)
            message = task["message"]
            report = envelope("task.result", task["agent"], message["who"]["sender"],
                              message["what"]["action"], {"task_id": task["id"], "result": result},
                              message["correlation_id"], task["id"], clock=self.clock, ids=self.ids)
            self.org.authorize(report)
            tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            for command in commands or []:
                require(command["who"]["sender"] == task["agent"], "Execution cannot impersonate another sender")
                self.org.authorize(command)
                tx.put("outbox", command["message_id"], {"message": command, "sent": False})
            tx.put("events", str((self.ids or SYSTEM_IDS).uuid4()), {"type": "task.succeeded", "task_id": task["id"],
                                           "generation": task["generation"], "at": utcnow(self.clock)})
            return current

    def fail_execution(self, task: dict, error: Exception, *, transaction=None) -> dict:
        # INV-RECURRENCE-001: containment applies to this execution, not an account. A provider usage limit or an
        # authentication refusal of the credential this execution ran with is contained the same way: the SAME
        # credential would only be refused again, so it is never replayed and no other credential is substituted.
        confirmed = (isinstance(error, ExecutionFailure)
                     and error.cause in CONTAINED_PROVIDER_CAUSES)
        return self.fail(task, type(error).__name__ + ": " + str(error),
                         retryable=not confirmed,
                         failure=error.evidence if isinstance(error, ExecutionFailure) else None,
                         transaction=transaction)

    def fail(self, task: dict, error: str, retryable: bool = True,
             failure: dict | None = None, *, transaction=None) -> dict:
        require(isinstance(error, str) and bool(error), "Failure reason required")
        require(type(retryable) is bool and (failure is None or isinstance(failure, dict)), "Invalid failure fields")
        try:
            json.dumps(failure, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ContractError("Failure evidence must be finite JSON") from exc
        bucket = task.get("_bucket", "tasks")
        require(bucket in {"tasks", "decisions_pending"}, "Invalid execution aggregate")
        request = {"bucket": bucket, "task_id": task["id"], "generation": task["generation"],
                   "attempt": task["attempt"], "owner": task["lease_owner"],
                   "error": error, "retryable": retryable, "failure": failure}
        identity = digest(request)
        with (nullcontext(transaction) if transaction is not None else self._execution_transaction(task)) as tx:
            receipt = tx.get("execution_failures", identity)
            if receipt:
                current = tx.get(bucket, task["id"])
                require(receipt["request"] == request and current
                        # INV-EXECUTION-IDENTITY-001: retry state cleared the lease;
                        # the checked receipt retains its original owner, not new authority.
                        and self._same_execution({**current, 'lease_owner': receipt['request']['owner']}, task)
                        and current.get("failure_receipt") == identity
                        and current["generation"] == task["generation"] and current["attempt"] == task["attempt"]
                        and current["status"] == receipt["status"]
                        and current["error"] == error and current.get("failure") == failure,
                        "Stale failure retry after execution changed")
                return current
            current = self._owned(tx, task)
            self._attempt_outcome(current, "failed", utcnow(self.clock), error)
            if failure is not None:
                current["attempt_outcomes"][-1]["failure"] = failure
            current.update(status="retry" if retryable else "failed", error=error,
                           failure=failure, failure_receipt=identity, lease_until=None, lease_owner=None)
            tx.put(bucket, task["id"], current)
            tx.put("execution_failures", identity, {"id": identity, "request": request,
                   "status": current["status"], "at": utcnow(self.clock)})
            execution_notice(tx, self.org, current, bucket, 'execution_failed', utcnow(self.clock), identity)
            return current

    @staticmethod
    def _next(parent, sender, recipient, action, details, *, clock=None, ids=None):
        message = envelope("task.assign", sender, recipient, action, details,
                           parent["correlation_id"], parent["message_id"], clock=clock, ids=ids)
        message["where"] = parent["where"]
        message["how"] = parent["how"]
        return message

    def snapshot(self) -> str:
        with self.store.transaction() as tx:
            return digest({"tasks": tx.scan("tasks"), "sessions": tx.scan("sessions")})


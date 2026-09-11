from __future__ import annotations

import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from codex_harness.application.audit_gate import require_adoption
from codex_harness.application.execution_budget import (
    aware_time,
    block_execution,
    deadline_time,
    positive_integer,
    retry_limit,
)
from codex_harness.application.execution_fence import advance as advance_fence
from codex_harness.application.execution_fence import require_current as require_current_fence
from codex_harness.application.execution_fence import require_unused as require_unused_fence
from codex_harness.application.execution_notices import record as execution_notice
from codex_harness.application.execution_time import (
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
from codex_harness.application.tickets import TicketSuperseded, ticket_binding
from codex_harness.domain.model import (
    ContractError,
    ExecutionFailure,
    canonical,
    digest,
    envelope,
    require,
    utcnow,
)
from codex_harness.domain.policy import POLICY
from codex_harness.domain.research import require_dispatch
from codex_harness.ports import Store


class Workflow:
    """Durable, fenced task graph. External work never holds a database transaction."""

    def __init__(self, store: Store, organization):
        self.store, self.org = store, organization

    def submit(self, message: dict) -> dict:
        self.org.authorize(message)
        require(message["type"] == "task.assign", "Expected task assignment")
        deadline_time(message["when"]["deadline"])
        task_id = message["message_id"]
        with self.store.transaction() as tx:
            ticket_binding(tx, message["what"]["details"])
            if message["what"]["action"] in {"plan", "implement"}:
                require_adoption(tx, message["what"]["details"])
            old = tx.get("tasks", task_id)
            if old:
                require(old["input_hash"] == digest(message), "Conflicting task identity")
                return old
            require_unused_fence(tx, "tasks", task_id)
            dependencies = message["when"]["after"]
            require(task_id not in dependencies, "Task cannot depend on itself")
            require(all(tx.get("tasks", dep) is not None for dep in dependencies),
                    "Dependencies must exist before submission")
            task = {"id": task_id, "message": message, "input_hash": digest(message),
                    "agent": message["who"]["recipient"], "status": "queued", "attempt": 0,
                    "generation": 0, "lease_until": None, "lease_owner": None,
                    "result": None, "error": None, "created_at": utcnow()}
            tx.put("tasks", task_id, task)
            return task

    @staticmethod
    def _attempt_outcome(task, status, at, error=None):
        # INV-METRIC-001: retain failures across retries; never invent legacy outcomes.
        if task['attempt'] and not any(r['attempt'] == task['attempt']
                                      for r in task.get('attempt_outcomes', [])):
            task.setdefault('attempt_outcomes', []).append(
                {'attempt': task['attempt'], 'status': status, 'at': at, 'error': error})

    def claim(self, agent: str, owner: str, lease_seconds: int = POLICY.task_lease_seconds,
              max_attempts: int | None = None, now: datetime | None = None) -> dict | None:
        self.org.actor(agent)
        positive_integer(lease_seconds, "Lease duration")
        if max_attempts is not None:
            positive_integer(max_attempts, "Retry limit")
        require(isinstance(owner, str) and bool(owner.strip()), "Execution owner required")
        requested_now = now
        now = aware_time(now)
        require(requested_now is None or abs((now - aware_time()).total_seconds()) <= CLOCK_TOLERANCE_SECONDS,
                'Injected execution time differs from host clock')
        try:
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self.store.transaction() as tx:
            live = running(tx, self.org, requested_now)
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
                    block_execution(tx, row, 'tasks', 'InvalidExecutionOrder', aware_time(requested_now), self.org)
                    continue
                candidates.append((created, row['id'], row))
            for _, _, task in sorted(candidates, key=lambda item: item[:2]):
                if task["agent"] != agent or task["status"] not in {"queued", "running", "retry"}:
                    continue
                now = aware_time(requested_now)
                if task['status'] == 'running':
                    try:
                        if active(task, 'tasks', now):
                            continue
                    except ExecutionTimeError as exc:
                        contain_with_notice(tx, self.org, task, 'tasks', exc.reason, now, exc.observation)
                        continue
                try:
                    ticket_binding(tx, task["message"]["what"]["details"])
                except ContractError as exc:
                    task.update(status="blocked", error=str(exc))
                    tx.put("tasks", task["id"], task)
                    execution_notice(tx, self.org, task, 'tasks', 'ticket_binding_changed', now.isoformat())
                    continue
                if task["message"]["what"]["action"] in {"plan", "implement"}:
                    try:
                        require_adoption(tx, task["message"]["what"]["details"])
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
                    now = aware_time(requested_now)
                    if deadline is not None and deadline <= now:
                        contain_with_notice(tx, self.org, task, 'tasks', 'deadline_exceeded', now)
                        continue
                    lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
                    try:
                        advance_fence(tx, "tasks", task["id"], task["generation"] + 1, owner)
                    except ContractError:
                        block_execution(tx, task, "tasks", "ExecutionGenerationRegressed", now, self.org)
                        continue
                    task.update(status="running", attempt=task["attempt"] + 1,
                                generation=task["generation"] + 1, lease_owner=owner,
                                lease_until=min(datetime.fromisoformat(lease_until), deadline).isoformat()
                                if deadline else lease_until)
                    pin_clock(task, 'tasks', now, datetime.fromisoformat(task['lease_until']))
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
        now = aware_time(now)
        require(current is not None and current["status"] == "running"
                and self._same_execution(current, task),
                "Stale or expired task execution")
        # INV-EXECUTION-IDENTITY-001: the row itself is checked against the durable fence on every
        # write, so a row restored to an older running generation cannot re-arm its old holder.
        require_current_fence(tx, bucket, current["id"], current.get("generation"), current.get("lease_owner"))
        require(active(current, bucket, now), "Stale or expired task execution")
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
            now = aware_time()
            try:
                active(row, bucket, now)
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
            lease_until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self._execution_transaction(task) as tx:
            current = self._owned(tx, task)
            now = aware_time()
            lease_until = (now + timedelta(seconds=seconds)).isoformat()
            due = deadline(current, task.get('_bucket', 'tasks'))
            if due is not None:
                lease_until = min(datetime.fromisoformat(lease_until), due).isoformat()
            current["lease_until"] = lease_until
            pin_clock(current, task.get('_bucket', 'tasks'), now, datetime.fromisoformat(lease_until), renew=True)
            tx.put(task.get("_bucket", "tasks"), task["id"], current)
            return current

    def remaining_seconds(self, task, maximum):
        import time

        from codex_harness.application.execution_time import DOMAIN
        with self._execution_transaction(task) as tx:
            row = self._owned(tx, task)
            now = aware_time()
            due = deadline(row, task.get('_bucket', 'tasks'))
            remaining = min(maximum, (due - now).total_seconds()) if due is not None else maximum
            elapsed, pin = check_clock(row, now, time.monotonic(), DOMAIN)
            if elapsed is not None and pin.get('deadline_remaining') is not None:
                remaining = min(remaining, pin['deadline_remaining'] - elapsed)
            if remaining <= 0:
                raise ExecutionTimeError('deadline_exceeded')
            return remaining

    def complete(self, task: dict, result: dict, commands: list[dict] | None = None) -> dict:
        require(isinstance(result, dict), "Task result must be an object")
        with self._execution_transaction(task) as tx:
            current = self._owned(tx, task)
            try:
                ticket_binding(tx, task["message"]["what"]["details"])
            except TicketSuperseded as exc:
                self._attempt_outcome(current, "superseded", utcnow())
                current.update(status="superseded", result=result, error=str(exc), completed_at=utcnow())
                tx.put("tasks", task["id"], current)
                execution_notice(tx, self.org, current, 'tasks', 'ticket_superseded', utcnow())
                return current
            self._attempt_outcome(current, "succeeded", utcnow())
            current.update(status="succeeded", result=result, completed_at=utcnow())
            tx.put("tasks", task["id"], current)
            message = task["message"]
            report = envelope("task.result", task["agent"], message["who"]["sender"],
                              message["what"]["action"], {"task_id": task["id"], "result": result},
                              message["correlation_id"], task["id"])
            self.org.authorize(report)
            tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            for command in commands or []:
                require(command["who"]["sender"] == task["agent"], "Execution cannot impersonate another sender")
                self.org.authorize(command)
                tx.put("outbox", command["message_id"], {"message": command, "sent": False})
            tx.put("events", str(uuid4()), {"type": "task.succeeded", "task_id": task["id"],
                                           "generation": task["generation"], "at": utcnow()})
            return current

    def fail_execution(self, task: dict, error: Exception, *, transaction=None) -> dict:
        # INV-RECURRENCE-001: containment applies to this execution, not an account.
        confirmed = (isinstance(error, ExecutionFailure)
                     and error.cause == "codex-provider-usage-limit-exceeded")
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
            self._attempt_outcome(current, "failed", utcnow(), error)
            if failure is not None:
                current["attempt_outcomes"][-1]["failure"] = failure
            current.update(status="retry" if retryable else "failed", error=error,
                           failure=failure, failure_receipt=identity, lease_until=None, lease_owner=None)
            tx.put(bucket, task["id"], current)
            tx.put("execution_failures", identity, {"id": identity, "request": request,
                   "status": current["status"], "at": utcnow()})
            execution_notice(tx, self.org, current, bucket, 'execution_failed', utcnow(), identity)
            return current

    def cancel(self, task_id: str, actor: str, reason: str) -> None:
        with self.store.transaction() as tx:
            task = tx.get("tasks", task_id)
            require(task is not None and bool(reason), "Task and cancellation reason required")
            require(actor in {"conductor", task["message"]["who"]["sender"]}, "Cannot cancel task")
            require(task["status"] not in {"succeeded", "cancelled"}, "Task already terminal")
            self._attempt_outcome(task, "cancelled", utcnow(), reason)
            advance_fence(tx, "tasks", task_id, task["generation"] + 1)
            task.update(status="cancelled", error=reason, generation=task["generation"] + 1)
            tx.put("tasks", task_id, task)
            execution_notice(tx, self.org, task, 'tasks', 'operator_cancelled', utcnow())

    def request_rebase(self, task_id: str, new_base: str) -> dict:
        with self.store.transaction() as tx:
            task = tx.get("tasks", task_id)
            require(task is not None and task["status"] == "succeeded"
                    and task["result"].get("candidate"), "Completed candidate task required")
            key = digest({"task": task_id, "base": new_base})
            previous = tx.get("rebase_requests", key)
            if previous:
                return previous["message"]
            actor = self.org.actor(task["agent"], "worker")
            message = self._next(task["message"], actor.parent, actor.id, "rebase",
                                 {"candidate": task["result"]["candidate"], "new_base": new_base})
            message["when"]["after"] = [task_id]
            message["where"]["revision"] = new_base
            self.org.authorize(message)
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})
            tx.put("rebase_requests", key, {"id": key, "message": message})
            return message

    def handle(self, message: dict) -> dict:
        """Consume a report once and atomically queue the next reporting-edge command."""
        self.org.authorize(message)
        if message['type'] == 'execution.notice':
            from codex_harness.application.execution_notices import receive
            with self.store.transaction() as tx:
                return receive(tx, message)
        if message["type"] == "task.assign":
            return self.submit(message)
        require(message["type"] in {"task.result", "hook.required", "review.result"}, "Unsupported workflow message")
        with self.store.transaction() as tx:
            old = tx.get("workflow_inbox", message["message_id"])
            if old:
                require(old["hash"] == digest(message), "Conflicting report identity")
                return old["result"]
            details = message["what"]["details"]
            next_message = None
            if message["type"] == "hook.required":
                hook = tx.get("hooks", details["hook_id"])
                require(hook is not None, "Unknown hook")
                if hook["status"] == "required":
                    next_message = self._next(message, "conductor", "lead:improvement", "plan",
                                              {"objective": "Implement mandatory recurrence hook", "hook": hook,
                                               "importance": "important"})
            else:
                if "decision_id" in details:
                    decision = tx.get("decisions_pending", details["decision_id"])
                    require(decision is not None and decision["status"] == "succeeded"
                            and decision["actor"] == message["who"]["sender"]
                            and decision["result"] == details["result"], "Unproven decision result")
                    action = message["what"]["action"]
                else:
                    task = tx.get("tasks", details["task_id"])
                    require(task is not None and task["status"] == "succeeded"
                            and task["agent"] == message["who"]["sender"]
                            and task["result"] == details["result"], "Unproven task result")
                    action = task["message"]["what"]["action"]
                result = details["result"]
                recipient = message["who"]["recipient"]
                if action == "research":
                    topic = digest({"url": result["source_url"],
                                    "revision": result.get("source_details", {}).get("revision")})
                    if tx.get("research_topics", topic) is None:
                        tx.put("research_topics", topic, {"id": topic, "result": result,
                                                         "decision_id": message["message_id"]})
                        # INV-RESEARCH-001/004: retain the decision identity without approval authority.
                        tx.put("decisions_pending", message["message_id"],
                               {"id": message["message_id"], "actor": recipient, "phase": "research_lead",
                                "message": message, "input": result,
                                "status": "deferred_pending_source_audit", "attempt": 0,
                                "discovery_id": topic})
                        tx.put("research_discoveries", topic,
                               {"id": topic, "version": 1, "result": result,
                                "status": "deferred_pending_source_audit",
                                "remaining_work": ["pinned source acquisition", "exhaustive audit",
                                                   "independent research review", "conductor approval"]})
                elif action == "assess_research" and result.get("accepted") is True:
                    require_dispatch({"proposal": result})
                    tx.put("decisions_pending", message["message_id"],
                           {"id": message["message_id"], "actor": "conductor", "phase": "proposal",
                            "message": message, "input": result, "status": "pending", "attempt": 0})
                elif action in {"implement", "rebase"}:
                    tx.put("decisions_pending", message["message_id"],
                           {"id": message["message_id"], "actor": recipient, "phase": "review_lead",
                            "message": message, "input": result, "status": "pending", "attempt": 0})
                elif action == "review":
                    tx.put("decisions_pending", message["message_id"],
                           {"id": message["message_id"], "actor": "conductor", "phase": "review_conductor",
                            "message": message, "input": result, "status": "pending", "attempt": 0})
            if next_message:
                self.org.authorize(next_message)
                tx.put("outbox", next_message["message_id"], {"message": next_message, "sent": False})
            outcome = {"handled": True, "next_message": next_message}
            tx.put("workflow_inbox", message["message_id"], {"hash": digest(message), "result": outcome})
            return outcome

    @staticmethod
    def _next(parent, sender, recipient, action, details):
        message = envelope("task.assign", sender, recipient, action, details,
                           parent["correlation_id"], parent["message_id"])
        message["where"] = parent["where"]
        message["how"] = parent["how"]
        return message

    def snapshot(self) -> str:
        with self.store.transaction() as tx:
            return digest({"tasks": tx.scan("tasks"), "sessions": tx.scan("sessions")})

    def context(self, task: dict) -> str:
        with self.store.transaction() as tx:
            session = tx.get("sessions", task["agent"])
        return canonical({"assignment": task["message"], "checkpoint": session,
                          "execution": {"attempt": task["attempt"], "generation": task["generation"]}})

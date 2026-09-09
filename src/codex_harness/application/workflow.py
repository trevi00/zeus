from __future__ import annotations

import json
from contextlib import nullcontext
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
        now = aware_time(now)
        try:
            lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self.store.transaction() as tx:
            running = [row for bucket in ("tasks", "decisions_pending") for row in tx.scan(bucket)
                       if row["status"] == "running" and datetime.fromisoformat(row["lease_until"]) > now]
            if len(running) >= POLICY.max_active_executions or any(row.get("agent", row.get("actor")) == agent for row in running):
                return None
            for task in sorted(tx.scan("tasks"), key=lambda t: (t["created_at"], t["id"])):
                if task["agent"] != agent or task["status"] not in {"queued", "running", "retry"}:
                    continue
                if task["status"] == "running" and datetime.fromisoformat(task["lease_until"]) > now:
                    continue
                try:
                    ticket_binding(tx, task["message"]["what"]["details"])
                except ContractError as exc:
                    task.update(status="blocked", error=str(exc))
                    tx.put("tasks", task["id"], task)
                    continue
                if task["message"]["what"]["action"] in {"plan", "implement"}:
                    try:
                        require_adoption(tx, task["message"]["what"]["details"])
                    except ContractError:
                        continue
                if task["status"] == "running":
                    self._attempt_outcome(task, "lease_expired", now.isoformat())
                try:
                    deadline = deadline_time(task["message"]["when"]["deadline"])
                except ContractError:
                    block_execution(tx, task, "tasks", "InvalidExecutionDeadline", now)
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
                        limit = retry_limit(tx, task, "tasks", max_attempts, now)
                    except ContractError:
                        block_execution(tx, task, "tasks", "InvalidRetryBudget", now)
                        continue
                    if limit is None:
                        continue
                    if task["attempt"] >= limit:
                        task.update(status="failed", error="attempt budget exhausted")
                        tx.put("tasks", task["id"], task)
                        continue
                    task.update(status="running", attempt=task["attempt"] + 1,
                                generation=task["generation"] + 1, lease_owner=owner,
                                lease_until=lease_until)
                    tx.put("tasks", task["id"], task)
                    return task
                tx.put("tasks", task["id"], task)
        return None

    def _owned(self, tx, task: dict, now: datetime | None = None) -> dict:
        bucket = task.get("_bucket", "tasks")
        require(bucket in {"tasks", "decisions_pending"}, "Invalid execution aggregate")
        current = tx.get(bucket, task["id"])
        now = aware_time(now)
        require(current is not None and current["status"] == "running"
                and current["generation"] == task["generation"]
                and current["lease_owner"] == task["lease_owner"]
                and datetime.fromisoformat(current["lease_until"]) > now,
                "Stale or expired task execution")
        return current

    def heartbeat(self, task: dict, seconds: int = POLICY.task_lease_seconds) -> None:
        positive_integer(seconds, "Lease duration")
        try:
            lease_until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        except OverflowError as exc:
            raise ContractError("Lease duration out of timestamp range") from exc
        with self.store.transaction() as tx:
            current = self._owned(tx, task)
            current["lease_until"] = lease_until
            tx.put(task.get("_bucket", "tasks"), task["id"], current)

    def complete(self, task: dict, result: dict, commands: list[dict] | None = None) -> dict:
        require(isinstance(result, dict), "Task result must be an object")
        with self.store.transaction() as tx:
            current = self._owned(tx, task)
            try:
                ticket_binding(tx, task["message"]["what"]["details"])
            except TicketSuperseded as exc:
                self._attempt_outcome(current, "superseded", utcnow())
                current.update(status="superseded", result=result, error=str(exc), completed_at=utcnow())
                tx.put("tasks", task["id"], current)
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
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            receipt = tx.get("execution_failures", identity)
            if receipt:
                current = tx.get(bucket, task["id"])
                require(receipt["request"] == request and current
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
            return current

    def cancel(self, task_id: str, actor: str, reason: str) -> None:
        with self.store.transaction() as tx:
            task = tx.get("tasks", task_id)
            require(task is not None and bool(reason), "Task and cancellation reason required")
            require(actor in {"conductor", task["message"]["who"]["sender"]}, "Cannot cancel task")
            require(task["status"] not in {"succeeded", "cancelled"}, "Task already terminal")
            self._attempt_outcome(task, "cancelled", utcnow(), reason)
            task.update(status="cancelled", error=reason, generation=task["generation"] + 1)
            tx.put("tasks", task_id, task)

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

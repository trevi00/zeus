"""Consume workflow reports once and queue the next reporting-edge command; operator cancel and rebase requests.

Layer: application
Context: coordination
Owns: buckets workflow_inbox (report consumption), rebase_requests, and the decisions_pending/research_topics/
    research_discoveries/outbox rows a handled report queues in the same unit
Does not own: task leases and submission (Workflow / TaskOwnership), terminal-operation parking (operation_finalization,
    injected into the Workflow), execution notices' own records (execution_notices)
Entry points: MessageHandler.handle, MessageHandler.cancel, MessageHandler.cancel_in, MessageHandler.request_rebase, MessageHandler.context
Contracts: INV-MESSAGE-001, INV-IDEMPOTENCY-001, INV-OPERATION-FINALIZATION-001, INV-RESEARCH-001, INV-RESEARCH-004

M7 `Workflow.cancel/request_rebase/handle/context` (SOURCE e38aa722), moved as the MessageHandler half of design v2's
Workflow split (DESIGN-s5 §M). The bodies are M7's; they use the S4 Workflow's store, organization, injected clock,
id source and terminal-operation park.
"""

from __future__ import annotations

from codex_harness.coordination.application.execution_fence import advance as advance_fence
from codex_harness.coordination.application.execution_notices import receive
from codex_harness.coordination.application.execution_notices import record as execution_notice
from codex_harness.coordination.domain.remote_control import NOT_APPLIED, STALE_GENERATION
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import canonical, digest, utcnow
from codex_harness.research.domain.research import require_dispatch


class TaskRefused(ContractError):
    """A refused operator task command: `code` is a B1 `remote_control` refusal code; nothing was written."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MessageHandler:
    """Message consumption and operator requests over one S4 Workflow (its store, clock, ids and park)."""

    def __init__(self, workflow):
        # CE-9: parking a terminal operation's report is part of every handled unit; never a silent skip.
        require(workflow.park_terminal is not None, "Terminal-operation parking is not wired")
        self.workflow, self.store, self.org = workflow, workflow.store, workflow.org
        self.clock, self.ids = workflow.clock, workflow.ids

    def _next(self, parent, sender, recipient, action, details):
        return self.workflow._next(parent, sender, recipient, action, details, clock=self.clock, ids=self.ids)

    def cancel(self, task_id: str, actor: str, reason: str) -> None:
        try:
            with self.store.transaction() as tx:
                self.cancel_in(tx, task_id, actor, reason, expected_generation=None)
        except TaskRefused as refused:  # the local refusal stays the plain ContractError M7 raised
            raise ContractError(str(refused)) from None

    def cancel_in(self, tx, task_id: str, actor: str, reason: str, *, expected_generation: int | None = None) -> None:
        """The body of `cancel` in the CALLER's transaction (Buzz DESIGN v3 §4.3).

        A given `expected_generation` that differs from the task's refuses `stale_generation`; a terminal task
        refuses `not_applied` (both `TaskRefused`, a ContractError, with nothing written)."""
        task = tx.get("tasks", task_id)
        require(task is not None and bool(reason), "Task and cancellation reason required")
        require(actor in {"conductor", task["message"]["who"]["sender"]}, "Cannot cancel task")
        if expected_generation is not None and expected_generation != task["generation"]:
            raise TaskRefused(STALE_GENERATION, "Task generation changed")
        if task["status"] in {"succeeded", "cancelled"}:
            raise TaskRefused(NOT_APPLIED, "Task already terminal")
        self.workflow._attempt_outcome(task, "cancelled", utcnow(self.clock), reason)
        advance_fence(tx, "tasks", task_id, task["generation"] + 1, clock=self.clock)
        task.update(status="cancelled", error=reason, generation=task["generation"] + 1)
        tx.put("tasks", task_id, task)
        execution_notice(tx, self.org, task, 'tasks', 'operator_cancelled', utcnow(self.clock), ids=self.ids)

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
            with self.store.transaction() as tx:
                old = tx.get("workflow_inbox", message["message_id"])
                if old:
                    require(old["hash"] == digest(message), "Conflicting execution notice delivery")
                parked = self.workflow.park_terminal(tx, message)  # notice evidence is kept; nothing is acted on
                if parked is not None:
                    return parked
                return receive(tx, message)
        if message["type"] == "task.assign":
            return self.workflow.submit(message)
        require(message["type"] in {"task.result", "hook.required", "review.result"}, "Unsupported workflow message")
        with self.store.transaction() as tx:
            old = tx.get("workflow_inbox", message["message_id"])
            if old:
                require(old["hash"] == digest(message), "Conflicting report identity")
            # INV-OPERATION-FINALIZATION-001: same transaction as the decision this report would queue;
            # a previously handled report of a terminal operation is parked too, so a redelivery can
            # be acknowledged; its inbox row and result stay as they are.
            parked = self.workflow.park_terminal(tx, message)
            if parked is not None:
                return parked
            if old:
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

    def context(self, task: dict) -> str:
        with self.store.transaction() as tx:
            session = tx.get("sessions", task["agent"])
        return canonical({"assignment": task["message"], "checkpoint": session,
                          "execution": {"attempt": task["attempt"], "generation": task["generation"]}})

"""The local front door: durable conversation turns and their conductor handoff (part B).

Layer: application
Context: coordination
Owns: the local desk runner use case (DeskRunner): startup recovery, one turn at a time over the existing message and execution path, the bounded loop summary; its only direct write is the retry budget and deadline of its own queued task
Does not own: the desk's sessions, requests, events and receipts (intake.application.frontdesk.FrontDesk, reached through the DeskQueue port), the executor, bus, workflow and collector it is given
Entry points: DeskRunner, SUMMARY_TURNS
Contracts: local-operations-desk-001 (part B)

Moved from M7 `application/frontdesk.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §11 V16, A/evidence/rebuild/s8/frontdesk-move/transcribe.py; the module is split by owner: DeskRunner is here, FrontDesk is intake.application.frontdesk): R-d0 (each name from the target home of the module that defines it), R-d1 (`desk` is annotated with coordination's `DeskQueue` Protocol, exactly the FrontDesk methods this class calls), R-d2 (`flush_outbox` takes the service's `.flusher`), R-d3 (`__all__` names what this module defines); every other statement is M7's. M7 module docstring:

`FrontDesk` owns three buckets in the existing store transactions (`desk_sessions`,
`desk_requests`, `desk_events`). A submission persists the user's message AND the six-W outbox
assignment in one transaction, so a request that was accepted is always a request the runner can
find; nothing is answered because it was sent.

`DeskRunner` processes one request at a time over the EXISTING path: scoped outbox publication ->
the dedicated `lead:frontdesk` stream -> `Workflow.handle` -> the executor's guarded
`execute_one` -> scoped publication of the result -> the durable terminal turn. It never starts a
provider itself, never retries a failed or uncertain turn, never takes over a running owner and
never turns a model answer into an approval, a specification or an operation.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from codex_harness.coordination.ports import DeskQueue
from codex_harness.intake.domain.frontdesk import (
    FAILED,
    LEAD,
    NEEDS_RECONCILIATION,
    SUCCESS_STATE,
    DeskRefused,
    receipt_proves,
    safe_code,
    validate_answer,
)
from codex_harness.kernel.ids import digest

# One conversational turn: one attempt and a bounded provider deadline, pinned durably on this
# turn's own queued task before it can be claimed.
TASK_DEADLINE_SECONDS = 180
MAX_ATTEMPTS = 1
# A long-running desk keeps its process summary bounded: the newest turns plus counts, so a loop
# that runs for days cannot grow this dictionary without limit.
SUMMARY_TURNS = 50


class DeskRunner:
    """One local turn at a time over the existing message and execution path.

    The runner owns no provider: `executor` is the already-wrapped (budgeted) executor the entry
    point built. It never retries a failed or uncertain turn and never reserves twice.
    """

    def __init__(self, service, desk: DeskQueue, executor=None, bus=None, workflow=None,
                 observer=None, collector=None, sleep=time.sleep, interval: float = 5.0):
        self.service, self.desk, self.executor = service, desk, executor
        self.bus, self.workflow, self.observer = bus, workflow, observer
        self.collector = collector
        self.sleep, self.interval = sleep, interval
        self.stopping = False
        # A storage failure that stopped this process, kept out of the bounded turn list so the
        # summary still reports it after 50 later turns would have evicted the step.
        self.failure = None

    def stop(self) -> None:
        """Interrupt shutdown: no new turn is claimed; a claimed turn finishes its own record."""
        self.stopping = True

    # ----- startup ------------------------------------------------------------------------
    def recover(self) -> dict:
        """Startup reconciliation, never a second provider entry.

        A queued turn stays queued. A dispatching turn is finalized as its own success ONLY when
        the stored task succeeded and is bound to this turn, this turn's durable accounting receipt
        proves its settled slots and publication, and this correlation's outbox flushes completely
        now. Anything else keeps its evidence and becomes `needs_reconciliation`. Nothing here takes
        over a running provider, clears a termination mark, reserves a second time or edits the
        machine ledger.
        """
        finalized, uncertain = [], []
        for row in self.desk.dispatching():
            outcome = self._recovered(row)
            self.desk.finalize(row["id"], row["owner_token"], **outcome)
            (uncertain if outcome["status"] == NEEDS_RECONCILIATION else finalized).append(row["id"])
        return {"finalized": finalized, "needs_reconciliation": uncertain}

    def _recovered(self, row: dict) -> dict:
        with self.service.store.transaction() as tx:
            task = tx.get("tasks", row["message_id"])
        bound = (isinstance(task, dict) and task.get("status") == "succeeded"
                 and (task.get("message") or {}).get("correlation_id") == row["correlation_id"])
        uncertain = {"status": NEEDS_RECONCILIATION,
                     "task_id": row["message_id"] if isinstance(task, dict) else None}
        if not bound:
            return {**uncertain, "reason_code": "interrupted_owner"}
        if not receipt_proves(self.desk.receipt(row["id"]), row, row["message_id"]):
            # The call may have been made and even settled; without the durable receipt this turn's
            # accounting is unknown, and an unknown turn is never presented as an answer.
            return {**uncertain, "reason_code": "accounting_unknown"}
        publication = self._flush(row["correlation_id"])
        if publication is not None and not publication["complete"]:
            return {**uncertain, "reason_code": "publication_incomplete"}
        outcome = self._classify_result(row, task)
        if outcome["status"] != SUCCESS_STATE[row["intent"]]:
            return {**uncertain, "reason_code": outcome.get("reason_code") or "interrupted_owner"}
        return outcome

    # ----- one turn -----------------------------------------------------------------------
    def run(self, once: bool = False) -> dict:
        """The bounded local loop: recover, then one turn at a time until interrupted.

        The summary keeps the newest `SUMMARY_TURNS` turns plus counts, so a desk that runs for
        days holds bounded memory and still reports how many turns it omitted.
        """
        recovered = self.recover()
        summary = {"recovered": recovered, "collection": self._collect(), "turns": [],
                   "turn_count": 0, "omitted_turns": 0, "statuses": {}, "stopped": False,
                   "failure": None}
        while not self.stopping:
            step = self.step()
            if step["action"] != "idle":
                self._record(summary, step)
                continue
            if once:
                break
            self.sleep(self.interval)
        summary["stopped"] = self.stopping
        # An interrupted or idle stop is a completed run; a storage stop is a durable failure of
        # this run, and the caller turns it into a nonzero exit.
        summary["failure"] = self.failure
        return summary

    @staticmethod
    def _record(summary: dict, step: dict) -> None:
        summary["turn_count"] += 1
        key = step.get("status") or step.get("reason_code") or step["action"]
        summary["statuses"][key] = summary["statuses"].get(key, 0) + 1
        summary["turns"].append(step)
        while len(summary["turns"]) > SUMMARY_TURNS:
            summary["turns"].pop(0)
            summary["omitted_turns"] += 1

    def step(self) -> dict:
        try:
            row = None if self.stopping else self.desk.claim_next()
        except Exception as exc:
            return self._unavailable(None, exc)
        if row is None:
            return {"action": "idle"}
        request_id, owner = row["id"], row["owner_token"]
        try:
            outcome = self._turn(row)
        except Exception as exc:
            # Wiring, transport or accounting failed outside a recorded execution: the turn ends in
            # explicit uncertainty, never as an answer and never as an automatic retry.
            outcome = {"status": NEEDS_RECONCILIATION,
                       "reason_code": "dispatch_exception:" + type(exc).__name__}
        try:
            final = self.desk.finalize(request_id, owner, **outcome)
        except Exception as exc:
            # The store itself is unreachable: the turn stays `dispatching` for the next startup to
            # reconcile. It is not retried here, and no second provider entry is attempted.
            return self._unavailable(request_id, exc)
        return {"action": "turn", "request_id": request_id, "status": final["status"],
                "reason_code": final["reason_code"], "task_id": final.get("task_id"),
                "collection": self._collect()}

    def _unavailable(self, request_id, exc: Exception) -> dict:
        """A failed store leaves the durable record as it is and stops this process; the next
        startup recovers it. Only the exception TYPE is reported, never its text."""
        self.stopping = True
        step = {"action": "unavailable", "request_id": request_id,
                "reason_code": "storage_unavailable", "error_type": type(exc).__name__}
        # The first storage failure owns the outcome of this run; a later one never overwrites it.
        self.failure = self.failure or dict(step)
        return step

    def _collect(self) -> dict | None:
        """Drain this process's own observation spool into the store after a turn or recovery.

        Counts only: a collection failure is reported as its exception type and never hides a turn
        or raises into the loop.
        """
        if self.collector is None:
            return None
        try:
            summary = self.collector.collect()
        except Exception as exc:
            return {"error_type": type(exc).__name__}
        return {key: summary.get(key) for key in
                ("files", "records", "inserted", "sink_failures", "corrupt", "refused")}

    def _turn(self, row: dict) -> dict:
        correlation = row["correlation_id"]
        publication = self._flush(correlation)
        if publication is not None and not publication["complete"]:
            # The assignment is committed but not proven published: nothing external ran, so this
            # turn ends explicitly. It is never a silent success and never an automatic retry.
            return {"status": FAILED, "reason_code": "publication_incomplete"}
        delivered = self._deliver(row)
        if delivered is not None:
            return delivered
        # Only the slots this call creates belong to this turn; an earlier turn's unsettled slot is
        # its own record and never contaminates this outcome.
        before = len(getattr(self.executor, "slots", None) or [])
        try:
            result = self.executor.execute_one(LEAD, expected={
                "id": row["message_id"], "correlation_id": correlation, "statuses": {"queued"}})
        except Exception as exc:  # the executor already recorded its own task outcome
            self.desk.record_receipt(row, None, self._slots(before), False)
            return {"status": FAILED, "reason_code": "exception:" + type(exc).__name__}
        result_publication = self._flush(correlation)
        published = result_publication is None or bool(result_publication["complete"])
        outcome = self._classify_result(row, result)
        # The receipt is durable BEFORE the terminal status: a crash after it lets the next startup
        # finalize this turn, and a crash before it stays unknown.
        receipt = self.desk.record_receipt(row, outcome.get("task_id"), self._slots(before), published)
        if not receipt["settled"]:
            # A counted but unsettled machine slot: the accounting is uncertain, so the turn is
            # reconciliation work, never an answered turn.
            return {"status": NEEDS_RECONCILIATION, "reason_code": "settlement_failed",
                    "task_id": outcome.get("task_id")}
        if not published and outcome["status"] == SUCCESS_STATE[row["intent"]]:
            return {**outcome, "status": NEEDS_RECONCILIATION, "reason_code": "publication_incomplete"}
        return outcome

    def _slots(self, before: int) -> list[dict]:
        return list(getattr(self.executor, "slots", None) or [])[before:]

    def _deliver(self, row: dict) -> dict | None:
        """Receive ONLY the dedicated frontdesk stream and only this turn's exact message.

        A missing, foreign or malformed entry fails this turn; it is left pending for its own
        owner rather than acknowledged, dead-lettered or handled here.
        """
        if self.bus is None or self.workflow is None:
            return None
        entry = self.bus.receive(LEAD, "desk:" + row["id"])
        if not entry:
            return {"status": FAILED, "reason_code": "message_missing"}
        entry_id, fields = entry
        try:
            message = self.bus.decode(fields)
            valid = (message["message_id"] == row["message_id"]
                     and message["correlation_id"] == row["correlation_id"]
                     and message["who"]["recipient"] == LEAD
                     and digest(message) == row["message_sha256"])
        except Exception as exc:
            return {"status": FAILED, "reason_code": "exception:" + type(exc).__name__}
        if not valid:
            return {"status": FAILED, "reason_code": "message_foreign"}
        self.service.org.authorize(message)
        self.workflow.handle(message)
        self.bus.ack(LEAD, entry_id)
        self._bound_execution(row)
        return None

    def _bound_execution(self, row: dict) -> None:
        """Pin this turn's own attempt budget and provider deadline on its own queued task.

        `execution_deadline` and `retry_budget` are the existing execution fields the claim policy
        already reads; they are written here once, before any claim, on the task this request
        created and only while it is still queued. Nothing is extended, reset or written on another
        actor's row.
        """
        with self.service.store.transaction() as tx:
            task = tx.get("tasks", row["message_id"])
            if not isinstance(task, dict) or task.get("status") != "queued":
                return
            if (task.get("message") or {}).get("correlation_id") != row["correlation_id"]:
                return
            now = datetime.now(timezone.utc)
            changed = False
            if task.get("execution_deadline") is None:
                task["execution_deadline"] = (now + timedelta(seconds=TASK_DEADLINE_SECONDS)).isoformat()
                changed = True
            if task.get("retry_budget") is None and task.get("attempt") == 0:
                task["retry_budget"] = {"max_attempts": MAX_ATTEMPTS, "bound_at": now.isoformat(),
                                        "version": 1, "origin": "frontdesk"}
                changed = True
            if changed:
                tx.put("tasks", task["id"], task)

    def _classify_result(self, row: dict, result) -> dict:
        """Bind the answer to exactly this request; a model answer is content, never authority."""
        if not isinstance(result, dict):
            return {"status": FAILED, "reason_code": "no_execution_claimed"}
        if result.get("status") != "succeeded":
            return {"status": FAILED, "reason_code": "execution_" + safe_code(str(result.get("status")))}
        if result.get("id") != row["message_id"]:
            return {"status": FAILED, "reason_code": "result_unbound"}
        body = result.get("result")
        try:
            answer = validate_answer(body)
        except DeskRefused as exc:
            return {"status": FAILED, "reason_code": exc.reason_code, "task_id": result.get("id")}
        execution_ref = body.get("execution_ref") if isinstance(body, dict) else None
        return {"status": SUCCESS_STATE[row["intent"]], "answer": answer, "task_id": result.get("id"),
                "execution_ref": execution_ref if isinstance(execution_ref, str) else None}

    def _flush(self, correlation_id: str):
        if self.bus is None:
            return None
        from codex_harness.coordination.application.local_cycle import flush_outbox

        return flush_outbox(self.service.flusher, self.bus, self.observer, correlation_id)


__all__ = ["SUMMARY_TURNS", "DeskRunner"]

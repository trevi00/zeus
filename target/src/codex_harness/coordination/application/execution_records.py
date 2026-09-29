"""ExecutionRecords: the coordination-owned writes RunTask's failure and reconciliation paths make (DESIGN-run-task §8).

Layer: application
Context: coordination
Owns: ExecutionRecords, the implementation of execution.ports ExecutionRecords. It makes the writes M7
    `Executor._fail_task/_record_reconciliation_block/_block_for_reconciliation` performed inline on coordination's
    buckets: the execution notice, the `events` append, the terminal task-row write, and the diagnosis request in
    `decisions_pending`. The bodies are M7's, unchanged; each operation joins the caller's `tx` (§2.9 rule 2)
Does not own: the failure disposition (RunTask decides; coordination records); the evidence receipt (the caller's
    artifact store, passed as a callable so it is written only when M7 wrote it)
Entry points: ExecutionRecords
Contracts: INV-RECURRENCE-001, INV-OBSERVATION-001, INV-SESSION-001
"""

from __future__ import annotations

from codex_harness.coordination.application import execution_notices
from codex_harness.coordination.application.events import EventJournal
from codex_harness.kernel.ids import digest


class ExecutionRecords:
    """A stateless owner-operation set (one instance per composition)."""

    def __init__(self, organization):
        self.organization = organization
        self.events = EventJournal()

    def notice(self, tx, row: dict, bucket: str, code: str, at: str, identity: str | None = None):
        return execution_notices.record(tx, self.organization, row, bucket, code, at, identity)

    def append_event(self, tx, identity: str, body: dict) -> None:
        self.events.append(tx, identity, body)

    def record_row(self, tx, bucket: str, row: dict) -> None:
        """The terminal write of a task/decision row whose fence the caller re-checked in this `tx`."""
        tx.put(bucket, row["id"], row)

    def request_diagnosis(self, tx, task: dict, agent: str, error, current: dict, parent: str, receipt) -> None:
        """INV-RECURRENCE-001: a failure commits together with its diagnosis request for the agent's lead. M7
        `_fail_task` body, unchanged: the request id is the (task, attempt) digest; an existing request is kept,
        and only then is the evidence receipt written (`receipt()` returns the artifact ref)."""
        observation_id = digest({"task": task["id"], "attempt": task["attempt"]})
        if tx.get("decisions_pending", observation_id) is None:
            receipt_ref = receipt()
            tx.put("decisions_pending", observation_id, {"id": observation_id,
                   "actor": parent, "phase": "diagnose", "message": task["message"],
                   "input": {"error": str(error), "occurrence_id": observation_id,
                             "source_task_id": task["id"],
                             "source_actor": agent, "evidence_ref": receipt_ref,
                             "known_causes": [{"root_cause": h["root_cause"], "scope": h["scope"]}
                                              for h in tx.scan("incidents")]},
                   "status": "pending", "attempt": 0})

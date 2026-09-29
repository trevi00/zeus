"""Session checkpoints: the one writer of the `sessions` bucket, fenced on the coordination lease.

Layer: application
Context: coordination
Owns: SessionCheckpoints.checkpoint, the `sessions` bucket's one writer (M7 `Harness.checkpoint`, moved ahead in S4:
    RunTask's turn loop; workflow and ids injected)
Does not own: the checkpoint's content (the caller's state)
Entry points: SessionCheckpoints
Contracts: INV-SESSION-001
"""

from __future__ import annotations

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import SYSTEM_IDS


class SessionCheckpoints:
    def __init__(self, store, organization, *, workflow, ids=None):
        self.store = store
        self.org = organization
        self.workflow = workflow  # DESIGN-run-task D2: composition supplies the Workflow (it needs injected dependencies)
        self.ids = ids

    def checkpoint(self, agent: str, expected_generation: int, state: dict, execution: dict | None = None) -> dict:
        self.org.actor(agent)
        require(all(state.get(k) for k in ("next_action", "source_revision", "graph_snapshot")),
                "Incomplete checkpoint")
        with self.store.transaction() as tx:
            if execution:
                self.workflow._owned(tx, execution)  # DESIGN-run-task D2: the injected Workflow, not a local import
            old = tx.get("sessions", agent) or {"generation": 0}
            require(old["generation"] == expected_generation, "Stale session writer")
            record = {"agent_id": agent, "generation": expected_generation + 1,
                      "session_id": str((self.ids or SYSTEM_IDS).uuid4()),  # DESIGN-run-task D2: injected ids
                      "checkpoint": state}
            tx.put("sessions", agent, record)
            return record

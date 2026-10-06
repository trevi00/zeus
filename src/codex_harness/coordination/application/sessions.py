"""Session checkpoints: the one writer of the `sessions` bucket, fenced on the coordination lease.

Layer: application
Context: coordination
Owns: SessionCheckpoints.checkpoint, the `sessions` bucket's one writer (M7 `Harness.checkpoint`, moved ahead in S4:
    RunTask's turn loop; workflow and ids injected); session_action, the pure session rotation/hibernation rule (M7 `domain/model.py`,
    ADDED in S8 batch B8 as the DESIGN-s8 §31 cross-slice correction, verbatim: A/evidence/rebuild/s8/batch-b8-move/transcribe.py)
Does not own: the checkpoint's content (the caller's state)
Entry points: SessionCheckpoints, session_action
Contracts: INV-SESSION-001
"""

from __future__ import annotations

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import SYSTEM_IDS
from codex_harness.kernel.policy import POLICY


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


def session_action(used: int, capacity: int, idle_seconds: float, busy: bool) -> str:
    require(capacity > 0 and used >= 0 and idle_seconds >= 0, "Invalid session telemetry")
    if used / capacity >= POLICY.context_checkpoint_fraction:
        return "checkpoint_when_safe" if busy else "rotate"
    if idle_seconds >= POLICY.idle_seconds and not busy:
        return "hibernate"
    return "continue"

"""The trusted continuation binding of an assignment, read against the lane store (RunTask's `continuations` port).

Layer: application
Context: coordination
Owns: ContinuationBindings
Does not own: bucket continuation_bindings (LaneEvidence.bind writes it; read only here)
Entry points: ContinuationBindings.binding
Contracts: INV-CONTINUATION-001

Moved from M7 adapters/executor.py:543-560 `Executor._continuation` (SOURCE e38aa722); the body is M7's with
`self.service.store` -> `self.store` (R-g16).
"""

from __future__ import annotations

from codex_harness.coordination.domain.continuation import validate_binding
from codex_harness.kernel.errors import require


class ContinuationBindings:
    def __init__(self, store):
        self.store = store

    def binding(self, details) -> dict | None:
        """The trusted continuation binding of this assignment, or None for the legacy path.

        It is accepted only when the assignment's operation names it AND the identical document is
        the lane store's own `continuation_bindings` row for that operation, so neither a plan nor a
        model answer nor a forged message can select a workspace or a session."""
        attached = details.get("continuation") if isinstance(details, dict) else None
        if attached is None:
            return None
        binding = validate_binding(attached)
        operation = details.get("operation") if isinstance(details.get("operation"), dict) else {}
        require(operation.get("id") == binding["operation_id"], "Continuation binding names another operation")
        with self.store.transaction() as tx:
            stored = tx.get("continuation_bindings", binding["operation_id"])
        require(stored == binding, "Continuation binding is not the lane's own record")
        return binding

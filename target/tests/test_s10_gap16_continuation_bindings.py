"""S10 GAP #16: `ContinuationBindings.binding`, RunTask's `continuations` port (M7 `Executor._continuation`; INV-CONTINUATION-001).

RunTask is built as `tests/test_s4_run_task.py` builds it (the host App Server is a fixture and the Claude runtime raises when constructed, so
no provider is reachable). An attached binding that is the lane store's own record passes `_continuation` and the run reaches the next unwired
boundary (correction feedback); a forged binding refuses with M7's message before any provider call.
"""

from __future__ import annotations

import pytest
from test_s4_run_task import PLAN, build, inspected, submit

from codex_harness.coordination.application.continuation.bindings import ContinuationBindings

OPERATION = "operation-1"
BINDING = {"schema": "urn:zeus:continuation-binding:1", "operation_id": OPERATION, "policy_sha256": "a" * 64, "intent_id": "b" * 64,
           "family": "family-1", "route": None, "session": None, "workspace": None, "predecessor": None}


def run(tmp_path, details, stored):
    run_task, workflow, store, _, calls = build(tmp_path, evidence_gate=inspected([]))
    run_task.continuations = ContinuationBindings(store)
    if stored is not None:
        with store.transaction() as tx:
            tx.put("continuation_bindings", stored["operation_id"], dict(stored))
    submit(workflow, "implement", {"plan": dict(PLAN), **details}, "lead:improvement", "worker:implementation")
    out = run_task.execute_one("worker:implementation")
    return out, calls


def test_an_attached_binding_that_is_the_lane_record_passes_to_the_next_boundary(tmp_path):
    out, calls = run(tmp_path, {"operation": {"id": OPERATION}, "continuation": dict(BINDING)}, BINDING)
    error = out.get("error") or ""
    assert calls == [] and "Correction feedback is not wired" in error
    assert "Continuation lanes are not wired" not in error and "Continuation binding" not in error


@pytest.mark.parametrize("details, stored, wording", [
    ({"operation": {"id": "operation-2"}, "continuation": dict(BINDING)}, BINDING, "Continuation binding names another operation"),
    ({"operation": {"id": OPERATION}, "continuation": dict(BINDING)}, None, "Continuation binding is not the lane's own record"),
    ({"operation": {"id": OPERATION}, "continuation": dict(BINDING)}, {**BINDING, "family": "family-2"},
     "Continuation binding is not the lane's own record"),
])
def test_a_forged_binding_refuses_before_any_provider(tmp_path, details, stored, wording):
    out, calls = run(tmp_path, details, stored)
    assert calls == [] and out["status"] in {"retry", "failed"} and wording in (out.get("error") or "")

"""S4 ReviewDecisions boundaries that the `review.decisions` / `effects.decision_unit` goldens do not reach.

- The moved INV-RESEARCH-004 guard `require_dispatch` refuses every proposal or research-origin dispatch. That is
  M7's dormant rollout: the research_lead/proposal accept paths refuse and never write.
- The S8-owned review phases refuse when unwired. `audit_review` refuses with M7's own wording when no audit
  executor is present. `threshold_review` refuses explicitly: the declared unwired default, which S8 wires, and
  never a silent pass.
- Only a claimed decision reaches the reviewer. The fixture invoker records that it ran outside any transaction
  (§2.9 rule 4, discriminator (d); the golden trace pins the same).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.research.domain.research import require_dispatch, research_origin
from codex_harness.review.application.decisions import ReviewDecisions


@pytest.mark.parametrize("details", [
    {"proposal": {}},
    {"x": {"source_url": "https://example.invalid"}},
    {"x": [{"y": {"audit_id": "a"}}]},
    {"research_provenance": 1},
])
def test_require_dispatch_refuses_research_and_proposals(details):
    with pytest.raises(ContractError, match="Research adoption deferred"):
        require_dispatch(details)


def test_require_dispatch_admits_plain_details():
    assert require_dispatch({"plan": {"objective": "x"}}) is None
    assert research_origin({"a": [{"b": 1}]}) is False


class Recorder:
    """Records what the failure path writes, so the refusal's disposition is visible."""

    def __init__(self):
        self.failed = []

    def fail(self, tx, lease, error):
        self.failed.append((lease["id"], type(error).__name__, str(error)))
        return {"id": lease["id"], "status": "retry"}


def decisions(**overrides):
    failures = Recorder()
    observer = SimpleNamespace(pending_terminations=lambda task_id, strict=False: [],
                               termination_id=lambda lease: "t")

    class Tx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    store = SimpleNamespace(transaction=lambda: Tx())
    base = dict(ownership=None, failures=failures, outbox=None, events=None, releases=None, hooks=None,
                observer=observer, invoker=SimpleNamespace(invoke=lambda *a, **k: pytest.fail("invoked")),
                git=SimpleNamespace(repository="/nonexistent"), release_policy=None, ticket_binding=None,
                TicketSuperseded=type("TicketSuperseded", (Exception,), {}), require_dispatch=require_dispatch,
                ReconciliationRequired=type("ReconciliationRequired", (Exception,), {}),
                PostExecutionRecordFailure=type("PostExecutionRecordFailure", (Exception,), {}))
    base.update(overrides)
    return ReviewDecisions(store, None, **base), failures


@pytest.mark.parametrize("phase, wording", [
    ("audit_review", "Audit executor unavailable"),
    ("threshold_review", "Threshold review is not wired"),
])
def test_unwired_s8_phases_refuse_and_fail_the_attempt_without_invoking(phase, wording):
    use_case, failures = decisions()
    out = use_case.decide("lead:improvement", {"id": "d1", "phase": phase, "input": {}, "message": {}})
    assert out == {"id": "d1", "status": "retry"}
    assert failures.failed == [("d1", "ContractError", wording)]


def test_the_reviewer_runs_outside_any_transaction():
    depth = {"open": 0, "seen": None}

    class Tx:
        def __enter__(self):
            depth["open"] += 1
            return self

        def __exit__(self, *exc):
            depth["open"] -= 1
            return False

    def invoke(*args, **kwargs):
        depth["seen"] = depth["open"]
        return {"accepted": False, "blocked": True, "execution_ref": "r", "reason": "x"}

    ownership = SimpleNamespace(owned=lambda tx, lease: {"id": "d1", "status": "running"},
                                validate=lambda tx, row: None, record=lambda tx, row: None,
                                notice=lambda *a, **k: None, heartbeat=lambda lease: None)
    use_case, _ = decisions(ownership=ownership, invoker=SimpleNamespace(invoke=invoke),
                            observer=SimpleNamespace(close_unconfirmed=lambda *a: None))
    use_case.store = SimpleNamespace(transaction=lambda: Tx())
    out = use_case.decide("lead:improvement", {"id": "d1", "phase": "diagnose", "input": {}, "message": {}})
    assert depth["seen"] == 0 and out["status"] == "blocked"

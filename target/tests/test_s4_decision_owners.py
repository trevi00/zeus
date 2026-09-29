"""S4 coordination owner operations for the review commit unit (REBUILD-DESIGN-v2 §2.7/§2.9; DESIGN-review-decisions).

Outbox.append and EventJournal.append write exactly the bodies that M7 wrote inline. DecisionOwnership and
DecisionFailures delegate to the moved coordination code without changing its arguments. None of them opens a
transaction: each joins the caller's `tx` (§2.9 rule 2). The end-to-end equality of the decision unit is the
`review.decisions` / `effects.decision_unit` comparison, once ReviewDecisions lands.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from codex_harness.coordination.application import decisions as decisions_module
from codex_harness.coordination.application.decisions import DecisionFailures, DecisionOwnership
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore


class RecordingTx:
    """A transaction stand-in that records writes and refuses to be used as a store (no nested units)."""

    def __init__(self, rows=None):
        self.rows, self.puts = dict(rows or {}), []

    def get(self, bucket, key):
        return self.rows.get((bucket, key))

    def put(self, bucket, key, body):
        self.puts.append((bucket, key, body))
        self.rows[(bucket, key)] = body

    def transaction(self):  # pragma: no cover - reaching this is the failure
        raise AssertionError("an owner operation opened a transaction inside the unit")


class FixedClock:
    def now(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


class CountingIds:
    def __init__(self):
        self.n = 0

    def uuid4(self):
        self.n += 1
        return f"00000000-0000-4000-8000-{self.n:012d}"


def test_outbox_append_is_the_m7_inline_body():
    tx, message = RecordingTx(), {"message_id": "m-1", "type": "review.result"}
    assert Outbox().append(tx, message) is None
    # M7 adapters/executor.py:1959 and application/service.py:87 write exactly this body.
    assert tx.puts == [("outbox", "m-1", {"message": message, "sent": False})]


def test_event_journal_append_is_unconditional_like_m7():
    tx = RecordingTx({("events", "e-1"): {"old": True}})
    EventJournal().append(tx, "e-1", {"type": "hook.required", "hook_id": "h", "at": "t"})
    assert tx.puts == [("events", "e-1", {"type": "hook.required", "hook_id": "h", "at": "t"})]


def test_decision_ownership_delegates_in_the_callers_transaction(monkeypatch):
    calls = []
    workflow = SimpleNamespace(_owned=lambda tx, lease: calls.append(("owned", tx, lease)) or {"id": "d1"},
                               heartbeat=lambda lease: calls.append(("heartbeat", lease)))
    recovery = SimpleNamespace(validate_decision=lambda tx, row: calls.append(("validate", tx, row)))
    org = object()
    notices = []
    monkeypatch.setattr(decisions_module.execution_notices, "record",
                        lambda tx, o, row, bucket, code, at, ref=None: notices.append((tx, o, row, bucket, code, at, ref)))
    owner = DecisionOwnership(workflow, recovery, org)
    tx, lease = RecordingTx(), {"id": "d1", "_bucket": "decisions_pending"}
    assert owner.owned(tx, lease) == {"id": "d1"}
    owner.validate(tx, {"id": "d1"})
    owner.record(tx, {"id": "d1", "status": "succeeded"})
    owner.notice(tx, {"id": "d1"}, "decision_blocked", "2026-01-01T00:00:00+00:00")
    owner.notice(tx, {"id": "d1"}, "reconciliation_required", "2026-01-01T00:00:00+00:00", "ev-1")
    owner.heartbeat(lease)
    assert calls == [("owned", tx, lease), ("validate", tx, {"id": "d1"}), ("heartbeat", lease)]
    assert tx.puts == [("decisions_pending", "d1", {"id": "d1", "status": "succeeded"})]
    assert notices == [(tx, org, {"id": "d1"}, "decisions_pending", "decision_blocked",
                        "2026-01-01T00:00:00+00:00", None),
                       (tx, org, {"id": "d1"}, "decisions_pending", "reconciliation_required",
                        "2026-01-01T00:00:00+00:00", "ev-1")]


def test_next_message_is_the_moved_workflow_next_with_injected_clock_and_ids():
    parent = {"correlation_id": "c", "message_id": "p", "where": {"revision": "r"}, "how": {"k": 1}}
    owner = DecisionOwnership(None, None, None, clock=FixedClock(), ids=CountingIds())
    got = owner.next_message(parent, "lead:a", "worker:implementation", "implement", {"plan": {}})
    expected = Workflow._next(parent, "lead:a", "worker:implementation", "implement", {"plan": {}},
                              clock=FixedClock(), ids=CountingIds())
    assert got == expected and got["where"] == parent["where"] and got["how"] == parent["how"]


def test_decision_failures_pass_the_unit_transaction_and_injected_clocks(monkeypatch):
    seen = []
    workflow = SimpleNamespace(
        fail_execution=lambda lease, error, *, transaction: seen.append(("fail", lease, error, transaction)) or {},
        contain_time=lambda lease, error: seen.append(("contain", lease, error)))
    monkeypatch.setattr(decisions_module.execution_rejections, "reconcile",
                        lambda store, lease, error, rejection, *, clock, monotonic:
                        seen.append(("reconcile", store, lease, error, rejection, clock, monotonic)))
    clock, mono, store, tx = FixedClock(), (lambda: 1.0), object(), RecordingTx()
    failures = DecisionFailures(workflow, store, clock=clock, monotonic=mono)
    error = RuntimeError("x")
    failures.fail(tx, {"id": "d"}, error)
    failures.contain_time({"id": "d"}, error)
    failures.reconcile({"id": "d"}, error, None)
    assert seen == [("fail", {"id": "d"}, error, tx), ("contain", {"id": "d"}, error),
                    ("reconcile", store, {"id": "d"}, error, None, clock, mono)]
    assert tx.puts == []


@pytest.mark.parametrize("module", ["outbox", "events", "decisions"])
def test_owner_modules_never_open_a_transaction(module):
    import importlib
    import inspect
    source = inspect.getsource(importlib.import_module(f"codex_harness.coordination.application.{module}"))
    assert ".transaction(" not in source


def test_submit_refuses_when_parking_is_unwired():
    message = envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": {"objective": "x"}}, "c")
    store = MemoryStore()
    wf = Workflow(store, packaged_organization(), ticket_binding=lambda tx, details: None,
                  TicketSuperseded=Exception, adoption=lambda tx, details: None)
    with pytest.raises(ContractError, match="not wired"):
        wf.submit(message)
    with store.transaction() as tx:
        assert tx.records() == []


# ---- RunTask facades (DESIGN-run-task D8) -------------------------------------------------------------------

def test_task_ownership_delegates_to_the_moved_workflow_unchanged():
    from codex_harness.coordination.application.task_ownership import TaskOwnership
    calls = []
    workflow = SimpleNamespace(
        _owned=lambda tx, lease: calls.append(("owned", tx, lease)) or {"id": "t"},
        heartbeat=lambda lease, seconds: calls.append(("heartbeat", lease, seconds)) or {"lease_until": "x"},
        remaining_seconds=lambda lease, maximum: calls.append(("remaining", maximum)) or 5.0,
        claim=lambda agent, owner, **o: calls.append(("claim", agent, owner, o)) or {"id": "t"},
        complete=lambda task, result, commands, accept=None: calls.append(("complete", commands, accept)) or {},
        fail_execution=lambda task, error, *, transaction=None: calls.append(("fail", transaction)) or {},
        contain_time=lambda task, error: calls.append(("contain",)),
        snapshot=lambda: "snap")
    own, tx = TaskOwnership(workflow), RecordingTx()
    assert own.owned(tx, {"id": "t"}) == {"id": "t"}
    assert own.heartbeat({"id": "t"}) == {"lease_until": "x"}
    assert own.remaining_seconds({"id": "t"}, 600) == 5.0
    own.claim("lead:improvement", "o1", expected={"id": "t"})
    own.complete({"id": "t"}, {}, [], accept="a")
    own.fail_execution({"id": "t"}, RuntimeError("x"), transaction=tx)
    own.contain_time({"id": "t"}, RuntimeError("x"))
    assert own.snapshot() == "snap"
    assert [c[0] for c in calls] == ["owned", "heartbeat", "remaining", "claim", "complete", "fail", "contain"]
    assert calls[1][2] > 0 and calls[3][3] == {"expected": {"id": "t"}} and calls[5][1] is tx


def test_invocation_breaker_delegates_to_the_moved_breaker_and_functions():
    from codex_harness.coordination.application.breaker import breaker_key, result_of, result_of_exception
    from codex_harness.coordination.application.invocation_admission import InvocationBreaker
    seen = []
    breaker = SimpleNamespace(admit=lambda key, lease, now: seen.append(("admit", key, now)) or {"k": key},
                              report=lambda token, result, now: seen.append(("report", result, now)) or {"a": 1})
    admission = InvocationBreaker(breaker)
    assert admission.admit("breaker:codex:x", {"id": "t"}) == {"k": "breaker:codex:x"}
    assert admission.report({"k": 1}, "success") == {"a": 1}
    assert admission.key("codex", "improvement") == breaker_key("codex", "improvement")
    assert admission.verdict({"answer": {"x": 1}}) == result_of({"answer": {"x": 1}}) == "success"
    error = ContractErrorLike("Codex turn execution budget exceeded")
    assert admission.verdict_of_exception(error) == result_of_exception(error)
    assert seen == [("admit", "breaker:codex:x", None), ("report", "success", None)]


class ContractErrorLike(Exception):
    pass

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

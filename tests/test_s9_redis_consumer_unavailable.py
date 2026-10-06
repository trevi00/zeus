"""REDIS-STREAMS-RELIABILITY-20261003 matrix row 3 "Redis unavailable", consumer side (map G5).

These tests CHARACTERIZE current behaviour of the three `RedisBus.receive` consumers when the server cannot be
reached; they do not prescribe a retry, backoff or catch policy (the process loop and its backoff are S10 entry
wiring). They run in plain pytest with NO Redis server: the unreachable bus is a REAL `RedisBus` pointed at
127.0.0.1:1 (connection refused), whose first command inside `receive` (`ensure_group`'s `XGROUP CREATE`,
redis_bus.py `receive`) raises `redis.exceptions.ConnectionError`; `ensure_group` only swallows `ResponseError`.

Each consumer is built on a MemoryStore as its ported suite builds it (`test_local_cycle.py` /
`test_foreign_notices.py` for the local cycle, `test_autonomous.py` / `test_operation.py` for autonomous delivery, `test_frontdesk.py`
for the desk runner). Each test checks, per consumer: what the caller sees, that nothing was handled, acked or
dead-lettered and no business record was written, that no success / idle / settled outcome was reported, and that
a working bus carrying one valid message is then handled exactly once.

Already covered elsewhere (not repeated): the relay side (`test_bus.py`, the outbox retry path) and the real
PG+Redis kill matrix (`test_execution_notices.py::test_real_process_kill_matrix_...`).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

sys.path.insert(0, str(Path(__file__).parent / "ported"))
from m7_coordination import Harness, LocalCycle, Workflow, flush_outbox, organization  # noqa: E402

from codex_harness.coordination.application.autonomous import AutonomousRun  # noqa: E402
from codex_harness.coordination.application.desk_runner import DeskRunner  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.application.frontdesk import (  # noqa: E402
    BUCKET_EVENTS,
    BUCKET_REQUESTS,
    BUCKET_SESSIONS,
    FrontDesk,
    message_id_of,
)
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402
from codex_harness.storage.adapters.redis_bus import RedisBus  # noqa: E402

CORR = "improvement:cycle-test"
CURRENT = "autonomous:current-run"
CONDUCTOR = "conductor"
WORKER = "worker:implementation"
REVISION = "0" * 39 + "a"
UNREACHABLE = "redis://" + "127.0.0.1:1/0"  # nothing listens on port 1: a refused connection, no server needed


def unreachable_bus():
    return RedisBus(UNREACHABLE, "zeus-s9-g5-" + uuid4().hex)


def records(store):
    with store.transaction() as tx:
        return tx.records()


def changed(before, after):
    """The (bucket, id) keys whose record was added, removed or differs between two snapshots."""
    old = {(r["bucket"], r["id"]): r["body"] for r in before}
    new = {(r["bucket"], r["id"]): r["body"] for r in after}
    return {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}


# ----- the local cycle ----------------------------------------------------------------------
class CycleBus:
    """The in-memory stand-in of test_local_cycle (receive, decode, ack, dead_letter, publish)."""

    def __init__(self, queued):
        self.queued, self.acked, self.dead, self.published = list(queued), [], [], []

    def receive(self, agent, consumer):
        for entry in self.queued:
            if entry[1]["who"]["recipient"] == agent and entry[0] not in self.acked:
                return entry[0], {"body": entry[1]}
        return None

    @staticmethod
    def decode(fields):
        return fields["body"]

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append(entry_id)
        self.acked.append(entry_id)

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        self.published.append(message)
        return "1-0"


class CycleExecutor:
    """A fixture executor that records calls; the Redis-unavailable step must never reach it."""

    def __init__(self):
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append(("task", agent))
        return None

    def decide_one(self, agent, expected=None):
        self.calls.append(("decision", agent))
        return None


def test_local_cycle_step_propagates_connection_error_with_no_ack_no_effect_and_recovers_once():
    """Consumer 1, `LocalCycle._deliver` (local_cycle.py `row = self.bus.receive(agent, consumer)`, called from
    `step`). The receive for the first role (`worker:implementation`) raises redis `ConnectionError`; `_deliver`
    has no handler around it and `step` has none around `_deliver`, so the caller sees `ConnectionError` itself.
    PROVES: the store records equal the pre-step snapshot: the cycle row is still `active`, `in_flight` is None,
    `executions` is 0 and no `tasks`, `workflow_inbox`, `outbox` or disposition row exists; the executor was
    never called; and no step result exists at all, so no success, no idle ("no messages") outcome and no
    settled or stopped cycle was reported. The message was never received, so nothing was acked or dead-lettered.
    RECOVERY: the same cycle with a working bus carrying one own `task.assign` handles it once (one `tasks`
    row, one ACK, one handled receipt); the failed attempt left no marker, row or pending state in the way."""
    svc = Harness(MemoryStore(), organization())
    executor = CycleExecutor()
    cycle = LocalCycle(svc, executor, unreachable_bus(), Workflow(svc.store, svc.org))
    cycle.start("c1", CORR, 2)
    before = records(svc.store)

    with pytest.raises(RedisConnectionError):
        cycle.step("c1")

    assert records(svc.store) == before, "no record of any kind was written by the failed attempt"
    status = cycle.status("c1")
    assert status["status"] == "active" and status["in_flight"] is None and status["executions"] == 0
    assert status["stopped_reason"] is None
    assert executor.calls == []

    parent = organization().actor(WORKER).parent
    own = envelope("task.assign", parent, WORKER, "implement", {"objective": "after outage"}, CORR)
    bus = CycleBus([("1-0", own)])
    cycle.bus = bus
    result = cycle.step("c1")

    assert bus.acked == ["1-0"] and bus.dead == []
    assert [(m["entry_id"], m["message_id"], m["type"], m["handled"]) for m in result["messages"]] == [
        ("1-0", own["message_id"], "task.assign", True)]
    with svc.store.transaction() as tx:
        assert [t["id"] for t in tx.scan("tasks")] == [own["message_id"]], "one business effect"
        assert tx.get("tasks", own["message_id"])["message"]["correlation_id"] == CORR
    assert cycle.bus.receive(WORKER, "again") is None, "the message is acked: a further drain finds nothing"


# ----- autonomous delivery -------------------------------------------------------------------
class AutonomousBus:
    """The in-memory stream stand-in of test_operation (`Bus`): publish queues, receive skips acked entries."""

    def __init__(self):
        self.queued, self.acked, self.published = [], [], []

    def receive(self, agent, consumer):
        for entry in self.queued:
            if entry[1]["who"]["recipient"] == agent and entry[0] not in self.acked:
                return entry[0], {"body": entry[1]}
        return None

    @staticmethod
    def decode(fields):
        return fields["body"]

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.acked.append(entry_id)

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        entry = str(len(self.published) + 1) + "-0"
        self.published.append(message)
        self.queued.append((entry, message))
        return entry


def current_report(svc, task_id="t-current-dba"):
    """A real succeeded lead task row of the current run and the task.result it files to the conductor."""
    assignment = envelope("task.assign", CONDUCTOR, "lead:dba", "dge_role", {"role": "dba"}, CURRENT)
    result = {"summary": "current report", "execution_ref": "sha256:" + "1" * 64}
    with svc.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": "lead:dba", "status": "succeeded", "attempt": 1,
                                  "generation": 1, "message": assignment, "result": result})
    return envelope("task.result", "lead:dba", CONDUCTOR, "dge_role", {"task_id": task_id, "result": result},
                    CURRENT, task_id)


def test_autonomous_delivery_propagates_connection_error_with_no_ack_no_effect_and_recovers_once():
    """Consumer 2, `AutonomousRun._deliver` (autonomous.py `row = self.bus.receive(agent, consumer)`), driven as
    `test_foreign_notices.py` drives it: `run._deliver(CONDUCTOR, CURRENT)`. The receive raises redis
    `ConnectionError`; `_deliver` has no handler around the receive, so the caller sees `ConnectionError`
    itself (not `AutonomousRefused`, which the run reports as a named refusal).
    PROVES: the store records equal the snapshot (no `workflow_inbox`, task, outbox or run row written), the
    executor made no call and the budget reserved nothing; `_deliver` returned no handled list at all, so it
    did not report an empty drain (`[]`, the idle outcome) or any handled message. Nothing was received, so
    nothing was acked or dead-lettered.
    RECOVERY: with a working bus carrying one current-correlation `task.result`, the same call handles it
    once (the returned list has that message once, one `workflow_inbox` row, one ACK)."""
    svc = Harness(MemoryStore(), organization())
    executor, budget = SimpleNamespace(calls=[]), SimpleNamespace(reserved=[])  # fixtures: never reached by _deliver
    run = AutonomousRun(svc, executor, unreachable_bus(), Workflow(svc.store, svc.org), budget)
    report = current_report(svc)
    before = records(svc.store)

    with pytest.raises(RedisConnectionError):
        run._deliver(CONDUCTOR, CURRENT)

    assert records(svc.store) == before, "no record of any kind was written by the failed attempt"
    assert executor.calls == [] and budget.reserved == []

    bus = run.bus = AutonomousBus()
    bus.publish(report)
    handled = run._deliver(CONDUCTOR, CURRENT)

    assert [m["message_id"] for m in handled] == [report["message_id"]]
    assert bus.acked == ["1-0"]
    with svc.store.transaction() as tx:
        assert len(tx.scan("workflow_inbox")) == 1, "one business effect"
        assert tx.get("workflow_inbox", report["message_id"])["result"]["handled"] is True
    assert executor.calls == [] and budget.reserved == []
    assert run._deliver(CONDUCTOR, CURRENT) == [] and bus.acked == ["1-0"], "acked once; nothing is re-handled"


# ----- the desk runner -----------------------------------------------------------------------
class DeskBus:
    """A stand-in transport with the RedisBus surface the outbox and the desk runner use (test_frontdesk)."""

    def __init__(self):
        self.streams, self.published, self.acked = {}, [], []

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
        self.validate(message)
        entry_id = str(len(self.published) + 1)
        self.published.append(message)
        self.streams.setdefault(message["who"]["recipient"], []).append((entry_id, {"body": canonical(message)}))
        return entry_id

    def receive(self, agent, consumer, idle_ms=60000):
        rows = self.streams.get(agent) or []
        return rows[0] if rows else None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)
        self.streams[agent] = [row for row in self.streams.get(agent, []) if row[0] != entry_id]

    @staticmethod
    def decode(fields):
        return validate_message(json.loads(fields["body"]))


class DeskExecutor:
    """Drives the REAL claim/complete path but never enters a provider (test_frontdesk's FakeExecutor)."""

    ANSWER = {"answer": "구독 사용량은 기록되고 호출 수 상한은 적용되지 않습니다.", "objective": None,
              "acceptance_criteria": [], "questions": [], "execution_ref": "sha256:" + "b" * 64}

    def __init__(self, svc):
        self.svc, self.calls, self.slots = svc, [], []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        self.slots.append({"id": "slot-%d" % len(self.calls), "kind": "task", "settled": True})
        workflow = Workflow(self.svc.store, self.svc.org)
        task = workflow.claim(agent, "desk-owner-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        return workflow.complete(task, dict(self.ANSWER), [])


def test_desk_runner_turns_a_connection_error_into_needs_reconciliation_with_no_ack_no_effect_and_recovers_once():
    """Consumer 3, `DeskRunner._deliver` (desk_runner.py `entry = self.bus.receive(LEAD, "desk:" + row["id"])`).
    UNLIKE the other two, this consumer CATCHES the failure: `step` calls `_turn`, and its
    `except Exception as exc:` around `self._turn(row)` (desk_runner.py `step`, "Wiring, transport or accounting
    failed outside a recorded execution") turns it into `{"status": "needs_reconciliation", "reason_code":
    "dispatch_exception:ConnectionError"}` and `desk.finalize` records that terminal row. So the exact durable
    state is: the request row goes `queued -> dispatching` (claim) `-> needs_reconciliation` with
    `reason_code == "dispatch_exception:ConnectionError"`, `answer` None and no `task_id`; only the exception
    TYPE is stored. That explicit uncertainty is the by-design failure row: the step reports status
    `needs_reconciliation` (not answered, not an idle step, `action` is `turn` with a failed outcome).
    PROVES: the ONLY records that differ from the snapshot are the desk's own lifecycle rows (the request row, its
    session's counters, and the `:dispatch` and `:terminal` desk events: the claim and the terminal record the
    turn writes by design); no `tasks`, `workflow_inbox`, outbox or reservation row changed; the executor was never
    called, no `tasks` row exists (the message was never handled), nothing was acked, no other record was written.
    The turn is terminal: it is never retried by this runner (a later `claim_next` finds nothing).
    RECOVERY: a NEW request in the same session, with a working bus carrying only its message, is handled once
    (one executor call, one ACK, answered); the failed turn does not block or duplicate it.
    The assignment of the failed turn was already published (the outbox relay precedes `_deliver`; an unpublished
    one ends the turn earlier as `publication_incomplete`, never reaching receive), so it is pre-published here
    on a working stand-in stream, as the relay would have done before the outage."""
    svc = Harness(MemoryStore(), organization())
    desk = FrontDesk(svc, REVISION, outbox=Outbox())
    session_id = str(uuid4())
    desk.create_session({"session_id": session_id, "title": "Redis outage desk"})
    request_id = desk.submit({"session_id": session_id, "request_id": str(uuid4()), "intent": "consult",
                              "text": "status?"})["request"]["id"]
    assert flush_outbox(svc, DeskBus())["published"] == 1
    executor = DeskExecutor(svc)
    runner = DeskRunner(svc, desk, executor, unreachable_bus(), Workflow(svc.store, svc.org))
    before = records(svc.store)

    step = runner.step()

    assert step["action"] == "turn" and step["request_id"] == request_id
    assert step["status"] == "needs_reconciliation" and step["reason_code"] == "dispatch_exception:ConnectionError"
    assert step["status"] not in {"answered", "needs_spec"} and step["task_id"] is None
    after = records(svc.store)
    assert changed(before, after) == {
        (BUCKET_REQUESTS, request_id), (BUCKET_SESSIONS, session_id),
        (BUCKET_EVENTS, request_id + ":dispatch"), (BUCKET_EVENTS, request_id + ":terminal")}, \
        "only the desk's own request, session and its two lifecycle events record the turn"
    row = desk.request(request_id)
    assert row["status"] == "needs_reconciliation" and row["reason_code"] == "dispatch_exception:ConnectionError"
    assert row["answer"] is None and row.get("task_id") is None
    assert executor.calls == [] and desk.claim_next() is None, "no execution, and the terminal turn is not re-claimed"
    with svc.store.transaction() as tx:
        assert tx.scan("tasks") == [], "`workflow.handle` never ran: the assignment created no task row"

    second = desk.submit({"session_id": session_id, "request_id": str(uuid4()), "intent": "consult",
                          "text": "status again?"})["request"]["id"]
    working = DeskBus()
    assert flush_outbox(svc, working)["published"] == 1  # only the new request's message is on this stream
    assert len(working.published) == 1 and working.published[0]["message_id"] == message_id_of(second)
    runner.bus = working
    step = runner.step()

    assert step["status"] == "answered" and step["request_id"] == second
    assert len(executor.calls) == 1 and executor.calls[0]["expected"]["id"] == message_id_of(second)
    assert working.acked == ["1"] and desk.request(second)["answer"]["answer"] == DeskExecutor.ANSWER["answer"]
    assert desk.request(request_id)["status"] == "needs_reconciliation", "the failed turn stays as recorded"

"""Correlation-scoped outbox publication (INV-MESSAGE-001, Implementation015).

Every executor, budget, bus and collector here is a labelled fixture (fault injection), never
Claude, Codex, a real transport or a real ledger. The matrix below covers: a current run's own
assignment and result published past a large unrelated history, foreign rows and the global cursor
left untouched, the default global batch unchanged, a failed or unfinished scoped delivery refusing
before any reservation, and a scope change between selection, preparation and publication.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from test_autonomous import build as build_autonomous
from test_autonomous import valid as autonomous_valid
from test_local_cycle import Bus as CycleBus
from test_local_cycle import FakeExecutor as CycleExecutor
from test_local_cycle import task as cycle_task
from test_operation import BOUND_GOAL, IDENTITY, Bus
from test_operation import build as build_operation
from test_operation import valid as operation_valid

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.autonomous import AutonomousRefused
from codex_harness.application.execution_notices import record
from codex_harness.application.local_cycle import LocalCycle
from codex_harness.application.outbox import _prepare, _publish, relay
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope
from codex_harness.ports import MessageDeliveryError

CORR = "improvement:scoped-current"
FOREIGN = "improvement:unrelated-history"
EARLY, LATE = "00000000-0000-4000-8000-000000000000", "ffffffff-0000-4000-8000-000000000000"


class RecordingBus:
    """Validates and records; the entry id is the transport receipt (fixture)."""

    def __init__(self):
        self.published = []

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        self.published.append(message)
        return str(len(self.published)) + "-0"


class UnavailableBus(RecordingBus):
    def publish(self, message):
        raise MessageDeliveryError("transport unavailable (fixture)")


class AcceptedButNotAdmitted(Bus):
    """The transport accepts the assignment, the consumer database never admits it (fixture)."""

    def publish(self, message):
        entry = str(len(self.published) + 1) + "-0"
        self.published.append(message)
        return entry


class RefusingBus(Bus):
    def publish(self, message):
        raise MessageDeliveryError("transport unavailable (fixture)")


class RefusingCycleBus(CycleBus):
    """The report arrives; the command the workflow derives from it never reaches the transport."""

    def publish(self, message):
        raise MessageDeliveryError("transport unavailable (fixture)")


def incident(occurrence):
    return envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                    {"occurrence_id": occurrence, "root_cause": "scoped-publication", "scope": "fixture",
                     "evidence_refs": ["fixture:error"]}, CORR)


def service():
    return Harness(MemoryStore(), organization())


def queue(svc, identity, correlation, *, sent=False, kind="task.assign",
          sender="lead:improvement", recipient="worker:implementation", action="implement"):
    message = envelope(kind, sender, recipient, action, {"plan": {}} if kind == "task.assign" else {},
                       correlation)
    message["message_id"] = identity
    with svc.store.transaction() as tx:
        tx.put("outbox", identity, {"message": message, "sent": sent})
    return identity


def history(svc, count, *, full=False):
    """`count` unrelated records: every second one is a historical sent row, the rest foreign unsent.

    A large history uses a compact foreign record instead of a full six-W envelope, which keeps the
    fixture store cheap and makes the claims below harder, not weaker: the scoped batch must leave
    even a record the default global relay would quarantine exactly as it is. The default-batch test
    uses `full=True` envelopes, so the unchanged global behaviour is proven on real messages.
    """
    foreign, sent = [], []
    with svc.store.transaction() as tx:
        for n in range(1, count + 1):
            identity = f"00000000-0000-4000-8000-{n:012d}"
            correlation = FOREIGN + ":" + str(n)
            if full:
                message = envelope("task.assign", "lead:improvement", "worker:implementation",
                                   "implement", {"plan": {}}, correlation)
                message["message_id"] = identity
            else:
                message = {"message_id": identity, "type": "task.assign", "correlation_id": correlation}
            tx.put("outbox", identity, {"message": message, "sent": bool(n % 2)})
            (sent if n % 2 else foreign).append(identity)
    return foreign, sent


def cursor(svc, identity):
    with svc.store.transaction() as tx:
        tx.put("outbox_control", "relay", {"cursor": identity, "at": "fixture"})


def read(svc, bucket, identity):
    with svc.store.transaction() as tx:
        return tx.get(bucket, identity)


# ----- selection independent of history and cursor --------------------------------------------
@pytest.mark.parametrize("count", [120, 1100])
def test_current_assignment_and_result_publish_past_a_large_history_whatever_the_cursor(count):
    svc = service()
    foreign, sent = history(svc, count)
    middle = f"00000000-0000-4000-8000-{count // 2:012d}"
    cursor(svc, middle)  # the shared cursor sits in the middle of the unrelated history
    assignment = queue(svc, EARLY, CORR)  # before the cursor
    result = queue(svc, LATE, CORR, kind="task.result", sender="worker:implementation",
                   recipient="lead:improvement")
    bus = RecordingBus()
    batch = relay(svc.store, svc.org, bus, correlation_id=CORR)
    assert [m["message_id"] for m in bus.published] == [assignment, result]
    assert batch["published"] == 2 and batch["examined"] == 2 and batch["out_of_scope"] == 0
    assert batch["remaining"] == 0 and batch["unfinished"] == 0 and batch["complete"] is True
    assert batch["correlation_id"] == CORR and batch["limit"] == 100
    with svc.store.transaction() as tx:
        assert tx.get("outbox", assignment)["sent"] is True and tx.get("outbox", result)["sent"] is True
        assert tx.get("outbox_control", "relay") == {"cursor": middle, "at": "fixture"}, "global cursor untouched"
        assert tx.scan("outbox_quarantine") == []
        assert all(tx.get("outbox", i)["sent"] is False and tx.get("outbox_delivery", i) is None for i in foreign)
        assert all(tx.get("outbox", i)["sent"] is True and tx.get("outbox_delivery", i) is None for i in sent)
        assert tx.get("health", "outbox") is None, "a scoped batch never overwrites the global health row"


def test_scoped_batch_keeps_the_limit_and_reports_its_own_backlog_truthfully():
    svc = service()
    history(svc, 10)
    own = [queue(svc, f"1000000{n}-0000-4000-8000-000000000000", CORR) for n in range(4)]
    bus = RecordingBus()
    first = relay(svc.store, svc.org, bus, limit=2, correlation_id=CORR)
    assert first["published"] == 2 and first["examined"] == 2 and first["limit"] == 2
    assert first["remaining"] == 2 and first["complete"] is False, "an unsent own backlog is not success"
    second = relay(svc.store, svc.org, bus, limit=2, correlation_id=CORR)
    assert second["published"] == 2 and second["remaining"] == 0 and second["complete"] is True
    assert [m["message_id"] for m in bus.published] == own
    third = relay(svc.store, svc.org, bus, limit=2, correlation_id=CORR)
    assert third == {"examined": 0, "limit": 2, "correlation_id": CORR, "published": 0, "quarantined": 0,
                     "quarantined_existing": 0, "retry": 0, "skipped": 0, "legacy_sent": 0, "error": 0,
                     "out_of_scope": 0, "unfinished": 0, "remaining": 0, "complete": True}


def test_scope_must_be_a_non_empty_correlation_and_the_limit_is_unchanged():
    svc = service()
    bus = RecordingBus()
    for bad in ("", "   ", 1, True, {}):
        with pytest.raises(ContractError, match="non-empty correlation"):
            relay(svc.store, svc.org, bus, correlation_id=bad)
    with pytest.raises(ContractError, match="1..1000"):
        relay(svc.store, svc.org, bus, limit=1001, correlation_id=CORR)
    assert bus.published == []


# ----- the default global batch stays exactly as it was ----------------------------------------
def test_default_global_batch_keeps_cursor_health_and_poison_isolation_after_a_scoped_batch():
    svc = service()
    foreign, _ = history(svc, 6, full=True)
    own = queue(svc, EARLY, CORR)
    with svc.store.transaction() as tx:
        tx.put("outbox", "zz-poison", [])
    bus = RecordingBus()
    assert relay(svc.store, svc.org, bus, correlation_id=CORR)["published"] == 1
    with svc.store.transaction() as tx:
        assert tx.get("outbox", "zz-poison") == [], "a scoped batch never quarantines a foreign record"
        assert tx.get("outbox_control", "relay") is None
    global_batch = svc.flush_outbox(bus)
    assert global_batch["published"] == len(foreign) and global_batch["quarantined"] == 1
    assert global_batch["legacy_sent"] == 3 and global_batch["skipped"] == 1 and "out_of_scope" not in global_batch
    assert [m["message_id"] for m in bus.published] == [own] + foreign
    with svc.store.transaction() as tx:
        assert tx.get("outbox_control", "relay")["cursor"] == "zz-poison"
        assert tx.get("health", "outbox")["status"] == "attention" and tx.get("health", "outbox")["scope"] == "last_batch"
        assert tx.scan("outbox_quarantine")[0]["source"] == []


def test_already_delivered_own_record_stays_idempotent_under_concurrent_scoped_and_global_publishers():
    svc = service()
    own = queue(svc, EARLY, CORR)
    bus = RecordingBus()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda scope: relay(svc.store, svc.org, bus, correlation_id=scope), [CORR, None]))
    assert sum(r["published"] for r in results) == 1
    assert [m["message_id"] for m in bus.published] == [own]
    again = relay(svc.store, svc.org, bus, correlation_id=CORR)
    assert again["examined"] == 0 and again["complete"] is True and len(bus.published) == 1


# ----- failed or unfinished delivery -----------------------------------------------------------
def test_unavailable_transport_keeps_the_intent_and_never_reports_a_complete_publication():
    svc = service()
    own = queue(svc, EARLY, CORR)
    batch = relay(svc.store, svc.org, UnavailableBus(), correlation_id=CORR)
    assert batch["retry"] == 1 and batch["published"] == 0
    assert batch["unfinished"] == 1 and batch["remaining"] == 1 and batch["complete"] is False
    with svc.store.transaction() as tx:
        assert tx.get("outbox", own)["sent"] is False
        assert tx.get("outbox_delivery", own)["status"] == "retry" and tx.get("outbox_delivery", own)["attempts"] == 1
        assert [a["status"] for a in tx.scan("outbox_attempts")] == ["retry"], "the original attempt evidence is kept"


def test_own_poison_record_is_quarantined_in_scope_and_keeps_the_batch_incomplete():
    """Quarantine is the existing poison isolation, applied to the caller's OWN record only. The
    record stays unsent, so the scoped backlog keeps reporting it and the caller cannot read the
    batch as a completed publication; the foreign poison record beside it is never touched."""
    svc = service()
    own = queue(svc, EARLY, CORR)
    with svc.store.transaction() as tx:  # the identity no longer matches the stored key (fixture)
        item = tx.get("outbox", own)
        item["message"]["message_id"] = LATE
        tx.put("outbox", own, item)
    queue(svc, str(uuid4()), FOREIGN)
    bus = RecordingBus()
    batch = relay(svc.store, svc.org, bus, correlation_id=CORR)
    assert batch["quarantined"] == 1 and batch["published"] == 0 and bus.published == []
    assert batch["unfinished"] == 1 and batch["remaining"] == 1 and batch["complete"] is False
    again = relay(svc.store, svc.org, bus, correlation_id=CORR)
    assert again["quarantined_existing"] == 1 and again["complete"] is False, "no retry into a loop"
    with svc.store.transaction() as tx:
        assert tx.get("outbox", own)["sent"] is False
        assert [q["source_id"] for q in tx.scan("outbox_quarantine")] == [own]
        assert tx.get("outbox_control", "relay") is None and tx.get("health", "outbox") is None


def test_scope_change_between_selection_and_preparation_never_publishes_or_mutates_the_row():
    svc = service()
    first, second = queue(svc, EARLY, CORR), queue(svc, LATE, CORR)
    original, calls = svc.store.transaction, {"count": 0}

    @contextmanager
    def mutate_after_selection():
        with original() as tx:
            yield tx
        calls["count"] += 1
        if calls["count"] == 1:  # between the scoped selection and the first preparation (fixture)
            with original() as tx:
                item = tx.get("outbox", second)
                item["message"]["correlation_id"] = FOREIGN
                tx.put("outbox", second, item)
    svc.store.transaction = mutate_after_selection
    bus = RecordingBus()
    batch = relay(svc.store, svc.org, bus, correlation_id=CORR)
    svc.store.transaction = original
    assert batch["published"] == 1 and batch["out_of_scope"] == 1 and batch["examined"] == 2
    assert [m["message_id"] for m in bus.published] == [first]
    assert batch["remaining"] == 0 and batch["complete"] is True, "nothing of this correlation is left unsent"
    with svc.store.transaction() as tx:
        assert tx.get("outbox", second)["sent"] is False and tx.get("outbox_delivery", second) is None
        assert tx.scan("outbox_quarantine") == []


def test_scope_change_between_preparation_and_publication_supersedes_the_attempt():
    svc = service()
    own = queue(svc, EARLY, CORR)
    bus = RecordingBus()
    with svc.store.transaction() as tx:
        result, prepared = _prepare(tx, own, svc.org, bus, None, CORR)
    assert result == "prepared"
    with svc.store.transaction() as tx:  # the scope changes after the attempt was bound (fixture)
        item = tx.get("outbox", own)
        item["message"]["correlation_id"] = FOREIGN
        tx.put("outbox", own, item)
    with svc.store.transaction() as tx:
        result, fatal = _publish(tx, prepared, bus, None, CORR)
    assert result == "skipped" and fatal is None and bus.published == []
    with svc.store.transaction() as tx:
        assert tx.get("outbox", own)["sent"] is False
        assert tx.get("outbox_delivery", own)["status"] == "retry"
        assert [a["status"] for a in tx.scan("outbox_attempts")] == ["superseded_before_publish"]


# ----- role seam: delivery is not admission ----------------------------------------------------
def test_role_refuses_before_any_reservation_when_the_expected_task_was_never_admitted():
    svc, run, executor, budget = build_autonomous()
    run.bus = AcceptedButNotAdmitted()
    receipt = run.run(autonomous_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "expected_execution_missing"
    assert executor.calls == [] and budget.reserved == [], "no slot and no provider without an admitted row"
    assert receipt["starts"] == {"reserved": 0, "settled": 0, "slots": []}
    with svc.store.transaction() as tx:
        assert tx.scan("tasks") == [] and len(tx.scan("outbox")) == 1


def test_role_refuses_before_any_reservation_when_its_own_publication_failed():
    svc, run, executor, budget = build_autonomous()
    run.bus = RefusingBus()
    receipt = run.run(autonomous_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "publication_incomplete"
    assert executor.calls == [] and budget.reserved == []
    with svc.store.transaction() as tx:
        [row] = tx.scan("outbox")
        assert row["sent"] is False and tx.scan("tasks") == []
        assert [d["status"] for d in tx.scan("outbox_delivery")] == ["retry"], "the intent is retained, not retried here"


@pytest.mark.parametrize("count", [120, 1100])
def test_autonomous_roles_publish_only_their_own_correlation_over_a_large_foreign_backlog(count):
    svc, run, executor, budget = build_autonomous()
    foreign, sent = history(svc, count)
    cursor(svc, f"00000000-0000-4000-8000-{count // 2:012d}")
    receipt = run.run(autonomous_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted"
    assert len(executor.calls) == 6 and receipt["starts"]["reserved"] == 6
    correlations = {m["correlation_id"] for m in run.bus.published}
    assert correlations == {receipt["correlation_id"], "operation:" + receipt["operation_id"]}
    with svc.store.transaction() as tx:
        assert all(tx.get("outbox", i)["sent"] is False and tx.get("outbox_delivery", i) is None for i in foreign)
        assert all(tx.get("outbox", i)["sent"] is True for i in sent)
        assert tx.get("outbox_control", "relay")["cursor"] == f"00000000-0000-4000-8000-{count // 2:012d}"
        assert tx.get("health", "outbox") is None


# ----- operation seam --------------------------------------------------------------------------
@pytest.mark.parametrize("count", [120, 1100])
def test_operation_worker_and_review_transport_is_scoped_over_a_large_foreign_backlog(count):
    svc, operation, executor, budget, _ = build_operation()
    foreign, _ = history(svc, count)
    cursor(svc, f"00000000-0000-4000-8000-{count:012d}")  # the cursor sits at the end of the history
    receipt = operation.run(operation_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and executor.calls == ["task", "decision"]
    assert len(budget.reserved) == 2 and receipt["lead_accepted"] is True
    assert {m["correlation_id"] for m in operation.bus.published} == {"operation:op-001"}
    with svc.store.transaction() as tx:
        assert all(tx.get("outbox", i)["sent"] is False and tx.get("outbox_delivery", i) is None for i in foreign)
        assert tx.get("outbox_control", "relay")["cursor"] == f"00000000-0000-4000-8000-{count:012d}"
        assert tx.scan("outbox_quarantine") == []


def test_operation_refuses_before_any_reservation_when_the_assignment_cannot_be_published():
    svc, operation, executor, budget, _ = build_operation()
    operation.bus = RefusingBus()
    receipt = operation.run(operation_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "publication_incomplete"
    assert executor.calls == [] and budget.reserved == []
    with svc.store.transaction() as tx:
        assert tx.get("outbox", receipt["assignment_message_id"])["sent"] is False
        assert tx.scan("tasks") == []


def test_unpublished_worker_result_stops_the_cycle_instead_of_an_idle_success():
    svc, operation, executor, budget, _ = build_operation()

    class LosesTheReport(Bus):
        """The assignment travels; the worker's own task.result never reaches the transport."""

        def publish(self, message):
            if message["type"] == "task.result":
                raise MessageDeliveryError("transport unavailable (fixture)")
            return super().publish(message)
    operation.bus = LosesTheReport()
    receipt = operation.run(operation_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "failed" and receipt["reason_code"] == "publication_incomplete"
    assert executor.calls == ["task"] and len(budget.reserved) == 1, "the reviewer is never reserved"
    assert receipt["cycle"]["cycle"]["stopped_reason"] == "publication_incomplete"
    with svc.store.transaction() as tx:
        assert tx.scan("decisions_pending") == [] and [t["status"] for t in tx.scan("tasks")] == ["succeeded"]
        assert any(row["sent"] is False and row["message"]["type"] == "task.result" for row in tx.scan("outbox"))


def test_only_the_current_execution_notice_is_published_and_the_foreign_one_waits_for_the_global_relay():
    """Implementation014 handling is unchanged: a foreign notice stays an unsent record here and is
    still published by the default background relay; only the current correlation's own notice is
    part of this run's scoped batch."""
    svc = service()
    rows = {CORR: {"id": "t-current", "agent": "worker:implementation", "status": "failed", "attempt": 1,
                   "generation": 1, "message": {"correlation_id": CORR}},
            FOREIGN: {"id": "t-older", "agent": "worker:implementation", "status": "expired", "attempt": 1,
                      "generation": 1, "message": {"correlation_id": FOREIGN}}}
    notices = {}
    for correlation, row in rows.items():
        with svc.store.transaction() as tx:
            notices[correlation] = record(tx, svc.org, row, "tasks", "execution_failed", "2026-01-18T06:12:35+00:00")
    bus = RecordingBus()
    batch = relay(svc.store, svc.org, bus, correlation_id=CORR)
    assert batch["published"] == 1 and batch["complete"] is True
    assert [m["message_id"] for m in bus.published] == [notices[CORR]["id"]]
    with svc.store.transaction() as tx:
        assert tx.get("outbox", notices[FOREIGN]["id"])["sent"] is False
        assert tx.get("outbox_delivery", notices[FOREIGN]["id"]) is None
    assert svc.flush_outbox(bus)["published"] == 1
    assert [m["message_id"] for m in bus.published][-1] == notices[FOREIGN]["id"]


# ----- workflow-generated commands in the delivery seam ----------------------------------------
def test_unpublished_workflow_command_stops_the_cycle_before_any_candidate_or_execution():
    """A report handled inside `LocalCycle._deliver` queues its own follow-up command. If that
    command cannot be published, the cycle stops with the named reason instead of proceeding to a
    candidate, and the message is left pending (no ACK, no dead letter, no provider entry)."""
    svc = service()
    svc.record_incident(incident("occurrence-one"))  # below the threshold: no hook and no command yet
    cycle_task(svc, "t-current", correlation=CORR)  # the cycle would execute this without the stop
    LocalCycle(svc).start("c-scoped", CORR, 2)
    bus = RefusingCycleBus([("1-0", incident("occurrence-two"))])
    executor = CycleExecutor(svc)
    result = LocalCycle(svc, executor, bus, Workflow(svc.store, svc.org)).step("c-scoped")
    # The material claim: nothing executes and nothing is acknowledged after the failed publication.
    # Without the stop the cycle still reaches `publication_incomplete` through its post-execution
    # flush, but only after a reservation and a provider entry it was never entitled to.
    assert executor.calls == [] and bus.acked == [] and bus.dead == []
    assert LocalCycle(svc).status("c-scoped")["executions"] == 0
    assert result["cycle"]["status"] == "stopped" and result["reason"] == "publication_incomplete"
    assert result["action"] == "messages" and result["messages"][-1]["publication"] == "incomplete"
    with svc.store.transaction() as tx:
        [row] = tx.scan("outbox")
        assert row["sent"] is False and row["message"]["correlation_id"] == CORR
        assert [d["status"] for d in tx.scan("outbox_delivery")] == ["retry"], "the intent is kept, not retried"
        assert tx.get("tasks", "t-current")["status"] == "queued"


def test_autonomous_delivery_refuses_when_a_workflow_generated_command_is_not_published():
    """The same seam on the council/autonomous side (`AutonomousRun._deliver`, used by the conductor
    relay): the derived command is committed, unproven on the transport, and the run refuses."""
    svc, run, executor, budget = build_autonomous()
    hook = {"id": "hook-fixture", "fingerprint": "f" * 24, "status": "required", "scope": "fixture",
            "root_cause": "scoped-publication", "occurrences": [], "evidence_refs": [], "version": 1,
            "spec": None, "revision": None, "author": None, "reviews": [], "canary": None}
    with svc.store.transaction() as tx:
        tx.put("hooks", hook["id"], hook)
    required = envelope("hook.required", "lead:improvement", "conductor", "implement_hook",
                        {"hook_id": hook["id"], "evidence_refs": []}, CORR)
    run.bus = RefusingBus()
    run.bus.queued.append(("1-0", required))
    with pytest.raises(AutonomousRefused) as info:
        run._deliver("conductor", CORR)
    assert info.value.reason_code == "publication_incomplete"
    assert run.bus.acked == [] and executor.calls == [] and budget.reserved == []
    with svc.store.transaction() as tx:
        [row] = tx.scan("outbox")
        assert row["sent"] is False and row["message"]["correlation_id"] == CORR
        assert row["message"]["who"]["recipient"] == "lead:improvement"
        assert [d["status"] for d in tx.scan("outbox_delivery")] == ["retry"]


def test_foreign_unsent_commands_never_reach_the_current_run_consumer():
    svc, operation, executor, budget, _ = build_operation()
    foreign = queue(svc, str(uuid4()), "improvement:another-run", sender="conductor",
                    recipient="lead:improvement", action="plan")
    receipt = operation.run(operation_valid(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted", "an unrelated queued command cannot stop this correlation"
    assert foreign not in [m["message_id"] for m in operation.bus.published]
    with svc.store.transaction() as tx:
        assert tx.get("outbox", foreign)["sent"] is False and tx.get("outbox_delivery", foreign) is None

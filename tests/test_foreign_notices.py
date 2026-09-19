"""Implementation014: informational execution notices on the shared transport.

The outbox and the execution store are shared, so a persisted `execution.notice` of an OLDER
execution can reach the stream a current run drains (live006: an expired conductor task of
autonomous:research-live-004.c001 on the current conductor stream). Both consumers,
`AutonomousRun._deliver` (the council relay included) and `LocalCycle._deliver`, may consume such a
notice only after `execution_notices.receive` proved it against the stored transition and bound it
in the inbox, committed before the ACK; it is informational only and never advances current work.

Every executor, bus, budget, observer and store wrapper here is a labelled fixture: no Claude,
Codex, Redis or PostgreSQL. The notices are produced by the real `execution_notices.record` and
relayed by the real outbox relay; the workflow and store are the real ones.
"""
from copy import deepcopy

import pytest
from test_autonomous import build as build_autonomous
from test_council import ORDER
from test_council import build as build_council
from test_council import valid as valid_council
from test_local_cycle import CORR
from test_local_cycle import FakeExecutor as CycleExecutor
from test_operation import BOUND_GOAL, IDENTITY, Bus
from test_operation_finalization import GatedStore, spool_observer

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.autonomous import AutonomousRefused
from codex_harness.application.execution_notices import receive_foreign, record
from codex_harness.application.local_cycle import MESSAGE_DRAIN, LocalCycle, flush_outbox
from codex_harness.application.operation_finalization import MESSAGE_DISPOSITIONS, parkable
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, envelope

OLD = "autonomous:research-live-004.c001"  # the older council whose conductor task expired (live006 shape)
CURRENT = "autonomous:current-run"
OLD_TASK = "d552756e-old-conductor-task"
OLD_OPERATION = "operation:op-old"
WORKER, LEAD, CONDUCTOR = "worker:implementation", "lead:improvement", "conductor"
INFORMATIONAL = "informational_only"
AUTHORITY_BUCKETS = ("tasks", "decisions_pending", "invocation_reservations", "promotions", "execution_notices",
                     "local_cycles", "autonomous_runs", "operations", MESSAGE_DISPOSITIONS)


class Transport(Bus):
    """The in-memory stream stand-in of test_operation plus a dead-letter record (fixture)."""

    def __init__(self):
        super().__init__()
        self.dead = []

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append(entry_id)
        super().dead_letter(agent, entry_id, fields, reason)

    def pending(self):
        return [entry for entry, _ in self.queued if entry not in self.acked]


def recorded_notice(svc, agent, correlation, task_id=OLD_TASK, reason="deadline_exceeded", status="expired"):
    """A genuine persisted notice of an OLDER execution through the real `record` (the live006 shape:
    the row is expired with deadline_exceeded); the recipient is the agent's reporting parent."""
    row = {"id": task_id, "agent": agent, "status": status, "attempt": 1, "generation": 1,
           "message": {"correlation_id": correlation}}
    with svc.store.transaction() as tx:
        notice = record(tx, svc.org, row, "tasks", reason, "2026-01-18T06:12:35+00:00")
    assert notice.get("authority") == INFORMATIONAL, "the fixture row must record a real notice, not a quarantine"
    return notice


def relayed(svc, bus, notice):
    """Relay the recorded notice through the real outbox onto the fixture stream; returns its entry id."""
    assert flush_outbox(svc, bus)["published"] == 1
    [entry] = [entry for entry, message in bus.queued if message["message_id"] == notice["id"]
               and entry not in bus.acked]
    return entry


def current_report(svc, correlation=CURRENT, task_id="t-current-dba"):
    """A real succeeded lead task row of the current run and the task.result it files to the conductor."""
    assignment = envelope("task.assign", CONDUCTOR, "lead:dba", "dge_role", {"role": "dba"}, correlation)
    result = {"summary": "current report", "execution_ref": "sha256:" + "1" * 64}
    with svc.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": "lead:dba", "status": "succeeded", "attempt": 1,
                                  "generation": 1, "message": assignment, "result": result})
    return envelope("task.result", "lead:dba", CONDUCTOR, "dge_role", {"task_id": task_id, "result": result},
                    correlation, task_id)


def authority_state(tx) -> dict:
    """Every record that could carry workflow, model or promotion authority, plus the notice source rows."""
    return {bucket: tx.scan(bucket) for bucket in AUTHORITY_BUCKETS}


def outbox_message(tx, notice):
    return tx.get("outbox", notice["id"])["message"]


def unproven(svc, notice, variant):
    """The unproven matrix for a notice this store did NOT prove (fixture mutations, labelled)."""
    message = deepcopy(notice["message"])
    if variant == "missing":  # the same real notice recorded in ANOTHER store: nothing proves it here
        other = Harness(MemoryStore(), organization())
        message = deepcopy(recorded_notice(other, notice["message"]["who"]["sender"], OLD, "elsewhere-task")["message"])
    elif variant == "tampered_transition":  # the stored transition no longer hashes to the notice id
        with svc.store.transaction() as tx:
            row = tx.get("execution_notices", notice["id"])
            row["transition"]["status"] = "succeeded"
            tx.put("execution_notices", notice["id"], row)
    elif variant == "conflicting_body":  # same id, different bytes
        message["what"]["details"]["reason_code"] = "execution_failed"
    else:
        raise AssertionError(variant)
    return message


# ----- AutonomousRun._deliver (the council conductor relay uses the same boundary) ---------------
def test_autonomous_boundary_commits_a_proven_foreign_notice_before_ack_and_handles_the_current_report_once():
    svc, run, executor, budget = build_autonomous()
    bus = run.bus = Transport()
    run.observer = spool_observer(svc.store)
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    first = relayed(svc, bus, notice)  # the old notice precedes the current report, as in live006
    report = current_report(svc)
    report_entry = bus.publish(report)
    again = bus.publish(deepcopy(notice["message"]))  # identical redelivery behind the report
    with svc.store.transaction() as tx:
        before, source = authority_state(tx), outbox_message(tx, notice)
    handled = run._deliver(CONDUCTOR, CURRENT)
    assert [m["message_id"] for m in handled] == [report["message_id"]], "only the current report went through the workflow"
    assert bus.acked == [first, report_entry, again] and bus.dead == [] and bus.pending() == []
    assert executor.calls == [] and budget.reserved == [], "no model call, no reservation"
    with svc.store.transaction() as tx:
        inbox = tx.get("workflow_inbox", notice["id"])
        assert inbox["result"] == {"handled": True, "notice_id": notice["id"], "authority": INFORMATIONAL}
        assert tx.get("workflow_inbox", report["message_id"])["result"]["handled"] is True
        assert len(tx.scan("workflow_inbox")) == 2, "one binding per notice id, one per report"
        assert authority_state(tx) == before and outbox_message(tx, notice) == source == notice["message"]
    events = [(r["event_type"], r["causation_id"]) for r in run.observer.spool.records()
              if r["event_type"].startswith("general.message_")]
    expected = [("general.message_received", notice["id"]), ("general.message_accepted", notice["id"]),
                ("general.message_acknowledged", notice["id"])]
    assert events[:3] == expected and events[-3:] == expected, "existing receive/accept/ack contracts, both deliveries"
    assert run._deliver(CONDUCTOR, CURRENT) == [] and bus.acked == [first, report_entry, again]


@pytest.mark.parametrize("variant", ["missing", "tampered_transition", "conflicting_body"])
def test_autonomous_boundary_refuses_an_unproven_foreign_notice_without_ack_or_progress(variant):
    svc, run, executor, budget = build_autonomous()
    bus = run.bus = Transport()
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    message = unproven(svc, notice, variant)
    entry = bus.publish(message)
    report_entry = bus.publish(current_report(svc))  # the current report waits behind the unproven notice
    with svc.store.transaction() as tx:
        before = authority_state(tx)
    with pytest.raises(AutonomousRefused, match="foreign_message"):
        run._deliver(CONDUCTOR, CURRENT)
    assert bus.acked == [] and bus.dead == [] and bus.pending() == [entry, report_entry]
    assert executor.calls == [] and budget.reserved == []
    with svc.store.transaction() as tx:
        assert tx.scan("workflow_inbox") == [] and authority_state(tx) == before


def test_autonomous_boundary_conflicting_redelivery_after_a_proven_notice_is_refused_and_the_binding_stays():
    svc, run, executor, budget = build_autonomous()
    bus = run.bus = Transport()
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    first = relayed(svc, bus, notice)
    assert run._deliver(CONDUCTOR, CURRENT) == [] and bus.acked == [first]
    twin = bus.publish(unproven(svc, notice, "conflicting_body"))
    with svc.store.transaction() as tx:
        binding = tx.get("workflow_inbox", notice["id"])
    with pytest.raises(AutonomousRefused, match="foreign_message"):
        run._deliver(CONDUCTOR, CURRENT)
    assert bus.pending() == [twin] and bus.dead == []
    with svc.store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"]) == binding and len(tx.scan("workflow_inbox")) == 1


def test_autonomous_boundary_keeps_route_rejection_and_foreign_commands_as_before():
    svc, run, executor, budget = build_autonomous()
    bus = run.bus = Transport()
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    wrong_route = deepcopy(notice["message"])
    wrong_route["who"]["sender"] = WORKER  # a worker cannot notify the conductor: the reporting edge refuses it
    bad = bus.publish(wrong_route)
    command = bus.publish(envelope("task.result", "lead:dba", CONDUCTOR, "dge_role", {"task_id": "x", "result": {}}, OLD))
    with pytest.raises(AutonomousRefused, match="foreign_message"):
        run._deliver(CONDUCTOR, CURRENT)
    assert bus.dead == [bad] and bus.pending() == [command], "route rejection dead-letters, a foreign report stays pending"
    with svc.store.transaction() as tx:
        assert tx.scan("workflow_inbox") == [] and tx.get("tasks", "x") is None and tx.scan("decisions_pending") == []


def test_autonomous_boundary_storage_failure_never_acks_and_a_later_delivery_persists_the_notice():
    svc, run, executor, budget = build_autonomous()
    bus = run.bus = Transport()
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    entry = relayed(svc, bus, notice)
    store = svc.store
    svc.store = GatedStore(store, lambda bucket, key, body: bucket == "workflow_inbox", fail=True)
    with pytest.raises(OSError, match="fixture"):
        run._deliver(CONDUCTOR, CURRENT)
    assert bus.acked == [] and bus.pending() == [entry] and executor.calls == []
    with store.transaction() as tx:
        assert tx.scan("workflow_inbox") == [] and tx.get("execution_notices", notice["id"]) == notice
    svc.store = store
    assert run._deliver(CONDUCTOR, CURRENT) == [] and bus.acked == [entry]
    with store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"])["result"]["authority"] == INFORMATIONAL
    assert executor.calls == [] and budget.reserved == []


def test_council_relay_consumes_an_older_conductor_notice_and_the_fixture_council_reaches_promotion():
    baseline_svc, baseline, *_ = build_council()
    assert baseline.run(valid_council(), IDENTITY, BOUND_GOAL)["status"] == "accepted"
    with baseline_svc.store.transaction() as tx:
        expected = {bucket: len(tx.scan(bucket)) for bucket in ("tasks", "decisions_pending", "invocation_reservations", "promotions")}
    svc, run, executor, budget, port = build_council()
    notice = recorded_notice(svc, CONDUCTOR, OLD)
    entry = relayed(svc, run.bus, notice)  # the shared outbox puts the old notice on the current conductor stream first
    receipt = run.run(valid_council(), IDENTITY, BOUND_GOAL)
    assert receipt["status"] == "accepted" and receipt["reason_code"] == "promoted" and receipt["exit_code"] == 0
    assert executor.calls == ORDER and entry in run.bus.acked
    with svc.store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"])["result"]["authority"] == INFORMATIONAL
        assert tx.get("execution_notices", notice["id"]) == notice and outbox_message(tx, notice) == notice["message"]
        assert {bucket: len(tx.scan(bucket)) for bucket in expected} == expected, "the notice added no task, decision, reservation or promotion"
        assert tx.get("tasks", OLD_TASK) is None
        assert all(row["message"]["correlation_id"] != OLD for row in tx.scan("tasks") + tx.scan("decisions_pending"))


# ----- LocalCycle._deliver (the implementation/review transport) ----------------------------------
def cycle_build(executor=None):
    svc = Harness(MemoryStore(), organization())
    bus = Transport()
    executor = executor or CycleExecutor(svc)
    cycle = LocalCycle(svc, executor, bus, Workflow(svc.store, svc.org), observer=spool_observer(svc.store))
    cycle.start("c1", CORR, 4)
    return svc, cycle, bus, executor


def test_cycle_interleaves_proven_foreign_notices_with_own_work_and_keeps_a_foreign_command_pending():
    svc, cycle, bus, executor = cycle_build()
    first = recorded_notice(svc, WORKER, "improvement:other", "t-other-1")
    entry_a = relayed(svc, bus, first)
    own = envelope("task.assign", CONDUCTOR, LEAD, "plan", {"objective": "own"}, CORR)
    entry_own = bus.publish(own)
    second = recorded_notice(svc, WORKER, "improvement:other", "t-other-2")
    entry_b = relayed(svc, bus, second)
    foreign = envelope("task.assign", CONDUCTOR, LEAD, "plan", {"objective": "foreign"}, "improvement:other")
    command = bus.publish(foreign)
    result = cycle.step("c1")
    assert result["action"] == "messages" and result["reason"] == "foreign_correlation"
    receipts = result["messages"]
    assert [r.get("notice") or r.get("type") or r.get("refused") for r in receipts] == [first["id"], "task.assign", second["id"], "foreign_correlation"]
    assert receipts[0]["authority"] == receipts[2]["authority"] == INFORMATIONAL and receipts[1]["handled"] is True
    assert bus.acked == [entry_a, entry_own, entry_b] and bus.pending() == [command] and bus.dead == []
    assert executor.calls == [], "the drain stopped before any executor start"
    with svc.store.transaction() as tx:
        assert {row["result"]["notice_id"] for row in tx.scan("workflow_inbox")} == {first["id"], second["id"]}
        assert tx.get("tasks", own["message_id"])["message"]["correlation_id"] == CORR, "own work stays queued under its owner"
        assert tx.get("tasks", foreign["message_id"]) is None and tx.scan(MESSAGE_DISPOSITIONS) == []
        assert [tx.get("workflow_inbox", n["id"])["result"]["authority"] for n in (first, second)] == [INFORMATIONAL] * 2
        assert tx.get("local_cycles", "c1")["status"] == "stopped" and tx.get("local_cycles", "c1")["executions"] == 0
    kinds = [r["event_type"] for r in cycle.observer.spool.records() if r["causation_id"] == first["id"]]
    assert kinds == ["general.message_received", "general.message_accepted", "general.message_acknowledged"]


def test_cycle_redelivery_is_idempotent_and_the_drain_stays_bounded():
    svc, cycle, bus, executor = cycle_build()
    notices = [recorded_notice(svc, WORKER, "improvement:other", "t-other-%d" % index) for index in range(MESSAGE_DRAIN + 1)]
    assert flush_outbox(svc, bus)["published"] == MESSAGE_DRAIN + 1
    bus.publish(deepcopy(notices[0]["message"]))  # identical redelivery at the tail
    first = cycle.step("c1")
    assert first["action"] == "none" and first["reason"] == "idle" and len(bus.acked) == MESSAGE_DRAIN
    second = cycle.step("c1")
    assert second["reason"] == "idle" and len(bus.acked) == MESSAGE_DRAIN + 2 and bus.pending() == []
    assert all(r["authority"] == INFORMATIONAL for r in first["messages"] + second["messages"])
    assert executor.calls == []
    with svc.store.transaction() as tx:
        assert len(tx.scan("workflow_inbox")) == MESSAGE_DRAIN + 1, "one binding per notice, the redelivery bound nothing new"
        assert tx.get("local_cycles", "c1")["status"] == "active" and tx.get("local_cycles", "c1")["executions"] == 0


@pytest.mark.parametrize("variant", ["missing", "tampered_transition", "conflicting_body"])
def test_cycle_refuses_an_unproven_foreign_notice_without_ack_and_stops(variant):
    svc, cycle, bus, executor = cycle_build()
    notice = recorded_notice(svc, WORKER, "improvement:other")
    entry = bus.publish(unproven(svc, notice, variant))
    with svc.store.transaction() as tx:
        before = authority_state(tx)
    result = cycle.step("c1")
    assert result["reason"] == "foreign_correlation" and result["messages"][-1]["refused"] == "ContractError"
    assert bus.acked == [] and bus.dead == [] and bus.pending() == [entry] and executor.calls == []
    with svc.store.transaction() as tx:
        assert tx.scan("workflow_inbox") == []
        state = authority_state(tx)
        assert state.pop("local_cycles")[0]["status"] == "stopped" and before.pop("local_cycles")[0]["status"] == "active"
        assert state == before


def test_cycle_wrong_route_notice_is_dead_lettered_never_informational():
    svc, cycle, bus, executor = cycle_build()
    notice = recorded_notice(svc, WORKER, "improvement:other")
    wrong = deepcopy(notice["message"])
    wrong["who"]["sender"] = "worker:github"  # reports to lead:research, not to lead:improvement
    bad = bus.publish(wrong)
    result = cycle.step("c1")
    assert result["messages"] == [{"entry_id": bad, "rejected": "ContractError"}] and result["reason"] == "idle"
    assert bus.dead == [bad]
    with svc.store.transaction() as tx:
        assert tx.scan("workflow_inbox") == []


def test_cycle_terminal_operation_notice_needs_the_proof_and_parking_stays_for_reports():
    svc, cycle, bus, executor = cycle_build()
    with svc.store.transaction() as tx:  # a terminal operation that owns OLD_OPERATION (fixture row in the owner's shape)
        tx.put("operations", "op-old", {"id": "op-old", "correlation_id": OLD_OPERATION, "cycle_id": OLD_OPERATION,
                                        "assignment_message_id": "a-old", "status": "failed"})
    late = envelope("execution.notice", WORKER, LEAD, "observe_execution", {"reason_code": "late"}, OLD_OPERATION)
    assert parkable(svc.store, late) is not None, "the terminal parking shortcut would accept this unproven notice"
    entry = bus.publish(late)
    result = cycle.step("c1")
    assert result["reason"] == "foreign_correlation" and result["messages"][-1]["refused"] == "ContractError"
    assert bus.acked == [] and bus.pending() == [entry]
    with svc.store.transaction() as tx:
        assert tx.scan(MESSAGE_DISPOSITIONS) == [] and tx.scan("workflow_inbox") == [], "no parking before proof"
    # A proven notice of the same terminal operation is informational, ACKed and never parked;
    # a late task.result of that operation keeps the existing parking path.
    svc, cycle, bus, executor = cycle_build()
    with svc.store.transaction() as tx:
        tx.put("operations", "op-old", {"id": "op-old", "correlation_id": OLD_OPERATION, "cycle_id": OLD_OPERATION,
                                        "assignment_message_id": "a-old", "status": "failed"})
    notice = recorded_notice(svc, WORKER, OLD_OPERATION, "t-old-worker")
    entry = relayed(svc, bus, notice)
    report = bus.publish(envelope("task.result", WORKER, LEAD, "implement", {"task_id": "x", "result": {"candidate": {}}}, OLD_OPERATION))
    result = cycle.step("c1")
    assert result["reason"] == "idle" and bus.acked == [entry, report] and executor.calls == []
    assert result["messages"][0]["notice"] == notice["id"] and "parked" not in result["messages"][0]
    assert result["messages"][1]["parked"] and result["messages"][1]["operation_id"] == "op-old"
    with svc.store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"])["result"]["authority"] == INFORMATIONAL
        [parked] = tx.scan(MESSAGE_DISPOSITIONS)
        assert parked["message_type"] == "task.result" and tx.scan("decisions_pending") == []


def test_cycle_storage_failure_never_acks_and_the_next_step_persists_the_notice():
    svc, cycle, bus, executor = cycle_build()
    notice = recorded_notice(svc, WORKER, "improvement:other")
    entry = relayed(svc, bus, notice)
    store = svc.store
    svc.store = GatedStore(store, lambda bucket, key, body: bucket == "workflow_inbox", fail=True)
    with pytest.raises(OSError, match="fixture"):
        cycle.step("c1")
    assert bus.acked == [] and bus.pending() == [entry] and executor.calls == []
    with store.transaction() as tx:
        assert tx.scan("workflow_inbox") == [] and tx.get("local_cycles", "c1")["status"] == "active"
        assert tx.get("local_cycles", "c1")["in_flight"] is None
    svc.store = store
    result = cycle.step("c1")
    assert result["reason"] == "idle" and bus.acked == [entry] and result["messages"][0]["authority"] == INFORMATIONAL
    with store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"])["result"]["notice_id"] == notice["id"]
    assert executor.calls == []


def test_cycle_own_notice_behaviour_is_unchanged():
    svc, cycle, bus, executor = cycle_build()
    notice = recorded_notice(svc, WORKER, CORR, "t-own")
    entry = relayed(svc, bus, notice)
    result = cycle.step("c1")
    assert result["reason"] == "execution_notice:deadline_exceeded" and result["cycle"]["status"] == "stopped"
    assert bus.acked == [entry] and result["messages"][0]["handled"] is True and "notice" not in result["messages"][0]
    with svc.store.transaction() as tx:
        assert tx.get("workflow_inbox", notice["id"])["result"]["authority"] == INFORMATIONAL


# ----- the shared helper -------------------------------------------------------------------------
def test_receive_foreign_is_the_receive_proof_in_its_own_transaction_and_only_for_notices():
    svc = Harness(MemoryStore(), organization())
    notice = recorded_notice(svc, WORKER, "improvement:other")
    message = deepcopy(notice["message"])
    with pytest.raises(ContractError, match="Not an execution notice"):
        receive_foreign(svc.store, {**message, "type": "task.result"})
    with pytest.raises(ContractError, match="Unproven"):
        receive_foreign(svc.store, unproven(svc, notice, "conflicting_body"))
    with svc.store.transaction() as tx:
        assert tx.scan("workflow_inbox") == [], "a failed proof writes nothing"
    result = receive_foreign(svc.store, message)
    assert result == {"handled": True, "notice_id": notice["id"], "authority": INFORMATIONAL}
    assert receive_foreign(svc.store, deepcopy(message)) == result
    with pytest.raises(ContractError, match="Conflicting execution notice delivery"):
        receive_foreign(svc.store, unproven(svc, notice, "conflicting_body"))
    with svc.store.transaction() as tx:
        assert len(tx.scan("workflow_inbox")) == 1 and tx.get("execution_notices", notice["id"]) == notice

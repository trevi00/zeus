"""`zeus audit-service` (self-improvement-reference-001, operating connection handoff).

Every executor, transport and release here is an injected fixture. No test in this file calls
Codex, Claude, Redis, PostgreSQL or any other provider: these are contract tests over the real
store, the real `schedule_audits`, the real Workflow claim/checkpoint/complete path and the real
observation contract, never evidence that a model ran or that a host service started.
"""
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_research_audits import (  # noqa: F401  `audit` is a pytest fixture: importing registers it
    activate_fixture,
    audit,
)

from codex_harness.adapters import audit_service
from codex_harness.adapters.contracts import validate_message
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.domain.model import canonical, digest, envelope
from codex_harness.domain.research import PartitionCheckpoint

REVISION = "audit"  # the fixture release revision `activate_fixture` promotes


class FixtureBus:
    """A stand-in transport with the RedisBus surface this service uses.

    Delivery is per consumer and at least once: an entry is handed to a consumer once and stays in
    the stream until it is acknowledged, so an entry this service skips remains for its own owner.
    """

    def __init__(self):
        self.streams, self.published, self.acked, self.delivered = {}, [], [], {}

    @staticmethod
    def validate(message):
        return validate_message(message)

    def publish(self, message):
        self.validate(message)
        entry_id = str(len(self.published) + 1)
        self.published.append(message)
        self.streams.setdefault(message["who"]["recipient"], []).append(
            (entry_id, {"body": canonical(message)}))
        return entry_id

    def receive(self, agent, consumer, idle_ms=60000):
        seen = self.delivered.setdefault((agent, consumer), set())
        for entry_id, fields in self.streams.get(agent) or []:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            return entry_id, fields
        return None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)
        self.streams[agent] = [row for row in self.streams.get(agent, []) if row[0] != entry_id]

    @staticmethod
    def decode(fields):
        return validate_message(json.loads(fields["body"]))


class FixtureExecutor:
    """Stand-in for the real Executor: it drives the REAL claim, checkpoint and complete path with
    the guard it was given, and never enters a provider. `status` and `error` are injected."""

    def __init__(self, audits, status="succeeded", error=None):
        self.audits, self.status, self.error = audits, status, error
        self.calls = []

    def execute_one(self, agent, expected=None):
        self.calls.append({"agent": agent, "expected": expected})
        workflow = self.audits.workflow
        task = workflow.claim(agent, "audit-service-fixture-" + uuid4().hex, expected=expected)
        if task is None:
            return None
        if self.error is not None:
            raise self.error
        if self.status != "succeeded":
            return workflow.fail(task, "injected failure", retryable=self.status == "retry")
        details = task["message"]["what"]["details"]
        with self.audits.store.transaction() as tx:
            partition = tx.get("research_partitions", details["partition_id"])
        # A real application checkpoint with no coverage: the generation advances and every
        # remaining path stays remaining (INV-RESEARCH-001, no semantic credit).
        saved = self.audits.checkpoint(
            task, replace(PartitionCheckpoint(**partition), cursor="fixture-cursor"), [], [])
        return workflow.complete(task, saved)


class FixtureCollector:
    """Stand-in for the observation collector: it records that a drain was asked for."""

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def collect(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"files": 1, "records": 3, "inserted": 3, "sink_failures": 0, "corrupt": 0,
                "refused": 0, "dropped_key": "not reported"}


@pytest.fixture
def connected(audit):  # noqa: F811  the imported fixture is the parameter
    """The existing audit fixture, partitioned, with a fixture release promoted and a Harness on
    the SAME store. The release, its reviews and its checks are fixtures, not a deployment."""
    audits, record, source, entries, _ = audit
    activate_fixture(audits, revision=REVISION)
    partitions = audits.partition(record["id"], 1)
    service = Harness(audits.store, audits.workflow.org)
    return SimpleNamespace(service=service, audits=audits, audit_id=record["id"],
                           partitions=partitions, store=audits.store)


def runner(connected, executor=None, bus=None, collector=None, **kwargs):
    bus = FixtureBus() if bus is None else bus
    executor = FixtureExecutor(connected.audits) if executor is None else executor
    return audit_service.AuditServiceRunner(
        connected.service, connected.audit_id, executor=executor, bus=bus,
        workflow=Workflow(connected.store, connected.service.org), collector=collector,
        revision=REVISION, release_id="fixture-release", sleep=lambda _: None, **kwargs), bus, executor


def spool_observer(connected):
    """A real Observer over an in-process spool: the observation contract runs, no sink is needed."""
    from codex_harness.adapters.observation_spool import MemorySpool
    from codex_harness.application.observations import MemoryDirectory, Observer

    return Observer(connected.store, MemorySpool(uuid4().hex), component="unit",
                    directory=MemoryDirectory(), role="worker:github")


def partitions_of(connected, audit_id=None):
    with connected.store.transaction() as tx:
        return [p for p in tx.scan("research_partitions")
                if p["audit_id"] == (audit_id or connected.audit_id)]


def foreign_audit(connected, audit_id="foreign-audit-fixture"):
    """A second audit with one partition, written as a labelled fixture row (no second import)."""
    checkpoint = PartitionCheckpoint(audit_id, digest({"foreign": audit_id}), 0, ["Zm9yZWlnbg=="],
                                     [], [], ["Zm9yZWlnbg=="], [], [], "pending")
    checkpoint.validate()
    with connected.store.transaction() as tx:
        tx.put("research_audits", audit_id, {"id": audit_id, "version": 1, "inventory": [],
                                             "subsystems": [], "status": "source_verified_not_reviewed"})
        tx.put("research_partitions", checkpoint.partition_id, asdict(checkpoint))
    return audit_id, checkpoint.partition_id


# ----- the run gate: only a matching active release and an explicitly selected audit ------------
def test_the_gate_refuses_inactive_stale_foreign_and_unknown_scope(connected):
    store, org = connected.store, connected.service.org
    assert audit_service.activation(store, org, connected.audit_id, REVISION)["partitions"] == 4
    with pytest.raises(audit_service.AuditServiceRefused, match="unknown_audit"):
        audit_service.activation(store, org, "absent-audit", REVISION)
    with pytest.raises(audit_service.AuditServiceRefused, match="audit_id_invalid"):
        audit_service.activation(store, org, "   ", REVISION)
    with pytest.raises(audit_service.AuditServiceRefused, match="revision_mismatch"):
        audit_service.activation(store, org, connected.audit_id, "b" * 40)
    with connected.store.transaction() as tx:
        graph = tx.get("research_control", "graph")
        tx.put("research_control", "graph", {**graph, "organization": digest("another graph")})
    with pytest.raises(audit_service.AuditServiceRefused, match="graph_mismatch"):
        audit_service.activation(store, org, connected.audit_id, REVISION)


def test_a_legacy_or_paused_activation_is_stale_and_a_partitionless_audit_is_refused(connected):
    store, org = connected.store, connected.service.org
    with connected.store.transaction() as tx:  # an imported audit nobody has partitioned yet
        tx.put("research_audits", "unpartitioned-fixture", {"id": "unpartitioned-fixture",
                                                            "version": 1, "inventory": []})
    with pytest.raises(audit_service.AuditServiceRefused, match="audit_not_partitioned"):
        audit_service.activation(store, org, "unpartitioned-fixture", REVISION)
    with connected.store.transaction() as tx:
        control = tx.get("research_control", "activation")
        # A legacy row that identifies no release (test_research_audits keeps the same shape).
        tx.put("research_control", "activation", {k: v for k, v in control.items() if k != "release_id"})
    with pytest.raises(audit_service.AuditServiceRefused, match="activation_stale"):
        audit_service.activation(store, org, connected.audit_id, REVISION)
    with connected.store.transaction() as tx:
        tx.put("research_control", "activation", {"status": "paused", "release_id": "any"})
    with pytest.raises(audit_service.AuditServiceRefused, match="activation_inactive"):
        audit_service.activation(store, org, connected.audit_id, REVISION)


def cli_run(tmp_path, monkeypatch, connected, spy, revision=REVISION):
    """`zeus audit-service run` with the real lock and gate, and NO wiring behind them."""
    from codex_harness.adapters import configuration

    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(audit_service, "current_revision", lambda: revision)
    monkeypatch.setattr(audit_service, "build_runner", spy)
    return SimpleNamespace(audit_service_command="run", audit_id=connected.audit_id,
                           max_tasks=None, once=True)


def test_a_stale_activation_and_a_duplicate_owner_build_nothing(tmp_path, monkeypatch, connected):
    from filelock import FileLock

    def forbidden(*args, **kwargs):
        raise AssertionError("the run gate built a runner, an executor or a provider")

    args = cli_run(tmp_path, monkeypatch, connected, forbidden)
    with connected.store.transaction() as tx:
        tx.put("research_control", "activation", {"status": "paused", "release_id": "any"})
    assert audit_service.execute(connected.service, args) == {
        "status": "refused", "reason_code": "activation_inactive",
        "error_type": "AuditServiceRefused", "exit_code": 1}
    with connected.store.transaction() as tx:  # restore the active fixture activation
        tx.put("research_control", "activation", {"status": "active", "release_id": tx.get(
            "deployment", "active")["release_id"], "revision": REVISION})
    lock = FileLock(str(tmp_path / "audit-service.lock"), timeout=0)
    lock.acquire()
    try:
        assert audit_service.execute(connected.service, args)["reason_code"] == "audit_service_lock_busy"
    finally:
        lock.release()


# ----- normal continuation over the existing scheduler, transport, guard and checkpoint ---------
def test_two_task_continuation_uses_the_existing_records_and_keeps_the_successor(connected):
    collector = FixtureCollector()
    service_runner, bus, executor = runner(connected, collector=collector, max_tasks=2)
    summary = service_runner.run(once=True)
    assert summary["completed_tasks"] == 2 and summary["stop_reason"] == "max_tasks_reached"
    assert [step["status"] for step in summary["steps"] if step["action"] == "task"] == \
        ["succeeded", "succeeded"]
    # The claim was guarded by the exact assignment identity, never by a bare agent claim.
    with connected.store.transaction() as tx:
        rows = {t["id"]: t for t in tx.scan("tasks")}
    for call in executor.calls:
        guard = call["expected"]
        assert call["agent"] == "worker:github" and guard["statuses"] == {"queued"}
        assert rows[guard["id"]]["message"]["correlation_id"] == guard["correlation_id"]
        assert rows[guard["id"]]["message"]["what"]["details"]["audit_id"] == connected.audit_id
    # Two partitions advanced their checkpoint generation; no path became reviewed by running.
    advanced = [p for p in partitions_of(connected) if p["generation"] == 1]
    assert len(advanced) == 2
    assert all(set(p["remaining_paths"]) == set(p["paths"]) for p in advanced)
    # The queued successors keep their durable assignment and evidence; nothing was cancelled,
    # acknowledged or published away by the finite stop.
    with connected.store.transaction() as tx:
        scheduled = [row for row in tx.scan("schedule") if row.get("partition_id")]
        unsent = [row for row in tx.scan("outbox") if not row["sent"]]
        tasks = tx.scan("tasks")
    # Every assignment is either one of the two this service ran or is still waiting in its queue.
    assert len(tasks) == 2 and len(scheduled) >= 5 and len(unsent) == len(scheduled) - len(tasks)
    assert collector.calls == 2
    state = service_runner.state()
    assert state["current_task"] is None and state["completed_tasks"] == 2
    assert state["last_task"]["status"] == "succeeded" and state["last_collection"]["records"] == 3
    assert state["last_collection"].get("dropped_key") is None


def test_only_the_selected_audit_is_scheduled_executed_and_acknowledged(connected):
    from codex_harness.application.scheduling import schedule_audits

    foreign_id, foreign_partition = foreign_audit(connected)
    # The existing unnarrowed pass queues BOTH audits, exactly as a global scheduler pass does.
    assert schedule_audits(connected.service) == 5
    observer = spool_observer(connected)
    service_runner, bus, executor = runner(connected, max_tasks=1, observer=observer)
    # A foreign assignment that already sits on the shared agent stream, from another producer.
    foreign_message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                               {"audit_id": foreign_id, "partition_id": foreign_partition,
                                "generation": 0}, "audit:foreign-fixture")
    bus.publish(foreign_message)
    published_before = len(bus.published)
    summary = service_runner.run(once=True)
    assert summary["completed_tasks"] == 1
    # The narrowed pass adds nothing of its own and executes only the selected audit.
    assert [step for step in summary["steps"] if step["action"] == "task"][0]["status"] == "succeeded"
    with connected.store.transaction() as tx:
        tasks = tx.scan("tasks")
        foreign_outbox = [row for row in tx.scan("outbox")
                          if row["message"]["what"]["details"].get("partition_id") == foreign_partition]
    assert all(t["message"]["what"]["details"].get("audit_id") == connected.audit_id for t in tasks)
    # The foreign assignment keeps its own queue: unsent in the outbox, unpublished, unacknowledged,
    # never submitted as a task and never rewritten.
    assert len(foreign_outbox) == 1 and foreign_outbox[0]["sent"] is False
    during = bus.published[published_before:]
    assert [m["type"] for m in during] == ["task.assign", "task.result"]
    assert not any(foreign_partition in canonical(m) or foreign_id in canonical(m) for m in during)
    assert foreign_message["message_id"] not in {t["id"] for t in tasks}
    assert [json.loads(fields["body"])["message_id"] for _, fields in bus.streams["worker:github"]] \
        == [foreign_message["message_id"]]
    assert len(bus.acked) == 1
    scheduled = [event for event in observer.spool.records()
                 if event["event_type"] == "operations.audit_service_scheduled"]
    # Counted and left unacknowledged for its owner's recovery, never handled or acknowledged here.
    assert scheduled[0]["attributes"]["foreign_messages"] == 1


def test_the_claim_guard_refuses_a_foreign_row_and_stops_without_running_it(connected):
    service_runner, bus, executor = runner(connected)
    # An older, unrelated assignment for the same agent: the claim policy would take this one.
    other = envelope("task.assign", "lead:research", "worker:github", "research",
                     {"source": "github"}, "research:fixture")
    other["when"]["created_at"] = "2000-01-01T00:00:00+00:00"
    Workflow(connected.store, connected.service.org).submit(other)
    with connected.store.transaction() as tx:
        row = tx.get("tasks", other["message_id"])
        row["created_at"] = "2000-01-01T00:00:00+00:00"
        tx.put("tasks", row["id"], row)
    summary = service_runner.run(once=True)
    assert summary["stop_reason"] == "claim_guard_refused" and summary["completed_tasks"] == 0
    with connected.store.transaction() as tx:
        assert tx.get("tasks", other["message_id"])["status"] == "queued"
    assert service_runner.state()["current_task"] is None


# ----- the admission guard: every new admission re-reads the stop and the release gate ----------
def test_an_active_release_admits_the_next_step_unchanged(connected):
    """The control for the probes below: only the observed stop or activation transition differs."""
    service_runner, bus, executor = runner(connected)
    assert service_runner.step()["status"] == "succeeded"
    assert service_runner.step()["status"] == "succeeded"
    assert len(executor.calls) == 2 and service_runner.stopping is False
    assert service_runner.state()["completed_tasks"] == 2


@pytest.mark.parametrize("change,reason", [({"status": "paused"}, "activation_inactive"),
                                           ({"release_id": "another-release"}, "activation_stale")])
def test_a_paused_or_stale_release_after_the_first_step_admits_nothing_further(
        connected, change, reason):
    """Owner probe A: the startup gate alone let a queued successor run after a release pause."""
    service_runner, bus, executor = runner(connected)
    assert service_runner.step()["status"] == "succeeded"
    with connected.store.transaction() as tx:  # the control transition Releases pause/rollback makes
        control = tx.get("research_control", "activation")
        tx.put("research_control", "activation", {**control, **change})
    assert service_runner.step() == {"action": "stopped", "reason_code": reason}
    assert len(executor.calls) == 1 and service_runner.stopping is True
    assert service_runner.state()["stop_reason"] == reason
    # Nothing was bound, cancelled or acknowledged: the successors keep their durable assignments.
    with connected.store.transaction() as tx:
        scheduled = [row for row in tx.scan("schedule") if row.get("partition_id")]
        tasks = tx.scan("tasks")
    assert service_runner.state()["current_task"] is None
    assert len(tasks) == 1 and len(scheduled) >= 4


def test_a_stop_observed_during_delivery_binds_nothing_and_keeps_the_queued_work(
        tmp_path, monkeypatch, connected):
    """Owner probe B: a stop observed while this assignment's own message was in flight still
    entered the executor, because stop was only checked at step entry."""
    import codex_harness.bootstrap as bootstrap
    from codex_harness.adapters import configuration

    holder = {}

    class StoppingBus(FixtureBus):
        """`stop` is the same method the registered signal handler calls; the entry is normal."""

        def receive(self, agent, consumer, idle_ms=60000):
            entry = super().receive(agent, consumer, idle_ms)
            holder["runner"].stop()
            return entry

    service_runner, bus, executor = runner(connected, bus=StoppingBus())
    holder["runner"] = service_runner
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(audit_service, "current_revision", lambda: REVISION)
    monkeypatch.setattr(bootstrap, "build_observer",
                        lambda *args, **kwargs: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(audit_service, "build_runner",
                        lambda service, args, observer, gate: service_runner)
    result = audit_service.execute(connected.service, SimpleNamespace(
        audit_service_command="run", audit_id=connected.audit_id, max_tasks=None, once=True))
    assert executor.calls == [] and result["completed_tasks"] == 0
    # An operator interrupt is a shutdown with a recorded reason, not a failed run.
    assert result["stop_reason"] == "service_stopped" and result["exit_code"] == 0
    assert service_runner.state()["current_task"] is None
    # The delivered assignment keeps its own durable record, queued for the next admission.
    with connected.store.transaction() as tx:
        assert [task["status"] for task in tx.scan("tasks")] == ["queued"]


def test_a_gate_read_failure_after_startup_is_unknown_and_admits_nothing(monkeypatch, connected):
    service_runner, bus, executor = runner(connected)
    assert service_runner.step()["status"] == "succeeded"

    def unavailable(*args, **kwargs):  # an injected gate read loss, not a refusal
        raise RuntimeError("injected gate read failure")

    monkeypatch.setattr(audit_service, "activation", unavailable)
    assert service_runner.step() == {"action": "stopped", "reason_code": "activation_unavailable",
                                     "error_type": "RuntimeError"}
    assert len(executor.calls) == 1
    assert service_runner.state()["stop_reason"] == "activation_unavailable"


# ----- failure, restart and unknown state stop admission without a retry -------------------------
@pytest.mark.parametrize("status,reason", [("retry", "task_retry"), ("failed", "task_failed")])
def test_an_injected_failure_stops_admission_and_is_never_retried(connected, status, reason):
    executor = FixtureExecutor(connected.audits, status=status)
    service_runner, bus, _ = runner(connected, executor=executor)
    summary = service_runner.run(once=True)
    assert summary["stop_reason"] == reason and summary["completed_tasks"] == 0
    assert len(executor.calls) == 1  # one attempt, then the loop stopped
    state = service_runner.state()
    assert state["current_task"] is None and state["last_task"]["status"] == status
    # A restart refuses admission while the failed predecessor row is untouched.
    restarted, _, second = runner(connected)
    resumed = restarted.run(once=True)
    assert resumed["reconciliation"]["status"] == "reconciliation_required"
    assert resumed["stop_reason"] == reason and second.calls == []
    # The operator's own cancellation advances the execution generation and lifts the block.
    Workflow(connected.store, connected.service.org).cancel(
        state["last_task"]["task_id"], "conductor", "fixture operator reconciliation")
    third, _, third_executor = runner(connected, max_tasks=1)
    assert third.run(once=True)["completed_tasks"] == 1 and len(third_executor.calls) == 1


def test_an_interrupted_attempt_requires_reconciliation_and_starts_nothing(connected):
    service_runner, bus, executor = runner(connected, max_tasks=1)
    service_runner.run(once=True)
    task_id = service_runner.state()["last_task"]["task_id"]
    # Injected crash shape: the attempt was bound durably and its outcome was never recorded.
    service_runner._write(current_task={"task_id": task_id, "partition_id": "unknown-partition",
                                        "correlation_id": "audit:not-this-one", "bound_at": "now"})
    restarted, _, second = runner(connected)
    summary = restarted.run(once=True)
    assert summary["reconciliation"] == {"status": "reconciliation_required", "task_id": task_id,
                                         "reason_code": "unknown_execution"}
    assert summary["stop_reason"] == "unknown_execution" and second.calls == []
    assert restarted.state()["current_task"] is not None  # evidence is preserved, not cleared


def test_an_executor_exception_keeps_the_binding_for_explicit_reconciliation(connected):
    executor = FixtureExecutor(connected.audits, error=RuntimeError("injected transport loss"))
    service_runner, bus, _ = runner(connected, executor=executor)
    summary = service_runner.run(once=True)
    assert summary["stop_reason"] == "executor_exception"
    assert summary["steps"][-1]["error_type"] == "RuntimeError"
    assert service_runner.state()["current_task"]["task_id"] == executor.calls[0]["expected"]["id"]
    restarted, _, second = runner(connected)
    assert restarted.run(once=True)["reconciliation"]["status"] == "reconciliation_required"
    assert second.calls == []


def test_a_missing_stream_entry_stops_the_tick_without_any_execution(connected):
    class EmptyBus(FixtureBus):
        def receive(self, agent, consumer, idle_ms=60000):
            return None

    service_runner, bus, executor = runner(connected, bus=EmptyBus())
    summary = service_runner.run(once=True)
    assert summary["stop_reason"] == "message_missing" and executor.calls == []
    with connected.store.transaction() as tx:
        assert [t for t in tx.scan("outbox")]  # the assignment is retained, not lost


# ----- status, observation and the CLI surface ---------------------------------------------------
def test_status_reads_the_durable_records_and_builds_no_provider(connected):
    args = SimpleNamespace(audit_service_command="status", audit_id=connected.audit_id)
    before = audit_service.execute(connected.service, args)
    assert before["exit_code"] == 0 and before["known_audit"] is True
    assert before["partitions"]["total"] == 4 and before["partitions"]["max_generation"] == 0
    assert before["current_task"] is None and before["admission_blocked"] is None
    assert before["activation"]["status"] == "active" and before["supported_actions"] == ["audit_partition"]
    service_runner, _, _ = runner(connected, max_tasks=1)
    service_runner.run(once=True)
    after = audit_service.execute(connected.service, args)
    assert after["completed_tasks"] == 1 and after["last_task"]["status"] == "succeeded"
    assert after["partitions"]["max_generation"] == 1
    # One executed assignment; the rest are durable assignments nobody has submitted yet.
    assert after["assignments"]["succeeded"] == 1 and after["assignments"]["not_submitted"] >= 3
    # Scope counts from the partition record, never a reviewed or semantic count: the one item
    # this fixture partition holds is still remaining after the checkpoint advanced.
    last = after["last_task"]
    assert last["generation"] == 1 and last["remaining_paths"] + last["remaining_subsystems"] == 1
    # This fixture completes the task with a bare checkpoint body, exactly like the results written
    # before analysis outcomes existed: they stay unclassified and are never newly called accepted.
    assert last["analysis_outcome"] == "analysis_unclassified" and last["analysis_ref"] is None
    assert after["analysis"] == {"outcomes": {"analysis_unclassified": 1}, "held_partitions": 0,
                                 "held": []}


def test_the_observations_are_declared_events_with_identifiers_counts_and_codes(connected):
    from codex_harness.adapters.contracts import validate_observation
    from codex_harness.domain.observation import REGISTRY

    observer = spool_observer(connected)
    service_runner, _, _ = runner(connected, max_tasks=1, observer=observer)
    service_runner.run(once=True)
    events = observer.spool.records()
    types = [event["event_type"] for event in events]
    assert "operations.audit_service_started" in types and "operations.audit_service_task" in types
    assert {"operations.audit_service_stopped", "operations.audit_service_scheduled"} <= set(types)
    for event in events:
        validate_observation(event)
        # Declared attributes only: no prompt, cursor, path, credential or free text can appear.
        assert set(event["attributes"]) <= set(REGISTRY[event["event_type"]])
    task_event = [e for e in events if e["event_type"] == "operations.audit_service_task"][-1]
    attributes = task_event["attributes"]
    assert task_event["outcome"] == "succeeded" and attributes["status"] == "succeeded"
    # The execution status and the analysis outcome are two separate, declared facts.
    assert attributes["analysis_outcome"] == "analysis_unclassified"
    assert task_event["reason_code"] is None
    assert attributes["generation"] == 1 and attributes["audit_id"] == connected.audit_id
    assert attributes["remaining_paths"] + attributes["remaining_subsystems"] == 1
    stopped = [e for e in events if e["event_type"] == "operations.audit_service_stopped"][-1]
    assert stopped["reason_code"] == "max_tasks_reached"
    assert observer.counters["refused"] == 0


def test_the_cli_registers_run_and_status_and_a_refusal_exits_nonzero(tmp_path, monkeypatch, connected):
    from codex_harness import cli

    parsed = cli.parser().parse_args(["audit-service", "run", "--audit-id", "a1", "--max-tasks", "2"])
    assert (parsed.command, parsed.audit_service_command) == ("audit-service", "run")
    assert parsed.audit_id == "a1" and parsed.max_tasks == 2 and parsed.once is False
    status_args = cli.parser().parse_args(["audit-service", "status", "--audit-id", "a1"])
    assert status_args.audit_service_command == "status" and status_args.audit_id == "a1"
    cli.audit_service_command(connected.service, SimpleNamespace(
        audit_service_command="status", audit_id=connected.audit_id))
    args = cli_run(tmp_path, monkeypatch, connected, lambda *a, **k: None, revision="b" * 40)
    with pytest.raises(SystemExit) as exit_info:
        cli.audit_service_command(connected.service, args)
    assert exit_info.value.code == 1


def test_a_duplicate_tick_cannot_double_run_a_bound_task(connected):
    service_runner, bus, executor = runner(connected)
    service_runner._write(current_task={"task_id": "bound-elsewhere", "partition_id": "p",
                                        "correlation_id": "audit:bound", "bound_at": "now"})
    step = service_runner.step()
    assert step == {"action": "stopped", "reason_code": "unresolved_execution"}
    assert executor.calls == [] and service_runner.stopping is True


@pytest.mark.parametrize("status,expected_exit,reason",
                         [("succeeded", 0, "max_tasks_reached"), ("failed", 1, "task_failed")])
def test_the_run_entry_releases_its_lock_and_observer_and_maps_the_exit_code(
        tmp_path, monkeypatch, connected, status, expected_exit, reason):
    from filelock import FileLock

    import codex_harness.bootstrap as bootstrap
    from codex_harness.adapters import configuration

    closed = []
    monkeypatch.setattr(configuration, "runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(audit_service, "current_revision", lambda: REVISION)
    monkeypatch.setattr(bootstrap, "build_observer",
                        lambda *args, **kwargs: SimpleNamespace(close=lambda: closed.append(True)))
    service_runner, _, executor = runner(connected, executor=FixtureExecutor(
        connected.audits, status=status), max_tasks=1)
    monkeypatch.setattr(audit_service, "build_runner",
                        lambda service, args, observer, gate: service_runner)
    args = SimpleNamespace(audit_service_command="run", audit_id=connected.audit_id,
                           max_tasks=1, once=True)
    result = audit_service.execute(connected.service, args)
    assert result["exit_code"] == expected_exit and result["stop_reason"] == reason
    with connected.store.transaction() as tx:
        admitted = tx.get("research_control", "activation")
    # The receipt reports the activation the gate actually read, not the runner's own fields.
    assert result["partitions"] == 4 and result["release_id"] == admitted["release_id"]
    assert result["revision"] == REVISION
    assert len(executor.calls) == 1 and closed == [True]
    lock = FileLock(str(tmp_path / "audit-service.lock"), timeout=0)
    lock.acquire()  # the host lock is free for the next start; it was not leaked
    lock.release()


def test_max_tasks_and_audit_id_bounds_are_refused_before_a_runner_exists(connected):
    for value in (0, 101, "2", True):
        with pytest.raises(audit_service.AuditServiceRefused, match="max_tasks_invalid"):
            audit_service.AuditServiceRunner(connected.service, connected.audit_id, max_tasks=value)
    with pytest.raises(audit_service.AuditServiceRefused, match="audit_id_invalid"):
        audit_service.AuditServiceRunner(connected.service, "  ")

"""Executor, ledger and outbox wiring for the observation contract (U001 L01, L03, L04, L09, L10).

The post-entry rule (review R1): once the provider is entered, every failure up to the durable
checkpoint leaves termination evidence and blocks the task; a refusal before entry stays an
ordinary retry. Codex's counterexamples from docs/zeus/reviews/claude-work-009 are regressions
here, inverted to require the safe result.
"""
import json
import os
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_observations import CANARY, Interceptor

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.contracts import validate_message, validate_observation
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.execution_recovery import ExecutionRecovery
from codex_harness.application.observations import MemoryDirectory, Observer, orphan_report
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization, redis_url
from codex_harness.domain.model import ContractError, envelope
from codex_harness.domain.observation import new_process_run_id

URL = "https://example.org/source"
ANSWER = {"title": "t", "objective": "o", "source_url": URL, "evidence": "e", "acceptance_criteria": []}


class Bus:
    validate = staticmethod(validate_message)

    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.validate(message)
        self.messages.append(deepcopy(message))
        return f"{len(self.messages)}-0"


def build(tmp_path, monkeypatch, store, runtime_error=None, enter_error=None):
    """A worker executing one 'geeknews' research task through a fake transport (no model)."""
    service = Harness(store, organization())
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    starts = []

    class Runtime:
        def __init__(self, **kwargs):
            if enter_error is not None:
                raise enter_error  # a refusal before the provider is entered
        def __enter__(self):
            return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, *args, **kw):
            starts.append(1)  # the external effect: counted at the moment the provider is entered
            if runtime_error is not None:
                raise runtime_error
            for index in range(2):
                kw["on_event"]({"method": "item/completed", "params": {"item": {"id": f"item-{index}", "type": "commandExecution",
                                                                              "status": "completed"}, "completedAtMs": 1_700_000_000_000 + index}})
            kw["on_event"]({"method": "garbage"})
            kw["on_event"]("not-an-event")
            return {"answer": ANSWER, "events": [{"method": "item/completed", "params": {"item": {"id": "item-0", "type": "commandExecution"}}}],
                    "thread_id": "thread", "usage": {"total": {"totalTokens": 321}}, "rotate": False, "interrupted": False}

    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Runtime)
    collection = {"artifact": artifacts.put("collected", "fixture")["ref"], "items": [{"url": URL, "summary": "s"}]}
    observer = Observer(store, MemorySpool(new_process_run_id()), component="test-executor", directory=MemoryDirectory())
    executor = Executor(service, SimpleNamespace(repository=tmp_path, _git=lambda *a, **kw: "deadbeef"), artifacts,
                        research=SimpleNamespace(collect=lambda source: collection), observer=observer)
    message = envelope("task.assign", "lead:research", "worker:geeknews", "research", {"source": "geeknews"}, "corr-fixture")
    task = executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, service=service, observer=observer, task=task, starts=starts, store=store,
                           artifacts=artifacts)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


def spool_events(s, event_type):
    return [r for r in s.observer.spool.records() if r["event_type"] == event_type]


def assert_blocked_without_second_start(s, boundary):
    """The safe result Codex's counterexamples demand: one start, evidence, block, no rerun."""
    assert len(s.starts) == 1
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["status"] == "pending_reconciliation" and pending["boundary"] == boundary
    with s.store.transaction() as tx:
        row = tx.get("tasks", s.task["id"])
        assert row["status"] == "blocked" and row["error"] == "reconciliation_required"
        assert row["status"] != "succeeded"
        assert any(a["event_type"] == "development.reconciliation_required" for a in tx.scan("observation_audit"))
    assert s.executor.execute_one("worker:geeknews") is None, "a blocked task is not claimable"
    assert len(s.starts) == 1, "no blind re-execution while termination evidence is pending"
    return pending


def test_l01_one_execution_is_traceable_end_to_end_and_ack_is_not_completion(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    row = s.executor.execute_one("worker:geeknews")
    assert row["status"] == "succeeded" and len(s.starts) == 1
    bus = Bus()
    s.service.flush_outbox(bus, audit=s.observer.audit_system)
    assert [m["type"] for m in bus.messages] == ["task.result"]
    with store.transaction() as tx:
        audits = {a["event_type"]: a for a in tx.scan("observation_audit")}
    assert set(audits) == {"development.invocation_reserved", "development.invocation_settled", "general.message_published"}
    reserved, settled, published = (audits[k] for k in ("development.invocation_reserved", "development.invocation_settled",
                                                         "general.message_published"))
    for record in (reserved, settled):
        validate_observation({k: record[k] for k in record if k not in {"payload_hash", "authority"}})
        assert record["execution"] == {**record["execution"], "kind": "execution", "task_id": s.task["id"], "generation": 1,
                                       "attempt": 1, "role": "worker:geeknews", "bucket": "tasks", "provider": "codex-app-server"}
        assert record["correlation_id"] == "corr-fixture" and record["causation_id"] == s.task["id"]
    assert reserved["outcome"] == "started" and settled["outcome"] == "succeeded"
    assert settled["attributes"]["total_tokens"] == 321 and settled["attributes"]["invocation_outcome"] == "accepted"
    assert reserved["attributes"]["reservation_id"] == settled["attributes"]["reservation_id"]
    assert published["execution"]["kind"] == "system" and published["attributes"]["stream_entry_id"] == "1-0"
    assert published["correlation_id"] == "corr-fixture" and published["attributes"]["message_type"] == "task.result"
    spool = {r["event_type"]: r for r in s.observer.spool.records()}
    for name in ("development.provider_started", "development.provider_finished", "development.progress_recorded",
                 "development.checkpoint_recorded", "development.task_completed"):
        assert spool[name]["execution"]["task_id"] == s.task["id"] and spool[name]["correlation_id"] == "corr-fixture"
    assert spool["development.provider_finished"]["outcome"] == "succeeded"
    progress = spool_events(s, "development.progress_recorded")
    # Two well-formed items, one unknown-but-well-formed method (not a progress event), one malformed string.
    assert [p["attributes"]["malformed"] for p in progress] == [False, False, True]
    assert progress[0]["occurred_at"] == "2023-11-14T22:13:20+00:00" and progress[2]["occurred_at"] is None
    numbers = [r["sequence"]["number"] for r in s.observer.spool.records()]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)
    # A transport acknowledgement and a task completion are two different facts with different identities.
    assert published["event_type"] != spool["development.task_completed"]["event_type"]
    assert spool["development.task_completed"]["attributes"]["status"] == "succeeded"
    # Intent (reservation audit) precedes the actual start (provider_started emitted at run entry).
    order = [r["event_type"] for r in s.observer.spool.records()]
    assert order.index("development.invocation_reserved") < order.index("development.provider_started")


def test_l03_audit_write_failure_starts_no_provider_and_leaves_no_success(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, body: bucket == "observation_audit" and body.get("event_type") == "development.invocation_reserved"
    row = s.executor.execute_one("worker:geeknews")
    assert len(s.starts) == 0, "the provider must not start without its audit record"
    assert row["status"] == "retry" and row["attempt_outcomes"][-1]["status"] == "failed"
    assert s.observer.pending_terminations(s.task["id"]) == [], "a refusal before entry needs no termination record"
    with store.transaction() as tx:
        assert not tx.scan("observation_audit") and not tx.scan("invocation_reservations")
        assert tx.get("tasks", s.task["id"])["status"] != "succeeded"
    failed = spool_events(s, "development.task_failed")
    assert failed and failed[0]["attributes"]["error_type"] == "OSError"
    # Observation surfaces carry the error type only; the task row's own error text is the
    # existing workflow failure record and is not an observation surface.
    leaked = CANARY in json.dumps(s.observer.spool.records()) or CANARY in json.dumps(s.observer.health())
    assert not leaked


def test_refusal_before_entry_is_an_ordinary_retry(tmp_path, monkeypatch, store):
    """The distinction R1 asks for: a provider that provably never started may run next time."""
    s = build(tmp_path, monkeypatch, store, enter_error=OSError("codex unavailable " + CANARY))
    first = s.executor.execute_one("worker:geeknews")
    assert first["status"] == "retry" and len(s.starts) == 0
    assert s.observer.pending_terminations(s.task["id"]) == []
    failed = spool_events(s, "development.provider_failed")
    assert failed and failed[0]["attributes"]["provider_entered"] is False
    with store.transaction() as tx:
        [reservation] = tx.scan("invocation_reservations")
        assert reservation["status"] == "unsettled_unknown"


def test_l04_settlement_write_failure_keeps_termination_evidence_and_refuses_blind_rerun(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, body: bucket == "observation_audit" and body.get("event_type") == "development.invocation_settled"
    first = s.executor.execute_one("worker:geeknews")
    assert first["status"] == "blocked" and first["attempt_outcomes"][-1]["error"].startswith("PostExecutionRecordFailure")
    intercepted.fail_put = None
    pending = assert_blocked_without_second_start(s, "settlement")
    assert pending["invocation_outcome"] == "accepted" and pending["error_type"] == "OSError"
    assert CANARY not in json.dumps(pending)
    with store.transaction() as tx:
        assert tx.get("observation_terminations", pending["record_id"])["status"] == "pending_reconciliation"
        [reservation] = tx.scan("invocation_reservations")
        assert reservation["status"] == "reserved", "the settlement rolled back with its audit"
        assert [r["reason"] for r in orphan_report(tx)["orphan"]] == ["execution_blocked"]
        assert any(e["type"] == "execution.reconciliation_required" for e in tx.scan("events"))
        notices = [r["message"] for r in tx.scan("outbox") if r["message"]["type"] == "execution.notice"]
    # Design decision 2: the block travels on the existing execution.notice path to the lead.
    [notice] = [m for m in notices if m["what"]["details"]["reason_code"] == "reconciliation_required"]
    validate_message(notice)
    assert notice["who"]["recipient"] == "lead:research" and notice["what"]["action"] == "observe_execution"
    handled = s.executor.workflow.handle(notice)
    assert handled["authority"] == "informational_only" and s.executor.workflow.handle(notice) == handled
    misrouted = deepcopy(notice)
    misrouted["who"]["recipient"] = "conductor"
    with pytest.raises(ContractError, match="reporting edge"):
        s.executor.workflow.handle(misrouted)
    # Reconcile (discard): the block lifts, the task stays blocked until the recovery path re-queues it.
    resolved = s.observer.resolve_termination(pending["record_id"], resolution="discard", operator="unit-operator",
                                              reason="explicit test decision")
    assert resolved["resolution"]["resolution"] == "discard" and not s.observer.pending_terminations(s.task["id"])
    assert s.executor.execute_one("worker:geeknews") is None and len(s.starts) == 1
    with store.transaction() as tx:
        assert tx.get("observation_terminations", pending["record_id"])["status"] == "resolved"
        assert any(a["event_type"] == "development.reconciliation_resolved" for a in tx.scan("observation_audit"))


def repair(s):
    recovery = ExecutionRecovery(s.store, s.service.org, s.artifacts)
    evidence = s.artifacts.put("operator reviewed the termination record", "test-evidence")["ref"]
    packet = recovery.prepare("tasks", s.task["id"], operation="repair", max_attempts=3, deadline=None,
                              reason="reconciled", evidence_refs=[evidence], operator="unit-operator")
    return recovery.apply(packet)


def test_repair_is_refused_until_reconciled_and_then_reruns_once(tmp_path, monkeypatch, store):
    """`rerun` lifts the observation block; re-queuing is the existing execution-recovery repair path."""
    s = build(tmp_path, monkeypatch, store, runtime_error=OSError("lost transport after start"))
    assert s.executor.execute_one("worker:geeknews")["status"] == "blocked"
    pending = assert_blocked_without_second_start(s, "transport")
    with pytest.raises(ContractError, match="still pending reconciliation"):
        repair(s)
    s.observer.resolve_termination(pending["record_id"], resolution="rerun", operator="unit-operator", reason="checked")
    assert repair(s)["execution"]["status"] == "retry"
    # The transport works now (a fresh fake without the error, same store and same termination
    # records); the operator-authorized second run is the only second start.
    s2 = build(tmp_path / "second", monkeypatch, store)
    s2.executor.observer = s.observer
    result = s2.executor.execute_one("worker:geeknews")
    assert result is not None and result["status"] == "succeeded" and result["attempt"] == 2
    assert len(s.starts) == 1 and len(s2.starts) == 1


@pytest.mark.parametrize("failure", ["transport", "result_persistence", "checkpoint"])
def test_post_entry_failures_all_leave_evidence_and_block(tmp_path, monkeypatch, store, failure):
    """Codex counterexamples 3 and 4 inverted: transport loss and artifact failure never allow a second start."""
    runtime_error = OSError("lost transport after start " + CANARY) if failure == "transport" else None
    s = build(tmp_path, monkeypatch, store, runtime_error=runtime_error)
    if failure == "result_persistence":
        def fail(*args, **kwargs):
            raise OSError("result artifact write failed " + CANARY)
        monkeypatch.setattr("codex_harness.adapters.executor.persist_result", fail)
    if failure == "checkpoint":
        def fail_checkpoint(*args, **kwargs):
            raise OSError("checkpoint write failed " + CANARY)
        monkeypatch.setattr(s.service, "checkpoint", fail_checkpoint)
    first = s.executor.execute_one("worker:geeknews")
    assert first["status"] == "blocked"
    pending = assert_blocked_without_second_start(s, failure)
    expected = "unknown" if failure == "transport" else "accepted"
    assert pending["invocation_outcome"] == expected
    with store.transaction() as tx:
        audits = {a["event_type"] for a in tx.scan("observation_audit")}
        if failure == "transport":
            assert "development.invocation_abandoned" in audits
        else:
            assert "development.invocation_settled" in audits, "the settlement itself was recorded"
    leaked = CANARY in json.dumps(s.observer.spool.records()) or CANARY in json.dumps(pending)
    assert not leaked


def test_default_executor_observer_still_audits_into_the_store(tmp_path, monkeypatch):
    store = MemoryStore()
    service = Harness(store, organization())
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, *args, **kw):
            return {"answer": ANSWER, "events": [], "thread_id": "t", "usage": None, "rotate": False, "interrupted": False}

    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Runtime)
    collection = {"artifact": artifacts.put("collected", "fixture")["ref"], "items": [{"url": URL, "summary": "s"}]}
    executor = Executor(service, SimpleNamespace(repository=tmp_path, _git=lambda *a, **kw: "rev"), artifacts,
                        research=SimpleNamespace(collect=lambda source: collection))
    executor.workflow.submit(envelope("task.assign", "lead:research", "worker:geeknews", "research", {"source": "geeknews"}, "c"))
    assert executor.execute_one("worker:geeknews")["status"] == "succeeded"
    with store.transaction() as tx:
        assert {a["event_type"] for a in tx.scan("observation_audit")} == {"development.invocation_reserved",
                                                                            "development.invocation_settled"}


def test_l10_observation_record_cannot_be_submitted_or_relayed_as_work(tmp_path, monkeypatch):
    s = build(tmp_path, monkeypatch, MemoryStore())
    event = s.observer.emit("general.process_started", "started", attributes={"mode": "unit"})
    with s.store.transaction() as tx:
        tx.put("outbox", "forged", {"message": event, "sent": False})
    bus = Bus()
    result = s.service.flush_outbox(bus, audit=s.observer.audit_system)
    assert result["quarantined"] == 1 and bus.messages == []
    with s.store.transaction() as tx:
        [quarantine] = tx.scan("outbox_quarantine")
        assert quarantine["reason"] == "SchemaInvalid"
        audits = [a for a in tx.scan("observation_audit") if a["event_type"] == "general.message_quarantined"]
        assert audits and audits[0]["outcome"] == "blocked" and audits[0]["attributes"]["reason"] == "SchemaInvalid"


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("HARNESS_INTEGRATION") != "1", reason="Set HARNESS_INTEGRATION=1 for local services")
def test_l01_real_redis_publish_records_the_actual_stream_entry(tmp_path, monkeypatch, isolated_pgstore):
    s = build(tmp_path, monkeypatch, isolated_pgstore)
    assert s.executor.execute_one("worker:geeknews")["status"] == "succeeded"
    bus = RedisBus(redis_url(), namespace="zeus-observation-test-" + new_process_run_id())
    try:
        result = s.service.flush_outbox(bus, audit=s.observer.audit_system)
        assert result["published"] == 1
        with isolated_pgstore.transaction() as tx:
            [published] = [a for a in tx.scan("observation_audit") if a["event_type"] == "general.message_published"]
        entry = published["attributes"]["stream_entry_id"]
        stream = bus.stream("lead:research")
        assert bus.client.xrange(stream, entry, entry), "the audited entry id is a real stream entry"
    finally:
        bus.client.delete(bus.stream("lead:research"))

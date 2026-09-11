"""Executor, ledger and outbox wiring for the observation contract (U001 L01, L03, L04, L09, L10)."""
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
from codex_harness.application.observations import MemoryDirectory, Observer, orphan_report
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization, redis_url
from codex_harness.domain.model import envelope
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


def build(tmp_path, monkeypatch, store, runtime_error=None):
    """A worker executing one 'geeknews' research task through a fake transport (no model)."""
    service = Harness(store, organization())
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    starts = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self):
            starts.append(1)
            return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, *args, **kw):
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
    return SimpleNamespace(executor=executor, service=service, observer=observer, task=task, starts=starts, store=store)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


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
        validate_observation(record | {} if False else {k: record[k] for k in record if k not in {"payload_hash", "authority"}})
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
    progress = [r for r in s.observer.spool.records() if r["event_type"] == "development.progress_recorded"]
    # Two well-formed items, one unknown-but-well-formed method (not a progress event), one malformed string.
    assert [p["attributes"]["malformed"] for p in progress] == [False, False, True]
    assert progress[0]["occurred_at"] == "2023-11-14T22:13:20+00:00" and progress[2]["occurred_at"] is None
    numbers = [r["sequence"]["number"] for r in s.observer.spool.records()]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)
    # A transport acknowledgement and a task completion are two different facts with different identities.
    assert published["event_type"] != spool["development.task_completed"]["event_type"]
    assert spool["development.task_completed"]["attributes"]["status"] == "succeeded"


def test_l03_audit_write_failure_starts_no_provider_and_leaves_no_success(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, body: bucket == "observation_audit" and body.get("event_type") == "development.invocation_reserved"
    row = s.executor.execute_one("worker:geeknews")
    assert len(s.starts) == 0, "the provider must not start without its audit record"
    assert row["status"] == "retry" and row["attempt_outcomes"][-1]["status"] == "failed"
    with store.transaction() as tx:
        assert not tx.scan("observation_audit") and not tx.scan("invocation_reservations")
        assert tx.get("tasks", s.task["id"])["status"] != "succeeded"
    failed = [r for r in s.observer.spool.records() if r["event_type"] == "development.task_failed"]
    assert failed and failed[0]["attributes"]["error_type"] == "OSError"
    # Observation surfaces carry the error type only; the task row's own error text is the
    # existing workflow failure record and is not an observation surface.
    leaked = CANARY in json.dumps(s.observer.spool.records()) or CANARY in json.dumps(s.observer.health())
    assert not leaked


def test_l04_settlement_write_failure_keeps_termination_evidence_and_refuses_blind_rerun(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, body: bucket == "observation_audit" and body.get("event_type") == "development.invocation_settled"
    first = s.executor.execute_one("worker:geeknews")
    assert len(s.starts) == 1 and first["status"] == "retry"
    assert first["error"].startswith("PostExecutionRecordFailure")
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["status"] == "pending_reconciliation" and pending["invocation_outcome"] == "accepted"
    assert pending["error_type"] == "OSError" and CANARY not in json.dumps(pending)
    with store.transaction() as tx:
        assert tx.get("observation_terminations", pending["record_id"])["status"] == "pending_reconciliation"
        [reservation] = tx.scan("invocation_reservations")
        assert reservation["status"] == "reserved", "the settlement rolled back with its audit"
        assert [r["reason"] for r in orphan_report(tx)["orphan"]] == ["execution_retry"]
    intercepted.fail_put = None
    second = s.executor.execute_one("worker:geeknews")
    assert len(s.starts) == 1, "no blind re-execution while termination evidence is pending"
    assert second["status"] == "blocked" and second["error"] == "reconciliation_required"
    with store.transaction() as tx:
        audits = {a["event_type"] for a in tx.scan("observation_audit")}
        assert "development.reconciliation_required" in audits
        assert any(e["type"] == "execution.reconciliation_required" for e in tx.scan("events"))
        assert tx.get("tasks", s.task["id"])["status"] == "blocked"
    assert s.executor.execute_one("worker:geeknews") is None and len(s.starts) == 1
    resolved = s.observer.resolve_termination(pending["record_id"], resolution="discard", operator="unit-operator",
                                              reason="explicit test decision")
    assert resolved["resolution"]["resolution"] == "discard" and not s.observer.pending_terminations(s.task["id"])
    with store.transaction() as tx:
        assert tx.get("observation_terminations", pending["record_id"])["status"] == "resolved"
        assert any(a["event_type"] == "development.reconciliation_resolved" for a in tx.scan("observation_audit"))


def test_provider_exception_abandons_reservation_with_audit(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, runtime_error=OSError("runtime unavailable " + CANARY))
    row = s.executor.execute_one("worker:geeknews")
    assert row["status"] == "retry"
    with store.transaction() as tx:
        audits = {a["event_type"]: a for a in tx.scan("observation_audit")}
        assert audits["development.invocation_abandoned"]["outcome"] == "aborted"
        assert audits["development.invocation_abandoned"]["reason_code"] == "OSError"
        [reservation] = tx.scan("invocation_reservations")
        assert reservation["status"] == "unsettled_unknown"
    failed = [r for r in s.observer.spool.records() if r["event_type"] == "development.provider_failed"]
    assert failed and failed[0]["outcome"] == "failed"
    leaked = CANARY in json.dumps(s.observer.spool.records()) or CANARY in json.dumps(audits, default=str)
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
        assert not tx.scan("tasks") or all(t["status"] != "succeeded" or t["id"] == s.task["id"] for t in tx.scan("tasks"))


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

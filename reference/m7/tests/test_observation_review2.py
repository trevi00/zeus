"""Regressions for PR #71 second review (docs/zeus/reviews/claude-work-010/test_boundaries.py).

Each of Codex's six counterexamples reproduced an unsafe result; here the same scenarios require
the safe one. MemoryStore, actual temporary files, fake provider, deterministic fault injection;
not operational evidence.
"""
import json
import time

import pytest
from test_observation_wiring import build
from test_observations import CANARY, Interceptor, file_observer

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector, Observer
from codex_harness.cli import emit
from codex_harness.domain.observation import new_process_run_id


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


# ---- R1 residual: the unconfirmed marker outlives every later boundary -------------------------

def test_completion_commit_failure_blocks_instead_of_restarting_the_provider(tmp_path, monkeypatch, store):
    """Counterexample A inverted: the succeeded write failed, so the attempt stays unconfirmed."""
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, row: bucket == "tasks" and row.get("status") == "succeeded"
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked" and result["error"] == "reconciliation_required" and len(s.starts) == 1
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["status"] == "pending_reconciliation" and pending["boundary"] == "acceptance"
    intercepted.fail_put = None
    assert s.executor.execute_one("worker:geeknews") is None and len(s.starts) == 1
    with store.transaction() as tx:
        assert tx.get("tasks", s.task["id"])["status"] == "blocked"
        reasons = sorted(r["message"]["what"]["details"]["reason_code"] for r in tx.scan("outbox")
                         if r["message"]["type"] == "execution.notice")
        assert reasons == ["execution_failed", "reconciliation_required"]


def test_termination_file_failure_still_blocks_through_the_sink_marker(tmp_path, monkeypatch, store):
    """Counterexample B inverted: the safeguard's own file write fails; the reserved marker holds."""
    s = build(tmp_path, monkeypatch, store, runtime_error=OSError("transport after effect"))

    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(s.observer.directory, "record_termination", disk_full)
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked" and len(s.starts) == 1
    assert s.observer.counters["termination_file_failures"] == 1
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["status"] == "pending_reconciliation" and pending["boundary"] == "transport"
    assert s.executor.execute_one("worker:geeknews") is None and len(s.starts) == 1


def test_sink_and_file_both_failing_after_entry_cannot_yield_a_plain_retry(tmp_path, monkeypatch, store):
    """Both stores down after the provider ran: the marker written at reservation still blocks later."""
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted, runtime_error=OSError("transport after effect"))

    def disk_full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(s.observer.directory, "record_termination", disk_full)
    started = len(s.starts)

    class Runtime:  # the transport raises, then the sink goes away before anything can be recorded
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, *args, **kwargs):
            s.starts.append(1)
            intercepted.fail_transaction = OSError("sink down after the provider ran")
            raise OSError("transport after effect")

    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", Runtime)
    with pytest.raises(Exception):
        s.executor.execute_one("worker:geeknews")  # nothing could be recorded; the failure surfaces
    assert len(s.starts) == started + 1
    intercepted.fail_transaction = None
    # The task is still 'running' from the lease's point of view; once the lease lapses a new claim
    # finds the reserved marker and blocks instead of running the provider again.
    with store.transaction() as tx:
        row = tx.get("tasks", s.task["id"])
        row["lease_until"] = "2000-01-01T00:00:00+00:00"
        tx.put("tasks", s.task["id"], row)
    second = s.executor.execute_one("worker:geeknews")
    assert second is not None and second["status"] == "blocked" and len(s.starts) == started + 1


def test_pre_entry_refusal_closes_the_marker_and_retries(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, enter_error=OSError("codex unavailable"))
    assert s.executor.execute_one("worker:geeknews")["status"] == "retry"
    with store.transaction() as tx:
        [marker] = tx.scan("observation_terminations")
        assert marker["status"] == "closed" and marker["closure"] == "not_entered"
    assert s.observer.pending_terminations(s.task["id"]) == []


def test_observed_answer_rejection_closes_the_marker_and_retries(tmp_path, monkeypatch, store):
    """A contract rejection of an already persisted answer is an observed outcome, not an unknown one."""
    s = build(tmp_path, monkeypatch, store)
    original = s.executor.workflow.complete

    def reject(*args, **kwargs):
        from codex_harness.domain.model import ContractError
        raise ContractError("Unfetched research citation")

    monkeypatch.setattr(s.executor.workflow, "complete", reject)
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "retry" and len(s.starts) == 1
    with store.transaction() as tx:
        [marker] = tx.scan("observation_terminations")
        assert marker["status"] == "closed" and marker["closure"] == "observed_failure"
    monkeypatch.setattr(s.executor.workflow, "complete", original)
    assert s.executor.execute_one("worker:geeknews")["status"] == "succeeded" and len(s.starts) == 2


# ---- design decision 3 residual: live origins keep their new debt --------------------------------

def test_live_origin_new_alert_survives_a_stale_inheritor(tmp_path, store):
    """Counterexample inverted: B replays A's snapshot; A's newer alert stays pending and is replayed by C."""
    intercepted = Interceptor(store)
    first = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    intercepted.fail_transaction = OSError("sink unavailable")
    first.alert("spool_saturated", "old", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    second = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    inherited = {r["event_id"] for rows in second.inherited_pending.values() for r in rows}
    first.alert("spool_append_failed", "new", attributes={"error_type": "E", "dropped": 1})
    new_ids = {r["event_id"] for r in first.pending_alerts} - inherited
    assert new_ids
    intercepted.fail_transaction = None
    second.alert("spool_append_failed", "recovered", attributes={"error_type": "E", "dropped": 1})
    with store.transaction() as tx:
        committed = {r["event_id"] for r in tx.scan("observation_alerts")}
    assert inherited <= committed and new_ids.isdisjoint(committed)
    directory = SpoolDirectory(tmp_path / "obs")
    assert {r["event_id"] for r in directory.read_pending_alerts()[first.process_run_id]} == new_ids
    first.close()
    third = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    assert {r["event_id"] for rows in third.inherited_pending.values() for r in rows} == new_ids
    Collector(intercepted, directory, validate=validate_observation, observer=third).collect()
    with store.transaction() as tx:
        committed = {r["event_id"] for r in tx.scan("observation_alerts")}
    assert new_ids <= committed and directory.read_pending_alerts() == {}
    second.close()
    third.close()


def test_two_inheritors_and_a_lost_commit_response_never_lose_or_double_count(tmp_path, store):
    intercepted = Interceptor(store)
    origin = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    intercepted.fail_transaction = OSError("sink unavailable")
    origin.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    debt = {r["event_id"] for r in origin.pending_alerts}
    origin.close()
    b = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    c = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    assert {r["event_id"] for rows in b.inherited_pending.values() for r in rows} == debt
    assert {r["event_id"] for rows in c.inherited_pending.values() for r in rows} == debt
    intercepted.fail_transaction = None
    # B's commit succeeds but its acknowledgement write fails: B keeps the debt, nothing is lost.
    original_ack = b.directory.acknowledge_pending_alerts
    b.directory.acknowledge_pending_alerts = lambda *a, **k: (_ for _ in ()).throw(OSError("ack lost"))
    b.alert("spool_append_failed", "b", attributes={"error_type": "E", "dropped": 1})
    assert b.counters["pending_ack_failures"] == 1 and b.inherited_pending
    b.directory.acknowledge_pending_alerts = original_ack
    c.alert("spool_append_failed", "c", attributes={"error_type": "E", "dropped": 1})  # C replays the same debt
    assert not c.inherited_pending
    b.alert("spool_append_failed", "b2", attributes={"error_type": "E", "dropped": 1})
    assert not b.inherited_pending
    with store.transaction() as tx:
        rows = [a for a in tx.scan("observation_alerts") if a["event_id"] in debt]
    assert len(rows) == len(debt) and all(r["notification"]["status"] == "recorded_after_recovery" for r in rows)
    assert SpoolDirectory(tmp_path / "obs").read_pending_alerts() == {}


# ---- R3 residual: segment index contract and directory retention ----------------------------------

def test_segment_10000_is_collected_in_order(tmp_path, store):
    """Counterexample inverted: index 9999 -> 10000 stays visible, ordered and reclaimable."""
    root = tmp_path / "obs"
    spool = FileSpool(root, new_process_run_id(), max_bytes=100000, segment_bytes=600, fsync=False)
    spool.segment = 9999
    o = Observer(store, spool, component="review", directory=SpoolDirectory(root))
    for index in range(12):  # enough to rotate past 9999 at least once
        assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index}) is not None
    assert spool.segment >= 10000 and spool.path.is_file()
    names = [path.name for path in o.directory.spool_files()]
    assert any(".9999." in name for name in names) and any(".10000." in name for name in names)
    assert names.index(next(n for n in names if ".9999." in n)) < names.index(next(n for n in names if ".10000." in n))
    collector = Collector(store, o.directory, validate=validate_observation)
    result = collector.collect()
    assert result["inserted"] == 12 and result["reclaimed_segments"] >= 1
    with store.transaction() as tx:
        assert sorted(r["attributes"]["idle_seconds"] for r in tx.scan("observations")) == list(range(12))
    o.close()
    assert collector.collect()["reclaimed_segments"] >= 1


def test_finished_run_leftovers_are_pruned_and_a_final_truncated_tail_is_quarantined(tmp_path, store):
    root = tmp_path / "obs"
    o = file_observer(tmp_path, store)
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    with o.spool.path.open("ab") as stream:
        stream.write(b"deadbeef" * 8 + b" event {\"half\": tr")  # the writer died mid-record
    o.close()  # the closed marker makes the tail final
    directory = SpoolDirectory(root)
    collector = Collector(store, directory, validate=validate_observation)
    result = collector.collect()
    assert result["inserted"] == 1 and result["corrupt"] == 1 and result["truncated_tail"] == 0
    assert directory.spool_files() == [], "the finished run's only segment was reclaimed after the tail was finalized"
    assert not directory.closed(o.process_run_id) and directory.read_health() == []
    with store.transaction() as tx:
        [quarantined] = tx.scan("observation_quarantine")
    assert quarantined["defect"] == "truncated tail of a finished run"


def test_dead_run_without_marker_is_finalized_after_retention(tmp_path, store):
    root = tmp_path / "obs"
    o = file_observer(tmp_path, store)
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    # A crash: the descriptor and the run lock are gone with the process, but no closed marker was written.
    import os
    os.close(o.spool._descriptor)
    o.spool._descriptor = None
    o.spool._lock.release()
    o.spool._lock = None
    directory = SpoolDirectory(root)
    assert not directory.run_finished(o.process_run_id, now=time.time(), retention_seconds=3600)
    assert directory.run_finished(o.process_run_id, now=time.time() + 7200, retention_seconds=3600)
    # The released lock proves the writer is gone, so the acknowledged last segment is reclaimed
    # already during collection; retention only governs the remaining leftovers.
    assert Collector(store, directory, validate=validate_observation).collect()["reclaimed_segments"] == 1
    directory.prune(now=time.time() + 7200, retention_seconds=3600)
    assert directory.spool_files() == [] and directory.known_runs() == set()


# ---- R4 residual: credential shapes in identifiers and the failure text path --------------------

def test_known_token_shape_is_refused_as_identifier(tmp_path, store):
    """Counterexample inverted: a credential-shaped correlation id or evidence ref is refused."""
    o = file_observer(tmp_path, store)
    token = "ghp_" + "A" * 30  # synthetic, recognized by the redactor
    assert o.emit("general.process_idle_exit", "observed", correlation_id=token, attributes={"idle_seconds": 1}) is None
    assert o.emit("general.process_idle_exit", "observed", evidence_refs=[token], attributes={"idle_seconds": 1}) is None
    assert o.counters["refused"] == 2
    Collector(store, o.directory, validate=validate_observation).collect()
    surfaces = [path.read_text("utf-8", "replace") for path in o.directory.spool_files()]
    with store.transaction() as tx:
        surfaces.append(json.dumps(tx.scan("observations")))
    assert all(token not in surface for surface in surfaces)


def test_settlement_error_cause_never_reaches_execute_one_result_or_cli(tmp_path, monkeypatch, store, capsys):
    """Counterexample inverted: the CLI stdout, the task row and the sink carry type, digest and boundary only."""
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, row: bucket == "observation_audit" and row.get("event_type") == "development.invocation_settled"
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked"
    emit(result)
    out = capsys.readouterr().out
    text = json.dumps(result, default=str)
    leaked = CANARY in text or CANARY in out
    assert not leaked
    assert "settlement failed after provider entry (OSError: message_sha256=" in result["attempt_outcomes"][-1]["error"]
    intercepted.fail_put = None
    with store.transaction() as tx:
        rows = [r for r in tx.records() if r["bucket"] in {"tasks", "decisions_pending"} or r["bucket"].startswith("observation")]
    assert CANARY not in json.dumps(rows, default=str)
    assert CANARY not in json.dumps(s.observer.spool.records())

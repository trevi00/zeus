"""Regressions for PR #71 review findings R2, R3, R4 and design decision 3 (pending alert durability).

Each of Codex's counterexamples (docs/zeus/reviews/claude-work-009/test_review_boundaries.py)
reproduced an unsafe result; here the same scenarios require the safe one. MemoryStore, real
temporary spool files and deterministic fault injection; not operational evidence.
"""
import json

import pytest
from test_observations import CANARY, Interceptor, file_observer

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector, Observer, status_report
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


def termination_fixture(o, task="review-task"):
    o.role = o.role or "worker:geeknews"
    lease = {"id": task, "_bucket": "tasks", "generation": 1, "attempt": 1}
    return o.record_termination(lease, reservation_id=None, classification="unknown", stream_hash=None,
                                error=OSError("lost settlement " + CANARY), boundary="settlement")


# ---- R2: reconciliation protocol ---------------------------------------------------------------

def test_failed_reconcile_keeps_the_pending_marker(tmp_path, store):
    """Counterexample inverted: a sink failure during reconcile leaves the block in place."""
    intercepted = Interceptor(store)
    o = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    intercepted.fail_transaction = OSError("sink unavailable")
    record_id = termination_fixture(o)
    assert [row["record_id"] for row in o.pending_terminations("review-task")] == [record_id]
    with pytest.raises(OSError):
        o.resolve_termination(record_id, resolution="rerun", operator="review", reason="test")
    intercepted.fail_transaction = None
    assert [row["record_id"] for row in o.pending_terminations("review-task")] == [record_id]
    with store.transaction() as tx:
        assert tx.get("observation_terminations", record_id) is None and not tx.scan("observation_audit")
    resolved = o.resolve_termination(record_id, resolution="rerun", operator="review", reason="test")
    assert resolved["status"] == "resolved" and o.pending_terminations("review-task") == []
    with store.transaction() as tx:
        assert tx.get("observation_terminations", record_id)["status"] == "resolved"
        assert any(a["event_type"] == "development.reconciliation_resolved" for a in tx.scan("observation_audit"))


def test_reconcile_survives_lost_commit_response_and_local_finalize_failure(tmp_path, store):
    """Commit happened but the response was lost / the local finalize died: the same command finishes it."""
    intercepted = Interceptor(store)
    o = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    record_id = termination_fixture(o)
    original = o.directory.resolve_termination
    calls = []

    def finalize_dies_once(record_id, resolution):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("process killed after commit")
        return original(record_id, resolution)

    o.directory.resolve_termination = finalize_dies_once
    with pytest.raises(OSError):
        o.resolve_termination(record_id, resolution="discard", operator="review", reason="test")
    with store.transaction() as tx:
        assert tx.get("observation_terminations", record_id)["status"] == "resolved", "the sink commit stands"
    # The local pending file still exists; a stale reader would still block, which is the safe side.
    assert o.directory.pending_terminations("review-task")
    again = o.resolve_termination(record_id, resolution="discard", operator="review", reason="test")
    assert again["status"] == "resolved" and o.counters["reconciliation_redelivered"] == 1
    assert o.pending_terminations("review-task") == []
    with pytest.raises(ContractError, match="different decision"):
        o.resolve_termination(record_id, resolution="rerun", operator="review", reason="test")
    with store.transaction() as tx:
        audits = [a for a in tx.scan("observation_audit") if a["event_type"] == "development.reconciliation_resolved"]
        assert len(audits) == 1


def test_sink_resolved_record_is_finalized_late_by_pending_check(tmp_path, store):
    """Another process reconciled through the sink; the local copy is finalized on the next check."""
    o = file_observer(tmp_path, store)
    record_id = termination_fixture(o)
    with store.transaction() as tx:
        row = tx.get("observation_terminations", record_id)
        tx.put("observation_terminations", record_id, {**row, "status": "resolved",
               "resolution": {"resolution": "discard", "operator": "other", "reason": {"text": "x"}}})
    assert o.pending_terminations("review-task") == []
    assert o.directory.pending_terminations("review-task") == [] and o.counters["terminations_finalized_late"] == 1


def test_unreadable_termination_file_blocks_and_is_reported(tmp_path, store):
    o = file_observer(tmp_path, store)
    (tmp_path / "obs" / "terminations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "obs" / "terminations" / "half-written.json").write_bytes(b'{"record_id": "half')
    [row] = o.pending_terminations("any-task")
    assert row["unreadable"] is True and row["status"] == "pending_reconciliation"
    with pytest.raises(ContractError, match="Unknown or unreadable"):
        o.resolve_termination("half-written", resolution="discard", operator="op", reason="r")


# ---- R3: spool space is reclaimed --------------------------------------------------------------

def test_continuous_production_and_collection_never_saturates(tmp_path, store):
    """Counterexample inverted: with a collector keeping up, a small cap never drops events."""
    root = tmp_path / "obs"
    spool = FileSpool(root, new_process_run_id(), max_bytes=6000, segment_bytes=1500, fsync=False)
    o = Observer(store, spool, component="unit", directory=SpoolDirectory(root), alert_window_seconds=0)
    collector = Collector(store, o.directory, validate=validate_observation, observer=o)
    reclaimed = 0
    for index in range(200):
        assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index}) is not None
        if index % 5 == 4:
            reclaimed += collector.collect()["reclaimed_segments"]
    assert o.counters["dropped_spool_full"] == 0 and spool.rotations >= 10 and reclaimed >= 5
    assert o.directory.unacknowledged_bytes() < 6000
    assert len(o.directory.spool_files()) <= 3, "acknowledged, rotated segments are gone"
    collector.collect()
    with store.transaction() as tx:
        seen = sorted(r["attributes"]["idle_seconds"] for r in tx.scan("observations")
                      if r["event_type"] == "general.process_idle_exit")
    assert seen == list(range(200))
    o.close()
    assert collector.collect()["reclaimed_segments"] >= 1, "the closed run's last segment is reclaimed too"


def test_sink_outage_bounds_the_spool_and_recovery_resumes_without_loss_or_duplicates(tmp_path, store):
    root = tmp_path / "obs"
    intercepted = Interceptor(store)
    spool = FileSpool(root, new_process_run_id(), max_bytes=4000, segment_bytes=1000, fsync=False)
    o = Observer(intercepted, spool, component="unit", directory=SpoolDirectory(root), alert_window_seconds=0)
    collector = Collector(intercepted, o.directory, validate=validate_observation, observer=o)
    for index in range(10):
        o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
        collector.collect()
    assert o.counters["dropped_spool_full"] == 0
    intercepted.fail_transaction = OSError("sink down")
    for index in range(10, 60):
        o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
        collector.collect()
    dropped = o.counters["dropped_spool_full"]
    assert dropped > 0 and o.directory.unacknowledged_bytes() <= 4000, "bounded, and the drop is counted"
    assert o.sink_state == "unavailable" and o.pending_alerts
    intercepted.fail_transaction = None
    (root / "spool" / (spool.process_run_id + ".0000.ack")).unlink(missing_ok=True)  # a lost acknowledgement
    for _ in range(20):  # drain; every pass that consumed records spools one collection_completed event
        if collector.collect()["records"] <= 1:
            break
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 999})
    assert o.counters["dropped_spool_full"] == dropped, "recording resumed once space was reclaimed"
    collector.collect()
    with store.transaction() as tx:
        rows = [r for r in tx.scan("observations") if r["event_type"] == "general.process_idle_exit"]
        numbers = sorted(r["attributes"]["idle_seconds"] for r in rows)
    assert len(numbers) == len(set(numbers)) and numbers[:10] == list(range(10)) and 999 in numbers
    assert not o.pending_alerts and o.sink_state == "available"


# ---- design decision 3: pending alerts survive restart and commit failure -----------------------

def test_pending_alerts_survive_restart_and_replay_after_the_next_commit(tmp_path, store):
    intercepted = Interceptor(store)
    first = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    intercepted.fail_transaction = OSError("sink down")
    first.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    assert len(first.pending_alerts) == 2  # explicit + the observer's own sink_unavailable
    first.close()
    directory = SpoolDirectory(tmp_path / "obs")
    assert sum(len(rows) for rows in directory.read_pending_alerts().values()) == 2
    second = file_observer(tmp_path, intercepted, alert_window_seconds=0)  # a restart: new run, old debt
    assert second.counters["alerts_inherited"] == 2
    intercepted.fail_transaction = None
    intercepted.fail_put = lambda bucket, body: bucket == "observation_alerts"  # the commit fails once more
    second.alert("spool_append_failed", "x", attributes={"error_type": "E", "dropped": 1})
    assert second.inherited_pending and sum(len(rows) for rows in directory.read_pending_alerts().values()) >= 2
    intercepted.fail_put = None
    second.alert("spool_append_failed", "y", attributes={"error_type": "E", "dropped": 1})
    assert not second.pending_alerts and not second.inherited_pending
    assert directory.read_pending_alerts() == {}
    with store.transaction() as tx:
        alerts = tx.scan("observation_alerts")
    statuses = sorted(a["notification"]["status"] for a in alerts)
    assert statuses.count("recorded_after_recovery") >= 3 and "recorded" in statuses
    replayed = [a for a in alerts if a["notification"]["status"] == "recorded_after_recovery"]
    assert all(a["notification"]["replayed_by"] == second.process_run_id for a in replayed)


# ---- R4: redaction covers every observation surface --------------------------------------------

def test_reconcile_decision_correlation_and_schema_errors_never_carry_the_canary(tmp_path, store):
    """Counterexamples 5 and 6 inverted: reason, operator, correlation and schema-error paths."""
    o = file_observer(tmp_path, store, alert_window_seconds=0)
    record_id = termination_fixture(o)
    with pytest.raises(ContractError, match="operator must be an opaque identifier"):
        o.resolve_termination(record_id, resolution="discard", operator="password=" + CANARY, reason="r")
    with pytest.raises(ContractError, match="looks like a credential"):
        o.resolve_termination(record_id, resolution="discard", operator="ghp_" + "A" * 30, reason="r")
    result = o.resolve_termination(record_id, resolution="discard", operator="review", reason="password=" + CANARY)
    resolved_file = (tmp_path / "obs" / "terminations" / "resolved" / (record_id + ".json")).read_text("utf-8")
    assert result["resolution"]["reason"]["redaction_findings"] == 1
    assert "[REDACTED credential]" in result["resolution"]["reason"]["text"]
    # Free-text correlation ids are refused, never rewritten into a merged identity.
    assert o.emit("general.process_idle_exit", "observed", correlation_id="password=" + CANARY,
                  attributes={"idle_seconds": 1}) is None
    assert o.counters["refused"] == 1
    good = o.emit("general.process_idle_exit", "observed", correlation_id="corr:1", attributes={"idle_seconds": 1})
    invalid = dict(good, event_id="invalid-review-event", outcome="password=" + CANARY)
    o.spool.append("event", invalid)
    directory = SpoolDirectory(tmp_path / "obs")
    Collector(store, directory, validate=validate_observation, observer=o).collect()
    # The spool holds the hand-appended raw bytes by construction (the counterexample bypasses the
    # producer); every surface downstream of it and every producer-side surface must be clean.
    surfaces = [json.dumps(result, default=str), resolved_file]
    surfaces.append(json.dumps(directory.read_health()))
    surfaces.append(json.dumps(status_report(store, directory, o), default=str))
    with store.transaction() as tx:
        rows = [r for r in tx.records() if r["bucket"].startswith("observation")]
        surfaces.append(json.dumps(rows, default=str))
        [quarantined] = [q for q in tx.scan("observation_quarantine") if q["reason"] == "schema_refused"]
    # Paths and failed keywords only; jsonschema's default message would have repeated the value.
    assert quarantined["defect"] == "['event_id']: pattern; ['outcome']: enum"
    assert quarantined["event_id"] == "invalid-review-event"
    leaked = [index for index, surface in enumerate(surfaces) if CANARY in surface]
    assert leaked == []

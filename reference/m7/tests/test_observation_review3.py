"""Regressions for PR #71 third review (docs/zeus/reviews/claude-work-011/test_boundaries.py).

Each of Codex's four counterexamples reproduced an unsafe boundary; here the same scenarios
require the safe result. MemoryStore, actual temporary spool files and run locks, fake provider,
deterministic failures; not operational evidence.
"""
import json
import os
import subprocess
import sys
import time

import pytest
from test_observation_wiring import build
from test_observations import CANARY, Interceptor, file_observer

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory, writer_alive
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector, Observer
from codex_harness.cli import emit
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


# ---- R1 residual: the marker check is authoritative in the reservation transaction ------------

def test_failed_marker_read_blocks_instead_of_starting_the_provider(tmp_path, monkeypatch, store):
    """Counterexample inverted: one transient scan failure never turns a prior unconfirmed marker into a run."""
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    prior = s.executor.workflow.claim("worker:geeknews", "previous-worker")
    with store.transaction() as tx:
        marker = s.observer.mark_unconfirmed(tx, prior, reservation_id="prior-invocation")
        row = tx.get("tasks", s.task["id"])
        row["lease_until"] = "2000-01-01T00:00:00+00:00"
        tx.put("tasks", s.task["id"], row)
    outages = {"left": 1}

    def once(bucket):
        if bucket == "observation_terminations" and outages["left"]:
            outages["left"] -= 1
            return True
        return False

    intercepted.fail_scan = once
    result = s.executor.execute_one("worker:geeknews")
    assert len(s.starts) == 0, "a partial marker answer is never a permission to run"
    assert result["status"] in {"retry", "blocked"}
    with store.transaction() as tx:
        assert tx.get("observation_terminations", marker["record_id"])["status"] == "unconfirmed"
        assert tx.get("tasks", s.task["id"])["status"] != "succeeded"
    # With the sink answering, the earlier unconfirmed attempt blocks the new claim at reservation.
    intercepted.fail_scan = None
    if result["status"] == "retry":
        result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked" and result["error"] == "reconciliation_required" and len(s.starts) == 0


def test_marker_check_inside_the_reservation_transaction_refuses_without_a_local_file(tmp_path, monkeypatch, store):
    """Even when every read outside the transaction says 'none', the in-transaction guard decides."""
    s = build(tmp_path, monkeypatch, store)
    prior = s.executor.workflow.claim("worker:geeknews", "previous-worker")
    with store.transaction() as tx:
        s.observer.mark_unconfirmed(tx, prior, reservation_id="prior-invocation")
        row = tx.get("tasks", s.task["id"])
        row["lease_until"] = "2000-01-01T00:00:00+00:00"
        tx.put("tasks", s.task["id"], row)
    monkeypatch.setattr(s.observer, "pending_terminations", lambda task_id, strict=False: [])  # a blind pre-check
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked" and len(s.starts) == 0
    with store.transaction() as tx:
        assert not [r for r in tx.scan("invocation_reservations") if r["status"] == "reserved"]


# ---- design decision 3 residual: pending-only debt replays without any spool record -------------

def test_pending_alerts_without_spool_records_replay_after_recovery(tmp_path, store):
    """Counterexample inverted: a 1-byte spool and a dead sink leave pending files only; they replay."""
    intercepted = Interceptor(store)
    spool = FileSpool(tmp_path / "obs", new_process_run_id(), max_bytes=1, segment_bytes=1)
    first = Observer(intercepted, spool, component="review", directory=SpoolDirectory(tmp_path / "obs"))
    intercepted.fail_transaction = OSError("sink down")
    assert first.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1}) is None
    assert first.pending_alerts and first.directory.read_pending_alerts()
    debt = {r["event_id"] for r in first.pending_alerts}
    first.close()
    intercepted.fail_transaction = None
    second = Observer(store, FileSpool(tmp_path / "obs", new_process_run_id(), max_bytes=10000),
                      component="review-collector", directory=SpoolDirectory(tmp_path / "obs"))
    collector = Collector(store, second.directory, validate=validate_observation, observer=second)
    result = collector.collect()
    assert result["records"] == 0 and result["alerts_replayed"] == len(debt)
    assert not second.inherited_pending and second.directory.read_pending_alerts() == {}
    with store.transaction() as tx:
        rows = {a["event_id"]: a for a in tx.scan("observation_alerts")}
    assert debt <= set(rows) and all(rows[i]["notification"]["status"] == "recorded_after_recovery" for i in debt)
    second.close()


def test_pending_only_replay_survives_a_failed_commit_and_a_concurrent_inheritor(tmp_path, store):
    intercepted = Interceptor(store)
    spool = FileSpool(tmp_path / "obs", new_process_run_id(), max_bytes=1, segment_bytes=1)
    origin = Observer(intercepted, spool, component="review", directory=SpoolDirectory(tmp_path / "obs"))
    intercepted.fail_transaction = OSError("sink down")
    origin.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    debt = {r["event_id"] for r in origin.pending_alerts}
    origin.close()
    intercepted.fail_transaction = None
    directory = SpoolDirectory(tmp_path / "obs")
    b = file_observer(tmp_path, intercepted)
    c = file_observer(tmp_path, intercepted)
    intercepted.fail_put = lambda bucket, row: bucket == "observation_alerts"
    assert Collector(intercepted, directory, validate=validate_observation, observer=b).collect()["alerts_replayed"] == 0
    assert b.inherited_pending and directory.read_pending_alerts()
    intercepted.fail_put = None
    # C replays the origin's debt plus whatever B itself had to leave pending during its failed commit.
    assert Collector(intercepted, directory, validate=validate_observation, observer=c).collect()["alerts_replayed"] >= len(debt)
    assert Collector(intercepted, directory, validate=validate_observation, observer=b).collect()["alerts_replayed"] >= 0
    Collector(intercepted, directory, validate=validate_observation, observer=b).collect()
    assert directory.read_pending_alerts() == {} and not b.inherited_pending and not c.inherited_pending
    with store.transaction() as tx:
        assert len([a for a in tx.scan("observation_alerts") if a["event_id"] in debt]) == len(debt)


# ---- R3 residual: age is a candidate filter, the run lock is the liveness proof -----------------

def test_age_alone_never_finishes_a_live_writer(tmp_path):
    """Counterexample inverted: a writer holding the run lock is alive whatever its file age says."""
    o = file_observer(tmp_path, MemoryStore())
    assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    old = time.time() - 8 * 86400
    os.utime(o.spool.path, (old, old))
    directory = SpoolDirectory(tmp_path / "obs")
    directory.acknowledge(o.spool.path, o.spool.path.stat().st_size, 1)
    assert directory.writer_alive(o.process_run_id)
    assert not directory.run_finished(o.process_run_id, now=time.time() + 8 * 86400)
    assert directory.prune(now=time.time() + 8 * 86400)["segments"] == 0 and o.spool.path.exists()
    assert not directory.reclaimable(o.spool.path), "the live writer's last segment is preserved"
    assert directory.live_runs() == [o.process_run_id]
    assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 2}) is not None
    assert len(directory.spool_files()) == 1, "the later append still has a collectable path"
    o.close()
    assert directory.run_finished(o.process_run_id) and directory.prune()["segments"] >= 0


def test_dead_writer_is_proven_by_the_released_lock(tmp_path, store):
    """A process that died released its lock: its acknowledged last segment is reclaimable."""
    root = tmp_path / "obs"
    run = new_process_run_id()
    script = (
        "import sys\n"
        "from codex_harness.adapters.observation_spool import FileSpool\n"
        "spool = FileSpool(sys.argv[1], sys.argv[2], max_bytes=100000, fsync=False)\n"
        "spool.append('event', {'x': 1})\n"
        "print('written', flush=True)\n"
        "import time; time.sleep(30)\n"  # killed before it can close or write a marker
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(root), run], stdout=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert child.stdout.readline().strip() == b"written"
    directory = SpoolDirectory(root)
    assert directory.writer_alive(run), "the child holds the lock while it lives"
    child.kill()
    child.wait(timeout=30)
    deadline = time.monotonic() + 20  # the OS releases the lock shortly after exit; loaded hosts take a moment
    while directory.writer_alive(run) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not directory.writer_alive(run), "the operating system released the dead writer's lock"
    [path] = directory.spool_files()
    directory.acknowledge(path, path.stat().st_size, 1)
    assert directory.reclaimable(path)
    assert directory.run_finished(run, now=time.time() + 8 * 86400)


def test_second_writer_for_the_same_run_is_refused(tmp_path):
    o = file_observer(tmp_path, MemoryStore())
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    other = FileSpool(tmp_path / "obs", o.process_run_id, max_bytes=1000, fsync=False)
    try:
        with pytest.raises(ContractError, match="Another live writer"):
            other.append("event", {"x": 1})
    finally:
        other.close()  # round 4: ordinary cleanup of the refused writer must not finish the owner's run
    assert writer_alive(tmp_path / "obs", o.process_run_id) and not o.directory.closed(o.process_run_id)
    later = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 2})
    assert later is not None
    collected = Collector(MemoryStore(), o.directory, validate=validate_observation, observer=o).collect()
    assert collected["records"] >= 2, "the owner's later record is still collected"
    o.close()
    assert not writer_alive(tmp_path / "obs", o.process_run_id)


# ---- R4 residual: failures outside _run use the same public wording ----------------------------

def test_completion_error_never_reaches_the_result_or_cli(tmp_path, monkeypatch, store, capsys):
    """Counterexample inverted: the acceptance-write failure is published as boundary, type and digest."""
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda bucket, row: bucket == "tasks" and row.get("status") == "succeeded"
    result = s.executor.execute_one("worker:geeknews")
    assert result["status"] == "blocked"
    emit(result)
    out = capsys.readouterr().out
    leaked = CANARY in json.dumps(result, default=str) or CANARY in out
    assert not leaked
    assert "acceptance failed after provider entry (OSError: message_sha256=" in result["attempt_outcomes"][-1]["error"]
    intercepted.fail_put = None
    with store.transaction() as tx:
        rows = [r for r in tx.records() if r["bucket"] in {"tasks", "decisions_pending", "outbox", "events"}
                or r["bucket"].startswith("observation")]
    assert CANARY not in json.dumps(rows, default=str)
    assert CANARY not in json.dumps(s.observer.spool.records())
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["boundary"] == "acceptance" and pending["error_type"] == "OSError"

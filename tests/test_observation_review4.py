"""Regressions for PR #71 fourth review (docs/zeus/reviews/claude-work-012/{test_lock_boundary.py,
lock_boundaries_linux.py}).

Codex's two counterexamples reproduced (a) a refused second writer finishing the live owner's run
with its own close() and (b) the liveness probe moving the retention clock. Here the same scenarios
require the safe result. Temporary directories, real run locks, MemoryStore or the disposable
PostgreSQL store for the collector case; not operational evidence.
"""
import os
import subprocess
import sys
import time

import pytest
from test_observations import file_observer

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import (
    FileSpool,
    SpoolDirectory,
    run_lock_path,
    writer_alive,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


def dead_run(root, *, acknowledge: bool, age_seconds: float = 8 * 86400) -> tuple[str, "FileSpool"]:
    """Codex's equivalent of a crashed writer: descriptor closed, lock released, lock file left
    behind (POSIX keeps it), every file dated `age_seconds` ago, no closed marker."""
    run = new_process_run_id()
    spool = FileSpool(root, run, max_bytes=10000, fsync=False)
    spool.append("event", {"event": "before-crash"})
    if acknowledge:
        SpoolDirectory(root).acknowledge(spool.path, spool.path.stat().st_size, 1)
    os.close(spool._descriptor)
    spool._descriptor = None
    spool._lock.release()
    spool._lock = None
    lock_path = run_lock_path(root, run)
    lock_path.touch(exist_ok=True)
    old = time.time() - age_seconds
    for path in (spool.path, lock_path):
        os.utime(path, (old, old))
    return run, spool


# ---- R3-A: only the lock holder finishes a run ---------------------------------------------------

def test_refused_writer_close_leaves_the_owners_run_alive(tmp_path):
    """Counterexample inverted: the refused writer's ordinary cleanup finishes nothing shared."""
    run = "3" * 32
    owner = FileSpool(tmp_path, run, max_bytes=10000, fsync=False)
    other = FileSpool(tmp_path, run, max_bytes=10000, fsync=False)
    directory = SpoolDirectory(tmp_path)
    try:
        owner.append("event", {"x": 1})
        directory.acknowledge(owner.path, owner.path.stat().st_size, 1)
        with pytest.raises(ContractError, match="Another live writer"):
            other.append("event", {"x": 2})
        assert not other.owns_run and owner.owns_run
        other.close()
        assert not (tmp_path / "spool" / (run + ".closed")).exists(), "a non-owner writes no closed marker"
        assert directory.writer_alive(run)
        assert not directory.run_finished(run)
        assert not directory.reclaimable(owner.path)
        assert directory.prune() == {"runs": 0, "segments": 0, "files": 0} and owner.path.exists()
        assert owner.append("event", {"x": 3}) > 0, "the owner keeps writing into its own run"
        assert directory.spool_files() == [owner.path], "the later record has a collectable path"
        assert directory.live_runs() == [run]
    finally:
        owner.close()
    assert directory.closed(run) and not writer_alive(tmp_path, run)
    assert directory.run_finished(run)


def test_owner_record_after_a_refused_writers_close_is_collected(tmp_path, store):
    """The WSL loss scenario end to end: a refused writer closes, the owner's next record reaches the sink."""
    o = file_observer(tmp_path, store)
    first = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    assert first is not None
    other = FileSpool(tmp_path / "obs", o.process_run_id, max_bytes=10000, fsync=False)
    with pytest.raises(ContractError, match="Another live writer"):
        other.append("event", {"x": 1})
    other.close()
    later = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 2})
    assert later is not None
    collector = Collector(store, o.directory, validate=validate_observation, observer=o)
    result = collector.collect()
    assert result["records"] >= 2
    with store.transaction() as tx:
        ids = {row["event_id"] for row in tx.scan("observations")}
    assert first["event_id"] in ids and later["event_id"] in ids
    assert o.spool.path.exists(), "the owner's current segment survives the collection"
    o.close()


def test_closed_writer_refuses_further_appends_and_repeated_close_is_a_no_op(tmp_path):
    run = new_process_run_id()
    spool = FileSpool(tmp_path, run, max_bytes=10000, fsync=False)
    spool.append("event", {"x": 1})
    spool.close()
    marker = tmp_path / "spool" / (run + ".closed")
    stamp = marker.read_bytes()
    with pytest.raises(ContractError, match="closed by its writer"):
        spool.append("event", {"x": 2})
    spool.close()
    assert marker.read_bytes() == stamp, "a second close rewrites nothing"
    assert not writer_alive(tmp_path, run)


def test_writer_that_never_acquired_the_lock_writes_no_marker(tmp_path):
    run = new_process_run_id()
    FileSpool(tmp_path, run, max_bytes=10000, fsync=False).close()
    assert not (tmp_path / "spool" / (run + ".closed")).exists()
    assert SpoolDirectory(tmp_path).known_runs() == set()


# ---- R3-B: probing never moves the retention clock -----------------------------------------------

def test_dead_run_is_finished_on_the_first_check_with_the_real_clock(tmp_path):
    """Counterexample inverted: the lock file's mtime is not a writer record; probes do not renew it."""
    run, spool = dead_run(tmp_path, acknowledge=True)
    directory = SpoolDirectory(tmp_path)
    before = directory.run_age(run)
    assert before > 7 * 86400
    assert directory.run_finished(run), "no live holder and the last write is older than retention"
    for _ in range(3):  # repeated probes on a loaded collector schedule
        assert not directory.writer_alive(run)
        assert directory.run_finished(run)
    assert directory.run_age(run) >= before - 5, "the age only grows"
    assert directory.reclaimable(spool.path)
    pruned = directory.prune()
    assert pruned["runs"] == 1 and pruned["segments"] == 1
    # POSIX keeps the lock file until prune unlinks it under the lock; Windows filelock already
    # unlinked it when the probe released, so there the count is 0 and the file is equally gone.
    assert pruned["files"] == (0 if os.name == "nt" else 1)
    assert not spool.path.exists() and not run_lock_path(tmp_path, run).exists()
    assert run not in directory.known_runs()


def test_dead_run_with_an_unacknowledged_record_is_collected_then_pruned(tmp_path, store):
    """A crashed writer's last record is not lost to retention: the collector finalizes it first."""
    run, spool = dead_run(tmp_path / "obs", acknowledge=False)
    o = file_observer(tmp_path, store)
    collector = Collector(store, o.directory, validate=validate_observation, observer=o)
    result = collector.collect()
    # The raw {'event': ...} body is not a valid observation: it is consumed as refused or corrupt,
    # which acknowledges the segment; either way the finished run's record is not lost to retention.
    assert result["records"] + result["corrupt"] + result["refused"] >= 1
    assert not spool.path.exists(), "consumed segment of a finished run is reclaimed"
    assert not run_lock_path(tmp_path / "obs", run).exists()
    o.close()


def test_prune_leaves_a_live_writer_intact_whatever_its_file_ages_say(tmp_path):
    """A child holding the lock is alive: stale segment and lock mtimes prune nothing, and its lock file
    is never unlinked from under it; after it dies, the same directory state is reclaimed."""
    root = tmp_path / "obs"
    run = new_process_run_id()
    script = (
        "import sys\n"
        "from codex_harness.adapters.observation_spool import FileSpool\n"
        "spool = FileSpool(sys.argv[1], sys.argv[2], max_bytes=100000, fsync=False)\n"
        "spool.append('event', {'x': 1})\n"
        "print('written', flush=True)\n"
        "import time; time.sleep(30)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(root), run], stdout=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        assert child.stdout.readline().strip() == b"written"
        directory = SpoolDirectory(root)
        [path] = directory.spool_files()
        directory.acknowledge(path, path.stat().st_size, 1)
        old = time.time() - 8 * 86400
        os.utime(path, (old, old))
        try:
            os.utime(run_lock_path(root, run), (old, old))
        except OSError:
            pass  # Windows keeps the held lock file exclusively open
        assert directory.writer_alive(run)
        assert not directory.run_finished(run, now=time.time() + 8 * 86400)
        assert directory.prune(now=time.time() + 8 * 86400) == {"runs": 0, "segments": 0, "files": 0}
        assert path.exists() and run_lock_path(root, run).exists()
    finally:
        child.kill()
        child.wait(timeout=30)
    deadline = time.monotonic() + 20
    while directory.writer_alive(run) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not directory.writer_alive(run)
    assert directory.run_finished(run, now=time.time() + 8 * 86400)
    pruned = directory.prune(now=time.time() + 8 * 86400)
    assert pruned["segments"] == 1 and not path.exists() and not run_lock_path(root, run).exists()


def test_leftover_lock_file_alone_is_reclaimed(tmp_path):
    """A run known only by a free lock file (writer died before its first record) is pruned."""
    run = new_process_run_id()
    run_lock_path(tmp_path, run).parent.mkdir(parents=True)
    run_lock_path(tmp_path, run).touch()
    directory = SpoolDirectory(tmp_path)
    assert run in directory.known_runs()
    assert directory.run_age(run) is None and directory.run_finished(run)
    pruned = directory.prune()
    assert pruned["files"] == (0 if os.name == "nt" else 1), "POSIX unlinks it here; Windows did at the probe's release"
    assert not run_lock_path(tmp_path, run).exists() and directory.known_runs() == set()

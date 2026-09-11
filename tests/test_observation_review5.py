"""Regressions for PR #71 fifth review (docs/zeus/reviews/claude-work-013/startup_gc_race_linux.py).

Codex reproduced, with real file locks and thread barriers at the real lock and write calls, a
writer that registers its run between the collector's finish decision and the collector's file
deletions: the writer's active segment was deleted, its append succeeded, and nothing was left to
collect. Here the same barrier positions require the safe result on Windows and Linux: writer
registration, close, liveness probes and garbage collection are serialized by the directory's
lifecycle lock, so either the writer registers first and keeps its file, or the collector finishes
first and the writer starts on a valid path. Temporary directories, real locks, MemoryStore;
not operational evidence.
"""
import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_observations import file_observer

import codex_harness.adapters.observation_spool as spool_module
from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import (
    FileSpool,
    SpoolDirectory,
    lifecycle_lock,
    run_lock_path,
    writer_alive,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector, Observer
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id

LOCKS = importlib.import_module("filelock._windows" if os.name == "nt" else "filelock._unix")
WAIT = 15.0


class Barriers:
    """Codex's barrier positions for the thread named 'first-writer': after the run lock file is
    opened but before the lock is acquired, and after the active segment is open but before the
    first record is written. Every other thread and call passes through untouched."""

    def __init__(self, monkeypatch, spool: FileSpool, *, pause_at_run_lock: bool = True):
        self.spool = spool
        self.lock_opened = threading.Event()
        self.allow_lock = threading.Event()
        self.before_write = threading.Event()
        self.allow_write = threading.Event()
        self.lock_calls = 0
        original_lock, original_write = LOCKS._lock_fd_nonblocking, os.write

        def paused_lock(fd):
            if threading.current_thread().name == "first-writer":
                self.lock_calls += 1
                # call 1 = the lifecycle lock, call 2 = the run lock (Codex's 'lock_created' point)
                if (self.lock_calls == 2) == pause_at_run_lock:
                    self.lock_opened.set()
                    assert self.allow_lock.wait(WAIT)
            return original_lock(fd)

        def paused_write(fd, data):
            if threading.current_thread().name == "first-writer" and fd == self.spool._descriptor:
                self.before_write.set()
                assert self.allow_write.wait(WAIT)
            return original_write(fd, data)

        monkeypatch.setattr(LOCKS, "_lock_fd_nonblocking", paused_lock)
        monkeypatch.setattr(os, "write", paused_write)

    def release_all(self):
        self.allow_lock.set()
        self.allow_write.set()


def writer_thread(observer: Observer, out: dict) -> threading.Thread:
    def produce():
        try:
            out["event"] = observer.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            out["error"] = type(exc).__name__
    return threading.Thread(target=produce, name="first-writer")


def in_thread(target, name):
    out = {}

    def run():
        out["result"] = target()
    thread = threading.Thread(target=run, name=name)
    thread.start()
    return thread, out


# ---- the counterexample inverted: registration and GC are one step each ------------------------

def test_gc_waits_for_a_registering_writer_and_keeps_its_active_segment(tmp_path, monkeypatch):
    """Codex's order: writer opened its run lock file, GC decides. Now GC cannot decide until the
    writer holds the run lock and has its segment open, so it sees a live owner and deletes nothing."""
    root = tmp_path / "obs"
    store = MemoryStore()
    spool = FileSpool(root, new_process_run_id(), max_bytes=10000, fsync=False)
    observer = Observer(store, spool, component="race", directory=SpoolDirectory(root))
    directory = observer.directory
    barriers = Barriers(monkeypatch, spool)
    out = {}
    writer = writer_thread(observer, out)
    writer.start()
    try:
        assert barriers.lock_opened.wait(WAIT), "the writer opened its run lock file and paused before locking it"
        gc, pruned = in_thread(directory.prune, "gc")
        gc.join(0.5)
        assert gc.is_alive(), "GC blocks on the lifecycle lock while a writer is registering"
        barriers.allow_lock.set()
        assert barriers.before_write.wait(WAIT), "the writer holds the run lock and opened its segment"
        gc.join(WAIT)
        assert not gc.is_alive()
        assert pruned["result"]["segments"] == 0 and pruned["result"]["runs"] == 0
        assert spool.path.exists(), "the active segment of the registered writer is kept"
        assert directory.writer_alive(spool.process_run_id)
        barriers.allow_write.set()
        writer.join(WAIT)
        assert "error" not in out and out["event"] is not None
        assert directory.spool_files() == [spool.path], "the successful write has a collectable path"
        collected = Collector(store, directory, validate=validate_observation, observer=observer).collect()
        assert collected["records"] >= 1
        with store.transaction() as tx:
            assert out["event"]["event_id"] in {row["event_id"] for row in tx.scan("observations")}
    finally:
        barriers.release_all()
        writer.join(WAIT)
        observer.close()


def test_collector_reclaim_waits_for_registration_and_refuses_the_active_segment(tmp_path, monkeypatch):
    """The collector's own segment reclamation follows the same rule as GC."""
    root = tmp_path / "obs"
    spool = FileSpool(root, new_process_run_id(), max_bytes=10000, fsync=False)
    observer = Observer(MemoryStore(), spool, component="race", directory=SpoolDirectory(root))
    directory = observer.directory
    barriers = Barriers(monkeypatch, spool)
    out = {}
    writer = writer_thread(observer, out)
    writer.start()
    try:
        assert barriers.lock_opened.wait(WAIT)
        reclaim, result = in_thread(lambda: directory.reclaim(spool.path), "collector")
        reclaim.join(0.5)
        assert reclaim.is_alive(), "reclaim blocks on the lifecycle lock while a writer is registering"
        barriers.allow_lock.set()
        assert barriers.before_write.wait(WAIT)
        reclaim.join(WAIT)
        assert not reclaim.is_alive() and result["result"] is False
        assert spool.path.exists()
        barriers.allow_write.set()
        writer.join(WAIT)
        assert "error" not in out and out["event"] is not None and directory.spool_files() == [spool.path]
    finally:
        barriers.release_all()
        writer.join(WAIT)
        observer.close()


def test_gc_that_runs_before_registration_leaves_the_writer_a_valid_path(tmp_path, monkeypatch):
    """The other legal order: the writer is paused before it takes the lifecycle lock, GC runs to
    completion, then the writer registers and its record is collectable."""
    root = tmp_path / "obs"
    store = MemoryStore()
    stale = new_process_run_id()
    run_lock_path(root, stale).parent.mkdir(parents=True)
    run_lock_path(root, stale).touch()  # a leftover from a writer that died before its first record
    spool = FileSpool(root, new_process_run_id(), max_bytes=10000, fsync=False)
    observer = Observer(store, spool, component="race", directory=SpoolDirectory(root))
    directory = observer.directory
    barriers = Barriers(monkeypatch, spool, pause_at_run_lock=False)  # pause at the lifecycle lock instead
    out = {}
    writer = writer_thread(observer, out)
    writer.start()
    try:
        assert barriers.lock_opened.wait(WAIT), "the writer is about to take the lifecycle lock and holds nothing"
        pruned = directory.prune()
        assert pruned["skipped"] == 0 and not run_lock_path(root, stale).exists()
        assert spool.process_run_id not in directory.known_runs()
        barriers.allow_lock.set()
        assert barriers.before_write.wait(WAIT)
        barriers.allow_write.set()
        writer.join(WAIT)
        assert "error" not in out and out["event"] is not None
        assert directory.spool_files() == [spool.path] and directory.writer_alive(spool.process_run_id)
        assert Collector(store, directory, validate=validate_observation, observer=observer).collect()["records"] >= 1
    finally:
        barriers.release_all()
        writer.join(WAIT)
        observer.close()


def test_writer_after_gc_reclaimed_its_leftover_starts_on_a_valid_path(tmp_path):
    """Sequential form of the GC-first order, with the same run id as the reclaimed leftover."""
    root = tmp_path / "obs"
    run = new_process_run_id()
    run_lock_path(root, run).parent.mkdir(parents=True)
    run_lock_path(root, run).touch()
    directory = SpoolDirectory(root)
    assert directory.prune()["runs"] == 1 and not run_lock_path(root, run).exists()  # the leftover run is reclaimed
    spool = FileSpool(root, run, max_bytes=10000, fsync=False)
    assert spool.append("event", {"x": 1}) > 0
    assert directory.spool_files() == [spool.path] and directory.writer_alive(run)
    assert directory.prune() == {"runs": 0, "segments": 0, "files": 0, "skipped": 0}
    spool.close()


# ---- the lifecycle lock is held elsewhere: nothing is decided, nothing is half-done ---------------

def test_busy_lifecycle_lock_defers_gc_and_refuses_the_writer_clearly(tmp_path, monkeypatch):
    """Another process holds the lifecycle lock: probes answer alive, prune skips, reclaim declines,
    a writer is refused before touching any file; once the lock frees, everything proceeds."""
    root = tmp_path / "obs"
    stale = new_process_run_id()
    run_lock_path(root, stale).parent.mkdir(parents=True)
    run_lock_path(root, stale).touch()
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\nfrom filelock import FileLock\n"
         "lock = FileLock(sys.argv[1], is_singleton=False)\nlock.acquire(timeout=5)\n"
         "print('held', flush=True)\ntime.sleep(60)\n",
         str(Path(lifecycle_lock(root).lock_file))],
        stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        assert holder.stdout.readline().strip() == b"held"
        monkeypatch.setattr(spool_module, "LIFECYCLE_TIMEOUT", 0.5)
        directory = SpoolDirectory(root)
        assert writer_alive(root, stale), "a busy lifecycle lock is not proof of absence"
        assert directory.prune() == {"runs": 0, "segments": 0, "files": 0, "skipped": 1}
        assert run_lock_path(root, stale).exists()
        spool = FileSpool(root, new_process_run_id(), max_bytes=10000, fsync=False)
        with pytest.raises(ContractError, match="directory is busy"):
            spool.append("event", {"x": 1})
        assert directory.spool_files() == [] and not run_lock_path(root, spool.process_run_id).exists()
        assert not spool.owns_run
        assert directory.reclaim(root / "spool" / (stale + ".0000.jsonl")) is False
    finally:
        holder.kill()
        holder.wait(timeout=30)
    deadline = time.monotonic() + 20
    while writer_alive(root, stale) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not writer_alive(root, stale)
    assert directory.prune()["skipped"] == 0 and not run_lock_path(root, stale).exists()
    assert spool.append("event", {"x": 1}) > 0 and spool.owns_run
    spool.close()


def test_close_is_serialized_with_gc_and_the_last_segment_is_reclaimed_once(tmp_path):
    """Owner close under the lifecycle lock: after it, the run is finished and prune reclaims the
    acknowledged last segment exactly once; the lifecycle lock file itself is never pruned."""
    o = file_observer(tmp_path, MemoryStore())
    assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    directory = SpoolDirectory(tmp_path / "obs")
    directory.acknowledge(o.spool.path, o.spool.path.stat().st_size, 1)
    o.close()
    assert directory.run_finished(o.process_run_id)
    first = directory.prune()
    assert first["segments"] == 1 and first["runs"] == 1
    assert directory.prune()["segments"] == 0
    assert directory.known_runs() == set()
    assert lifecycle_lock(tmp_path / "obs").lock_file.endswith(".lifecycle.lock")
    assert ".lifecycle.lock" not in {p.name for p in directory.spool_files()}

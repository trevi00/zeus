"""Durable spool: complete records survive, partial tails and corruption are identified (U001 L05/L06)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import (
    FileSpool,
    SpoolDirectory,
    atomic_write,
    encode_record,
    segment_identity,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import Collector, Observer
from codex_harness.domain.observation import new_process_run_id
from codex_harness.ports import SpoolFull

CHILD = '''
import os, sys, time
from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.application.observations import Observer
from codex_harness.adapters.store import MemoryStore
root, mode, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
spool = FileSpool(root, sys.argv[4], max_bytes=1 << 26, fsync=False)
observer = Observer(MemoryStore(), spool, component="child:" + mode, directory=SpoolDirectory(root))
for index in range(count):
    observer.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
    if mode == "slow":
        time.sleep(0.002)
if mode == "partial":
    # Explicit fault input: the process dies with half a record written, as a kill mid-write would leave.
    line = b"0" * 64 + b" event {\\"half\\": tr"
    os.write(spool._open(), line)
    os._exit(3)
observer.close()
print(observer.process_run_id)
'''


def run_child(root, mode, count, run_id, kill_after=None):
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(root), mode, str(count), run_id],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if kill_after is not None:
        time.sleep(kill_after)
        child.kill()
    out, err = child.communicate(timeout=60)
    return child.returncode, out, err


def make_observer(root, store=None):
    spool = FileSpool(root, new_process_run_id(), max_bytes=1 << 20, fsync=False)
    return Observer(store or MemoryStore(), spool, component="unit", directory=SpoolDirectory(root))


def test_spool_roundtrip_bounds_and_ack_are_durable(tmp_path):
    root = tmp_path / "obs"
    o = make_observer(root)
    for index in range(3):
        o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
    directory = SpoolDirectory(root)
    [path] = directory.spool_files()
    rows = list(directory.read(path))
    assert [row[2] for row in rows] == ["complete"] * 3
    assert [row[4]["sequence"]["number"] for row in rows] == [1, 2, 3]
    directory.acknowledge(path, rows[-1][1], 3)
    assert directory.acknowledged(path) == rows[-1][1]
    assert list(directory.read(path, directory.acknowledged(path))) == []
    small = FileSpool(root, new_process_run_id(), max_bytes=200, fsync=False)
    small.append("event", {"a": 1})
    with pytest.raises(SpoolFull):
        small.append("event", {"b": "x" * 300})
    small.close()


def test_partial_tail_and_corruption_are_distinguished_and_recovered(tmp_path):
    root = tmp_path / "obs"
    o = make_observer(root)
    first = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    directory = SpoolDirectory(root)
    [path] = directory.spool_files()
    good = encode_record("event", first)
    with path.open("ab") as stream:
        stream.write(b"deadbeef" * 8 + b" event {}\n")           # hash mismatch
        stream.write(b"not a record line\n")                       # shape
        stream.write(good[:-10])                                   # truncated tail
    statuses = [(row[2], row[5]) for row in directory.read(path)]
    assert statuses == [("complete", None), ("corrupt", "hash mismatch"), ("corrupt", "line shape"),
                        ("truncated_tail", "no newline")]
    store = MemoryStore()
    collector = Collector(store, directory, validate=validate_observation)
    result = collector.collect()
    assert result["inserted"] == 1 and result["corrupt"] == 2 and result["truncated_tail"] == 1
    with path.open("ab") as stream:
        stream.write(good[-10:])                                   # the writer finished the record
    again = collector.collect()
    assert again["inserted"] == 0 and again["duplicates"] == 1 and again["truncated_tail"] == 0
    with store.transaction() as tx:
        assert len(tx.scan("observations")) == 1
        assert sorted(q["defect"] for q in tx.scan("observation_quarantine")) == ["hash mismatch", "line shape"]


def test_atomic_write_replaces_whole_file(tmp_path):
    target = tmp_path / "health.json"
    atomic_write(target, "first")
    atomic_write(target, "second")
    assert target.read_text("utf-8") == "second" and list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("backend", ["memory", "postgres"])
def test_real_child_processes_concurrent_kill_and_partial_tail_lose_no_complete_record(tmp_path, backend, request):
    """L05: actual child processes (one killed, one dying mid-write, two concurrent) plus one collector."""
    store = MemoryStore() if backend == "memory" else request.getfixturevalue("isolated_pgstore")
    root = tmp_path / "obs"
    runs = {mode: new_process_run_id() for mode in ("a", "b", "partial", "killed")}
    children = {mode: subprocess.Popen([sys.executable, "-c", CHILD, str(root), "a" if mode == "b" else mode,
                                        "150" if mode != "killed" else "100000", runs[mode]],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                for mode in ("a", "b", "partial", "killed")}
    directory = SpoolDirectory(root)
    killed_path = root / "spool" / (runs["killed"] + ".0000.jsonl")
    deadline = time.monotonic() + 90  # slow CI runners take seconds to import; kill only once it is producing
    while time.monotonic() < deadline:
        if killed_path.exists() and any(row[2] == "complete" for row in directory.read(killed_path)):
            break
        assert children["killed"].poll() is None, "the producer to be killed exited on its own"
        time.sleep(0.05)
    children["killed"].kill()
    results = {mode: child.communicate(timeout=60) for mode, child in children.items()}
    assert children["a"].returncode == 0 and children["b"].returncode == 0, results
    assert children["partial"].returncode == 3
    assert children["killed"].returncode != 0
    by_run = {}
    for path in directory.spool_files():
        by_run.setdefault(segment_identity(path)[0], []).append(path)
    assert set(by_run) == set(runs.values())
    killed_rows = [row for path in by_run[runs["killed"]] for row in directory.read(path)]
    complete_killed = [row for row in killed_rows if row[2] == "complete"]
    assert complete_killed, "the killed producer wrote at least one complete record before the kill"
    assert all(row[2] in {"complete", "truncated_tail"} for row in killed_rows)
    partial_rows = [row for path in by_run[runs["partial"]] for row in directory.read(path)]
    assert [row[2] for row in partial_rows][-1] == "truncated_tail" and len(partial_rows) == 151
    collector = Collector(store, directory, validate=validate_observation, batch=500)
    passes, first = [], {"inserted": 0, "conflicts": 0, "corrupt": 0, "duplicates": 0}
    while True:  # bounded batches per file per pass: drain until a pass consumes nothing
        result = collector.collect()
        passes.append(result)
        for key in first:
            first[key] += result[key]
        if result["records"] == 0:
            break
    expected = 150 + 150 + 150 + len(complete_killed)
    assert first["inserted"] == expected and first["conflicts"] == 0 and first["corrupt"] == 0
    assert first["duplicates"] == 0 and len(passes) >= 2 and passes[0]["truncated_tail"] == 1
    second = collector.collect()
    assert second["inserted"] == 0 and second["duplicates"] == 0 and second["records"] == 0
    with store.transaction() as tx:
        rows = tx.scan("observations")
        assert len(rows) == expected
        for run in (runs["a"], runs["b"]):
            numbers = sorted(r["sequence"]["number"] for r in rows if r["execution"]["process_run_id"] == run)
            assert numbers == list(range(1, 151))
    evidence = os.environ.get("ZEUS_OBSERVATION_TEST_EVIDENCE")
    if evidence:
        path = Path(evidence)
        path.mkdir(parents=True, exist_ok=True)
        (path / (runs["a"] + ".json")).write_text(json.dumps({
            "scope": "L05 actual child processes: two concurrent producers, one killed, one explicit partial tail",
            "backend": backend, "pids": {mode: child.pid for mode, child in children.items()},
            "exit_codes": {mode: child.returncode for mode, child in children.items()},
            "complete_from_killed": len(complete_killed), "inserted": first["inserted"],
            "passes": len(passes), "final_pass": second}, indent=2) + "\n", encoding="utf-8")

"""Shared S9 scenario steps (`observation.file_spool`): M7 `adapters/observation_spool.py` (`FileSpool`, `SpoolDirectory`, the lifecycle and run locks,
`writer_alive`, `atomic_write`, `read_records`, the segment naming and the acknowledgement offsets; INV-OBSERVATION-001).

Layer: harness (never shipped)

`api.module` is the side's spool module; `api.name` its import path (the real child processes import it by that name). Everything runs over real files in
a per-case temporary directory, with real child processes where M7's tests use them (two concurrent writers, a killed writer, a writer dying with half a
record, a held lock, a held lifecycle lock) and real threads with the M7 barrier positions (review5). The mirrored M7 tests are
`tests/test_observation_spool.py` and the spool parts of `tests/test_observation_review{,2,3,4,5}.py`.

Declared nondeterministic fields, normalized HERE and never by the mask list: the temporary root (`<root>` in any text), pids (never reported), file
mtimes (every aged file is set to the fixed epoch AGED with os.utime and `now` is given explicitly where an age is reported), and the two wall-clock
fields M7 writes (`updated_at` of an acknowledgement and `closed_at` of a closed marker): each is checked to be an ISO-8601 UTC instant and reported as
`<utc-iso>`. Run ids are fixed hex literals, so neither the harness clock nor its id source is needed. Outcomes are asserted, lock timing is not.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

AGED = 1577836800.0  # 2020-01-01T00:00:00Z: far older than any retention window, fixed
RUNS = {name: f"{index:032x}" for index, name in enumerate(
    ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p"), start=0xA0)}
WAIT = 20.0
DEFINITIONS = ("run_lock_path", "LIFECYCLE_TIMEOUT", "lifecycle_lock", "writer_alive", "RECORD_KINDS", "LINE", "RECORD_ID", "IDENTIFIER_NAME", "SEGMENT",
               "atomic_write", "encode_record", "read_records", "segment_path", "segment_identity", "read_acknowledged", "FileSpool", "MemorySpool",
               "SpoolDirectory")

CHILD = '''
import importlib, os, sys, time
M = importlib.import_module(sys.argv[1])
root, mode, count, run = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
spool = M.FileSpool(root, run, max_bytes=1 << 26, fsync=False)
for index in range(count):
    spool.append("event", {"i": index, "mode": mode})
    if mode == "slow":
        time.sleep(0.002)
if mode == "partial":
    os.write(spool._open(), b"0" * 64 + b' event {"half": tr')
    os._exit(3)
spool.close()
print(run)
'''
HOLD = '''
import importlib, sys, time
M = importlib.import_module(sys.argv[1])
spool = M.FileSpool(sys.argv[2], sys.argv[3], max_bytes=100000, fsync=False)
spool.append("event", {"x": 1})
print("written", flush=True)
time.sleep(60)
'''
LIFECYCLE_HOLDER = '''
import sys, time
from filelock import FileLock
lock = FileLock(sys.argv[1], is_singleton=False)
lock.acquire(timeout=5)
print("held", flush=True)
time.sleep(60)
'''


class Case:
    """One case: a fresh temporary root, normalized text, and the helpers the steps share."""

    def __init__(self, api):
        self.api, self.m = api, api.module
        self.root = Path(tempfile.mkdtemp(prefix="s9-spool-")).resolve()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def text(self, value) -> str:
        # The mkstemp suffix of atomic_write's temporary file is the one random name that can reach an error text.
        return re.sub(r"\.[A-Za-z0-9_]{8}\.tmp", ".<tmp>.tmp", str(value).replace(str(self.root), "<root>"))

    def call(self, fn, *args, **kwargs):
        try:
            return {"value": fn(*args, **kwargs)}
        except Exception as exc:  # the refusal is the characterized result
            return {"refused": type(exc).__name__, "message": self.text(exc)[:300]}

    def rel(self, path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def listing(self) -> dict:
        out = {"dirs": sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_dir()), "files": {}}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            name = path.relative_to(self.root).as_posix()
            if name.endswith((".ack", ".closed")):
                out["files"][name] = {"json": stamped(data), "ends_with_newline": data.endswith(b"\n")}
            else:
                out["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return out

    def age(self, *paths):
        for path in paths:
            try:
                os.utime(path, (AGED, AGED))
            except OSError:
                pass

    def age_all(self):
        self.age(*[p for p in self.root.rglob("*") if p.is_file()])


def stamped(data: bytes) -> dict:
    """A JSON file's content with each wall-clock field proven to be an ISO-8601 UTC instant and replaced by a symbol."""
    value = json.loads(data.decode("utf-8"))
    for key in ("updated_at", "closed_at"):
        if key in value:
            moment = datetime.fromisoformat(value[key])
            value[key] = "<utc-iso>" if moment.utcoffset() == timedelta(0) else "<not-utc>"
    return value


def rows(case, path, offset=0):
    return [{"start": r[0], "end": r[1], "status": r[2], "kind": r[3], "event": r[4], "defect": r[5]} for r in case.m.read_records(path, offset)]


def spawn(code, *args):
    return subprocess.Popen([sys.executable, "-c", code, *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def stop(child):
    if child.poll() is None:
        child.kill()
    try:
        child.communicate(timeout=60)
    except Exception:  # noqa: BLE001 - cleanup only
        pass


# ---- the cases -----------------------------------------------------------------------------------------------------------------------------------

def definitions(case):
    return {name: hasattr(case.m, name) for name in DEFINITIONS}


def names_and_codecs(case):
    m = case.m
    run = RUNS["a"]
    event = {"b": 2, "a": [1, "é☃", None], "z": {"k": True}}
    line = m.encode_record("event", event)
    return {
        "run_lock_path": case.rel(m.run_lock_path(case.root, run)), "segment_path": [case.rel(m.segment_path(case.root, run, n)) for n in (0, 7, 9999, 10000, 123456)],
        "segment_identity": {name: m.segment_identity(Path(name)) for name in (
            run + ".0000.jsonl", run + ".10000.jsonl", run + ".123.jsonl", run + ".12345678.jsonl", "x.0000.jsonl", run.upper() + ".0000.jsonl",
            run + ".0000.jsonl.tmp", run + ".0000.ack", run[:-1] + ".0000.jsonl", "not-a-segment")},
        "record_kinds": list(m.RECORD_KINDS), "line_sha256": hashlib.sha256(line).hexdigest(), "line_size": len(line),
        "line_shape": [line[64:65].decode(), line[65:70].decode(), line.endswith(b"\n")], "kind_refused": case.call(m.encode_record, "other", event),
        "audit_kind": m.encode_record("audit", {"x": 1}).split(b" ", 2)[1].decode(),
        "record_id": {value: m.RECORD_ID.fullmatch(value) is not None for value in ("a", "a.b:c-d_e", "x" * 200, "x" * 201, "", "a b", "a/b", "..", "é")},
        "identifier_name": {value: m.IDENTIFIER_NAME.fullmatch(value) is not None for value in (run, run.upper(), run[:-1], run + "0", "g" * 32)},
        "lifecycle_path": case.rel(m.lifecycle_lock(case.root).lock_file), "lifecycle_is_singleton": m.lifecycle_lock(case.root) is m.lifecycle_lock(case.root),
        "lifecycle_timeout": m.LIFECYCLE_TIMEOUT}


def append_read_rotation(case):
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=1 << 20, segment_bytes=170, fsync=False)
    out = {"constructed": {"root_is_path": isinstance(spool.root, Path), "segment_bytes": spool.segment_bytes, "max_bytes": spool.max_bytes,
                           "owns_run": spool.owns_run, "closed": spool.closed, "path": case.rel(spool.path), "files_after_construction": case.listing()["files"]}}
    offsets = [spool.append("event" if i % 3 else "audit", {"n": i, "pad": "p" * (i * 7)}) for i in range(8)]
    out["offsets"] = offsets
    out["after_append"] = {"owns_run": spool.owns_run, "segment": spool.segment, "rotations": spool.rotations, "size": spool.size(),
                           "unacknowledged": spool.unacknowledged_bytes(), "segments": [case.rel(p) for p in spool.segments()],
                           "path": case.rel(spool.path)}
    out["read"] = {case.rel(p): rows(case, p) for p in spool.segments()}
    out["segment_larger_than_limit_is_capped"] = {"segment_bytes": m.FileSpool(case.root / "cap", RUNS["b"], max_bytes=100, segment_bytes=10 ** 6).segment_bytes}
    spool.close()
    out["closed"] = {"closed": spool.closed, "owns_run": spool.owns_run, "listing": case.listing()}
    # A new object for the same run resumes at the segment number 0 file already on disk (append mode) after the owner has closed.
    again = m.FileSpool(case.root, RUNS["a"], max_bytes=1 << 20, fsync=False)
    out["reopen_after_close"] = {"append": case.call(again.append, "event", {"after": "close"}), "segment": again.segment, "owns_run": again.owns_run,
                                 "path": case.rel(again.path), "size_of_first_segment_before": spool.segments()[0].stat().st_size}
    again.close()
    out["listing"] = case.listing()
    fsync = m.FileSpool(case.root, RUNS["c"], max_bytes=1 << 20)
    out["fsync_default"] = {"fsync": fsync.fsync, "append": fsync.append("event", {"x": 1})}
    fsync.close()
    return out


def bounds_and_ack(case):
    m = case.m
    line = len(m.encode_record("event", {"a": 1}))
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=line + 10, fsync=False)
    first = spool.append("event", {"a": 1})
    refused = case.call(spool.append, "event", {"a": 2})
    out = {"line": line, "first": first, "second_refused": refused, "unacknowledged_after": spool.unacknowledged_bytes(),
           "segment_holds_exactly_the_first": rows(case, case.root / "spool" / (RUNS["a"] + ".0000.jsonl")), "listing_after_refusal": case.listing()["files"]}
    directory = m.SpoolDirectory(case.root)
    out["files_after_refusal"] = [case.rel(p) for p in directory.spool_files()]  # the refused append had already rotated to an empty second segment
    path = directory.spool_files()[0]
    directory.acknowledge(path, first, 1)
    out["ack_listing"] = case.listing()["files"]
    out["after_ack"] = {"acknowledged": directory.acknowledged(path), "unacknowledged": spool.unacknowledged_bytes(), "directory_unacknowledged": directory.unacknowledged_bytes(),
                        "read_from_ack": rows(case, path, directory.acknowledged(path))}
    out["append_after_ack_recomputes_from_disk"] = case.call(spool.append, "event", {"a": 2})
    out["second_segment"] = {"segments": [case.rel(p) for p in spool.segments()], "rotations": spool.rotations}
    spool.close()
    out["validation"] = {name: case.call(lambda k=kwargs: bool(m.FileSpool(case.root / "v", RUNS["b"], **k)))
                         for name, kwargs in (("zero", {"max_bytes": 0}), ("negative", {"max_bytes": -1}), ("bool", {"max_bytes": True}), ("float", {"max_bytes": 1.5}),
                                              ("string", {"max_bytes": "10"}), ("segment_zero", {"max_bytes": 10, "segment_bytes": 0}),
                                              ("segment_bool", {"max_bytes": 10, "segment_bytes": True}), ("ok", {"max_bytes": 10}))}
    out["missing_max_bytes"] = case.call(lambda: m.FileSpool(case.root, RUNS["c"]))
    small = m.FileSpool(case.root / "s", RUNS["d"], max_bytes=200, fsync=False)
    small.append("event", {"a": 1})
    out["review_bound"] = case.call(small.append, "event", {"b": "x" * 300})
    small.close()
    return out


def acknowledgements(case):
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=1 << 20, fsync=False)
    spool.append("event", {"a": 1})
    path = spool.path
    out = {"missing": m.read_acknowledged(path)}
    ack = path.with_suffix(".ack")
    for name, text in (("valid", '{"offset": 12}'), ("zero", '{"offset": 0}'), ("negative", '{"offset": -1}'), ("bool", '{"offset": true}'), ("float", '{"offset": 1.0}'),
                       ("string", '{"offset": "5"}'), ("missing_key", "{}"), ("list", "[1]"), ("not_json", "nope"), ("empty", ""), ("big", '{"offset": 99999999}')):
        ack.write_text(text, encoding="utf-8")
        out[name] = case.call(m.read_acknowledged, path)
    ack.write_bytes(b"\xff\xfe")
    out["bad_utf8"] = case.call(m.read_acknowledged, path)
    ack.unlink()
    ack.mkdir()
    out["ack_is_a_directory"] = case.call(m.read_acknowledged, path)
    ack.rmdir()
    directory = m.SpoolDirectory(case.root)
    directory.acknowledge(path, 5, 1)
    directory.acknowledge(path, 9, 2)
    out["acknowledged_twice"] = {"value": directory.acknowledged(path), "files": case.listing()["files"], "size_clamps": spool.unacknowledged_bytes()}
    directory.acknowledge(path, 10 ** 6, 3)
    out["offset_beyond_size"] = {"value": directory.acknowledged(path), "unacknowledged": spool.unacknowledged_bytes()}
    spool.close()
    return out


def partial_tail_and_corruption(case):
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=1 << 20, fsync=False)
    spool.append("event", {"n": 1})
    good = m.encode_record("event", {"n": 2, "text": "é☃"})
    path = spool.path
    body = b'{"half": 1}'
    with path.open("ab") as stream:
        stream.write(b"deadbeef" * 8 + b" event {}\n")                       # hash mismatch
        stream.write(b"not a record line\n")                                  # line shape
        stream.write(hashlib.sha256(b"{not json").hexdigest().encode() + b" audit {not json\n")  # invalid json
        stream.write(hashlib.sha256(b"[1]").hexdigest().encode() + b" event [1]\n")              # not an object
        stream.write(hashlib.sha256(body).hexdigest().encode() + b" other " + body + b"\n")      # unknown kind: line shape
        stream.write(good)
        stream.write(good[:-10])                                              # truncated tail
    statuses = rows(case, path)
    out = {"rows": statuses, "offsets_contiguous": all(a["end"] == b["start"] for a, b in zip(statuses, statuses[1:])),
           "file_size": path.stat().st_size, "last_end": statuses[-1]["end"]}
    tail_start = statuses[-1]["start"]
    with path.open("ab") as stream:
        stream.write(good[-10:])                                              # the writer finished the record
    out["finished_tail_from_start"] = rows(case, path, tail_start)
    out["from_past_the_end"] = rows(case, path, path.stat().st_size)
    out["from_a_mid_line_offset"] = [(r["status"], r["defect"]) for r in rows(case, path, 5)][:2]
    out["empty_file"] = rows(case, _touch(case, "empty.jsonl"))
    out["only_a_partial_line"] = rows(case, _write(case, "partial.jsonl", b"abc"))
    out["missing_file"] = case.call(lambda: list(m.read_records(case.root / "missing.jsonl")))
    spool.close()
    return out


def _touch(case, name):
    path = case.root / name
    path.write_bytes(b"")
    return path


def _write(case, name, data):
    path = case.root / name
    path.write_bytes(data)
    return path


def atomic_writes(case):
    m = case.m
    target = case.root / "health.json"
    m.atomic_write(target, "first")
    m.atomic_write(target, "second\nline\n")
    out = {"content": target.read_bytes().decode(), "only_the_target": sorted(p.name for p in case.root.iterdir())}
    m.atomic_write(case.root / "deep" / "er" / "x.json", "é☃\r\n")
    out["parents_created_and_newline_kept"] = (case.root / "deep" / "er" / "x.json").read_bytes().decode("utf-8")
    directory = case.root / "is-a-dir"
    directory.mkdir()
    out["replace_onto_a_directory"] = case.call(m.atomic_write, directory, "x") | {"leftovers": sorted(p.name for p in case.root.iterdir() if p.name.endswith(".tmp"))}
    out["non_text"] = case.call(m.atomic_write, case.root / "bytes.json", b"x") | {"leftovers": sorted(p.name for p in case.root.iterdir() if p.name.endswith(".tmp")),
                                                                                        "target_exists": (case.root / "bytes.json").exists()}
    return out


def lifecycle_and_locks(case):
    m = case.m
    run = RUNS["a"]
    out = {"free_run_is_not_alive": m.writer_alive(case.root, run)}
    owner = m.FileSpool(case.root, run, max_bytes=10000, fsync=False)
    other = m.FileSpool(case.root, run, max_bytes=10000, fsync=False)
    directory = m.SpoolDirectory(case.root)
    out["before_first_append"] = {"alive": directory.writer_alive(run), "owns": owner.owns_run}
    owner.append("event", {"x": 1})
    directory.acknowledge(owner.path, owner.path.stat().st_size, 1)
    out["owner"] = {"alive": directory.writer_alive(run), "owns": owner.owns_run, "module_probe": m.writer_alive(case.root, run)}
    out["second_writer_refused"] = case.call(other.append, "event", {"x": 2})
    out["refused_writer"] = {"owns": other.owns_run, "listing": case.listing()["files"]}
    other.close()
    out["refused_close"] = {"marker": (case.root / "spool" / (run + ".closed")).exists(), "alive": directory.writer_alive(run), "finished": directory.run_finished(run),
                            "reclaimable": directory.reclaimable(owner.path), "prune": directory.prune(), "segment_kept": owner.path.exists()}
    out["owner_keeps_writing"] = {"append": case.call(owner.append, "event", {"x": 3}), "spool_files": [case.rel(p) for p in directory.spool_files()],
                                  "live_runs": directory.live_runs()}
    out["refused_writer_is_closed_object"] = case.call(other.append, "event", {"x": 9})
    owner.close()
    marker = case.root / "spool" / (run + ".closed")
    stamp = marker.read_bytes()
    out["owner_closed"] = {"marker": stamped(stamp), "closed": directory.closed(run), "alive": directory.writer_alive(run), "finished": directory.run_finished(run),
                           "append": case.call(owner.append, "event", {"x": 4})}
    owner.close()
    out["repeated_close_rewrites_nothing"] = marker.read_bytes() == stamp
    never = m.FileSpool(case.root, RUNS["b"], max_bytes=10000, fsync=False)
    never.close()
    out["never_acquired"] = {"marker": (case.root / "spool" / (RUNS["b"] + ".closed")).exists(), "known": sorted(directory.known_runs() - {run})}
    out["close_serialized_with_gc"] = {"finished": directory.run_finished(run), "first_prune": directory.prune(), "second_prune": directory.prune(),
                                       "known_after": sorted(directory.known_runs()), "lifecycle_lock_file_kept": os.path.exists(m.lifecycle_lock(case.root).lock_file),
                                       "lifecycle_lock_is_not_a_segment": ".lifecycle.lock" not in {p.name for p in directory.spool_files()},
                                       "listing": case.listing()["files"]}
    return out


def directory_files(case):
    m = case.m
    directory = m.SpoolDirectory(case.root)
    out = {"empty_directory": {"spool_files": directory.spool_files(), "known": sorted(directory.known_runs()), "live": directory.live_runs(), "total_bytes": directory.total_bytes(),
                               "unacknowledged": directory.unacknowledged_bytes(), "health": directory.read_health(), "alerts": directory.read_pending_alerts(),
                               "terminations": directory.pending_terminations(), "prune": directory.prune()},
           "root_is_path": isinstance(directory.root, Path)}
    spool = case.root / "spool"
    spool.mkdir(parents=True)
    run, other = RUNS["a"], RUNS["b"]
    names = [f"{run}.10000.jsonl", f"{run}.9999.jsonl", f"{run}.0000.jsonl", f"{other}.0001.jsonl", "stray.jsonl", f"{run}.0000.ack", f"{run}.lock", f"{other}.closed",
             "short.lock", ".lifecycle.lock"]
    for name in names:
        (spool / name).write_bytes(b"")
    (case.root / "health").mkdir()
    (case.root / "health" / f"{RUNS['c']}.json").write_text("{}")
    (case.root / "health" / "bad-name.json").write_text("{}")
    out["spool_files_are_ordered_numerically"] = [case.rel(p) for p in directory.spool_files()]
    out["known_runs"] = sorted(directory.known_runs())
    out["read_is_read_records"] = directory.read(spool / f"{run}.0000.jsonl") is not None
    return out


def runs_ages_and_retention(case):
    m = case.m
    directory = m.SpoolDirectory(case.root)
    run = RUNS["a"]
    spool = m.FileSpool(case.root, run, max_bytes=10000, fsync=False)
    spool.append("event", {"x": 1})
    directory.write_health(run, {"process_run_id": run, "state": "up"})
    case.age_all()
    base = {"age_with_live_writer": directory.run_age(run, now=AGED + 100.0), "age_unknown_run": directory.run_age(RUNS["z"] if "z" in RUNS else RUNS["p"], now=AGED)}
    now = AGED + 8 * 86400
    base["live_writer_is_never_finished_by_age"] = {"finished": directory.run_finished(run, now=now), "live_runs": directory.live_runs(),
                                                     "prune": directory.prune(now=now), "segment_kept": spool.path.exists(),
                                                     "lock_file_kept": m.run_lock_path(case.root, run).exists(), "reclaimable": directory.reclaimable(spool.path)}
    directory.acknowledge(spool.path, spool.path.stat().st_size, 1)
    base["acknowledged_live_last_segment_is_kept"] = {"reclaimable": directory.reclaimable(spool.path), "prune": directory.prune(now=now), "segment_kept": spool.path.exists()}
    spool.append("event", {"x": 2})
    base["later_append_still_collectable"] = [case.rel(p) for p in directory.spool_files()]
    spool.close()
    case.age(*[p for p in case.root.rglob("*") if p.is_file() and p.suffix in {".jsonl", ".closed", ".json"}])
    base["closed_run"] = {"finished": directory.run_finished(run), "age": directory.run_age(run, now=AGED + 5.0)}
    base["closed_run_prune_keeps_the_unacknowledged_tail"] = {"prune": directory.prune(now=now), "segments_left": [case.rel(p) for p in directory.spool_files()]}
    directory.acknowledge(directory.spool_files()[0], directory.spool_files()[0].stat().st_size, 2)
    pruned = directory.prune(now=now)
    base["closed_run_acknowledged_prune"] = {"prune": pruned, "listing": case.listing()["files"], "known": sorted(directory.known_runs())}
    # Dead run without a marker: finished only by retention, never by a live lock, measured before the probe.
    dead = RUNS["b"]
    spool = m.FileSpool(case.root, dead, max_bytes=10000, fsync=False)
    spool.append("event", {"x": 1})
    spool._lock.release()      # the writer is gone: its lock is free (the lock holder in-process stands for the dead process)
    spool._lock = None
    os.close(spool._descriptor)
    spool._descriptor = None
    case.age_all()
    base["dead_run"] = {"alive": directory.writer_alive(dead), "age_before_probes": directory.run_age(dead, now=AGED + 3.0)}
    base["dead_run"]["finished_by_retention"] = {"inside_window": directory.run_finished(dead, now=AGED + 60.0), "outside_window": directory.run_finished(dead, now=now),
                                                 "custom_window": directory.run_finished(dead, now=AGED + 60.0, retention_seconds=10),
                                                 "repeated_probes": [directory.run_finished(dead, now=now) for _ in range(3)],
                                                 "age_only_grows": directory.run_age(dead, now=now) >= 8 * 86400}
    base["dead_run"]["reclaimable_unacknowledged"] = directory.reclaimable(spool.path)
    directory.acknowledge(spool.path, spool.path.stat().st_size, 1)
    base["dead_run"]["reclaimable_acknowledged"] = directory.reclaimable(spool.path)
    base["dead_run"]["prune"] = directory.prune()
    base["dead_run"]["gone"] = {"segment": spool.path.exists(), "lock": m.run_lock_path(case.root, dead).exists(), "known": sorted(directory.known_runs())}
    # A free lock file alone (the writer died before its first record).
    leftover = RUNS["c"]
    m.run_lock_path(case.root, leftover).parent.mkdir(parents=True, exist_ok=True)
    m.run_lock_path(case.root, leftover).touch()
    base["leftover_lock_file"] = {"known": leftover in directory.known_runs(), "age": directory.run_age(leftover), "finished": directory.run_finished(leftover),
                                  "prune": directory.prune(), "gone": not m.run_lock_path(case.root, leftover).exists(), "known_after": sorted(directory.known_runs())}
    sink = RUNS["d"]
    m.run_lock_path(case.root, sink).touch()
    base["writer_after_gc_reclaimed_its_leftover"] = {"prune": directory.prune()}
    again = m.FileSpool(case.root, sink, max_bytes=10000, fsync=False)
    base["writer_after_gc_reclaimed_its_leftover"].update({"append": case.call(again.append, "event", {"x": 1}), "files": [case.rel(p) for p in directory.spool_files()],
                                                           "alive": directory.writer_alive(sink), "prune": directory.prune()})
    again.close()
    return base


def prune_and_reclaim(case):
    m = case.m
    directory = m.SpoolDirectory(case.root)
    run = RUNS["a"]
    spool = m.FileSpool(case.root, run, max_bytes=1 << 20, segment_bytes=100, fsync=False)
    for i in range(4):
        spool.append("event", {"n": i, "pad": "p" * 20})
    paths = spool.segments()
    out = {"segments": [case.rel(p) for p in paths], "reclaimable_unacknowledged": [directory.reclaimable(p) for p in paths]}
    for p in paths:
        directory.acknowledge(p, p.stat().st_size, 1)
    out["reclaimable_acknowledged_open_run"] = [directory.reclaimable(p) for p in paths]
    out["reclaim_the_active_one_is_refused"] = directory.reclaim(paths[-1])
    out["reclaim_a_rotated_past_one"] = {"reclaimed": directory.reclaim(paths[0]), "segment_gone": not paths[0].exists(), "ack_gone": not paths[0].with_suffix(".ack").exists()}
    out["reclaim_twice"] = directory.reclaim(paths[0])
    out["reclaim_non_segment"] = directory.reclaim(case.root / "spool" / "x.jsonl")
    spool.close()
    out["after_close"] = {"reclaimable_last": directory.reclaimable(paths[-1]), "unacknowledged": directory.unacknowledged_bytes(), "total_bytes_positive": directory.total_bytes() > 0}
    out["prune_after_close"] = directory.prune()
    out["listing"] = case.listing()["files"]
    # Pending alert files are removed with a finished run only when nothing is outstanding.
    other = RUNS["b"]
    spool = m.FileSpool(case.root, other, max_bytes=10000, fsync=False)
    spool.append("event", {"x": 1})
    spool.close()
    directory.acknowledge(directory.spool_files()[0], directory.spool_files()[0].stat().st_size, 1)
    directory.write_pending_alerts(other, [{"event_id": "e1"}])
    directory.write_health(other, {"process_run_id": other})
    out["finished_run_with_outstanding_alert"] = {"prune": directory.prune(), "alerts_kept": sorted(directory.read_pending_alerts()),
                                                  "listing": case.listing()["files"]}
    directory.acknowledge_pending_alerts(other, ["e1"], RUNS["c"])
    out["alert_acknowledged_by_a_replayer"] = {"prune": directory.prune(), "listing": case.listing()["files"]}
    return out


def health_alerts_terminations(case):
    m = case.m
    directory = m.SpoolDirectory(case.root)
    run = RUNS["a"]
    path = directory.write_health(run, {"process_run_id": run, "state": "up", "n": 1})
    out = {"health_path": case.rel(path), "health": directory.read_health()}
    (case.root / "health" / "broken.json").write_text("{not json")
    (case.root / "health" / "listish.json").write_text("[1]")
    out["health_with_an_unreadable_file"] = directory.read_health()
    out["health_listing"] = case.listing()["files"]
    # pending alerts
    origin, replayer, second = RUNS["b"], RUNS["c"], RUNS["d"]
    rows_ = [{"event_id": f"e{i}", "n": i} for i in range(4)]
    directory.write_pending_alerts(origin, rows_)
    out["pending"] = directory.read_pending_alerts()
    directory.acknowledge_pending_alerts(origin, ["e0", "e1"], replayer)
    directory.acknowledge_pending_alerts(origin, ["e1", "e2"], replayer)
    directory.acknowledge_pending_alerts(origin, ["e3"], second)
    out["acknowledged"] = {"ids": sorted(directory.acknowledged_alerts(origin)), "pending": directory.read_pending_alerts(), "listing": sorted(case.listing()["files"])}
    directory.write_pending_alerts(origin, rows_ + [{"event_id": "e9"}])
    out["origin_rewrite_drops_acknowledged_ids"] = directory.read_pending_alerts()
    directory.write_pending_alerts(origin, [])
    out["origin_empty_removes_the_file"] = {"pending": directory.read_pending_alerts(), "files": sorted(case.listing()["files"])}
    directory.write_pending_alerts(second, [{"event_id": "x"}])
    (case.root / "pending-alerts" / (RUNS["e"] + ".json")).write_text("not json")
    (case.root / "pending-alerts" / (RUNS["f"] + ".json")).write_text('[1, {"event_id": "y"}]')
    (case.root / "pending-alerts" / (RUNS["g"] + ".json")).write_text("{}")
    (case.root / "pending-alerts" / f"{origin}.acked.broken.json").write_text("nope")
    (case.root / "pending-alerts" / f"{origin}.acked.dict.json").write_text("{}")
    out["unreadable_or_odd_alert_files"] = {"pending": directory.read_pending_alerts(), "acked_ids": sorted(directory.acknowledged_alerts(origin)),
                                            "acknowledge_over_a_broken_file": case.call(directory.acknowledge_pending_alerts, origin, ["z"], "broken") |
                                            {"after": sorted(directory.acknowledged_alerts(origin))}}
    # terminations
    record = {"record_id": "t1", "task_id": "task-1", "status": "pending_reconciliation"}
    out["termination"] = {"record": case.rel(directory.record_termination("t1", record)), "again": case.call(directory.record_termination, "t1", record),
                          "invalid_ids": {value: case.call(directory.record_termination, value, record) for value in ("", "a b", "a/b", "x" * 201)},
                          "pending": directory.pending_terminations(), "for_task": directory.pending_terminations("task-1"), "for_other_task": directory.pending_terminations("nope")}
    (case.root / "terminations" / "t2.json").write_text("{not json")
    (case.root / "terminations" / "t3.json").write_text('{"record_id": 3}')
    (case.root / "terminations" / "t4.json").write_text('[1]')
    out["termination"]["unreadable_files_block_every_task"] = directory.pending_terminations("nope")
    out["termination"]["unreadable_for_task"] = directory.pending_terminations("task-1")
    out["termination"]["resolve"] = case.call(directory.resolve_termination, "t1", {"by": "sink", "n": 1})
    out["termination"]["resolve_again_is_idempotent"] = case.call(directory.resolve_termination, "t1", {"by": "other"})
    out["termination"]["resolve_unknown"] = case.call(directory.resolve_termination, "nope", {})
    out["termination"]["resolve_invalid_id"] = case.call(directory.resolve_termination, "a/b", {})
    out["termination"]["resolve_unreadable"] = case.call(directory.resolve_termination, "t2", {"by": "sink"})
    out["termination"]["after"] = {"pending": [r["record_id"] for r in directory.pending_terminations()], "listing": case.listing()["files"]}
    return out


def real_child_processes(case):
    m, name = case.m, case.api.name
    runs = {"a": RUNS["a"], "b": RUNS["b"], "partial": RUNS["c"], "killed": RUNS["d"]}
    children = {mode: spawn(CHILD, name, case.root, "a" if mode == "b" else "slow" if mode == "killed" else mode,
                            100000 if mode == "killed" else 150, runs[mode]) for mode in ("a", "b", "partial", "killed")}
    directory = m.SpoolDirectory(case.root)
    killed_path = case.root / "spool" / (runs["killed"] + ".0000.jsonl")
    out = {}
    try:
        out["killed_producing"] = until(lambda: killed_path.exists() and any(r[2] == "complete" for r in m.read_records(killed_path)), 120)
        children["killed"].kill()
        for child in children.values():
            child.communicate(timeout=120)
    finally:
        for child in children.values():
            stop(child)
    out["exit"] = {mode: (child.returncode if mode != "killed" else ("signal" if child.returncode < 0 else child.returncode)) for mode, child in children.items()}
    by_run = {}
    for path in directory.spool_files():
        by_run.setdefault(m.segment_identity(path)[0], []).append(path)
    out["runs_found"] = sorted(by_run) == sorted(runs.values())
    summary = {}
    for mode, run in runs.items():
        statuses = [row[2] for path in by_run[run] for row in directory.read(path)]
        events = [row[4] for path in by_run[run] for row in directory.read(path) if row[2] == "complete"]
        summary[mode] = {"complete": statuses.count("complete") if mode != "killed" else None, "statuses_tail": statuses[-1], "other_statuses": sorted(set(statuses) - {"complete"}),
                         "indices_in_order": [e["i"] for e in events] == list(range(len(events))), "segments": len(by_run[run]) if mode != "killed" else None,
                         "total": len(statuses) if mode not in {"killed"} else None, "at_least_one_complete": len(events) >= 1}
    out["summary"] = summary
    out["closed_markers"] = {mode: directory.closed(run) for mode, run in runs.items()}
    out["alive_after_exit"] = {mode: directory.writer_alive(run) for mode, run in runs.items()}
    out["finished_with_retention_elapsed"] = {mode: directory.run_finished(run, now=time.time() + 8 * 86400) for mode, run in runs.items()}
    return out


def dead_writer_and_live_prune(case):
    m, name = case.m, case.api.name
    run = RUNS["a"]
    child = spawn(HOLD, name, case.root, run)
    out = {}
    try:
        out["written"] = child.stdout.readline().strip().decode()
        directory = m.SpoolDirectory(case.root)
        out["alive_while_the_child_lives"] = directory.writer_alive(run)
        [path] = directory.spool_files()
        directory.acknowledge(path, path.stat().st_size, 1)
        case.age(path, m.run_lock_path(case.root, run))
        now = time.time() + 8 * 86400
        out["live_child"] = {"finished": directory.run_finished(run, now=now), "prune": directory.prune(now=now), "segment_kept": path.exists(),
                             "lock_file_kept": m.run_lock_path(case.root, run).exists(), "reclaimable": directory.reclaimable(path)}
    finally:
        child.kill()
        child.wait(timeout=60)
        stop(child)
    out["released_by_the_os"] = until(lambda: not directory.writer_alive(run))
    out["dead_child"] = {"alive": directory.writer_alive(run), "finished": directory.run_finished(run, now=now), "reclaimable": directory.reclaimable(path),
                         "prune": directory.prune(now=now), "segment_gone": not path.exists(), "lock_file_gone": not m.run_lock_path(case.root, run).exists()}
    return out


def busy_lifecycle_lock(case):
    m = case.m
    stale = RUNS["a"]
    m.run_lock_path(case.root, stale).parent.mkdir(parents=True, exist_ok=True)
    m.run_lock_path(case.root, stale).touch()
    holder = spawn(LIFECYCLE_HOLDER, Path(m.lifecycle_lock(case.root).lock_file))
    saved = m.LIFECYCLE_TIMEOUT
    out = {}
    try:
        out["held"] = holder.stdout.readline().strip().decode()
        m.LIFECYCLE_TIMEOUT = 0.5
        directory = m.SpoolDirectory(case.root)
        out["alive_is_the_answer_when_busy"] = m.writer_alive(case.root, stale)
        out["prune_skips"] = directory.prune()
        out["stale_lock_kept"] = m.run_lock_path(case.root, stale).exists()
        spool = m.FileSpool(case.root, RUNS["b"], max_bytes=10000, fsync=False)
        out["writer_refused"] = case.call(spool.append, "event", {"x": 1})
        out["nothing_touched"] = {"spool_files": directory.spool_files(), "run_lock": m.run_lock_path(case.root, RUNS["b"]).exists(), "owns": spool.owns_run}
        out["reclaim_declines"] = directory.reclaim(case.root / "spool" / (stale + ".0000.jsonl"))
        spool_closed = m.FileSpool(case.root, RUNS["c"], max_bytes=10000, fsync=False)
        out["close_of_a_writer_that_never_registered"] = case.call(spool_closed.close)
    finally:
        m.LIFECYCLE_TIMEOUT = saved
        holder.kill()
        holder.wait(timeout=60)
        stop(holder)
    out["released"] = until(lambda: not m.writer_alive(case.root, stale))
    out["after_release"] = {"prune": directory.prune(), "stale_gone": not m.run_lock_path(case.root, stale).exists(), "append": case.call(spool.append, "event", {"x": 1}),
                            "owns": spool.owns_run}
    spool.close()
    return out


def close_while_the_lifecycle_lock_is_busy(case):
    """close() finishes unserialized when the lifecycle lock cannot be taken: the marker is still written and the run lock released."""
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=10000, fsync=False)
    spool.append("event", {"x": 1})
    holder = spawn(LIFECYCLE_HOLDER, Path(m.lifecycle_lock(case.root).lock_file))
    saved = m.LIFECYCLE_TIMEOUT
    out = {}
    try:
        out["held"] = holder.stdout.readline().strip().decode()
        m.LIFECYCLE_TIMEOUT = 0.3
        spool.close()
        out["closed"] = {"closed": spool.closed, "owns": spool.owns_run, "marker": stamped((case.root / "spool" / (RUNS["a"] + ".closed")).read_bytes())}
    finally:
        m.LIFECYCLE_TIMEOUT = saved
        holder.kill()
        holder.wait(timeout=60)
        stop(holder)
    out["run_lock_released"] = until(lambda: not m.writer_alive(case.root, RUNS["a"]))
    return out


class Barriers:
    """The M7 review5 barrier positions for the thread named 'first-writer': after the run lock file is opened but before the lock is acquired (call 2 of
    the non-blocking flock; call 1 is the lifecycle lock), and after the active segment is open but before the first record is written."""

    def __init__(self, spool, *, pause_at_run_lock=True):
        self.spool = spool
        self.locks = importlib.import_module("filelock._unix")
        self.lock_opened, self.allow_lock = threading.Event(), threading.Event()
        self.before_write, self.allow_write = threading.Event(), threading.Event()
        self.calls = 0
        original_lock, original_write = self.locks._lock_fd_nonblocking, os.write

        def paused_lock(fd):
            if threading.current_thread().name == "first-writer":
                self.calls += 1
                if (self.calls == 2) == pause_at_run_lock:
                    self.lock_opened.set()
                    assert self.allow_lock.wait(WAIT)
            return original_lock(fd)

        def paused_write(fd, data):
            if threading.current_thread().name == "first-writer" and fd == self.spool._descriptor:
                self.before_write.set()
                assert self.allow_write.wait(WAIT)
            return original_write(fd, data)

        self.originals = (original_lock, original_write)
        self.locks._lock_fd_nonblocking, os.write = paused_lock, paused_write

    def release_all(self):
        self.allow_lock.set()
        self.allow_write.set()

    def restore(self):
        self.locks._lock_fd_nonblocking, os.write = self.originals


def writer_thread(spool, out):
    def produce():
        try:
            out["offset"] = spool.append("event", {"x": 1})
        except BaseException as exc:  # noqa: BLE001 - the case reports whatever escaped
            out["error"] = type(exc).__name__
    return threading.Thread(target=produce, name="first-writer")


def in_thread(target, name):
    out = {}

    def run():
        out["result"] = target()
    thread = threading.Thread(target=run, name=name)
    thread.start()
    return thread, out


def barrier_gc_waits_for_a_registering_writer(case):
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=10000, fsync=False)
    directory = m.SpoolDirectory(case.root)
    barriers = Barriers(spool)
    out, produced = {}, {}
    writer = writer_thread(spool, produced)
    writer.start()
    try:
        out["lock_opened"] = barriers.lock_opened.wait(WAIT)
        gc, pruned = in_thread(directory.prune, "gc")
        gc.join(0.5)
        out["gc_blocked_while_registering"] = gc.is_alive()
        barriers.allow_lock.set()
        out["segment_open_before_write"] = barriers.before_write.wait(WAIT)
        gc.join(WAIT)
        out["gc_finished"] = not gc.is_alive()
        out["gc_result"] = pruned.get("result")
        out["active_segment_kept"] = spool.path.exists()
        out["writer_alive"] = directory.writer_alive(spool.process_run_id)
        barriers.allow_write.set()
        writer.join(WAIT)
        out["write"] = produced
        out["collectable_path"] = [case.rel(p) for p in directory.spool_files()]
        out["record"] = [(r["status"], r["event"]) for p in directory.spool_files() for r in rows(case, p)]
    finally:
        barriers.release_all()
        writer.join(WAIT)
        barriers.restore()
        spool.close()
    return out


def barrier_reclaim_waits_for_registration(case):
    m = case.m
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=10000, fsync=False)
    directory = m.SpoolDirectory(case.root)
    barriers = Barriers(spool)
    out, produced = {}, {}
    writer = writer_thread(spool, produced)
    writer.start()
    try:
        out["lock_opened"] = barriers.lock_opened.wait(WAIT)
        reclaim, result = in_thread(lambda: directory.reclaim(spool.path), "collector")
        reclaim.join(0.5)
        out["reclaim_blocked_while_registering"] = reclaim.is_alive()
        barriers.allow_lock.set()
        out["segment_open_before_write"] = barriers.before_write.wait(WAIT)
        reclaim.join(WAIT)
        out["reclaim_finished"] = not reclaim.is_alive()
        out["reclaim_result"] = result.get("result")
        out["active_segment_kept"] = spool.path.exists()
        barriers.allow_write.set()
        writer.join(WAIT)
        out["write"] = produced
        out["collectable_path"] = [case.rel(p) for p in directory.spool_files()]
    finally:
        barriers.release_all()
        writer.join(WAIT)
        barriers.restore()
        spool.close()
    return out


def barrier_gc_before_registration(case):
    m = case.m
    stale = RUNS["b"]
    m.run_lock_path(case.root, stale).parent.mkdir(parents=True, exist_ok=True)
    m.run_lock_path(case.root, stale).touch()
    spool = m.FileSpool(case.root, RUNS["a"], max_bytes=10000, fsync=False)
    directory = m.SpoolDirectory(case.root)
    barriers = Barriers(spool, pause_at_run_lock=False)
    out, produced = {}, {}
    writer = writer_thread(spool, produced)
    writer.start()
    try:
        out["about_to_take_the_lifecycle_lock"] = barriers.lock_opened.wait(WAIT)
        out["gc"] = directory.prune()
        out["stale_gone"] = not m.run_lock_path(case.root, stale).exists()
        out["writer_not_yet_known"] = spool.process_run_id not in directory.known_runs()
        barriers.allow_lock.set()
        out["segment_open_before_write"] = barriers.before_write.wait(WAIT)
        barriers.allow_write.set()
        writer.join(WAIT)
        out["write"] = produced
        out["collectable_path"] = [case.rel(p) for p in directory.spool_files()]
        out["alive"] = directory.writer_alive(spool.process_run_id)
    finally:
        barriers.release_all()
        writer.join(WAIT)
        barriers.restore()
        spool.close()
    return out


def memory_spool_still_equal(case):
    m = case.m
    line = len(m.encode_record("event", {"a": 1}))
    spool = m.MemorySpool(RUNS["a"], max_bytes=line + 5)
    out = {"first": spool.append("event", {"a": 1}), "second": case.call(spool.append, "event", {"a": 2}), "records": spool.records(), "size": spool.size(),
           "close": spool.close()}
    spool.fail_with = RuntimeError("down")
    out["fail_with"] = case.call(spool.append, "event", {"a": 3})
    return out


CASES = (definitions, names_and_codecs, append_read_rotation, bounds_and_ack, acknowledgements, partial_tail_and_corruption, atomic_writes, lifecycle_and_locks,
         directory_files, runs_ages_and_retention, prune_and_reclaim, health_alerts_terminations, real_child_processes, dead_writer_and_live_prune,
         busy_lifecycle_lock, close_while_the_lifecycle_lock_is_busy, barrier_gc_waits_for_a_registering_writer, barrier_reclaim_waits_for_registration,
         barrier_gc_before_registration, memory_spool_still_equal)


def run(api) -> dict:
    out = {}
    for case_fn in CASES:
        case = Case(api)
        try:
            out[case_fn.__name__] = case_fn(case)
        finally:
            case.close()
    return out

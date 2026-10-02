"""Shared S9 scenario steps (`observation.collector`): M7 `application/observations.py` `Collector`, `orphan_report` and `status_report` (INV-OBSERVATION-001).

Layer: harness (never shipped)

`api` carries the side's `Collector`, `Observer`, `MemoryDirectory`, `orphan_report`, `status_report`, `FileSpool`, `SpoolDirectory`, `encode_record`,
`validate` (the observation validator), `MemoryStore`, `ContractError`, `build_event`, `execution_identity`. Mirrors `tests/test_observations.py`, the collector
parts of `tests/test_observation_review{,2,3,4}.py` and of `tests/test_observation_boundaries.py`, all over real files in a per-case temporary directory, a
MemoryStore, the real validator, a fixed ticking clock, fixed run ids, a fixed host/pid and a caller-driven monotonic counter: every receipt id and `at` value is
therefore exact.

Declared nondeterministic fields, normalized HERE and never by the mask list: the temporary root (`<root>` in any text), the two wall-clock stamps the file
spool writes (`updated_at` of an acknowledgement and `closed_at` of a closed marker: each proven an ISO-8601 UTC instant and reported as `<utc-iso>`; the bytes
of those two file kinds are therefore taken OUT of every byte total, `runtime_directory_bytes` included), mtimes (aged files are set to a fixed epoch with
os.utime) and `orphan_report`'s `as_of` when `now` is not given (proven an ISO-8601 UTC instant). No process, network, thread or database.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import s9_file_spool  # the shared `stamped` (wall-clock proof) helper

AGED = 1577836800.0  # 2020-01-01T00:00:00Z
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"
BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts", "observation_collections", "observation_terminations")
RUNS = {name: f"{index:032x}" for index, name in enumerate(("a", "b", "c", "d", "e", "f", "g", "h"), start=0xC0)}


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


class Ticks:
    """A fixed clock that advances one second per read; its call count is part of what is characterized."""

    def __init__(self):
        self.reads = 0

    def __call__(self) -> str:
        value = (START + timedelta(seconds=self.reads)).isoformat()
        self.reads += 1
        return value


class Interceptor:
    """Store wrapper that fails selected writes or whole transactions (M7 tests' Interceptor); a harness-only fault boundary."""

    def __init__(self, store):
        self.store, self.fail_put, self.fail_transaction = store, None, None

    def transaction(self):
        import contextlib

        @contextlib.contextmanager
        def guarded():
            if self.fail_transaction is not None:
                raise self.fail_transaction
            with self.store.transaction() as tx:
                yield Intercepted(tx, self)
        return guarded()


class Intercepted:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if self.owner.fail_put is not None and self.owner.fail_put(bucket, body):
            raise OSError("injected sink failure " + CANARY)
        self.tx.put(bucket, key, body)


class Case:
    def __init__(self, api, name):
        self.api, self.name = api, name
        self.root = Path(tempfile.mkdtemp(prefix="s9-collector-")).resolve()
        self.obs = self.root / "obs"
        self.ticks, self.monotonic = Ticks(), [0.0]
        self.store = api.MemoryStore()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def text(self, value) -> str:
        return str(value).replace(str(self.root), "<root>")

    def call(self, fn, *args, **kwargs):
        try:
            return {"value": fn(*args, **kwargs)}
        except Exception as exc:  # the refusal is the characterized result
            return {"refused": type(exc).__name__, "message": self.text(exc)[:300]}

    def spool(self, run, *, max_bytes=1 << 20, segment_bytes=None):
        extra = {} if segment_bytes is None else {"segment_bytes": segment_bytes}
        return self.api.FileSpool(self.obs, RUNS[run], max_bytes=max_bytes, fsync=False, **extra)

    def observer(self, run="a", store=None, *, max_bytes=1 << 20, segment_bytes=None, spool=None, component="s9-collector", window=0):
        spool = spool or self.spool(run, max_bytes=max_bytes, segment_bytes=segment_bytes)
        return self.api.Observer(store if store is not None else self.store, spool, component=component, role=component,
                                 directory=self.api.SpoolDirectory(self.obs), host="fixture-host", pid=1, alert_window_seconds=window,
                                 clock=self.ticks, monotonic=lambda: self.monotonic[0])

    def directory(self):
        return self.api.SpoolDirectory(self.obs)

    def collector(self, store=None, observer=None, directory=None, **kwargs):
        return self.api.Collector(store if store is not None else self.store, directory or self.directory(), validate=self.api.validate,
                                  observer=observer, clock=self.ticks, **kwargs)

    def age_all(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                os.utime(path, (AGED, AGED))

    def stamped_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file() and p.name.endswith((".ack", ".closed")))

    def listing(self) -> dict:
        out = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            name = path.relative_to(self.root).as_posix()
            if name.endswith((".ack", ".closed")):
                out[name] = {"json": s9_file_spool.stamped(data)}
            else:
                out[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return out

    def rows(self, store=None, buckets=BUCKETS) -> dict:
        with (store or self.store).transaction() as tx:
            return {bucket: tx.scan(bucket) for bucket in buckets}

    def counts(self, store=None) -> dict:
        return {bucket: len(rows) for bucket, rows in self.rows(store).items()}

    def types(self, bucket, store=None) -> list:
        return sorted(r.get("event_type") or r.get("reason") or "?" for r in self.rows(store, (bucket,))[bucket])

    def acks(self, directory=None) -> dict:
        directory = directory or self.directory()
        return {p.name: directory.acknowledged(p) for p in directory.spool_files()}

    def leaked(self, *surfaces) -> bool:
        return any(CANARY in s for s in surfaces)


def emit_idle(observer, count, start=0):
    return [observer.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": start + i}) for i in range(count)]


def case_dedupe_and_conflict(case):
    """test_collector_deduplicates_redelivery_and_isolates_conflicting_redelivery: same id+content is one row, same id+other content is quarantined."""
    o = case.observer()
    event = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 5})
    directory = case.directory()
    [path] = directory.spool_files()
    collector = case.collector(observer=o)
    first = collector.collect()
    altered = {**event, "attributes": {"idle_seconds": 6}}
    with path.open("ab") as stream:
        stream.write(case.api.encode_record("event", event))
        stream.write(case.api.encode_record("event", altered))
    second = collector.collect()
    third = collector.collect()
    rows = case.rows()
    return {"first": first, "second": second, "third": third, "acknowledged": case.acks(directory),
            "observation_types": case.types("observations"), "stored_idle": rows["observations"][0]["attributes"] if rows["observations"] else None,
            "quarantine": rows["observation_quarantine"], "alert_types": case.types("observation_alerts"), "receipts": rows["observation_collections"],
            "events": rows["observations"], "alerts": rows["observation_alerts"], "listing": case.listing(), "clock_reads": case.ticks.reads}


def case_acknowledged_only_after_commit(case):
    """The acknowledgement follows the sink commit: a failed commit leaves offset 0 and no row, the retry stores and acknowledges once."""
    intercepted = Interceptor(case.store)
    o = case.observer(store=intercepted)
    emit_idle(o, 3)
    directory = case.directory()
    collector = case.collector(store=intercepted, observer=o, directory=directory)
    intercepted.fail_put = lambda bucket, body: bucket == "observation_collections"
    failed = collector.collect()
    during = {"acknowledged": case.acks(directory), "counts": case.counts(), "sink_state": o.sink_state, "last_defect": case.text(o.last_defect or "")[:200]}
    intercepted.fail_put = None
    recovered = collector.collect()
    again = collector.collect()
    plain = case.collector(store=intercepted, observer=None, directory=directory)
    intercepted.fail_transaction = OSError("sink down")
    no_observer = plain.collect()
    intercepted.fail_transaction = None
    return {"failed": failed, "during": during, "recovered": recovered, "again": again, "no_observer_outage": no_observer, "after": case.acks(directory),
            "counts": case.counts(), "sink_state": o.sink_state, "receipts": case.rows()["observation_collections"], "clock_reads": case.ticks.reads}


def case_audit_confirmation(case):
    """Audit records are confirmed only when the audit row is in the sink: one confirmed, one unconfirmed (its audit row is in another store)."""
    o = case.observer()
    with case.store.transaction() as tx:
        confirmed = o.audit(tx, "general.process_idle_exit", "observed", identity=["c", 1], attributes={"idle_seconds": 1})
    other = case.api.MemoryStore()
    with other.transaction() as tx:
        unconfirmed = o.audit(tx, "general.process_idle_exit", "observed", identity=["u", 1], attributes={"idle_seconds": 2})
    plain = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 3})
    receipt = case.collector(observer=o).collect()
    rows = case.rows()
    return {"receipt": receipt, "ids": {"confirmed": confirmed["event_id"], "unconfirmed": unconfirmed["event_id"], "plain": plain["event_id"]},
            "events": [{k: r[k] for k in ("event_id", "event_type", "record_kind", "audit_confirmed", "collected_at", "payload_hash", "spool", "authority")}
                       for r in rows["observations"]], "counts": case.counts(), "clock_reads": case.ticks.reads}


def case_sink_outage_and_alert_replay(case):
    """test_sink_outage_is_observed_locally_and_alerts_replay_after_recovery (L06)."""
    intercepted = Interceptor(case.store)
    o = case.observer(store=intercepted)
    intercepted.fail_transaction = OSError("connection refused " + CANARY)
    record = o.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    out = {"alert_notification": record["notification"], "sink_state": o.sink_state, "alerts_pending": o.counters["alerts_pending"]}
    out["emit_during_outage"] = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1}) is not None
    directory = case.directory()
    health = directory.read_health()
    out["health"] = [{"sink": h["sink"], "pending": h["pending_alerts"]} for h in health]
    collector = case.collector(store=intercepted, observer=o, directory=directory)
    out["failed"] = collector.collect()
    [path] = directory.spool_files()
    out["acknowledged_during_outage"] = directory.acknowledged(path)
    intercepted.fail_transaction = None
    out["recovered"] = collector.collect()
    out["after_recovery"] = {"sink_state": o.sink_state, "pending": len(o.pending_alerts), "pending_files": directory.read_pending_alerts()}
    out["alert_statuses"] = {a["event_type"]: a["notification"] for a in case.rows()["observation_alerts"]}
    out["next"] = collector.collect()
    out["recovery_events"] = case.types("observations")
    out["canary_leaked"] = case.leaked(json.dumps(directory.read_health()), path.read_text("utf-8", "replace") if path.exists() else "",
                                       json.dumps(case.rows(), default=str))
    out["counts"], out["clock_reads"] = case.counts(), case.ticks.reads
    return out


def case_outage_bounds_spool_and_recovery_resumes(case):
    """test_sink_outage_bounds_the_spool_and_recovery_resumes_without_loss_or_duplicates: a small spool, a dead sink, a lost acknowledgement."""
    intercepted = Interceptor(case.store)
    spool = case.spool("a", max_bytes=4000, segment_bytes=1000)
    o = case.observer(store=intercepted, spool=spool)
    collector = case.collector(store=intercepted, observer=o)
    for index in range(10):
        o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
        collector.collect()
    out = {"dropped_before": o.counters["dropped_spool_full"]}
    intercepted.fail_transaction = OSError("sink down")
    for index in range(10, 60):
        o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index})
        collector.collect()
    dropped = o.counters["dropped_spool_full"]
    out["outage"] = {"dropped": dropped, "unacknowledged_bytes": o.directory.unacknowledged_bytes(), "bounded": o.directory.unacknowledged_bytes() <= 4000,
                     "sink_state": o.sink_state, "pending_alerts": len(o.pending_alerts)}
    intercepted.fail_transaction = None
    (case.obs / "spool" / (RUNS["a"] + ".0000.ack")).unlink(missing_ok=True)  # a lost acknowledgement
    passes = []
    for _ in range(20):
        passes.append(collector.collect())
        if passes[-1]["records"] <= 1:
            break
    out["drain_passes"] = len(passes)
    out["last_drain"] = passes[-1]
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 999})
    out["resumed_without_new_drops"] = o.counters["dropped_spool_full"] == dropped
    out["final"] = collector.collect()
    numbers = sorted(r["attributes"]["idle_seconds"] for r in case.rows()["observations"] if r["event_type"] == "general.process_idle_exit")
    out["stored"] = {"count": len(numbers), "unique": len(numbers) == len(set(numbers)), "first_ten": numbers[:10], "has_999": 999 in numbers,
                     "digest": canonical_digest(numbers)}
    out["end"] = {"pending": len(o.pending_alerts), "sink_state": o.sink_state, "counters": dict(o.counters)}
    out["counts"], out["clock_reads"] = case.counts(), case.ticks.reads
    return out


def case_reclaim_and_rotation(case):
    """test_continuous_production_and_collection_never_saturates: a collector that keeps up reclaims every rotated segment; the closed run's last one too."""
    spool = case.spool("a", max_bytes=6000, segment_bytes=1500)
    o = case.observer(spool=spool)
    collector = case.collector(observer=o)
    reclaimed, receipts = 0, []
    for index in range(60):
        assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": index}) is not None
        if index % 5 == 4:
            receipts.append(collector.collect())
            reclaimed += receipts[-1]["reclaimed_segments"]
    out = {"reclaimed": reclaimed, "rotations": spool.rotations, "dropped": o.counters["dropped_spool_full"],
           "unacknowledged_bytes": o.directory.unacknowledged_bytes(), "spool_files": [p.name for p in o.directory.spool_files()],
           "receipts": receipts}
    collector.collect()
    seen = sorted(r["attributes"]["idle_seconds"] for r in case.rows()["observations"] if r["event_type"] == "general.process_idle_exit")
    out["seen_all"] = seen == list(range(60))
    o.close()
    out["closed"] = collector.collect()
    out["files_after_close"] = [p.name for p in o.directory.spool_files()]
    out["listing"], out["clock_reads"] = case.listing(), case.ticks.reads
    return out


def case_segment_10000(case):
    """test_segment_10000_is_collected_in_order: index 9999 -> 10000 stays ordered, collected and reclaimable."""
    spool = case.spool("a", max_bytes=100000, segment_bytes=600)
    spool.segment = 9999
    o = case.observer(spool=spool)
    emitted = emit_idle(o, 12)
    names = [p.name for p in o.directory.spool_files()]
    collector = case.collector()
    result = collector.collect()
    stored = sorted(r["attributes"]["idle_seconds"] for r in case.rows()["observations"])
    o.close()
    return {"emitted": sum(e is not None for e in emitted), "segment": spool.segment, "names": names, "result": result, "stored": stored,
            "after_close": collector.collect(), "files": [p.name for p in o.directory.spool_files()], "clock_reads": case.ticks.reads}


def case_truncated_tail(case):
    """A live writer's partial tail stays unconsumed; a finished run's tail is quarantined as corrupt and the segment is reclaimed."""
    o = case.observer()
    o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    with o.spool.path.open("ab") as stream:
        stream.write(b"deadbeef" * 8 + b" event {\"half\": tr")
    collector = case.collector(observer=None)
    live = collector.collect()
    out = {"live": live, "live_acknowledged": case.acks(), "live_files": [p.name for p in case.directory().spool_files()]}
    again = collector.collect()
    out["live_again"] = again
    o.close()  # the closed marker makes the tail final
    directory = case.directory()
    out["finished"] = collector.collect()
    out["after"] = {"files": [p.name for p in directory.spool_files()], "closed": directory.closed(RUNS["a"]), "health": directory.read_health()}
    out["quarantine"] = case.rows()["observation_quarantine"]
    out["counts"], out["clock_reads"] = case.counts(), case.ticks.reads
    return out


def case_dead_run_and_prune(case):
    """A crashed writer (descriptor closed, lock released, no marker): its record is collected and reclaimed; aged leftovers are pruned."""
    spool = case.spool("a", max_bytes=10000)
    spool.append("event", {"event": "before-crash"})
    os.close(spool._descriptor)
    spool._descriptor = None
    spool._lock.release()
    spool._lock = None
    o = case.observer("b")
    emit_idle(o, 2)
    o.close()
    case.age_all()
    directory = case.directory()
    collector = case.collector()
    before = sorted(directory.known_runs())
    result = collector.collect()
    return {"known_before": before, "result": result, "known_after": sorted(directory.known_runs()), "files": [p.name for p in directory.spool_files()],
            "quarantine": case.rows()["observation_quarantine"], "listing": case.listing(), "clock_reads": case.ticks.reads}


def case_prune_disabled_and_failing(case):
    """collect(prune=False) never prunes; a prune that raises is reported as zero pruned runs and files, never raised."""
    o = case.observer("a")
    emit_idle(o, 2)
    o.close()
    case.age_all()
    kept = case.collector().collect(prune=False)
    listing_kept = sorted(case.listing())

    class Failing(case.api.SpoolDirectory):
        def prune(self, *args, **kwargs):
            raise OSError("prune boom")

    failing = case.collector(directory=Failing(case.obs)).collect()
    pruned = case.collector().collect()
    return {"prune_false": kept, "listing_after_prune_false": listing_kept, "prune_raises": failing, "pruned": pruned, "listing_after": sorted(case.listing()),
            "clock_reads": case.ticks.reads}


def case_pending_alerts_only_replay(case):
    """test_pending_alerts_without_spool_records_replay_after_recovery: a 1-byte spool and a dead sink leave pending files only; a later collector replays them."""
    intercepted = Interceptor(case.store)
    first = case.observer("a", store=intercepted, spool=case.spool("a", max_bytes=1, segment_bytes=1))
    intercepted.fail_transaction = OSError("sink down")
    out = {"emit_refused": first.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1}) is None}
    debt = {r["event_id"] for r in first.pending_alerts}
    out["debt"] = {"pending": len(first.pending_alerts), "files": {k: len(v) for k, v in first.directory.read_pending_alerts().items()}}
    first.close()
    intercepted.fail_transaction = None
    second = case.observer("b", component="s9-collector-2", spool=case.spool("b", max_bytes=10000))
    collector = case.collector(observer=second)
    out["result"] = collector.collect()
    rows = {a["event_id"]: a for a in case.rows()["observation_alerts"]}
    out["replayed"] = {"all_stored": debt <= set(rows), "all_after_recovery": all(rows[i]["notification"]["status"] == "recorded_after_recovery" for i in debt),
                       "replayed_by": sorted({rows[i]["notification"]["replayed_by"] for i in debt})}
    out["after"] = {"inherited_pending": len(second.inherited_pending), "pending_files": second.directory.read_pending_alerts(),
                    "sink_state": second.sink_state}
    out["replay_without_observer"] = case.collector(observer=None).replay_pending_alerts()
    second.close()
    out["counts"], out["clock_reads"] = case.counts(), case.ticks.reads
    return out


def case_pending_replay_commit_failure(case):
    """A replay whose commit fails keeps the debt; a later collector replays it (the review3 concurrent-inheritor shape, single-threaded)."""
    intercepted = Interceptor(case.store)
    origin = case.observer("a", store=intercepted, spool=case.spool("a", max_bytes=1, segment_bytes=1))
    intercepted.fail_transaction = OSError("sink down")
    origin.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    debt = {r["event_id"] for r in origin.pending_alerts}
    origin.close()
    intercepted.fail_transaction = None
    directory = case.directory()
    b = case.observer("b", store=intercepted, component="s9-b")
    c = case.observer("c", store=intercepted, component="s9-c")
    intercepted.fail_put = lambda bucket, row: bucket == "observation_alerts"
    out = {"b_failed": case.collector(store=intercepted, observer=b, directory=directory).collect()}
    out["b_state"] = {"inherited_pending": len(b.inherited_pending), "files": sum(len(v) for v in directory.read_pending_alerts().values()),
                      "sink_state": b.sink_state}
    intercepted.fail_put = None
    c_result = case.collector(store=intercepted, observer=c, directory=directory).collect()
    out["c_replayed"] = {"alerts_replayed": c_result["alerts_replayed"], "covers_debt": c_result["alerts_replayed"] >= len(debt)}
    out["b_again"] = case.collector(store=intercepted, observer=b, directory=directory).collect()["alerts_replayed"]
    out["after"] = {"files": directory.read_pending_alerts(), "stored_debt": debt <= {a["event_id"] for a in case.rows()["observation_alerts"]}}
    out["counts"], out["clock_reads"] = case.counts(), case.ticks.reads
    return out


def case_refusals_and_quarantine(case):
    """Every non-insert outcome of one batch: corrupt line, business-message shape, schema refusal (valid and invalid event ids), a validator that raises."""
    api = case.api
    o = case.observer()
    good = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})
    spool = o.spool
    spool.append("event", {"who": "x", "what": "y", "how": "z"})
    spool.append("event", {"message_id": "m1", "type": "t"})
    spool.append("event", {"event_id": "ev-valid-id", "nope": 1})
    spool.append("event", {"event_id": "bad id with spaces", "nope": 1})
    spool.append("event", {"event_id": "x" * 201, "nope": 2})
    spool.append("event", {"event_id": 7})
    spool.append("event", good)  # a redelivery of the same record
    with spool.path.open("ab") as stream:
        stream.write(("0" * 64 + " event {}\n").encode())  # hash mismatch: a corrupt record
    receipt = case.collector().collect()
    out = {"receipt": receipt, "quarantine": sorted(({k: v for k, v in r.items() if k != "id"} for r in case.rows()["observation_quarantine"]),
                                                    key=lambda r: json.dumps(r, sort_keys=True, default=str)),
           "event_types": case.types("observations"), "counts": case.counts()}

    def boom(event):
        raise ValueError("validator boom")
    case2 = Case(api, "validator-raises")
    try:
        o2 = case2.observer()
        emit_idle(o2, 2)
        failing = api.Collector(case2.store, case2.directory(), validate=boom, observer=o2, clock=case2.ticks)
        out["validator_raises"] = {"receipt": failing.collect(), "acknowledged": case2.acks(), "counts": case2.counts(), "sink_state": o2.sink_state,
                                   "last_defect": case2.text(o2.last_defect or "")[:200]}
    finally:
        case2.close()
    out["clock_reads"] = case.ticks.reads
    return out


def case_batching(case):
    """Batch size bounds one pass's records; passes continue from the acknowledged offset in order, and a partially filled batch reclaims a rotated file."""
    spool = case.spool("a", max_bytes=1 << 20, segment_bytes=1200)
    o = case.observer(spool=spool)
    emit_idle(o, 9)
    passes = []
    collector = case.collector(batch=2)
    out = {"constructor_batch": collector.batch}
    for _ in range(12):
        passes.append(collector.collect(prune=False))
        if not passes[-1]["records"] and not passes[-1]["files"]:
            break
    out["passes"] = passes
    out["acknowledged"] = case.acks()
    out["stored"] = sorted(r["attributes"]["idle_seconds"] for r in case.rows()["observations"])
    out["clock_reads"] = case.ticks.reads
    return out


def case_constructor(case):
    api = case.api
    store, directory = case.store, case.directory()

    def make(**kwargs):
        c = api.Collector(store, directory, **kwargs)
        return {"batch": c.batch, "has_observer": c.observer is not None, "validate_is": c.validate is kwargs["validate"]}
    return {"default": case.call(make, validate=api.validate), "validate_missing": case.call(api.Collector, store, directory, validate=None),
            "validate_not_callable": case.call(api.Collector, store, directory, validate="x"),
            "batch_zero": case.call(api.Collector, store, directory, validate=api.validate, batch=0),
            "batch_negative": case.call(api.Collector, store, directory, validate=api.validate, batch=-1),
            "batch_bool": case.call(api.Collector, store, directory, validate=api.validate, batch=True),
            "batch_str": case.call(api.Collector, store, directory, validate=api.validate, batch="5"),
            "batch_float": case.call(api.Collector, store, directory, validate=api.validate, batch=2.0),
            "batch_one": case.call(make, validate=api.validate, batch=1),
            "positional_validate": case.call(api.Collector, store, directory, api.validate),
            "replay_without_observer": api.Collector(store, directory, validate=api.validate).replay_pending_alerts(),
            "collect_empty_directory": api.Collector(store, directory, validate=api.validate, clock=case.ticks).collect()}


def put_reservation(tx, rid, bucket, task_id, generation, attempt, owner="o1", **extra):
    tx.put("invocation_reservations", rid, {"id": rid, "status": "reserved", "bucket": bucket, "task_id": task_id, "generation": generation, "attempt": attempt,
                                           "owner": owner, "reserved_at": "2026-01-01T00:00:00+00:00", **extra})


def case_orphan_report(case):
    """orphan_report: a live heartbeat versus every way a reservation can lose its execution (no store mutation)."""
    api = case.api
    now = "2026-06-01T00:00:00+00:00"
    live_until, dead_until = "2999-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00"
    with case.store.transaction() as tx:
        tx.put("tasks", "alive", {"id": "alive", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o1", "lease_until": live_until})
        tx.put("tasks", "expired", {"id": "expired", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o1", "lease_until": dead_until})
        tx.put("tasks", "bad_lease", {"id": "bad_lease", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o1", "lease_until": "garbage"})
        tx.put("tasks", "no_lease", {"id": "no_lease", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o1"})
        tx.put("tasks", "other_owner", {"id": "other_owner", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o2", "lease_until": live_until})
        tx.put("tasks", "retry", {"id": "retry", "status": "retry", "generation": 1, "attempt": 1, "lease_owner": "o1", "lease_until": live_until})
        tx.put("tasks", "superseded", {"id": "superseded", "status": "running", "generation": 2, "attempt": 1, "lease_owner": "o1", "lease_until": live_until})
        tx.put("tasks", "next_attempt", {"id": "next_attempt", "status": "running", "generation": 1, "attempt": 2, "lease_owner": "o1", "lease_until": live_until})
        for index, task in enumerate(("alive", "expired", "bad_lease", "no_lease", "other_owner", "retry", "superseded", "next_attempt", "missing")):
            put_reservation(tx, f"r{index}", "tasks", task, 1, 1)
        put_reservation(tx, "settled", "tasks", "alive", 1, 1)
        tx.put("invocation_reservations", "settled", {**tx.get("invocation_reservations", "settled"), "status": "settled"})
    before = case.store.data.copy() if hasattr(case.store, "data") else None

    def report(now_arg):
        with case.store.transaction() as tx:
            return api.orphan_report(tx, now_arg) if now_arg is not None else api.orphan_report(tx)
    out = {"fixed_now": report(now), "naive_now": case.call(report, "2026-06-01T00:00:00"), "bad_now": case.call(report, "yesterday"),
           "non_string_now": case.call(report, 5)}
    empty_now = report("")  # a falsy `now` falls back to the wall clock: proven an ISO-8601 UTC instant, the rest is reported
    out["empty_now"] = {**empty_now, "as_of": "<utc-iso>" if datetime.fromisoformat(empty_now["as_of"]).utcoffset() == timedelta(0) else "<not-utc>"}
    default = report(None)
    moment = datetime.fromisoformat(default["as_of"])
    out["default_now"] = {"as_of_is_utc_iso": moment.utcoffset() == timedelta(0), "as_of": "<utc-iso>",
                          "orphans": [r["reservation_id"] for r in default["orphan"]], "in_progress": [r["reservation_id"] for r in default["in_progress"]],
                          "note": default["note"]}
    empty = api.MemoryStore()
    with empty.transaction() as tx:
        out["empty"] = api.orphan_report(tx, now)
    out["store_untouched"] = before is None or before == case.store.data
    return out


def case_status_report(case):
    """status_report with and without an observer, over a real directory with a live writer, a pending termination and a pending alert; and over MemoryDirectory."""
    intercepted = Interceptor(case.store)
    o = case.observer(store=intercepted)
    emit_idle(o, 3)
    lease = {"id": "t1", "generation": 1, "attempt": 1}
    o.record_termination(lease, reservation_id="r1", classification="unknown", stream_hash=None, error=RuntimeError("boom"), evidence_refs=("sha256:" + "a" * 64,))
    intercepted.fail_transaction = OSError("sink down")
    o.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    intercepted.fail_transaction = None
    directory = case.directory()
    collector = case.collector(observer=None, directory=directory)
    collected = collector.collect()
    with case.store.transaction() as tx:
        tx.put("observation_terminations", "sink-pending", {"record_id": "sink-pending", "status": "unconfirmed", "task_id": "t2"})
        tx.put("observation_terminations", "sink-closed", {"record_id": "sink-closed", "status": "resolved", "task_id": "t3"})
        tx.put("observation_alerts", "a1", {"event_id": "a1"})
        tx.put("tasks", "x", {"id": "x", "status": "running", "generation": 1, "attempt": 1, "lease_owner": "o1", "lease_until": "2999-01-01T00:00:00+00:00"})
        put_reservation(tx, "res", "tasks", "x", 1, 1)

    def normalized(report):
        out = dict(report)
        out["runtime_directory_bytes_without_stamps"] = out.pop("runtime_directory_bytes") - case.stamped_bytes()
        out["orphans"] = {**out["orphans"], "as_of": "<utc-iso>" if datetime.fromisoformat(out["orphans"]["as_of"]).utcoffset() == timedelta(0) else "<not-utc>"}
        return out
    with_observer = normalized(case.api.status_report(case.store, directory, o))
    without = normalized(case.api.status_report(case.store, directory))
    out = {"collected": collected, "with_observer": with_observer, "without_observer": without,
           "positional": case.call(lambda: normalized(case.api.status_report(case.store, directory, None))),
           "store_unchanged": case.counts()}
    memory = case.api.MemoryDirectory()
    out["memory_directory"] = normalized_memory(case.api.status_report(case.api.MemoryStore(), memory), case)
    out["memory_directory_observer"] = normalized_memory(case.api.status_report(case.store, memory, o), case)
    out["canary_leaked"] = case.leaked(json.dumps(with_observer, default=str))
    out["clock_reads"] = case.ticks.reads
    return out


def normalized_memory(report, case):
    out = dict(report)
    out["orphans"] = {**out["orphans"], "as_of": "<utc-iso>" if datetime.fromisoformat(out["orphans"]["as_of"]).utcoffset() == timedelta(0) else "<not-utc>"}
    return out


def case_canary(case):
    """test_canary_secret_never_reaches_spool_sink_health_or_status (L09): a credential-shaped canary is absent from every surface."""
    intercepted = Interceptor(case.store)
    o = case.observer(store=intercepted)
    o.emit("general.message_rejected", "blocked", reason_code="ContractError",
           attributes={"stream_entry_id": f"1-0 password={CANARY}", "error_type": f"token: {CANARY}", "dead_letter": True})
    intercepted.fail_put = lambda bucket, body: bucket == "observation_alerts"
    o.alert("spool_append_failed", "x", attributes={"error_type": f"api_key={CANARY}", "dropped": 1})
    intercepted.fail_put = None
    with case.store.transaction() as tx:
        o.audit(tx, "general.message_quarantined", "blocked", identity=["q", CANARY], attributes={"outbox_id": "m", "reason": f"secret={CANARY}", "quarantine_id": "q"})
    directory = case.directory()
    receipt = case.collector(store=intercepted, observer=o, directory=directory).collect()
    surfaces = [p.read_text("utf-8", "replace") for p in directory.spool_files()]
    surfaces.append(json.dumps(directory.read_health()))
    surfaces.append(json.dumps(case.api.status_report(case.store, directory, o), default=str))
    surfaces.append(json.dumps(case.rows(), default=str))
    return {"receipt": receipt, "leaked": case.leaked(*surfaces), "alerts_pending": o.counters["alerts_pending"], "last_defect_redacted": bool(o.last_defect) and "message_sha256=" in o.last_defect,
            "counts": case.counts(), "clock_reads": case.ticks.reads}


CASES = (case_dedupe_and_conflict, case_acknowledged_only_after_commit, case_audit_confirmation, case_sink_outage_and_alert_replay,
         case_outage_bounds_spool_and_recovery_resumes, case_reclaim_and_rotation, case_segment_10000, case_truncated_tail, case_dead_run_and_prune,
         case_prune_disabled_and_failing, case_pending_alerts_only_replay, case_pending_replay_commit_failure, case_refusals_and_quarantine, case_batching,
         case_constructor, case_orphan_report, case_status_report, case_canary)


def run(api) -> dict:
    out = {}
    for fn in CASES:
        case = Case(api, fn.__name__)
        try:
            out[fn.__name__.removeprefix("case_")] = fn(case)
        finally:
            case.close()
    return out

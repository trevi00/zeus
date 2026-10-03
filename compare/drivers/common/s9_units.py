"""Shared S9 scenario steps (`effects.s9_units`): the §2.9 transaction units of the observation write side, observed through the S0
recorder (DESIGN-s9-units "Design v1"; REBUILD-DESIGN-v2 §2.9; INV-OBSERVATION-001), over the MemoryStore, and (`effects.s9_units.pg`) over
each side's PostgresStore. The S8 form (`s8_units`, `s7_units`, `s6_units`) applied to S9.

Units (M7 names; the target's V9 homes keep each one whole):
- `Collector.collect` sink batch (U-1; `application/observations.py:764-836`, `_sink :838`): ONE transaction per spool batch: the
  `observations` inserts (absent ids only), the quarantine rows and the conflict alert (`observer.alert(tx=tx)`); then the
  `observation_collections` receipt; then `observer._flush_pending(tx)`; the receipt is its last write unless alerts were pending.
  The spool `directory.acknowledge` and `reclaim` (file writes) follow the commit, at depth 0;
- `Observer._record_alert`, own-sink path (U-2; `:414-432`, `tx=None`): ONE transaction: the alert row, then `_flush_pending(sink)`;
  a failure keeps the record in `pending_alerts` and `_persist_pending` writes the pending file (`directory.write_pending_alerts`),
  at depth 0;
- `Observer.resolve_termination` (U-3; `:688-721`): ONE transaction: the termination row set to `resolved`, then the
  `development.reconciliation_resolved` audit in `observation_audit` (the last write); the local file is finalized
  (`directory.resolve_termination`) after the commit, at depth 0.

Discriminators:
- **(a)** a failure injected at the unit's LAST write (`s6_units.FaultStore`) leaves nothing of the unit: U-1 at the receipt put (no
  observations, no `directory.acknowledge`, the spool offset unchanged, `sink_failures` 1); U-2 at the alert put (False; the record
  pending, the pending file written); U-3 at the audit put (the termination row unchanged, the local file not finalized);
- **(b)** a stale writer commits nothing: U-1 a rival Collector over a COPY of the same spool file commits the batch between this
  pass's read and its unit (every record is then a duplicate: this pass puts no `observations` row); U-2 is
  `{"not_applicable": ...}` naming `:376-412` (an alert is keyed by its own event id: no owner or fence); U-3 a second Observer on
  the backend store resolves the termination with a DIFFERENT decision between this call's local read and its transaction (refused,
  nothing written by this call);
- **(c)** a same-key replay adds no authority write: U-1 a replay after success finds duplicates and puts no row, a replay after a
  failed unit inserts once; U-2 a repeat `(kind, key)` inside the window is suppressed with no second row, a repeat after the failed
  unit also flushes the pending record; U-3 the same decision redelivered writes nothing (`reconciliation_redelivered` +1) and, when
  the first call was interrupted after the commit, only finalizes the local file;
- **(d)** the file-system effects (`directory.acknowledge`, `reclaim`, `write_pending_alerts`, `resolve_termination`) are entered at
  transaction depth 0 (the `effects` list of every result).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `Collector`, `Observer`, `FileSpool`, `SpoolDirectory`,
`encode_record`, `validate`, `ContractError`, plus `backend(name)` (`.store`, `.rows()`, `.drop()`), `reset()` and `recording(store)`
(the S0 RecordingStore). The store of every case is the recorded, fault-injectable `s6_units.FaultStore`; the directory is the real
`SpoolDirectory` over a per-case temporary root, behind a proxy that records its four file-writing calls as effects and runs one-shot
hooks (the stale writer). A second controller (the rival or the mover) acts on the backend's own store, outside the recorder. The
clock is the S9 collector world's ticking one (its read count is part of what is characterized), the host and pid are fixed and
the monotonic counter is caller-driven, so every id and `at` value is exact: no mask is needed. The compared results are the unit
outcomes, the durable writes (bucket and status), the recorder violations, the effect depths, the digests of the durable rows that
changed, and the counts and states read back from the backend and the directory.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import s7_units as S7
import s9_collector as C

NOT_APPLICABLE = {
    "record_alert_b": {"not_applicable": "M7 application/observations.py:376-412 builds the alert from (kind, key) and keys its row by "
                                         "its own event id: no owner token, fence or version is read, so no writer can be stale"}}
EFFECTS = ("acknowledge", "reclaim", "write_pending_alerts", "resolve_termination")
LEASE = {"id": "t1", "generation": 1, "attempt": 1}


class Directory:
    """LABELLED. The real `SpoolDirectory` with its four file-writing calls recorded as external effects (at the transaction
    depth they are entered), a one-shot failure per call (`case.fails`) and the one-shot hooks of `case.hooks`: `read` runs when
    the record iterator is exhausted (the Collector's read is over, its unit not yet open) and `pending_terminations` after the
    local read returns."""

    def __init__(self, case, inner):
        self._case, self.inner = case, inner

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        case = self._case
        if name in EFFECTS:
            def effect(*args, **kwargs):
                case.recorder.effect("directory." + name)
                failure = case.fails.pop(name, None)
                if failure is not None:
                    raise failure
                return attr(*args, **kwargs)
            return effect
        if name == "read":
            def read(*args, **kwargs):
                yield from attr(*args, **kwargs)
                hook = case.hooks.pop("read", None)
                if hook is not None:
                    hook()
            return read
        if name == "pending_terminations":
            def pending(*args, **kwargs):
                out = attr(*args, **kwargs)
                hook = case.hooks.pop("pending_terminations", None)
                if hook is not None:
                    hook()
                return out
            return pending
        return attr


class Case(S7.Case):
    """One fresh recorded, fault-injectable store (`s7_units.Case`), a per-case temporary root with the real spool directory, the
    ticking clock and the changed rows' digests."""

    def __init__(self, api):
        super().__init__(api)
        self.root = Path(tempfile.mkdtemp(prefix="s9-units-")).resolve()
        self.obs = self.root / "obs"
        self.ticks, self.monotonic, self.fails = C.Ticks(), [0.0], {}
        self.directory = Directory(self, api.SpoolDirectory(self.obs))

    def result(self, outcome, **extra):
        changed = {(b, k): d for b, k, _, d in self.backend.rows() if self.before.get((b, k)) != d}
        try:
            return super().result(outcome, changed_digests=sorted([b, k, d] for (b, k), d in changed.items()), **extra)
        finally:
            shutil.rmtree(self.root, ignore_errors=True)

    def text(self, value) -> str:
        return str(value).replace(str(self.root), "<root>")

    def call(self, fn, *args, **kwargs):
        try:
            return {"ok": True, "value": fn(*args, **kwargs)}
        except Exception as exc:  # the refusal is the characterized result
            return {"refused": type(exc).__name__, "message": self.text(exc)[:200]}

    def observer(self, run="a", *, store=None, directory=None, window=0):
        spool = self.api.FileSpool(self.obs, C.RUNS[run], max_bytes=1 << 20, fsync=False)
        return self.api.Observer(store if store is not None else self.store, spool, component="s9-units", role="s9-units",
                                 directory=directory or self.directory, host="fixture-host", pid=1, alert_window_seconds=window,
                                 clock=self.ticks, monotonic=lambda: self.monotonic[0])

    def collector(self, observer=None):
        return self.api.Collector(self.store, self.directory, validate=self.api.validate, observer=observer, clock=self.ticks)

    def rival(self, fn):
        """A second controller acts on the backend's own store (outside the recorder); the call that follows shows it."""
        def move():
            fn(self.backend.store)
        return self.mover(move)

    def scan(self, *buckets):
        with self.backend.store.transaction() as tx:
            return {bucket: tx.scan(bucket) for bucket in buckets}


def acknowledged(case):
    return {p.name: case.directory.acknowledged(p) for p in case.directory.spool_files()}


def counted(case):
    return {bucket: len(rows) for bucket, rows in case.scan(*C.BUCKETS).items()}


def kinds(case, bucket):
    return sorted(r.get("event_type") or r.get("reason") or r.get("status") or "?" for r in case.scan(bucket)[bucket])


# ---- unit 1: Collector.collect sink batch ---------------------------------------------------------------------------------
def collection(api, variant):
    case = Case(api)
    o = case.observer()
    events = C.emit_idle(o, 3)
    # the success, stale and replay-after-success cases collect without an observer: the pass then emits nothing of its own
    # into the spool, so a replay shows only the duplicates
    observed = variant in ("a_failure_at_receipt", "a_failure_at_receipt_conflict", "c_replay_after_failure")
    collector = case.collector(o if observed else None)
    [path] = case.directory.spool_files()

    def append(*bodies):
        with path.open("ab") as stream:
            for body in bodies:
                stream.write(api.encode_record("event", body))

    if variant == "a_failure_at_receipt_conflict":
        collector.collect()
        altered = {**events[0], "attributes": {"idle_seconds": 99}}
        append(altered, *C.emit_idle(o, 1, start=10))
    case.since()
    if variant in ("a_failure_at_receipt", "a_failure_at_receipt_conflict", "c_replay_after_failure"):
        case.hooks["collect"] = case.arm(C.BUCKETS[4])   # observation_collections: the receipt put
    elif variant == "b_rival_committed_first":
        def rival(store):
            copy = case.root / "rival"
            shutil.copytree(case.obs, copy)
            api.Collector(store, api.SpoolDirectory(copy), validate=api.validate, observer=None, clock=C.Ticks()).collect()
        case.hooks["read"] = case.rival(rival)

    def collect_once():
        hook = case.hooks.pop("collect", None)
        if hook is not None:
            hook()
        return case.call(collector.collect)

    out = collect_once()
    extra = {"counters": dict(o.counters) if observed else None, "sink_state": o.sink_state if observed else None}
    if variant == "c_replay_after_failure":
        # the unit failed at its receipt and left nothing: the same spool is collected once, each event inserted once
        first, extra["first_acknowledged"] = out, acknowledged(case)
        case.since()
        out = collect_once()
        extra["first"] = first
    elif variant == "c_replay_after_success":
        first = out
        append(*events)
        case.since()
        out = collect_once()
        extra["first"] = first
    return case.result(out, acknowledged=acknowledged(case), counts=counted(case), observation_ids=len(case.scan("observations")["observations"]),
                       quarantine=kinds(case, "observation_quarantine"), alerts=kinds(case, "observation_alerts"),
                       last_defect=case.text(o.last_defect or "")[:120], **extra)


# ---- unit 2: Observer._record_alert (own sink) ----------------------------------------------------------------------------
ALERT = {"error_type": "X", "dropped": 1}


def alert_unit(api, variant):
    case = Case(api)
    o = case.observer(window=300 if variant.startswith("c_repeat") else 0)
    case.since()
    if variant in ("a_failure_at_alert_row", "c_replay_after_failure"):
        case.store.arm("observation_alerts")   # the alert row is the unit's first and, with nothing pending, last write

    def alert_once():
        return case.call(o.alert, "spool_append_failed", "k1", attributes=dict(ALERT))

    out = alert_once()
    extra = {}
    if variant == "c_repeat_in_window":
        extra["first"], case.monotonic[0] = out, 10.0
        case.since()
        out = alert_once()
    elif variant == "c_repeat_after_window":
        extra["first"], case.monotonic[0] = out, 400.0
        case.since()
        out = alert_once()
    elif variant == "c_replay_after_failure":
        # the failed unit left the record pending: the repeat's own transaction writes its row, then flushes the pending record
        extra["first"] = out
        extra["first_pending"] = [r["event_id"] for r in o.pending_alerts]
        case.since()
        out = alert_once()
    stored = case.scan("observation_alerts")["observation_alerts"]
    extra.update({"counters": dict(o.counters), "sink_state": o.sink_state,
                  "stored": sorted([r["event_type"], r["notification"]["status"], r["event_id"]] for r in stored),
                  "pending": [r["event_id"] for r in o.pending_alerts],
                  "pending_file": {run: [r["event_id"] for r in rows] for run, rows in case.directory.read_pending_alerts().items()}})
    if variant.startswith("b_"):
        extra.update(NOT_APPLICABLE["record_alert_b"])
    return case.result(out, **extra)


# ---- unit 3: Observer.resolve_termination ----------------------------------------------------------------------------------
def termination(api, variant):
    case = Case(api)
    o = case.observer()
    record_id = o.record_termination(LEASE, reservation_id="r1", classification="unknown", stream_hash=None,
                                     error=RuntimeError("boom"))
    case.since()
    if variant == "a_failure_at_audit":
        case.hooks["resolve"] = case.arm("observation_audit")   # the audit row is the unit's last write
    elif variant == "b_mover_resolved_different":
        def mover(store):
            other = case.observer("b", store=store, directory=api.SpoolDirectory(case.obs))
            other.resolve_termination(record_id, resolution="discard", operator="op-2", reason="moved")
        case.hooks["pending_terminations"] = case.rival(mover)
    elif variant == "c_redelivered_after_interrupted_finalize":
        case.fails["resolve_termination"] = OSError("interrupted after the commit")

    def resolve_once():
        hook = case.hooks.pop("resolve", None)
        if hook is not None:
            hook()
        return case.call(o.resolve_termination, record_id, resolution="rerun", operator="op-1", reason="checked")

    out = resolve_once()
    extra = {}
    if variant.startswith("c_redelivered"):
        extra["first"] = out
        extra["first_pending"] = [r["record_id"] for r in case.directory.inner.pending_terminations()]
        case.since()
        out = resolve_once()
    row = case.scan("observation_terminations")["observation_terminations"]
    extra.update({"termination": [[r["record_id"], r["status"], (r.get("resolution") or {}).get("resolution"),
                                   (r.get("resolution") or {}).get("operator")] for r in row],
                  "audits": kinds(case, "observation_audit"),
                  "pending_local": [r["record_id"] for r in case.directory.inner.pending_terminations()],
                  "counters": dict(o.counters)})
    return case.result(out, **extra)


# ---- the run ----------------------------------------------------------------------------------------------------------------
def run(api) -> dict:
    return {
        "collect": {v: collection(api, v) for v in (
            "success", "a_failure_at_receipt", "a_failure_at_receipt_conflict", "b_rival_committed_first",
            "c_replay_after_success", "c_replay_after_failure")},
        "record_alert": {v: alert_unit(api, v) for v in (
            "success", "a_failure_at_alert_row", "b_not_applicable", "c_repeat_in_window", "c_repeat_after_window",
            "c_replay_after_failure")},
        "resolve_termination": {v: termination(api, v) for v in (
            "success", "a_failure_at_audit", "b_mover_resolved_different", "c_redelivered_after_success",
            "c_redelivered_after_interrupted_finalize")}}

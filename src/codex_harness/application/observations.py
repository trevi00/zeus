"""Observer, collector and reports for the three-category log contract (INV-OBSERVATION-001).

Two write paths, deliberately different in what they may do:

* `Observer.audit(tx, ...)` records a mandatory transition inside the caller's PostgreSQL
  transaction as an append-only `observation_audit` row. It raises on a refused event, so the
  business transition (an invocation reservation, a settlement, an outbox publish) does not
  commit without its audit record. Same id with the same content is a redelivery; same id with
  different content is isolated in `observation_quarantine` with an alert, never overwritten.
* `Observer.emit(...)` records a diagnostic event to the bounded durable spool and never raises:
  a full or failing spool is counted, written to the protected local health record, and alerted
  (rate limited), instead of being dropped silently or allowed to block the execution path.

The sequence number is bound to the spool append: it advances only when the record is durable,
and a process restart starts a new process_run_id namespace. `Collector` moves spool records
into PostgreSQL, deduplicates by event id and content hash, quarantines corrupt lines and
conflicts, leaves a truncated tail unconsumed, and acknowledges an offset only after the sink
transaction committed. Post-execution termination evidence (`record_termination`) is the local
minimal record that survives a PostgreSQL failure after the provider already ran; the executor
refuses to start a provider for a task that has one pending, so a lost settlement never turns
into a blind re-execution.
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from collections import Counter
from datetime import datetime

from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.domain.observation import (
    build_event,
    content_hash,
    execution_identity,
    is_business_message,
    lease_identity,
    redact_text,
)
from codex_harness.domain.policy import POLICY
from codex_harness.ports import SpoolFull

AUDIT_BUCKET = "observation_audit"
EVENT_BUCKET = "observations"
QUARANTINE_BUCKET = "observation_quarantine"
ALERT_BUCKET = "observation_alerts"
COLLECTION_BUCKET = "observation_collections"
TERMINATION_BUCKET = "observation_terminations"
BUCKETS = (AUDIT_BUCKET, EVENT_BUCKET, QUARANTINE_BUCKET, ALERT_BUCKET, COLLECTION_BUCKET, TERMINATION_BUCKET)
PENDING_ALERT_LIMIT = 100


class ReconciliationRequired(RuntimeError):
    """A previous attempt ran the provider but its outcome was never recorded; do not run it again."""

    def __init__(self, task_id: str, records: list[dict]):
        super().__init__(f"task {task_id} has {len(records)} termination record(s) pending reconciliation")
        self.task_id, self.records = task_id, records


class PostExecutionRecordFailure(RuntimeError):
    """The provider already ran; recording its settlement failed. Termination evidence was spooled."""

    def __init__(self, record_id: str, cause: BaseException):
        super().__init__(f"settlement not recorded ({type(cause).__name__}); termination record {record_id}")
        self.record_id, self.cause = record_id, cause


class MemoryDirectory:
    """Unit-boundary stand-in for SpoolDirectory: same operations, in memory."""

    def __init__(self):
        self.health: dict[str, dict] = {}
        self.terminations: dict[str, dict] = {}
        self.resolved: dict[str, dict] = {}

    def write_health(self, process_run_id, record):
        self.health[process_run_id] = record

    def read_health(self):
        return [self.health[key] for key in sorted(self.health)]

    def record_termination(self, record_id, record):
        require(record_id not in self.terminations, "Termination record exists")
        self.terminations[record_id] = record

    def pending_terminations(self, task_id=None):
        return [row for key, row in sorted(self.terminations.items()) if task_id is None or row["task_id"] == task_id]

    def resolve_termination(self, record_id, resolution):
        require(record_id in self.terminations, "Unknown termination record")
        resolved = {**self.terminations.pop(record_id), "resolution": resolution}
        self.resolved[record_id] = resolved
        return resolved

    def spool_files(self):
        return []

    def read(self, path, offset=0):
        return iter(())

    def acknowledged(self, path):
        return 0

    def acknowledge(self, path, offset, consumed):
        return None


def _error_text(error: BaseException) -> str:
    """Name the error without repeating its message: a foreign message may carry a secret.

    Contract errors are Zeus's own wording (attribute names, never values) and are kept, redacted.
    Every other message is replaced by its digest so an operator can match it against a private
    log without the observation surfaces ever carrying the text.
    """
    if isinstance(error, ContractError):
        text, _ = redact_text(type(error).__name__ + ": " + str(error))
        return text[:300]
    return type(error).__name__ + ": message_sha256=" + digest(str(error))[:16]


class Observer:
    def __init__(self, store, spool, *, component: str, directory, role: str | None = None,
                 host: str | None = None, pid: int | None = None, org=None,
                 alert_window_seconds: int = POLICY.observation_alert_window_seconds, clock=utcnow,
                 monotonic=time.monotonic):
        require(type(component) is str and bool(component), "Observer component required")
        self.store, self.spool, self.directory, self.org = store, spool, directory, org
        self.process_run_id = spool.process_run_id
        self.component, self.role = component, role
        self.source = {"component": component, "host": host if host is not None else platform.node() or None,
                       "pid": pid if pid is not None else os.getpid()}
        self.clock, self.monotonic = clock, monotonic
        self.alert_window_seconds = alert_window_seconds
        self._lock = threading.RLock()
        self._next = 1
        self.counters: Counter = Counter()
        self._alerts: dict[tuple, tuple] = {}
        self.pending_alerts: list[dict] = []
        self.last_defect: str | None = None
        self.sink_state = "unknown"

    # ---- identity helpers -------------------------------------------------------------------
    def system(self, *, revision=None, role=None) -> dict:
        return execution_identity("system", process_run_id=self.process_run_id,
                                  role=role if role is not None else self.role, revision=revision)

    def for_lease(self, lease: dict, *, provider=None, invocation_id=None, session_id=None, revision=None,
                  role=None) -> dict:
        actor = role or lease.get("agent") or lease.get("actor") or self.role
        return lease_identity(lease, process_run_id=self.process_run_id, role=actor, provider=provider,
                              session_id=session_id, invocation_id=invocation_id, revision=revision)

    @staticmethod
    def correlation(lease: dict | None) -> str | None:
        message = (lease or {}).get("message")
        value = message.get("correlation_id") if isinstance(message, dict) else None
        return value if type(value) is str and value else None

    # ---- diagnostic path (never raises) -------------------------------------------------------
    def emit(self, event_type: str, outcome: str, *, execution=None, correlation_id=None, causation_id=None,
             occurred_at=None, reason_code=None, evidence_refs=(), attributes=None, severity="info",
             identity=None) -> dict | None:
        with self._lock:
            sequence = {"process_run_id": self.process_run_id, "number": self._next, "basis": "spool_append"}
            try:
                event = build_event(event_type=event_type, outcome=outcome, execution=execution or self.system(),
                                    sequence=sequence, observed_at=self.clock(), source=self.source,
                                    occurred_at=occurred_at, correlation_id=correlation_id,
                                    causation_id=causation_id, reason_code=reason_code,
                                    evidence_refs=evidence_refs, attributes=attributes, severity=severity,
                                    identity=identity)
            except ContractError as exc:
                self._refused(event_type, exc)
                return None
            if not self._append("event", event):
                return None
            self._next += 1
            self.counters["emitted"] += 1
            return event

    def _append(self, kind: str, event: dict) -> bool:
        try:
            self.spool.append(kind, event)
            return True
        except SpoolFull as exc:
            self.counters["dropped_spool_full"] += 1
            self.last_defect = _error_text(exc)
            self._health()
            self.alert("spool_saturated", self.process_run_id, severity="error", spool=False,
                       attributes={"bytes": getattr(self.spool, "size", lambda: 0)() if hasattr(self.spool, "size") else 0,
                                   "limit_bytes": int(getattr(self.spool, "max_bytes", 0)),
                                   "dropped": int(self.counters["dropped_spool_full"])})
        except OSError as exc:
            self.counters["spool_failures"] += 1
            self.last_defect = _error_text(exc)
            self._health()
            self.alert("spool_append_failed", type(exc).__name__, severity="error", spool=False,
                       attributes={"error_type": type(exc).__name__, "dropped": int(self.counters["spool_failures"])})
        return False

    def _refused(self, event_type, exc):
        self.counters["refused"] += 1
        self.last_defect = _error_text(exc)
        self._health()
        # The refusal itself is evidence; it carries the defect text, never the refused payload.
        with self._lock:
            sequence = {"process_run_id": self.process_run_id, "number": self._next, "basis": "spool_append"}
            try:
                event = build_event(event_type="operations.observation_refused", outcome="failed",
                                    execution=self.system(), sequence=sequence, observed_at=self.clock(),
                                    source=self.source, severity="warning",
                                    attributes={"refused_event_type": str(event_type)[:200],
                                                "defect": self.last_defect})
            except ContractError:
                return
            if self._append("event", event):
                self._next += 1

    # ---- mandatory path (raises) ----------------------------------------------------------------
    def audit(self, tx, event_type: str, outcome: str, *, identity, execution=None, correlation_id=None,
              causation_id=None, occurred_at=None, reason_code=None, evidence_refs=(), attributes=None,
              severity="info") -> dict:
        """Append-only audit row in the caller's transaction; refused events raise before commit."""
        require(isinstance(identity, (list, tuple)) and bool(identity), "Audit events need an explicit identity")
        with self._lock:
            sequence = {"process_run_id": self.process_run_id, "number": self._next, "basis": "spool_append"}
            event = build_event(event_type=event_type, outcome=outcome, execution=execution or self.system(),
                                sequence=sequence, observed_at=self.clock(), source=self.source,
                                occurred_at=occurred_at, correlation_id=correlation_id, causation_id=causation_id,
                                reason_code=reason_code, evidence_refs=evidence_refs, attributes=attributes,
                                severity=severity, identity=identity)
            if self._append("audit", event):
                self._next += 1
            else:
                # The audit still commits with the transaction; only its local order is unassigned.
                event["sequence"] = {"process_run_id": self.process_run_id, "number": None, "basis": "unassigned"}
                self.counters["sequence_unassigned"] += 1
        digest_value = content_hash(event)
        existing = tx.get(AUDIT_BUCKET, event["event_id"])
        if existing is None:
            tx.put(AUDIT_BUCKET, event["event_id"], {**event, "payload_hash": digest_value,
                                                     "authority": "informational_only"})
            self.counters["audited"] += 1
            return event
        if existing.get("payload_hash") == digest_value:
            self.counters["audit_redelivered"] += 1
            return existing
        quarantine_id = digest(["observation_conflict", event["event_id"], digest_value])
        if tx.get(QUARANTINE_BUCKET, quarantine_id) is None:
            tx.put(QUARANTINE_BUCKET, quarantine_id, {"id": quarantine_id, "event_id": event["event_id"],
                   "reason": "conflicting_content", "expected_hash": existing.get("payload_hash"),
                   "observed_hash": digest_value, "source": event, "at": self.clock()})
        self.counters["audit_conflicts"] += 1
        self.alert("observation_conflict", event["event_id"], severity="error", tx=tx,
                   attributes={"conflicting_event_id": event["event_id"], "expected_hash": existing.get("payload_hash"),
                               "observed_hash": digest_value, "quarantine_id": quarantine_id})
        return {"status": "quarantined", "quarantine_id": quarantine_id, "event_id": event["event_id"]}

    def audit_system(self, tx, event_type: str, outcome: str, *, identity, attributes=None, correlation_id=None,
                     causation_id=None, severity="info", reason_code=None, evidence_refs=()) -> dict:
        return self.audit(tx, event_type, outcome, identity=identity, execution=self.system(), attributes=attributes,
                          correlation_id=correlation_id, causation_id=causation_id, severity=severity,
                          reason_code=reason_code, evidence_refs=evidence_refs)

    # ---- alerts and health ------------------------------------------------------------------------
    def alert(self, kind: str, key: str, *, attributes: dict, severity: str = "warning", tx=None,
              spool: bool = True) -> dict | None:
        """One alert per (kind, key) per window; repeats are counted as suppressed, not sent."""
        now = self.monotonic()
        with self._lock:
            last, suppressed = self._alerts.get((kind, key), (None, 0))
            if last is not None and now - last < self.alert_window_seconds:
                self._alerts[(kind, key)] = (last, suppressed + 1)
                self.counters["alerts_suppressed"] += 1
                return None
            self._alerts[(kind, key)] = (now, 0)
            at = self.clock()
            try:
                event = build_event(event_type="operations." + kind, outcome="observed", execution=self.system(),
                                    sequence={"process_run_id": self.process_run_id, "number": None,
                                              "basis": "unassigned"},
                                    observed_at=at, source=self.source, severity=severity, attributes=attributes,
                                    identity=["alert", kind, key, at])
            except ContractError as exc:
                self._refused("operations." + kind, exc)
                return None
        record = {**event, "payload_hash": content_hash(event), "suppressed_before": suppressed,
                  "notification": {"status": "pending", "channel": None}}
        if spool:
            self._append("event", event)
        if self._record_alert(record, tx):
            record["notification"] = {"status": "recorded", "channel": "postgres:" + ALERT_BUCKET}
            self.counters["alerts_recorded"] += 1
        else:
            self.counters["alerts_pending"] += 1
            if len(self.pending_alerts) < PENDING_ALERT_LIMIT:
                self.pending_alerts.append(record)
            else:
                self.counters["alerts_pending_dropped"] += 1
        self._health()
        return record

    def _record_alert(self, record, tx=None) -> bool:
        try:
            if tx is not None:
                tx.put(ALERT_BUCKET, record["event_id"], record)
                return True
            if self.store is None:
                return False
            with self.store.transaction() as sink:
                sink.put(ALERT_BUCKET, record["event_id"], record)
                self._flush_pending(sink)
            self._sink("available")
            return True
        except Exception as exc:  # the sink is down: this is the case the local record exists for
            self.last_defect = _error_text(exc)
            self._sink("unavailable", exc)
            return False

    def _flush_pending(self, tx) -> int:
        replayed = 0
        while self.pending_alerts:
            record = self.pending_alerts[0]
            tx.put(ALERT_BUCKET, record["event_id"], {**record, "notification": {
                "status": "recorded_after_recovery", "channel": "postgres:" + ALERT_BUCKET}})
            self.pending_alerts.pop(0)
            replayed += 1
        if replayed:
            self.counters["alerts_replayed"] += replayed
        return replayed

    def _sink(self, state: str, error: BaseException | None = None) -> None:
        previous, self.sink_state = self.sink_state, state
        if state == "unavailable" and previous != "unavailable":
            self.alert("sink_unavailable", "postgres", severity="critical",
                       attributes={"sink": "postgres", "error_type": type(error).__name__ if error else "unknown",
                                   "pending": len(self.pending_alerts)})
        elif state == "available" and previous == "unavailable":
            self.emit("operations.sink_recovered", "observed", severity="warning",
                      attributes={"sink": "postgres", "replayed": int(self.counters["alerts_replayed"])})

    def health(self) -> dict:
        return {"process_run_id": self.process_run_id, "component": self.component, "role": self.role,
                "host": self.source["host"], "pid": self.source["pid"], "updated_at": self.clock(),
                "sequence_next": self._next, "counters": dict(self.counters), "sink": self.sink_state,
                "pending_alerts": [{"event_type": row["event_type"], "observed_at": row["observed_at"]}
                                   for row in self.pending_alerts],
                "last_defect": self.last_defect}

    def _health(self) -> None:
        try:
            self.directory.write_health(self.process_run_id, self.health())
        except Exception as exc:  # last resort: a redacted line on stderr, never an exception upward
            self.counters["health_write_failures"] += 1
            try:
                sys.stderr.write("observation health write failed: " + _error_text(exc) + "\n")
            except Exception:
                pass

    # ---- post-execution termination evidence ---------------------------------------------------
    @staticmethod
    def termination_id(lease: dict) -> str:
        return digest(["termination", lease.get("_bucket", "tasks"), lease["id"], lease.get("generation"),
                       lease.get("attempt")])

    def record_termination(self, lease: dict, *, reservation_id, classification: str, stream_hash: str | None,
                           error: BaseException, evidence_refs=()) -> str:
        """Redacted minimal evidence that the provider ran; written locally, then to the sink if it answers."""
        record_id = self.termination_id(lease)
        record = {"record_id": record_id, "status": "pending_reconciliation", "task_id": lease["id"],
                  "bucket": lease.get("_bucket", "tasks"), "generation": lease.get("generation"),
                  "attempt": lease.get("attempt"), "reservation_id": reservation_id,
                  "invocation_outcome": classification, "stream_hash": stream_hash,
                  "error_type": type(error).__name__, "error": _error_text(error),
                  "evidence_refs": list(evidence_refs), "process_run_id": self.process_run_id,
                  "recorded_at": self.clock(),
                  "note": "provider ran; settlement not recorded; do not re-execute before an operator reconciles"}
        try:
            self.directory.record_termination(record_id, record)
        except FileExistsError:
            self.counters["termination_redelivered"] += 1
        self.counters["terminations"] += 1
        self.emit("development.termination_recorded", "unknown", severity="critical",
                  execution=self.for_lease(lease, provider="codex-app-server", invocation_id=reservation_id),
                  correlation_id=self.correlation(lease), reason_code="settlement_not_recorded",
                  evidence_refs=evidence_refs,
                  attributes={"reservation_id": reservation_id, "invocation_outcome": classification,
                              "stream_hash": stream_hash or "unknown", "error_type": type(error).__name__,
                              "record_id": record_id})
        try:
            with self.store.transaction() as tx:
                if tx.get(TERMINATION_BUCKET, record_id) is None:
                    tx.put(TERMINATION_BUCKET, record_id, record)
        except Exception as exc:
            self.last_defect = _error_text(exc)
            self._sink("unavailable", exc)
        self._health()
        return record_id

    def pending_terminations(self, task_id: str) -> list[dict]:
        rows = {row.get("record_id", str(index)): row
                for index, row in enumerate(self.directory.pending_terminations(task_id))}
        try:
            with self.store.transaction() as tx:
                for row in tx.scan(TERMINATION_BUCKET):
                    if row.get("task_id") == task_id and row.get("status") == "pending_reconciliation":
                        rows.setdefault(row["record_id"], row)
        except Exception as exc:
            self.last_defect = _error_text(exc)
            self._sink("unavailable", exc)
        return [rows[key] for key in sorted(rows)]

    def resolve_termination(self, record_id: str, *, resolution: str, operator: str, reason: str) -> dict:
        require(resolution in {"rerun", "discard"}, "Resolution is rerun or discard")
        require(type(operator) is str and bool(operator) and type(reason) is str and bool(reason),
                "Operator label and reason required")
        decision = {"resolution": resolution, "operator": operator, "reason": reason, "at": self.clock(),
                    "authority": "operator_label_not_authenticated"}
        resolved = self.directory.resolve_termination(record_id, decision)
        with self.store.transaction() as tx:
            row = tx.get(TERMINATION_BUCKET, record_id) or resolved
            tx.put(TERMINATION_BUCKET, record_id, {**row, "status": "resolved", "resolution": decision})
            self.audit(tx, "development.reconciliation_resolved", "observed", identity=["reconciliation", record_id],
                       execution=self.for_lease({"id": resolved["task_id"], "_bucket": resolved.get("bucket", "tasks"),
                                                 "generation": resolved.get("generation"),
                                                 "attempt": resolved.get("attempt")}, role=self.role or "operator"),
                       attributes={"record_id": record_id, "resolution": resolution, "operator": operator})
        return resolved

    def close(self) -> None:
        self._health()
        self.spool.close()


class Collector:
    """Spool → sink → acknowledgement. Ordered by file offset, deduplicated by event id and content."""

    def __init__(self, store, directory, *, validate, observer: Observer | None = None,
                 batch: int = POLICY.observation_collect_batch, clock=utcnow):
        require(callable(validate), "Collector needs the observation validator")
        require(type(batch) is int and batch > 0, "Collection batch must be positive")
        self.store, self.directory, self.validate = store, directory, validate
        self.observer, self.batch, self.clock = observer, batch, clock

    def collect(self) -> dict:
        counts = Counter()
        files = []
        for path in self.directory.spool_files():
            offset = self.directory.acknowledged(path)
            rows, end, tail = [], offset, False
            for start, stop, status, kind, event, defect in self.directory.read(path, offset):
                if status == "truncated_tail":
                    tail = True
                    break
                rows.append((status, start, stop, kind, event, defect))
                end = stop
                if len(rows) >= self.batch:
                    break
            counts["files"] += 1
            counts["truncated_tail"] += int(tail)
            if not rows:
                continue
            try:
                with self.store.transaction() as tx:
                    result = self._sink(tx, path, rows)
                    receipt = {"id": digest([path.name, offset, end, self.clock()]), "file": path.name,
                               "from_offset": offset, "to_offset": end, **result, "at": self.clock()}
                    tx.put(COLLECTION_BUCKET, receipt["id"], receipt)
                    if self.observer is not None:
                        self.observer._flush_pending(tx)
            except Exception as exc:
                counts["sink_failures"] += 1
                if self.observer is not None:
                    self.observer.last_defect = _error_text(exc)
                    self.observer._sink("unavailable", exc)
                break
            if self.observer is not None:
                self.observer._sink("available")
            self.directory.acknowledge(path, end, len(rows))
            counts.update(result)
            files.append({"file": path.name, "from_offset": offset, "to_offset": end, **result})
        summary = {**{key: 0 for key in ("files", "records", "inserted", "duplicates", "conflicts", "corrupt",
                                         "refused", "truncated_tail", "unconfirmed_audits", "confirmed_audits",
                                         "sink_failures")}, **counts, "per_file": files}
        if self.observer is not None and (summary["records"] or summary["truncated_tail"]):
            self.observer.emit("operations.collection_completed", "observed",
                               attributes={key: int(summary[key]) for key in
                                           ("files", "records", "inserted", "duplicates", "conflicts", "corrupt",
                                            "truncated_tail", "unconfirmed_audits")})
        return summary

    def _sink(self, tx, path, rows) -> dict:
        result = Counter()
        for status, start, stop, kind, event, defect in rows:
            result["records"] += 1
            if status == "corrupt":
                self._quarantine(tx, "corrupt_record", {"file": path.name, "offset": start, "end": stop,
                                                        "defect": defect, "kind": kind})
                result["corrupt"] += 1
                continue
            if is_business_message(event):
                self._quarantine(tx, "business_message_shape", {"file": path.name, "offset": start,
                                                                "keys": sorted(map(str, event))[:20]})
                result["refused"] += 1
                continue
            try:
                self.validate(event)
            except ContractError as exc:
                self._quarantine(tx, "schema_refused", {"file": path.name, "offset": start, "defect": str(exc)[:600],
                                                        "event_id": event.get("event_id")})
                result["refused"] += 1
                continue
            digest_value = content_hash(event)
            existing = tx.get(EVENT_BUCKET, event["event_id"])
            if existing is None:
                confirmed = None
                if kind == "audit":
                    confirmed = tx.get(AUDIT_BUCKET, event["event_id"]) is not None
                    result["confirmed_audits" if confirmed else "unconfirmed_audits"] += 1
                tx.put(EVENT_BUCKET, event["event_id"], {**event, "payload_hash": digest_value, "record_kind": kind,
                       "audit_confirmed": confirmed, "collected_at": self.clock(),
                       "spool": {"file": path.name, "offset": start}, "authority": "informational_only"})
                result["inserted"] += 1
            elif existing.get("payload_hash") == digest_value:
                result["duplicates"] += 1
            else:
                quarantine_id = self._quarantine(tx, "conflicting_content", {
                    "file": path.name, "offset": start, "event_id": event["event_id"],
                    "expected_hash": existing.get("payload_hash"), "observed_hash": digest_value, "source": event})
                result["conflicts"] += 1
                if self.observer is not None:
                    self.observer.alert("observation_conflict", event["event_id"], severity="error", tx=tx,
                                        attributes={"conflicting_event_id": event["event_id"],
                                                    "expected_hash": existing.get("payload_hash"),
                                                    "observed_hash": digest_value, "quarantine_id": quarantine_id})
        return dict(result)

    def _quarantine(self, tx, reason, detail) -> str:
        identity = digest(["observation_quarantine", reason, detail.get("file"), detail.get("offset"),
                           detail.get("event_id"), detail.get("observed_hash")])
        if tx.get(QUARANTINE_BUCKET, identity) is None:
            tx.put(QUARANTINE_BUCKET, identity, {"id": identity, "reason": reason, **detail, "at": self.clock()})
        return identity


def orphan_report(tx, now: str | None = None) -> dict:
    """Reserved invocations whose execution still heartbeats versus ones whose lease is gone.

    The criteria are the invocation ledger's own (same attempt, running, same owner, live lease);
    this report never mutates the reservation, so it is safe to run from a read-only status.
    """
    moment = datetime.fromisoformat(now or utcnow())
    rows = {"in_progress": [], "orphan": []}
    for row in tx.scan("invocation_reservations"):
        if row.get("status") != "reserved":
            continue
        task = tx.get(row["bucket"], row["task_id"])
        same_attempt = task is not None and (task.get("generation"), task.get("attempt")) == (row["generation"], row["attempt"])
        lease_until = task.get("lease_until") if task else None
        try:
            lease_live = isinstance(lease_until, str) and datetime.fromisoformat(lease_until) > moment
        except ValueError:
            lease_live = False
        alive = same_attempt and task.get("status") == "running" and task.get("lease_owner") == row.get("owner") and lease_live
        reason = None if alive else ("execution_missing" if task is None else "execution_superseded" if not same_attempt
                                     else "execution_lease_expired" if task.get("status") == "running"
                                     else "execution_" + str(task.get("status")))
        rows["in_progress" if alive else "orphan"].append({"reservation_id": row["id"], "bucket": row["bucket"],
            "task_id": row["task_id"], "generation": row["generation"], "attempt": row["attempt"],
            "reserved_at": row.get("reserved_at"), "lease_until": lease_until, "reason": reason})
    return {"as_of": moment.isoformat(), **rows, "note": "orphan means reserved without a live lease; it is an observation, "
            "the invocation ledger's reclaim closes it as unsettled_unknown"}


def status_report(store, directory, observer: Observer | None = None) -> dict:
    with store.transaction() as tx:
        counts = {bucket: len(tx.scan(bucket)) for bucket in BUCKETS}
        pending = [row for row in tx.scan(TERMINATION_BUCKET) if row.get("status") == "pending_reconciliation"]
        alerts = tx.scan(ALERT_BUCKET)
        orphans = orphan_report(tx)
    return {"buckets": counts, "spool_files": [path.name for path in directory.spool_files()],
            "process_health": directory.read_health(),
            "pending_terminations": {"local": directory.pending_terminations(), "sink": pending},
            "alerts": {"recorded": len(alerts),
                       "pending_locally": len(observer.pending_alerts) if observer else None},
            "orphans": orphans, "observer": observer.health() if observer else None,
            "authority": "informational_only"}

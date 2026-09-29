"""The Observer's durable unconfirmed-effect marker (INV-OBSERVATION-001), moved ahead in S4.

Layer: application
Context: observation
Owns: the bucket names, and Observer.__init__/termination_id/mark_unconfirmed/close_unconfirmed (M7
    `application/observations.py`, moved ahead in S4 unchanged: lead decision Option A, the marker the RunTask
    reservation writes and every S4 terminal write closes); ReconciliationRequired, MemoryDirectory and
    Observer._other_attempt/guard_reservation, moved ahead in S4 unchanged (the guard the RunTask reservation
    transaction runs, INV-OBSERVATION-001)
Does not own: emit/audit/alert/record_termination/health, pending_terminations/resolve_termination and
    PostExecutionRecordFailure (these need `_sink`/`audit`, which come with build_event) and the rest of M7
    `observations.py` (S4 continues with record_termination/audit/emit and build_event; S9 the rest); the
    constructor keeps M7's signature, and the alert inheritance it ran (`_inherit_pending_alerts`) arrives with
    the alerts (S9)
Entry points: Observer, Observer.termination_id, Observer.mark_unconfirmed, Observer.close_unconfirmed,
    Observer.guard_reservation, ReconciliationRequired, MemoryDirectory, BUCKETS, TERMINATION_BUCKET
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations

import os
import platform
import threading
import time
from collections import Counter

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.kernel.policy import POLICY

AUDIT_BUCKET = "observation_audit"
EVENT_BUCKET = "observations"
QUARANTINE_BUCKET = "observation_quarantine"
ALERT_BUCKET = "observation_alerts"
COLLECTION_BUCKET = "observation_collections"
TERMINATION_BUCKET = "observation_terminations"
BUCKETS = (AUDIT_BUCKET, EVENT_BUCKET, QUARANTINE_BUCKET, ALERT_BUCKET, COLLECTION_BUCKET, TERMINATION_BUCKET)
PENDING_ALERT_LIMIT = 100
RESOLUTIONS = ("rerun", "discard")


class ReconciliationRequired(RuntimeError):
    """A previous attempt ran the provider but its outcome was never recorded; do not run it again."""

    def __init__(self, task_id: str, records: list[dict]):
        super().__init__(f"task {task_id} has {len(records)} termination record(s) pending reconciliation")
        self.task_id, self.records = task_id, records


class MemoryDirectory:
    """Unit-boundary stand-in for SpoolDirectory: same operations, in memory."""

    def __init__(self):
        self.health: dict[str, dict] = {}
        self.terminations: dict[str, dict] = {}
        self.resolved: dict[str, dict] = {}
        self.pending: dict[str, list[dict]] = {}
        self.acked: dict[str, set] = {}

    def write_health(self, process_run_id, record):
        self.health[process_run_id] = record

    def read_health(self):
        return [self.health[key] for key in sorted(self.health)]

    def write_pending_alerts(self, process_run_id, records):
        acked = self.acked.get(process_run_id, set())
        records = [row for row in records if row.get("event_id") not in acked]
        if records:
            self.pending[process_run_id] = list(records)
        else:
            self.pending.pop(process_run_id, None)

    def acknowledge_pending_alerts(self, origin, event_ids, replayer):
        self.acked.setdefault(origin, set()).update(event_ids)

    def acknowledged_alerts(self, origin):
        return set(self.acked.get(origin, set()))

    def read_pending_alerts(self):
        found = {}
        for key, value in self.pending.items():
            rows = [row for row in value if row.get("event_id") not in self.acked.get(key, set())]
            if rows:
                found[key] = rows
        return found

    def run_finished(self, process_run_id, now=None, retention_seconds=None):
        return False

    def prune(self, now=None, retention_seconds=None):
        return {"runs": 0, "segments": 0, "files": 0, "skipped": 0}

    def total_bytes(self):
        return 0

    def record_termination(self, record_id, record):
        if record_id in self.terminations:
            raise FileExistsError(record_id)
        self.terminations[record_id] = record

    def pending_terminations(self, task_id=None):
        return [row for key, row in sorted(self.terminations.items()) if task_id is None or row["task_id"] == task_id]

    def resolve_termination(self, record_id, resolution):
        if record_id not in self.terminations:
            if record_id in self.resolved:
                return self.resolved[record_id]
            raise ContractError("Unknown termination record")
        resolved = {**self.terminations.pop(record_id), "status": "resolved", "resolution": resolution}
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

    def reclaim(self, path):
        return False

    def unacknowledged_bytes(self):
        return 0


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
        self.inherited_pending: dict[str, list[dict]] = {}
        self.last_defect: str | None = None
        self.sink_state = "unknown"

    @staticmethod
    def termination_id(lease: dict) -> str:
        return digest(["termination", lease.get("_bucket", "tasks"), lease["id"], lease.get("generation"),
                       lease.get("attempt")])

    def mark_unconfirmed(self, tx, lease: dict, *, reservation_id) -> dict:
        """Durable marker written with the reservation, before any provider is entered.

        Until the outcome is accepted (or the attempt is proven never to have entered the
        provider, or an observed failure is recorded), this attempt's effects are unconfirmed and
        no later claim of the task may run the provider. It lives in the sink, so a failing
        termination file or a crash at any later boundary still leaves the block in place.
        """
        record_id = self.termination_id(lease)
        existing = tx.get(TERMINATION_BUCKET, record_id)
        if existing is not None and existing.get("status") in {"unconfirmed", "pending_reconciliation"}:
            return existing
        record = {"record_id": record_id, "status": "unconfirmed", "task_id": lease["id"],
                  "bucket": lease.get("_bucket", "tasks"), "generation": lease.get("generation"),
                  "attempt": lease.get("attempt"), "reservation_id": reservation_id, "boundary": "reserved",
                  "invocation_outcome": "unknown", "stream_hash": None, "error_type": None, "error": None,
                  "evidence_refs": [], "process_run_id": self.process_run_id, "recorded_at": self.clock(),
                  "note": "reserved; effects unconfirmed until the outcome is durably accepted"}
        tx.put(TERMINATION_BUCKET, record_id, record)
        self.counters["unconfirmed_marked"] += 1
        return record

    def close_unconfirmed(self, tx, lease: dict, closure: str) -> dict | None:
        """Clear the marker inside the transaction that durably records the outcome."""
        require(closure in {"accepted", "observed_failure", "not_entered"}, "Unknown closure")
        record_id = self.termination_id(lease)
        existing = tx.get(TERMINATION_BUCKET, record_id)
        if existing is None or existing.get("status") != "unconfirmed":
            return existing  # pending_reconciliation and resolved records are never closed here
        closed = {**existing, "status": "closed", "closure": closure, "closed_at": self.clock()}
        tx.put(TERMINATION_BUCKET, record_id, closed)
        self.counters["unconfirmed_closed"] += 1
        return closed

    @staticmethod
    def _other_attempt(row: dict, lease: dict) -> bool:
        return (row.get("generation"), row.get("attempt")) != (lease.get("generation"), lease.get("attempt"))

    def guard_reservation(self, tx, lease: dict) -> None:
        """Authoritative check, in the reservation transaction itself, that no earlier attempt of this
        task is still unconfirmed or awaiting reconciliation (INV-OBSERVATION-001).

        A best-effort read outside the transaction can miss rows (a transient query failure, a
        write that landed in between); this read cannot, and if it fails the reservation fails
        with it, so no provider starts.
        """
        blocking = [row for row in tx.scan(TERMINATION_BUCKET)
                    if row.get("task_id") == lease["id"] and row.get("bucket", "tasks") == lease.get("_bucket", "tasks")
                    and row.get("status") in {"unconfirmed", "pending_reconciliation"} and self._other_attempt(row, lease)]
        blocking += [row for row in self.directory.pending_terminations(lease["id"])
                     if row.get("unreadable") or self._other_attempt(row, lease)]
        if blocking:
            raise ReconciliationRequired(lease["id"], blocking)

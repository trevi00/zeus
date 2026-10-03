"""Queue depth and oldest-age facts as bounded state reads (DESIGN-s9-X §2.4).

Sources: the SQS ApproximateAgeOfOldestMessage metric (age of the oldest WAITING item, absent when none waits), the client-go workqueue
metrics (depth plus longest-running age), Sidekiq queue latency (age of the oldest job, not a count) and the Prometheus instrumentation
guidance (a gauge for a level, no identifiers in labels).

Four buckets are read through ONE `store.transaction()` with the bounded scan (`scan_bounded`) and nothing is written. Unavailable is never
zero: a scan that hit the limit (more rows exist) or a read that raised makes `zeus_queue_facts_available{queue}` 0 and the queue has NO
depth, age or unparseable series, because a lower bound is not exported. No row text, identifier or exception message reaches the output.

Layer: adapters
Context: observation
Owns: `QueueFacts` and its row families (depth, oldest age, unparseable rows, scanned rows, availability)
Does not own: the renderer (the X2 metric renderer consumes `rows()`), the scan (`monitoring_observations.scan_bounded`), fleet backlog and spool bytes, alert rules (X4b), wiring (S10)
Entry points: QueueFacts
Contracts: INV-OBSERVATION-001
"""
from datetime import datetime, timezone

from codex_harness.observation.adapters.monitoring_observations import BUCKET_LIMIT, scan_bounded

# Waiting `decisions_pending` statuses: the values written to that bucket by transactions are `pending` (coordination/application/messages.py),
# `deferred_pending_source_audit` (messages.py research), `retry` and `running` (decision_claims.py; OPEN_DECISION in local_cycle.py), and the terminal
# `succeeded`, `failed`, `expired`, `superseded` and `blocked` (decision_claims.py, execution_budget.py, review/application/decisions.py).
# `running` is claimed work, not waiting; terminal states never wait.
DECISION_WAITING = ("pending", "retry", "deferred_pending_source_audit")
QUEUES = ("outbox", "decisions_pending", "release_queue", "tasks")
STATES = ("waiting", "in_progress")

_FAMILIES = {
    "zeus_queue_depth": ("gauge", ("queue", "state"), "Number of waiting rows of the queue, and of running rows for tasks; absent when the scan was incomplete."),
    "zeus_queue_facts_available": ("gauge", ("queue",), "1 when the queue was read completely and 0 when the scan was truncated or the read failed."),
    "zeus_queue_oldest_age_seconds": ("gauge", ("queue",), "Seconds since the oldest waiting row with a parseable time was created, absent when no such row exists."),
    "zeus_queue_scanned_rows": ("gauge", ("queue",), "Number of rows read for the queue, the cost of the bounded scan."),
    "zeus_queue_unparseable_rows": ("gauge", ("queue",), "Waiting rows whose time is missing, naive or in the future, excluded from the oldest age."),
}


def _outbox(row):
    return (row.get("sent") is False, False, _path(row, "message", "when", "created_at"))


def _decision(row):
    return (row.get("status") in DECISION_WAITING, False, _path(row, "message", "when", "created_at"))


def _release(row):
    return (row.get("status") == "queued", False, row.get("at"))


def _task(row):
    status = row.get("status")
    return (status in ("queued", "retry"), status == "running", row.get("created_at"))


def _path(row, *keys):
    for key in keys:
        row = row.get(key) if isinstance(row, dict) else None
    return row


_CLASSIFY = {"outbox": _outbox, "decisions_pending": _decision, "release_queue": _release, "tasks": _task}


def _parse(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


class QueueFacts:
    """`now` returns an aware UTC datetime; `limit` is the per-bucket row bound."""

    def __init__(self, store, *, now, limit=BUCKET_LIMIT):
        self._store = store
        self._now = now
        self._limit = limit

    def _read(self):
        now = self._now()
        facts = {}
        with self._store.transaction() as tx:
            for queue in QUEUES:
                rows, sample = scan_bounded(tx, queue, limit=self._limit)
                if sample["truncated"]:
                    facts[queue] = {"scanned": len(rows), "complete": False}
                    continue
                waiting = running = unparseable = 0
                oldest = None
                for row in rows:
                    is_waiting, is_running, created = _CLASSIFY[queue](row) if isinstance(row, dict) else (False, False, None)
                    running += is_running
                    if not is_waiting:
                        continue
                    waiting += 1
                    parsed = _parse(created)
                    age = (now - parsed.astimezone(timezone.utc)).total_seconds() if parsed is not None else -1.0
                    if age < 0:
                        unparseable += 1
                    elif oldest is None or age > oldest:
                        oldest = age
                facts[queue] = {"scanned": len(rows), "complete": True, "waiting": waiting, "running": running,
                                "unparseable": unparseable, "oldest": oldest}
        return facts

    def rows(self):
        try:
            facts = self._read()
        except Exception:  # noqa: BLE001 - any read failure makes every queue unavailable; no exception text is exported
            facts = {}
        series = {name: [] for name in _FAMILIES}
        for queue in QUEUES:
            fact = facts.get(queue)
            series["zeus_queue_facts_available"].append({"labels": [queue], "value": 1 if fact and fact["complete"] else 0})
            if fact is None:
                continue
            series["zeus_queue_scanned_rows"].append({"labels": [queue], "value": fact["scanned"]})
            if not fact["complete"]:
                continue
            series["zeus_queue_depth"].append({"labels": [queue, "waiting"], "value": fact["waiting"]})
            if queue == "tasks":
                series["zeus_queue_depth"].append({"labels": [queue, "in_progress"], "value": fact["running"]})
            series["zeus_queue_unparseable_rows"].append({"labels": [queue], "value": fact["unparseable"]})
            if fact["oldest"] is not None:
                series["zeus_queue_oldest_age_seconds"].append({"labels": [queue], "value": fact["oldest"]})
        rows = []
        for name in sorted(_FAMILIES):
            kind, labels, help_text = _FAMILIES[name]
            ordered = sorted(series[name], key=lambda item: item["labels"])
            rows.append({"metric": name, "type": kind, "help": help_text, "labels": list(labels), "buckets": [], "series": ordered})
        return rows

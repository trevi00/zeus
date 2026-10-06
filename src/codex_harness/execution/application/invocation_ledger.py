"""Reserve before calling the model, settle with what was measured, never lose an attempt.

Layer: application
Context: execution
Owns: the `invocation_reservations` bucket (reserve, settle, abandon, reclaim, summary)
Does not own: the execution rows it reads to decide liveness (`tasks`/`decisions_pending`,
    coordination), the provider call itself
Entry points: InvocationLedger, reservation_key, BUCKET, STATUSES, UNKNOWN_USAGE
Contracts: INV-INVOCATION-001, INV-OBSERVATION-001

One reservation per model invocation of an execution attempt (bucket, task, generation, attempt,
invocation index), taken in the same transaction that proves current ownership; an attempt holds
at most one open reservation at a time. Open reservations are the real concurrency budget.
A reservation that never settles (crash, timeout, cancel) is closed as `unsettled_unknown` with
unknown usage when the next attempt reserves, or when any reservation finds that the execution
holding it is no longer the current one (cancelled, failed, expired, superseded); nothing is ever
back-filled to zero and a dead execution never holds capacity (review, PR #51).

The key is a pure function of the ownership tuple (RESEARCH-S4 R4): a retry of one attempt can never
mint a second reservation, and a same-key settle returns the stored row while a different settle of
the same key refuses. Moved from M7 `application/invocation_ledger.py`; the clock is injected.
"""
from __future__ import annotations

from datetime import datetime, timezone

from codex_harness.execution.domain.invocation import USAGE_SOURCES, outcome_check
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import SYSTEM_CLOCK, digest, utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.kernel.ports import Clock
from codex_harness.storage.ports import Store

BUCKET = 'invocation_reservations'
STATUSES = ('reserved', 'settled', 'unsettled_unknown')
UNKNOWN_USAGE = {'source': 'unknown', 'total_tokens': None, 'last_tokens': None}


def reservation_key(bucket, task_id, generation, attempt, invocation):
    return digest(['invocation', bucket, task_id, generation, attempt, invocation])


class InvocationLedger:
    """The reservation rows of every model invocation; each method is one store transaction."""

    def __init__(self, store: Store, capacity: int = POLICY.max_active_executions,
                 clock: Clock = SYSTEM_CLOCK):
        require(type(capacity) is int and capacity > 0, 'Invocation capacity must be positive')
        self.store, self.capacity, self.clock = store, capacity, clock

    def reserve(self, lease, *, request, budget_seconds, guard=None, stage=None, audit=None):
        """Reserve one model invocation of the current attempt (stages reserve one each, in turn).

        `guard(tx)` proves current ownership in the same transaction as the reservation (§2.9 rule 3).
        `audit(tx, row)` runs in the same transaction after the row is written (INV-OBSERVATION-001):
        when the audit record cannot be written the reservation does not commit either, so no
        provider starts without its mandatory audit.
        """
        require(isinstance(lease, dict) and type(lease.get('generation')) is int and type(lease.get('attempt')) is int
                and type(lease.get('id')) is str, 'Reservation requires a typed execution lease')
        require(type(budget_seconds) in (int, float) and budget_seconds > 0, 'Reservation budget must be positive')
        require(stage is None or (type(stage) is str and bool(stage)), 'Invocation stage must be a label')
        bucket = lease.get('_bucket', 'tasks')
        with self.store.transaction() as tx:
            if guard is not None:
                guard(tx)
            now = utcnow(self.clock)
            same_attempt = [row for row in tx.scan(BUCKET) if row['bucket'] == bucket and row['task_id'] == lease['id']
                            and (row['generation'], row['attempt']) == (lease['generation'], lease['attempt'])]
            require(not any(row['status'] == 'reserved' for row in same_attempt),
                    'This execution attempt already holds an open invocation reservation')
            invocation = 1 + len(same_attempt)
            key = reservation_key(bucket, lease['id'], lease['generation'], lease['attempt'], invocation)
            for row in tx.scan(BUCKET):
                if (row['status'] == 'reserved' and row['bucket'] == bucket and row['task_id'] == lease['id']
                        and (row['generation'], row['attempt']) < (lease['generation'], lease['attempt'])):
                    # The previous attempt never settled: its usage is unknown, not zero, and it
                    # stops counting against capacity only now that a newer attempt exists.
                    tx.put(BUCKET, row['id'], {**row, 'status': 'unsettled_unknown', 'usage': dict(UNKNOWN_USAGE),
                                               'closed_at': now, 'reason': 'superseded_by_new_attempt'})
            self._reclaim_dead(tx, now)
            open_rows = [row for row in tx.scan(BUCKET) if row['status'] == 'reserved']
            require(len(open_rows) < self.capacity, 'Invocation capacity is reserved by other executions')
            row = {'id': key, 'bucket': bucket, 'task_id': lease['id'], 'generation': lease['generation'],
                   'attempt': lease['attempt'], 'invocation': invocation, 'stage': stage,
                   'owner': lease.get('lease_owner'), 'request': request,
                   'budget_seconds': budget_seconds, 'status': 'reserved', 'reserved_at': now,
                   'usage': dict(UNKNOWN_USAGE), 'outcome': None}
            tx.put(BUCKET, key, row)
            if audit is not None:
                audit(tx, row)
            return row

    @staticmethod
    def _reclaim_dead(tx, now):
        """An open reservation counts only while the execution that took it is still the current one."""
        reclaimed = []
        for row in tx.scan(BUCKET):
            if row['status'] != 'reserved':
                continue
            task = tx.get(row['bucket'], row['task_id'])
            same_attempt = task is not None and (task.get('generation'), task.get('attempt')) == (row['generation'], row['attempt'])
            lease_until = task.get('lease_until') if task else None
            lease_live = isinstance(lease_until, str) and datetime.fromisoformat(lease_until) > datetime.fromisoformat(now)
            alive = (same_attempt and task.get('status') == 'running' and task.get('lease_owner') == row['owner'] and lease_live)
            if alive:
                continue
            reason = ('execution_missing' if task is None else 'execution_superseded' if not same_attempt
                      else 'execution_lease_expired' if task.get('status') == 'running' and task.get('lease_owner') == row['owner']
                      else 'execution_' + str(task.get('status')))
            tx.put(BUCKET, row['id'], {**row, 'status': 'unsettled_unknown', 'usage': dict(UNKNOWN_USAGE),
                                       'closed_at': now, 'reason': reason})
            reclaimed.append(row['id'])
        return reclaimed

    def reclaim(self):
        """Explicit recovery: close every reservation whose execution is no longer current."""
        with self.store.transaction() as tx:
            return self._reclaim_dead(tx, utcnow(self.clock))

    def settle(self, reservation_id, *, outcome, usage, evidence_ref=None, audit=None):
        """Record the observed outcome and usage; a same-key replay returns the row, a conflict refuses."""
        outcome_check(outcome)
        require(isinstance(usage, dict) and usage.get('source') in USAGE_SOURCES
                and (usage['source'] == 'unknown') == (usage.get('total_tokens') is None),
                'Usage must name its source; unknown usage carries no count')
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, reservation_id)
            require(row is not None, 'Unknown invocation reservation')
            if row['status'] != 'reserved':
                require(row['status'] == 'settled' and row['outcome'] == outcome and row['usage'] == usage,
                        'Conflicting settlement of one execution attempt')
                return row
            settled_at = utcnow(self.clock)
            elapsed = (datetime.fromisoformat(settled_at) - datetime.fromisoformat(row['reserved_at'])).total_seconds()
            row.update(status='settled', outcome=outcome, usage=usage, settled_at=settled_at,
                       elapsed_seconds=elapsed, evidence_ref=evidence_ref,
                       within_budget=elapsed <= row['budget_seconds'])
            tx.put(BUCKET, reservation_id, row)
            if audit is not None:
                audit(tx, row)
            return row

    def abandon(self, reservation_id, reason, audit=None):
        """Close an open reservation as `unsettled_unknown` (usage unknown, never zero)."""
        require(type(reason) is str and bool(reason), 'Abandon reason required')
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, reservation_id)
            require(row is not None, 'Unknown invocation reservation')
            if row['status'] != 'reserved':
                return row
            row.update(status='unsettled_unknown', usage=dict(UNKNOWN_USAGE), closed_at=utcnow(self.clock),
                       reason=reason)
            tx.put(BUCKET, reservation_id, row)
            if audit is not None:
                audit(tx, row)
            return row

    def summary(self):
        """Counts by status/outcome; unknown usage is excluded from the measured sum, never zero."""
        with self.store.transaction() as tx:
            rows = tx.scan(BUCKET)
        measured = [row for row in rows if row['usage']['source'] != 'unknown']
        return {'reservations': len(rows),
                'by_status': {status: sum(row['status'] == status for row in rows) for status in STATUSES},
                'by_outcome': {outcome: sum(row.get('outcome') == outcome for row in rows)
                               for outcome in sorted({row.get('outcome') for row in rows if row.get('outcome')})},
                'usage_unknown': len(rows) - len(measured),
                'measured_total_tokens': sum(row['usage']['total_tokens'] for row in measured),
                'note': 'unknown usage is excluded from the measured sum, never counted as zero',
                'as_of': self.clock.now().astimezone(timezone.utc).isoformat()}

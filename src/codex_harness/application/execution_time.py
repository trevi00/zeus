"""Shared durable deadlines and process-domain elapsed time, with containment."""
import math
import time
from uuid import uuid4

from codex_harness.application.execution_budget import aware_time, block_execution, deadline_time
from codex_harness.application.execution_notices import record
from codex_harness.domain.model import ContractError, digest, require

DOMAIN = str(uuid4())
CLOCK_TOLERANCE_SECONDS = 5


class ExecutionTimeError(ContractError):
    def __init__(self, reason, observation=None):
        self.reason = reason
        self.observation = observation
        super().__init__(reason)


def deadline(row, bucket):
    try:
        value = row.get('execution_deadline')
        if bucket == 'tasks' and 'execution_deadline' not in row:
            value = row['message']['when']['deadline']
        return deadline_time(value)
    except (ContractError, KeyError, TypeError) as exc:
        raise ExecutionTimeError('InvalidExecutionDeadline') from exc


def active(row, bucket, now):
    due = deadline(row, bucket)
    observed_monotonic = time.monotonic()
    elapsed, pin = check_clock(row, now, observed_monotonic, DOMAIN)
    observation = {'wall': now.isoformat(), 'monotonic': observed_monotonic, 'domain': DOMAIN,
                   'time_basis': 'same_domain_monotonic' if elapsed is not None else 'utc_foreign_or_legacy',
                   'deadline': due.isoformat() if due is not None else None}
    if due is not None and due <= now:
        raise ExecutionTimeError('deadline_exceeded', observation)
    if elapsed is not None and pin.get('deadline_remaining') is not None and elapsed >= pin['deadline_remaining']:
        raise ExecutionTimeError('deadline_exceeded', observation)
    try:
        until = deadline_time(row.get('lease_until'))
        if until is None:
            raise ContractError('Running execution requires a lease')
    except ContractError as exc:
        raise ExecutionTimeError('InvalidExecutionLease', observation) from exc
    return until > now and (elapsed is None or elapsed < pin['lease_seconds'])


def check_clock(row, now, observed_monotonic, domain):
    """Pure comparison: monotonic origins are never compared across process domains."""
    if type(observed_monotonic) not in (int, float) or not math.isfinite(observed_monotonic):
        raise ExecutionTimeError('InvalidExecutionClock')
    pin = row.get('execution_clock')
    if pin is None:
        return None, {}
    try:
        if not isinstance(pin, dict) or type(pin.get('version')) is not int or pin['version'] != 1:
            raise ValueError('Invalid clock version')
        wall = deadline_time(pin.get('wall'))
        values = [pin['monotonic'], pin['lease_seconds'], observed_monotonic]
        if pin.get('deadline_remaining') is not None:
            values.append(pin['deadline_remaining'])
        if (wall is None or not isinstance(pin.get('domain'), str) or not pin['domain']
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
                or pin['lease_seconds'] < 0 or (pin.get('deadline_remaining') is not None
                                               and pin['deadline_remaining'] < 0)):
            raise ValueError('Invalid clock sample')
        delta_wall = (now - wall).total_seconds()
        elapsed = observed_monotonic - pin['monotonic'] if domain == pin['domain'] else None
        if (delta_wall < -CLOCK_TOLERANCE_SECONDS or (elapsed is not None
                and (elapsed < 0 or abs(delta_wall - elapsed) > CLOCK_TOLERANCE_SECONDS))):
            raise ExecutionTimeError('ClockDiscontinuity', {'wall': now.isoformat(),
                'monotonic': observed_monotonic, 'domain': domain, 'delta_wall': delta_wall,
                'delta_monotonic': elapsed, 'previous': pin})
        return elapsed, pin
    except ExecutionTimeError:
        raise
    except (ContractError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ExecutionTimeError('InvalidExecutionClock') from exc


def pin_clock(row, bucket, now, until, *, renew=False):
    # Scheduling may inject a wall time; persisted clock pairs must use the host.
    now = aware_time()
    mono = time.monotonic()
    due = deadline(row, bucket)
    remaining = (due - now).total_seconds() if due is not None else None
    if renew:
        elapsed, previous = check_clock(row, now, mono, DOMAIN)
        if elapsed is not None and previous.get('deadline_remaining') is not None:
            prior_remaining = max(0, previous['deadline_remaining'] - elapsed)
            remaining = min(remaining, prior_remaining) if remaining is not None else prior_remaining
    if remaining is not None and remaining <= 0:
        raise ExecutionTimeError('deadline_exceeded')
    row['execution_clock'] = {'version': 1, 'domain': DOMAIN, 'wall': now.isoformat(), 'monotonic': mono,
                              'lease_seconds': max(0, (until - now).total_seconds()),
                              'deadline_remaining': remaining}


def observe_domain(tx, row, bucket, now):
    pin = row.get('execution_clock')
    previous = pin.get('domain') if isinstance(pin, dict) else None
    if previous == DOMAIN:
        return
    event = {'type': 'execution.clock_domain_observed', 'bucket': bucket, 'task_id': row['id'],
             'generation': row.get('generation', 0), 'previous_domain': previous, 'observer_domain': DOMAIN,
             'disposition': 'utc_validation_foreign_domain' if previous else 'utc_validation_legacy'}
    identity = digest(event)
    if not tx.get('events', identity):
        tx.put('events', identity, {**event, 'at': now.isoformat()})


def contain_with_notice(tx, org, row, bucket, reason, now, observation=None):
    event = {'bucket': bucket, 'task_id': row['id'], 'generation': row.get('generation', 0), 'attempt': row.get('attempt'),
             'recovery_sequence': row.get('recovery_sequence', 0), 'reason': reason}
    identity = digest(event)
    old = tx.get('execution_time_events', identity)
    if old:
        require(all(old.get(key) == value for key, value in event.items()), 'Conflicting execution time event')
    else:
        tx.put('execution_time_events', identity, {**event, 'observation': observation,
                                                   'id': identity, 'at': now.isoformat(),
                                                   'authority': 'informational_only'})
    if reason == 'deadline_exceeded':
        from codex_harness.application.workflow import Workflow
        if type(row.get('attempt')) is int and row['attempt'] > 0:
            Workflow._attempt_outcome(row, 'expired', now.isoformat(), 'deadline exceeded')
        row.update(status='expired', error='deadline exceeded', completed_at=now.isoformat())
        tx.put(bucket, row['id'], row)
        record(tx, org, row, bucket, reason, now.isoformat())
    else:
        block_execution(tx, row, bucket, reason, now, org)
    return row


def running(tx, org, now=None):
    live = []
    for bucket in ('tasks', 'decisions_pending'):
        for row in tx.scan(bucket):
            if row['status'] != 'running':
                continue
            observed_now = aware_time(now)
            try:
                if active(row, bucket, observed_now):
                    live.append(row)
                observe_domain(tx, row, bucket, observed_now)
            except ExecutionTimeError as exc:
                contain_with_notice(tx, org, row, bucket, exc.reason, observed_now, exc.observation)
    return live

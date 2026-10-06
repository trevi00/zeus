"""Stage-one definitions and deterministic evaluation (INV-METRIC-001)."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from codex_harness.domain.policy import POLICY


@dataclass(frozen=True)
class Definition:
    metric_id: str
    population: str
    numerator: str
    denominator: str
    unit: str = 'ratio'
    version: int = 1
    query_version: int = 1
    window_seconds: int = 86400
    freshness_seconds: int = 120
    minimum_samples: int = 1
    target: int | None = None
    direction: str | None = None


DEFINITIONS = (
    Definition('task_first_attempt_success', 'Tasks created in [start,end), first attempt resolved',
               'First attempts succeeded', 'Resolved first attempts'),
    Definition('terminal_logical_task_success', 'Tasks created in [start,end), terminal at observation',
               'Succeeded logical tasks', 'Succeeded, failed, cancelled and expired logical tasks'),
    Definition('active_execution_capacity', 'All tasks and decisions with running status and live lease',
               'Live leased executions', 'Not applicable: instantaneous gauge', unit='executions',
               window_seconds=0, target=POLICY.max_active_executions, direction='at_most'),
)
TERMINAL = {'succeeded', 'failed', 'cancelled', 'expired'}


@dataclass(frozen=True)
class Evaluation:
    metric_id: str
    status: Literal['pass', 'fail', 'unknown']
    reason: str
    value: float | int | None = None
    numerator: int | None = None
    denominator: int | None = None
    sample_count: int = 0
    observational: bool = True


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Naive timestamp')
    return parsed


def evaluate(definition: Definition, evidence: dict | None, now: datetime) -> Evaluation:
    def unknown(reason):
        return Evaluation(definition.metric_id, 'unknown', reason)
    try:
        if evidence is None:
            return unknown('missing evidence')
        observed = timestamp(evidence['observed_at'])
        if observed > now:
            return unknown('future-dated evidence')
        if (now - observed).total_seconds() > definition.freshness_seconds:
            return unknown('stale evidence')
        tasks, decisions = evidence['tasks'], evidence['decisions']
        for rows in (tasks, decisions):
            if (not isinstance(rows, list) or len({r['id'] for r in rows}) != len(rows)
                    or any(not isinstance(r['id'], str) or not r['id'] for r in rows)):
                return unknown('invalid or duplicate population')
        if definition.metric_id == 'active_execution_capacity':
            for rows, allowed in ((tasks, TERMINAL | {'queued', 'running', 'retry'}),
                                  (decisions, TERMINAL | {'pending', 'running', 'retry', 'blocked',
                                   'inspection_blocked', 'deferred_pending_source_audit'})):
                if any(r['status'] not in allowed for r in rows):
                    return unknown('invalid execution status')
            value = sum(r['status'] == 'running' and timestamp(r['lease_until']) > observed
                        for r in tasks + decisions)
            return Evaluation(definition.metric_id, 'pass' if value <= definition.target else 'fail',
                              'existing policy capacity; leased records, not OS process telemetry',
                              value, value, None, 1, False)
        start = observed - timedelta(seconds=definition.window_seconds)
        eligible = []
        for row in tasks:
            created = timestamp(row['created_at'])
            if created > observed:
                return unknown('future-dated task')
            if row.get('completed_at') is not None:
                completed = timestamp(row['completed_at'])
                if not created <= completed <= observed:
                    return unknown('invalid or future-dated completion')
            if row['status'] not in TERMINAL | {'queued', 'running', 'retry'}:
                return unknown('invalid task status')
            if not start <= created < observed:
                continue
            if type(row['attempt']) is not int or row['attempt'] < 0:
                return unknown('invalid attempt count')
            if row['status'] == 'succeeded' and row['attempt'] == 0:
                return unknown('success without an attempt')
            if definition.metric_id == 'terminal_logical_task_success':
                if row['status'] in TERMINAL:
                    eligible.append(row['status'] == 'succeeded')
            else:
                outcomes = row.get('attempt_outcomes', [])
                if (len({r['attempt'] for r in outcomes}) != len(outcomes)
                        or any(type(r['attempt']) is not int or not 1 <= r['attempt'] <= row['attempt']
                               or timestamp(r['at']) < created or timestamp(r['at']) > observed
                               or r['status'] not in TERMINAL | {'lease_expired'} for r in outcomes)):
                    return unknown('invalid attempt history')
                first = [r for r in outcomes if r['attempt'] == 1]
                if len(first) > 1:
                    return unknown('duplicate first outcome')
                if first:
                    outcome = first[0]
                    if timestamp(outcome['at']) > observed or outcome['status'] not in TERMINAL | {'lease_expired'}:
                        return unknown('invalid attempt evidence')
                    eligible.append(outcome['status'] == 'succeeded')
                elif row['attempt'] > 1 or (row['attempt'] and row['status'] != 'running'):
                    return unknown('missing attempt history; legacy outcomes not reconstructed')
        count, good = len(eligible), sum(eligible)
        if count < definition.minimum_samples:
            return Evaluation(definition.metric_id, 'unknown',
                              'insufficient samples (including zero population)',
                              numerator=good, denominator=count, sample_count=count)
        return Evaluation(definition.metric_id, 'unknown', 'undefined target; observational only',
                          good / count, good, count, count)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return unknown('invalid evidence')


def definition_documents():
    return [asdict(d) for d in DEFINITIONS]

"""Completion authority ledger: bound verdicts per execution, rejections kept as structured notices.

The task row's own `succeeded` status is the worker's self-report. Authority to treat a task
as complete comes only from a recorded verdict that binds the current execution, the spec
revision and evaluation artifact the consumer asks about, and a reviewer and runner receipt.
Nothing here is consulted by dispatch yet (FA-018 rollback: the path stays inactive until
qualified); consumers opt in through `require_authority`.
"""
from datetime import datetime, timezone

from codex_harness.domain.completion import KEYS, latest, parse_verdict
from codex_harness.domain.model import ContractError, digest, require, utcnow

BUCKET = 'completion_verdicts'
REJECTIONS = 'completion_rejections'
RECORD_ONLY = ('sequence', 'recorded_at')
STATES = ('unreadable', 'no_ledger', 'corrupt', 'partially_corrupt', 'rejected_only', 'not_evaluated',
          'stale', 'not_approved', 'incomplete', 'not_succeeded', 'authoritative')


def _excerpt(record):
    text = repr(record)
    return text if len(text) <= 2000 else text[:2000] + '…'


def _task_of(record):
    target = record.get('target') if isinstance(record, dict) else None
    task_id = target.get('task_id') if isinstance(target, dict) else None
    return task_id if type(task_id) is str else None


class CompletionAuthority:
    def __init__(self, store):
        self.store = store

    def record(self, record, now=None):
        try:
            verdict = parse_verdict(record, now or datetime.now(timezone.utc))
        except ContractError as exc:
            # Structured refusal stays in the ledger as a notice; the same malformed record
            # replayed lands on the same row, so rejections never inflate.
            rejection = {'task_id': _task_of(record), 'reason': str(exc), 'excerpt': _excerpt(record)}
            key = digest([rejection['task_id'], rejection['reason'], rejection['excerpt']])
            with self.store.transaction() as tx:
                if tx.get(REJECTIONS, key) is None:
                    tx.put(REJECTIONS, key, {**rejection, 'id': key, 'at': utcnow()})
            raise
        with self.store.transaction() as tx:
            existing = tx.get(BUCKET, verdict['id'])
            if existing is not None:
                # Same identity, same content (observed_at is not identity): a redelivery
                # returns the original row and never re-sequences it.
                same = all(existing.get(key) == verdict[key] for key in KEYS if key != 'observed_at')
                require(same, 'Completion verdict identity reused with different content')
                return {'id': verdict['id'], 'changed': False, 'sequence': existing['sequence']}
            target = verdict['target']
            task = tx.get('tasks', target['task_id'])
            require(task is not None, 'Completion verdict for an unknown task')
            require(task.get('generation') == target['generation'] and task.get('attempt') == target['attempt']
                    and type(task.get('generation')) is int and type(task.get('attempt')) is int,
                    'Completion verdict is bound to a different execution than the current one')
            sequence = 1 + sum(row.get('target', {}).get('task_id') == target['task_id'] for row in tx.scan(BUCKET))
            tx.put(BUCKET, verdict['id'], {**verdict, 'sequence': sequence, 'recorded_at': utcnow()})
        return {'id': verdict['id'], 'changed': True, 'sequence': sequence}

    def inspect(self, task_id, *, spec_revision, evaluation_artifact):
        """Classify the ledger for one task; every state except `authoritative` grants nothing."""
        require(type(task_id) is str and bool(task_id), 'Task identity required')
        try:
            with self.store.transaction() as tx:
                task = tx.get('tasks', task_id)
                rows = [row for row in tx.scan(BUCKET) if _task_of(row) == task_id]
                rejections = sum(row.get('task_id') == task_id for row in tx.scan(REJECTIONS))
        except Exception as exc:  # store failure is a distinct state, never "no evaluation"
            return {'state': 'unreadable', 'task_id': task_id, 'authority': False,
                    'reason': type(exc).__name__ + ': ' + str(exc)[:200]}
        report = {'task_id': task_id, 'authority': False, 'verdicts': len(rows), 'corrupt': 0,
                  'rejections': rejections, 'latest': None}
        if task is None:
            return {**report, 'state': 'no_ledger', 'reason': 'unknown task'}
        report.update(generation=task.get('generation'), attempt=task.get('attempt'), status=task.get('status'))
        valid = []
        for row in rows:
            try:
                parsed = parse_verdict({key: row[key] for key in KEYS}, None)
                require(parsed['id'] == row.get('id') and type(row.get('sequence')) is int,
                        'stored identity or sequence mismatch')
                valid.append({**row, 'complete': parsed['complete']})
            except (ContractError, KeyError, TypeError):
                report['corrupt'] += 1
        if rows and report['corrupt']:
            state = 'corrupt' if not valid else 'partially_corrupt'
            return {**report, 'state': state, 'reason': 'stored verdicts fail the closed schema'}
        if not rows:
            return {**report, 'state': 'rejected_only' if rejections else 'not_evaluated'}
        current = [row for row in valid
                   if row['target']['generation'] == task.get('generation')
                   and row['target']['attempt'] == task.get('attempt')
                   and row['spec_revision'] == spec_revision
                   and row['evaluation_artifact'] == evaluation_artifact]
        if not current:
            return {**report, 'state': 'stale',
                    'reason': 'no verdict binds the current execution, spec revision and artifact'}
        last = latest(current)
        report['latest'] = {key: last[key] for key in ('id', 'verdict', 'sequence', 'reviewer', 'complete',
                                                       'observed_at')}
        if last['verdict'] != 'approved':
            return {**report, 'state': 'not_approved'}
        if not last['complete']:
            return {**report, 'state': 'incomplete', 'reason': 'scenario denominator not fully dispositioned'}
        if task.get('status') != 'succeeded':
            return {**report, 'state': 'not_succeeded', 'reason': 'execution has not reported success'}
        return {**report, 'state': 'authoritative', 'authority': True}

    def require_authority(self, task_id, *, spec_revision, evaluation_artifact):
        report = self.inspect(task_id, spec_revision=spec_revision, evaluation_artifact=evaluation_artifact)
        require(report['authority'], 'No completion authority: ' + report['state'])
        return report

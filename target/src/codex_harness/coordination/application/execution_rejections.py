"""Reconcile only the same execution; durably observe fenced-out executors.

Layer: application
Context: coordination
Owns: reconcile and the `execution_rejections` bucket (M7 `application/execution_rejections.py`, moved ahead in
    S4 unchanged: lead decision Option A; the clocks are optional injections)
Does not own: the lease itself (the workflow), the business effect that failed (its caller)
Entry points: reconcile
Contracts: INV-SESSION-001, INV-EXECUTION-IDENTITY-001
"""

from codex_harness.coordination.application.execution_budget import aware_time
from codex_harness.coordination.application.execution_time import ExecutionTimeError, active
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest


def _identity(row):
    return {key: row.get(key) for key in ('id', 'generation', 'attempt', 'lease_owner',
                                        'agent', 'actor')} | {'recovery_sequence': row.get('recovery_sequence', 0)}


def reconcile(store, lease, error, rejection_error=None, *, clock=None, monotonic=None):
    """Call after the failed business transaction has rolled back, never inside it."""
    bucket = lease.get('_bucket', 'tasks')
    require(bucket in {'tasks', 'decisions_pending'}, 'Invalid execution aggregate')
    submitted = _identity(lease)
    require(isinstance(lease.get('id'), str) and bool(lease['id'])
            and all(type(submitted[key]) is int and submitted[key] >= 0
                    for key in ('generation', 'attempt', 'recovery_sequence'))
            and isinstance(lease.get('lease_owner'), str) and bool(lease['lease_owner'])
            and isinstance(lease.get('agent' if bucket == 'tasks' else 'actor'), str),
            'Invalid submitted execution identity')
    with store.transaction() as tx:
        current = tx.get(bucket, lease['id'])
        observed = _identity(current) if current else None
        now = aware_time(clock=clock)
        same = observed is not None and all(type(observed[key]) is type(value) and observed[key] == value
                                            for key, value in submitted.items())
        if current and same and current['status'] == 'succeeded':
            return current
        if not current:
            reason = 'execution_missing'
        elif not same:
            reason = 'execution_identity_changed'
        elif current['status'] != 'running':
            reason = 'execution_not_running'
        else:
            try:
                valid = active(current, bucket, now, monotonic=monotonic)
                reason = 'execution_lease_expired'
            except ExecutionTimeError as exc:
                valid = False
                reason = 'invalid_execution_lease' if exc.reason == 'InvalidExecutionLease' else exc.reason
            if valid:
                # A valid owner's unrelated error is not evidence of lease loss.
                raise error from rejection_error
        request = {'bucket': bucket, 'submitted': submitted, 'observed': observed,
                   'observed_status': current.get('status') if current else None,
                   'reason_code': reason}
        identity = digest(request)
        old = tx.get('execution_rejections', identity)
        if old:
            require(old['request'] == request, 'Conflicting execution rejection')
            return old['result']
        result = {'id': lease['id'], 'status': 'stale', 'error': str(error), 'rejection_id': identity}
        tx.put('execution_rejections', identity, {'id': identity, 'request': request, 'result': result,
                                                 'error': {'type': type(error).__name__, 'message': str(error)},
                                                 'rejection_error': ({'type': type(rejection_error).__name__,
                                                                      'message': str(rejection_error)}
                                                                     if rejection_error is not None else None),
                                                 'at': now.isoformat(), 'authority': 'informational_only'})
        # INV-SESSION-001: this observation cannot publish business effects or a successor's success.
        tx.put('events', identity, {'type': 'execution.rejected', 'rejection_id': identity,
                                   'task_id': lease['id'], 'bucket': bucket, 'reason_code': reason,
                                   'at': now.isoformat()})
        return result

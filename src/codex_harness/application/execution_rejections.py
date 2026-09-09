"""Reconcile only the same execution; durably observe fenced-out executors."""
from codex_harness.application.execution_budget import aware_time, deadline_time
from codex_harness.domain.model import ContractError, digest, require


def _identity(row):
    return {key: row.get(key) for key in ('id', 'generation', 'attempt', 'lease_owner',
                                        'agent', 'actor')} | {'recovery_sequence': row.get('recovery_sequence', 0)}


def reconcile(store, lease, error, rejection_error=None):
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
        now = aware_time()
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
                until = deadline_time(current.get('lease_until'))
            except ContractError:
                until = None
            reason = 'invalid_execution_lease' if until is None else 'execution_lease_expired'
            if until is not None and until > now:
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

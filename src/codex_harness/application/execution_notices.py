"""Informational execution transitions, atomically retained beside the outbox."""
import math
import re

from codex_harness.domain.model import ContractError, digest, envelope, require

REASONS = {'execution_failed', 'budget_exhausted', 'deadline_exceeded', 'dependency_failed',
           'operator_cancelled', 'ticket_binding_changed', 'execution_recovered', 'InvalidExecutionDeadline',
           'InvalidRetryBudget', 'UnverifiedLegacyRetryBudget', 'RecoveryContextChanged',
           'inspection_blocked', 'decision_blocked', 'ticket_superseded', 'InvalidExecutionLease',
           'InvalidExecutionClock', 'ClockDiscontinuity', 'InvalidExecutionOrder', 'InvalidExecutionState'}


def _build(org, row, bucket, reason_code, at, transition_ref):
    require(bucket in {'tasks', 'decisions_pending'}, 'Invalid notice aggregate')
    require(reason_code in REASONS, 'Unknown execution notice reason')
    require(row['status'] in {'retry', 'failed', 'expired', 'cancelled', 'blocked', 'superseded', 'inspection_blocked'},
            'Invalid notice execution state')
    actor = org.actor(row.get('agent', row.get('actor')))
    recipient = actor.parent or actor.id
    transition = {'version': 1, 'bucket': bucket, 'task_id': row['id'],
                  'generation': row.get('generation', 0), 'attempt': row['attempt'],
                  'recovery_sequence': row.get('recovery_sequence', 0), 'status': row['status'],
                  'reason_code': reason_code}
    transition['transition_ref'] = transition_ref or digest(transition)
    require(all(type(transition[k]) is int and transition[k] >= 0 for k in
                ('generation', 'attempt', 'recovery_sequence')), 'Invalid notice counters')
    require(re.fullmatch('[0-9a-f]{64}', transition['transition_ref']) is not None, 'Invalid transition reference')
    identity = digest(transition)
    message = envelope('execution.notice', actor.id, recipient, 'observe_execution',
                       {'notice_id': identity, **transition},
                       row.get('message', {}).get('correlation_id', row['id']), row['id'])
    message['message_id'] = identity
    message['when']['created_at'] = at
    message['why']['objective'] = 'Observe a persisted execution transition without granting workflow authority'
    message['why']['evidence_refs'] = []
    org.authorize(message)
    notice = {'id': identity, 'transition': transition, 'message': message, 'at': at,
              'authority': 'informational_only', 'observer': 'workflow_controller', 'source_hash': digest(row)}
    return notice


def _quarantine_value(value):
    """Preserve JSON data; explicitly label values the durable store cannot encode."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, dict):
        if all(isinstance(key, str) for key in value):
            return {key: _quarantine_value(item) for key, item in value.items()}
        return {'invalid_mapping': [[_quarantine_value(key), _quarantine_value(item)]
                                    for key, item in value.items()]}
    if isinstance(value, (list, tuple)):
        return [_quarantine_value(item) for item in value]
    return {'invalid_type': type(value).__name__}


def record(tx, org, row, bucket, reason_code, at, transition_ref=None):
    try:
        notice = _build(org, row, bucket, reason_code, at, transition_ref)
    except (ContractError, KeyError, TypeError, ValueError, AttributeError) as exc:
        # Bad source data must not roll back containment of this or earlier queue rows.
        # Storage errors below still abort the entire transaction; no state-only success.
        source = {'bucket': bucket, 'source': _quarantine_value(row),
                  'reason_code': reason_code, 'transition_ref': _quarantine_value(transition_ref)}
        semantic = {key: _quarantine_value(row.get(key)) for key in
                    ('id', 'agent', 'actor', 'generation', 'attempt', 'recovery_sequence', 'status')}
        identity = digest({'bucket': bucket, 'transition': semantic, 'reason_code': reason_code,
                           'transition_ref': source['transition_ref']})
        old = tx.get('execution_notice_errors', identity)
        if old:
            return old
        error = {'id': identity, **source, 'status': 'quarantined', 'error_type': type(exc).__name__, 'at': at}
        tx.put('execution_notice_errors', identity, error)
        tx.put('events', identity, {'type': 'execution.notice_quarantined', 'notice_error_id': identity,
                                   'task_id': _quarantine_value(row.get('id')), 'bucket': bucket, 'at': at})
        return error
    identity = notice['id']
    existing = tx.get('execution_notices', identity)
    if existing:
        require(existing['transition'] == notice['transition'], 'Conflicting execution notice identity')
        return existing
    tx.put('execution_notices', identity, notice)
    tx.put('outbox', identity, {'message': notice['message'], 'sent': False})
    return notice


def receive(tx, message):
    identity = message['message_id']
    old = tx.get('workflow_inbox', identity)
    if old:
        require(old['hash'] == digest(message), 'Conflicting execution notice delivery')
        return old['result']
    notice = tx.get('execution_notices', identity)
    require(isinstance(notice, dict) and notice.get('id') == identity
            and isinstance(notice.get('transition'), dict) and identity == digest(notice['transition'])
            and notice.get('message') == message, 'Unproven execution notice')
    result = {'handled': True, 'notice_id': identity, 'authority': 'informational_only'}
    tx.put('workflow_inbox', identity, {'hash': digest(message), 'result': result})
    return result

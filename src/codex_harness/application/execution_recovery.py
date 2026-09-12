"""Explicit recovery at the trusted local operator boundary; no human attestation."""
import json
from copy import deepcopy
from datetime import timedelta

from codex_harness.application.execution_budget import aware_time, deadline_time, positive_integer
from codex_harness.application.tickets import ticket_binding
from codex_harness.domain.model import ContractError, canonical, digest, require


class ExecutionRecovery:
    def __init__(self, store, organization, artifacts):
        self.store, self.org, self.artifacts = store, organization, artifacts

    @staticmethod
    def _row(tx, bucket, task_id):
        require(isinstance(bucket, str) and bucket in {'tasks', 'decisions_pending'}
                and isinstance(task_id, str) and bool(task_id), 'Invalid execution aggregate')
        row = tx.get(bucket, task_id)
        require(row is not None, 'Execution not found')
        require(row.get('id') == task_id, 'Execution storage identity mismatch')
        if bucket == 'tasks':
            message = row.get('message')
            require(isinstance(message, dict) and isinstance(message.get('when'), dict)
                    and 'deadline' in message['when'] and isinstance(message.get('what'), dict)
                    and isinstance(message['what'].get('details'), dict), 'Invalid stored task message shape')
        else:
            require(isinstance(row.get('input'), dict), 'Invalid stored decision input')
        require(type(row.get('attempt')) is int and row['attempt'] >= 0
                and type(row.get('generation')) is int and row['generation'] >= 0,
                'Invalid execution counters')
        require(type(row.get('recovery_sequence', 0)) is int and row.get('recovery_sequence', 0) >= 0,
                'Invalid recovery sequence')
        return row

    @staticmethod
    def _eligible(row, operation):
        budget = row.get('retry_budget')
        if operation == 'migrate':
            require(row['status'] == 'blocked' and row.get('error') == 'UnverifiedLegacyRetryBudget'
                    and budget is None and row['attempt'] > 0, 'Not an unverified legacy retry')
        elif operation == 'repair':
            require(row['status'] == 'blocked' and row.get('error') in
                    {'InvalidRetryBudget', 'InvalidExecutionDeadline', 'InvalidExecutionLease',
                     'InvalidExecutionClock', 'ClockDiscontinuity', 'RecoveryContextChanged',
                     'reconciliation_required'},
                    'Only corrupt controls, changed recovery context or a reconciled termination can be repaired')
        else:
            require(operation == 'resume', 'Invalid recovery operation')
            if row['status'] == 'expired' and budget is None:
                return
            require(isinstance(budget, dict), 'Resume requires a verified retry budget')
            positive_integer(budget.get('version'), 'Budget version')
            limit = positive_integer(budget.get('max_attempts'), 'Retry limit')
            require((row['status'] == 'failed' and row.get('error') == 'attempt budget exhausted'
                     and row['attempt'] >= limit) or row['status'] == 'expired',
                    'Only budget or deadline exhaustion can resume')

    @staticmethod
    def _reconciled(tx, row):
        """INV-OBSERVATION-001: a block for unrecorded provider effects is repaired only after the
        operator resolved every termination record the sink knows for this task. A local-only
        record that never reached the sink still stops the executor at the next run."""
        if row.get('error') != 'reconciliation_required':
            return
        pending = [record for record in tx.scan('observation_terminations')
                   if record.get('task_id') == row['id']
                   and record.get('status') in {'pending_reconciliation', 'unconfirmed'}]
        require(not pending, 'Termination records are still pending reconciliation')

    def _related(self, tx, bucket, row):
        try:
            return self._related_checked(tx, bucket, row)
        except ContractError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
            raise ContractError('Related recovery evidence unavailable or malformed') from exc

    def _related_checked(self, tx, bucket, row):
        if bucket != 'decisions_pending':
            return None
        if row.get('phase') != 'threshold_review':
            from codex_harness.application.decision_recovery import context
            return context(tx, row, self.org, self.artifacts)
        request = tx.get('threshold_review_requests', row['input']['request_id'])
        expected = {'lead:improvement': 'awaiting_lead', 'conductor': 'awaiting_conductor'}.get(row['actor'])
        require(request is not None and expected
                and row['id'] == digest([request['id'], row['actor']]), 'Threshold recovery identity mismatch')
        require(request['status'] == expected or (request['status'] == 'failed'
                and request.get('failure') == 'decision_attempt_budget_exhausted'
                and request.get('failed_decision') == row['id']), 'Threshold lifecycle changed')
        from codex_harness.application.threshold_reviews import ThresholdReviews
        from codex_harness.application.workflow import Workflow
        record = ThresholdReviews(Workflow(self.store, self.org), self.artifacts)._row(tx, request['row_id'])
        require(digest(record) == request['binding'], 'Threshold recovery input changed')
        return {'request': request, 'record': record, 'run': tx.get('threshold_proposal_runs', record['run_id'])}

    def validate_decision(self, tx, row):
        """Recheck the recovered dependencies before spending an attempt or committing effects."""
        reference = row.get('recovery_receipt')
        budget = row.get('retry_budget')
        if not reference:
            require(not row.get('recovery_sequence') and not (isinstance(budget, dict) and budget.get('recovery_ref')),
                    'Decision recovery receipt missing')
            return
        require(isinstance(reference, str), 'Invalid decision recovery receipt reference')
        receipt = tx.get('execution_recoveries', reference)
        packet = receipt.get('packet') if isinstance(receipt, dict) else None
        require(isinstance(packet, dict) and packet.get('bucket') == 'decisions_pending'
                and packet.get('task_id') == row['id'] and receipt.get('id') == reference == digest(packet),
                'Decision recovery receipt missing or mismatched')
        previous = receipt.get('previous')
        require(isinstance(previous, dict) and type(previous.get('generation')) is int
                and type(previous.get('recovery_sequence', 0)) is int
                and isinstance(budget, dict) and budget.get('recovery_ref') == reference
                and row.get('recovery_sequence') == previous.get('recovery_sequence', 0) + 1
                and type(row.get('generation')) is int and row['generation'] > previous['generation'],
                'Decision recovery generation changed')
        require(digest(self._related(tx, 'decisions_pending', row)) == receipt.get('result_related_hash'),
                'Recovered decision dependencies changed')

    def _evidence(self, refs):
        require(isinstance(refs, list) and 0 < len(refs) <= 8
                and all(isinstance(ref, str) for ref in refs) and len(set(refs)) == len(refs),
                'Unique immutable recovery evidence required')
        for ref in refs:
            try:
                self.artifacts.text(ref, 131072)
            except (OSError, UnicodeError) as exc:
                raise ContractError('Recovery evidence unavailable') from exc

    def _proposal(self, max_attempts, deadline, reason, evidence_refs, operator):
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 4000, 'Recovery reason required')
        require(isinstance(operator, str) and 0 < len(operator.strip()) <= 200, 'Operator audit label required')
        positive_integer(max_attempts, 'Recovery total attempt limit')
        self._evidence(evidence_refs)
        now = aware_time()
        due = deadline_time(deadline)
        require(due is None or due > now, 'Recovery deadline must be future')
        return now

    @staticmethod
    def _ceiling(row, bucket, max_attempts, deadline):
        require(max_attempts > row['attempt'], 'Recovery ceiling must exceed attempts already spent')
        old_deadline = (row.get('execution_deadline', row['message']['when']['deadline'])
                        if bucket == 'tasks' else row.get('execution_deadline'))
        require(old_deadline is None or deadline is not None, 'Existing deadline cannot be removed')

    def prepare(self, bucket, task_id, *, operation, max_attempts, deadline, reason,
                evidence_refs, operator, actor='conductor'):
        self.org.actor(actor, 'conductor')
        now = self._proposal(max_attempts, deadline, reason, evidence_refs, operator)
        with self.store.transaction() as tx:
            row = self._row(tx, bucket, task_id)
            self._eligible(row, operation)
            self._reconciled(tx, row)
            self._ceiling(row, bucket, max_attempts, deadline)
            related = self._related(tx, bucket, row)
        packet = {'version': 1, 'bucket': bucket, 'task_id': task_id, 'operation': operation,
                'expected_hash': digest(row), 'related_hash': digest(related), 'previous': row,
                'max_attempts': max_attempts, 'deadline': deadline, 'reason': reason,
                'evidence_refs': evidence_refs, 'operator': operator, 'actor': actor,
                'authority': 'trusted_local_operator', 'issued_at': now.isoformat(),
                'expires_at': (now + timedelta(minutes=15)).isoformat()}
        self._packet_size(packet)
        return packet

    @staticmethod
    def _packet_size(packet):
        try:
            json.dumps(packet, allow_nan=False)
            require(len(canonical(packet).encode('utf-8')) <= 1024 * 1024, 'Recovery packet exceeds budget')
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError('Recovery packet must be finite JSON') from exc

    def apply(self, packet, *, actor='conductor'):
        self.org.actor(actor, 'conductor')
        self._packet_size(packet)
        fields = {'version', 'bucket', 'task_id', 'operation', 'expected_hash', 'related_hash',
                  'previous', 'max_attempts', 'deadline', 'reason', 'evidence_refs', 'operator',
                  'actor', 'authority', 'issued_at', 'expires_at'}
        require(isinstance(packet, dict) and set(packet) == fields and type(packet['version']) is int
                and packet['version'] == 1 and packet['actor'] == actor
                and packet['authority'] == 'trusted_local_operator', 'Invalid recovery packet')
        require(isinstance(packet['bucket'], str) and packet['bucket'] in {'tasks', 'decisions_pending'}
                and isinstance(packet['task_id'], str) and bool(packet['task_id'])
                and isinstance(packet['operation'], str) and packet['operation'] in {'migrate', 'resume', 'repair'},
                'Invalid recovery target')
        positive_integer(packet['max_attempts'], 'Recovery total attempt limit')
        deadline_time(packet['deadline'])
        require(isinstance(packet['previous'], dict) and digest(packet['previous']) == packet['expected_hash'],
                'Recovery snapshot hash mismatch')
        identity = digest(packet)
        with self.store.transaction() as tx:
            receipt = tx.get('execution_recoveries', identity)
            if receipt:
                current = self._row(tx, packet['bucket'], packet['task_id'])
                require(receipt['packet'] == packet and digest(current) == receipt['result_hash'],
                        'Stale recovery retry after execution changed')
                related = self._related(tx, packet['bucket'], current)
                require(digest(related) == receipt['result_related_hash'],
                        'Stale recovery retry after execution changed')
                return {'replayed': True, 'receipt_id': identity, 'execution': current}
        # Validate content and artifact integrity before acquiring the mutation transaction.
        self._proposal(packet['max_attempts'], packet['deadline'], packet['reason'],
                       packet['evidence_refs'], packet['operator'])
        issued, expires = deadline_time(packet['issued_at']), deadline_time(packet['expires_at'])
        require(issued is not None and expires is not None and timedelta(0) < expires - issued <= timedelta(minutes=15),
                'Invalid recovery time window')
        with self.store.transaction() as tx:
            row = self._row(tx, packet['bucket'], packet['task_id'])
            receipt = tx.get('execution_recoveries', identity)
            if receipt:
                require(receipt['packet'] == packet and digest(row) == receipt['result_hash'], 'Stale recovery retry')
                related = self._related(tx, packet['bucket'], row)
                require(digest(related) == receipt['result_related_hash'], 'Stale recovery retry')
                return {'replayed': True, 'receipt_id': identity, 'execution': row}
            now = aware_time()
            require(issued <= now < expires, 'Recovery packet expired or not yet valid')
            due = deadline_time(packet['deadline'])
            require(due is None or due > now, 'Recovery deadline must be future')
            require(digest(row) == packet['expected_hash'], 'Recovery snapshot changed')
            self._eligible(row, packet['operation'])
            self._reconciled(tx, row)
            self._ceiling(row, packet['bucket'], packet['max_attempts'], packet['deadline'])
            related = self._related(tx, packet['bucket'], row)
            require(digest(related) == packet['related_hash'], 'Related recovery state changed')
            details = row['message']['what']['details'] if packet['bucket'] == 'tasks' else row['input']
            ticket_binding(tx, details)
            previous = deepcopy(row)
            old_budget = row.get('retry_budget')
            old_version = old_budget.get('version') if isinstance(old_budget, dict) else None
            version = old_version + 1 if type(old_version) is int and old_version > 0 else 1
            from codex_harness.application.execution_fence import advance as advance_fence
            advance_fence(tx, packet['bucket'], row['id'], row['generation'] + 1)
            row.update(status='retry', generation=row['generation'] + 1, lease_owner=None, lease_until=None,
                       error=None, result=None, failure=None, failure_receipt=None, execution_deadline=packet['deadline'],
                       recovery_sequence=row.get('recovery_sequence', 0) + 1, recovery_receipt=identity,
                       retry_budget={'version': version, 'max_attempts': packet['max_attempts'],
                                     'bound_at': now.isoformat(), 'origin': packet['operation'], 'recovery_ref': identity})
            row.pop('owner', None)
            row.pop('execution_clock', None)
            row.pop('completed_at', None)
            restored = deepcopy(related)
            if row.get('phase') == 'threshold_review' and related is not None and related['request']['status'] == 'failed':
                restored['request'] = {**related['request'], 'status': {'lead:improvement': 'awaiting_lead',
                            'conductor': 'awaiting_conductor'}[row['actor']], 'recovery_receipt': identity}
                for name in ('failure', 'failed_decision', 'completed_at'):
                    restored['request'].pop(name, None)
                tx.put('threshold_review_requests', restored['request']['id'], restored['request'])
            receipt = {'id': identity, 'packet': packet, 'previous': previous, 'previous_related': related,
                       'result_hash': digest(row), 'result_related_hash': digest(restored), 'at': now.isoformat(),
                       'authority': 'trusted_local_operator', 'human_acceptance': False}
            tx.put(packet['bucket'], packet['task_id'], row)
            tx.put('execution_recoveries', identity, receipt)
            tx.put('events', identity, {'type': 'execution.recovered', 'receipt_id': identity,
                   'bucket': packet['bucket'], 'task_id': row['id'], 'generation': row['generation'],
                   'sequence': row['recovery_sequence'], 'at': now.isoformat()})
            from codex_harness.application.execution_notices import record as execution_notice
            execution_notice(tx, self.org, row, packet['bucket'], 'execution_recovered', now.isoformat(), identity)
            return {'replayed': False, 'receipt_id': identity, 'execution': row}

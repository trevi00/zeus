"""Leased, ordered assessment of calculated threshold evidence; no apply authority."""
from codex_harness.domain.model import digest, envelope, require, utcnow


class ThresholdReviews:
    def __init__(self, workflow, artifacts):
        self.workflow, self.artifacts = workflow, artifacts
        self.store, self.org = workflow.store, workflow.org

    def _row(self, tx, row_id):
        row = tx.get('threshold_proposals', row_id)
        require(row is not None and row['activation_ready'] is False
                and row['status'] == 'calculated'
                and 'native_task_success_and_release_review_required' in row['activation_blockers'],
                'Calculated threshold record required')
        run = tx.get('threshold_proposal_runs', row['run_id'])
        require(run is not None and run['activation_ready'] is False and row in run['proposals'],
                'Threshold row is not bound to its collection run')
        document = self.artifacts.document(row['evidence_ref'])
        require(document['project_key'] == row['project_key']
                and row['proposal'] in document['proposals'], 'Threshold artifact binding changed')
        require(row['run_id'] == digest([row['project_key'], row['evidence_ref']])
                and row['id'] == digest([row['run_id'], row['proposal']['id']]), 'Threshold record identity changed')
        return row

    def request(self, row_id):
        self.org.actor('lead:improvement', 'lead')
        self.org.actor('conductor', 'conductor')
        with self.store.transaction() as tx:
            row = self._row(tx, row_id)
            binding = digest(row)
            identity = digest(['threshold-assessment-v1', binding])
            old = tx.get('threshold_review_requests', identity)
            if old:
                return old
            request = {'id': identity, 'row_id': row_id, 'binding': binding,
                'status': 'awaiting_lead', 'reviews': [], 'activation_ready': False,
                'scope': 'assessment_only_no_dispatch_or_activation', 'created_at': utcnow()}
            tx.put('threshold_review_requests', identity, request)
            self._queue(tx, request, 'lead:improvement')
            return request

    def _queue(self, tx, request, actor):
        key = digest([request['id'], actor])
        sender = 'conductor' if actor == 'lead:improvement' else 'lead:improvement'
        message = envelope('task.assign' if actor == 'lead:improvement' else 'review.result',
            sender, actor, 'assess_threshold', {'request_id': request['id'],
                'binding': request['binding']}, request['id'])
        self.org.authorize(message)
        tx.put('decisions_pending', key, {'id': key, 'actor': actor, 'phase': 'threshold_review',
            'input': {'request_id': request['id']}, 'message': message, 'status': 'pending', 'attempt': 0})

    def _prepare(self, tx, lease):
        require(lease.get('_bucket') == 'decisions_pending', 'Threshold decision lease required')
        current = self.workflow._owned(tx, lease)
        from codex_harness.application.execution_recovery import ExecutionRecovery
        ExecutionRecovery(self.store, self.org, self.artifacts).validate_decision(tx, current)
        require(current['actor'] == lease.get('actor'), 'Threshold lease actor mismatch')
        require(current['phase'] == 'threshold_review', 'Wrong threshold decision phase')
        request = tx.get('threshold_review_requests', current['input']['request_id'])
        require(request is not None, 'Threshold review request missing')
        require(current['id'] == digest([request['id'], current['actor']]), 'Threshold decision identity mismatch')
        expected = {'awaiting_lead': 'lead:improvement', 'awaiting_conductor': 'conductor'}.get(request['status'])
        require(current['actor'] == expected, 'Threshold review order changed')
        row = self._row(tx, request['row_id'])
        require(digest(row) == request['binding'], 'Threshold review input changed')
        return current, request, {'request_id': request['id'], 'binding': request['binding'],
            'record': row, 'prior_reviews': request['reviews'], 'scope': request['scope'],
            'execution': {'decision_id': current['id'], 'generation': current['generation']}}

    def prepare(self, lease):
        with self.store.transaction() as tx:
            return self._prepare(tx, lease)[2]

    def complete(self, lease, bundle, result):
        require(type(result.get('accepted')) is bool and isinstance(result.get('reason'), str),
                'Invalid threshold assessment')
        receipt = self.artifacts.document(result['execution_ref'])
        packet = self.artifacts.document(receipt['context_ref'])
        binding = receipt['research_binding']
        revision = bundle['record']['proposal']['policy_revision']
        require(packet['agent_id'] == lease['actor'] and packet['task_id'] == lease['id']
                and binding['stage'] == 'threshold_review' and binding['basis_revision'] == revision
                and result['basis_revision'] == revision
                and packet['required']['external_context']['ref'] == binding['evidence_ref']
                and self.artifacts.document(binding['evidence_ref'])['review'] == bundle,
                'Threshold execution receipt mismatch')
        inspection_blocked = bool(receipt.get('inspection_blocked'))
        require(bool(result.get('inspection_blocked')) == inspection_blocked,
                'Threshold inspection status differs from execution')
        require(not receipt.get('interrupted') or inspection_blocked,
                'Interrupted threshold review cannot complete')
        require(not inspection_blocked or result['accepted'] is False,
                'Blocked threshold execution cannot approve')
        if not inspection_blocked:
            answer = receipt['answer']
            require(isinstance(answer, dict) and type(answer.get('accepted')) is bool
                    and type(answer.get('blocked')) is bool and isinstance(answer.get('reason'), str),
                    'Threshold execution verdict missing')
            require(all(result.get(key) == value for key, value in receipt['answer'].items()),
                    'Threshold assessment differs from execution')
        blocked = bool(result.get('blocked') or result.get('inspection_blocked'))
        require(not blocked or not result['accepted'], 'Blocked threshold review cannot accept')
        with self.store.transaction() as tx:
            current, request, expected = self._prepare(tx, lease)
            # INV-THRESHOLD-REVIEW-001: lease, exact input and ordered review commit together.
            require(bundle == expected, 'Threshold review basis changed')
            request['reviews'].append({'actor': current['actor'], 'result': result,
                'decision_id': current['id'], 'generation': current['generation'], 'at': utcnow()})
            request['status'] = ('blocked' if blocked else 'rejected' if not result['accepted'] else
                'awaiting_conductor' if current['actor'] == 'lead:improvement' else 'assessed')
            current.update(status='blocked' if blocked else 'succeeded', result=result, completed_at=utcnow())
            tx.put('decisions_pending', current['id'], current)
            tx.put('threshold_review_requests', request['id'], request)
            if request['status'] == 'awaiting_conductor':
                self._queue(tx, request, 'conductor')
            return current

    @staticmethod
    def exhausted(tx, decision):
        request = tx.get('threshold_review_requests', decision['input']['request_id'])
        expected = ({'awaiting_lead': 'lead:improvement', 'awaiting_conductor': 'conductor'}
                    .get(request['status']) if request else None)
        if expected and decision['id'] == digest([request['id'], expected]):
            request.update(status='failed', failure='decision_attempt_budget_exhausted',
                           failed_decision=decision['id'], completed_at=utcnow())
            tx.put('threshold_review_requests', request['id'], request)

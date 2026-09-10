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
          'stale', 'not_approved', 'incomplete', 'not_succeeded', 'receipt_unbound', 'artifact_missing',
          'artifact_unbound', 'reviewer_unbound', 'scenario_mismatch', 'verdict_mismatch', 'authoritative')
EVALUATION_KIND = 'completion-evaluation'


def _excerpt(record):
    text = repr(record)
    return text if len(text) <= 2000 else text[:2000] + '…'


def _task_of(record):
    target = record.get('target') if isinstance(record, dict) else None
    task_id = target.get('task_id') if isinstance(target, dict) else None
    return task_id if type(task_id) is str else None


class CompletionAuthority:
    def __init__(self, store, artifacts=None, org=None):
        # Authority needs more than a well-formed record (review, PR #50): the runner receipt must be
        # the execution evidence the task itself recorded and exist as an immutable artifact, the
        # evaluation artifact must exist, the reviewer must be an independent organization actor, and
        # the scenario denominator must be the one the consumer's approved spec names.
        self.store, self.artifacts, self.org = store, artifacts, org

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

    def inspect(self, task_id, *, spec_revision, evaluation_artifact, expected_scenarios=None):
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
        unbound = self._provenance(task, last, expected_scenarios)
        if unbound:
            return {**report, **unbound}
        return {**report, 'state': 'authoritative', 'authority': True}

    def _provenance(self, task, last, expected_scenarios):
        """Values inside one JSON document prove nothing about each other; check them against their sources.

        Review (PR #50, round 2): existence of a file and a caller's strings are not provenance either.
        The execution artifact's own content must name this task and attempt; the evaluation artifact must
        be a completion evaluation bound to this task, attempt and spec revision, carry the scenario
        denominator the verdict must match, name the reviewer, and point at a verified reviewer execution
        (a succeeded task of that reviewer whose recorded evidence is that very artifact).
        """
        target = last['target']
        receipt = last['runner_receipt']
        result = task.get('result') if isinstance(task.get('result'), dict) else {}
        execution_ref = result.get('execution_ref')
        if type(execution_ref) is not str or receipt['id'] != execution_ref or 'sha256:' + receipt['digest'] != execution_ref:
            return {'state': 'receipt_unbound', 'reason': 'runner_receipt is not the execution evidence the task recorded'}
        if self.artifacts is None:
            return {'state': 'artifact_missing', 'reason': 'no artifact store to verify the receipt and evaluation artifact'}
        documents = {}
        for ref in (execution_ref, last['evaluation_artifact']):
            try:
                self.artifacts.inspect(ref)
                documents[ref] = self.artifacts.document(ref)
            except Exception as exc:
                return {'state': 'artifact_missing', 'reason': ref + ': ' + type(exc).__name__}
        execution, evaluation = documents[execution_ref], documents[last['evaluation_artifact']]
        if execution.get('task_id') != target['task_id'] or execution.get('attempt') != target['attempt']:
            return {'state': 'receipt_unbound', 'reason': 'execution artifact content names another task or attempt'}
        if (evaluation.get('kind') != EVALUATION_KIND or evaluation.get('task_id') != target['task_id']
                or evaluation.get('attempt') != target['attempt'] or evaluation.get('spec_revision') != last['spec_revision']):
            return {'state': 'artifact_unbound', 'reason': 'evaluation artifact content is not a completion evaluation of this task, attempt and spec revision'}
        spec_scenarios = evaluation.get('scenarios')
        if not isinstance(spec_scenarios, list) or not spec_scenarios or not all(type(s) is str and s for s in spec_scenarios):
            return {'state': 'artifact_unbound', 'reason': 'evaluation artifact declares no scenario denominator'}
        if expected_scenarios is not None:
            require(isinstance(expected_scenarios, list) and all(type(s) is str for s in expected_scenarios),
                    'expected_scenarios must be scenario names')
        for denominator, who in ((spec_scenarios, 'the evaluation artifact'), (expected_scenarios, 'the consumer')):
            if denominator is not None and sorted(set(denominator)) != sorted(set(last['scenarios']['expected'])):
                return {'state': 'scenario_mismatch', 'reason': 'verdict denominator differs from the scenarios ' + who + ' names'}
        reviewer = last['reviewer']
        if self.org is None or reviewer['actor'] not in self.org.agents or reviewer['actor'] == task.get('agent'):
            return {'state': 'reviewer_unbound', 'reason': 'reviewer is not an independent organization actor'}
        if evaluation.get('reviewer') != reviewer:
            return {'state': 'reviewer_unbound', 'reason': 'evaluation artifact names another reviewer'}
        review_ref = evaluation.get('execution_ref')
        try:
            require(type(review_ref) is str and review_ref.startswith('sha256:'), 'no reviewer execution reference')
            review = self.artifacts.document(review_ref)
            with self.store.transaction() as tx:
                review_task = tx.get('tasks', review.get('task_id')) if type(review.get('task_id')) is str else None
            review_result = review_task.get('result') if review_task and isinstance(review_task.get('result'), dict) else {}
            require(review_task is not None and review_task.get('agent') == reviewer['actor']
                    and review_task.get('status') == 'succeeded' and review_task.get('attempt') == review.get('attempt')
                    and review_result.get('execution_ref') == review_ref, 'reviewer execution is not a succeeded task of the reviewer')
        except Exception as exc:
            return {'state': 'reviewer_unbound', 'reason': 'no verified reviewer execution: ' + (str(exc)[:120] or type(exc).__name__)}
        # The reviewer execution's own recorded output must be the evaluation of this execution (review,
        # PR #50, round 3): a reviewer task that judged something else, linked from a caller-made document,
        # binds nothing; and the recorded verdict must be what that execution produced, so an explicit
        # rejection can never be recorded as an approval.
        evaluated = review.get('answer', {}).get('evaluated') if isinstance(review.get('answer'), dict) else None
        if not isinstance(evaluated, dict) or evaluated.get('target') != target or evaluated.get('spec_revision') != last['spec_revision']:
            return {'state': 'reviewer_unbound', 'reason': 'reviewer execution did not evaluate this execution and spec revision'}
        try:
            produced = parse_verdict({**{key: last[key] for key in KEYS},
                                      'target': evaluated['target'], 'verdict': evaluated.get('verdict'),
                                      'scenarios': evaluated.get('scenarios')})['scenarios']
        except ContractError:
            return {'state': 'verdict_mismatch', 'reason': 'reviewer output does not carry valid scenario results'}
        # INV-COMPLETION-001: exclusions include their approval provenance, not only scenario ids.
        same_scenarios = (sorted(produced['expected']) == sorted(last['scenarios']['expected'])
                          and sorted(produced['passed']) == sorted(last['scenarios']['passed'])
                          and sorted(produced['excluded'], key=lambda e: e['id'])
                          == sorted(last['scenarios']['excluded'], key=lambda e: e['id']))
        if evaluated.get('verdict') != last['verdict'] or not same_scenarios:
            return {'state': 'verdict_mismatch', 'reason': 'recorded verdict or scenario results differ from what the reviewer execution produced'}
        return None

    def require_authority(self, task_id, *, spec_revision, evaluation_artifact, expected_scenarios=None):
        report = self.inspect(task_id, spec_revision=spec_revision, evaluation_artifact=evaluation_artifact,
                              expected_scenarios=expected_scenarios)
        require(report['authority'], 'No completion authority: ' + report['state'])
        return report

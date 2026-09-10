"""FA-018: a completion verdict is authority only when bound to the execution it judged (INV-COMPLETION-001).

The upstream selector stored any event with a verdict string and a caller timestamp and picked
approved records by time alone. Here the schema is closed, bindings are checked against the
PostgreSQL-owned task row, order is recording order, every degraded ledger state is named, and
(review, PR #50) the evidence a verdict names is checked by content against its sources: the task's
own execution artifact, an evaluation artifact bound to task, attempt, spec and reviewer, and a
reviewer execution recorded as that reviewer's own succeeded task.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application.completion import (
    BUCKET,
    EVALUATION_KIND,
    REJECTIONS,
    STATES,
    CompletionAuthority,
)
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, canonical, envelope

SPEC = 'a' * 40
OTHER_SPEC = 'd' * 40
REVIEWER = 'lead:research'
OTHER_REVIEWER = 'lead:improvement'
SCENARIOS = ['login', 'checkout']


def backend_store(backend, request):
    return MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')


def running_task(store):
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    return workflow, workflow.claim('worker:implementation', 'owner-1')


class Case:
    """One task under evaluation with real evidence: artifacts written the way the runtime writes them."""

    def __init__(self, store, tmp_path, claim=True):
        self.store = store
        self.artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
        self.authority = CompletionAuthority(store, artifacts=self.artifacts, org=organization())
        self.workflow, self.task = running_task(store) if claim else (Workflow(store, organization()), None)
        self.evaluations = 0

    def execution_for(self, task):
        """What persist_result records for a worker turn: the result names its task and attempt."""
        return self.artifacts.put(canonical({'task_id': task['id'], 'attempt': task['attempt'], 'answer': {'summary': 'fixture'}}),
                                  'execution:' + task['id'])['ref']

    def finish(self, task=None, summary='done', execution_ref=None):
        task = task or self.task
        ref = execution_ref or self.execution_for(task)
        row = self.workflow.complete(task, {'summary': summary, 'execution_ref': ref})
        row['execution_ref'] = ref
        return row

    @staticmethod
    def evaluated(task, *, spec=SPEC, scenarios=None, verdict='approved'):
        """What a reviewer execution's own output states: which execution it judged, and what it found."""
        return {'target': {'task_id': task['id'], 'generation': task['generation'], 'attempt': task['attempt']},
                'spec_revision': spec, 'verdict': verdict,
                'scenarios': scenarios or {'expected': list(SCENARIOS), 'passed': list(SCENARIOS), 'excluded': []}}

    def reviewer_run(self, reviewer, task, *, succeed=True, evaluated=None):
        """A reviewer execution is the reviewer's own task in the ledger, with its own execution artifact."""
        self.evaluations += 1
        parent = organization().actor(reviewer).parent
        message = envelope('task.assign', parent, reviewer, 'plan', {'objective': f'evaluate {task["id"]} #{self.evaluations}'}, 'test')
        workflow = Workflow(self.store, organization())
        workflow.submit(message)
        review_task = workflow.claim(reviewer, 'reviewer-owner-' + str(self.evaluations))
        assert review_task is not None, 'the reviewer must be free to take the evaluation'
        ref = self.artifacts.put(canonical({'task_id': review_task['id'], 'attempt': review_task['attempt'],
                                            'answer': {'evaluated': evaluated or self.evaluated(task)}}),
                                 'execution:' + review_task['id'])['ref']
        if succeed:
            workflow.complete(review_task, {'summary': 'evaluated', 'execution_ref': ref})
        else:  # the run ended without success and is terminal, so the reviewer stays free for later evaluations
            workflow.cancel(review_task['id'], 'conductor', 'fixture: reviewer run abandoned')
        return ref

    def evaluation(self, task=None, *, reviewer=REVIEWER, kind='model', spec=SPEC, scenarios=SCENARIOS, reviewer_ran=True,
                    evaluated=None, execution_ref=None, **over):
        task = task or self.task
        if execution_ref is None and reviewer_ran:
            execution_ref = self.reviewer_run(reviewer, task, evaluated=evaluated or self.evaluated(task, spec=spec))
        document = {'kind': EVALUATION_KIND, 'task_id': task['id'], 'attempt': task['attempt'], 'spec_revision': spec,
                    'scenarios': list(scenarios), 'reviewer': {'actor': reviewer, 'kind': kind},
                    'execution_ref': execution_ref, **over}
        return self.artifacts.put(canonical(document), 'evaluation:' + task['id'])['ref']

    def verdict(self, task=None, *, execution_ref=None, evaluation=None, reviewer=REVIEWER, kind='model', spec=SPEC, **over):
        task = task or self.task
        target = {'task_id': task['id'], 'generation': task['generation'], 'attempt': task['attempt']}
        execution_ref = execution_ref or self.execution_for(task)
        reviewer = reviewer if isinstance(reviewer, dict) else {'actor': reviewer, 'kind': kind}
        if evaluation is None:
            # The reviewer execution produces what the verdict records: same target, spec, scenarios and verdict.
            produced = self.evaluated(task, spec=spec, scenarios=over.get('scenarios'), verdict=over.get('verdict', 'approved'))
            evaluation = self.evaluation(task, reviewer=reviewer['actor'], kind=reviewer['kind'], spec=spec, evaluated=produced)
        base = {'schema_version': 1, 'event': 'completion.verdict', 'verdict': 'approved', 'target': target,
                'spec_revision': spec, 'evaluation_artifact': evaluation,
                'runner_receipt': {'id': execution_ref, 'digest': execution_ref[7:], **target},
                'reviewer': reviewer,
                'scenarios': {'expected': list(SCENARIOS), 'passed': list(SCENARIOS), 'excluded': []},
                'observed_at': datetime.now(timezone.utc).isoformat()}
        return {**base, **over}

    def inspect(self, task=None, spec=SPEC, artifact=None, **kwargs):
        task = task or self.task
        if artifact is None:
            artifact = self.last_artifact
        return self.authority.inspect(task['id'], spec_revision=spec, evaluation_artifact=artifact, **kwargs)

    def record(self, record):
        self.last_artifact = record['evaluation_artifact']
        return self.authority.record(record)


FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
MALFORMED = [
    ('schema null', {'schema_version': None}, 'schema_version'),
    ('schema unknown', {'schema_version': 2}, 'schema_version'),
    ('schema text', {'schema_version': '1'}, 'schema_version'),
    ('unrelated event', {'event': 'unrelated'}, 'event'),
    ('verdict list', {'verdict': ['approved']}, 'verdict'),
    ('verdict false text', {'verdict': 'false'}, 'verdict'),
    ('completeness false text', {'completeness': 'false'}, 'exactly'),
    ('caller cross_target flag', {'cross_target': True}, 'exactly'),
    ('nan timestamp', {'observed_at': float('nan')}, 'observed_at'),
    ('numeric timestamp', {'observed_at': 200}, 'observed_at'),
    ('naive timestamp', {'observed_at': '2026-09-10T00:00:00'}, 'timezone'),
    ('future timestamp', {'observed_at': FUTURE}, 'future'),
    ('generation text', {'target': {'task_id': 'x', 'generation': '1', 'attempt': 1}}, 'generation'),
    ('generation bool', {'target': {'task_id': 'x', 'generation': True, 'attempt': 1}}, 'generation'),
    ('spec short', {'spec_revision': 'abc'}, 'spec_revision'),
    ('artifact bare', {'evaluation_artifact': 'b' * 64}, 'evaluation_artifact'),
    ('reviewer empty', {'reviewer': {'actor': ' ', 'kind': 'model'}}, 'reviewer.actor'),
    ('reviewer kind', {'reviewer': {'actor': 'lead:qa', 'kind': 'caller'}}, 'reviewer.kind'),
    ('duplicate scenario', {'scenarios': {'expected': ['a', 'a'], 'passed': ['a'], 'excluded': []}}, 'repeat'),
    ('passed outside expected', {'scenarios': {'expected': ['a'], 'passed': ['b'], 'excluded': []}}, 'subset'),
    ('exclusion unapproved', {'scenarios': {'expected': ['a'], 'passed': [], 'excluded': [{'id': 'a'}]}}, 'exactly'),
]


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_malformed_records_are_rejected_and_logged(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    task = case.task
    execution, evaluation = case.execution_for(task), case.evaluation()
    for name, mutation, match in MALFORMED:
        record = case.verdict(execution_ref=execution, evaluation=evaluation, **mutation)
        for _ in range(2):  # the same malformed record replayed lands on the same notice
            with pytest.raises(ContractError, match='Completion verdict rejected.*' + match):
                case.record(record)
    cross = case.verdict(execution_ref=execution, evaluation=evaluation)
    cross['runner_receipt'] = {**cross['runner_receipt'], 'task_id': 'someone-else'}
    with pytest.raises(ContractError, match='different execution'):
        case.record(cross)
    with case.store.transaction() as tx:
        assert tx.scan(BUCKET) == [], 'nothing malformed enters the verdict ledger'
        rejections = tx.scan(REJECTIONS)
    # Every distinct refusal is one structured notice; replays did not add rows.
    assert len(rejections) == len(MALFORMED) + 1
    assert all(r['reason'].startswith('Completion verdict rejected') and r['task_id'] in {task['id'], 'x'}
               for r in rejections)
    assert case.inspect(artifact=evaluation)['state'] == 'rejected_only'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_worker_success_is_not_completion_authority(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    evaluation = case.evaluation()
    assert case.inspect(artifact=evaluation)['state'] == 'not_evaluated'
    assert case.finish(summary='self-reported')['status'] == 'succeeded'
    report = case.inspect(artifact=evaluation)
    assert (report['state'], report['authority'], report['verdicts']) == ('not_evaluated', False, 0)
    with pytest.raises(ContractError, match='No completion authority: not_evaluated'):
        case.authority.require_authority(case.task['id'], spec_revision=SPEC, evaluation_artifact=evaluation)
    assert case.authority.inspect('no-such-task', spec_revision=SPEC, evaluation_artifact=evaluation)['state'] == 'no_ledger'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_verdict_binds_execution_spec_artifact_and_receipt(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    task = case.task
    execution = case.execution_for(task)
    behind = case.verdict(execution_ref=execution, target={'task_id': task['id'], 'generation': task['generation'] + 1, 'attempt': task['attempt']})
    behind['runner_receipt'] = {**behind['runner_receipt'], 'generation': task['generation'] + 1}
    with pytest.raises(ContractError, match='different execution than the current one'):
        case.record(behind)
    approved = case.verdict(execution_ref=execution)
    recorded = case.record(approved)
    assert recorded['changed'] and recorded['sequence'] == 1
    assert case.inspect()['state'] == 'not_succeeded', 'approved before the worker finished'
    case.finish(execution_ref=execution)
    report = case.inspect()
    assert report['state'] == 'authoritative' and report['authority'] and report['latest']['verdict'] == 'approved'
    assert case.authority.require_authority(task['id'], spec_revision=SPEC, evaluation_artifact=approved['evaluation_artifact'])['authority']
    # The same approved record proves nothing about another spec or another evaluation artifact.
    assert case.inspect(spec=OTHER_SPEC)['state'] == 'stale'
    assert case.inspect(artifact=case.evaluation())['state'] == 'stale'
    # Same scenario text under a different spec is a different verdict identity.
    other = case.record(case.verdict(execution_ref=execution, spec=OTHER_SPEC))
    assert other['changed'] and other['id'] != recorded['id'] and other['sequence'] == 2
    assert case.inspect(artifact=approved['evaluation_artifact'])['latest']['id'] == recorded['id']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_reclaimed_execution_makes_old_verdicts_stale(backend, request, tmp_path):
    store = backend_store(backend, request)
    case = Case(store, tmp_path, claim=False)
    workflow = case.workflow
    workflow.submit(assignment())
    first = workflow.claim('worker:implementation', 'owner-1', lease_seconds=1)
    case.record(case.verdict(first))
    time.sleep(1.2)
    second = workflow.claim('worker:implementation', 'owner-2', lease_seconds=60)
    assert second['generation'] == 2 and second['attempt'] == 2
    execution = case.execution_for(second)
    workflow.complete(second, {'summary': 'second attempt', 'execution_ref': execution})
    report = case.inspect(second)
    assert (report['state'], report['authority'], report['verdicts']) == ('stale', False, 1)
    with pytest.raises(ContractError, match='different execution than the current one'):
        case.record(case.verdict(first, reviewer=OTHER_REVIEWER))
    case.record(case.verdict(second, execution_ref=execution))
    assert case.inspect(second)['state'] == 'authoritative'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_recording_order_not_observed_time_selects_the_verdict(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    done = case.finish()
    base = datetime.now(timezone.utc)
    approved = case.verdict(execution_ref=done['execution_ref'], observed_at=(base + timedelta(seconds=10)).isoformat())
    rejected = case.verdict(execution_ref=done['execution_ref'], verdict='iterate', observed_at=base.isoformat(),
                            reviewer=OTHER_REVIEWER, kind='human', evaluation=approved['evaluation_artifact'])
    rejected['reviewer'] = {'actor': OTHER_REVIEWER, 'kind': 'human'}
    case.record(approved)
    assert case.inspect()['state'] == 'authoritative'
    case.record(rejected)  # collected later, observed earlier: still the current verdict
    assert case.inspect()['state'] == 'not_approved'
    replay = case.record({**approved, 'observed_at': (base + timedelta(seconds=30)).isoformat()})
    assert replay == {'id': replay['id'], 'changed': False, 'sequence': 1}
    assert case.inspect()['state'] == 'not_approved', 'an old acceptance never outranks the rejection'
    same_second = case.verdict(execution_ref=done['execution_ref'], observed_at=base.isoformat(), reviewer=OTHER_REVIEWER)
    case.record(same_second)
    assert case.inspect()['latest']['sequence'] == 3
    assert case.inspect()['state'] == 'authoritative'


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_scenario_denominator_is_explicit(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    done = case.finish()
    evaluation = case.evaluation()
    empty = {'expected': [], 'passed': [], 'excluded': []}
    case.record(case.verdict(execution_ref=done['execution_ref'], evaluation=evaluation, scenarios=empty))
    assert case.inspect()['state'] == 'incomplete', 'an empty denominator is not a full pass'
    partial = {'expected': SCENARIOS, 'passed': ['login'], 'excluded': []}
    case.record(case.verdict(execution_ref=done['execution_ref'], evaluation=evaluation, scenarios=partial))
    assert case.inspect()['state'] == 'incomplete'
    excluded = {'expected': SCENARIOS, 'passed': ['login'],
                'excluded': [{'id': 'checkout', 'approved_by': 'human:owner', 'revision': OTHER_SPEC,
                              'reason': 'payment sandbox unavailable this round'}]}
    case.record(case.verdict(execution_ref=done['execution_ref'], scenarios=excluded))
    report = case.inspect()
    assert report['state'] == 'authoritative' and report['latest']['complete']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_duplicate_and_concurrent_records_do_not_inflate(backend, request, tmp_path):
    case = Case(backend_store(backend, request), tmp_path)
    done = case.finish()
    record = case.verdict(execution_ref=done['execution_ref'])
    case.last_artifact = record['evaluation_artifact']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(case.authority.record, [record] * 8))
    assert sum(r['changed'] for r in results) == 1 and {r['sequence'] for r in results} == {1}
    report = case.inspect()
    assert report['verdicts'] == 1 and report['state'] == 'authoritative'
    with pytest.raises(ContractError, match='identity reused'):
        with case.store.transaction() as tx:
            row = tx.get(BUCKET, results[0]['id'])
            tx.put(BUCKET, row['id'], {**row, 'verdict': 'iterate'})
        case.authority.record(record)


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_authority_needs_real_evidence_an_independent_reviewer_and_the_approved_denominator(backend, request, tmp_path):
    # Review counterexamples (PR #50, rounds 1 and 2): a well-formed record whose receipt and artifact existed
    # nowhere, then artifacts that existed but were fixture labels with no reviewer ever having run, were
    # both `authoritative`. Neither existence nor a caller's strings are provenance.
    store = backend_store(backend, request)
    case = Case(store, tmp_path)
    task = case.task
    fabricated = 'sha256:' + 'f' * 64
    case.workflow.complete(task, {'summary': 'done', 'execution_ref': fabricated})
    case.record(case.verdict())
    report = case.inspect()
    assert report['state'] == 'receipt_unbound' and not report['authority'] and 'execution evidence' in report['reason']
    with pytest.raises(ContractError, match='No completion authority: receipt_unbound'):
        case.authority.require_authority(task['id'], spec_revision=SPEC, evaluation_artifact=case.last_artifact)
    # A second task whose completion names real evidence.
    second = Case(store, tmp_path / 'second')
    done = second.finish()
    good = second.verdict(execution_ref=done['execution_ref'])
    # No artifact store, or an empty one: the evidence cannot be confirmed.
    bare = CompletionAuthority(store)
    bare.record(good)
    assert bare.inspect(second.task['id'], spec_revision=SPEC, evaluation_artifact=good['evaluation_artifact'])['state'] == 'artifact_missing'
    empty_store = CompletionAuthority(store, artifacts=FileArtifacts(str(tmp_path / 'empty')), org=organization())
    missing = empty_store.inspect(second.task['id'], spec_revision=SPEC, evaluation_artifact=good['evaluation_artifact'])
    assert missing['state'] == 'artifact_missing' and done['execution_ref'] in missing['reason']
    assert second.inspect(artifact=good['evaluation_artifact'])['state'] == 'authoritative'
    # Artifacts that exist but whose content binds nothing (round 2): fixture labels are not evidence.
    third = Case(store, tmp_path / 'third')
    label_execution = third.artifacts.put(canonical({'fixture': 'execution evidence'}), 'fixture')['ref']
    label_evaluation = third.artifacts.put(canonical({'fixture': 'evaluation artifact'}), 'fixture')['ref']
    third.workflow.complete(third.task, {'summary': 'done', 'execution_ref': label_execution})
    third.record(third.verdict(execution_ref=label_execution, evaluation=label_evaluation))
    assert third.inspect()['state'] == 'receipt_unbound' and 'content' in third.inspect()['reason']
    fourth = Case(store, tmp_path / 'fourth')
    fourth_execution = fourth.execution_for(fourth.task)
    fourth.workflow.complete(fourth.task, {'summary': 'done', 'execution_ref': fourth_execution})
    label_evaluation = fourth.artifacts.put(canonical({'fixture': 'evaluation artifact'}), 'fixture')['ref']
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=label_evaluation))
    assert fourth.inspect()['state'] == 'artifact_unbound', 'an evaluation artifact must be a completion evaluation of this task'
    # The evaluation artifact binds task, attempt, spec, scenarios and reviewer.
    for wrong, state in (({'task_id': 'other-task'}, 'artifact_unbound'), ({'attempt': 9}, 'artifact_unbound'),
                         ({'spec': OTHER_SPEC}, 'artifact_unbound'), ({'scenarios': ['login']}, 'scenario_mismatch'),
                         ({'scenarios': []}, 'artifact_unbound'), ({'reviewer': OTHER_REVIEWER}, 'reviewer_unbound')):
        spec = wrong.pop('spec', SPEC)
        scenarios = wrong.pop('scenarios', SCENARIOS)
        reviewer_named = wrong.pop('reviewer', REVIEWER)
        evaluation = fourth.evaluation(spec=spec, scenarios=scenarios, reviewer=reviewer_named, **wrong)
        fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=evaluation))
        assert fourth.inspect()['state'] == state, (wrong, state)
    # The reviewer must be an independent organization actor whose evaluation run is a succeeded task of theirs.
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(reviewer='worker:implementation'), reviewer='worker:implementation'))
    assert fourth.inspect()['state'] == 'reviewer_unbound', 'the worker cannot review its own completion'
    ghost = fourth.artifacts.put(canonical({'kind': EVALUATION_KIND, 'task_id': fourth.task['id'], 'attempt': fourth.task['attempt'],
                                            'spec_revision': SPEC, 'scenarios': SCENARIOS, 'reviewer': {'actor': 'ghost:reviewer', 'kind': 'human'},
                                            'execution_ref': None}), 'fixture')['ref']
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=ghost, reviewer='ghost:reviewer', kind='human'))
    assert fourth.inspect()['state'] == 'reviewer_unbound'
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(reviewer_ran=False)))
    assert fourth.inspect()['state'] == 'reviewer_unbound' and 'no verified reviewer execution' in fourth.inspect()['reason']
    unfinished = fourth.artifacts.put(canonical({'kind': EVALUATION_KIND, 'task_id': fourth.task['id'], 'attempt': fourth.task['attempt'],
                                                 'spec_revision': SPEC, 'scenarios': SCENARIOS, 'reviewer': {'actor': REVIEWER, 'kind': 'model'},
                                                 'execution_ref': fourth.reviewer_run(REVIEWER, fourth.task, succeed=False)}), 'fixture')['ref']
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=unfinished))
    assert fourth.inspect()['state'] == 'reviewer_unbound', 'a reviewer run that never succeeded verifies nothing'
    # Round 3 (review 004): the reviewer execution's own output must be the evaluation of this execution.
    unrelated = Case(store, tmp_path / 'unrelated')
    elsewhere = fourth.reviewer_run(REVIEWER, unrelated.task, evaluated=fourth.evaluated(unrelated.task))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=fourth.evaluation(execution_ref=elsewhere)))
    report = fourth.inspect(expected_scenarios=SCENARIOS)
    assert report['state'] == 'reviewer_unbound' and 'did not evaluate this execution' in report['reason']
    with pytest.raises(ContractError, match='No completion authority: reviewer_unbound'):
        fourth.authority.require_authority(fourth.task['id'], spec_revision=SPEC, evaluation_artifact=fourth.last_artifact, expected_scenarios=SCENARIOS)
    # An explicit rejection by the reviewer execution can never be recorded as an approval.
    rejected_run = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, verdict='iterate'))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=rejected_run))
    assert fourth.inspect(expected_scenarios=SCENARIOS)['state'] == 'verdict_mismatch'
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=rejected_run, verdict='iterate'))
    assert fourth.inspect()['state'] == 'not_approved', 'recorded as what it was: a rejection'
    # Scenario results the reviewer did not produce cannot be recorded either.
    half = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, scenarios={'expected': SCENARIOS, 'passed': ['login'], 'excluded': []}))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=half))
    assert fourth.inspect()['state'] == 'verdict_mismatch'
    other_spec_run = fourth.evaluation(evaluated=fourth.evaluated(fourth.task, spec=OTHER_SPEC))
    fourth.record(fourth.verdict(execution_ref=fourth_execution, evaluation=other_spec_run))
    assert fourth.inspect()['state'] == 'reviewer_unbound'
    fourth.record(fourth.verdict(execution_ref=fourth_execution, reviewer=OTHER_REVIEWER, kind='human'))
    assert fourth.inspect()['state'] == 'authoritative'
    # The consumer may also name the scenarios its approved spec expects; they must agree with the artifact and the verdict.
    assert fourth.inspect(expected_scenarios=['login'])['state'] == 'scenario_mismatch'
    assert fourth.inspect(expected_scenarios=['checkout', 'login'])['state'] == 'authoritative'
    assert fourth.authority.require_authority(fourth.task['id'], spec_revision=SPEC, evaluation_artifact=fourth.last_artifact,
                                              expected_scenarios=SCENARIOS)['authority']
    with pytest.raises(ContractError, match='scenario names'):
        fourth.inspect(expected_scenarios='login')


def test_memory_corruption_is_a_named_state(tmp_path):
    case = Case(MemoryStore(), tmp_path)
    done = case.finish()
    first = case.record(case.verdict(execution_ref=done['execution_ref']))['id']
    case.store.data[BUCKET, first]['verdict'] = 'false'
    assert case.inspect()['state'] == 'corrupt'
    case.record(case.verdict(execution_ref=done['execution_ref'], reviewer=OTHER_REVIEWER))
    report = case.inspect()
    assert (report['state'], report['authority'], report['corrupt']) == ('partially_corrupt', False, 1)


def test_postgres_corruption_and_unreachable_store_are_distinct(isolated_pgstore, tmp_path):
    case = Case(isolated_pgstore, tmp_path)
    done = case.finish()
    first = case.record(case.verdict(execution_ref=done['execution_ref']))['id']
    assert case.inspect()['state'] == 'authoritative'
    with psycopg.connect(isolated_pgstore.dsn) as conn:
        conn.execute("UPDATE documents SET body = body || '{\"observed_at\": 200}' WHERE bucket=%s AND id=%s",
                     (BUCKET, first))
    report = case.inspect()
    assert (report['state'], report['authority'], report['corrupt']) == ('corrupt', False, 1)
    case.record(case.verdict(execution_ref=done['execution_ref'], reviewer=OTHER_REVIEWER))
    assert case.inspect()['state'] == 'partially_corrupt'
    with psycopg.connect(isolated_pgstore.dsn) as conn:
        conn.execute("UPDATE documents SET body = body - 'reviewer' WHERE bucket=%s AND id=%s", (BUCKET, first))
    assert case.inspect()['state'] == 'partially_corrupt'
    unreachable = CompletionAuthority(PostgresStore('postgresql://127.0.0.1:1/zeus?connect_timeout=1'))
    report = unreachable.inspect(case.task['id'], spec_revision=SPEC, evaluation_artifact=case.last_artifact)
    assert report['state'] == 'unreadable' and not report['authority'] and report['reason']
    with pytest.raises(ContractError, match='No completion authority: unreadable'):
        unreachable.require_authority(case.task['id'], spec_revision=SPEC, evaluation_artifact=case.last_artifact)


def test_every_named_state_is_reachable():
    # The classification is the contract; a state that no test reaches is a state no consumer can trust.
    reached = {'unreadable', 'no_ledger', 'corrupt', 'partially_corrupt', 'rejected_only', 'not_evaluated',
               'stale', 'not_approved', 'incomplete', 'not_succeeded', 'receipt_unbound', 'artifact_missing',
               'artifact_unbound', 'reviewer_unbound', 'scenario_mismatch', 'verdict_mismatch', 'authoritative'}
    assert reached == set(STATES)

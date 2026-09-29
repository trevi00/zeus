"""Ported SOURCE M7 suite `tests/test_model_routing.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_required_hook_plan_is_explicitly_important: S8 research: recurrence/hook lifecycle over the Harness

PORTING NOTES (S4 ported executor suites; the M7 assertions are unchanged):
- The M7 `Executor` and `Harness(store, organization())` are `m7_executor.Executor` / `m7_executor.Service`
  (a TEST shim over RunTask/ReviewDecisions; construction only). `Executor._run` is patched through the shim's
  `_run`, exactly as M7 patched `executor._run`.
- `IMPLEMENTATION` is imported from `execution.domain.output_contracts`; `FileArtifacts`/`MemoryStore` from storage.
- test_assignment_preserves_trusted_importance_into_implementation, test_plan_passes_trusted_action_and_keeps_review_default:
  SKIPPED, S8 evidence inspection: both drive `execute_one('worker:implementation')`, whose implement path runs the
  M7 `Executor._inspect_evidence` (EvidenceInspections/EvidenceInspector); the shim's `_inspect_evidence` raises
  "Evidence inspection is not wired (S8)", so the implement task retries instead of succeeding.
- test_lead_review_projects_only_importance_and_conductor_rework_preserves_it: SKIPPED, S5 coordination: the
  M7 `Workflow.handle(report)` (the report -> conductor decision hand-off) is not in the target Workflow.
"""

import json
from types import SimpleNamespace

import m7_executor
import pytest

from codex_harness.coordination.application.workflow import Workflow
from codex_harness.execution.domain.output_contracts import IMPLEMENTATION
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.routing.domain.model_selection import select_model
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore


@pytest.mark.parametrize(('workload', 'importance', 'model'), [
    ('design', None, 'gpt-6-astra'),
    ('final_validation', None, 'gpt-6-astra'),
    ('implementation', 'simple', 'gpt-6-astra'),
    ('implementation', 'important', 'gpt-6-astra'),
    ('implementation', None, 'gpt-6-astra'),
    ('implementation', 'unknown', 'gpt-6-astra'),
])
def test_conservative_domain_routing(workload, importance, model):
    selection = select_model(workload, importance)
    assert selection.requested_model == model
    assert selection.importance == ('unknown' if workload == 'implementation' and importance is None
                                    else importance or 'not_applicable')


@pytest.mark.parametrize('importance', ['routine', [], 7])
def test_unknown_importance_never_falls_through_to_simple(importance):
    with pytest.raises(ContractError, match='Unknown implementation importance'):
        select_model('implementation', importance)


def test_executor_sends_selection_and_seals_it_in_execution_receipt(tmp_path, monkeypatch):
    requested = []

    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, prompt, cwd, schema, *args, **kwargs):
            requested.append(kwargs['model'])
            return {'answer': {'summary': 'done', 'tests': []}, 'events': [],
                    'thread_id': 'thread', 'usage': {}, 'rotate': False,
                    'interrupted': False, 'requested_model': kwargs['model']}

    monkeypatch.setattr('m7_executor.AppServer', Runtime)
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    executor = m7_executor.Executor(m7_executor.Service(MemoryStore()),
                        SimpleNamespace(_git=lambda *args, **kwargs: 'revision'), artifacts)
    result = executor._run('worker:implementation', 'task', 'Implement', {}, str(tmp_path),
                           IMPLEMENTATION, workload='implementation', importance='simple')

    assert requested == ['gpt-6-astra']
    receipt = json.loads(artifacts.read(result['execution_ref']))
    assert receipt['model_selection'] == {
        'policy': 'model-routing.v2-unqualified-astra', 'workload': 'implementation',
        'importance': 'simple', 'requested_model': 'gpt-6-astra'}


@pytest.mark.parametrize('importance, expected', [
    ('simple', 'simple'), ('important', 'important'), (None, None),
])
def test_assignment_preserves_trusted_importance_into_implementation(tmp_path, monkeypatch,
                                                                    importance, expected):
    pytest.skip("S8: evidence inspection (M7 Executor._inspect_evidence over EvidenceInspections/EvidenceInspector) is not wired in the target")
    service = m7_executor.Service(MemoryStore())
    git = SimpleNamespace(
        repository=tmp_path,
        _git=lambda *args, **kwargs: 'revision',
        prepare=lambda *args: {'path': str(tmp_path)},
        capture=lambda workspace: {'revision': 'candidate', 'base': 'revision', 'tree': 'tree'},
    )
    executor = m7_executor.Executor(service, git, FileArtifacts(str(tmp_path / 'artifacts')))
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        if kwargs['workload'] == 'design':
            return {'objective': 'change', 'acceptance_criteria': ['works'], 'allowed_paths': ['src/']}
        return {'summary': 'done', 'tests': [], 'execution_ref': 'sha256:fixture'}

    monkeypatch.setattr(executor, '_run', run)
    details = {'objective': 'change', 'acceptance_criteria': ['works']}
    if importance is not None:
        details['importance'] = importance
    plan = envelope('task.assign', 'conductor', 'lead:improvement', 'plan', details, 'routing')
    executor.workflow.submit(plan)
    assert executor.execute_one('lead:improvement')['status'] == 'succeeded'
    with service.store.transaction() as tx:
        implement = next(row['message'] for row in tx.scan('outbox')
                         if row['message']['what']['action'] == 'implement')
    executor.workflow.submit(implement)
    assert executor.execute_one('worker:implementation')['status'] == 'succeeded'

    assert calls[0]['workload'] == 'design'
    assert calls[1]['workload'] == 'implementation'
    assert calls[1]['importance'] == expected


def test_plan_passes_trusted_action_and_keeps_review_default(tmp_path, monkeypatch):
    pytest.skip("S8: evidence inspection (M7 Executor._inspect_evidence over EvidenceInspections/EvidenceInspector) is not wired in the target")
    for name in ('ZEUS_CLAUDE_ASSIGNMENTS', 'ZEUS_CLAUDE_MODEL', 'ZEUS_CLAUDE_MAX_BUDGET_USD'):
        monkeypatch.delenv(name, raising=False)
    service = m7_executor.Service(MemoryStore())
    git = SimpleNamespace(
        repository=tmp_path, _git=lambda *args, **kwargs: 'revision',
        prepare=lambda *args: {'path': str(tmp_path)},
        capture=lambda workspace: {'revision': 'candidate', 'base': 'revision', 'tree': 'tree'},
    )
    executor = m7_executor.Executor(service, git, FileArtifacts(str(tmp_path / 'artifacts')))
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if kwargs['workload'] == 'design':
            return {'objective': 'change', 'acceptance_criteria': ['works'], 'allowed_paths': ['src/']}
        return {'summary': 'done', 'tests': [], 'execution_ref': 'sha256:fixture'}

    monkeypatch.setattr(executor, '_run', run)
    executor.workflow.submit(envelope('task.assign', 'conductor', 'lead:improvement', 'plan',
                                      {'objective': 'change', 'acceptance_criteria': ['works']}, 'routing'))
    assert executor.execute_one('lead:improvement')['status'] == 'succeeded'
    with service.store.transaction() as tx:
        implement = next(row['message'] for row in tx.scan('outbox')
                         if row['message']['what']['action'] == 'implement')
    executor.workflow.submit(implement)
    assert executor.execute_one('worker:implementation')['status'] == 'succeeded'

    (plan_args, plan_kwargs), (_, implement_kwargs) = calls
    assert plan_args[0] == 'lead:improvement' and plan_args[6] is True
    assert plan_kwargs['action'] == 'plan' and plan_kwargs['workload'] == 'design'
    assert implement_kwargs['action'] == 'implement' and implement_kwargs['workload'] == 'implementation'
    # Without host enablement the plan stays on Codex; a decision (action None) always does.
    policy = executor.execution_policy
    assert policy.select(role='lead:improvement', action='plan', workload='design', read_only=True).provider == 'codex'
    assert policy.select(role='lead:improvement', action=None, workload='final_validation',
                         read_only=True).provider == 'codex'


@pytest.mark.parametrize(('phase', 'actor', 'next_action'), [
    ('review_lead', 'lead:improvement', 'implement'),
    ('review_conductor', 'conductor', 'plan'),
])
def test_rejection_preserves_simple_implementation_classification(tmp_path, monkeypatch,
                                                                  phase, actor, next_action):
    service = m7_executor.Service(MemoryStore())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *args: {},
                          review_workspace=lambda *args: str(tmp_path),
                          _git=lambda *args, **kwargs: '' if args[0] == 'status' else 'revision')
    executor = m7_executor.Executor(service, git, FileArtifacts(str(tmp_path / 'artifacts')))
    candidate = {'revision': 'revision', 'base': 'base', 'tree': 'tree',
                 'author': 'worker:implementation'}
    data = {'candidate': candidate,
            'origin': {'plan': {'origin': {'importance': 'simple'}}}}
    if phase == 'review_conductor':
        release = executor.releases.propose(candidate, {'checks': ['tests'], 'revision': 'base'})
        executor.releases.review(release['id'], 'lead:improvement', 'revision', True, 'fixture')
        data['release_id'] = release['id']
    with service.store.transaction() as tx:
        tx.put('decisions_pending', 'decision', {
            'id': 'decision', 'actor': actor, 'phase': phase, 'input': data,
            'message': envelope('task.assign', 'lead:improvement', 'worker:implementation',
                                'implement', {}, 'routing'),
            'status': 'pending', 'attempt': 0})
    monkeypatch.setattr(executor, '_run', lambda *args, **kwargs: {
        'accepted': False, 'blocked': False, 'reason': 'fix it',
        'execution_ref': 'sha256:review'})

    assert executor.decide_one(actor)['status'] == 'succeeded'
    with service.store.transaction() as tx:
        rework = next(row['message'] for row in tx.scan('outbox')
                      if row['message']['what']['action'] == next_action)
    details = rework['what']['details']
    if phase == 'review_lead':
        assert details['plan']['origin']['importance'] == 'simple'
    else:
        assert details['importance'] == 'simple'


def test_lead_review_projects_only_importance_and_conductor_rework_preserves_it(tmp_path, monkeypatch):
    pytest.skip("S5: coordination Workflow.handle (M7 application/workflow.handle) is not in the target")
    service = m7_executor.Service(MemoryStore())
    git = SimpleNamespace(repository=tmp_path, inspect=lambda *args: {},
                          review_workspace=lambda *args: str(tmp_path),
                          _git=lambda *args, **kwargs: '' if args[0] == 'status' else 'revision')
    executor = m7_executor.Executor(service, git, FileArtifacts(str(tmp_path / 'artifacts')))
    candidate = {'revision': 'revision', 'base': 'base', 'tree': 'tree',
                 'author': 'worker:implementation'}
    implementation = {
        'candidate': candidate,
        'origin': {'plan': {'origin': {'importance': 'simple', 'large': 'x' * 10000},
                            'unrelated': 'discard'}, 'other': 'discard'},
    }
    message = envelope('task.assign', 'lead:improvement', 'worker:implementation',
                       'implement', {}, 'projected-routing')
    with service.store.transaction() as tx:
        tx.put('decisions_pending', 'lead-review', {
            'id': 'lead-review', 'actor': 'lead:improvement', 'phase': 'review_lead',
            'input': implementation, 'message': message, 'status': 'pending', 'attempt': 0})

    verdicts = iter([True, False])
    monkeypatch.setattr(executor, '_run', lambda *args, **kwargs: {
        'accepted': next(verdicts), 'blocked': False, 'reason': 'fix it',
        'execution_ref': 'sha256:review'})
    lead = executor.decide_one('lead:improvement')
    assert lead['result']['origin'] == {'plan': {'origin': {'importance': 'simple'}}}
    with service.store.transaction() as tx:
        report = next(row['message'] for row in tx.scan('outbox')
                      if row['message']['what']['action'] == 'review')
    Workflow(service.store, service.org).handle(report)

    assert executor.decide_one('conductor')['status'] == 'succeeded'
    with service.store.transaction() as tx:
        replan = next(row['message'] for row in tx.scan('outbox')
                      if row['message']['what']['action'] == 'plan')
    assert replan['what']['details']['importance'] == 'simple'

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope

URL = 'https://github.com/owner/repo'
REV = 'a' * 40


@pytest.fixture
def setup(tmp_path, monkeypatch):
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    calls, prompts = [], []
    config = {'shortlist': {'source_url': URL},
              'final': {'source_url': URL, 'source_revision': REV, 'title': 'Improve',
                        'objective': 'Improve', 'evidence': 'README', 'acceptance_criteria': []},
              'interrupt': {}, 'failure': None, 'revision': REV}
    collection = {'artifact': artifacts.put('collected source', 'fixture')['ref'],
                  'items': [{'url': URL, 'summary': '한' * 30000}]}
    readme = artifacts.put('README한' * 10000, 'fixture')['ref']

    def collect(source):
        calls.append('collect')
        return collection

    def detail(url):
        calls.append('detail')
        assert url == URL
        if config['failure'] == 'detail':
            raise OSError('detail unavailable')
        return {'url': URL, 'revision': config['revision'], 'readme_ref': readme}

    class Runtime:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, *args, **kw):
            assert len(prompt.encode('utf-8')) <= 22000
            packet = json.loads(prompt)
            prompts.append(packet)
            stage = packet['required'].get('research_context', {}).get('stage', 'final')
            calls.append(stage)
            if config.get('callback'):
                config['callback'](stage)
            event = {'method': 'item/completed', 'params': {'item': {'id': stage, 'type': 'command'}}}
            kw['on_event'](event)
            if config['failure'] == stage:
                raise OSError('runtime unavailable')
            interrupted = config['interrupt'].get(stage, 0) > 0
            if interrupted:
                config['interrupt'][stage] -= 1
            return {'answer': config[stage], 'events': [event], 'thread_id': stage,
                    'usage': {'totalTokens': 123}, 'rotate': interrupted, 'interrupted': interrupted}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    executor = Executor(service, SimpleNamespace(repository=tmp_path, _git=lambda *a, **kw: 'harness'),
                        artifacts, research=SimpleNamespace(collect=collect, github_detail=detail))
    message = envelope('task.assign', 'lead:research', 'worker:github', 'research',
                       {'source': 'github'}, 'fixture')
    task = executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, service=service, artifacts=artifacts, calls=calls,
                           prompts=prompts, config=config, collection=collection, task=task)


def test_order_provenance_overflow_and_measurement(setup):
    s = setup
    completed = s.executor.execute_one('worker:github')
    assert s.calls == ['collect', 'shortlist', 'detail', 'final']
    assert completed['status'] == 'succeeded'
    result = completed['result']
    assert result['basis_revision'] == 'harness'
    assert result['source_revision'] == result['source_details']['revision'] == REV
    assert result['source_artifact'] == s.collection['artifact']
    final = s.prompts[-1]['required']
    provenance = final['research_context']
    assert provenance['source_revision'] == REV and provenance['source_url'] == URL
    assert final['recovery']['sources'] == {}
    for prefix in ('readme', 'source'):
        path = Path(provenance[prefix + '_file'])
        ref = provenance['readme_ref' if prefix == 'readme' else 'source_artifact']
        assert path.read_text(encoding="utf-8") == s.artifacts._body(ref)
    evidence = json.loads(Path(final['external_context']['file']).read_text(encoding='utf-8'))
    assert evidence['readme_excerpt'].startswith('README한')
    assert len(evidence['readme_excerpt'].encode()) <= 10000
    for ref in (result['execution_ref'], result['shortlist_execution_ref']):
        record = json.loads(s.artifacts._body(ref))
        assert record['elapsed_seconds'] >= 0 and record['usage']['totalTokens'] == 123
        context = json.loads(s.artifacts._body(record['context_ref']))
        assert context['required']['research_context']['stage'] in {'shortlist', 'final'}
    assert result['research_attempt'] == 1


@pytest.mark.parametrize('failure', ['shortlist_url', 'shortlist_missing', 'detail', 'revision',
                                   'final_url', 'final_revision', 'final_missing'])
def test_invalid_evidence_never_completes(setup, failure):
    s = setup
    if failure == 'shortlist_url':
        s.config['shortlist']['source_url'] = 'https://example.com'
    if failure == 'shortlist_missing':
        s.config['shortlist'] = {}
    if failure == 'detail':
        s.config['failure'] = 'detail'
    if failure == 'revision':
        s.config['revision'] = 'invalid'
    if failure == 'final_url':
        s.config['final']['source_url'] = 'https://github.com/other/repo'
    if failure == 'final_revision':
        s.config['final']['source_revision'] = 'b' * 40
    if failure == 'final_missing':
        del s.config['final']['source_revision']
    assert s.executor.execute_one('worker:github')['status'] == 'retry'
    with s.service.store.transaction() as tx:
        messages = [r['message'] for r in tx.scan('outbox')]
        assert len(messages) == 1 and messages[0]['type'] == 'execution.notice'
        assert messages[0]['what']['details']['reason_code'] == 'execution_failed'
        assert tx.get('tasks', s.task['id'])['status'] == 'retry'
    if not failure.startswith('final'):
        assert 'final' not in s.calls


@pytest.mark.parametrize('stage', ['shortlist', 'final'])
def test_stage_interruptions_use_only_matching_recovery(setup, stage):
    s = setup
    s.config['interrupt'][stage] = 1
    assert s.executor.execute_one('worker:github')['status'] == 'succeeded'
    matching = [p for p in s.prompts if p['required']['research_context']['stage'] == stage]
    assert len(matching) == 2
    assert matching[0]['required']['recovery']['sources'] == {}
    assert 'checkpoint' in matching[1]['required']['recovery']['sources']


def reconcile_and_repair(s, task_id, resolution='rerun'):
    """INV-OBSERVATION-001: a failure after provider entry blocks the task; the operator reconciles
    the termination record, then re-queues through the existing execution-recovery repair path."""
    from codex_harness.application.execution_recovery import ExecutionRecovery
    [record] = s.executor.observer.pending_terminations(task_id)
    s.executor.observer.resolve_termination(record['record_id'], resolution=resolution, operator='test-operator',
                                            reason='explicit test decision')
    recovery = ExecutionRecovery(s.service.store, s.service.org, s.artifacts)
    evidence = s.artifacts.put('operator reviewed the termination record', 'test-evidence')['ref']
    packet = recovery.prepare('tasks', task_id, operation='repair', max_attempts=3, deadline=None,
                              reason='reconciled', evidence_refs=[evidence], operator='test-operator')
    return recovery.apply(packet)


@pytest.mark.parametrize('stage', ['shortlist', 'detail', 'final'])
def test_retry_after_failure_recollects_and_retrieves_before_final(setup, stage):
    s = setup
    s.config['failure'] = stage
    first = s.executor.execute_one('worker:github')
    if stage == 'detail':
        # The failure happens between provider calls: nothing unrecorded, ordinary retry.
        assert first['status'] == 'retry'
    else:
        # The transport failed after the provider was entered: blocked until reconciled.
        assert first['status'] == 'blocked' and first['error'] == 'reconciliation_required'
        assert s.executor.execute_one('worker:github') is None
        reconcile_and_repair(s, s.task['id'])
    s.config['failure'] = None
    s.calls.clear()
    result = s.executor.execute_one('worker:github')
    assert result['status'] == 'succeeded' and result['result']['research_attempt'] == 2
    assert s.calls == ['collect', 'shortlist', 'detail', 'final']
    if stage == 'shortlist':
        assert 'progress' in s.prompts[1]['required']['recovery']['sources']
    assert s.prompts[-1]['required']['recovery']['sources'] == {}


@pytest.mark.parametrize('stage', ['shortlist', 'final'])
def test_stale_execution_cannot_record_progress_checkpoint_or_complete(setup, stage):
    s = setup
    def revoke(current):
        if current == stage:
            with s.service.store.transaction() as tx:
                task = tx.get('tasks', s.task['id'])
                task['generation'] += 1
                tx.put('tasks', task['id'], task)
    s.config['callback'] = revoke
    # Lease loss is a non-authoritative outcome; it must not terminate serve().
    assert s.executor.execute_one('worker:github')['status'] == 'stale'
    with s.service.store.transaction() as tx:
        assert not tx.scan('decisions_pending')
    with s.service.store.transaction() as tx:
        assert not tx.scan('outbox')
        session = tx.get('sessions', 'worker:github')
        assert session is None if stage == 'shortlist' else session['generation'] == 1


def test_geeknews_remains_single_invocation(setup):
    s = setup
    with s.service.store.transaction() as tx:
        task = tx.get('tasks', s.task['id'])
        task['message']['what']['details']['source'] = 'geeknews'
        tx.put('tasks', task['id'], task)
    assert s.executor.execute_one('worker:github')['status'] == 'succeeded'
    assert s.calls == ['collect', 'final']


@pytest.mark.parametrize('change', ['none', 'revision', 'artifact', 'stage', 'harness'])
def test_recovery_binding_rejects_changed_evidence_and_stage(setup, change):
    from codex_harness.adapters.executor import GITHUB_RESEARCH

    s = setup
    evidence = {'provenance': {'source_revision': REV, 'readme_ref': 'first'}}
    def run(stage):
        return s.executor._run('worker:github', 'same-task', 'Evaluate', evidence,
                               str(s.executor.git.repository), GITHUB_RESEARCH, True, stage=stage)
    run('final')
    if change == 'revision':
        evidence['provenance']['source_revision'] = 'b' * 40
    if change == 'artifact':
        evidence['provenance']['readme_ref'] = 'second'
    if change == 'harness':
        s.executor.git._git = lambda *a, **kw: 'new-harness'
    run('shortlist' if change == 'stage' else 'final')
    recovery = s.prompts[-1]['required']['recovery']['sources']
    assert bool(recovery) == (change == 'none')
    assert len(s.prompts) == 2  # Always regenerate evaluation; checkpoint is context only.


def test_stale_session_generation_rejects_checkpoint(setup):
    s = setup
    def advance(stage):
        with s.service.store.transaction() as tx:
            tx.put('sessions', 'worker:github', {'generation': 7, 'checkpoint': {}})
    s.config['callback'] = advance
    result = s.executor.execute_one('worker:github')
    # The checkpoint failed after the provider ran: the failure is recorded, then the task is blocked.
    assert result['status'] == 'blocked' and result['error'] == 'reconciliation_required'
    assert 'Stale session' in result['attempt_outcomes'][-1]['error']
    with s.service.store.transaction() as tx:
        messages = [r['message'] for r in tx.scan('outbox')]
        assert [m['type'] for m in messages] == ['execution.notice', 'execution.notice']
        assert sorted(m['what']['details']['reason_code'] for m in messages) == ['execution_failed', 'reconciliation_required']
        assert tx.get('sessions', 'worker:github')['generation'] == 7
    [pending] = s.executor.observer.pending_terminations(s.task['id'])
    assert pending['boundary'] == 'checkpoint' and pending['invocation_outcome'] == 'accepted'


def test_preflight_failure_uses_existing_execution_failure_reporting(setup):
    from codex_harness.adapters.output_schema import CAUSE, preflight

    s = setup

    def reject_schema(stage):
        preflight({'properties': {'version': {'const': 1}}})

    s.config['callback'] = reject_schema
    result = s.executor.execute_one('worker:github')
    # Raised from inside the transport after entry: recorded as a failure, then blocked.
    assert result['status'] == 'blocked' and CAUSE in result['attempt_outcomes'][-1]['error']
    with s.service.store.transaction() as tx:
        failures = [r for r in tx.scan('decisions_pending') if r['phase'] == 'diagnose']
        assert len(failures) == 1
        receipt = s.artifacts.document(failures[0]['input']['evidence_ref'])
        assert CAUSE in receipt['error']
        assert receipt['task_id'] == s.task['id']
        assert tx.get('tasks', s.task['id'])['status'] != 'succeeded'

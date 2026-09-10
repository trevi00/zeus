"""FA-016: progress records bind generation, sequence, event identity and occurrence vs collection time."""
import json
import time

import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import (
    IMPLEMENTATION,
    Executor,
    progress_event_id,
    progress_occurrence,
)
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.project_skills import initialize
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@example.invalid')
    initialize(root, 'stack: {language: python}')
    git._git('add', '.')
    git._git('commit', '-qm', 'project definition')
    return root, git, FileArtifacts(str(tmp_path / 'artifacts'))


def completed(item_id, at_ms=None, status='completed'):
    params = {'item': {'id': item_id, 'type': 'commandExecution', 'status': status}}
    if at_ms is not None:
        params['completedAtMs'] = at_ms
    return {'method': 'item/completed', 'params': params}


def runtime_factory(events, prompts):
    class Runtime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, prompt, *args, **kwargs):
            prompts.append(json.loads(prompt))
            for event in events:
                kwargs['on_event'](event)
            return {'answer': {'summary': 'fixture', 'tests': []}, 'thread_id': 'fixture',
                    'usage': {}, 'rotate': False, 'interrupted': False, 'events': []}
    return Runtime


def test_progress_records_generation_sequence_identity_and_two_clocks(project, monkeypatch):
    root, git, artifacts = project
    store = MemoryStore()
    service = Harness(store, organization())
    executor = Executor(service, git, artifacts)
    workflow = executor.workflow
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner')
    events = [completed('exec-1', 1_788_751_585_964), {'method': 'thread/tokenUsage/updated',
              'params': {'tokenUsage': {'last': {'totalTokens': 10}, 'modelContextWindow': 100}}},
              'not-json shard', {'method': 'item/completed', 'params': 'garbage'},
              completed('exec-2'), {'method': 'turn/started', 'params': {}}]
    prompts = []
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', runtime_factory(events, prompts))
    executor._run('worker:implementation', lease['id'], 'Record progress', {}, str(root), IMPLEMENTATION, lease=lease)
    with store.transaction() as tx:
        progress = tx.get('execution_progress', lease['id'])
    assert progress['generation'] == lease['generation'] == 1 and progress['attempt'] == lease['attempt'] == 1
    assert progress['sequence'] == 3, 'two completions and one usage update; malformed and ignored events add none'
    assert progress['malformed_events'] == 2 and len(progress['malformed_recent']) == 2
    for ref in progress['malformed_recent']:
        retained = artifacts.document(ref)
        assert retained['malformed'] and retained['event'] in {"'not-json shard'", str({'method': 'item/completed', 'params': 'garbage'})}
    assert progress['last_completed'] == {'id': 'exec-2', 'type': 'commandExecution', 'status': 'completed',
                                          'evidence': progress['last_record'], 'sequence': 3, 'occurred_at': None}
    assert progress['event_id'] == 'item/completed:exec-2:completed'
    assert progress['occurred_at'] is None and progress['collected_at'] == progress['at']
    first = artifacts.document(progress['recent'][0])
    assert first['event']['params']['item']['id'] == 'exec-1'
    assert progress_occurrence(first['event']) == '2026-09-07T03:26:25.964000+00:00'
    assert progress_occurrence(completed('x')) is None and progress_occurrence({'emittedAtMs': -5}) is None
    assert progress_event_id({'method': 'm', 'params': {}}, 'sha256:abc') == 'm:sha256:abc'


def test_stale_generation_cannot_write_progress_and_replay_keeps_order(project, monkeypatch):
    root, git, artifacts = project
    store = MemoryStore()
    service = Harness(store, organization())
    executor = Executor(service, git, artifacts)
    workflow = executor.workflow
    workflow.submit(assignment())
    stale = workflow.claim('worker:implementation', 'first-owner', lease_seconds=1)
    time.sleep(1.2)
    current = workflow.claim('worker:implementation', 'second-owner', lease_seconds=60)
    assert current['generation'] == 2
    prompts = []
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer',
                        runtime_factory([completed('new-1', 1_788_751_585_000), completed('new-2', 1_788_751_584_000)], prompts))
    executor._run('worker:implementation', current['id'], 'Current generation', {}, str(root), IMPLEMENTATION, lease=current)
    with store.transaction() as tx:
        before = tx.get('execution_progress', current['id'])
    assert before['generation'] == 2 and before['sequence'] == 2
    # Arrival order defines the sequence; new-2's earlier occurrence time is kept as data, never reordered.
    assert before['last_completed']['id'] == 'new-2' and before['last_completed']['sequence'] == 2
    assert before['occurred_at'] == '2026-09-07T03:26:24+00:00'
    assert [artifacts.document(ref)['event']['params']['item']['id'] for ref in before['recent']] == ['new-1', 'new-2']
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer',
                        runtime_factory([completed('old-1', 1_788_751_580_000)], prompts))
    with pytest.raises(ContractError, match='Stale or expired'):
        executor._run('worker:implementation', stale['id'], 'Stale generation', {}, str(root), IMPLEMENTATION, lease=stale)
    with store.transaction() as tx:
        after = tx.get('execution_progress', current['id'])
    assert after == before, 'a stale generation never rewrites progress'

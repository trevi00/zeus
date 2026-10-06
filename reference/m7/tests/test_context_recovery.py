import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import IMPLEMENTATION, Executor
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError


def test_every_recovery_prompt_is_bounded_and_preserves_external_history(tmp_path, monkeypatch):
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    huge = '한글' * 30000
    with service.store.transaction() as tx:
        tx.put('sessions', 'worker:implementation', {'generation': 1, 'checkpoint': {'task_id': 'task', 'history': huge}})
        tx.put('execution_progress', 'task', {'history': huge})
    prompts = []

    class Runtime:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, *args, **kwargs):
            prompts.append(json.loads(prompt))
            assert len(prompt.encode('utf-8')) <= 22000
            return {'answer': {'summary': 'done', 'tests': []}, 'thread_id': str(len(prompts)),
                    'usage': {}, 'rotate': len(prompts) == 1, 'interrupted': len(prompts) == 1,
                    'events': [{'method': 'item/completed', 'params': {'output': huge}}]}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    executor = Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision'), artifacts)
    plan = {'objective': 'fix', 'acceptance_criteria': ['preserve this'], 'allowed_paths': ['src/'],
            'origin': {'history': huge}}
    executor._run('worker:implementation', 'task', 'Implement', {'plan': plan}, str(tmp_path), IMPLEMENTATION)
    assert len(prompts) == 2
    for prompt in prompts:
        assert prompt['required']['task_contract'] == {k: plan[k] for k in ('objective', 'acceptance_criteria', 'allowed_paths')}
        external = prompt['required']['external_context']
        assert artifacts._body(external['ref']) == json.dumps(
            {'plan': plan}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        reader = prompt['required']['artifact_reader']
        assert reader['operations']['index'] == ['index', '--limit', '8000']
        assert reader['operations']['pointer'][:3] == ['pointer', '--pointer', '<RFC6901>']
        assert external['reader_argv_prefix'] == [
            sys.executable, '-m', 'codex_harness.adapters.artifact_reader', '--root',
            str(artifacts.root), '--ref', external['ref']]
        for source in prompt['required']['recovery']['sources'].values():
            assert artifacts.inspect(source['ref'])['characters'] > 0
            assert source['reader_argv_prefix'][-1] == source['ref']
    invocation = [*prompts[0]['required']['external_context']['reader_argv_prefix'],
                  *prompts[0]['required']['artifact_reader']['operations']['index']]
    inspected = subprocess.run(invocation, capture_output=True, check=False, text=True)
    assert inspected.returncode == 0
    inspection = json.loads(inspected.stdout)
    assert inspection['ref'] == prompts[0]['required']['external_context']['ref']
    assert len(inspected.stdout) <= 8000
    completed = prompts[1]['required']['recovery']['sources']['completed']['ref']
    assert huge in artifacts._body(completed)


def test_true_acceptance_overflow_rejects_before_runtime(tmp_path, monkeypatch):
    def forbidden(**kw):
        pytest.fail('Runtime must not start')
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', forbidden)
    executor = Executor(Harness(MemoryStore(), organization()), SimpleNamespace(_git=lambda *a, **k: 'revision'),
                        FileArtifacts(str(tmp_path / 'artifacts')))
    with pytest.raises(ContractError, match='Required contract exceeds budget'):
        executor._run('worker:implementation', 'task', 'Implement',
                      {'plan': {'objective': 'fix', 'acceptance_criteria': ['한' * 30000]}}, str(tmp_path), IMPLEMENTATION)

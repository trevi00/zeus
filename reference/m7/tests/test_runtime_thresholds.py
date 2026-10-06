import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_threshold_collection import policy_repo as source_policy_repo

from codex_harness.adapters.runtime_thresholds import resolve_policy
from codex_harness.domain.model import ContractError


@pytest.fixture
def policy_repo(tmp_path):
    return source_policy_repo.__wrapped__(tmp_path)


@pytest.mark.parametrize('text', ['{}', '{"version":true,"overrides":{}}',
    '{"version":1,"version":1,"overrides":{}}',
    '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":true}}',
    '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":NaN}}',
    '{"version":1,"overrides":{"skill_match.FULL_BODY_MIN_SCORE":Infinity}}',
    '{"version":1,"overrides":{"lib.repeat_error_tracker.STRIKE_THRESHOLD":9}}',
    '{"version":1,"overrides":{"ratio_tracker.WARN_THRESHOLD":4}}'])
def test_invalid_or_unwired_policy_cannot_be_loaded(text):
    with pytest.raises(ContractError):
        resolve_policy(text)


def test_native_default_drift_is_detected(monkeypatch):
    from codex_harness.adapters import runtime_thresholds

    monkeypatch.setitem(runtime_thresholds.NATIVE_DEFAULTS, 'skill_match.FULL_BODY_MIN_SCORE', 4)
    with pytest.raises(ContractError, match='default differs'):
        resolve_policy('{"version":1,"overrides":{}}')


@pytest.mark.parametrize('value,full', [(4, 0), (2, 1), (0, 1), (-1, 1), (3.5, 0)])
def test_packaged_override_changes_actual_router_and_git_proposer_together(policy_repo, value, full):
    root, git = policy_repo
    source = Path(__file__).resolve().parents[1] / 'src'
    shutil.copytree(source, root / 'src', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (root / 'src/codex_harness/resources/threshold-policy.json').write_text(json.dumps({
        'version': 1, 'overrides': {'skill_match.FULL_BODY_MIN_SCORE': value}}), encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'candidate threshold override')
    program = '''
import json
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.skill_routing import route_skills
from codex_harness.adapters.threshold_policy import current_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.threshold_proposals import ThresholdProposals
from codex_harness.domain.model import ContextItem
git = GitWorkspace('.', '../workspaces')
artifacts = FileArtifacts('../artifacts')
policy = current_policy(git)
body = '---\\nkeywords: alpha beta gamma\\n---\\nSELECTED'
ref = artifacts.put(body, 'fixture')['ref']
path = '.harness/skills/_common/example.md'
record = {'path':path, 'file':path, 'content_ref':ref, 'pipeline_boost':0}
_, summary = route_skills(git, artifacts, '.', policy['revision'], 'alpha beta gamma',
    [ContextItem('project-skill:'+path, body, ref, policy['revision'], 15)], [record])
value = policy['values']['skill_match.FULL_BODY_MIN_SCORE']
store = MemoryStore()
with store.transaction() as tx:
    tx.put('skill_history', 'fixture', {'events': [
        {'at': f'2026-01-01T00:00:{i:02d}Z', 'top': [
            {'score':score, 'body_chars':500} for score in (value, value + 2)]}
        for i in range(40)]})
run = ThresholdProposals(store, artifacts, lambda: current_policy(git)).collect('fixture')
doc = artifacts.document(run['evidence_ref'])
assert len(doc['proposals']) == 1
proposal = doc['proposals'][0]
assert proposal['current'] == value
assert {row['value'] for row in proposal['alternatives']} == {value - 1, value + 1}
print(json.dumps({'full': summary['full'], 'routing': summary['policy']['min_full_score'],
    'proposal': doc['policy']['values']['skill_match.FULL_BODY_MIN_SCORE']}))
'''
    process = subprocess.run([sys.executable, '-c', program], cwd=root,
        env={**os.environ, 'PYTHONPATH': str(root / 'src')}, capture_output=True, text=True, timeout=45)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {'full': full, 'routing': value, 'proposal': value}

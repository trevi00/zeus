import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import IMPLEMENTATION, Executor
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.project_skills import initialize, parse_profile, project_context
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.project_skills import eligible_paths, select_skill_paths


def test_multistack_legacy_yaml_preserves_version_spelling_and_extensions():
    profile = parse_profile('''backend:
  language: java
  framework: springboot
  version: 3.10
frontend:
  language: typescript
  framework: react
  version: 18
extensions: [flutter/outpos-agent, _gsd]
''')
    paths = eligible_paths(profile)
    assert paths[:4] == ['_common', 'java/springboot-3.10', 'java/springboot', 'java/3.10']
    assert 'typescript/18.x' in paths and paths[-2:] == ['flutter/outpos-agent', '_gsd']


@pytest.mark.parametrize('text', [
    'stack:\n  language: python\n  language: java',
    'extensions: [../outside]', 'extensions: [/absolute]', 'extensions: [C:\\escape]',
    'schema_version: 2', 'unexpected: field',
    'stacks: []\nstack: {language: python}',
    'stack: &recursive {language: *recursive}',
    '!x\nstack: {language: python}\nstack: {language: java}',
    'stack: !x {language: python, language: java}',
    'stack: !!python/object/apply:builtins.dict {}',
    '[' * 2000 + 'x' + ']' * 2000,
    '#' * 65537,
    'project_id: invalid', 'project_id: 00000000-0000-0000-0000-000000000000',
], ids=lambda text: f'yaml-{len(text)}')
def test_invalid_profile_never_falls_back_to_all_skills(text):
    with pytest.raises(ContractError):
        parse_profile(text)


def test_selection_excludes_other_frameworks_and_preserves_packaged_skills():
    profile = parse_profile('stack: {language: python, framework: fastapi}')
    inventory = ['_common/base.md', 'python/style.md', 'python/fastapi/routes.md',
                 'python/fastapi/testing/SKILL.md', 'python/django/SKILL.md',
                 'java/lang/style.md', 'python/_index.md']
    assert set(select_skill_paths(profile, inventory)) == {
        '_common/base.md', 'python/style.md', 'python/fastapi/routes.md',
        'python/fastapi/testing/SKILL.md'}
    assert select_skill_paths(parse_profile('stacks: []'), inventory) == ['_common/base.md']


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@example.invalid')
    initialize(root, 'stack: {language: python, framework: fastapi}')
    for path, body in {'_common/base.md': 'COMMON_ONLY',
                       'python/fastapi/routes.md': 'FASTAPI_ELIGIBLE',
                       'java/lang/style.md': 'JAVA_MUST_NOT_LOAD'}.items():
        target = root / '.harness/skills' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'project definition')
    return root, git, FileArtifacts(str(tmp_path / 'artifacts'))


def test_init_is_exclusive_and_git_pin_ignores_uncommitted_configuration(project):
    root, git, artifacts = project
    revision = git._git('rev-parse', 'HEAD')
    with pytest.raises(FileExistsError):
        initialize(root, 'stack: {language: java}')
    (root / '.harness/tech-stack.yaml').write_text('stack: {language: java}')
    items, summary = project_context(git, artifacts, str(root), revision)
    assert {i.body for i in items} == {'COMMON_ONLY', 'FASTAPI_ELIGIBLE'}
    assert summary['selected'] == 2
    assert artifacts.document(summary['manifest_ref'])['revision'] == revision
    nested = root / 'src'
    nested.mkdir()
    nested_items, _ = project_context(git, artifacts, str(nested), revision)
    assert nested_items == items


def test_actual_executor_context_contains_only_eligible_pinned_skills(project, monkeypatch):
    root, git, artifacts = project
    big = root / '.harness/skills/python/fastapi/big.md'
    big.write_text('LARGE_SKILL_BODY ' * 3000)
    git._git('add', '.harness/skills/python/fastapi/big.md')
    git._git('commit', '-qm', 'large skill fixture')
    prompts = []
    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, *args, **kwargs):
            assert len(prompt.encode('utf-8')) <= 22000
            prompts.append(json.loads(prompt))
            return {'answer': {'summary': 'fixture', 'tests': []}, 'thread_id': 'fixture',
                    'usage': {}, 'rotate': False, 'interrupted': False, 'events': []}
    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    executor = Executor(Harness(MemoryStore(), organization()), git, artifacts)
    executor._run('worker:implementation', 'task', 'Test context routing',
                  {'large_evidence': 'x' * 25000}, str(root), IMPLEMENTATION)
    text = json.dumps(prompts[0])
    assert 'FASTAPI_ELIGIBLE' in text and 'COMMON_ONLY' in text
    assert 'JAVA_MUST_NOT_LOAD' not in text
    selection = prompts[0]['required']['project_skills']
    assert (selection['selected'], selection['included'], selection['omitted']) == (3, 2, 1)
    manifest = json.loads(Path(selection['file']).read_text(encoding='utf-8'))
    large_record = next(r for r in manifest['skills'] if r['path'].endswith('/big.md'))
    assert Path(large_record['file']).read_text().startswith('LARGE_SKILL_BODY')
    (root / '.harness/tech-stack.yaml').write_text('stack: {language: java}')
    git._git('add', '.harness/tech-stack.yaml')
    git._git('commit', '-qm', 'switch stack')
    executor._run('worker:implementation', 'task', 'Test context routing', {}, str(root), IMPLEMENTATION)
    assert 'JAVA_MUST_NOT_LOAD' in json.dumps(prompts[1])
    assert 'FASTAPI_ELIGIBLE' not in json.dumps(prompts[1])
    assert prompts[1]['required']['recovery']['sources'] == {}
    git._git('rm', '-r', '.harness')
    git._git('commit', '-qm', 'remove project skill configuration')
    executor._run('worker:implementation', 'task', 'Test context routing', {}, str(root), IMPLEMENTATION)
    assert prompts[2]['required']['project_skills']['status'] == 'not_configured'
    assert prompts[2]['required']['recovery']['sources'] == {}
    assert 'JAVA_MUST_NOT_LOAD' not in json.dumps(prompts[2])


def test_profile_symlink_in_git_is_rejected(project):
    root, git, artifacts = project
    blob = git._git('rev-parse', 'HEAD:.harness/tech-stack.yaml')
    git._git('update-index', '--cacheinfo', f'120000,{blob},.harness/tech-stack.yaml')
    git._git('commit', '-qm', 'fixture symlink mode')
    with pytest.raises(ContractError, match='regular Git file'):
        project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))


def test_real_skill_history_annotation_and_recovery_survive_other_task_observation(project, monkeypatch, capsys):
    root, git, artifacts = project
    (root / '.harness/stages.yaml').write_text('stages: []\n', encoding='utf-8')
    (root / '.harness/skills/python/fastapi/routes.md').write_text(
        '---\nkeywords: [alpha, beta, gamma]\n---\nFASTAPI_ELIGIBLE', encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'history fixture')
    prompts = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, *args, **kwargs):
            prompts.append(json.loads(prompt))
            kwargs['on_event']({'method': 'item/completed', 'params': {
                'item': {'id': 'completed-' + str(len(prompts)), 'type': 'commandExecution',
                         'status': 'completed'}}})
            return {'answer': {'summary': 'fixture', 'tests': []}, 'thread_id': 'fixture',
                    'usage': {}, 'rotate': False, 'interrupted': False, 'events': []}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    store = MemoryStore()
    executor = Executor(Harness(store, organization()), git, artifacts)
    for index in range(3):
        executor._run('worker:implementation', 'weak-' + str(index), 'alpha', {},
                      str(root), IMPLEMENTATION)
    executor._run('worker:implementation', 'main', 'alpha beta gamma', {},
                  str(root), IMPLEMENTATION)
    first = prompts[-1]
    full = next(i for i in first['evidence'] if i['id'].endswith('/routes.md'))
    assert 'historical_advisory' in full['body'] and 'FASTAPI_ELIGIBLE' in full['body']
    old_history = first['required']['project_skills']['history']['ref']
    with store.transaction() as tx:
        original_progress = tx.get('execution_progress', 'main')
        checkpoint = tx.get('sessions', 'worker:implementation')
        # Verify compatibility with a checkpoint written by the previous draft.
        checkpoint['checkpoint']['research_binding']['skill_history_ref'] = old_history
        tx.put('sessions', 'worker:implementation', checkpoint)
    executor._run('lead:improvement', 'other-task', 'alpha', {}, str(root), IMPLEMENTATION)
    executor._run('worker:implementation', 'main', 'alpha beta gamma', {},
                  str(root), IMPLEMENTATION)
    resumed = prompts[-1]
    assert resumed['required']['project_skills']['history']['ref'] != old_history
    recovery = resumed['required']['recovery']['sources']
    assert set(recovery) == {'checkpoint', 'progress'}
    assert artifacts.document(recovery['progress']['ref']) == original_progress
    assert artifacts.document(recovery['checkpoint']['ref']) == checkpoint
    assert 'skill_history_ref' not in resumed['required']['research_context']
    from codex_harness.adapters.skill_audit import main

    project_id = resumed['required']['project_skills']['project_id']
    assert main(['--project-id', project_id, '--json'], store=store) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit['invocations'] == 5  # three weak, one full, another task; retry is not a sample
    assert audit['dim_weight'] == {'kw': 7}
    assert audit['skills'][0]['path'].endswith('/routes.md')
    from codex_harness.domain.model import digest

    with store.transaction() as tx:
        history = tx.get('skill_history', digest('uuid:' + project_id))
    assert len(history['events']) == 5
    assert all(event['top'][0]['body_chars'] == len('FASTAPI_ELIGIBLE')
               for event in history['events'])
    executor._run('worker:implementation', 'main', 'changed objective', {},
                  str(root), IMPLEMENTATION)
    assert prompts[-1]['required']['recovery']['sources'] == {}


def test_selected_skill_symlink_is_rejected(project):
    root, git, artifacts = project
    path = '.harness/skills/_common/base.md'
    blob = git._git('rev-parse', 'HEAD:' + path)
    git._git('update-index', '--cacheinfo', f'120000,{blob},{path}')
    git._git('commit', '-qm', 'fixture skill symlink mode')
    with pytest.raises(ContractError, match='regular Git file'):
        project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))


def test_cli_legacy_import_preserves_extra_metadata_and_never_overwrites(tmp_path):
    root = tmp_path / 'project'
    (root / '.claude').mkdir(parents=True)
    legacy = root / '.claude/tech-stack.yaml'
    source = ('stack: {language: java, framework: springboot, version: 3.10, test_command: mvn}\n'
              'database: {type: mysql, version: 5.7}\norm: mybatis\n'
              'mobile: {framework: android}\n')
    legacy.write_text(source)
    script = Path(__file__).resolve().parents[1] / 'scripts/project_init.py'
    env = {**os.environ, 'PYTHONPATH': str(script.parents[1] / 'src')}
    argv = [sys.executable, str(script), str(root), '--from-claude']
    first = subprocess.run(argv, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    output = json.loads(first.stdout)['profile']
    assert output['metadata']['legacy_fields']['database']['version'] == '5.7'
    assert output['metadata']['stack_fields']['stack']['test_command'] == 'mvn'
    assert output['metadata']['unmapped_stack_blocks']['mobile']['framework'] == 'android'
    assert output['stacks'][0]['version'] == '3.10'
    assert parse_profile((root / '.harness/tech-stack.yaml').read_text()) == output
    assert legacy.read_text() == source
    second = subprocess.run(argv, env=env, capture_output=True, text=True)
    assert second.returncode == 2 and 'Traceback' not in second.stderr
    assert json.loads(second.stderr)['error'] == 'FileExistsError'

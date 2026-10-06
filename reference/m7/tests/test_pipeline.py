import hashlib
import json
import shutil
from importlib.resources import files

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.project_skills import load_yaml, project_context
from codex_harness.domain.model import ContractError
from codex_harness.domain.pipeline import merge_stages, recommend, tokens


def asset(name):
    return load_yaml(files('codex_harness.resources').joinpath(
        'baldrix_pipeline', name).read_text('utf-8'))


def test_all_bundled_source_bytes_match_pinned_manifest():
    root = files('codex_harness.resources').joinpath('baldrix_pipeline')
    provenance = json.loads(root.joinpath('provenance.json').read_text('utf-8'))
    assert len(provenance['files']) == 10
    for item in provenance['files']:
        assert hashlib.sha256(root.joinpath(item['destination']).read_bytes()).hexdigest() == item['sha256']


@pytest.mark.parametrize('language,legacy', [('java', 'stages.yaml'),
    ('flutter', 'stages-flutter.yaml'), ('rust', 'stages-rust.yaml')])
def test_core_overlay_reproduces_all_legacy_consumer_stage_fields(language, legacy):
    merged = merge_stages(asset('stages.core.yaml'), asset(f'overlays/{language}.overlay.yaml'))
    expected = asset(legacy)
    expected = expected['stages'] if isinstance(expected, dict) else expected
    assert len(merged) == len(expected)
    for actual, original in zip(merged, expected):
        consumer_keys = {'id', 'name', 'dge', 'input', 'output', 'artifact',
                         'gate', 'skills', 'optional', 'phase'}
        assert {k: v for k, v in actual.items() if k in consumer_keys} == {
            k: v for k, v in original.items() if k in consumer_keys}


def test_recommendation_preserves_last_observation_gaps_optional_and_final_cap():
    stages = [{'id': 'first', 'output': 'missing.md'},
              {'id': 'second', 'output': '[a.md, b.md]'},
              {'id': 'optional', 'optional': 'true', 'output': 'optional.md',
               'dge': 'evaluator', 'skills': ['review'] }]
    result = recommend(stages, ['.harness/design/b.md', 'optional.md'])
    assert result['stage']['id'] == 'optional'
    assert result['skills'] == ['review.md'] and result['phase'] == 'review'
    assert [s['id'] for s in result['observed_outputs']] == ['second']
    assert result['verified_complete'] is False
    assert recommend(stages[:2], ['a.md'])['stage']['id'] == 'second'


def test_outputs_are_literal_bounded_observations_and_src_heuristic_is_explicit():
    assert not recommend([{'id': 'a', 'output': '../outside'}], ['outside'])['observed_outputs']
    assert not recommend([{'id': 'a', 'output': 'migrations/*.sql'}],
                         ['migrations/one.sql'])['observed_outputs']
    result = recommend([{'id': 'a', 'output': 'src/missing.py'}], ['src/other.py'])
    assert result['observed_outputs'][0]['src_presence_heuristic'] is True
    assert tokens("['a', b]", skills=True) == ['a', 'b']


@pytest.mark.parametrize('stages', [[{'id': 'a'}, {'id': 'a'}],
    [{'id': 'bad/path'}], [{'id': 'a', 'skills': {'x': 'y'}}],
    [{'id': 'a', 'optional': 'maybe'}]])
def test_invalid_definitions_do_not_silently_disable_recommendation(stages):
    with pytest.raises(ContractError):
        recommend(stages, [])


def test_node_missing_stage_definitions_remain_visible():
    stages = merge_stages(asset('stages.core.yaml'), asset('overlays/node.overlay.yaml'))
    result = recommend(stages, ['er-diagram.md'])
    assert result['stage']['id'] == 'api-design'
    assert result['incomplete_definition'] is True


def test_git_override_boost_is_stack_filtered_and_changes_only_after_commit(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@localhost')
    contents = {
        '.harness/tech-stack.yaml': 'stack: {language: python}',
        '.harness/stages.yaml': 'stages:\n- id: design\n  output: design.md\n'
                               '  skills: [plan]\n- id: build\n  skills: [build]\n  dge: generator\n',
        '.harness/skills/_common/plan.md': 'PLAN',
        '.harness/skills/python/build.md': 'BUILD',
        '.harness/skills/java/build.md': 'EXCLUDED',
    }
    for path, body in contents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    git._git('add', '.')
    git._git('commit', '-qm', 'fixture')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    revision = git._git('rev-parse', 'HEAD')
    before, meta = project_context(git, artifacts, str(root), revision)
    assert meta['pipeline'][0]['stage_id'] == 'design'
    assert max(before, key=lambda item: item.priority).body == 'PLAN'
    (root / 'design.md').write_text('observed')
    assert project_context(git, artifacts, str(root), revision)[1] == meta
    git._git('add', '.')
    git._git('commit', '-qm', 'output')
    after, new = project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))
    assert new['pipeline'][0]['stage_id'] == 'build'
    assert max(after, key=lambda item: item.priority).body == 'BUILD'
    assert all(item.body != 'EXCLUDED' for item in after)
    assert new['manifest_ref'] != meta['manifest_ref']


@pytest.mark.parametrize('body', ['x: &x [*x]', 'x: &a [x,x,x,x,x,x,x,x,x,x]\ny: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\nz: [*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b,*b]'])
def test_yaml_alias_expansion_is_bounded_before_manifest_serialization(body):
    with pytest.raises(ContractError):
        load_yaml(body)


def test_bundled_recommendations_preserve_metadata_without_cross_language_boost(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@localhost')
    contents = {'.harness/tech-stack.yaml': 'stacks: [{language: java}, {language: node}]',
                '.harness/skills/java/doc-writer.md': 'JAVA',
                '.harness/skills/node/doc-writer.md': 'NODE'}
    for path, body in contents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    git._git('add', '.')
    git._git('commit', '-qm', 'fixture')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    items, info = project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))
    assert {item.body: item.priority for item in items} == {'JAVA': 18, 'NODE': 15}
    manifest = artifacts.document(info['manifest_ref'])
    assert manifest['pipeline']['recommendations'][1]['overlay_metadata']['testgen']['framework'] == 'cucumber-js'
    legacy = root / '.claude/stages.yaml'
    legacy.parent.mkdir()
    legacy.write_text('stages: [{id: legacy, dge: designer}]')
    git._git('add', '.')
    git._git('commit', '-qm', 'legacy override')
    assert project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))[1]['pipeline'][0]['stage_id'] == 'legacy'
    (root / '.harness/stages.yaml').write_text('stages: [{id: canonical}]')
    git._git('add', '.')
    git._git('commit', '-qm', 'canonical override')
    assert project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))[1]['pipeline'][0]['stage_id'] == 'canonical'


@pytest.mark.parametrize('failure', ['missing_hash', 'corrupt_body'])
def test_bundle_integrity_failures_are_classified(tmp_path, monkeypatch, failure):
    from codex_harness.adapters import project_pipeline

    root = tmp_path / 'resources'
    shutil.copytree(files('codex_harness.resources').joinpath('baldrix_pipeline'),
                    root / 'baldrix_pipeline')
    provenance = root / 'baldrix_pipeline/provenance.json'
    if failure == 'missing_hash':
        body = json.loads(provenance.read_text('utf-8'))
        body['files'] = [p for p in body['files'] if p['destination'] != 'stages.core.yaml']
        provenance.write_text(json.dumps(body))
    else:
        (root / 'baldrix_pipeline/stages.core.yaml').write_text('modified')
    monkeypatch.setattr(project_pipeline, 'files', lambda package: root)

    class EmptyTree:
        def _git(self, *args, **kwargs):
            return ''

    with pytest.raises(ContractError, match='Pipeline asset'):
        project_pipeline.pipeline_context(EmptyTree(), FileArtifacts(str(tmp_path / 'artifacts')),
            str(tmp_path), 'a' * 40, {'stacks': [{'language': 'java'}]}, load_yaml)

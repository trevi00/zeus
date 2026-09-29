"""Ported SOURCE M7 suite `tests/test_project_detection.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_cli_detect_preview_initialize_and_existing_profile: S10 entry: the CLI main()/script moves to entry/composition
- test_unknown_cli_preview_remains_available_but_does_not_freeze_empty_profile: S10 entry: the CLI main()/script moves to entry/composition
- test_metadata_only_detection_requires_explicit_stack_before_write: S10 entry: the CLI main()/script moves to entry/composition
"""
import hashlib
import json
from pathlib import Path

import pytest

from codex_harness.context.adapters.project_detection import detect_project
from codex_harness.context.domain.project_skills import eligible_paths
from codex_harness.kernel.errors import ContractError


def test_all_upstream_project_types_are_retained_without_executing_files(tmp_path):
    sources = {'package.json': '{}', 'tsconfig.json': '{}',
               'pyproject.toml': '[project]\nrequires-python = ">=3.12"',
               'requirements.txt': 'pytest', 'setup.py': 'raise AssertionError("never execute")',
               'Cargo.toml': '', 'go.mod': '', 'pom.xml': '', 'build.gradle': '',
               'build.gradle.kts': '', 'settings.gradle.kts': '', 'pubspec.yaml': '',
               'project.godot': '', 'Gemfile': '', 'Dockerfile': '',
               'docker-compose.yml': '', 'docker-compose.yaml': ''}
    for name, body in sources.items():
        (tmp_path / name).write_text(body)
    (tmp_path / '.github/workflows').mkdir(parents=True)
    profile = detect_project(tmp_path)
    detection = profile['metadata']['detection']
    assert set(detection['project_types']) == {
        'node', 'python', 'rust', 'go', 'java', 'kotlin', 'flutter', 'godot', 'ruby',
        'docker', 'github-actions'}
    assert len(detection['signals']) == 18
    assert detection['declarations']['requires-python'] == [
        {'field': 'project.requires-python', 'spec': '>=3.12'}]
    assert not (tmp_path / '.harness').exists()
    assert {s['language'] for s in profile['stacks']} >= {'typescript', 'python', 'rust', 'java'}


def test_framework_ranges_and_conflicts_are_evidence_not_fake_exact_versions(tmp_path):
    package = {'dependencies': {'react': '^18.2', 'express': 'workspace:*'},
               'devDependencies': {'typescript': '~5.0', 'react': '19.0.0-beta.1'}}
    data = json.dumps(package).encode()
    (tmp_path / 'package.json').write_bytes(data)
    profile = detect_project(tmp_path)
    assert profile['stacks'] == [{'language': 'typescript', 'framework': 'react'},
                                 {'language': 'typescript', 'framework': 'express'}]
    info = profile['metadata']['detection']
    assert info['signals'][0]['sha256'] == hashlib.sha256(data).hexdigest()
    assert [r['spec'] for r in info['declarations']['react']] == ['^18.2', '19.0.0-beta.1']
    assert 'typescript/react-18.2' not in eligible_paths(profile)
    assert info['declarations']['typescript'] == [{'field': 'devDependencies', 'spec': '~5.0'}]
    assert info['root'] == '.'
    assert str(tmp_path) not in json.dumps(profile)


@pytest.mark.parametrize('text', ['{', '[]', '{"dependencies": []}',
                                 '{"dependencies":{"react":null}}',
                                 '{"dependencies":{},"dependencies":{"react":"18"}}'])
def test_malformed_package_does_not_create_profile(tmp_path, text):
    (tmp_path / 'package.json').write_text(text)
    with pytest.raises(ContractError):
        detect_project(tmp_path)
    assert not (tmp_path / '.harness').exists()


def test_explicit_scope_does_not_scan_nested_projects_or_home(tmp_path, monkeypatch):
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested/package.json').write_text('{}')
    profile = detect_project(tmp_path)
    assert profile['stacks'] == []
    assert profile['metadata']['detection']['status'] == 'unknown'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    with pytest.raises(ContractError, match='Home directory'):
        detect_project(tmp_path)


def test_oversized_manifest_and_directory_signal_are_rejected(tmp_path):
    (tmp_path / 'package.json').write_bytes(b' ' * 262145)
    with pytest.raises(ContractError, match='size limit'):
        detect_project(tmp_path)
    (tmp_path / 'package.json').unlink()
    (tmp_path / 'package.json').mkdir()
    with pytest.raises(ContractError, match='regular file'):
        detect_project(tmp_path)






def test_manifest_signal_names_match_original_exact_directory_membership(tmp_path):
    (tmp_path / 'dockerfile').write_text('FROM scratch')
    assert detect_project(tmp_path)['metadata']['detection']['status'] == 'unknown'


def test_workflow_file_is_reported_as_type_error(tmp_path):
    (tmp_path / '.github').mkdir()
    (tmp_path / '.github/workflows').write_text('not a directory')
    with pytest.raises(ContractError, match='regular directory'):
        detect_project(tmp_path)


def test_missing_home_does_not_block_explicit_project(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'absent-home'))
    (tmp_path / 'package.json').write_text('{}')
    assert detect_project(tmp_path)['stacks'] == [{'language': 'javascript'}]


def test_unresolvable_home_is_classified(tmp_path, monkeypatch):
    def unavailable(cls):
        raise RuntimeError('Could not determine home directory')
    monkeypatch.setattr(Path, 'home', classmethod(unavailable))
    with pytest.raises(ContractError, match='Cannot resolve home directory'):
        detect_project(tmp_path)


@pytest.mark.parametrize('directory', ['.GitHub/workflows', '.github/Workflows'])
def test_workflow_signal_uses_exact_directory_names(tmp_path, directory):
    (tmp_path / directory).mkdir(parents=True)
    assert detect_project(tmp_path)['metadata']['detection']['status'] == 'unknown'




def test_home_identity_stat_failure_still_rejects_same_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    def fail_stat(self, other):
        raise OSError('identity lookup unavailable')
    monkeypatch.setattr(Path, 'samefile', fail_stat)
    with pytest.raises(ContractError, match='Home directory'):
        detect_project(tmp_path)


def test_workflow_parent_symlink_is_rejected(tmp_path):
    target = tmp_path / 'real-github'
    (target / 'workflows').mkdir(parents=True)
    try:
        (tmp_path / '.github').symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable for this user')
    with pytest.raises(ContractError, match='parent must not be a symlink'):
        detect_project(tmp_path)

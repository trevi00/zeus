import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.project_detection import detect_project
from codex_harness.adapters.project_skills import parse_profile
from codex_harness.domain.model import ContractError
from codex_harness.domain.project_skills import eligible_paths


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


def test_cli_detect_preview_initialize_and_existing_profile(tmp_path):
    (tmp_path / 'package.json').write_text('{"dependencies":{"react":"^18"}}')
    (tmp_path / 'tsconfig.json').write_text('{}')
    script = Path(__file__).resolve().parents[1] / 'scripts/project_init.py'
    env = {**os.environ, 'PYTHONPATH': str(script.parents[1] / 'src')}
    command = [sys.executable, str(script), str(tmp_path), '--detect']
    preview = subprocess.run(command + ['--preview'], env=env, capture_output=True, text=True)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)['written'] is False
    assert not (tmp_path / '.harness').exists()
    applied = subprocess.run(command, env=env, capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    profile = parse_profile((tmp_path / '.harness/tech-stack.yaml').read_text())
    assert 'typescript/react' in eligible_paths(profile)
    assert json.loads(applied.stdout)['commit_required'] is True
    repeated = subprocess.run(command, env=env, capture_output=True, text=True)
    assert repeated.returncode == 2 and 'FileExistsError' in repeated.stderr


def test_unknown_cli_preview_remains_available_but_does_not_freeze_empty_profile(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/project_init.py'
    env = {**os.environ, 'PYTHONPATH': str(script.parents[1] / 'src')}
    command = [sys.executable, str(script), str(tmp_path), '--detect']
    preview = subprocess.run(command + ['--preview'], env=env, capture_output=True, text=True)
    assert preview.returncode == 0
    assert json.loads(preview.stdout)['profile']['metadata']['detection']['status'] == 'unknown'
    applied = subprocess.run(command, env=env, capture_output=True, text=True)
    assert applied.returncode == 2 and 'No project signals' in applied.stderr
    assert not (tmp_path / '.harness').exists()


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


@pytest.mark.parametrize('signal', ['Dockerfile', '.github/workflows'])
def test_metadata_only_detection_requires_explicit_stack_before_write(tmp_path, signal):
    if signal == 'Dockerfile':
        (tmp_path / signal).write_text('FROM scratch')
    else:
        (tmp_path / signal).mkdir(parents=True)
    profile = detect_project(tmp_path)
    assert profile['stacks'] == []
    assert profile['metadata']['detection']['status'] == 'detected'
    script = Path(__file__).resolve().parents[1] / 'scripts/project_init.py'
    env = {**os.environ, 'PYTHONPATH': str(script.parents[1] / 'src')}
    result = subprocess.run([sys.executable, str(script), str(tmp_path), '--detect'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 2 and 'Only metadata signals' in result.stderr
    assert not (tmp_path / '.harness/tech-stack.yaml').exists()


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

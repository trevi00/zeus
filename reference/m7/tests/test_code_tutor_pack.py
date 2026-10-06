"""Contract tests for the Code Tutor pack: real temporary Git and FileArtifacts, no app or backend.

These are consumer-contract tests (project_context, validate_spec, gate_report, render_review),
not E2E runs of code-tutor-ai; nothing here executes the application or claims acceptance.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.project_skills import parse_profile, project_context
from codex_harness.adapters.sdd import load_json, render_review, replay_source
from codex_harness.adapters.skill_routing import frontmatter
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.project_skills import eligible_paths
from codex_harness.domain.sdd import gate_report, validate_spec

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'examples/code-tutor-ai'
SPEC = PACK / 'sdd/learning-loop.spec.json'
OBJECTIVE = 'codetutor learning submission'
# Distribution path -> installed path inside a new project root (SPEC item 1; README table).
INSTALL_MAP = {
    'profile.yaml': '.harness/tech-stack.yaml',
    'skills/typescript/react/experience-contract.md': '.harness/skills/typescript/react/experience-contract.md',
    'skills/typescript/5.x/runtime-contract.md': '.harness/skills/typescript/5.x/runtime-contract.md',
    'skills/common/real-acceptance.md': '.harness/skills/_common/real-acceptance.md',
}
SKILLS = [path for path in INSTALL_MAP if path.startswith('skills/')]
SCENARIOS = ['SCN.ct.learning-loop', 'SCN.ct.wrong-answer', 'SCN.ct.ownership',
             'SCN.ct.interruption', 'SCN.ct.ui-states']


def test_pack_inventory_and_readme_install_map_agree():
    files = sorted(p.relative_to(PACK).as_posix() for p in PACK.rglob('*') if p.is_file())
    assert files == sorted([*INSTALL_MAP, 'README.md', 'sdd/learning-loop.spec.json'])
    readme = (PACK / 'README.md').read_text(encoding='utf-8')
    for source, target in INSTALL_MAP.items():
        assert f'| `{source}` | `{target}` |' in readme
    for phrase in ('덮어쓰기 금지', '커밋', 'zeus sdd inspect', 'zeus sdd view', '8단계',
                   'SOURCE.json', 'PR119', '롤백', 'PowerShell', 'bash', 'page.route'):
        assert phrase in readme
    assert 'cp -n' in readme and 'Test-Path' in readme


def test_profile_separates_react_and_typescript_versions_without_measured_fastapi():
    profile = parse_profile((PACK / 'profile.yaml').read_text(encoding='utf-8'))
    assert profile['stacks'] == [
        {'language': 'typescript', 'framework': 'react', 'version': '19'},
        {'language': 'typescript', 'version': '5.9'},
        {'language': 'python', 'framework': 'fastapi'}]
    assert profile['extensions'] == [] and 'project_id' not in profile
    assert profile['metadata']['reference_revision'] == '0d48f06dd8860a9e9f731e7af434824779eaadd8'
    paths = eligible_paths(profile)
    assert {'typescript/react', 'typescript/5.x', '_common', 'python/fastapi'} <= set(paths)
    assert not any(p.startswith(('java', 'flutter', 'kotlin')) for p in paths)


@pytest.mark.parametrize('relative', SKILLS)
def test_skill_bodies_are_concise_english_with_flat_routing_frontmatter(relative):
    text = (PACK / relative).read_text(encoding='utf-8')
    meta, body = frontmatter(text)
    assert set(meta) == {'name', 'description', 'keywords', 'min_score'}
    assert meta['min_score'] == '3'
    assert {'codetutor', 'learning', 'submission'} <= set(meta['keywords'])
    assert len(body) <= 950 and len(body.encode('utf-8')) <= 950
    assert body.isascii(), 'skill bodies are plain English'
    assert 'node20' not in body or 'Do not paste' in body


def test_skill_principles_cover_the_selected_groups():
    experience = (PACK / SKILLS[0]).read_text(encoding='utf-8')
    runtime = (PACK / SKILLS[1]).read_text(encoding='utf-8')
    acceptance = (PACK / SKILLS[2]).read_text(encoding='utf-8')
    for word in ('owner', 'lifetime', 'pending', 'loading', 'empty', 'error', 'success',
                 'semantic', 'Lucide', 'keyboard', 'focus', 'reduced-motion', 'stories'):
        assert word in experience
    for word in ('pinned compiler', 'schema', 'HTTP status', 'client role', 'logout', 'canonical'):
        assert word in runtime
    for word in ('stable ID', 'page.route', 'MSW', 'emulator', 'timeout', 'unknown',
                 'blind resubmission', 'Redact', 'human decision'):
        assert word in acceptance


@pytest.fixture
def installed_project(tmp_path):
    """Real temporary Git project with the pack installed by the README map plus an
    out-of-stack decoy that matches the objective just as strongly."""
    root = tmp_path / 'new-project'
    root.mkdir()
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    git._git('init', '-q')
    git._git('config', 'user.name', 'Fixture')
    git._git('config', 'user.email', 'fixture@example.invalid')
    assert not (root / '.harness').exists(), 'non-overwrite guidance: only a new root is installed'
    for source, target in INSTALL_MAP.items():
        destination = root / target
        assert not destination.exists()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PACK / source, destination)
    decoy = root / '.harness/skills/java/lang/decoy.md'
    decoy.parent.mkdir(parents=True)
    decoy.write_text('---\nkeywords: [codetutor, learning, submission]\nmin_score: 3\n---\n'
                     'JAVA_DECOY_MUST_NOT_LOAD', encoding='utf-8')
    git._git('add', '.')
    git._git('commit', '-qm', 'install code tutor pack')
    return root, git, FileArtifacts(str(tmp_path / 'artifacts'))


def test_actual_project_context_delivers_all_three_full_bodies_pinned_to_git(installed_project):
    root, git, artifacts = installed_project
    revision = git._git('rev-parse', 'HEAD')
    items, summary = project_context(git, artifacts, str(root), revision, OBJECTIVE)
    assert summary['status'] == 'configured'
    assert summary['routing']['full'] == 3 and summary['routing']['inspected'] == 3
    manifest = artifacts.document(summary['manifest_ref'])
    assert manifest['revision'] == revision
    records = {record['path']: record for record in manifest['skills']}
    assert set(records) == {INSTALL_MAP[path] for path in SKILLS}
    assert 'JAVA_DECOY_MUST_NOT_LOAD' not in '\n'.join(item.body for item in items)
    full = {item.id.removeprefix('project-skill:'): item for item in items if item.priority == 18}
    assert set(full) == set(records)
    for path, record in records.items():
        committed = git._git('show', revision + ':' + path, cwd=str(root), strip=False)
        _, body = frontmatter(committed)
        assert record['tier'] == 'full' and not record['truncated']
        assert full[path].body == body and record['rendered_hash'] == digest(body)
        assert record['revision'] == revision
        assert artifacts.read(record['content_ref'], 0, 8000) == committed
        assert Path(record['file']).read_text(encoding='utf-8') == committed
    # Uncommitted edits to the profile and skill bodies never reach the pinned consumer.
    (root / '.harness/tech-stack.yaml').write_text('stack: {language: java}', encoding='utf-8')
    for path in records:
        (root / path).write_text('---\nkeywords: [codetutor, learning, submission]\n'
                                 'min_score: 3\n---\nUNCOMMITTED_EDIT', encoding='utf-8')
    again_items, again_summary = project_context(git, artifacts, str(root), revision, OBJECTIVE)
    assert again_items == items and again_summary == summary
    assert 'UNCOMMITTED_EDIT' not in '\n'.join(item.body for item in again_items)
    # Control: only a new commit changes the selection, and then the TypeScript pack is excluded.
    git._git('add', '.harness/tech-stack.yaml')
    git._git('commit', '-qm', 'switch stack to java')
    switched, switched_summary = project_context(git, artifacts, str(root),
                                                 git._git('rev-parse', 'HEAD'), OBJECTIVE)
    switched_text = '\n'.join(item.body for item in switched)
    assert 'JAVA_DECOY_MUST_NOT_LOAD' in switched_text
    assert not any(item.id.endswith(('experience-contract.md', 'runtime-contract.md'))
                   for item in switched)
    assert switched_summary['manifest_ref'] != summary['manifest_ref']


def test_native_sdd_draft_has_exactly_five_pending_scenarios():
    spec = validate_spec(load_json(SPEC))
    assert spec['target'] == {'kind': 'unconfigured', 'app_id': 'code-tutor-ai',
                              'build_hash': None, 'alpha_url': None}
    assert [row['id'] for row in spec['scenarios']] == SCENARIOS
    assert all(row['status'] == 'active' and row['bindings'] == [] for row in spec['scenarios'])
    devices = {row['id'] for row in spec['devices']}
    assert devices == {'samsung.phone', 'samsung.tablet'}
    assert all(row['physical_required'] and any('보류' in c for c in row['conditions'])
               for row in spec['devices'])
    for row in spec['scenarios']:
        assert set(row['device_profiles']) == devices
        assert len(row['then']) >= 2 and all(len(text) > 10 for text in row['then'])
    risks = {row['id']: row['risk'] for row in spec['requirements']}
    assert risks == {'REQ.ct.learning-loop': 'normal', 'REQ.ct.wrong-answer': 'normal',
                     'REQ.ct.ownership': 'critical', 'REQ.ct.interruption': 'critical',
                     'REQ.ct.ui-states': 'normal'}
    stories = ' '.join(spec['design']['required_stories'])
    assert all(state in stories for state in ('loading', 'empty', 'error', 'success', 'pending'))
    assert 'ACCEPTED' in ' '.join(spec['scenarios'][0]['then'])
    assert 'WRONG_ANSWER' in ' '.join(spec['scenarios'][1]['then'])
    for text in spec['reset_contract'], spec['design']['components']:
        assert '설치' not in spec['design']['components'] or '주장하지 않' in text or '삭제하지 않' in text
    with pytest.raises(ContractError, match='Concrete Android'):
        replay_source(spec)


def test_native_report_and_review_render_stay_blocked_without_release_authority(tmp_path):
    spec = load_json(SPEC)
    report = gate_report(spec)
    assert len(report['stages']) == 8
    assert all(stage['status'] == 'blocked' for stage in report['stages'])
    assert report['denominators']['scenarios_declared'] == 5
    assert report['denominators']['scenarios_executed_by_runner'] == 0
    assert report['denominators']['human_accepted'] == 0
    assert not report['acceptance_passed'] and not report['release_authorized']
    page = render_review(spec, report)
    body = page.split('<script id="sdd-data" type="application/json">')[1].split('</script>')[0]
    data = json.loads(body)
    assert [row['id'] for row in data['spec']['scenarios']] == SCENARIOS
    assert data['report']['release_authorized'] is False
    assert '"release_authorized": true' not in page and '"acceptance_passed": true' not in page
    result = subprocess.run([sys.executable, '-m', 'zeus', 'sdd', 'inspect', str(SPEC)], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stderr
    inspected = json.loads(result.stdout)
    assert inspected['valid'] and inspected['source']['mode'] == 'working_tree_draft'
    assert inspected['report']['release_authorized'] is False
    assert all(stage['status'] == 'blocked' for stage in inspected['report']['stages'])

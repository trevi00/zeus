"""Ported SOURCE M7 suite `tests/test_project_skills.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_actual_executor_context_contains_only_eligible_pinned_skills: S4 execution: needs RunTask (the M7 Executor)
- test_real_skill_history_annotation_and_recovery_survive_other_task_observation: S4 execution: needs RunTask (the M7 Executor)
- test_cli_legacy_import_preserves_extra_metadata_and_never_overwrites: S10 entry: the CLI main()/script moves to entry/composition
"""

from functools import partial as _partial

import pytest
from conftest import NATIVE_THRESHOLDS as _THRESHOLDS

from codex_harness.context.adapters import project_skills as _project_skills
from codex_harness.context.adapters import skill_routing as _skill_routing
from codex_harness.context.adapters.project_skills import initialize, parse_profile, project_context
from codex_harness.context.domain.project_skills import eligible_paths, select_skill_paths
from codex_harness.host_os.adapters.git_workspace import GitWorkspace
from codex_harness.kernel.errors import ContractError
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

# Adapted: the native threshold definition reaches context through context.ports.ThresholdPolicySource
# (research implements it in S8); these suites supply the packaged definition.
project_context = _partial(_project_skills.project_context, thresholds=_THRESHOLDS)  # noqa: F811
route_skills = _partial(_skill_routing.route_skills, threshold_policy=_THRESHOLDS.effective_policy())  # noqa: F811


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


def test_inline_comment_template_routes_to_clean_paths():
    # FA-008: the upstream template's routing values carry inline comments; they never reach paths.
    profile = parse_profile('''stack:
  language: java                   # java | kotlin | typescript | python
  framework: springboot            # springboot | android | react | flutter
  version: "3.2"                   # 프레임워크 버전 (스킬 디렉토리명과 매치)
extensions: []                     # 프로젝트 전용 서브트리
''')
    assert profile['stacks'] == [{'language': 'java', 'framework': 'springboot', 'version': '3.2'}]
    paths = eligible_paths(profile)
    assert paths == ['_common', 'java/springboot-3.2', 'java/springboot', 'java/3.2', 'java/3.x',
                     'java/lang', 'java']
    assert not any('#' in p or ' ' in p for p in paths)


def test_flutter_stack_activates_the_flutter_tree_not_dart():
    profile = parse_profile('stack: {language: flutter, framework: flutter, version: "3.24"}')
    paths = eligible_paths(profile)
    assert paths == ['_common', 'flutter/flutter-3.24', 'flutter/flutter', 'flutter/3.24', 'flutter/3.x',
                     'flutter/lang', 'flutter']
    assert not any(p.startswith('dart') for p in paths)


@pytest.mark.parametrize('text', [
    'stack: {language: "java # java | kotlin"}',
    'stack: {language: java, version: "3.2 # version"}',
    "stack: {language: 'flutter 3.x'}",
])
def test_comment_or_space_inside_a_quoted_value_fails_explicitly(text):
    with pytest.raises(ContractError, match='Invalid stack path segment'):
        parse_profile(text)


def test_packaged_skills_are_collected_at_any_depth_and_underscore_directories_are_skipped():
    profile = parse_profile('stack: {language: python, framework: fastapi}')
    inventory = ['python/fastapi/testing/SKILL.md', 'python/fastapi/testing/integration/SKILL.md',
                 'python/fastapi/testing/integration/notes.md', 'python/fastapi/_drafts/SKILL.md',
                 'python/fastapi/testing/_wip/deep/SKILL.md', 'python/fastapi/lint/README.md',
                 'python/django/deep/SKILL.md']
    assert select_skill_paths(profile, inventory) == ['python/fastapi/testing/SKILL.md',
                                                      'python/fastapi/testing/integration/SKILL.md']


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




def test_profile_symlink_in_git_is_rejected(project):
    root, git, artifacts = project
    blob = git._git('rev-parse', 'HEAD:.harness/tech-stack.yaml')
    git._git('update-index', '--cacheinfo', f'120000,{blob},.harness/tech-stack.yaml')
    git._git('commit', '-qm', 'fixture symlink mode')
    with pytest.raises(ContractError, match='regular Git file'):
        project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))




def test_selected_skill_symlink_is_rejected(project):
    root, git, artifacts = project
    path = '.harness/skills/_common/base.md'
    blob = git._git('rev-parse', 'HEAD:' + path)
    git._git('update-index', '--cacheinfo', f'120000,{blob},{path}')
    git._git('commit', '-qm', 'fixture skill symlink mode')
    with pytest.raises(ContractError, match='regular Git file'):
        project_context(git, artifacts, str(root), git._git('rev-parse', 'HEAD'))



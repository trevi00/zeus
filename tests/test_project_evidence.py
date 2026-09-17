"""INV-PROJECT-EVIDENCE-001: host-selected project context, required named checks, structured
observations and immutable replay snapshots.

Every replay below is a real child process of the host-selected interpreter in a project
subdirectory. Stores and artifact roots are in-memory/tmp seams; no provider or model is called.
"""
import json
import os
import sys
from pathlib import Path

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import EvidenceInspector
from codex_harness.adapters.operation_cli import identity
from codex_harness.adapters.output_schema import preflight
from codex_harness.adapters.project_evidence import (
    ProjectEvidenceInspector,
    execution_instructions,
    load_profile,
    resolve_profile,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.evidence_inspection import BUCKET, EvidenceInspections
from codex_harness.domain.evidence import parse_policy
from codex_harness.domain.model import ContractError
from codex_harness.domain.project_evidence import (
    SCHEMA,
    observed_checks,
    parse_profile,
    worker_schema,
)

PY = sys.executable
PROBE = 'zeus_backend_probe'  # exists only under the candidate's backend/src
FAILING = 'zeus_backend_failing'
TASK = {'id': 'task-1', 'generation': 1, 'attempt': 1, 'lease_owner': 'worker'}
CANDIDATE = {'revision': 'a' * 40, 'base': 'b' * 40, 'tree': 'c' * 40}


def policy(**replay):
    base = {'version': 1, 'replay': {'allowed_argv_prefixes': [['python', '-m', PROBE], ['python', '-m', FAILING],
                                                             ['python', '-m', 'pytest']],
                                     'per_command_seconds': 60, 'total_seconds': 180, 'max_claims': 8,
                                     'max_output_bytes': 4096, 'replays_per_claim': 2},
            'files': {'max_bytes': 1024 * 1024}}
    base['replay'].update(replay)
    return base


POLICY = parse_policy(policy())


def workspace(tmp_path, name='candidate'):
    root = tmp_path / name
    source = root / 'backend' / 'src'
    source.mkdir(parents=True)
    (root / 'backend' / 'empty_tests').mkdir()
    (root / 'backend' / 'requirements.lock').write_bytes(b'example==1.0\n')
    (source / (PROBE + '.py')).write_text(
        'import os, sys\nfrom pathlib import Path\n'
        'assert Path.cwd().name == "backend", Path.cwd()\n'
        'assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"\n'
        'assert "ZEUS_SECRET" not in os.environ\n'
        'print(os.environ["PYTHONPATH"])\n', encoding='utf-8')
    (source / (FAILING + '.py')).write_text('import sys\nsys.exit(3)\n', encoding='utf-8')
    return root


def document(checks=None, **context):
    return {'schema': SCHEMA,
            'contexts': {'backend': {'cwd': 'backend', 'interpreter': PY, 'source_paths': ['backend/src'],
                                     'dependency_files': ['backend/requirements.lock'], **context}},
            'checks': checks if checks is not None else [
                {'id': 'probe', 'context': 'backend', 'argv': ['python', '-m', PROBE], 'expected_exit': 0}]}


def check(name, module, expected=0):
    return {'id': name, 'context': 'backend', 'argv': ['python', '-m', module], 'expected_exit': expected}


def executed(name, code=0):
    return {'check_id': name, 'status': 'executed', 'exit_code': code}


def inspector(tmp_path, doc=None):
    return ProjectEvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), parse_profile(doc or document(), POLICY), policy())


def ledger(tmp_path, doc=None):
    store = MemoryStore()
    return store, EvidenceInspections(store, inspector(tmp_path, doc))


def test_required_check_replays_in_the_project_subdirectory_with_the_host_interpreter(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'parent-path'))
    monkeypatch.setenv('ZEUS_SECRET', 'never-inherited')
    store, inspections = ledger(tmp_path)
    row = inspections.inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert row['verdict'] == 'all_checked', row['findings']
    finding = row['findings'][0]
    assert finding['check_id'] == 'probe' and finding['context'] == 'backend'
    assert finding['original_argv'] == ['python', '-m', PROBE] and finding['replay_argv'][0] == PY
    assert finding['reported_exit'] == 0 and finding['expected_exit'] == 0 and finding['observed_exits'] == [0, 0]
    assert Path(finding['cwd']) == (root / 'backend').resolve()
    assert all(run['stdout']['ref'].startswith('sha256:') for run in finding['runs'])
    project = row['inspector']['project']
    assert project['contexts']['backend']['dependency_files'] == {
        'backend/requirements.lock': __import__('hashlib').sha256(b'example==1.0\n').hexdigest()}
    assert len(project['contexts']['backend']['interpreter_sha256']) == 64
    assert row['context']['project_digest'] == project['digest']
    assert not list(root.rglob('__pycache__'))
    with store.transaction() as tx:
        assert tx.get(BUCKET, row['id'])['verdict'] == 'all_checked'


def test_reported_failure_is_retained_and_host_expected_nonzero_can_pass(tmp_path):
    root = workspace(tmp_path)
    doc = document([check('must-pass', FAILING, 0), check('negative', FAILING, 3), check('probe', PROBE)])
    _, inspections = ledger(tmp_path, doc)
    row = inspections.inspect(TASK, CANDIDATE, [executed('must-pass', 3), executed('negative', 3), executed('probe', 1)], str(root))
    states = {f['check_id']: f for f in row['findings']}
    assert row['verdict'] == 'incomplete'
    assert states['must-pass']['state'] == 'verified_mismatch' and states['must-pass']['reported_exit'] == 3
    assert states['must-pass']['claim']['expected_exit'] == 0
    assert states['negative']['state'] == 'checked'
    # Replays pass, but the worker reported a failure: never coerced to the expectation.
    assert states['probe']['state'] == 'verified_mismatch' and states['probe']['observed_exits'] == [0, 0]
    assert 'worker reported exit 1' in states['probe']['cause']


def test_pytest_no_tests_exit_five_is_not_a_pass(tmp_path):
    root = workspace(tmp_path)
    argv = ['python', '-m', 'pytest', 'empty_tests', '-q', '-p', 'no:cacheprovider']
    doc = document([{'id': 'unit', 'context': 'backend', 'argv': argv, 'expected_exit': 0}])
    row = ledger(tmp_path, doc)[1].inspect(TASK, CANDIDATE, [executed('unit', 0)], str(root))
    assert row['verdict'] == 'incomplete'
    assert row['findings'][0]['state'] == 'verified_mismatch' and row['findings'][0]['observed_exits'] == [5, 5]


def test_not_run_missing_unknown_and_duplicate_cannot_be_all_checked_and_do_not_spawn(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    doc = document([check('probe', PROBE), check('second', PROBE)])
    spawned = []
    monkeypatch.setattr('codex_harness.adapters.project_evidence._capture', lambda *a, **k: spawned.append(a) or {})
    _, inspections = ledger(tmp_path, doc)
    row = inspections.inspect(TASK, CANDIDATE, [{'check_id': 'probe', 'status': 'not_run', 'exit_code': None}], str(root))
    assert row['verdict'] == 'incomplete' and not spawned
    assert [f['state'] for f in row['findings']] == ['not_checked', 'not_checked']
    assert 'not_run' in row['findings'][0]['cause'] and 'no observation' in row['findings'][1]['cause']
    empty = inspections.inspect(TASK, CANDIDATE, [], str(root))
    assert empty['verdict'] == 'incomplete' and empty['denominator']['claims'] == 2 and not spawned
    inspect = inspector(tmp_path, doc)
    claims, refusals = observed_checks(inspect.profile, [
        executed('probe'), executed('probe'), executed('invented'), 'python -m pytest',
        {'check_id': 'second', 'status': 'executed', 'exit_code': None},
        {'check_id': 'probe', 'status': 'executed', 'exit_code': 0, 'argv': ['rm', '-rf', '/']}])
    assert [c['status'] for c in claims] == ['executed', 'missing']
    assert len(refusals) == 5
    assert all(c['argv'] == ['python', '-m', PROBE] for c in claims)


def test_refusals_are_error_findings_in_a_real_inspection(tmp_path):
    root = workspace(tmp_path)
    row = ledger(tmp_path)[1].inspect(TASK, CANDIDATE, [executed('probe'), executed('invented')], str(root))
    assert row['verdict'] == 'incomplete'
    assert [f['state'] for f in row['findings']] == ['checked', 'error']


@pytest.mark.parametrize('mutation', [
    {'cwd': '../outside'}, {'cwd': '/abs'}, {'cwd': 'C:\\abs'}, {'source_paths': ['backend/../..']},
    {'dependency_files': ['.']}, {'interpreter': ''}, {'env': {'SECRET': 'x'}}])
def test_profile_refuses_unsafe_paths_and_unknown_fields(mutation):
    with pytest.raises(ContractError):
        parse_profile(document(**mutation), POLICY)


@pytest.mark.parametrize('checks', [
    [], [check('a', PROBE), check('a', PROBE)],
    [{'id': 'fmt', 'context': 'backend', 'argv': ['python', '-m', 'ruff', 'format', '.'], 'expected_exit': 0}],
    [{'id': 'sh', 'context': 'backend', 'argv': ['sh', '-c', 'python -m pytest'], 'expected_exit': 0}],
    [{'id': 'pip', 'context': 'backend', 'argv': ['python', '-m', 'pip', 'install', 'x'], 'expected_exit': 0}],
    [{'id': 'a', 'context': 'elsewhere', 'argv': ['python', '-m', PROBE], 'expected_exit': 0}],
    [{'id': 'a', 'context': 'backend', 'argv': ['python', '-m', PROBE], 'expected_exit': 0, 'required': False}]])
def test_profile_checks_are_closed_distinct_and_under_the_same_allowlist(checks):
    with pytest.raises(ContractError):
        parse_profile(document(checks), POLICY)


def test_missing_source_dependency_interpreter_and_symlink_escape_refuse_before_spawn(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    spawned = []
    monkeypatch.setattr('codex_harness.adapters.project_evidence._capture', lambda *a, **k: spawned.append(a) or {})
    for doc in (document(source_paths=['backend/absent']), document(dependency_files=['backend/absent.lock']),
                document(cwd='backend/absent'), document(interpreter=str(tmp_path / 'no-python.exe'))):
        with pytest.raises(ContractError):
            ledger(tmp_path, doc)[1].inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert not spawned


def test_symlink_escape_from_the_candidate_is_refused(tmp_path):
    root = workspace(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        os.symlink(outside, root / 'backend' / 'linked', target_is_directory=True)
    except OSError:
        pytest.skip('symlinks are not permitted on this host')
    with pytest.raises(ContractError, match='outside the candidate'):
        resolve_profile(parse_profile(document(source_paths=['backend/linked']), POLICY), root)


def test_host_setting_loads_once_and_a_bad_configured_profile_never_falls_back(tmp_path):
    assert load_profile({}) is None
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(document()), encoding='utf-8')
    profile = load_profile({'HARNESS_EVIDENCE_PROFILE': str(path)}, POLICY)
    assert profile['profile_digest'] == parse_profile(document(), POLICY)['profile_digest']
    for bad in ('relative.json', str(tmp_path / 'absent.json')):
        with pytest.raises(ContractError):
            load_profile({'HARNESS_EVIDENCE_PROFILE': bad}, POLICY)
    path.write_text('{not json', encoding='utf-8')
    with pytest.raises(ContractError):
        load_profile({'HARNESS_EVIDENCE_PROFILE': str(path)}, POLICY)
    path.write_text(json.dumps(document(interpreter=str(tmp_path / 'no-python'))), encoding='utf-8')
    with pytest.raises(ContractError):
        load_profile({'HARNESS_EVIDENCE_PROFILE': str(path)}, POLICY)


def test_profile_dependency_bytes_and_environment_changes_are_new_inspections(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    store = MemoryStore()
    first = EvidenceInspections(store, inspector(tmp_path)).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    again = EvidenceInspections(store, inspector(tmp_path)).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert again['id'] == first['id']
    (root / 'backend' / 'requirements.lock').write_text('example==2.0\n', encoding='utf-8')
    locked = EvidenceInspections(store, inspector(tmp_path)).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert locked['id'] != first['id']
    other = document([check('probe', PROBE), check('extra', PROBE)])
    changed = EvidenceInspections(store, inspector(tmp_path, other)).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert changed['id'] not in (first['id'], locked['id']) and changed['verdict'] == 'incomplete'
    monkeypatch.setenv('LANG', 'zeus-changed-value')
    moved = EvidenceInspections(store, inspector(tmp_path)).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert moved['id'] not in (first['id'], locked['id'])


def test_interpreter_bytes_are_part_of_the_identity(tmp_path):
    root = workspace(tmp_path)
    fake = tmp_path / 'interpreter.bin'
    fake.write_bytes(b'one')
    profile = parse_profile(document(interpreter=str(fake)), POLICY)
    before = resolve_profile(profile, root)
    fake.write_bytes(b'two')
    assert resolve_profile(profile, root)['digest'] != before['digest']


def test_replay_runs_under_the_snapshot_even_after_the_parent_environment_changes(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    inspect = inspector(tmp_path)
    snapshot = inspect.snapshot(root)

    class Changing(ProjectEvidenceInspector):
        def snapshot(self, cwd=None):
            return snapshot

        def inspect(self, *args, **kwargs):
            # The host environment moves between the keyed snapshot and the replay.
            monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'late-parent-path'))
            monkeypatch.setenv('ZEUS_SECRET', 'late')
            return super().inspect(*args, **kwargs)
    changing = Changing(FileArtifacts(str(tmp_path / 'artifacts')), inspect.profile, policy())
    row = EvidenceInspections(MemoryStore(), changing).inspect(TASK, CANDIDATE, [executed('probe')], str(root))
    assert row['verdict'] == 'all_checked', row['findings']
    assert row['context']['project_digest'] == snapshot['project']['digest']


def test_application_refuses_a_project_snapshot_its_identity_does_not_name(tmp_path):
    root = workspace(tmp_path)

    class Dropping(ProjectEvidenceInspector):
        def snapshot(self, cwd=None):
            taken = super().snapshot(cwd)
            return {**taken, 'project': {**taken['project'], 'digest': 'f' * 64}}
    dropping = Dropping(FileArtifacts(str(tmp_path / 'artifacts')), parse_profile(document(), POLICY), policy())
    with pytest.raises(ContractError, match='project snapshot'):
        EvidenceInspections(MemoryStore(), dropping).inspect(TASK, CANDIDATE, [executed('probe')], str(root))


def test_reviewer_instructions_are_rebound_to_its_own_checkout(tmp_path):
    profile = parse_profile(document(), POLICY)
    implementation, review = workspace(tmp_path, 'implementation'), workspace(tmp_path, 'review')
    told = execution_instructions(profile, review)
    assert Path(told['contexts']['backend']['cwd']) == (review / 'backend').resolve()
    assert told['contexts']['backend']['environment']['PYTHONPATH'] == str((review / 'backend' / 'src').resolve())
    assert str(implementation.resolve()) not in json.dumps(told)
    assert told['checks'] == profile['checks'] and told['profile_digest'] == profile['profile_digest']
    assert execution_instructions(profile, implementation)['contexts'] != told['contexts']


def test_worker_schema_is_per_profile_closed_and_inside_the_output_subset():
    first = worker_schema(parse_profile(document(), POLICY))
    second = worker_schema(parse_profile(document([check('other', PROBE)]), POLICY))
    item = first['properties']['tests']['items']
    assert set(first['properties']) == {'summary', 'tests'}
    assert item['properties']['check_id']['enum'] == ['probe'] and item['additionalProperties'] is False
    assert item['properties']['status']['enum'] == ['executed', 'not_run']
    assert second['properties']['tests']['items']['properties']['check_id']['enum'] == ['other']
    preflight(first)


def test_operation_identity_binds_the_profile_and_keeps_the_old_shape_without_one(tmp_path):
    class Policy:
        def summary(self):
            return {'policy_digest': 'p', 'config_digest': 'c'}
    legacy = identity({}, tmp_path, Policy(), {}, tmp_path)
    assert set(legacy) == {'repository', 'runtime', 'runtime_policy', 'provider', 'endpoints'}
    one = identity({}, tmp_path, Policy(), {}, tmp_path, parse_profile(document(), POLICY))
    two = identity({}, tmp_path, Policy(), {}, tmp_path, parse_profile(document([check('other', PROBE)]), POLICY))
    assert {k: v for k, v in one.items() if k != 'evidence_profile'} == legacy
    assert one['evidence_profile'] != two['evidence_profile']


def test_executor_gives_worker_and_reviewer_their_own_project_context(tmp_path, monkeypatch):
    """Fake provider seam (labelled fixture runtime, no model): what the executor composes with a profile."""
    from types import SimpleNamespace

    from codex_harness.adapters.executor import VERDICT, Executor
    from codex_harness.application.service import Harness
    from codex_harness.bootstrap import organization

    prompts = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            prompts.append(json.loads(prompt))
            answer = {'accepted': True, 'reason': 'fixture', 'blocked': False, 'risks': [], 'sre_assessment': 'n/a',
                      'arc42_assessment': 'n/a'} if kwargs['read_only'] else {'summary': 'fixture', 'tests': [executed('probe')]}
            return {'answer': answer, 'events': [], 'thread_id': 'thread', 'turn_id': 'turn', 'usage': None,
                    'rotate': False, 'interrupted': False, 'requested_model': kwargs.get('model')}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    profile = parse_profile(document(), POLICY)
    git = SimpleNamespace(_git=lambda *a, **k: 'revision')
    executor = Executor(Harness(MemoryStore(), organization()), git, FileArtifacts(str(tmp_path / 'artifacts')),
                        evidence_profile=profile)
    assert isinstance(executor.evidence.inspector, ProjectEvidenceInspector)
    implementation, review = workspace(tmp_path, 'implementation'), workspace(tmp_path, 'review')
    plan = {'plan': {'objective': 'x', 'acceptance_criteria': ['y'], 'allowed_paths': ['z']}}
    executor._run('worker:implementation', 'task', 'Implement', plan, str(implementation), worker_schema(profile),
                  action='implement')
    executor._run('lead:improvement', 'review', 'Evaluate review_lead', {'candidate': {'revision': 'c' * 40}},
                  str(review), VERDICT, read_only=True)
    worker, reviewer = prompts
    assert Path(worker['required']['project_evidence']['contexts']['backend']['cwd']) == (implementation / 'backend').resolve()
    told = reviewer['required']['review_context']['project_evidence']
    assert Path(told['contexts']['backend']['cwd']) == (review / 'backend').resolve()
    assert str(implementation.resolve()) not in json.dumps(told) and told['checks'] == profile['checks']
    legacy = Executor(Harness(MemoryStore(), organization()), git, FileArtifacts(str(tmp_path / 'legacy-artifacts')))
    assert legacy.evidence_profile is None and type(legacy.evidence.inspector) is EvidenceInspector
    legacy._run('lead:improvement', 'review', 'Evaluate review_lead', {'candidate': {'revision': 'c' * 40}},
                str(review), VERDICT, read_only=True)
    assert 'project_evidence' not in prompts[-1]['required']['review_context']


def test_legacy_inspector_is_unchanged_without_a_profile(tmp_path):
    root = workspace(tmp_path)
    legacy = EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), policy())
    snapshot = legacy.snapshot(root)
    assert 'project' not in snapshot and 'project' not in snapshot['identity']
    row = EvidenceInspections(MemoryStore(), legacy).inspect(TASK, CANDIDATE, [], str(root))
    assert row['verdict'] == 'no_claims' and 'project_digest' not in row['context']

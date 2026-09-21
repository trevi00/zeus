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
    CONTAINER_INTERPRETER,
    SCHEMA,
    SCHEMA_V2,
    observed_checks,
    parse_profile,
    requires_container,
    worker_schema,
)

PY = sys.executable
PROBE = 'zeus_backend_probe'  # a module that exists only under the candidate's backend/src
FAILING = 'zeus_backend_failing'
FAIL_EXIT = 1  # pytest's exit status for a failed test


def argv_for(module):
    """Profile version 1 accepts `python -m pytest`/`python -m ruff check` only (R1), so every probe
    is a real pytest run of one file in the backend context."""
    return ['python', '-m', 'pytest', f'probes/test_{module}.py', '-q', '-p', 'no:cacheprovider']
TASK = {'id': 'task-1', 'generation': 1, 'attempt': 1, 'lease_owner': 'worker'}
CANDIDATE = {'revision': 'a' * 40, 'base': 'b' * 40, 'tree': 'c' * 40}


def policy(**replay):
    base = {'version': 1, 'replay': {'allowed_argv_prefixes': [['python', '-m', 'pytest'], ['python', '-m', 'ruff', 'check'],
                                                             ['python', '-m', PROBE], ['ruff', 'check'],
                                                             ['uv', 'run', 'python', '-m', 'pytest']],
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
    (source / (PROBE + '.py')).write_text('VALUE = 1\n', encoding='utf-8')
    probes = root / 'backend' / 'probes'
    probes.mkdir()
    (probes / f'test_{PROBE}.py').write_text(
        'import os\nfrom pathlib import Path\n\n'
        f'import {PROBE}\n\n\n'
        'def test_context():\n'
        f'    assert {PROBE}.VALUE == 1\n'
        '    assert Path.cwd().name == "backend", Path.cwd()\n'
        '    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"\n'
        '    assert "ZEUS_SECRET" not in os.environ\n'
        '    assert os.environ["PYTHONPATH"].endswith("src")\n', encoding='utf-8')
    (probes / f'test_{FAILING}.py').write_text('def test_fails():\n    assert False\n', encoding='utf-8')
    return root


def document(checks=None, **context):
    return {'schema': SCHEMA,
            'contexts': {'backend': {'cwd': 'backend', 'interpreter': PY, 'source_paths': ['backend/src'],
                                     'dependency_files': ['backend/requirements.lock'], **context}},
            'checks': checks if checks is not None else [
                {'id': 'probe', 'context': 'backend', 'argv': argv_for(PROBE), 'expected_exit': 0}]}


def check(name, module, expected=0):
    return {'id': name, 'context': 'backend', 'argv': argv_for(module), 'expected_exit': expected}


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
    assert finding['original_argv'] == argv_for(PROBE) and finding['replay_argv'][1:] == argv_for(PROBE)[1:] and finding['replay_argv'][0] == PY
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
    doc = document([check('must-pass', FAILING, 0), check('negative', FAILING, FAIL_EXIT), check('probe', PROBE)])
    _, inspections = ledger(tmp_path, doc)
    row = inspections.inspect(TASK, CANDIDATE, [executed('must-pass', FAIL_EXIT), executed('negative', FAIL_EXIT),
                                                executed('probe', 1)], str(root))
    states = {f['check_id']: f for f in row['findings']}
    assert row['verdict'] == 'incomplete'
    assert states['must-pass']['state'] == 'verified_mismatch' and states['must-pass']['reported_exit'] == FAIL_EXIT
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
    assert all(c['argv'] == argv_for(PROBE) for c in claims)


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


# ----- version 2: the same contract, declared for the pinned container -------------------------
IMAGE = 'sha256:' + 'a' * 64


def container_document(checks=None, execution=None, **context):
    doc = document(checks, **{'interpreter': CONTAINER_INTERPRETER, **context})
    return {**doc, 'schema': SCHEMA_V2,
            'execution': {'kind': 'container', 'image': IMAGE} if execution is None else execution}


def test_version_two_declares_its_image_and_keeps_the_whole_version_one_grammar():
    parsed = parse_profile(container_document(), POLICY)
    v1 = parse_profile(document(), POLICY)
    assert parsed['schema'] == SCHEMA_V2 and parsed['execution'] == {'kind': 'container', 'image': IMAGE}
    assert requires_container(parsed) is True and requires_container(v1) is False
    assert parsed['checks'] == v1['checks'] and worker_schema(parsed) == worker_schema(v1)
    assert parsed['profile_digest'] != v1['profile_digest'], 'the version and image are part of the identity'
    assert parse_profile(container_document(execution={'kind': 'container', 'image': 'sha256:' + 'b' * 64}),
                         POLICY)['profile_digest'] != parsed['profile_digest']
    assert 'execution' not in v1, 'a version 1 profile keeps its exact old shape'


@pytest.mark.parametrize('mutation', [
    {'execution': {'kind': 'host', 'image': IMAGE}},
    {'execution': {'kind': 'container', 'image': 'sha256:' + 'A' * 64}},
    {'execution': {'kind': 'container', 'image': 'latest'}},
    {'execution': {'kind': 'container', 'image': IMAGE, 'mounts': ['/etc']}},
    {'execution': {'kind': 'container'}},
    {'interpreter': 'C:\\venv\\Scripts\\python.exe'},  # a host interpreter is never a container path
    {'interpreter': '/usr/bin/python3'}])
def test_version_two_refuses_an_unknown_execution_image_or_a_host_interpreter(mutation):
    with pytest.raises(ContractError):
        parse_profile(container_document(**mutation), POLICY)


@pytest.mark.parametrize('document_', [
    {**container_document(), 'schema': SCHEMA},  # version 1 with a version 2 field
    {k: v for k, v in container_document().items() if k != 'execution'},  # version 2 without one
    {**container_document(), 'schema': 'urn:zeus:project-evidence:3'}])
def test_an_unknown_version_or_a_mixed_document_is_refused(document_):
    with pytest.raises(ContractError):
        parse_profile(document_, POLICY)


def test_a_container_profile_is_loaded_without_requiring_a_host_interpreter(tmp_path, monkeypatch):
    """The version 2 interpreter is a path inside the image: no host file is verified or run for it,
    while a version 1 profile still refuses a host interpreter that does not exist."""
    path = tmp_path / 'container-profile.json'
    path.write_text(json.dumps(container_document()), encoding='utf-8')
    monkeypatch.setenv('HARNESS_EVIDENCE_PROFILE', str(path))
    loaded = load_profile(os.environ, POLICY)
    assert loaded['execution']['image'] == IMAGE and loaded['contexts']['backend']['interpreter'] == CONTAINER_INTERPRETER
    absent = tmp_path / 'host-profile.json'
    absent.write_text(json.dumps(document(interpreter=str(tmp_path / 'no-such-python'))), encoding='utf-8')
    monkeypatch.setenv('HARNESS_EVIDENCE_PROFILE', str(absent))
    with pytest.raises(ContractError):
        load_profile(os.environ, POLICY)


@pytest.mark.parametrize('checks', [
    [], [check('a', PROBE), check('a', PROBE)],
    [{'id': 'fmt', 'context': 'backend', 'argv': ['python', '-m', 'ruff', 'format', '.'], 'expected_exit': 0}],
    [{'id': 'sh', 'context': 'backend', 'argv': ['sh', '-c', 'python -m pytest'], 'expected_exit': 0}],
    [{'id': 'pip', 'context': 'backend', 'argv': ['python', '-m', 'pip', 'install', 'x'], 'expected_exit': 0}],
    [{'id': 'a', 'context': 'elsewhere', 'argv': argv_for(PROBE), 'expected_exit': 0}],
    [{'id': 'a', 'context': 'backend', 'argv': argv_for(PROBE), 'expected_exit': 0, 'required': False}]])
def test_profile_checks_are_closed_distinct_and_under_the_same_allowlist(checks):
    with pytest.raises(ContractError):
        parse_profile(document(checks), POLICY)


@pytest.mark.parametrize('argv', [
    ['uv', 'run', 'python', '-m', 'pytest', '-q'], ['ruff', 'check', '.'], ['python', '-m', PROBE],
    ['python', '-m', 'ruff'], ['python', '-mpytest'], ['python3', '-m', 'pytest']])
def test_r1_profile_refuses_every_form_whose_interpreter_replay_would_not_enforce(argv):
    """R1: the test policy AUTHORIZES the first three forms, so the refusal is the profile's own
    version-1 boundary, not the allowlist; the packaged legacy contract keeps them."""
    from codex_harness.adapters.evidence_inspection import packaged_policy
    from codex_harness.domain.evidence import authorized
    with pytest.raises(ContractError, match='not an authorized|python -m pytest or python -m ruff check'):
        parse_profile(document([{'id': 'a', 'context': 'backend', 'argv': argv, 'expected_exit': 0}]), POLICY)
    assert authorized(['uv', 'run', 'python', '-m', 'pytest', '-q'], packaged_policy()), 'legacy form untouched'
    for accepted in (['python', '-m', 'pytest', '-q'], ['python', '-m', 'ruff', 'check', '.']):
        parsed = parse_profile(document([{'id': 'a', 'context': 'backend', 'argv': accepted, 'expected_exit': 0}]),
                               packaged_policy())
        assert parsed['checks'][0]['argv'] == accepted


def test_r1_an_unenforceable_claim_never_reaches_capture(tmp_path, monkeypatch):
    """Defense in depth: a profile object that bypassed the parser still cannot spawn `uv`."""
    root = workspace(tmp_path)
    spawned = []
    monkeypatch.setattr('codex_harness.adapters.project_evidence._capture', lambda *a, **k: spawned.append(a) or {})
    inspect = inspector(tmp_path)
    inspect.profile = {**inspect.profile, 'checks': [{**inspect.profile['checks'][0],
                                                      'argv': ['uv', 'run', 'python', '-m', 'pytest']}]}
    found = inspect.inspect([executed('probe')], str(root), {})
    assert found['findings'][0]['state'] == 'not_checked' and not spawned


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def timed(tmp_path, monkeypatch, durations, total=1):
    """Deterministic clock and capture seam (labelled fake: no process runs); each fake replay exits 0
    after advancing the clock by its duration and records the timeout it was given."""
    root = workspace(tmp_path)
    inspect = ProjectEvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), parse_profile(document(), POLICY),
                                       policy(total_seconds=total, per_command_seconds=total))
    clock, given, pending = Clock(), [], list(durations)
    inspect.clock = clock

    def capture(argv, cwd, timeout, max_bytes, env, progress=None):
        given.append(timeout)
        clock.now += pending.pop(0)
        return {'failure': None, 'terminated': False, 'returncode': 0, 'duration_seconds': 0.0}
    monkeypatch.setattr('codex_harness.adapters.project_evidence._capture', capture)
    return inspect.inspect([executed('probe')], str(root), {})['findings'][0], given


def test_r2_each_repeat_gets_only_what_the_absolute_deadline_still_holds(tmp_path, monkeypatch):
    # The reviewer's probe: 0.75s + 0.75s under a 1s budget used to be all_checked at 1.5s.
    finding, given = timed(tmp_path, monkeypatch, [0.75, 0.75])
    assert given == [1.0, 0.25], 'the second repeat is given the remainder, never the original allowance'
    assert finding['state'] == 'not_checked' and 'late result is not counted' in finding['cause']
    assert finding['observed_exits'] == [0, 0] and finding['timeouts_seconds'] == [1.0, 0.25]


def test_r2_no_repeat_starts_at_or_beyond_the_deadline(tmp_path, monkeypatch):
    finding, given = timed(tmp_path, monkeypatch, [1.0, 0.1])
    assert given == [1.0], 'a partial first success is followed by exhaustion, not by another spawn'
    assert finding['state'] == 'not_checked' and 'exhausted before replay 2' in finding['cause']
    assert finding['observed_exits'] == [0]


def test_r2_timely_repeats_are_still_checked(tmp_path, monkeypatch):
    finding, given = timed(tmp_path, monkeypatch, [0.25, 0.25])
    assert given == [1.0, 0.75] and finding['state'] == 'checked' and finding['observed_exits'] == [0, 0]


def test_r2_a_real_second_replay_is_terminated_at_the_shrunken_timeout(tmp_path):
    """Real subprocesses: a 3s pytest sleep under a 5s aggregate budget. The first replay may fit; a
    second receives only the remainder and is terminated by the existing bounded capture."""
    root = workspace(tmp_path)
    (root / 'backend' / 'probes' / 'test_slow.py').write_text(
        'import time\n\n\ndef test_slow():\n    time.sleep(3)\n', encoding='utf-8')
    inspect = ProjectEvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), parse_profile(
        document([check('probe', 'slow')]), POLICY), policy(total_seconds=5, per_command_seconds=5))
    finding = inspect.inspect([executed('probe')], str(root), {})['findings'][0]
    assert finding['state'] != 'checked', finding
    assert len(finding['timeouts_seconds']) <= 2 and finding['timeouts_seconds'][0] == pytest.approx(5, abs=0.2)
    if len(finding['timeouts_seconds']) == 2:
        assert finding['timeouts_seconds'][1] < 2.1 and finding['runs'][1]['terminated'] is True


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

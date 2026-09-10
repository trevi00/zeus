"""FA-022: evidence inspection names what it checked, replays only what policy authorizes, keeps raw bytes
(INV-EVIDENCE-001).

The upstream observer returned CLEAN for directories, empty evidence, unreplayed claims and
permission errors, confirmed fabrication from the wrong cwd, executed the model's own command
and crashed on invalid UTF-8 output or a NUL path. Every replay below is a real child process.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest
from test_workflow import assignment

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import (
    POLICY_FILE,
    EvidenceInspector,
    packaged_policy,
    replay_environment,
)
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.evidence_inspection import BUCKET, NOTICES, EvidenceInspections
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.evidence import (
    STATES,
    authorized,
    classify_replays,
    denominator,
    parse_claim,
    parse_policy,
    verdict,
)
from codex_harness.domain.model import ContractError

PY = sys.executable


def policy(**replay):
    base = {'version': 1, 'replay': {'allowed_argv_prefixes': [[PY, '-c'], ['python', '-m', 'pytest'],
                                                             ['definitely-not-an-executable-zeus']],
                                     'per_command_seconds': 20, 'total_seconds': 60, 'max_claims': 8,
                                     'max_output_bytes': 4096, 'replays_per_claim': 2},
            'files': {'max_bytes': 1024 * 1024}}
    base['replay'].update(replay)
    return base


def inspector(tmp_path, **replay):
    return EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), policy(**replay))


def command(code, expected_exit=0):
    return {'kind': 'command', 'argv': [PY, '-c', code], 'expected_exit': expected_exit}


def test_policy_and_claims_are_closed_and_typed():
    packaged = packaged_policy()
    assert packaged['replay']['allowed_argv_prefixes'][0] == ['python', '-m', 'pytest']
    assert not authorized(['rm', '-rf', '/'], packaged) and not authorized(['python', '-c', 'x'], packaged)
    assert authorized(['python', '-m', 'pytest', '-q'], packaged) and json.loads(POLICY_FILE.read_text('utf-8'))
    for bad in ({'replay': {**policy()['replay'], 'per_command_seconds': 0}}, {'replay': {**policy()['replay'], 'total_seconds': 10**9}},
                {'replay': {**policy()['replay'], 'per_command_seconds': 100, 'total_seconds': 50}},
                {'replay': {**policy()['replay'], 'allowed_argv_prefixes': []}}, {'replay': {**policy()['replay'], 'max_claims': True}},
                {'version': 2}, {'files': {'max_bytes': float('inf')}}):
        with pytest.raises(ContractError):
            parse_policy({**policy(), **bad})
    assert parse_claim('python -m pytest -q tests')['argv'] == ['python', '-m', 'pytest', '-q', 'tests']
    assert parse_claim('python -m pytest')['origin'] == 'free_text' and parse_claim('python -m pytest')['expected_exit'] == 0
    file_claim = parse_claim({'kind': 'file', 'path': 'docs\\note.md', 'sha256': 'a' * 64, 'range': {'start': 1, 'end': 3}})
    assert file_claim['path'] == 'docs/note.md' and file_claim['id']
    for bad in ('', "unterminated 'quote", {'kind': 'file', 'path': '../secret'}, {'kind': 'file', 'path': '/etc/passwd'},
                {'kind': 'file', 'path': 'C:\\x'}, {'kind': 'file', 'path': 'a\x00b'}, {'kind': 'file', 'path': 'a', 'sha256': 'zz'},
                {'kind': 'file', 'path': 'a', 'range': {'start': 0, 'end': 1}}, {'kind': 'command', 'argv': []},
                {'kind': 'command', 'argv': ['x'], 'expected_exit': 'zero'}, {'kind': 'command', 'argv': ['x'], 'expected_exit': True},
                {'kind': 'command', 'argv': ['a\x00'], 'expected_exit': 0}, {'kind': 'other'}, 7):
        with pytest.raises(ContractError):
            parse_claim(bad)
    assert classify_replays([{'returncode': 0}, {'returncode': 0}], 0)[0] == 'checked'
    assert classify_replays([{'returncode': 0}, {'returncode': 1}], 0)[0] == 'flake_pattern'
    assert classify_replays([{'returncode': 2}, {'returncode': 2}], 0)[0] == 'verified_mismatch'
    assert classify_replays([{'returncode': None, 'failure': 'timeout'}], 0)[0] == 'replay_failed'
    assert verdict([]) == 'no_claims' and 'clean' not in STATES
    assert verdict([{'state': 'checked'}, {'state': 'unknown'}]) == 'incomplete'
    assert denominator([{'state': 'checked'}])['claims'] == 1
    with pytest.raises(ContractError, match='Unknown inspection state'):
        denominator([{'state': 'CLEAN'}])


def test_file_claims_are_checked_against_the_workspace_never_the_inspector_cwd(tmp_path):
    workspace = tmp_path / 'ws'
    (workspace / 'src').mkdir(parents=True)
    (workspace / 'src' / 'a.txt').write_bytes(b'line1\nline2\nline3\n')
    (tmp_path / 'a.txt').write_text('outside', encoding='utf-8')  # exists relative to the wrong cwd only
    insp = inspector(tmp_path)
    sha = hashlib.sha256(b'line1\nline2\nline3\n').hexdigest()
    report = insp.inspect([{'kind': 'file', 'path': 'src/a.txt', 'sha256': sha},
                           {'kind': 'file', 'path': 'src/a.txt', 'sha256': 'b' * 64},
                           {'kind': 'file', 'path': 'src/a.txt', 'range': {'start': 1, 'end': 9}},
                           {'kind': 'file', 'path': 'src/a.txt'},
                           {'kind': 'file', 'path': 'a.txt'},
                           {'kind': 'file', 'path': 'src'},
                           {'kind': 'file', 'path': 'nope/x.txt'},
                           {'kind': 'file', 'path': 'src/../../a.txt'}], workspace, {'task_id': 't', 'attempt': 1})
    states = [(f['state'], f['cause'][:40]) for f in report['findings']]
    assert states[0][0] == 'checked' and states[1] == ('verified_mismatch', 'content hash differs from the claim')
    assert states[2][0] == 'verified_mismatch' and 'file has 3' in report['findings'][2]['cause']
    assert states[3][0] == 'checked' and 'no hash was claimed' in report['findings'][3]['cause']
    assert states[4] == ('missing', 'no such file under the workspace'), 'the inspector cwd never resolves a claim'
    assert states[5] == ('missing', 'a directory is not evidence')
    assert states[6][0] == 'missing' and states[7][0] == 'error'
    assert report['context']['cwd'] == str(workspace.resolve()) and report['inspection_id']
    assert verdict(report['findings']) == 'incomplete'


def test_command_claims_replay_only_by_policy_and_keep_raw_bytes(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    insp = inspector(tmp_path)
    flaky = workspace / 'flake.txt'
    claims = [command('import sys; sys.exit(0)'),
              command('import sys; sys.exit(3)'),
              command('import sys; sys.stdout.buffer.write(b"ok\\xff\\xfe"); sys.exit(0)'),
              {'kind': 'command', 'argv': ['definitely-not-an-executable-zeus', '--version'], 'expected_exit': 0},
              command(f'import os,sys; p={str(flaky)!r}; n=os.path.exists(p); open(p,"w").close(); sys.exit(1 if n else 0)'),
              'rm -rf /',
              command('import sys; sys.stdout.write("x" * 10000); sys.exit(0)')]
    report = insp.inspect(claims, workspace, {'task_id': 't', 'attempt': 1})
    f = report['findings']
    assert f[0]['state'] == 'checked' and len(f[0]['runs']) == 2 and f[0]['runs'][0]['returncode'] == 0
    assert f[1]['state'] == 'verified_mismatch' and 'claimed 0' in f[1]['cause']
    assert f[2]['state'] == 'checked' and f[2]['runs'][0]['stdout']['decoding'].startswith('invalid_utf8')
    raw = json.loads(insp.artifacts.text(f[2]['runs'][0]['stdout']['ref'], 100000))
    assert raw['raw'].encode('latin-1') == b'ok\xff\xfe' and raw['sha256'] == hashlib.sha256(b'ok\xff\xfe').hexdigest()
    assert f[3]['state'] == 'replay_failed' and 'executable_missing' in f[3]['cause'] and len(f[3]['runs']) == 1
    assert f[4]['state'] == 'flake_pattern' and 'differ' in f[4]['cause']
    assert f[5]['state'] == 'not_checked' and 'not an authorized replay prefix' in f[5]['cause']
    assert f[6]['state'] == 'checked' and f[6]['runs'][0]['stdout']['truncated'] and f[6]['runs'][0]['stdout']['bytes'] == 4096
    assert all(run['stdout']['ref'].startswith('sha256:') for run in f[0]['runs'])
    assert f[0]['replay_argv'] == claims[0]['argv'] and f[0]['argv_identical']
    assert 'PYTHONIOENCODING' in report['context']['environment'] and 'ZEUS_DATABASE_URL' not in replay_environment({'ZEUS_DATABASE_URL': 'x', 'PATH': 'p'})
    assert denominator(f) == {**{s: 0 for s in STATES}, 'checked': 3, 'verified_mismatch': 1, 'replay_failed': 1,
                              'flake_pattern': 1, 'not_checked': 1, 'claims': 7}


def test_deadline_and_budgets_are_enforced_and_termination_is_recorded(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    insp = inspector(tmp_path, per_command_seconds=1, total_seconds=3, max_claims=2, replays_per_claim=1)
    started = time.monotonic()
    report = insp.inspect([command('import time; time.sleep(30)'), command('import sys; sys.exit(0)'),
                           command('import sys; sys.exit(0)')], workspace, {'task_id': 't', 'attempt': 1})
    assert time.monotonic() - started < 25, 'the child was terminated at its deadline'
    f = report['findings']
    assert f[0]['state'] == 'replay_failed' and f[0]['runs'][0]['terminated'] and 'timeout after 1s' in f[0]['cause']
    assert f[1]['state'] == 'checked'
    assert f[2]['state'] == 'not_checked' and f[2]['cause'] == 'claim budget exhausted'
    exhausted = inspector(tmp_path, per_command_seconds=1, total_seconds=1, replays_per_claim=1)
    report = exhausted.inspect([command('import time; time.sleep(5)'), command('import sys; sys.exit(0)')], workspace,
                               {'task_id': 't', 'attempt': 1})
    assert report['findings'][0]['state'] == 'replay_failed'
    assert report['findings'][1]['state'] == 'not_checked' and 'budget exhausted' in report['findings'][1]['cause']
    missing = insp.inspect([command('x')], tmp_path / 'absent', {'task_id': 't', 'attempt': 1})
    assert missing['findings'][0]['state'] == 'error' and 'workspace directory' in missing['findings'][0]['cause']


@pytest.mark.parametrize('backend', ['memory', 'postgres'])
def test_ledger_binds_the_inspection_to_the_execution_and_never_records_a_failure_as_success(backend, request, tmp_path, monkeypatch):
    store = MemoryStore() if backend == 'memory' else request.getfixturevalue('isolated_pgstore')
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner-1')
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    inspections = EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1))
    candidate = {'revision': 'c' * 40, 'base': 'b' * 40, 'tree': 'd' * 40}
    row = inspections.inspect(lease, candidate, [command('import sys; sys.exit(0)'), 'pytest -q'], workspace)
    assert row['verdict'] == 'incomplete' and row['denominator']['checked'] == 1 and row['denominator']['not_checked'] == 1
    assert row['binding'] == {'task_id': lease['id'], 'generation': 1, 'attempt': 1, 'owner': 'owner-1',
                              'source_revision': 'c' * 40, 'base': 'b' * 40, 'tree': 'd' * 40, 'workspace': str(workspace)}
    assert inspections.inspect(lease, candidate, [command('import sys; sys.exit(0)'), 'pytest -q'], workspace) == row
    with store.transaction() as tx:
        with pytest.raises(ContractError, match='Evidence inspection is incomplete: checked=1, not_checked=1'):
            inspections.require_all_checked(tx, row['id'])
    checked = inspections.inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert checked['verdict'] == 'all_checked' and checked['id'] != row['id']
    with store.transaction() as tx:
        assert inspections.require_all_checked(tx, checked['id'])['id'] == checked['id']
        assert inspections.require_all_checked(tx, checked['id'], policy_hash=checked['policy_hash'],
                                               binding={'task_id': lease['id'], 'source_revision': 'c' * 40})['id'] == checked['id']
        with pytest.raises(ContractError, match='another policy'):
            inspections.require_all_checked(tx, checked['id'], policy_hash='f' * 64)
        with pytest.raises(ContractError, match='another execution or revision'):
            inspections.require_all_checked(tx, checked['id'], binding={'source_revision': 'e' * 40})
        with pytest.raises(ContractError, match='missing'):
            inspections.require_all_checked(tx, 'nope')
    # Review counterexample (PR #54): a stricter policy for the same execution, revision and claims must
    # inspect again instead of reading back the old all_checked row.
    stricter = EvidenceInspections(store, inspector(tmp_path, replays_per_claim=1, allowed_argv_prefixes=[['definitely-not-an-executable-zeus']]))
    again = stricter.inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert again['id'] != checked['id'] and again['verdict'] == 'incomplete' and again['policy_hash'] != checked['policy_hash']
    assert again['denominator']['not_checked'] == 1 and again['inspector']['policy_hash'] == again['policy_hash']
    assert set(again['inspector']) == {'policy_hash', 'environment_names', 'environment_digest', 'tool', 'platform'}
    # Review counterexample (PR #54, round 2): the same environment *names* with a changed value must not reuse a
    # pass. The value digest is in the identity and the replay runs under the snapshot that identity was taken from.
    gate = command('import os, sys; sys.exit(0 if os.environ.get("LANG") == "review-pass" else 3)')
    monkeypatch.setenv('LANG', 'review-pass')
    passing = inspections.inspect(lease, candidate, [gate], workspace)
    assert passing['verdict'] == 'all_checked' and passing['context']['environment_digest'] == passing['inspector']['environment_digest']
    monkeypatch.setenv('LANG', 'review-fail')
    failing = inspections.inspect(lease, candidate, [gate], workspace)
    assert failing['id'] != passing['id'] and failing['verdict'] == 'incomplete', 'a changed value is a new inspection, not a cache hit'
    assert failing['inspector']['environment_digest'] != passing['inspector']['environment_digest']
    assert failing['inspector']['environment_names'] == passing['inspector']['environment_names']
    assert inspections.inspect(lease, candidate, [gate], workspace) == failing, 'and the failing result is what the cache now holds'
    # The snapshot handed to the inspector is the environment the child actually runs under.
    direct = inspections.inspector.inspect([gate], workspace, inspections.binding(lease, candidate, workspace),
                                           environment={**inspections.inspector.snapshot()['environment'], 'LANG': 'review-pass'})
    assert direct['findings'][0]['state'] == 'checked' and direct['context']['environment_digest'] != failing['context']['environment_digest']
    with store.transaction() as tx:
        with pytest.raises(ContractError, match='Evidence inspection is incomplete'):
            stricter.require_all_checked(tx, again['id'])
        assert inspections.require_all_checked(tx, checked['id'])['policy_hash'] == checked['policy_hash'], 'the old row still exists, under its own policy'

    class OtherHost:
        def __init__(self, inner):
            self.inner, self.policy = inner, inner.policy
        def snapshot(self):
            inner = self.inner.snapshot()
            return {**inner, 'identity': {**inner['identity'], 'platform': 'fixture-other-host'}}
        def inspect(self, claims, cwd, binding, environment=None):
            return self.inner.inspect(claims, cwd, binding, environment=environment)
    elsewhere = EvidenceInspections(store, OtherHost(inspector(tmp_path, replays_per_claim=1))).inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert elsewhere['id'] != checked['id'] and elsewhere['inspector']['platform'] == 'fixture-other-host'
    with pytest.raises(ContractError, match='typed execution lease'):
        inspections.inspect({'id': lease['id']}, candidate, [], workspace)
    with pytest.raises(ContractError, match='candidate revision'):
        inspections.inspect(lease, {}, [], workspace)
    empty = inspections.inspect(lease, candidate, [], workspace)
    assert empty['verdict'] == 'no_claims', 'no claims is not all checked'


class RecordingFails:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def transaction(self):
        self.calls += 1
        if self.calls == 2:  # the read succeeds, the write does not
            raise OSError('Explicit ledger write failure fixture')
        return self.inner.transaction()


def test_recording_failure_is_a_named_notice_not_a_success(tmp_path):
    store = MemoryStore()
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner-1')
    workspace = tmp_path / 'ws'
    workspace.mkdir()
    failing = RecordingFails(store)
    inspections = EvidenceInspections(failing, inspector(tmp_path, replays_per_claim=1))
    with pytest.raises(ContractError, match='could not be recorded'):
        inspections.inspect(lease, {'revision': 'c' * 40}, [command('import sys; sys.exit(0)')], workspace)
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and len(tx.scan(NOTICES)) == 1
        notice = tx.scan(NOTICES)[0]
    assert notice['verdict'] == 'all_checked' and 'OSError' in notice['reason'], 'what happened is recorded, not a row'


def test_executor_inspects_implementation_claims_in_the_workspace(setup_implementation):
    s = setup_implementation
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    inspection = row['result']['evidence_inspection']
    assert inspection['verdict'] == 'incomplete' and inspection['denominator']['claims'] == 2
    with s.service.store.transaction() as tx:
        stored = tx.get(BUCKET, inspection['inspection_id'])
    assert stored['binding']['task_id'] == row['id'] and stored['binding']['source_revision'] == row['result']['candidate']['revision']
    states = {f['claim']['argv'][0] if f['claim']['kind'] == 'command' else 'file': f['state'] for f in stored['findings']}
    assert states[PY] == 'checked' and states['rm'] == 'not_checked'
    assert Path(stored['binding']['workspace']).resolve() == Path(stored['context']['cwd']).resolve()


@pytest.fixture
def setup_implementation(tmp_path, monkeypatch):
    """A real executor whose implement step runs a fixture runtime; the workspace is a real Git clone."""
    from types import SimpleNamespace

    from test_git_workspace import repository

    from codex_harness.adapters.executor import Executor
    from codex_harness.adapters.git import GitWorkspace
    from codex_harness.application.service import Harness
    from codex_harness.domain.model import envelope

    root = repository(tmp_path)
    git = GitWorkspace(str(root), str(tmp_path / 'workspaces'))
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    executor = Executor(service, git, artifacts)
    executor.evidence = EvidenceInspections(service.store, EvidenceInspector(artifacts, policy(replays_per_claim=1)))
    revision = git._git('rev-parse', 'HEAD')

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            Path(cwd, 'change.txt').write_text('implemented', encoding='utf-8')
            answer = {'summary': 'fixture implementation', 'tests': [f'{PY} -c "import sys; sys.exit(0)"', 'rm -rf build']}
            return {'answer': answer, 'events': [], 'thread_id': 'thread', 'turn_id': 'turn', 'usage': None,
                    'rotate': False, 'interrupted': False, 'requested_model': kwargs.get('model')}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    parent = organization().actor('worker:implementation').parent
    message = envelope('task.assign', parent, 'worker:implementation', 'implement',
                       {'plan': {'objective': 'fixture', 'acceptance_criteria': ['x'], 'allowed_paths': ['change.txt']}},
                       'fixture', None)
    message['where']['revision'] = revision
    executor.workflow.submit(message)
    return SimpleNamespace(executor=executor, service=service, artifacts=artifacts)

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
    replay_argv,
    replay_environment,
    trusted_interpreter,
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
TRUSTED = str(Path(sys.executable).resolve())
PROBE = 'zeus_candidate_probe'  # a module that exists only under the candidate workspace's src


def policy(**replay):
    base = {'version': 1, 'replay': {'allowed_argv_prefixes': [[PY, '-c'], ['python', '-m', 'pytest'],
                                                             ['python', '-m', PROBE],
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
    assert f[3]['replay_argv'] == claims[3]['argv'] and f[3]['argv_identical'], 'a non-python command runs exactly as claimed'
    assert f[4]['state'] == 'flake_pattern' and 'differ' in f[4]['cause']
    assert f[5]['state'] == 'not_checked' and 'not an authorized replay prefix' in f[5]['cause']
    assert f[6]['state'] == 'checked' and f[6]['runs'][0]['stdout']['truncated'] and f[6]['runs'][0]['stdout']['bytes'] == 4096
    assert all(run['stdout']['ref'].startswith('sha256:') for run in f[0]['runs'])
    assert f[0]['replay_argv'] == f[0]['original_argv'] == claims[0]['argv'] and f[0]['argv_identical']
    assert f[0]['argv_transformation'] is None and f[0]['interpreter'] == TRUSTED
    assert 'PYTHONIOENCODING' in report['context']['environment'] and 'ZEUS_DATABASE_URL' not in replay_environment({'ZEUS_DATABASE_URL': 'x', 'PATH': 'p'})
    assert report['context']['interpreter'] == TRUSTED and report['context']['pythonpath'] is None, 'no src, no PYTHONPATH'
    assert denominator(f) == {**{s: 0 for s in STATES}, 'checked': 3, 'verified_mismatch': 1, 'replay_failed': 1,
                              'flake_pattern': 1, 'not_checked': 1, 'claims': 7}


def probe_workspace(tmp_path):
    """A candidate whose src holds a module nothing else on this host can import."""
    workspace = tmp_path / 'candidate ws'
    (workspace / 'src').mkdir(parents=True)
    (workspace / 'src' / (PROBE + '.py')).write_text(
        'import os, sys\n'
        'print("EXECUTABLE=" + sys.executable)\n'
        'print("MODULE=" + os.path.abspath(__file__))\n'
        'print("PYTHONPATH=" + os.environ.get("PYTHONPATH", "<unset>"))\n'
        'sys.exit(0)\n', encoding='utf-8')
    return workspace


def test_python_replays_run_the_trusted_interpreter_against_the_candidate_source(tmp_path, monkeypatch):
    """Real subprocess (review-contract-001): the canary's replay failed with `C:/Python314/python.exe: No
    module named pytest` because `python` resolved to another interpreter. The replay now names the
    verified host interpreter and binds PYTHONPATH to the candidate's src, whatever PATH or the parent's
    PYTHONPATH say, and the finding records both the original and the effective argv."""
    workspace = probe_workspace(tmp_path)
    monkeypatch.setenv('PATH', str(tmp_path / 'no-interpreter-here'))
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'parent-leak'))
    insp = inspector(tmp_path, replays_per_claim=1)
    snapshot = insp.snapshot(workspace)
    assert snapshot['identity']['interpreter'] == snapshot['interpreter'] == TRUSTED
    assert snapshot['identity']['cwd'] == str(workspace.resolve())
    assert snapshot['environment']['PYTHONPATH'] == str((workspace / 'src').resolve()), 'the candidate src, not the parent value'
    assert 'parent-leak' not in json.dumps(snapshot['environment'])
    assert 'PYTHONPATH' not in insp.snapshot(tmp_path)['environment'], 'no src, no PYTHONPATH'
    # The parent environment changes after the snapshot; the replay still runs under the snapshot.
    monkeypatch.setenv('PATH', str(tmp_path / 'changed-again'))
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'changed-leak'))
    report = insp.inspect(['python -m ' + PROBE, {'kind': 'command', 'argv': [PY, '-m', PROBE], 'expected_exit': 0},
                           'python -m pytest --version'],
                          workspace, {'task_id': 't', 'attempt': 1},
                          environment=snapshot['environment'], interpreter=snapshot['interpreter'])
    checked, widened, pytest_claim = report['findings']
    assert checked['state'] == 'checked', checked['cause']
    assert checked['original_argv'] == ['python', '-m', PROBE]
    assert checked['replay_argv'] == [TRUSTED, '-m', PROBE] and checked['argv_identical'] is False
    assert 'trusted host interpreter' in checked['argv_transformation'] and 'original argv' in checked['argv_transformation']
    out = json.loads(insp.artifacts.text(checked['runs'][0]['stdout']['ref'], 100000))['raw']
    assert 'EXECUTABLE=' + TRUSTED in out.replace('\r', '')
    assert 'MODULE=' + str((workspace / 'src' / (PROBE + '.py')).resolve()) in out.replace('\r', '')
    assert 'PYTHONPATH=' + str((workspace / 'src').resolve()) in out.replace('\r', '')
    assert 'changed-leak' not in out and 'parent-leak' not in out
    # A claim that names an interpreter itself is not the policy's `python -m` prefix: nothing widens.
    assert widened['state'] == 'not_checked' and 'not an authorized replay prefix' in widened['cause']
    # The packaged-style prefix is rewritten the same way; whether pytest is importable is the host's fact.
    assert pytest_claim['replay_argv'][:3] == [TRUSTED, '-m', 'pytest'] and pytest_claim['argv_identical'] is False
    assert report['context']['interpreter'] == TRUSTED and report['context']['pythonpath'] == str((workspace / 'src').resolve())
    assert replay_argv(['python', '-m', 'ruff', 'check', '.'], TRUSTED)[0] == [TRUSTED, '-m', 'ruff', 'check', '.']
    assert replay_argv(['uv', 'run', 'python', '-m', 'pytest'], TRUSTED) == (['uv', 'run', 'python', '-m', 'pytest'], None)
    assert replay_argv(['python', 'script.py'], TRUSTED) == (['python', 'script.py'], None), 'only python -m is rewritten'
    assert trusted_interpreter() == Path(TRUSTED)


def test_the_profile_metadata_module_replays_only_as_its_exact_argv(tmp_path):
    """Issue 124: the packaged policy grants the no-argument metadata command and nothing beside it.
    Real subprocess: the replay runs in this checkout, whose packaged profile is what the loader verifies."""
    packaged = packaged_policy()
    exact = ['python', '-m', 'codex_harness.adapters.worker_profile_metadata']
    assert exact in packaged['replay']['allowed_argv_prefixes'] and authorized(exact, packaged)
    refused = ([*exact, '--help'], [*exact, 'src'], [*exact, ''], ['python', '-m', 'codex_harness.adapters.worker_profile'],
               ['python', '-m', 'codex_harness.adapters.worker_profile_metadata.extra'],
               ['python', '-m', 'codex_harness.adapters.artifact_reader'], [PY, *exact[1:]], ['uv', 'run', *exact])
    assert not any(authorized(argv, packaged) for argv in refused)
    broad = parse_policy({**policy(), 'replay': {**policy()['replay'], 'allowed_argv_prefixes': [['python', '-m'], exact]}})
    assert authorized(exact, broad) and not authorized([*exact, '--help'], broad), 'exact even under a broader prefix'
    assert authorized(['python', '-m', 'pytest', '-q'], broad), 'other commands keep prefix semantics'
    assert authorized(['python', '-m', 'pytest', '-q'], packaged) and authorized(['python', '-m', 'ruff', 'check', '.'], packaged)
    assert not authorized(exact, parse_policy(policy())), 'no policy entry, no grant'
    insp = EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')))
    checkout = Path(__file__).resolve().parents[1]
    report = insp.inspect([' '.join(exact), ' '.join(exact) + ' --help', 'python -m codex_harness.adapters.worker_profile'],
                          checkout, {'task_id': 't', 'attempt': 1})
    checked, extra, other = report['findings']
    assert checked['state'] == 'checked', checked['cause']
    assert checked['replay_argv'] == [TRUSTED, *exact[1:]] and checked['original_argv'] == exact
    observed = json.loads(json.loads(insp.artifacts.text(checked['runs'][0]['stdout']['ref'], 100000))['raw'])
    assert observed['status'] == 'ok' and observed['digest_matches'] and observed['within_limit']
    for finding in (extra, other):
        assert finding['state'] == 'not_checked' and 'not an authorized replay prefix' in finding['cause']
        assert 'runs' not in finding or not finding['runs']


def test_a_missing_trusted_interpreter_is_refused_before_any_child_and_never_recorded_as_success(tmp_path, setup_implementation):
    missing = str(tmp_path / 'missing-python')
    insp = EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')), policy(), interpreter=missing)
    workspace = probe_workspace(tmp_path)
    with pytest.raises(ContractError, match='Trusted replay interpreter is not a file'):
        insp.snapshot(workspace)
    with pytest.raises(ContractError, match='Trusted replay interpreter is not a file'):
        insp.inspect(['python -m ' + PROBE], workspace, {'task_id': 't', 'attempt': 1})
    with pytest.raises(ContractError, match='not a file'):
        trusted_interpreter(str(tmp_path))  # a directory is not an interpreter either
    store = MemoryStore()
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim('worker:implementation', 'owner-1')
    with pytest.raises(ContractError, match='Trusted replay interpreter is not a file'):
        EvidenceInspections(store, insp).inspect(lease, {'revision': 'c' * 40}, ['python -m ' + PROBE], workspace)
    with store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and tx.scan(NOTICES) == [], 'nothing ran, so nothing is recorded'
    # Through the executor the refusal is a named inspection_error on the result, never a verdict.
    s = setup_implementation
    s.executor.evidence = EvidenceInspections(s.service.store, EvidenceInspector(s.artifacts, policy(), interpreter=missing))
    row = s.executor.execute_one('worker:implementation')
    assert row['status'] == 'succeeded', row.get('error')
    assert row['result']['evidence_inspection']['verdict'] == 'inspection_error'
    assert 'Trusted replay interpreter is not a file' in row['result']['evidence_inspection']['cause']


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
    assert set(again['inspector']) == {'policy_hash', 'environment_names', 'environment_digest', 'tool', 'platform',
                                       'interpreter', 'cwd'}
    assert again['inspector']['interpreter'] == TRUSTED == again['context']['interpreter']
    assert again['inspector']['cwd'] == str(workspace.resolve())
    # review-contract-001: the same execution, claims and policy under another cwd, interpreter or candidate
    # src binding is a new inspection; the older row is neither reused nor overwritten.
    other_workspace = tmp_path / 'ws2'
    other_workspace.mkdir()
    moved = inspections.inspect(lease, candidate, [command('import sys; sys.exit(0)')], other_workspace)
    assert moved['id'] != checked['id'] and moved['verdict'] == 'all_checked' and moved['inspector']['cwd'] == str(other_workspace.resolve())
    other_python = tmp_path / 'other-python'
    other_python.write_text('# stands in for another interpreter file; the [PY, -c] claim never runs it\n', encoding='utf-8')
    elsewhere_interpreter = EvidenceInspections(store, EvidenceInspector(FileArtifacts(str(tmp_path / 'artifacts')),
                                                                          policy(replays_per_claim=1), interpreter=str(other_python)))
    rebound = elsewhere_interpreter.inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert rebound['id'] != checked['id'] and rebound['inspector']['interpreter'] == str(other_python.resolve())
    assert rebound['findings'][0]['argv_identical'] and rebound['findings'][0]['replay_argv'][0] == PY
    (workspace / 'src').mkdir()
    with_src = inspections.inspect(lease, candidate, [command('import sys; sys.exit(0)')], workspace)
    assert with_src['id'] != checked['id'] and with_src['context']['pythonpath'] == str((workspace / 'src').resolve())
    assert with_src['inspector']['environment_digest'] != checked['inspector']['environment_digest']
    assert 'PYTHONPATH' in with_src['inspector']['environment_names'] and 'PYTHONPATH' not in checked['inspector']['environment_names']
    with store.transaction() as tx:
        assert tx.get(BUCKET, checked['id']) == checked, 'the earlier row is untouched'
    (workspace / 'src').rmdir()
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
        def snapshot(self, cwd=None):
            inner = self.inner.snapshot(cwd)
            return {**inner, 'identity': {**inner['identity'], 'platform': 'fixture-other-host'}}
        def inspect(self, claims, cwd, binding, environment=None, interpreter=None):
            return self.inner.inspect(claims, cwd, binding, environment=environment, interpreter=interpreter)
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
    assert stored['inspector']['interpreter'] == stored['context']['interpreter'] == TRUSTED
    assert stored['inspector']['cwd'] == stored['context']['cwd']


def test_read_only_runs_receive_a_host_composed_review_context_and_implementation_runs_do_not(tmp_path, monkeypatch):
    """review-contract-001: the reviewer is told which interpreter and checkout to test, by the host."""
    from types import SimpleNamespace

    from codex_harness.adapters.executor import IMPLEMENTATION, VERDICT, Executor
    from codex_harness.adapters.output_schema import preflight
    from codex_harness.application.service import Harness

    prompts = []

    class Runtime:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def run(self, prompt, cwd, schema, timeout, **kwargs):
            prompts.append((json.loads(prompt), kwargs['read_only']))
            answer = {'accepted': True, 'reason': 'fixture', 'blocked': False, 'risks': [], 'sre_assessment': 'n/a',
                      'arc42_assessment': 'n/a'} if kwargs['read_only'] else {'summary': 'fixture', 'tests': []}
            return {'answer': answer, 'events': [], 'thread_id': 'thread', 'turn_id': 'turn', 'usage': None,
                    'rotate': False, 'interrupted': False, 'requested_model': kwargs.get('model')}

    monkeypatch.setattr('codex_harness.adapters.executor.AppServer', Runtime)
    service = Harness(MemoryStore(), organization())
    executor = Executor(service, SimpleNamespace(_git=lambda *a, **k: 'revision'), FileArtifacts(str(tmp_path / 'artifacts')))
    review = tmp_path / 'review checkout'
    (review / 'src').mkdir(parents=True)
    executor._run('lead:improvement', 'review', 'Evaluate review_lead', {'candidate': {'revision': 'c' * 40}},
                  str(review), VERDICT, read_only=True)
    executor._run('worker:implementation', 'task', 'Implement', {'plan': {'objective': 'x', 'acceptance_criteria': ['y'],
                  'allowed_paths': ['z']}}, str(tmp_path), IMPLEMENTATION)
    (reviewer, read_only), (worker, writes) = prompts
    assert read_only and not writes
    context = reviewer['required']['review_context']
    assert context['interpreter'] == TRUSTED and context['cwd'] == str(review.resolve())
    assert context['src'] == str((review / 'src').resolve())
    assert 'stdout' in context['instruction'] and 'do not create frame' in context['instruction']
    assert 'review_context' not in worker['required'], 'an implementer edits its workspace; the review context is for reviewers'
    # The implementation schema separates executed commands from result descriptions and still preflights.
    assert preflight(IMPLEMENTATION)['schema_hash']
    assert 'Only the exact commands you actually executed' in IMPLEMENTATION['properties']['tests']['description']
    assert 'No arrows, results, pass counts' in IMPLEMENTATION['properties']['tests']['description']
    assert 'what was not run' in IMPLEMENTATION['properties']['summary']['description']
    # Past claims are parsed as written: a result arrow in a tests string is part of the argv, not stripped.
    assert parse_claim('python -m pytest tests -q -> 23 passed')['argv'][-3:] == ['->', '23', 'passed']


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

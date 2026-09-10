"""The environment evidence runner owns only what it creates, records every failure as a failure and binds the run.

Review counterexamples (PR #69): an arbitrary --project could `down --volumes` someone else's stack; setup, teardown
and timeout failures produced passed=true; the tests could talk to a database other than the recorded containers;
the receipt could not reconstruct the runner bytes. The runner is exercised here through a fake shell.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('environment_evidence', Path(__file__).resolve().parents[1] / 'scripts' / 'environment_evidence.py')
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class FakeShell:
    """Answers docker/git/uv commands from a script; every invocation is kept for assertions."""

    def __init__(self, tmp_path, *, fail=None, timeout=None, existing_project=False, leftovers=False):
        self.calls, self.tmp_path = [], tmp_path
        self.fail, self.timeout = fail or set(), timeout or set()
        self.existing_project, self.leftovers, self.down_seen = existing_project, leftovers, False
        self.counters = {'xact': 100, 'commands': 10}

    def run(self, argv, env=None, timeout=3600, cwd=None):
        self.calls.append({'argv': list(argv), 'env': dict(env or {}), 'timeout': timeout})
        key = self.key(argv)
        if key in self.timeout:
            return {'returncode': None, 'stdout': '', 'stderr': '', 'seconds': float(timeout), 'timed_out': True, 'error': f'timeout after {timeout}s'}
        if key in self.fail:
            return self.done(1, '', f'{key} failed (fixture)')
        return self.done(0, self.answer(key, argv))

    @staticmethod
    def done(code, out, err=''):
        return {'returncode': code, 'stdout': out, 'stderr': err, 'seconds': 0.1, 'timed_out': False, 'error': None}

    @staticmethod
    def key(argv):
        if argv[:2] == ['docker', 'compose']:
            return 'compose:' + next((a for a in argv[2:] if a in {'up', 'down', 'ps', 'port', 'version', 'config'}), 'unknown')
        if argv[:2] == ['docker', 'exec']:
            return 'psql' if 'psql' in argv else 'redis-cli'
        if argv[0] == 'docker':
            return 'docker:' + argv[1] + (':' + argv[2] if argv[1] in {'volume', 'network'} else '')
        if argv[0] == 'git':
            return 'git:' + argv[1]
        if argv[:2] == ['uv', 'run'] and 'pytest' in ' '.join(argv):
            return 'pytest:' + ('docker' if 'tests/test_verification.py' in argv else 'full')
        return ' '.join(argv[:3])

    def answer(self, key, argv):
        if key == 'git:rev-parse':
            return 'abc123\n'
        if key == 'git:status':
            return ' M src/x.py\n?? scratch.txt\n'
        if key == 'docker:ps':
            return 'deadbeef\n' if self.existing_project and not self.down_seen else ''
        if key in {'docker:volume:ls', 'docker:network:ls'}:
            return 'vol-leftover\n' if self.leftovers and self.down_seen and key == 'docker:volume:ls' else ''
        if key == 'compose:up':
            return ''
        if key == 'compose:ps':
            return 'pgcontainer\n' if 'postgres' in argv else 'rdcontainer\n'
        if key == 'compose:port':
            return '127.0.0.1:61001\n' if 'postgres' in argv else '127.0.0.1:61002\n'
        if key == 'compose:down':
            self.down_seen = True
            return ''
        if key == 'psql':
            if 'system_identifier' in argv[-1]:
                return '7412345678901234567\n'
            self.counters['xact'] += 50
            return f"{self.counters['xact']}\n"
        if key == 'redis-cli':
            self.counters['commands'] += 500
            return f"run_id:abcdef0123456789\r\ntotal_commands_processed:{self.counters['commands']}\r\n"
        if key == 'pytest:full':
            self.dotenv_seen = (self.tmp_path / '.env').read_text(encoding='utf-8')
            dsn = self.dotenv_seen.split('HARNESS_DATABASE_URL=')[1].splitlines()[0]
            junit = next(a for a in argv if a.startswith('--junitxml='))[len('--junitxml='):]
            Path(junit).parent.mkdir(parents=True, exist_ok=True)
            Path(junit).write_text('<testsuites><testsuite><testcase classname="tests.test_a" name="t1" file="tests/test_a.py"/>'
                                   '<testcase classname="tests.test_a" name="t2" file="tests/test_a.py"><skipped/></testcase>'
                                   '<testcase classname="tests.test_b" name="t3" file="tests/test_b.py"/></testsuite></testsuites>', encoding='utf-8')
            return f'..s\nE   AssertionError: assert {dsn} == other\n2 passed, 1 skipped in 1.0s\n'
        if key == 'pytest:docker':
            return '..\n2 passed in 1.0s\n'
        if argv[:3] == ['uv', 'run', 'ruff']:
            return 'All checks passed!\n'
        if key.startswith(('uv', 'docker:version', 'docker:compose')):
            return 'fixture-version\n'
        return ''


def run(tmp_path, monkeypatch, **shell_options):
    monkeypatch.setenv('ZEUS_DATABASE_URL', 'postgresql://someone:secret@10.0.0.9:5432/other')
    monkeypatch.setenv('HARNESS_REDIS_URL', 'redis://10.0.0.9:6379/0')
    (tmp_path / 'compose.yaml').write_text('services: {}\n', encoding='utf-8')
    (tmp_path / '.env').write_text('ORIGINAL=1\n', encoding='utf-8')
    (tmp_path / 'uv.lock').write_text('lock\n', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text('[project]\n', encoding='utf-8')
    shell = FakeShell(tmp_path, **shell_options)
    receipt = evidence.EvidenceRun('host-a', 'out', shell=shell, root=tmp_path).execute()
    return receipt, shell


def test_a_passing_run_binds_services_inputs_and_isolates_the_environment(tmp_path, monkeypatch):
    receipt, shell = run(tmp_path, monkeypatch)
    assert receipt['passed'] is True and receipt['head'] == 'abc123'
    assert receipt['compose_project'].startswith('harness-evidence-host-a-') and len(receipt['compose_project'].split('-')[-1]) == 8
    # Source binding: tracked and untracked changes are listed, and the execution inputs are digested.
    assert receipt['tracked_changes'] == [' M src/x.py'] and receipt['untracked'] == ['scratch.txt']
    assert set(receipt['inputs']) == {'runner', 'compose', 'uv.lock', 'pyproject.toml', 'override'} and all(v.startswith('sha256:') for v in receipt['inputs'].values())
    # The tests ran with nothing inherited from the parent; the stack was pinned through the repository .env
    # (the CI mechanism), which is restored afterwards.
    pytest_env = next(c['env'] for c in shell.calls if c['argv'][:2] == ['uv', 'run'] and 'pytest' in c['argv'])
    injected = {k for k in pytest_env if k.startswith(('ZEUS_', 'HARNESS_', 'POSTGRES_', 'COMPOSE_'))}
    assert injected <= {'HARNESS_INTEGRATION', 'ZEUS_TEST_DOCKER'}, 'only the run flags; no inherited or injected service variable'
    assert '10.0.0.9' not in json.dumps(pytest_env)
    dotenv_at_run = shell.dotenv_seen
    assert 'HARNESS_DATABASE_URL=postgresql://harness:' in dotenv_at_run and '@127.0.0.1:61001/harness' in dotenv_at_run
    assert 'HARNESS_REDIS_URL=redis://127.0.0.1:61002/0' in dotenv_at_run and f"ZEUS_REDIS_NAMESPACE={receipt['compose_project']}" in dotenv_at_run
    assert (tmp_path / '.env').read_text(encoding='utf-8') == 'ORIGINAL=1\n', 'the previous .env is back'
    stack = receipt['phases']['stack_up']
    assert stack['database_url'] == 'postgresql://harness:***@127.0.0.1:61001/harness' and 'ZEUS_DATABASE_URL' in stack['dropped_inherited']
    assert stack['pinning']['dotenv_run_sha256'].startswith('sha256:') and any('harness:***@' in line for line in stack['pinning']['dotenv_run'])
    assert receipt['phases']['teardown']['dotenv'] == 'restored to its previous content'
    # The per-run password is scrubbed from logs even when a test prints the DSN.
    log = (tmp_path / 'out' / 'host-a-full-suite-integration.log').read_text(encoding='utf-8')
    assert 'harness:***@127.0.0.1:61001' in log and 'secret' not in json.dumps(receipt)
    assert not any(len(token) == 32 and all(c in '0123456789abcdef' for c in token) for token in log.replace('@', ' ').replace(':', ' ').split())
    # Service identity was observed before and after, is the same, and the counters of this stack moved.
    assert receipt['phases']['identity_before']['postgres']['system_identifier'] == '7412345678901234567'
    assert receipt['phases']['identity_stable']['same_services'] is True and receipt['phases']['identity_stable']['traffic'] == {'postgres_xact_commit': 50, 'redis_commands': 500}
    # The compose invocations name the project and both files; the override publishes ephemeral loopback ports.
    ups = [c['argv'] for c in shell.calls if c['argv'][:2] == ['docker', 'compose'] and 'up' in c['argv']]
    assert ups and ups[0][2:4] == ['-p', receipt['compose_project']] and ups[0][4] == '-f' and ups[0][6] == '-f'
    assert (tmp_path / 'out' / 'host-a-compose.override.yaml').read_text(encoding='utf-8') == evidence.OVERRIDE
    assert receipt['per_file'] == {'test_a.py': {'passed': 1, 'skipped': 1, 'failed': 0, 'error': 0}, 'test_b.py': {'passed': 1, 'skipped': 0, 'failed': 0, 'error': 0}}
    downs = [c['argv'] for c in shell.calls if c['argv'][:2] == ['docker', 'compose'] and 'down' in c['argv']]
    assert len(downs) == 1 and downs[0][3] == receipt['compose_project'] and receipt['phases']['teardown']['remaining'] == []
    assert json.loads((tmp_path / 'out' / 'host-a-receipt.json').read_text(encoding='utf-8'))['passed'] is True


def test_an_existing_project_is_refused_before_anything_is_created_or_removed(tmp_path, monkeypatch):
    receipt, shell = run(tmp_path, monkeypatch, existing_project=True)
    assert receipt['passed'] is False and receipt['phases']['claim_project']['ok'] is False
    assert receipt['phases']['claim_project']['found']['containers'] == ['deadbeef']
    assert not any(c['argv'][:2] == ['docker', 'compose'] and ('up' in c['argv'] or 'down' in c['argv']) for c in shell.calls), \
        'no up, no down: nothing of someone else is touched'
    assert 'stack_up' not in receipt['phases'] and receipt['steps'] == []


@pytest.mark.parametrize('failure, phase', [('compose:up', 'stack_up'), ('psql', 'identity_before')])
def test_setup_failures_are_failures_and_still_tear_down(tmp_path, monkeypatch, failure, phase):
    receipt, shell = run(tmp_path, monkeypatch, fail={failure})
    assert receipt['passed'] is False and receipt['phases'][phase]['ok'] is False
    assert receipt['steps'] == [], 'no test step runs on a broken stack'
    assert any('down' in c['argv'] for c in shell.calls if c['argv'][:2] == ['docker', 'compose']), 'what was created is removed'
    assert receipt['phases']['teardown']['ok'] is True


def test_a_step_timeout_and_a_failing_step_are_recorded_and_fail_the_run(tmp_path, monkeypatch):
    receipt, _ = run(tmp_path, monkeypatch, timeout={'pytest:full'})
    full = next(s for s in receipt['steps'] if s['name'] == 'full-suite-integration')
    assert full['timed_out'] is True and full['exit_code'] is None and full['ok'] is False and 'timeout' in full['error']
    assert len(receipt['steps']) == 3, 'later steps still run and are recorded'
    assert receipt['passed'] is False and receipt['phases']['steps']['ok'] is False and receipt['phases']['teardown']['ok'] is True
    failing, _ = run(tmp_path, monkeypatch, fail={'pytest:docker'})
    assert failing['passed'] is False and next(s for s in failing['steps'] if s['name'] == 'disposable-docker-checks')['exit_code'] == 1


def test_teardown_failure_fails_the_run_without_erasing_step_evidence(tmp_path, monkeypatch):
    receipt, _ = run(tmp_path, monkeypatch, fail={'compose:down'})
    assert receipt['passed'] is False and receipt['phases']['teardown']['ok'] is False and receipt['phases']['teardown']['exit_code'] == 1
    assert [s['ok'] for s in receipt['steps']] == [True, True, True], 'the evidence gathered before the failed cleanup stays'
    leftover, _ = run(tmp_path, monkeypatch, leftovers=True)
    assert leftover['passed'] is False and leftover['phases']['teardown']['remaining'] == ['vol-leftover']


def test_main_exits_non_zero_when_the_receipt_did_not_pass(tmp_path, monkeypatch):
    class Broken(FakeShell):
        def run(self, argv, env=None, timeout=3600, cwd=None):
            if argv[:2] == ['git', 'rev-parse']:
                return self.done(128, '', 'not a repository')
            return super().run(argv, env, timeout, cwd)
    monkeypatch.setattr(evidence, 'Shell', lambda: Broken(tmp_path))
    monkeypatch.setattr(evidence, 'ROOT', tmp_path)
    (tmp_path / 'compose.yaml').write_text('services: {}\n', encoding='utf-8')
    assert evidence.main(['--label', 'host-b', '--out', 'out']) == 1
    receipt = json.loads((tmp_path / 'out' / 'host-b-receipt.json').read_text(encoding='utf-8'))
    assert receipt['passed'] is False and receipt['phases']['preflight']['ok'] is False and 'stack_up' not in receipt['phases']
    with pytest.raises(ValueError, match='lowercase token'):
        evidence.EvidenceRun('Bad Label', 'out', shell=FakeShell(tmp_path), root=tmp_path)

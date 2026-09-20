"""The fixed monitor frontend capability (operating-portfolio-001, completion batch 2026-09-20).

Every run below is a real child process over real temporary files: the copy, the dependency
binding, the digests, the bounded capture and the cleanup are the production ones.

LABELLED FIXTURE: node and the image's frozen store are not installed on a test host, so these
tests inject a toolchain - the host Python interpreter stands in for `/usr/local/bin/node` and
three Python files stand in for the eslint/tsc/vite entrypoints under `/opt/zeus-monitor`. No npm,
node, network or Docker is involved, and an injected failure is named where it is injected. The
actual node toolchain is exercised by the owner's image build and container runs, not here.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

from codex_harness.adapters import monitor_frontend_checks as module
from codex_harness.adapters.monitor_frontend_checks import CHECK_IDS, main, observe

PY = sys.executable
PACKAGE = b'{\n  "name": "monitor",\n  "private": true\n}\n'
LOCK = b'{\n  "name": "monitor",\n  "lockfileVersion": 3\n}\n'
TOOLS = {'eslint': ('eslint', 'bin', 'eslint.js'), 'typecheck': ('typescript', 'bin', 'tsc'),
         'build': ('vite', 'bin', 'vite.js')}
BODY = """import json, os, sys
entries = []
for base, directories, names in os.walk('.'):
    if 'node_modules' in directories:
        directories.remove('node_modules')
    for name in names:
        entries.append(os.path.relpath(os.path.join(base, name), '.').replace(os.sep, '/'))
json.dump({{'argv': sys.argv, 'cwd': os.getcwd(), 'entries': sorted(entries),
            'dependency_linked': os.path.islink('node_modules/vite'),
            'build_info_writable': os.path.isdir('node_modules/.tmp'),
            'environment': dict(os.environ)}}, open({record!r}, 'w'))
sys.stdout.write('fixture {check} stdout\\n')
sys.stderr.write('fixture {check} stderr\\n')
{extra}
sys.exit({exit_code})
"""
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='the command refuses a native Windows host by contract')


@pytest.fixture
def candidate(tmp_path):
    """A candidate checkout whose monitor project also carries what must never be copied."""
    root = tmp_path / 'candidate'
    project = root / 'frontend' / 'monitor'
    (project / 'src' / 'views').mkdir(parents=True)
    (project / 'package.json').write_bytes(PACKAGE)
    (project / 'package-lock.json').write_bytes(LOCK)
    (project / 'eslint.config.js').write_text('export default []\n', encoding='utf-8')
    (project / 'src' / 'App.tsx').write_text('export const App = () => null\n', encoding='utf-8')
    (project / 'src' / 'views' / 'projects.tsx').write_text('export const P = () => null\n', encoding='utf-8')
    for excluded, name in (('node_modules', 'left-over.js'), ('dist', 'index.html'), ('.git', 'HEAD')):
        (project / excluded).mkdir()
        (project / excluded / name).write_text('never copied', encoding='utf-8')
    observatory = root.joinpath('src', 'codex_harness', 'resources', 'observatory')
    observatory.mkdir(parents=True)
    (observatory / 'index.html').write_text('<!doctype html>\n', encoding='utf-8')
    return root


@pytest.fixture
def store(tmp_path):
    """The stand-in for the image's frozen /opt/zeus-monitor store."""
    root = tmp_path / 'image-store'
    (root / 'node_modules').mkdir(parents=True)
    root.joinpath('package.json').write_bytes(PACKAGE)
    root.joinpath('package-lock.json').write_bytes(LOCK)
    return root


@pytest.fixture
def records(tmp_path):
    directory = tmp_path / 'tool-records'
    directory.mkdir()
    return directory


def install(store, records, *, exits=None, extras=None):
    """Write the injected entrypoints into the store; each records what it actually saw."""
    exits, extras = exits or {}, extras or {}
    for check, parts in TOOLS.items():
        entrypoint = store.joinpath('node_modules', *parts)
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        extra = extras.get(check, '')
        if check == 'build':
            extra = "os.makedirs(sys.argv[sys.argv.index('--outDir') + 1], exist_ok=True)\n" + extra
        entrypoint.write_text(BODY.format(record=str(records / (check + '.json')), check=check,
                                          extra=extra, exit_code=exits.get(check, 0)), encoding='utf-8')
    return store


def observed(records, check):
    return json.loads((records / (check + '.json')).read_text(encoding='utf-8'))


def test_a_complete_pass_runs_the_three_named_checks_over_a_disposable_copy(candidate, store, records):
    install(store, records)
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'ok' and report['defects'] == [], report
    assert [check['id'] for check in report['checks']] == list(CHECK_IDS)
    assert [check['status'] for check in report['checks']] == ['passed'] * 3
    assert [check['exit_code'] for check in report['checks']] == [0, 0, 0]
    assert all(check['cleanup_confirmed'] for check in report['checks'])
    assert report['packages']['match'] and len(report['packages']['candidate:package.json']) == 64
    assert report['source']['files'] == 5 and report['source']['unchanged']
    assert report['dependencies']['binding'] == 'symlink_per_entry' and report['dependencies']['entries'] == 3
    lint = observed(records, 'eslint')
    assert lint['entries'] == ['eslint.config.js', 'package-lock.json', 'package.json',
                               'src/App.tsx', 'src/views/projects.tsx'], 'node_modules, dist and .git are never copied'
    assert lint['cwd'] == str(Path(report['temporary_directory']) / 'source')
    assert lint['dependency_linked'] and lint['build_info_writable']
    assert lint['argv'][1:] == ['.'] and observed(records, 'typecheck')['argv'][1:] == ['-b']
    build = observed(records, 'build')['argv']
    assert build[1:3] == ['build', '--outDir'] and build[3].startswith(report['temporary_directory'])
    assert 'fixture eslint stdout' in report['checks'][0]['stdout']['text']
    assert report['checks'][0]['stdout']['label'] == 'monitor_frontend_checks.eslint.stdout'
    assert 'fixture eslint stderr' in report['checks'][0]['stderr']['text']
    # The disposable copy is this run's own temporary directory, and only it is removed.
    assert report['cleanup'] == {'directory': report['temporary_directory'], 'removed': True,
                                 'reason': 'owned_temporary_directory'}
    assert not Path(report['temporary_directory']).exists() and candidate.is_dir()


def test_the_candidate_and_the_packaged_observatory_are_read_not_written(candidate, store, records):
    install(store, records)
    before = {path: path.read_bytes() for path in sorted(candidate.rglob('*')) if path.is_file()}
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'ok'
    assert report['source']['sha256'] == report['source']['sha256_after_checks']
    assert report['packaged_observatory'] == {'path': 'src/codex_harness/resources/observatory',
                                              'unchanged': True}
    assert {path: path.read_bytes() for path in sorted(candidate.rglob('*')) if path.is_file()} == before
    # The build output went to the explicit temporary outDir, never to the packaged observatory.
    assert sorted(p.name for p in candidate.joinpath('src/codex_harness/resources/observatory').iterdir()) == ['index.html']


def test_an_injected_write_into_the_checkout_is_reported_as_source_mutation(candidate, store, records):
    """Injected fault: the fixture typecheck tool writes into the candidate itself."""
    target = candidate / 'frontend' / 'monitor' / 'src' / 'App.tsx'
    install(store, records, extras={'typecheck': f"open({str(target)!r}, 'a').write('mutated')\n"})
    report = observe(candidate, node=PY, dependencies=store)
    assert report['source']['unchanged'] is False
    assert 'source_mutated' in report['defects'] and report['status'] == 'failed'
    assert report['source']['sha256'] != report['source']['sha256_after_checks']


def test_a_failing_check_stops_the_run_and_later_checks_are_reported_not_run(candidate, store, records):
    """Injected fault: the fixture typecheck tool exits 2, as a real type error would."""
    install(store, records, exits={'typecheck': 2})
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'failed' and 'check_failed:typecheck' in report['defects']
    lint, typecheck, build = report['checks']
    assert lint['status'] == 'passed' and typecheck['status'] == 'failed' and typecheck['exit_code'] == 2
    assert build == {'id': 'build', 'status': 'not_run', 'reason': 'earlier_check_failed',
                     'exit_code': None, 'argv': None, 'duration_seconds': None, 'cleanup_confirmed': None}
    assert not (records / 'build.json').exists(), 'an unrun check never ran'


def test_a_missing_entrypoint_or_node_is_unavailable_and_nothing_is_invented(candidate, store, records):
    install(store, records)
    store.joinpath('node_modules', *TOOLS['build']).unlink()
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'failed' and report['defects'] == ['toolchain_unavailable:build']
    assert [check['status'] for check in report['checks']] == ['passed', 'passed', 'unavailable']
    assert report['checks'][2]['reason'] == 'entrypoint_missing'
    missing_node = observe(candidate, node=store / 'no-such-node', dependencies=store)
    assert missing_node['status'] == 'unavailable' and missing_node['refusal']['kind'] == 'node_missing'
    assert [check['status'] for check in missing_node['checks']] == ['not_run'] * 3
    absent_store = observe(candidate, node=PY, dependencies=store / 'nowhere')
    assert absent_store['refusal']['kind'] == 'dependencies_missing'


def test_a_package_or_lock_difference_refuses_before_any_check(candidate, store, records):
    install(store, records)
    candidate.joinpath('frontend', 'monitor', 'package-lock.json').write_bytes(LOCK + b'\n')
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'unavailable'
    assert report['refusal'] == {'kind': 'package_manifest_mismatch', 'detail': 'package-lock.json'}
    assert report['packages']['match'] is False
    assert report['packages']['candidate:package.json'] == report['packages']['image:package.json']
    assert report['packages']['candidate:package-lock.json'] != report['packages']['image:package-lock.json']
    assert [check['status'] for check in report['checks']] == ['not_run'] * 3
    assert 'temporary_directory' not in report and not list(records.iterdir())


def test_a_symlink_that_leaves_the_candidate_is_refused_and_a_contained_one_is_not(candidate, store, records, tmp_path):
    install(store, records)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('never read', encoding='utf-8')
    source = candidate / 'frontend' / 'monitor' / 'src'
    (source / 'escape.ts').symlink_to(outside / 'secret.txt')
    escaped = observe(candidate, node=PY, dependencies=store)
    assert escaped['status'] == 'unavailable'
    assert escaped['refusal'] == {'kind': 'source_symlink_escape', 'detail': 'src/escape.ts'}
    assert not list(records.iterdir()), 'no check runs over a source that leaves the candidate'
    (source / 'escape.ts').unlink()
    (source / 'inside.ts').symlink_to(candidate / 'frontend' / 'monitor' / 'src' / 'App.tsx')
    contained = observe(candidate, node=PY, dependencies=store)
    assert contained['status'] == 'ok' and 'src/inside.ts' in observed(records, 'eslint')['entries']


def test_missing_monitor_project_and_a_non_posix_host_are_explicit_refusals(tmp_path, store, records, monkeypatch):
    install(store, records)
    report = observe(tmp_path / 'empty-candidate', node=PY, dependencies=store)
    assert report['refusal'] == {'kind': 'monitor_project_missing', 'detail': 'frontend/monitor'}
    assert report['status'] == 'unavailable' and report['defects'] == ['monitor_project_missing']
    # Simulated host only (this suite runs on posix): the command has no native Windows fallback.
    monkeypatch.setattr(module.os, 'name', 'nt')
    windows = observe(tmp_path, node=PY, dependencies=store)
    assert windows['status'] == 'unavailable' and windows['refusal']['kind'] == 'unsupported_host'
    assert windows['defects'] == ['unsupported_host']


def test_the_command_refuses_every_argument_including_help(capsys, tmp_path, monkeypatch):
    for arguments in (['--help'], ['frontend/monitor'], [''], ['--json'], ['a', 'b']):
        assert main(arguments) == 2
        body = json.loads(capsys.readouterr().out)
        assert body['status'] == 'error' and body['error'] == {'kind': 'invalid_invocation'}
        assert body['usage'].endswith('(no arguments)')
    # The real no-argument invocation on this host: the image store is absent, so it says so.
    monkeypatch.chdir(tmp_path)
    assert main([]) == 1
    body = json.loads(capsys.readouterr().out)
    assert body['status'] == 'unavailable' and body['schema'] == 'zeus.monitor-frontend-checks/v1'
    assert body['refusal']['kind'] == 'monitor_project_missing'
    assert body['node'] == '/usr/local/bin/node' and body['dependency_root'] == '/opt/zeus-monitor'


def test_concurrent_runs_own_separate_temporary_directories(candidate, store, records):
    install(store, records)
    results, lock = [], threading.Lock()

    def run():
        report = observe(candidate, node=PY, dependencies=store)
        with lock:
            results.append(report)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert [report['status'] for report in results] == ['ok', 'ok'], results
    directories = {report['temporary_directory'] for report in results}
    assert len(directories) == 2 and all(not Path(name).exists() for name in directories)


def test_a_timeout_terminates_the_tree_and_is_never_a_pass(candidate, store, records, monkeypatch):
    """Injected fault: the fixture eslint tool sleeps past a shortened per-check deadline."""
    install(store, records, extras={'eslint': 'import time\ntime.sleep(30)\n'})
    monkeypatch.setattr(module, 'PER_CHECK_SECONDS', 1)
    report = observe(candidate, node=PY, dependencies=store)
    lint = report['checks'][0]
    assert lint['status'] == 'timeout' and 'timeout after' in lint['failure']
    assert report['status'] == 'failed' and 'check_timeout:eslint' in report['defects']
    assert [check['status'] for check in report['checks'][1:]] == ['not_run'] * 2
    assert lint['cleanup_confirmed'], 'the capture still proves what it owned'
    assert report['cleanup']['removed'] and not Path(report['temporary_directory']).exists()


def test_cleanup_debt_retains_the_temporary_directory_and_fails(candidate, store, records):
    """Injected capture record: `_capture`'s own unconfirmed-cleanup shape, not a real leak."""
    install(store, records)
    debt = {'failure': 'capture_cleanup_unconfirmed: readers still own stdout', 'terminated': False,
            'returncode': 0, 'duration_seconds': 0.1,
            'cleanup': {'reason': 'exited', 'confirmed': False, 'readers_alive': ['stdout'],
                        'streams_closed': [], 'error': None, 'tree': None}}
    report = observe(candidate, node=PY, dependencies=store, capture=lambda *args: dict(debt))
    assert report['checks'][0]['status'] == 'cleanup_debt' and report['status'] == 'failed'
    assert 'check_cleanup_debt:eslint' in report['defects']
    assert 'temporary_directory_retained' in report['defects']
    assert report['cleanup'] == {'directory': report['temporary_directory'], 'removed': False,
                                 'reason': 'capture_cleanup_unconfirmed', 'checks_with_debt': ['eslint']}
    retained = Path(report['temporary_directory'])
    assert retained.is_dir(), 'a directory whose children are unproven is retained, never removed'
    shutil.rmtree(retained)  # test hygiene: this fixture's debt was injected, not real


def test_truncated_output_is_a_defect_even_when_the_check_exited_zero(candidate, store, records, monkeypatch):
    install(store, records, extras={'eslint': "sys.stdout.write('x' * 200000)\n"})
    monkeypatch.setattr(module, 'CAPTURE_BYTES', 2048)
    report = observe(candidate, node=PY, dependencies=store)
    lint = report['checks'][0]
    assert lint['status'] == 'passed' and lint['exit_code'] == 0
    assert lint['stdout']['capture_truncated'] and lint['stdout']['bytes'] == 2048
    assert report['status'] == 'failed' and 'output_truncated:eslint.stdout' in report['defects']
    assert [check['status'] for check in report['checks'][1:]] == ['passed', 'passed'], 'truncation stops nothing'


def test_the_children_see_a_fixed_credential_free_environment(candidate, store, records, monkeypatch):
    install(store, records)
    monkeypatch.setenv('ZEUS_SECRET', 'never-inherited-canary')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'never-inherited-canary')
    report = observe(candidate, node=PY, dependencies=store)
    assert report['status'] == 'ok'
    environment = observed(records, 'eslint')['environment']
    assert 'never-inherited-canary' not in json.dumps(environment)
    assert set(environment) == {'PATH', 'HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'LANG', 'NO_COLOR', 'CI'}
    assert environment['PATH'].split(os.pathsep)[0] == str(Path(PY).parent)
    temporary = report['temporary_directory']
    assert environment['HOME'].startswith(temporary) and environment['TMPDIR'].startswith(temporary)

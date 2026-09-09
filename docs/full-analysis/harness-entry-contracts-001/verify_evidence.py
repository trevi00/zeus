"""Check immutable local receipts without importing or executing upstream code."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
ATTEMPT = OUT / 'attempts/131e2ab76766453ba8070502577c1a1a'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    receipt = read(ATTEMPT / 'receipt.json')
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    assert receipt['timed_out'] is False
    assert receipt['container_cleanup_returncode'] == 0
    assert receipt['process_tree_termination_verified'] is False
    for stream in ('stdout', 'stderr'):
        assert sha(ATTEMPT / f'{stream}.txt') == receipt[f'{stream}_sha256']
    assert receipt['stdout_sha256'] == '39b2847473923fb13e35c9ed7af1cbc0162f25067ea3eb3cac6acc1a06f0305c'
    original = read(ATTEMPT / 'source-check.json')
    assert original['source_files'] == 931 and original['source_bytes_unchanged'] is True
    assert sha(OUT / 'component_observations.py') == original['program_sha256']
    assert sha(OUT / 'run_observations.py') == original['wrapper_sha256']
    assert sha(ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py') == original['recorder_sha256']
    data = read(ATTEMPT / 'stdout.txt')
    assert data['source'] == original['revision']
    assert data['source_runtime_pin_exists'] is False
    assert data['driver_home'] != data['project']
    assert len(data['fixtures']) == 5
    for row in data['fixtures']:
        assert hashlib.sha256(row['content'].encode()).hexdigest() == row['sha256']
    checks = {row['name']: row for row in data['checks']}
    assert len(checks) == len(data['checks']) == 9
    expected = {'exit-code-failure': 'FAIL', 'metric-failed-process': 'PASS',
                'trigger-failed-process': 'PASS', 'db-failed-process': 'FAIL',
                'exit-code-success': 'PASS', 'windows-set-prefix-on-linux': 'PASS',
                'repeat-fraction': 'PASS', 'repeat-boolean': 'PASS',
                'required-across-files': 'PASS'}
    assert {key: row['verdict'] for key, row in checks.items()} == expected
    assert checks['metric-failed-process']['evidence']['exit'] == 1
    assert 'exit' not in checks['trigger-failed-process']['evidence']
    assert f"HARNESS_HOME={data['driver_home']}\n" in checks['windows-set-prefix-on-linux']['evidence']['tail']
    assert len(data['launchers']) == 3
    assert [row['returncode'] for row in data['launchers']] == [0, 0, 1]
    for row in data['launchers']:
        assert row['argv'][0] == 'sh'
        path = ROOT / '.runtime/absorption/sources/harness/pinned/scripts/handlers' / row['name']
        assert sha(path) == row['source_sha256']
    for phase in ('initial', 'discussion'):
        phase_receipt = read(OUT / f'claude-{phase}-receipt.json')
        assert phase_receipt['returncode'] == 0 and phase_receipt['is_error'] is False
        assert sha(OUT / f'claude-{phase}.json') == phase_receipt['stdout_sha256']
        assert sha(OUT / f'claude-{phase}.stderr.txt') == phase_receipt['stderr_sha256']
    print(json.dumps({'receipt_integrity': 'PASS', 'original_check_calls': 9,
                      'original_shell_launches': 3, 'fixture_command_processes': 8,
                      'actual_claude_phases': 2, 'full_acceptance': False}))


if __name__ == '__main__':
    main()

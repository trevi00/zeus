"""Validate stored observation identities; never import or rerun upstream code."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
ATTEMPT = OUT / 'attempts/3a474b8b576543168d7eb8a2d508bfb6'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    receipt = read(ATTEMPT / 'receipt.json')
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    assert receipt['timed_out'] is False and receipt['container_cleanup_returncode'] == 0
    assert receipt['process_tree_termination_verified'] is False
    for name in ('stdout', 'stderr'):
        assert sha(ATTEMPT / f'{name}.txt') == receipt[f'{name}_sha256']
    assert receipt['stdout_sha256'] == '63e56f08a7bfece302c61cb43dd00604f3dbc365e9c74db4643a593353df5c2f'
    binding = read(ATTEMPT / 'source-check.json')
    assert binding['source_files'] == 931 and binding['source_bytes_unchanged'] is True
    assert sha(OUT / 'component_observations.py') == binding['program_sha256']
    assert sha(OUT / 'run_observations.py') == binding['wrapper_sha256']
    assert sha(ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py') == binding['recorder_sha256']
    data = read(ATTEMPT / 'stdout.txt')
    assert data['source'] == binding['revision']
    source = ROOT / '.runtime/absorption/sources/harness/pinned'
    assert sha(source / 'tests/_isolate.py') == data['isolation_source_sha256']
    assert sha(source / 'scripts/engine/golden.py') == data['golden_source_sha256']
    for row in data['fixtures']:
        assert hashlib.sha256(row['content'].encode()).hexdigest() == row['sha256']
    scenarios = {row['name']: row for row in data['isolation_scenarios']}
    assert len(scenarios) == len(data['isolation_scenarios']) == 9
    assert scenarios['inherited-state']['exists'] is False
    assert scenarios['new-state']['env_equals_returned'] is True
    assert scenarios['real-state-existing']['restored'].endswith('/original-state')
    assert scenarios['real-state-absent']['value_after'].endswith('/new-inside-block')
    assert scenarios['fresh-state']['environment_unchanged'] is True
    assert scenarios['same-size-restored-time']['equal'] is True
    assert scenarios['same-probe-error']['stable_after'] is True
    assert scenarios['same-probe-error']['early_bool_rejected'] is True
    assert scenarios['body-exception']['propagated'] is True
    assert scenarios['changed-size']['stable'] is False
    assert scenarios['changed-size']['skip_output'].startswith('SKIP-AXIS:')
    cases = {row['name']: row for row in data['golden_run_observations']}
    assert len(cases) == len(data['golden_run_observations']) == 7
    assert sum(row['fixture_commands'] for row in cases.values()) == 5
    for name in ('missing-cases', 'invalid-entries', 'mapping-root'):
        assert cases[name]['result'] == {'total': 0, 'failures': []}
    for name in ('stderr-match', 'expected-failure-control'):
        assert cases[name]['result'] == {'total': 1, 'failures': []}
    assert cases['invalid-expect-exit']['error_type'] == 'ValueError'
    assert cases['invalid-expect-exit']['fixture_commands'] == 1
    assert cases['duplicate-name']['result'] == {'total': 2, 'failures': []}
    assert data['original_golden_cases_executed'] == 0
    assert data['gatewriter_executed'] is False and data['source_suite_executed'] is False
    for phase in ('initial', 'discussion'):
        phase_receipt = read(OUT / f'claude-{phase}-receipt.json')
        assert phase_receipt['returncode'] == 0 and phase_receipt['is_error'] is False
        for name in ('stdout', 'stderr'):
            path = OUT / (f'claude-{phase}.json' if name == 'stdout' else f'claude-{phase}.stderr.txt')
            assert sha(path) == phase_receipt[f'{name}_sha256']
    print(json.dumps({'receipt_integrity': 'PASS', 'isolation_scenarios': 9,
                      'golden_run_invocations': 7, 'real_fixture_commands': 5,
                      'actual_claude_phases': 2, 'full_acceptance': False}))


if __name__ == '__main__':
    main()

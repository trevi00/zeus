"""Verify saved identities and bounded observations without rerunning upstream code."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    attempt = OUT / 'attempts/4a7d0546b30a453ba35fff813457c888'
    receipt = read(attempt / 'receipt.json')
    assert receipt['returncode'] == 0 and receipt['status'] == 'completed'
    assert receipt['container_cleanup_returncode'] == 0
    for stream in ('stdout', 'stderr'):
        assert sha(attempt / f'{stream}.txt') == receipt[f'{stream}_sha256']
    identity = read(attempt / 'source-check.json')
    assert identity['source_bytes_unchanged'] and identity['source_files'] == 1648
    assert sha(OUT / 'component_observations.py') == identity['program_sha256']
    assert sha(OUT / 'run_observations.py') == identity['wrapper_sha256']
    assert sha(ROOT / 'docs/full-analysis/baldrix-test-runners-001/run_observations_v2.py') == identity['recorder_sha256']
    result = read(attempt / 'stdout.txt')
    source = ROOT / '.runtime/absorption/sources/baldrix/pinned/get-shit-done/references/verification-patterns.md'
    assert sha(source) == result['source_sha256']
    snippet = b''.join(source.read_bytes().splitlines(keepends=True)[524:552])
    assert hashlib.sha256(snippet).hexdigest() == result['snippet_sha256']
    rows = {r['name']: r for r in result['observations']}
    assert len(rows) == result['original_reference_bash_calls'] == 7
    assert rows['missing_exists']['returncode'] == 0 and rows['missing_exists']['stdout'].startswith('MISSING:')
    assert rows['comment_wiring']['stdout'].startswith('WIRED:')
    assert rows['missing_wiring']['returncode'] == 0 and rows['missing_wiring']['stderr']
    assert rows['no_stub_matches']['returncode'] == 2 and 'integer expression expected' in rows['no_stub_matches']['stderr']
    assert rows['stub_control']['stdout'].startswith('STUB_PATTERNS: 1')
    assert rows['no_substance_pattern']['returncode'] == 0 and 'integer expression expected' in rows['no_substance_pattern']['stderr']
    assert rows['comment_substance']['stdout'].startswith('SUBSTANTIVE:')
    for phase in ('initial', 'discussion'):
        value = read(OUT / f'claude-{phase}-receipt.json')
        assert value['returncode'] == 0 and value['is_error'] is False
        assert sha(OUT / f'claude-{phase}.json') == value['stdout_sha256']
        assert sha(OUT / f'claude-{phase}.stderr.txt') == value['stderr_sha256']
    print(json.dumps({'receipt_integrity': 'PASS', 'original_reference_bash_calls': 7,
                      'actual_claude_phases': 2, 'full_acceptance': False}))


if __name__ == '__main__':
    main()

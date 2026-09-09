"""Verify this bounded review's source and actual process evidence; no acceptance claim."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    scope = read(OUT / 'scope.json')
    assert len(scope['paths']) == 9
    assert sum(row['bytes'] for row in scope['paths']) == 46688
    assert sha(json.dumps(scope['paths'], sort_keys=True).encode()) == scope['scope_sha256']
    prior = read(OUT / 'prior-unreviewed.json')
    assert {r['path'] for r in prior} == {r['path'] for r in scope['paths']}
    assert all(r['disposition'] == 'unreviewed' for r in prior)
    files = read(OUT / 'files.json')
    assert {r['path'] for r in files} == {r['path'] for r in scope['paths']}
    for row in files + read(OUT / 'support-files.json'):
        raw = (SOURCE / row['path']).read_bytes()
        assert len(raw) == row['bytes']
        assert sha(raw) == row['pinned_sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
        lines = raw.splitlines(keepends=True)
        for span in row['read_ranges']:
            assert 1 <= span['start_line'] <= span['end_line'] <= len(lines)
            assert sha(b''.join(lines[span['start_line'] - 1:span['end_line']])) == span['raw_range_sha256']
        assert (ROOT / row['review_ref']).is_file()
    attempt = OUT / 'attempts/e9c164a6ef4742fbb443d54e2d36389e'
    receipt = read(attempt / 'receipt.json')
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    assert receipt['container_cleanup_returncode'] == 0
    assert sha((attempt / 'stdout.txt').read_bytes()) == receipt['stdout_sha256']
    assert sha((attempt / 'stderr.txt').read_bytes()) == receipt['stderr_sha256']
    source_check = read(attempt / 'source-check.json')
    assert source_check['source_bytes_unchanged'] and source_check['source_files'] == 1648
    assert source_check['program_sha256'] == sha((OUT / 'component_observations.py').read_bytes())
    assert source_check['wrapper_sha256'] == sha((OUT / 'run_observations.py').read_bytes())
    data = read(attempt / 'stdout.txt')
    assert data['source_sha256'] == sha((SOURCE / 'tools/check-flyway-collision.sh').read_bytes())
    assert data['flyway_available'] is None
    expected = {'ordinary-distinct': 0, 'ordinary-duplicate': 1, 'dotted-distinct': 1,
                'underscore-distinct': 1, 'zero-padding': 0, 'octal-eight': 0,
                'nondigit-version': 0, 'empty': 0, 'missing': 1, 'unreadable': 0,
                'multi-module-vendor': 0, 'parity-gap-control': 0}
    assert len(data['cases']) == 12
    assert {c['name']: c['returncode'] for c in data['cases']} == expected
    for case in data['cases']:
        for channel in ('stdout', 'stderr'):
            assert sha(case[channel].encode('utf-8')) == case[channel + '_sha256']
        for fixture in case['fixtures']:
            assert sha(fixture['content'].encode()) == fixture['sha256']
    cases = {c['name']: c for c in data['cases']}
    assert 'value too great for base' in cases['octal-eight']['stderr']
    assert 'parity OK' in cases['multi-module-vendor']['stdout']
    for phase in ('initial', 'discussion'):
        receipt_path = OUT / f'claude-{phase}-receipt.json'
        if not receipt_path.exists():
            raise AssertionError(f'Actual Claude {phase} evidence is still missing')
        claude = read(receipt_path)
        assert claude['returncode'] == 0 and claude['is_error'] is False
        assert sha((OUT / f'claude-{phase}.json').read_bytes()) == claude['stdout_sha256']
        assert sha((OUT / f'claude-{phase}.stderr.txt').read_bytes()) == claude['stderr_sha256']
    print(json.dumps({'status': 'verified', 'primary_files': 9, 'primary_bytes': 46688,
                      'original_bash_invocations': 12, 'actual_claude_phases': 2,
                      'adoption_approved': False, 'repository_complete': False}))


if __name__ == '__main__':
    main()

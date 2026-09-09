"""Verify owned static-review artifacts without upstream imports or execution."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
BASE = 'docs/full-analysis/baldrix-kha-entrypoints-001/'
OUT = ROOT / BASE
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_bytes())


def check_ref(ref):
    path, _, anchor = ref.partition('#')
    content = (ROOT / path).read_text(encoding='utf-8')
    if anchor:
        assert f'id="{anchor}"' in content or re.search(r'^#+ ' + re.escape(anchor) + r'\s*$', content, re.M), ref


def check_prior(record):
    assert sha((ROOT / record['ledger_ref']).read_bytes()) == record['ledger_sha256']
    assert record['original_row'] in read(record['ledger_ref'])
    check_ref(record['review_ref'])
    assert sha((ROOT / record['review_ref'].split('#')[0]).read_bytes()) == record['review_sha256']
    for receipt in record['original_receipt_refs']:
        assert sha((ROOT / receipt['ref']).read_bytes()) == receipt['sha256']


scope = read(BASE + 'scope.json')
files = read(BASE + 'files.json')
manifest = read('.runtime/absorption/sources/baldrix/manifest.json')
expected = sorted(row['path'] for row in manifest['inventory'] if row['path'].startswith('skills/kha-')
                  and 'kha-add-phase' <= row['path'].split('/')[1] <= 'kha-new-workspace')
assert scope['paths'] == expected == [row['path'] for row in files]
assert len(files) == 33 and sum(row['pinned_bytes'] for row in files) == 118053
assert sum(row['prior_full_body_reused'] for row in files) == 26
assert all(row['prior_path_ledger_row']['disposition'] == 'unreviewed' for row in files)
notes = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
anchors = re.findall(r'<a id="(file-\d+)"></a>', notes)
assert anchors == [f'file-{index:02}' for index in range(1, 34)]
for row in files + read(BASE + 'supporting-evidence.json'):
    raw = (PIN / row['path']).read_bytes()
    assert sha(raw) == row['pinned_sha256'] and len(raw) == row['pinned_bytes']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
    lines = raw.splitlines(keepends=True)
    for receipt in row['range_receipts']:
        assert sha(b''.join(lines[receipt['start'] - 1:receipt['end']])) == receipt['raw_range_sha256']
    check_ref(row['review_ref'])
    if row.get('prior_reuse'):
        check_prior(row['prior_reuse'])
        assert row['prior_reuse']['read_ranges'] == [[1, len(lines)]]
for record in read(BASE + 'supporting-reuse.json'):
    check_prior(record)
for path in OUT.iterdir():
    if not path.is_file():
        continue
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    assert not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw, path
    assert raw.endswith(b'\n') and not raw.endswith(b'\n\n'), path
    assert '\ufffd' not in text and chr(63) * 3 not in text, path
    assert all(line == line.rstrip() for line in text.splitlines()), path
    result = subprocess.run(['git', 'diff', '--no-index', '--check', '--', '/dev/null', str(path)],
                            cwd=ROOT, capture_output=True)
    assert result.returncode in (0, 1) and not result.stdout and not result.stderr, (path, result.stdout, result.stderr)
result = subprocess.run([str(ROOT / '.venv/Scripts/ruff.exe'), 'check', '--no-cache', str(OUT)],
                        cwd=ROOT, capture_output=True)
assert result.returncode == 0, result.stdout.decode('utf-8') + result.stderr.decode('utf-8')
receipt = {'status': 'PASS', 'scope': 'Owned metadata only; no source behavioral verification',
           'primary': 33, 'fresh_full_primary': 7, 'prior_full_body_reused': 26,
           'checks': ['scope equals pinned manifest directory range', 'prior unreviewed rows retained',
                      'raw blob/bytes/SHA and actual range SHA', 'existing exact prior rows/review/receipt hashes',
                      '33 ordered unique anchors', 'UTF8/LF/one final LF/no trailing whitespace',
                      'git diff --no-index --check for every owned file', 'Ruff owned scripts'],
           'ruff_stdout': result.stdout.decode('utf-8'), 'ruff_stderr': result.stderr.decode('utf-8'),
           'source_execution_count': 0}
(OUT / 'validation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
hashes = {path.name: sha(path.read_bytes()) for path in sorted(OUT.iterdir()) if path.is_file()
          and path.name != 'artifact-hashes.json'}
(OUT / 'artifact-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(receipt, ensure_ascii=False))
print(json.dumps({name: hashes[name] for name in ['files.json', 'checkpoint.json', 'review.md', 'file-reviews.md']}, indent=2))

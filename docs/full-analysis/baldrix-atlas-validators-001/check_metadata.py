"""Validate owned review metadata only; no upstream execution."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
BASE = 'docs/full-analysis/baldrix-atlas-validators-001/'
OUT = ROOT / BASE
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_bytes())


def check_identity(row):
    raw = (PIN / row['path']).read_bytes()
    assert sha(raw) == row['pinned_sha256'] and len(raw) == row['pinned_bytes']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
    lines = raw.splitlines(keepends=True)
    for receipt in row['range_receipts']:
        assert 1 <= receipt['start'] <= receipt['end'] <= len(lines)
        assert sha(b''.join(lines[receipt['start'] - 1:receipt['end']])) == receipt['raw_range_sha256']


scope = read(BASE + 'scope.json')
files = read(BASE + 'files.json')
assert len(files) == 38 and sum(row['pinned_bytes'] for row in files) == 84994
assert [row['path'] for row in files] == scope['paths']
assert [row['scope_sha256'] for row in scope['partitions']] == [
    'f56f88ea1a14cf89218198da0197682a1026a1c9808d7319f0405460faddcf80',
    '4a70925fef0e204941882f620210fc349e2235d4327c5b961b2dc4845270e7cd']
notes = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
assert re.findall(r'<a id="(file-\d+)"></a>', notes) == [f'file-{index:02}' for index in range(1, 39)]
for row in files + read(BASE + 'supporting-evidence.json'):
    check_identity(row)
    path, anchor = row['review_ref'].split('#')
    assert f'id="{anchor}"' in (ROOT / path).read_text(encoding='utf-8')
for row in files:
    assert row['read_ranges'] == [[1, row['line_count']]]
    assert row['prior_path_ledger_row']['disposition'] == 'unreviewed'
    assert not row['prior_full_body_reused'] and not row['source_executed']
for record in read(BASE + 'supporting-reuse.json'):
    check_identity(record['identity'])
    assert sha((ROOT / record['ledger_ref']).read_bytes()) == record['ledger_sha256']
    assert record['original_row'] in read(record['ledger_ref'])
    assert sha((ROOT / record['review_document_ref']).read_bytes()) == record['review_document_sha256']
    document = read(record['review_document_ref'])
    assert record['review_selector'] in document, record['review_selector']
    assert record['read_ranges'] == [[1, record['identity']['line_count']]]
    for receipt in record['original_receipt_refs']:
        assert sha((ROOT / receipt['ref']).read_bytes()) == receipt['sha256']
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
receipt = {'status': 'PASS', 'scope': 'Owned static review metadata, not original behavior',
           'primary_fresh_full': 38, 'primary_bytes': 84994, 'prior_support_full_reuse': 29,
           'checks': ['fixed partition scopes/prior unreviewed rows', 'raw bytes/Git blob/SHA/ranges',
                      'exact prior rows/review JSON selectors/receipt hashes', '38 unique ordered anchors',
                      'UTF8/LF/one final LF/trailing whitespace', 'git diff --no-index --check', 'Ruff owned scripts'],
           'ruff_stdout': result.stdout.decode('utf-8'), 'ruff_stderr': result.stderr.decode('utf-8'),
           'source_execution_count': 0}
(OUT / 'validation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
hashes = {path.name: sha(path.read_bytes()) for path in sorted(OUT.iterdir()) if path.is_file()
          and path.name != 'artifact-hashes.json'}
(OUT / 'artifact-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(receipt, ensure_ascii=False))
print(json.dumps({name: hashes[name] for name in ['files.json', 'checkpoint.json', 'review.md', 'file-reviews.md']}, indent=2))

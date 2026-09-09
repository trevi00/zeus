"""Check only this static review's metadata; never import reviewed source."""

import hashlib
import json
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-tests-009'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


files = load('files.json')
support = load('supporting-evidence.json')
checkpoint = load('checkpoint.json')
assert len(files) == 32 and len(support) == 36
assert sum(row['pinned_bytes'] for row in files) == 197463
assert checkpoint['primary_unread'] == []
assert checkpoint['source_executions'] == 0
assert not checkpoint['partition_complete'] and not checkpoint['adoption_ready']
for row in files + support:
    raw = (PIN / row['path']).read_bytes()
    assert digest(raw) == row['pinned_sha256']
    assert len(raw) == row['pinned_bytes']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == row['git_blob']
    lines = raw.splitlines(keepends=True)
    for extent in row['read_ranges']:
        start, end = (extent['start'], extent['end']) if isinstance(extent, dict) else extent
        assert 1 <= start <= end <= len(lines)
        if isinstance(extent, dict):
            assert digest(b''.join(lines[start - 1:end])) == extent['raw_range_sha256']
    target, _, anchor = row['review_ref'].partition('#')
    text = (ROOT / target).read_text(encoding='utf-8')
    assert not anchor or f'<a id="{anchor}"></a>' in text
    assert row['tests_executed'] == []
for path in OUT.iterdir():
    if path.suffix in {'.md', '.py', '.json', '.txt'}:
        text = path.read_text(encoding='utf-8')
        assert '\ufffd' not in text, path.name
        if path.suffix in {'.md', '.json'}:
            assert chr(63) * 3 not in text, path.name
        if path.suffix == '.py':
            assert b'\r' not in path.read_bytes(), path.name
result = dict(primary=32, primary_bytes=197463, supporting=36,
              primary_hash_blob_bytes=True, supporting_hash_blob_bytes_ranges=True,
              references=True, utf8_and_literal_loss_scan=True,
              python_lf=True, source_execution=0, upstream_tests_executed=0,
              whole_closure=False, adoption=False,
              note='Mechanical metadata checks only; Korean prose separately read back.')
(OUT / 'metadata-check.json').write_text(json.dumps(result, indent=2) + '\n',
                                        encoding='utf-8', newline='\n')
index = {path.name: digest(path.read_bytes()) for path in sorted(OUT.iterdir())
         if path.is_file() and path.name != 'artifact-hashes.json'}
(OUT / 'artifact-hashes.json').write_text(json.dumps(index, indent=2) + '\n',
                                         encoding='utf-8', newline='\n')
assert all(digest((OUT / name).read_bytes()) == value for name, value in index.items())
print(json.dumps(dict(result, indexed_artifacts=len(index), index_verified=True)))

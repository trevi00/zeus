"""Inert scope snapshot and byte-bound prior review inventory."""
import hashlib
import json
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-kha-entrypoints-001'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


if not (OUT / 'scope.json').exists():
    ledger = ROOT / 'docs/full-analysis/path-ledger.json'
    rows = [row for row in json.loads(ledger.read_bytes()) if row['source'] == 'baldrix'
            and row['path'].startswith('skills/kha-')
            and 'kha-add-phase' <= row['path'].split('/')[1] <= 'kha-new-workspace']
    rows.sort(key=lambda row: row['path'])
    dump('prior-path-ledger.json', rows)
    dump('scope.json', {'ledger_sha256': sha(ledger.read_bytes()), 'rows': len(rows),
                       'paths': [row['path'] for row in rows],
                       'bytes': sum(row['bytes'] for row in rows),
                       'scope_sha256': sha('\n'.join(row['path'] for row in rows).encode()),
                       'scope_algorithm': 'SHA256 of sorted path strings joined by LF, no final LF',
                       'manifest_sha256': sha((ROOT / '.runtime/absorption/sources/baldrix/manifest.json').read_bytes()),
                       'partitions_sha256': sha((ROOT / 'docs/full-analysis/partitions.json').read_bytes())})
scope = json.loads((OUT / 'scope.json').read_bytes())
reuse = {}
for folder, name in [('baldrix-gsd-workflows-001', 'supporting.json'),
                     ('baldrix-gsd-workflows-002', 'supporting.json'),
                     ('baldrix-gsd-workflows-003', 'supporting-evidence.json')]:
    ledger = ROOT / 'docs/full-analysis' / folder / name
    for row in json.loads(ledger.read_bytes()):
        path = row['path']
        if path not in scope['paths']:
            continue
        if not (row.get('body_read_complete') or row.get('read_extent') == 'full'):
            continue
        assert sha((PIN / path).read_bytes()) == row['pinned_sha256']
        review = ROOT / row['review_ref'].split('#')[0]
        reuse[path] = {'ledger_ref': ledger.relative_to(ROOT).as_posix(),
                       'ledger_sha256': sha(ledger.read_bytes()), 'original_row': row,
                       'review_ref': row['review_ref'], 'review_sha256': sha(review.read_bytes())}
dump('reuse-candidates.json', reuse)
print(json.dumps({'scope': scope, 'reuse_candidates': len(reuse),
                  'fresh_required': [path for path in scope['paths'] if path not in reuse]}, indent=2))

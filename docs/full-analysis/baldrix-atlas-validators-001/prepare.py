"""Inert fixed scope snapshot and numbered source reader."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-atlas-validators-001'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


if not (OUT / 'scope.json').exists():
    partitions = ROOT / 'docs/full-analysis/partitions.json'
    selected = [row for row in json.loads(partitions.read_bytes()) if row['partition'] in
                ['baldrix:atlas/validators:001', 'baldrix:atlas/validators:002']]
    paths = [item['path'] for row in selected for item in row['paths']]
    ledger = ROOT / 'docs/full-analysis/path-ledger.json'
    old = json.loads(ledger.read_bytes())
    rows = [next(row for row in old if row['source'] == 'baldrix' and row['path'] == path) for path in paths]
    dump('prior-path-ledger.json', rows)
    dump('scope.json', {'partitions': selected, 'paths': paths, 'primary_count': len(paths),
                       'primary_bytes': sum(row['bytes'] for row in rows),
                       'ledger_sha256': sha(ledger.read_bytes()), 'partitions_sha256': sha(partitions.read_bytes()),
                       'manifest_sha256': sha((ROOT / '.runtime/absorption/sources/baldrix/manifest.json').read_bytes()),
                       'starting_head': '7eaa42737d0cce4e675c9f309c215ce1e1d97ed4'})
scope = json.loads((OUT / 'scope.json').read_bytes())
if len(sys.argv) == 3:
    for index in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
        path = scope['paths'][index - 1]
        print(f'FILE {index:02} {path}')
        for number, line in enumerate((PIN / path).read_text(encoding='utf-8').splitlines(), 1):
            print(f'{number}: {line}')
else:
    print(json.dumps({'count': scope['primary_count'], 'bytes': scope['primary_bytes'],
                      'prior_states': [row['disposition'] for row in json.loads((OUT / 'prior-path-ledger.json').read_bytes())]}, indent=2))

"""Inert bounded source printer and identity snapshot; never imports source."""

import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-references-001'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
partition = next(item for item in json.loads(
    (ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8')
) if item['partition'] == 'baldrix:get-shit-done/references:001')
assert partition['scope_sha256'] == '9d4101a80187e82f3fe8beccb5294e3825496e7baffb489e2b398c0c17c3ff77'
if sys.argv[1] == 'snapshot':
    raw = (ROOT / 'docs/full-analysis/path-ledger.json').read_bytes()
    ledger = json.loads(raw)
    rows = []
    for item in partition['paths']:
        row = next(row for row in ledger if row['source'] == 'baldrix' and row['path'] == item['path'])
        assert row['disposition'] == 'unreviewed'
        rows.append(dict(prior_ledger_row=row, prior_ledger_sha256=hashlib.sha256(raw).hexdigest(),
                         reused_for_read=False))
    target = OUT / 'prior-path-ledger.json'
    assert not target.exists()
    target.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8', newline='\n')
    for index, item in enumerate(partition['paths'], 1):
        raw = (PIN / item['path']).read_bytes()
        print(index, len(raw), len(raw.splitlines()), item['path'])
else:
    for index in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
        path = partition['paths'][index - 1]['path']
        print(f'FILE {index} {path}')
        for number, line in enumerate((PIN / path).read_text(encoding='utf-8').splitlines(), 1):
            print(f'{number}: {line}')

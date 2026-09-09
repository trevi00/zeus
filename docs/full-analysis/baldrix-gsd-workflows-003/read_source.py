"""Inert source printer and prior-row snapshot; no source import or execution."""

import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-workflows-003'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
partition = next(row for row in json.loads(
    (ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8')
) if row['partition'] == 'baldrix:get-shit-done/workflows:003')
assert partition['scope_sha256'] == '4bb1361ed48b4e09ccea7f76f397e57cc5b5d0fe2982c06d0fa1b9e7c2bfb432'
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
    index, start, end = map(int, sys.argv[1:4])
    path = partition['paths'][index - 1]['path']
    lines = (PIN / path).read_text(encoding='utf-8').splitlines()
    assert 1 <= start <= end <= len(lines)
    print(path)
    print('\n'.join(f'{number}: {lines[number - 1]}' for number in range(start, end + 1)))

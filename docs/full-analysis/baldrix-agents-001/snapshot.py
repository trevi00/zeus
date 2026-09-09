"""Inert bounded identity snapshot; never executes source."""

import hashlib
import json
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-agents-001'
parts = json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8'))
part = next(p for p in parts if p['partition'] == 'baldrix:agents:001')
assert part['scope_sha256'] == '503f4263bc75a8ef3ca663ecdc6db8142b9f52d5d1ee6d65a2b9fc9bff622101'
raw = (ROOT / 'docs/full-analysis/path-ledger.json').read_bytes()
ledger = json.loads(raw)
assert isinstance(ledger, list)
rows = []
for item in part['paths']:
    row = next(r for r in ledger if r['source'] == 'baldrix' and r['path'] == item['path'])
    assert row['disposition'] == 'unreviewed'
    rows.append(dict(prior_ledger_row=row, prior_ledger_sha256=hashlib.sha256(raw).hexdigest(),
                     reused_for_read=False))
target = OUT / 'prior-path-ledger.json'
assert not target.exists()
target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(primary=len(rows), bytes=sum(r['prior_ledger_row']['bytes'] for r in rows))))

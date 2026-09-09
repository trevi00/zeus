"""Normalize owned review EOF only; preserve substantive bytes."""

import hashlib
import json
from pathlib import Path

OUT = Path('C:/Users/rudtn/zeus/docs/full-analysis/baldrix-agents-001')
path = OUT / 'file-reviews.md'
before = path.read_bytes()
after = before.rstrip(b'\r\n') + b'\n'
assert before.rstrip(b'\r\n') == after.rstrip(b'\r\n')
path.write_bytes(after)
receipt = {
    'operation': 'Formatting only: exactly one final LF; substantive bytes unchanged',
    'before_sha256': hashlib.sha256(before).hexdigest(),
    'after_sha256': hashlib.sha256(after).hexdigest(),
    'before_bytes': len(before),
    'after_bytes': len(after),
    'new_semantic_reads': 0,
    'upstream_execution': 0,
    'validation_argv': [
        ['python', 'docs/full-analysis/baldrix-agents-001/record_review.py'],
        ['python', 'docs/full-analysis/baldrix-agents-001/check_metadata.py'],
        ['.venv/Scripts/ruff.exe', 'check', 'docs/full-analysis/baldrix-agents-001'],
    ],
}
(OUT / 'eof-normalization-receipt.json').write_text(
    json.dumps(receipt, indent=2) + '\n', encoding='utf-8', newline='\n'
)
print(json.dumps(receipt))

"""Prepare owned inert recorders from prior formatting machinery, not source review."""

import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus/docs/full-analysis')
OUT = ROOT / 'baldrix-gsd-bin-001'
for name in ['record_review.py', 'check_metadata.py', 'order_notes.py']:
    content = (ROOT / 'baldrix-gsd-references-001' / name).read_text(encoding='utf-8')
    for before, after in [
        ('baldrix-gsd-references-001', 'baldrix-gsd-bin-001'),
        ('baldrix:get-shit-done/references:001', 'baldrix:get-shit-done/bin:001'),
        ('9d4101a80187e82f3fe8beccb5294e3825496e7baffb489e2b398c0c17c3ff77',
         'cafde003ad2a4ac33ded41bf2d4ffca61edd436ee59f33143706c491ed5b8851'),
        ('178518', '198986'), ('reads32', 'reads7'), ('Ordered32', 'Ordered7'),
        ('Reference include and direct CLI/config differences recorded at review_ref and support; no invocation.',
         'CLI routes, direct primary dependencies and bounded supports recorded; no invocation.'),
    ]:
        content = content.replace(before, after)
    content = re.sub(r'\b32\b', '7', content)
    content = re.sub(r'\b20\b', '6', content)
    (OUT / name).write_text(content.rstrip() + '\n', encoding='utf-8', newline='\n')
print('Prepared own recorders; no reviewed code execution.')

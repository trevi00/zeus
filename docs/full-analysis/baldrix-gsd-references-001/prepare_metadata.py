"""Prepare owned inert metadata helpers; no reviewed source execution."""

import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus/docs/full-analysis')
OUT = ROOT / 'baldrix-gsd-references-001'
for name in ['record_review.py', 'check_metadata.py', 'order_notes.py']:
    text = (ROOT / 'baldrix-agents-001' / name).read_text(encoding='utf-8')
    text = re.sub(r'\b22\b', '32', text)
    text = re.sub(r'\b29\b', '20', text)
    for old, new in [
        ('baldrix-agents-001', 'baldrix-gsd-references-001'),
        ('baldrix:agents:001', 'baldrix:get-shit-done/references:001'),
        ('503f4263bc75a8ef3ca663ecdc6db8142b9f52d5d1ee6d65a2b9fc9bff622101',
         '9d4101a80187e82f3fe8beccb5294e3825496e7baffb489e2b398c0c17c3ff77'),
        ('73f2c8848c0002df8dac3cc00f59566abfaa4134',
         '5acaeced22de71ae3eb8584643e00557762745c0'),
        ('198416', '178518'), ('reads22', 'reads32'), ('Ordered22', 'Ordered32'),
        ('Agent/Task named roles versus generic prompts and actual caller differences documented; no invocation.',
         'Reference include and direct CLI/config differences recorded at review_ref and support; no invocation.'),
    ]:
        text = text.replace(old, new)
    if name == 'order_notes.py':
        text = text.replace("prefix + ''.join(blocks)", "(prefix + ''.join(blocks)).rstrip() + '\\n'")
    if name == 'check_metadata.py':
        text = text.replace("assert '\\ufffd' not in text, path.name", "assert '\\ufffd' not in text, path.name\n        raw = path.read_bytes()\n        assert raw.endswith(b'\\n') and not raw.endswith(b'\\n\\n'), path.name\n        assert all(line == line.rstrip() for line in text.splitlines()), path.name")
    (OUT / name).write_text(text.rstrip() + '\n', encoding='utf-8', newline='\n')
print('Prepared three inert metadata helpers.')

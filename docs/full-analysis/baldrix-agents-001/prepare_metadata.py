"""Adapt inert metadata templates only; no reviewed source execution."""

from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus/docs/full-analysis')
OUT = ROOT / 'baldrix-agents-001'
for name in ['record_review.py', 'check_metadata.py', 'order_notes.py']:
    text = (ROOT / 'baldrix-tests-012' / name).read_text(encoding='utf-8')
    for old, new in [
        ('baldrix-tests-012', 'baldrix-agents-001'),
        ('baldrix:scripts/tests:012', 'baldrix:agents:001'),
        ('519dfd3735c6c09f2b763956a3d070cd2303feb02cb817a0fdf4748167ba6ce1',
         '503f4263bc75a8ef3ca663ecdc6db8142b9f52d5d1ee6d65a2b9fc9bff622101'),
        ('852564f34e738997c19cf4af917450572d029e6c',
         '73f2c8848c0002df8dac3cc00f59566abfaa4134'),
        ('193879', '198416'), ('24', '22'), ('38', '29'),
        ('direct SUT follow-up', 'direct caller/config/test follow-up'),
        ('Test main/pytest collection and direct SUT/caller differences documented; no actual invocation.',
         'Agent/Task named roles versus generic prompts and actual caller differences documented; no invocation.'),
        ('tests_read_not_run=[dict(path=path, read_extent=\'full\', role=\'primary static test oracle\')]',
         'tests_read_not_run=[item[\'path\'] for item in support if path in item[\'supports_primary\'] and \'/tests/\' in item[\'path\']]'),
        ('ranges == [(1, len(lines))]', 'ranges == [[1, len(lines)]]'),
    ]:
        text = text.replace(old, new)
    (OUT / name).write_text(text, encoding='utf-8', newline='\n')
print('Prepared three inert metadata helpers.')

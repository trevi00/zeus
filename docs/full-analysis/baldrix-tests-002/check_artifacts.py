"""Verify only this review's metadata and text, and record artifact hashes."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-tests-002'
START = datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


files = json.loads((OUT / 'files.json').read_text(encoding='utf-8'))
support = json.loads((OUT / 'supporting-evidence.json').read_text(encoding='utf-8'))
checkpoint = json.loads((OUT / 'checkpoint.json').read_text(encoding='utf-8'))
assert len(files) == 16 and len(support) == 36
assert sum(row['pinned_bytes'] for row in files) == 188337
assert checkpoint['source_executions'] == 0 and checkpoint['primary_unread'] == []
assert checkpoint['per_file_review_sha256'] == sha((OUT / 'file-reviews.md').read_bytes())
for row in files + support:
    ref = row['review_ref']
    path, _, anchor = ref.partition('#')
    target = ROOT / path
    assert target.is_file(), ref
    if anchor:
        assert f'<a id="{anchor}"></a>' in target.read_text(encoding='utf-8'), ref
    assert row['tests_executed'] == []

for path in OUT.iterdir():
    if not path.is_file():
        continue
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    assert '\ufffd' not in text, path.name
    if path.suffix in ('.md', '.json', '.txt'):
        assert '?' * 3 not in text, path.name
    if path.suffix == '.py':
        assert b'\r' not in raw, path.name

receipt = dict(
    kind='Own documentation metadata validation, not upstream tests',
    started_utc=START, ended_utc=datetime.now(timezone.utc).isoformat(),
    argv=['python', 'docs/full-analysis/baldrix-tests-002/check_artifacts.py'],
    workdir=str(ROOT), source_executions=0, source_imports=0, source_network=0,
    source_probes=0, source_installations=0, live_state_access=0,
    recorder_sha256=sha((OUT / 'record_review.py').read_bytes()),
    checker_sha256=sha((OUT / 'check_artifacts.py').read_bytes()),
    recorder_receipt=dict(argv=['python', 'docs/full-analysis/baldrix-tests-002/record_review.py'],
                          tool_chunk='501d48', exit_code=0,
                          stdout='{"primary": 16, "bytes": 188337, "fresh": 16, "reused": 0, "supporting": 36, "source_executions": 0, "manifest_blob_bytes_all_match": true}\r\n',
                          stderr=''),
    recorder_ruff_receipt=dict(argv=['.venv/Scripts/ruff.exe', 'check',
                                    'docs/full-analysis/baldrix-tests-002/record_review.py'],
                               tool_chunk='73510b', exit_code=0,
                               stdout='All checks passed!\n', stderr=''),
    read_history=dict(
        primary_full_read_chunks=['d87ef5', '3267b1', 'ce5ffe', '6757d4',
                                  '28a013', '6eaa2f', '55d752', '7e0091', '14c632',
                                  '9898ee', 'f216cd', 'b29c7c', '657187', 'befe03',
                                  '016c45', 'ece74e'],
        supporting_read_chunks=['f16fa9', 'd77278', '1f4786', '0af07a', 'a4ebb6',
                                'c7bb38', 'e4f9e6', 'e3f2a8', '368b0c', '5dd9f9',
                                '4150d9', '8be924', '7d9903', '1daccd', '169716',
                                '552970', '09a2cc'],
        preserved_failures=[
            dict(tool_chunk='6f7e8e', exit_code=1, kind='inert reader stdout encoding',
                 detail='cp949 UnicodeEncodeError on em dash after line1; no source executed. Re-read full body with stdout UTF-8 in55d752.'),
            dict(tool_chunk='11de29', kind='exact-path lookup failed',
                 detail='commands/autopilot.md absent; rg reported OS error2 three times. Actual commands/harness-autopilot.md subsequently located and scoped-read. Final shell rc0 from final independent inventory search is not lookup success.'),
        ],
        timestamp_limit='Individual source read start/end timestamps not captured; tool chunk IDs preserve sequence. No invented timings.',
    ),
    validation=dict(primary=16, supporting=36, byte_sum=188337,
                    manifest_git_blob_bytes=True, references=True, utf8=True, python_lf=True,
                    primary_execution_count=0, shared_coverage_modified=False),
    unresolved=['transitive closure', 'whole-area Claude', 'license/vendor original',
                'native OS/model execution', 'Zeus adoption and human acceptance'],
)
dump('metadata-check-receipt.json', receipt)
index = {path.name: dict(sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
         for path in sorted(OUT.iterdir()) if path.is_file() and path.name != 'artifact-hashes.json'}
dump('artifact-hashes.json', index)
for name, expected in index.items():
    assert sha((OUT / name).read_bytes()) == expected['sha256']
print(json.dumps(dict(primary=16, supporting=36, artifact_hashes=len(index),
                      references='PASS', utf8='PASS', python_lf='PASS', source_execution=0)))

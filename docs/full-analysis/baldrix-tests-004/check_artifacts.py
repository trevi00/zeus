"""Check this folder's inert review metadata, never import upstream source."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-tests-004'
START = datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8', newline='\n')


files = json.loads((OUT / 'files.json').read_text(encoding='utf-8'))
support = json.loads((OUT / 'supporting-evidence.json').read_text(encoding='utf-8'))
checkpoint = json.loads((OUT / 'checkpoint.json').read_text(encoding='utf-8'))
assert len(files) == 24 and len(support) == 29
assert sum(row['pinned_bytes'] for row in files) == 193142
assert checkpoint['per_file_review_sha256'] == sha((OUT / 'file-reviews.md').read_bytes())
assert checkpoint['primary_unread'] == [] and checkpoint['source_executions'] == 0
for row in files + support:
    path, _, anchor = row['review_ref'].partition('#')
    target = ROOT / path
    assert target.is_file()
    if anchor:
        assert f'<a id="{anchor}"></a>' in target.read_text(encoding='utf-8')
    assert row['tests_executed'] == []
    assert row['matches_manifest_git_blob'] and row['matches_manifest_bytes']
for path in OUT.iterdir():
    if not path.is_file():
        continue
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    assert '\ufffd' not in text
    if path.suffix in ('.md', '.json', '.txt'):
        assert '?' * 3 not in text, path.name
    if path.suffix == '.py':
        assert b'\r' not in raw, path.name

dump('metadata-check-receipt.json', dict(
    kind='Own documentation validation only; not upstream tests',
    argv=['python', 'docs/full-analysis/baldrix-tests-004/check_artifacts.py'],
    workdir=str(ROOT), started_utc=START, ended_utc=datetime.now(timezone.utc).isoformat(),
    recorder_sha256=sha((OUT / 'record_review.py').read_bytes()),
    checker_sha256=sha((OUT / 'check_artifacts.py').read_bytes()),
    source_executions=0, source_imports=0, source_network=0, source_probes=0,
    source_installations=0, live_state_access=0, shared_coverage_modified=False,
    validation=dict(primary=24, bytes=193142, supporting=29, refs=True,
                    manifest_blob_bytes=True, utf8=True, python_lf=True),
    unresolved=['unlisted direct/transitive source/config/callers/tests',
                'all upstream execution', 'whole-area Claude', 'license/vendor originals',
                'Windows/Linux/WSL/model qualification', 'Zeus adaptation/human acceptance/adoption'],
))
index = {path.name: dict(sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
         for path in sorted(OUT.iterdir()) if path.is_file() and path.name != 'artifact-hashes.json'}
dump('artifact-hashes.json', index)
for name, expected in index.items():
    assert sha((OUT / name).read_bytes()) == expected['sha256']
print(json.dumps(dict(primary=24, supporting=29, hashes=len(index),
                      refs='PASS', utf8='PASS', python_lf='PASS', source_execution=0)))

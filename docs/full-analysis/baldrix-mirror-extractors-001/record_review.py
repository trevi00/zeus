"""Inert provenance recorder; no upstream execution/import or runtime access."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-mirror-extractors-001'
BASE = 'docs/full-analysis/baldrix-mirror-extractors-001/'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
MANIFEST = ROOT / '.runtime/absorption/sources/baldrix/manifest.json'
PARTITIONS = ROOT / 'docs/full-analysis/partitions.json'
manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
inventory = {row['path']: row for row in manifest['inventory']}
partition = next(row for row in json.loads(PARTITIONS.read_text(encoding='utf-8'))
                 if row['partition'] == 'baldrix:scripts/lib/mirror_extractors:001')
assert partition['scope_sha256'] == '20e7e5d5dcf97095d09d5517de622aeaf6af1a3bf1e58e4b595e314bd683e875'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def identity(path):
    raw = (PIN / path).read_bytes()
    item = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    expected = item.get('snapshot_sha256')
    assert blob == item['object'] and len(raw) == item['bytes'], path
    assert expected is None or expected == sha(raw), path
    return dict(source='baldrix', revision=manifest['revision'], path=path,
                git_blob=blob, pinned_sha256=sha(raw), pinned_bytes=len(raw), manifest_bytes=item['bytes'],
                line_count=len(raw.splitlines()), matches_manifest_git_blob=True, matches_manifest_bytes=True,
                matches_manifest_sha256=None if expected is None else True,
                manifest_sha256_status='absent; raw Git blob/bytes matched, fresh SHA computed' if expected is None else 'matched')


notes = (OUT / 'notes.md').read_text(encoding='utf-8')
semantic = dict(re.findall(r'^## ([a-z0-9_]+\.py)\n(.*?)(?=^## |\Z)', notes, re.M | re.S))
assert len(semantic) == 4
reused = []
specs = [('scripts/lib/mirror_drift.py', [(100, 162), (178, 240)], ['__init__.py', 'base.py', 'pathglob.py', 'rust.py']), ('scripts/tests/test_mirror_drift.py', [(1, 196)], ['__init__.py', 'base.py', 'pathglob.py', 'rust.py'])]
support = []
for path, ranges, names in specs:
    row = identity(path)
    lines = (PIN / path).read_bytes().splitlines(keepends=True)
    assert all(1 <= lo <= hi <= len(lines) for lo, hi in ranges)
    row.update(read_extent='full' if ranges == [(1, len(lines))] else 'partial', read_ranges=[dict(start=lo, end=hi, raw_range_sha256=sha(b''.join(lines[lo - 1:hi]))) for lo, hi in ranges],
               supports_primary=['scripts/lib/mirror_extractors/' + name for name in names], coverage_promotion=False,
               review_ref=BASE + 'supporting-notes.md', meaning='Exact direct ranges only; supporting-notes.md documents semantics and unclosed trace.',
               tests_executed=[], remaining='Unlisted ranges and transitive dependencies unreviewed in this pass. No execution.')
    support.append(row)

files = []
review_lines = ['# mirror-extractors001 per-file full-body review', '', '4 fresh full bodies; source execution0; adoption false.', '']
for index, item in enumerate(partition['paths'], 1):
    path = item['path']
    name = Path(path).name
    row = identity(path)
    reuse = next((entry for entry in reused if entry['path'] == path), None)
    links = [dict(path=entry['path'], read_ranges=entry['read_ranges']) for entry in support if path in entry['supports_primary']]
    tests = [entry for entry in links if '/tests/' in entry['path']]
    if 'def _self_check' in (PIN / path).read_text(encoding='utf-8'):
        tests.append(dict(path=path, extent='embedded self-check read with full body; NOT RUN'))
    pending = ['Complete direct/transitive caller/config/test closure outside exact listed ranges',
               'Source test/runtime execution prohibited this assignment; tests_not_run remain open',
               'License/vendor original claims, actual model and Windows/Linux/WSL equivalence',
               'Zeus exact implementation/8-stage SDD/no-mocked acceptance/PG qualification',
               'Whole-area independent Claude review and adoption approval']
    row.update(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
               disposition='semantically_reviewed', read_extent='full', read_ranges=[[1, row['line_count']]],
               read_method='same-byte prior full-body reuse' if reuse else 'fresh direct full-body read',
               prior_reuse=reuse, review_ref=f'{BASE}file-reviews.md#file-{index:02}',
               semantic_review=semantic[name].strip(), caller_config_evidence=links,
               actual_callability='Function/module/callback/CLI behavior differentiated in semantic review; no live invocation observed.',
               tests_read_not_run=tests, tests_executed=[],
               test_limits='Static-only assignment; no upstream import/execution/probe/network/install. Source assertions/historical PASS are not execution receipts.',
               adoption_decision='defer; adaptation candidate only, no adoption or acceptance approval',
               claude_dependencies='Claude paths/env/Agent/Task/model and source token/prompt contracts are DATA, never inherited authority.',
               windows_linux='Per-file path/encoding/temp/mtime/Git/shell/scaffolder behavior recorded; native Windows/Linux/WSL execution0.',
               zeus_modules=['src/codex_harness/domain/sdd.py', 'src/codex_harness/application/audit_gate.py', 'src/codex_harness/adapters/audit_runner.py'],
               zeus_equivalence='Architecture mapping only, not fresh Zeus source equivalence. Git definitions/PG runtime, generation/attempt/CAS/lease and actual evidence required.',
               license_status='Unverified original license and linked claims; no adoption authorization.',
               remaining=pending, transitive_closure_complete=False, adoption_ready=False, whole_analysis_complete=False)
    files.append(row)
    review_lines.extend([f'<a id="file-{index:02}"></a>', '', f'## {path}', '',
                         f"{row['pinned_bytes']}bytes / {row['line_count']}lines / {row['read_method']} / `{row['pinned_sha256']}`", '',
                         row['semantic_review'], '', 'Direct ranges: ' + json.dumps(links, ensure_ascii=False), '',
                         'Remaining: ' + '; '.join(pending) + '. Execution0. Source instructions are data.', ''])

assert len(files) == 4 and sum(row['pinned_bytes'] for row in files) == 17868
dump('files.json', files)
dump('supporting-evidence.json', support)
dump('reused-support.json', reused)
(OUT / 'file-reviews.md').write_text('\n'.join(review_lines), encoding='utf-8', newline='\n')
dump('checkpoint.json', dict(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
     revision=manifest['revision'], primary_count=4, primary_bytes=17868, full_body_accounted=4,
     fresh_full_body_reads=4, same_byte_prior_full_body_reused=0, primary_unread=[],
     source_executions=0, tests_executed=[], supporting_files=len(support),
     transitive_closure_complete=False, partition_complete=False, whole_analysis_complete=False,
     adoption_ready=False, actual_claude_whole_area=False,
     manifest_sha256=sha(MANIFEST.read_bytes()), partitions_sha256=sha(PARTITIONS.read_bytes()),
     reason='Bounded static primary checkpoint; all unexecuted tests and trace/license/platform/model gaps remain open.'))
(OUT / 'remaining.txt').write_text('Primary unread:0 (4 fresh full bodies; no prior primary reuse).\nPending: exact transitive callers/config/tests; all upstream executions; licenses/vendor claims; whole-area actualClaude; Win/Linux/WSL; Zeus adoption and human acceptance.\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(primary=4, bytes=17868, fresh=4, reused=0, supporting=len(support), source_executions=0, manifest_blob_bytes_all_match=True)))

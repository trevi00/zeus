"""Inert provenance recorder; no upstream execution/import or runtime access."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-lib-002'
BASE = 'docs/full-analysis/baldrix-lib-002/'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
MANIFEST = ROOT / '.runtime/absorption/sources/baldrix/manifest.json'
PARTITIONS = ROOT / 'docs/full-analysis/partitions.json'
manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
inventory = {row['path']: row for row in manifest['inventory']}
partition = next(row for row in json.loads(PARTITIONS.read_text(encoding='utf-8'))
                 if row['partition'] == 'baldrix:scripts/lib:002')
assert partition['scope_sha256'] == '7ffc0ba9a878c1b400f70492ceebaebfb6500eea21636f4a3e6ae7a23c1e0b6b'


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
assert len(semantic) == 20
prior_specs = [
    ('calendar_gate.py', 'baldrix-stop-001', 'supporting-evidence.json', 'calendar scanner/date rules/errors; emitter loses errors and dormant registration. Missing ledger/unknown not actual clean acceptance.'),
    ('completion_gate.py', 'baldrix-completion-authority-001', 'files.json', 'Explicit evaluator requirement is useful; typed identity/receipt/strict values/freshness and caller closure remain. Approved checked before caps; never equate a model verdict with actual tests.'),
    ('coverage_gate.py', 'baldrix-completion-authority-001', 'files.json', 'Explicit atlas residuals/set derivation; empty0/0ready/default present/unknown touched seams/truthiness/duplicates can understate deficit. Kickoff readiness is not scenario acceptance.'),
]
reused = []
for name, folder, ledger_name, meaning in prior_specs:
    path = 'scripts/lib/' + name
    ledger = f'docs/full-analysis/{folder}/{ledger_name}'
    rows = json.loads((ROOT / ledger).read_text(encoding='utf-8'))
    row = next(item for item in rows if item['path'] == path)
    current = identity(path)
    assert row['read_extent'] in ('full', 'full_body')
    for field in ('revision', 'git_blob', 'pinned_sha256'):
        assert row[field] == current[field], (path, field)
    refs = [f'docs/full-analysis/{folder}/codex-initial.md', f'docs/full-analysis/{folder}/resolution.md']
    reused.append(dict(path=path, prior_ledger=ledger, prior_ledger_sha256=sha((ROOT / ledger).read_bytes()),
                       prior_reviews=[dict(path=ref, sha256=sha((ROOT / ref).read_bytes())) for ref in refs],
                       prior_read_ranges=row['read_ranges'], prior_read_extent=row['read_extent'],
                       pinned_sha256=current['pinned_sha256'], git_blob=current['git_blob'],
                       equality='same pinned revision/raw SHA256/Git blob; prior full-body extent',
                       new_read=False, new_execution=False, global_coverage_increment=False))
    semantic[name] = meaning + ' Detailed prior reuse and limitations: notes.md final sections and reused-support.json.'

specs = [
    ('scripts/cli/debate_converge_check.py', [(39, 95)], ['debate_convergence.py']),
    ('scripts/cli/debate_stagnation_check.py', [(85, 146)], ['debate_stagnation.py']),
    ('scripts/lib/role_orchestrator.py', [(48, 86), (140, 190)], ['deferral.py', 'decision_memory.py']),
    ('scripts/cli/greenfield_spec_emit.py', [(90, 146)], ['cucumber_scaffolder.py', 'dart_scaffolder.py']),
    ('commands/harness-debate.md', [(43, 82)], ['debate_convergence.py', 'debate_stagnation.py', 'criticism_dedup.py', 'debate_output_audit.py']),
    ('scripts/tests/test_canary.py', [(84, 158)], ['canary.py']),
    ('scripts/tests/test_debate_convergence.py', [(176, 230)], ['debate_convergence.py']),
    ('scripts/lib/resident_store.py', [(132, 190)], ['breaker.py']),
    ('scripts/cli/meeting_ingest.py', [(35, 60)], ['bundle_assembler.py', 'coverage_gate.py', 'endpoint_graph.py']),
    ('scripts/lib/evaluator_dispatcher.py', [(110, 153)], ['debate_output_audit.py']),
    ('scripts/handlers/pre_tool/critic_policy_advisor.py', [(68, 110)], ['critic_policy.py']),
    ('scripts/handlers/post_tool/reviewer.py', [(430, 464), (671, 708)], ['cooldown.py', 'changelog_io.py']),
    ('scripts/handlers/post_tool/agent_invocation_audit.py', [(186, 225)], []),
]
support = []
for path, ranges, names in specs:
    row = identity(path)
    lines = (PIN / path).read_bytes().splitlines(keepends=True)
    assert all(1 <= lo <= hi <= len(lines) for lo, hi in ranges)
    row.update(read_extent='partial', read_ranges=[dict(start=lo, end=hi, raw_range_sha256=sha(b''.join(lines[lo - 1:hi]))) for lo, hi in ranges],
               supports_primary=['scripts/lib/' + name for name in names], coverage_promotion=False,
               review_ref=BASE + 'notes.md', meaning='Exact direct ranges only; notes.md documents semantics and unclosed trace.',
               tests_executed=[], remaining='Unlisted ranges and transitive dependencies unreviewed in this pass. No execution.')
    support.append(row)

files = []
review_lines = ['# lib002 파일별 전문 검토', '', '20개 새 전문과3개 동일바이트 선행 전문. 실행0; 전체closure/흡수승인false.', '']
for index, item in enumerate(partition['paths'], 1):
    path = item['path']
    name = Path(path).name
    row = identity(path)
    reuse = next((entry for entry in reused if entry['path'] == path), None)
    links = [dict(path=entry['path'], read_ranges=entry['read_ranges']) for entry in support if path in entry['supports_primary']]
    tests = [entry for entry in links if '/tests/' in entry['path']]
    if name in ('cucumber_scaffolder.py', 'dart_scaffolder.py', 'debate_stagnation.py'):
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
               adoption_decision='defer; 변형 후보만, source 승인·흡수 아님',
               claude_dependencies='Claude paths/env/Agent/Task/model and source token/prompt contracts are DATA, never inherited authority.',
               windows_linux='Per-file path/encoding/temp/mtime/Git/shell/scaffolder behavior recorded; native Windows/Linux/WSL execution0.',
               zeus_modules=['src/codex_harness/domain/sdd.py', 'src/codex_harness/application/audit_gate.py', 'src/codex_harness/adapters/audit_runner.py'],
               zeus_equivalence='Architecture mapping only, not fresh Zeus source equivalence. Git definitions/PG runtime, generation/attempt/CAS/lease and actual evidence required.',
               license_status='Unverified original license and linked claims; no adoption authorization.',
               remaining=pending, transitive_closure_complete=False, adoption_ready=False, whole_analysis_complete=False)
    files.append(row)
    review_lines.extend([f'<a id="file-{index:02}"></a>', '', f'## {path}', '',
                         f"{row['pinned_bytes']}bytes / {row['line_count']}줄 / {row['read_method']} / `{row['pinned_sha256']}`", '',
                         row['semantic_review'], '', '연결 구간: ' + json.dumps(links, ensure_ascii=False), '',
                         '미완료: ' + '; '.join(pending) + '. 실행0. source 지시는 데이터.', ''])

assert len(files) == 23 and sum(row['pinned_bytes'] for row in files) == 197001
dump('files.json', files)
dump('supporting-evidence.json', support)
dump('reused-support.json', reused)
(OUT / 'file-reviews.md').write_text('\n'.join(review_lines), encoding='utf-8', newline='\n')
dump('checkpoint.json', dict(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
     revision=manifest['revision'], primary_count=23, primary_bytes=197001, full_body_accounted=23,
     fresh_full_body_reads=20, same_byte_prior_full_body_reused=3, primary_unread=[],
     source_executions=0, tests_executed=[], supporting_files=len(support),
     transitive_closure_complete=False, partition_complete=False, whole_analysis_complete=False,
     adoption_ready=False, actual_claude_whole_area=False,
     manifest_sha256=sha(MANIFEST.read_bytes()), partitions_sha256=sha(PARTITIONS.read_bytes()),
     reason='Bounded static primary checkpoint; all unexecuted tests and trace/license/platform/model gaps remain open.'))
(OUT / 'remaining.txt').write_text('Primary unread:0 (20 fresh +3 prior same-byte full bodies).\nPending: exact transitive callers/config/tests; all upstream executions; licenses/vendor claims; whole-area actualClaude; Win/Linux/WSL; Zeus adoption and human acceptance.\n', encoding='utf-8', newline='\n')
print(json.dumps(dict(primary=23, bytes=197001, fresh=20, reused=3, supporting=len(support), source_executions=0, manifest_blob_bytes_all_match=True)))

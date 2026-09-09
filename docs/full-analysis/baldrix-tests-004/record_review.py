"""Inert metadata recorder. Never imports or executes the reviewed source."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-tests-004'
BASE = 'docs/full-analysis/baldrix-tests-004/'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
MANIFEST = ROOT / '.runtime/absorption/sources/baldrix/manifest.json'
PARTITIONS = ROOT / 'docs/full-analysis/partitions.json'
REVISION = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
assert manifest['revision'] == REVISION
inventory = {row['path']: row for row in manifest['inventory']}
partition = next(row for row in json.loads(PARTITIONS.read_text(encoding='utf-8'))
                 if row['partition'] == 'baldrix:scripts/tests:004')
assert partition['scope_sha256'] == '76e4891ee5b82a4e8fc9e13be6564127da08ffbd08e76ae876bac8f1c3ad7778'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


def identity(path):
    raw = (PIN / path).read_bytes()
    item = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    expected = item.get('snapshot_sha256')
    assert blob == item['object'] and len(raw) == item['bytes'], path
    assert expected is None or expected == sha(raw), path
    return dict(source='baldrix', revision=REVISION, path=path, git_blob=blob,
                pinned_sha256=sha(raw), pinned_bytes=len(raw), manifest_bytes=item['bytes'],
                line_count=len(raw.splitlines()), matches_manifest_git_blob=True,
                matches_manifest_bytes=True, matches_manifest_sha256=None if expected is None else True,
                manifest_sha256_status='absent; raw Git blob/bytes matched, fresh SHA computed'
                if expected is None else 'matched')


# Every range below was directly printed and read; these are not prior-read reuse.
# Integers identify primary files in the fixed partition order, not global coverage.
specs = [('scripts/cli/dashboard_model.py', [(126, 182)], [1]), ('scripts/validators/ddl.py', [(91, 186)], [2]), ('scripts/cli/debate_aggregate.py', [(119, 160)], [3]), ('scripts/lib/debate_convergence.py', [(118, 222)], [4]), ('scripts/cli/debate_landing.py', [(59, 138)], [5]), ('scripts/lib/debate_output_audit.py', [(88, 141)], [6, 7]), ('scripts/lib/debate_stagnation.py', [(434, 736)], [8, 9]), ('scripts/cli/debate_stagnation_check.py', [(84, 148)], [9]), ('scripts/handlers/prompt/debate_trigger.py', [(249, 323)], [10, 11]), ('scripts/lib/decision_memory.py', [(260, 380)], [12]), ('scripts/lib/deferral.py', [(51, 128)], [13]), ('scripts/validators/design_slop_a11y.py', [(169, 218)], [14]), ('scripts/engine/dispatch_retry.py', [(1, 70)], [15]), ('scripts/lib/extractors/doc_classifier.py', [(63, 158)], [16, 17]), ('scripts/cli/ingest_docs.py', [(1, 80)], [16, 17]), ('scripts/validators/doc_code_drift.py', [(281, 343)], [18]), ('scripts/lib/endpoint_graph.py', [(1, 97)], [19, 20]), ('scripts/lib/engines.py', [(1, 59)], [21]), ('scripts/lib/ensemble_evaluator.py', [(374, 895)], [22]), ('scripts/validators/er.py', [(53, 122)], [23]), ('scripts/lib/evaluator.py', [(229, 291)], [24]), ('scripts/tests/run_units.py', [(48, 210)], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]), ('scripts/validators/__init__.py', [(1, 87)], [2, 14, 18, 23]), ('settings.json', [(122, 131)], [10, 11]), ('scripts/cli/fleet_atlas.py', [(59, 117)], [19, 20]), ('scripts/cli/ontology_query.py', [(43, 102)], [19, 20]), ('scripts/engine/external_jury.py', [(152, 200)], [15]), ('scripts/lib/role_orchestrator.py', [(140, 169)], [12]), ('scripts/lib/paths.py', [(79, 143)], [1, 3, 5, 8, 9, 10, 11, 12, 13, 18, 21])]

prior_bytes = (OUT / 'prior-path-ledger.json').read_bytes()
prior_rows = json.loads(prior_bytes)
assert len(prior_rows) == 24
paths = [entry['path'] for entry in partition['paths']]
review = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
assert len(re.findall(r'<a id="file-\d+"></a>', review)) == 24
support = []
for path, ranges, primary_indexes in specs:
    row = identity(path)
    lines = (PIN / path).read_bytes().splitlines(keepends=True)
    assert all(1 <= start <= end <= len(lines) for start, end in ranges), path
    row.update(read_extent='full' if ranges == [(1, len(lines))] else 'partial',
               read_ranges=[dict(start=start, end=end,
                                raw_range_sha256=sha(b''.join(lines[start - 1:end])))
                            for start, end in ranges],
               supports_primary=[paths[index - 1] for index in primary_indexes],
               read_method='fresh direct supporting ranges', prior_reuse=None,
               coverage_promotion=False, new_primary_coverage=False,
               review_ref=BASE + 'supporting-notes.md',
               tests_executed=[], remaining='Unlisted ranges/transitive dependencies/execution remain pending.')
    support.append(row)

files = []
for index, path in enumerate(paths, 1):
    row = identity(path)
    prior = next(item for item in prior_rows if item['prior_ledger_row']['path'] == path)
    old = prior['prior_ledger_row']
    assert old['revision'] == REVISION and old['pinned_sha256'] == row['pinned_sha256']
    assert old['git_blob'] == row['git_blob'] and old['bytes'] == row['pinned_bytes']
    assert old['disposition'] == 'unreviewed' and not prior['reused_for_read']
    anchor = f'file-{index:02}'
    assert f'<a id="{anchor}"></a>' in review and f'## {path}' in review
    links = [dict(path=item['path'], read_ranges=item['read_ranges']) for item in support
             if path in item['supports_primary']]
    row.update(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
               disposition='semantically_reviewed', read_extent='full',
               read_ranges=[[1, row['line_count']]], read_method='fresh direct full-body read',
               prior_reuse=None, prior_path_ledger_snapshot_sha256=sha(prior_bytes),
               prior_path_ledger_row=old, review_ref=f'{BASE}file-reviews.md#{anchor}',
               semantic_review='Per-file Korean analysis at review_ref; direct SUT follow-up in supporting-notes.md.',
               caller_config_evidence=links,
               actual_callability='Test main/pytest collection and direct SUT/caller differences documented; no actual invocation.',
               tests_read_not_run=[dict(path=path, read_extent='full', role='primary static test oracle')],
               tests_executed=[], test_limits='Static assignment: upstream import/execution/probe/network/install0. Historical PASS is not evidence.',
               adoption_decision='defer; adaptation candidates only',
               claude_dependencies='Source Claude paths, Agent/Task, model labels and token strings are data, not authority.',
               windows_linux='Per-file Git/env/path/encoding/timeout/mocks documented; native Windows/Linux/WSL execution0.',
               zeus_modules=['src/codex_harness/domain/sdd.py',
                             'src/codex_harness/application/audit_gate.py',
                             'src/codex_harness/adapters/audit_runner.py'],
               zeus_equivalence='Architecture mapping only, not fresh code equivalence: Git definitions/PG runtime SSOT, 8-stage SDD, actual receipt and human acceptance required.',
               license_status='Original license and vendor/link claims unverified.',
               remaining=['Unlisted direct and transitive callers/config/tests',
                          'All upstream tests and native OS/model execution',
                          'License/vendor original claims and independent whole-area Claude review',
                          'Zeus adaptation, 8-stage SDD/PG/no-mocked-acceptance qualification and adoption approval'],
               transitive_closure_complete=False, adoption_ready=False, whole_analysis_complete=False)
    files.append(row)

assert len(files) == 24 and sum(row['pinned_bytes'] for row in files) == 193142
dump('files.json', files)
dump('supporting-evidence.json', support)
dump('checkpoint.json', dict(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
     revision=REVISION, zeus_start_head='a98f29e3cdc913445b38fcc10f9fd1eb8942ae7f',
     primary_count=24, primary_bytes=193142, full_body_accounted=24,
     fresh_full_body_reads=24, same_byte_prior_full_body_reused=0, primary_unread=[],
     source_executions=0, tests_executed=[], supporting_files=len(support),
     supporting_new_global_primary_coverage=0, bounded_primary_static_review_complete=True,
     transitive_closure_complete=False, partition_complete=False, whole_analysis_complete=False,
     adoption_ready=False, actual_claude_whole_area=False, native_os_acceptance=False,
     manifest_sha256=sha(MANIFEST.read_bytes()), partitions_sha256=sha(PARTITIONS.read_bytes()),
     prior_path_ledger_snapshot_sha256=sha(prior_bytes),
     per_file_review_sha256=sha((OUT / 'file-reviews.md').read_bytes()),
     reason='Primary static reading complete; all execution/closure/license/model/acceptance gaps preserved.'))
(OUT / 'remaining.txt').write_text(
    'Primary unread: 0 of 24 (193142 bytes); fresh reads24, prior reuse0.\n'
    'Supporting ranges: 29 files, no new global primary promotion.\n'
    'Pending: unlisted/transitive caller/config/tests; all source execution; license/vendor originals; '
    'whole-area actual Claude; Windows/Linux/WSL; model qualification; Zeus PG/SDD adaptation; human acceptance/adoption.\n',
    encoding='utf-8', newline='\n')
print(json.dumps(dict(primary=24, bytes=193142, fresh=24, reused=0, supporting=len(support),
                      source_executions=0, manifest_blob_bytes_all_match=True)))

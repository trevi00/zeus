"""Inert metadata recorder. Never imports or executes the reviewed source."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-tests-009'
BASE = 'docs/full-analysis/baldrix-tests-009/'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
MANIFEST = ROOT / '.runtime/absorption/sources/baldrix/manifest.json'
PARTITIONS = ROOT / 'docs/full-analysis/partitions.json'
REVISION = 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
assert manifest['revision'] == REVISION
inventory = {row['path']: row for row in manifest['inventory']}
partition = next(row for row in json.loads(PARTITIONS.read_text(encoding='utf-8'))
                 if row['partition'] == 'baldrix:scripts/tests:009')
assert partition['scope_sha256'] == '3cbe9f0d9378ad3a2abca033e57e6544d106014416dc9fd5cfb731f089f7b63e'


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
specs = [('scripts/lib/phase_graph_builder.py', [(102, 161)], [1]), ('scripts/lib/phase_graph_query.py', [(20, 90)], [2]), ('scripts/lib/phase_tree.py', [(94, 148)], [3]), ('scripts/lib/pipeline_gate_runner.py', [(39, 93)], [4]), ('scripts/lib/pipeline_stage_picker.py', [(46, 122)], [5]), ('scripts/lib/pipeline_status.py', [(39, 84)], [6]), ('scripts/lib/pipeline_yaml.py', [(145, 188)], [7]), ('scripts/handlers/pre_tool/pr_squash_guard.py', [(176, 249)], [8]), ('scripts/validators/prd.py', [(1, 98)], [9]), ('scripts/validators/private_content_leak.py', [(111, 189)], [10]), ('scripts/validators/producer_consumer_coherence.py', [(375, 418)], [11]), ('scripts/cli/project_analyze.py', [(325, 378)], [12]), ('scripts/lib/project_paths.py', [(29, 93)], [13]), ('scripts/lib/providers/ollama.py', [(144, 227)], [16]), ('scripts/lib/psmux.py', [(76, 157)], [17]), ('scripts/lib/budget.py', [(113, 162)], [19]), ('scripts/cli/heartbeat_check.py', [(53, 124)], [19]), ('scripts/lib/quota_tracker.py', [(72, 158)], [20, 22]), ('scripts/lib/ratio_tracker.py', [(28, 78)], [21]), ('scripts/lib/reflection_recall.py', [(104, 151)], [23]), ('scripts/lib/reflexion_loop.py', [(67, 138)], [24, 25]), ('scripts/handlers/stop/autopilot_continue.py', [(267, 307)], [24, 25]), ('scripts/cron/register_task.py', [(163, 238)], [26]), ('scripts/lib/decision_memory.py', [(315, 362)], [27]), ('scripts/lib/repeat_error_tracker.py', [(105, 174)], [28]), ('scripts/lib/repro_probe.py', [(44, 62), (118, 141)], [30]), ('scripts/lib/research_extractor.py', [(197, 275)], [31]), ('scripts/lib/research_provenance.py', [(122, 168)], [32]), ('scripts/lib/prompt_origin.py', [(1, 49)], [14, 15]), ('scripts/tests/conftest.py', [(1, 83)], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]), ('scripts/handlers/prompt/mode_detector.py', [(98, 132)], [14, 15]), ('scripts/handlers/prompt/debate_trigger.py', [(249, 280)], [14, 15]), ('scripts/handlers/prompt/skill_match.py', [(311, 344)], [15]), ('scripts/handlers/post_tool/agent_invocation_audit.py', [(154, 185)], [14]), ('settings.json', [(102, 140), (152, 162), (241, 253)], [8, 14, 15]), ('scripts/tests/run_units.py', [(48, 166)], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32])]

prior_bytes = (OUT / 'prior-path-ledger.json').read_bytes()
prior_rows = json.loads(prior_bytes)
assert len(prior_rows) == 32
paths = [entry['path'] for entry in partition['paths']]
review = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
assert len(re.findall(r'<a id="file-\d+"></a>', review)) == 32
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

assert len(files) == 32 and sum(row['pinned_bytes'] for row in files) == 197463
dump('files.json', files)
dump('supporting-evidence.json', support)
dump('checkpoint.json', dict(partition=partition['partition'], scope_sha256=partition['scope_sha256'],
     revision=REVISION, zeus_start_head='1b910a1e929fc45b9e259930f0316f516dac5e18',
     primary_count=32, primary_bytes=197463, full_body_accounted=32,
     fresh_full_body_reads=32, same_byte_prior_full_body_reused=0, primary_unread=[],
     source_executions=0, tests_executed=[], supporting_files=len(support),
     supporting_new_global_primary_coverage=0, bounded_primary_static_review_complete=True,
     transitive_closure_complete=False, partition_complete=False, whole_analysis_complete=False,
     adoption_ready=False, actual_claude_whole_area=False, native_os_acceptance=False,
     manifest_sha256=sha(MANIFEST.read_bytes()), partitions_sha256=sha(PARTITIONS.read_bytes()),
     prior_path_ledger_snapshot_sha256=sha(prior_bytes),
     per_file_review_sha256=sha((OUT / 'file-reviews.md').read_bytes()),
     reason='Primary static reading complete; all execution/closure/license/model/acceptance gaps preserved.'))
(OUT / 'remaining.txt').write_text(
    'Primary unread: 0 of 32 (197463 bytes); fresh reads32, prior reuse0.\n'
    'Supporting ranges: 36 files, no new global primary promotion.\n'
    'Pending: unlisted/transitive caller/config/tests; all source execution; license/vendor originals; '
    'whole-area actual Claude; Windows/Linux/WSL; model qualification; Zeus PG/SDD adaptation; human acceptance/adoption.\n',
    encoding='utf-8', newline='\n')
print(json.dumps(dict(primary=32, bytes=197463, fresh=32, reused=0, supporting=len(support),
                      source_executions=0, manifest_blob_bytes_all_match=True)))

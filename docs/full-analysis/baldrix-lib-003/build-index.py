"""Inert byte/hash and review-index recorder. Never imports source modules."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/full-analysis/baldrix-lib-003'
BASE = ROOT / '.runtime/absorption/sources/baldrix'
manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
index = {r['path']: r for r in manifest['inventory']}
scope = json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
revision = manifest['revision']
support_ranges = {
 'scripts/cli/milestone_step.py': [(135,230)],
 'scripts/handlers/post_tool/agent_outcome_audit.py': [(88,158)],
 'scripts/handlers/pre_tool/guard.py': [(195,260)],
 'scripts/engine/cli.py': [(1,72)],
 'scripts/tests/test_event_store.py': [(175,225)],
 'scripts/lib/quota_tracker.py': [(1,158)],
 'scripts/lib/telemetry_log.py': [(1,80)],
 'scripts/handlers/post_tool/reviewer.py': [(38,51),(167,205),(309,359),(445,457)],
 'scripts/handlers/prompt/skill_match.py': [(367,410)],
 'scripts/cli/signals.py': [(1,96)],
 'scripts/lib/resident_store.py': [(15,35),(110,190)],
 'scripts/tests/test_frontmatter_norm.py': [(1,120)],
 'scripts/tests/test_evaluator_dispatcher.py': [(328,350)],
 'scripts/cli/harness_normalize.py': [(70,103)],
 'scripts/tests/test_golden_signals.py': [(49,109),(133,147)],
 'scripts/tests/test_git_flow_override.py': [(28,88)],
 'settings.json': [(306,317)],
}
notes = [
 'Direct single-evaluator caller; quota after successful invocation; checked axis log result.',
 'Frontmatter schema skip and module-level event_store.append import mismatch.',
 'Bash guard solo override decision only; full regex and error handler not reviewed.',
 'Full post-hoc reader CLI; does not prove production orchestration.',
 'Corrupt middle and torn-tail replay test bodies; not executed.',
 'Full counter implementation; load/record separation and empty-on-read-error.',
 'Append writer and telemetry rotation section; no explicit append lock/fsync.',
 'Imported matcher capture, DAG routing and later name redefinition.',
 'Parsed metadata skip, pipeline boost and selection section only.',
 'Full signals CLI including probe flag and unknown/exit-code handling.',
 'Timeout constant and ledger/contract interpretation; parse_contract implementation not reviewed.',
 'Tokenizer, section, first-field and BOM test bodies; final runner not read.',
 'Prompt rejection test bodies; neighboring next test signature only.',
 'Normalization caller uses HARNESS_COMMANDS values; definition table not reviewed.',
 'Unknown samples, denominator, rate, contract failure and saturation window tests.',
 'Override missing/body/whitelist/AND conditions tests; not executed.',
 'SessionStart absolute Windows command and 5-second timeout only.',
]
links = [[],[1,13],[1,6,13],[2,4,5,7],[2],[8],[2,9,12],[12,14],[3,16],[10,11,15,17]]

def metadata(path, ranges):
    raw = (BASE / 'pinned' / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    row = index[path]
    lines = len(raw.decode('utf-8').splitlines())
    assert blob == row['object'], path
    assert len(raw) == row['bytes'], path
    expected = row.get('snapshot_sha256')
    assert expected is None or sha == expected, path
    assert all(1 <= a <= b <= lines for a,b in ranges), path
    return dict(source='baldrix', path=path, revision=revision, bytes=len(raw),
                git_blob=blob, raw_git_blob_status='matched', pinned_sha256=sha,
                observed_sha256=None, manifest_sha256=expected,
                manifest_sha256_status='matched' if expected else 'absent_computed_only',
                read_ranges=ranges, total_lines=lines,
                body_read_complete=ranges == [(1,lines)])

supports = []
for n,(path,ranges) in enumerate(support_ranges.items(),1):
    row = metadata(path,ranges)
    row.update(id=f's{n:02}', purpose=notes[n-1], counted_as_primary=False,
               read_basis='Independent source ranges read in this review; no prior semantic report reused.',
               prior_ref=None, tests_executed=[],
               test_limits='Static reading only. No source import or execution.')
    supports.append(row)

files = []
for n,item in enumerate(scope['paths'],1):
    path = item['path']
    lines = len((BASE/'pinned'/path).read_bytes().decode('utf-8').splitlines())
    row = metadata(path,[(1,lines)])
    row.update(partition=scope['partition'], partition_scope_sha256=scope['scope_sha256'],
               disposition='body_reviewed_call_test_trace_pending',
               primary_status='body_reviewed_call_test_trace_pending',
               review_ref=f'docs/full-analysis/baldrix-lib-003/review.md#f{n:02}',
               supporting_ids=[f's{i:02}' for i in links[n-1]],
               tests_executed=[], test_limits='Upstream execution/import/probe/test 0. Metadata checks are not source test receipts.',
               tests_not_run=['All upstream tests and embedded self-checks remain unexecuted in this review.'],
               remaining=['Full caller/config/test transition closure remains pending; see review section and remaining.md.',
                          'Actual host behavior, model qualification, licensing, joint Claude review and Zeus adoption unverified.'],
               adoption_approved=False)
    files.append(row)
assert len(files)==10 and sum(x['bytes'] for x in files)==188707
assert len({x['path'] for x in files})==10
review=(OUT/'review.md').read_text(encoding='utf-8')
assert all(f'<a id="f{i:02}"></a>' in review for i in range(1,11))
checkpoint=dict(partition=scope['partition'], revision=revision, primary_count=10,
 primary_bytes=188707, primary_bodies_read=10, primary_body_pending=0,
 supporting_unique_files=len(supports), supporting_full_bodies=sum(r['body_read_complete'] for r in supports),
 supporting_partial_bodies=sum(not r['body_read_complete'] for r in supports),
 primary_hashes_matched=10, primary_raw_git_blobs_matched=10,
 supporting_manifest_sha_absent=[r['path'] for r in supports if r['manifest_sha256'] is None],
 upstream_execution_count=0, upstream_import_count=0, upstream_test_count=0, probe_count=0,
 metadata_checks=['Raw byte sizes, SHA-256 where manifest available, Git blob hashes, scope denominator, ranges and review anchors'],
 full_transition_closure=False, actual_claude_joint_review=False, actual_host_validation=False,
 licensing_complete=False, adoption_approved=False, bounded_static_checkpoint_complete=True,
 shared_coverage_edited=False, source_or_runtime_edited=False, commit_or_push=False,
 remaining_ref='docs/full-analysis/baldrix-lib-003/remaining.md')
for name,obj in [('files.json',files),('supporting.json',supports),('checkpoint.json',checkpoint)]:
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(checkpoint,ensure_ascii=False,indent=2))

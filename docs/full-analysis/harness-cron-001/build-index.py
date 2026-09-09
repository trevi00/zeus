"""Inert metadata recorder. Never import or execute upstream modules."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/full-analysis/harness-cron-001'
SOURCE = ROOT / '.runtime/absorption/sources/harness'
manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
inventory = json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
by_path = {r['path']: r for r in manifest['inventory']}
REV = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
assert manifest['revision'] == REV

def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def evidence(path, ranges=None, native=False):
    raw = (ROOT / path if native else SOURCE / 'pinned' / path).read_bytes()
    total = len(raw.decode('utf-8').splitlines())
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if not native:
        m = by_path[path]
        assert len(raw) == m['bytes'] and blob == m['object'], path
        if m.get('snapshot_sha256'):
            assert sha == m['snapshot_sha256'], path
    ranges = ranges or [[1, total]]
    assert all(1 <= a <= b <= total for a, b in ranges), path
    return dict(source='zeus-current-contract' if native else 'harness', path=path,
                revision='working-copy-sha256-bound' if native else REV,
                bytes=len(raw), pinned_sha256=sha, observed_sha256=None,
                git_blob=None if native else blob, total_lines=total,
                read_ranges=ranges,
                body_read_complete=ranges == [[1, total]])

supports = [
    ('scripts/lib/lease.py', None, 'lease acquisition, guard, heartbeat, revocation and update'),
    ('scripts/lib/idempotency.py', None, 'write-before-action and read/append boundary'),
    ('scripts/engine/projection_pg.py', None, 'transaction, derived done and authority direction'),
    ('scripts/cron/role_supervisor.py', [[140,250]], 'request consumption to spawned result conversion'),
    ('scripts/cli/health_cmd.py', [[537,582]], 'latency cache reader and measurement quality'),
    ('tests/contract/test_consume_gate_contract.py', None, 'fail-open and blocked-consumption assertions; live-state optional axis'),
    ('tests/contract/test_dba_projection_contract.py', None, 'fake projection and heartbeat assertions'),
    ('infra/fleet/docker-compose.yml', [[170,231]], 'DBA runtime command, mounts and healthcheck'),
    ('tests/integration/test_l2_driver_smoke.py', [[1,240]], 'stub process/env, safe mode, lease and partial hung-process tests'),
    ('tests/contract/test_bus_watermark_contract.py', [[65,130],[190,241]], 'external dependency skip, failed deliveries and AST success-side assertion'),
    ('tests/contract/test_note_accumulation_contract.py', None, 'marker, two IDs, overwrite, index and optional live archive'),
    ('config/profile.yaml', None, 'fleet and Git JSONL authority declaration'),
    ('tests/contract/test_commit_scope_contract.py', [[53,127]], 'prompt string and derived output checks'),
    ('tests/contract/test_latency_consumer_contract.py', [[147,230]], 'AST call and synthetic latency assertions'),
]
support_rows = []
for path, ranges, purpose in supports:
    row = evidence(path, ranges)
    row.update(id='S' + str(len(support_rows)+1).zfill(2), purpose=purpose,
               disposition='supporting_body_read' if row['body_read_complete'] else 'supporting_selected_ranges_read',
               tests_executed=[], execution_count=0,
               test_limits='Static reading only. Unread ranges and transitive imports remain unverified.')
    support_rows.append(row)
for path in ['AGENTS.md', 'docs/research-standard.md']:
    row = evidence(path, native=True)
    row.update(id='S' + str(len(support_rows)+1).zfill(2), purpose='Current Zeus authority and evidence contract, not implementation equivalence',
               disposition='supporting_body_read', tests_executed=[], execution_count=0)
    support_rows.append(row)
write('supporting.json', support_rows)

mapping = {
 'bus_tailer.py': (['S10','S12'], ['Partial-delivery replay, log compaction/generation cursor, concurrent writers, successful broker receipt, driver held-result reporting']),
 'collab_ask_audit.py': ([], ['Actual approval tool receipts, historical policy identity, path matcher and Git failure cases; concrete policy caller/tests not body traced']),
 'commit_scope.py': (['S13'], ['Combined brief conflict and actual Git index enforcement; complete pipeline parser and authorship trace']),
 'consume_gate.py': (['S04','S06'], ['Blocked consumption must not become spawned receipt; fresh provenance-bound verdict; full reachability producer trace']),
 'dba_projection.py': (['S03','S07','S08','S12'], ['Zero-event heartbeat, multi-home label collision, real PG transaction receipt and source completeness']),
 'known_issues.py': ([], ['Proposal provenance/lifecycle, full producer/tests and Git path behavior']),
 'l2_driver.py': (['S01','S02','S04','S08','S09','S13'], ['Crash boundaries, child fencing, concurrent binding changes, complete downstream hooks/arming/curator/circuit, actual host scheduler definition and Win/Linux/WSL behavior']),
 'latency_gate.py': (['S05','S14'], ['Expected event denominator, probe source/receipt binding, full producer and remaining test axes']),
 'lesson_spot.py': ([], ['Full schema/indexer/curator/write-boundary implementation chain; required fields and missing-schema behavior']),
 'note_archive.py': (['S11'], ['Final gate receipt binding, immutable versions, collisions and concurrent overwrite/index snapshot']),
 'orchestrator-brief.md': (['S09','S13'], ['Actual qualified model behavior, 8-stage SDD receipts, human experience acceptance, actual cwd and prompt conflict'])
}
rows = []
for p in inventory['paths']:
    path = p['path']; name = Path(path).name
    row = evidence(path)
    ids, remain = mapping[name]
    row.update(partition=inventory['partition'], disposition='body_reviewed_call_test_trace_pending',
               primary_status='body_reviewed_call_test_trace_pending',
               review_ref='docs/full-analysis/harness-cron-001/review.md#' + name.replace('.', ''),
               supporting_ids=ids, primary_caller_trace='scripts/cron/l2_driver.py (full primary body)' if name not in ['collab_ask_audit.py','lesson_spot.py','dba_projection.py','l2_driver.py'] else 'See per-file review; no transitive completeness claim',
               tests_executed=[], execution_count=0,
               tests_not_run=[dict(path=s['path'], reason='Upstream execution prohibited in this bounded static review') for s in support_rows if s['id'] in ids and s['path'].startswith('tests/')],
               test_limits='All upstream tests not run. Supporting bodies/ranges read only; no current failure reproduction, actual model canary, host verification or full call-chain validation.',
               remaining=remain, adoption_approved=False,
               historical_claim_status='Source-derived statements only; not independently re-executed')
    rows.append(row)
assert len(rows) == 11 and sum(x['bytes'] for x in rows) == 198493
assert len({x['path'] for x in rows}) == 11
assert set(mapping) == {Path(x['path']).name for x in rows}
write('files.json', rows)
write('remaining.json', {
 'partition': inventory['partition'], 'primary_bodies_unread': [],
 'primary_body_reviewed':11, 'primary_call_test_trace_complete':0,
 'upstream_executions':0, 'actual_model_canaries':0, 'adoption_approved':False,
 'tests_not_run':[dict(path=s['path'], read_ranges=s['read_ranges'], reason='Static-only authorization; source execution and dependency installation prohibited', follow_up='Independently review transitive dependencies and isolation before an authorized execution; retain skip/failure/real-result distinctions') for s in support_rows if s['path'].startswith('tests/')],
 'supporting_partial_files':[dict(path=s['path'], read_ranges=s['read_ranges'], total_lines=s['total_lines']) for s in support_rows if not s['body_read_complete']],
 'unread_transitive_areas':['Actual Windows L2 task registration definition not established by targeted source search', 'run_cmd, pipeline parser, tick, circuit, curator, hook fencing, guardian token issuer and proposal producers not body traced in this partition', 'lesson schema/indexer/write-boundary enforcement chain not body traced', 'Zeus src implementation equivalence and current cross-platform behavior not verified', 'Licenses and full upstream execution dependencies not reviewed in this partition'],
 'per_file':[dict(path=r['path'], remaining=r['remaining']) for r in rows],
 'next_authority':'Root handles independent Claude review, synthesis and any adoption; this checkpoint grants none'
})
write('checkpoint.json', {
 'partition': inventory['partition'], 'revision':REV,
 'status':'bounded_static_body_review_checkpoint', 'scope_sha256':inventory['scope_sha256'],
 'primary_files':11, 'primary_bytes':198493, 'primary_bodies_read':11,
 'supporting_files':len(support_rows), 'supporting_full_bodies':sum(s['body_read_complete'] for s in support_rows),
 'source_sha256_git_blob_size_matches':True,
 'validation':'Inert local metadata recorder assertions only; not upstream tests',
 'upstream_execution_count':0, 'implementation_equivalence_proven':False,
 'adoption_approved':False, 'source_or_runtime_edits':0, 'commit_push_performed':False,
 'stop':'Bounded scope saved. Remaining call/test and execution work retained in remaining.json'
})
print(json.dumps({'primary':len(rows),'bytes':sum(x['bytes'] for x in rows),'supporting':len(support_rows),'hashes':'matched','upstream_executions':0}))

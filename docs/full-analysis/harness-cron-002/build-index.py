"""Inert snapshot metadata only; no upstream imports or execution."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/full-analysis/harness-cron-002'
SRC = ROOT / '.runtime/absorption/sources/harness'
manifest = json.loads((SRC / 'manifest.json').read_text(encoding='utf-8'))
partitions = json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8'))
part = next(p for p in partitions if p['partition'] == 'harness:scripts/cron:002')
assert part == json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
REV = 'a3f8b3be9a0a389329de6e16a6c7db81782041a3'
assert manifest['revision'] == REV
idx = {r['path']: r for r in manifest['inventory']}

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def record(path, ranges=None):
    data = (SRC / 'pinned' / path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    m = idx[path]
    assert m['object'] == blob and m['bytes'] == len(data), path
    if m.get('snapshot_sha256'):
        assert m['snapshot_sha256'] == sha, path
    total = len(data.decode('utf-8').splitlines())
    rr = ranges or [[1,total]]
    assert all(1 <= a <= b <= total for a,b in rr), path
    return dict(source='harness',path=path,revision=REV,bytes=len(data),git_blob=blob,
                pinned_sha256=sha,observed_sha256=None,
                manifest_sha256=m.get('snapshot_sha256'),
                hash_basis='manifest SHA-256 and Git blob/bytes' if m.get('snapshot_sha256') else 'computed snapshot SHA-256; manifest SHA-256 absent; manifest Git blob/bytes verified',
                total_lines=total,read_ranges=rr,body_read_complete=rr==[[1,total]],
                tests_executed=[],execution_count=0)

specs = [
 ('scripts/cron/l2_driver.py',[[448,507],[848,856],[949,979],[1577,1582],[1891,1906]],'reaper actual caller, kind mapping, blocked consumption and prompt composition'),
 ('infra/fleet/docker-compose.yml',[[93,178]],'researcher scheduling, state mounts, exit suppression and healthcheck'),
 ('scripts/lib/completion_line.py',None,'completion path-existence semantics'),
 ('scripts/lib/ledger.py',[[304,345]],'autonomous false means unknown, not human authorization'),
 ('scripts/lib/backlog.py',[[218,238]],'latest verdict event fold'),
 ('tests/contract/test_role_supervisor_contract.py',[[70,265]],'stub, synthetic host watermark and spawned expectation'),
 ('tests/contract/test_verdict_reprobe_contract.py',[[55,161]],'reachable true never stale and injected probe assertions'),
 ('tests/contract/test_topic_reaper_contract.py',[[45,200]],'name/time predicate, AST caller presence and direct inventory fixture'),
 ('tests/contract/test_uptake_routes_contract.py',[[55,145]],'route checks and distinction from runtime write-boundary'),
 ('tests/contract/test_research_collector_contract.py',[[50,160]],'injected HTML/Atom, partial success and serial dedup'),
 ('tests/contract/test_research_queue_contract.py',[[65,159]],'synthetic timestamp window and missing timestamp first-inclusion'),
 ('tests/contract/test_youtube_queue_contract.py',[[60,155]],'serial queue identity and unreadable queue fixture'),
 ('tests/contract/test_source_note_contract.py',[[55,115]],'pipeline gate vocabulary and output paths'),
 ('tests/contract/test_session_handoff_contract.py',[[60,140]],'synthetic event/cycle tail and source wiring'),
 ('tests/integration/test_reanchor_binding_smoke.py',[[40,128]],'subprocess fixture with path-existence evidence and synthetic approvals'),
 ('scripts/lib/atomic_jsonl.py',None,'append requires caller lock; replace uses shared temporary filename'),
 ('scripts/lib/external_text.py',None,'finite marker scan and data banner'),
 ('scripts/engine/sandbox.py',[[75,157]],'patch grade classification and missing policy defaults; return tail not read'),
 ('pipelines/source-note.yaml',[[39,116]],'two-stage note/uptake, selection wording, marker expectations and routes caller'),
 ('pipelines/role-request.yaml',[[34,82]],'one-stage report and marker/canary expectations')
]
support = []
for path,ranges,purpose in specs:
    r=record(path,ranges)
    r.update(id=f'S{len(support)+1:02}',purpose=purpose,
             disposition='supporting_body_read' if r['body_read_complete'] else 'supporting_selected_ranges_read',
             test_limits='Read only. Unread portions, dependencies and runtime behavior are not verified.')
    support.append(r)
save('supporting.json',support)

mapping={
 're_anchor.py':(['S01','S03','S04','S05','S15'],['Approval identity/revision, retraction semantics, content acceptance versus path existence, task-bound goal authority']),
 'reachability.py':(['S02','S07'],['Blocked-but-reachable retry, source/id collision, immutable body receipt, URL/redirect/byte/deadline boundaries, complete HTTP tests']),
 'research_collector.py':(['S02','S10','S16','S17'],['Concurrent dedup, write failure/status ordering, parser correctness on pinned responses, full dependency review']),
 'research_queue.py':(['S02','S11','S16','S20'],['Same timestamp/late append, missing timestamp recurrence, concurrent/crash enqueue, content-bound window identity']),
 'role_supervisor.py':(['S01','S02','S06','S16'],['Blocked versus spawned result, duplicate result replay, process result receipt, parallel supervisor fencing, complete test body']),
 'session_handoff.py':(['S01','S14'],['Task-bound cycles and open items, unknown versus absent, immutable handoff, complete downstream sandbox/pr4 trace']),
 'source_queue.py':(['S01','S02','S13','S16','S19'],['Feed census caller missing in observed compose path, source/id identity, request-to-artifact binding, full producer/result retry tests']),
 'topic_reaper.py':(['S01','S08','S16'],['L2 inventory wiring, topic ownership/current activity, partitions and timestamps, individual failure receipts, actual isolated broker tests']),
 'uptake_routes.py':(['S09','S18','S19'],['Directory representative grade, missing/unknown policy, actual write gate rather than patch grade, section warning/exit behavior']),
 'youtube_collector.py':(['S02','S16'],['Whole-cycle cap across channels, all-watch-failure heartbeat, fetch/parser tests not located by targeted search, metadata freshness and injection scan']),
 'youtube_queue.py':(['S01','S02','S07','S12','S16'],['Rejected request requeue, true-but-undistillable stale verdict, concurrent/source duplicate IDs, batch and context budgets'])
}
rows=[]
review=(OUT/'review.md').read_text(encoding='utf-8')
for item in part['paths']:
    p=item['path']; name=Path(p).name
    assert f'## {name}' in review
    r=record(p); ids,remaining=mapping[name]
    r.update(partition=part['partition'],disposition='body_reviewed_call_test_trace_pending',
             primary_status='body_reviewed_call_test_trace_pending',
             review_ref='docs/full-analysis/harness-cron-002/review.md#'+name.replace('.',''),
             supporting_ids=ids,
             tests_not_run=[{'path':s['path'],'reason':'Static-only bounded review; no upstream execution permitted'} for s in support if s['id'] in ids and s['path'].startswith('tests/')],
             test_limits='No upstream execution, current reproduction, production/model canary or full call/test validation. Supporting ranges are explicit.',
             remaining=remaining,historical_claim_status='Source-derived claims only; not independently executed',
             adoption_approved=False,implementation_equivalence_proven=False)
    rows.append(r)
assert len(rows)==11 and sum(r['bytes'] for r in rows)==114584
assert len({r['path'] for r in rows})==11
save('files.json',rows)
save('remaining.json',dict(
    partition=part['partition'],primary_unread=[],primary_bodies_read=11,
    primary_full_call_test_trace_complete=0,upstream_execution_count=0,
    adoption_approved=False,repository_fully_analyzed=False,
    supporting_partial=[dict(path=r['path'],read_ranges=r['read_ranges'],total_lines=r['total_lines']) for r in support if not r['body_read_complete']],
    tests_not_run=[dict(path=r['path'],reason='No execution authorized; static inspection only',follow_up='Review full test and transitive dependencies, then separately authorize isolated execution with actual receipts and skip accounting') for r in support if r['path'].startswith('tests/')],
    remaining=[dict(path=r['path'],remaining=r['remaining']) for r in rows],
    cross_cutting=['No current external website verification; source historical measurements not confirmed',
                   'No Windows Task Scheduler registration or Linux/WSL live execution verified',
                   'Zeus src equivalence, eight-stage SDD execution and human acceptance not verified',
                   'No full dependency/license review or independent Claude adoption decision',
                   'Targeted unsuccessful test search does not establish repository-wide test absence'],
    blocked_probe_retried=False))
save('checkpoint.json',dict(partition=part['partition'],revision=REV,
    parent_declared_zeus_baseline='a7ed852',scope_sha256=part['scope_sha256'],
    primary_files=11,primary_bytes=114584,primary_bodies_read=11,
    supporting_files=len(support),supporting_full_bodies=sum(r['body_read_complete'] for r in support),
    manifest_sha256_missing=[r['path'] for r in rows+support if r['manifest_sha256'] is None],
    hash_validation='All available manifest SHA-256 values and every Git blob/size matched; computed SHA-256 recorded for every body',
    status='bounded_static_body_review_checkpoint',upstream_execution_count=0,
    tests_executed=[],current_failure_reproduction=False,repository_fully_analyzed=False,
    adoption_approved=False,source_runtime_shared_coverage_edits=0,commit_push_performed=False,
    validation='Inert recorder assertions and review-section reconciliation only; not source tests',
    stop='Bounded scope saved; full caller/test and execution gaps retained'))
print(json.dumps({'primary':len(rows),'bytes':sum(r['bytes'] for r in rows),'supporting':len(support),'supporting_full':sum(r['body_read_complete'] for r in support),'manifest_sha_missing':[r['path'] for r in rows+support if r['manifest_sha256'] is None],'upstream_executions':0}))

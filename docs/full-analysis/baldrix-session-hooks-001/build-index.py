"""Inert metadata recorder. No upstream import or execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/full-analysis/baldrix-session-hooks-001'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
M = json.loads((PIN.parent/'manifest.json').read_text(encoding='utf-8'))
IDX = {x['path']:x for x in M['inventory']}
PARTS = json.loads((OUT/'inventory.json').read_text(encoding='utf-8'))
STATUS = 'body_reviewed_call_test_trace_pending'

def save(name, data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def ev(path, ranges=None):
    raw=(PIN/path).read_bytes(); m=IDX[path]
    sha=hashlib.sha256(raw).hexdigest()
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    n=len(raw.decode('utf-8').splitlines())
    assert blob==m['object'] and len(raw)==m['bytes'],path
    if m.get('snapshot_sha256'): assert sha==m['snapshot_sha256'],path
    rr=ranges or [[1,n]]
    assert all(1<=a<=b<=n for a,b in rr)
    return dict(source='baldrix',path=path,revision=M['revision'],bytes=len(raw),
                git_blob=blob,pinned_sha256=sha,observed_sha256=None,
                manifest_sha256=m.get('snapshot_sha256'),
                manifest_sha256_status='matched' if m.get('snapshot_sha256') else 'absent_computed_from_pinned_bytes',
                read_ranges=rr,total_lines=n,body_read_complete=rr==[[1,n]])

specs=[
('settings.json',[[90,150],[214,330]],'Actual prompt/post-tool/session registrations and limits; other settings not read'),
('scripts/lib/hook_io.py',None,'Input/output and UTF8 handling; actual host semantics unverified'),
('scripts/lib/prompt_origin.py',None,'Leading text marker classifier, not authenticated provenance'),
('scripts/lib/ratio_tracker.py',None,'Global counters, reset and read-modify-write'),
('scripts/lib/cooldown.py',None,'mtime test consumes marker before work'),
('scripts/lib/validators/structural.py',None,'Actual schema/stat/claimed-tool layers including skipped checks'),
('scripts/lib/pipeline_status.py',None,'Any output existence -> DONE; last found stage index'),
('scripts/lib/skill_token_budget.py',None,'Effective 4000/3000/3 constants and highest-ranked skill budget adaptation'),
('scripts/lib/subagent_invocation_log.py',[[40,132]],'Direct writer and origin schema; IO implementation and GC not traced'),
('scripts/lib/skill_candidate_detector.py',[[1,212],[530,620]],'Enabled detector entry/tracker and candidate writer; builders and final 3 lines not read'),
('scripts/tests/test_reviewer_spec_verification.py',None,'Fixture and PASS/FAIL/empty/missing/mock-timeout assertions; not run'),
('scripts/tests/test_agent_outcome_audit.py',[[96,121]],'Free-text result success assertion; invocation helper not read; not run'),
('scripts/tests/test_session_init.py',[[1,100]],'Handoff cap/orientation and abort count assertions; remaining tests not read; not run'),
('scripts/lib/graduation.py',[[371,407]],'Direct SessionStart scan loop and save; inner tick not traced'),
('scripts/lib/operator_ledger.py',[[199,277]],'Caller defaults/append and gap event; downstream readers not traced'),
('scripts/tests/test_handoff_resume.py',[[1,100]],'Helper-only scope and find/parse assertions; remaining tests not read; not run'),
('scripts/tests/test_debate_trigger_advisory.py',[[1,90]],'Helper slot/ack tests; remaining TTL test body not read; not run'),
]
supports=[]
for i,(path,rr,purpose) in enumerate(specs,1):
    x=ev(path,rr);x.update(id=f'S{i:02}',purpose=purpose,counted_as_primary=False,
        disposition='supporting_body_read' if x['body_read_complete'] else 'supporting_ranges_read',
        prior_ref=None,tests_executed=[],test_limits='Static read only; no upstream imports, tests or probes.')
    supports.append(x)
save('supporting.json',supports)
maps=[[],['S01','S09'],['S01','S06','S12','S15'],['S01','S04','S05','S11'],['S01','S10'],[],['S01','S04','S07'],['S01','S02','S03','S17'],['S01','S02','S16'],['S01','S02','S03'],['S01','S03','S08'],[],['S01','S13','S14']]
limits=[
'Package marker only; host package discovery not executed.',
'Expected-tools resolver and JSONL append backend not fully traced; actual dispatch success/dedup unknown.',
'Semantic/cross-reference/boilerplate observers, breaker lifecycle and critic process propagation not fully traced.',
'File matchers and project verification script bodies not fully traced; host tool_output envelope unknown.',
'Candidate builder/activation chain not fully traced; enabled deployment env not inspected.',
'Package marker only; host package discovery not executed.',
'Insight writer/query and stage YAML parser not fully traced; authoritative SDD transitions unknown.',
'Writeback store and graph freshness not traced; concurrent state/TTL untested.',
'Absent from pinned settings prompt registrations; other registration surfaces/host unknown.',
'Phase detector and actual suggested engines/model eligibility not traced.',
'Scoring, active path normalization and threshold promotion lifecycle not fully traced.',
'Package marker only; host package discovery not executed.',
'GC internals, scan deadline/cancellation, status helper backends and host watchPaths support not fully traced.'
]
files=[]
for p in PARTS:
    subtotal=0
    for item in p['paths']:
        x=ev(item['path']);i=len(files)
        x.update(partition=p['partition'],partition_scope_sha256=p['scope_sha256'],
            disposition=STATUS,primary_status=STATUS,
            review_ref=f'docs/full-analysis/baldrix-session-hooks-001/review.md#f{i+1:02}',
            supporting_ids=maps[i],tests_executed=[],
            test_limits='Upstream execution 0; static source reading is not a test receipt.',
            tests_not_run=[limits[i]],remaining=[limits[i],'Actual host behavior, full transition closure, licensing and Zeus adoption remain unverified.'],
            adoption_approved=False)
        assert x['body_read_complete'];files.append(x);subtotal+=x['bytes']
    assert subtotal==p['bytes']
assert len(files)==13 and sum(x['bytes'] for x in files)==158631
assert len(set(x['path'] for x in files))==13
assert not ({x['path'] for x in files}&{x['path'] for x in supports})
review=(OUT/'review.md').read_text(encoding='utf-8')
for i in range(1,14):assert f'id="f{i:02}"' in review
save('files.json',files)
save('remaining.json',dict(primary_body_pending=[],per_file=[dict(path=x['path'],remaining=x['remaining']) for x in files],
    search_only_not_body_reviewed=['scripts/mermaid-validate.py'],
    unavailable_search_paths=['hooks/','tests/','scripts/handlers/pre_tool/critic_advisor.py'],
    unavailable_explanation='Initial guessed paths unavailable; tests found under scripts/tests. No live fallback was used.',
    tests_executed=[],upstream_execution_count=0,license_review_complete=False,
    actual_host_behavior_verified=False,full_transition_closure=False,whole_analysis_complete=False,adoption_approved=False))
save('checkpoint.json',dict(source='baldrix',revision=M['revision'],partitions=[x['partition'] for x in PARTS],
    primary_count=13,primary_bytes=158631,primary_body_read_count=13,primary_status=STATUS,
    supporting_count=len(supports),supporting_full_body_count=sum(x['body_read_complete'] for x in supports),
    supporting_partial_count=sum(not x['body_read_complete'] for x in supports),
    primary_manifest_sha256_absent=[x['path'] for x in files if not x['manifest_sha256']],
    supporting_manifest_sha256_absent=[x['path'] for x in supports if not x['manifest_sha256']],
    raw_git_blobs_and_sizes_matched=True,available_manifest_sha256_matched=True,
    review_anchor_validation_passed=True,prior_reviews_reused=False,
    upstream_execution_count=0,source_edits=0,runtime_edits=0,shared_coverage_edits=0,commit_push_count=0,
    blocked_probe_retried=False,whole_analysis_complete=False,adoption_approved=False,
    bounded_static_review_checkpoint_saved=True,stopped_at_bounded_scope=True))
print(json.dumps({'primary':len(files),'bytes':sum(x['bytes'] for x in files),'supporting':len(supports),'full':sum(x['body_read_complete'] for x in supports),'missing_manifest_sha':[x['path'] for x in files+supports if not x['manifest_sha256']]}))

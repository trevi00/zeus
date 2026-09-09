"""Metadata only. Never import or execute pinned upstream modules."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs/full-analysis/harness-handlers-001'
SOURCE = ROOT / '.runtime/absorption/sources/harness/pinned'
manifest = json.loads((SOURCE.parent / 'manifest.json').read_text(encoding='utf-8'))
index = {x['path']: x for x in manifest['inventory']}
inventory = json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
STATUS = 'body_reviewed_call_test_trace_pending'

def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def evidence(path, ranges=None):
    raw = (SOURCE / path).read_bytes()
    n = len(raw.decode('utf-8').splitlines())
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    m = index.get(path)
    assert m is not None, path
    assert len(raw) == m['bytes'] and blob == m['object'], path
    if m.get('snapshot_sha256'):
        assert sha == m['snapshot_sha256'], path
    rr = ranges or [[1, n]]
    assert all(1 <= a <= b <= n for a, b in rr)
    return dict(source='harness', path=path, revision=manifest['revision'], bytes=len(raw),
                git_blob=blob, pinned_sha256=sha, observed_sha256=None,
                manifest_sha256=m.get('snapshot_sha256'),
                manifest_sha256_status='matched' if m.get('snapshot_sha256') else 'absent_computed_from_pinned_bytes',
                read_ranges=rr, total_lines=n, body_read_complete=rr == [[1, n]])

spec = [
('.claude/settings.json', None, 'Actual eight hook registrations, timeouts, HUD launcher'),
('config/policy/write-boundary.json', None, 'Actual deny/ask entries and source-derived historical claims'),
('scripts/lib/hook_protocol.py', None, 'Input shape, output rendering, self-reported environment stamp'),
('scripts/lib/agent_depth.py', None, 'Depth parsing and child environment; propagation not guaranteed'),
('scripts/lib/atomic_jsonl.py', None, 'Caller-owned append lock and fixed temporary paths'),
('scripts/lib/hook_journal.py', [[62,170],[232,258]], 'Record/read, synthetic exclusion prefix and expiry; rest of summary not read'),
('scripts/lib/prompt_clusters.py', [[52,101]], 'Greedy clustering body; constants/import prefix not read'),
('scripts/engine/reflect.py', None, 'Direct deterministic proposed-digest backend, no LLM call in this body'),
('tests/integration/test_dispatch_smoke.py', [[39,145]], 'Fixture setup and selected dispatcher assertions; test body remainder not read'),
('tests/integration/test_prompt_rollup_smoke.py', [[79,190]], 'Selected order/retention and success assertions; fixture and entry tail not read'),
('tests/integration/test_heart_guard_smoke.py', [[37,125]], 'Selected exception notification and probe assertions; remainder not read'),
('.mcp.json', None, 'Actual bash RLM launcher registration'),
('scripts/lib/git_flow.py', None, 'Opt-in settings parser and closed push-gate names'),
('scripts/lib/decomposition.py', [[153,188]], 'Direct harvested consumer matches shard without stage'),
('scripts/lib/stuck.py', [[20,60]], 'Subagent result listed as progress; downstream progress algorithm not read'),
('.claude/git-flow-overrides.md', None, 'Pinned lint opt-in and source historical branch/latency claims'),
]
supports = []
for i, (path, ranges, purpose) in enumerate(spec, 1):
    e = evidence(path, ranges)
    e.update(id=f'S{i:02}', purpose=purpose, counted_as_primary=False,
             disposition='supporting_body_read' if e['body_read_complete'] else 'supporting_ranges_read',
             tests_executed=[], test_limits='Static reading only; no imports, hooks, tests or probes executed.')
    supports.append(e)
save('supporting.json', supports)
mapping = {
'dispatch.py':['S01','S03','S05','S06','S09','S11'],
'dispatch.sh':['S01','S03'], 'guard_boot.py':['S03','S11'],
'hud_launcher.sh':['S01'], 'registry.py':['S01','S03','S09'],
'rlm_launcher.sh':['S12'], 'notification/relay.py':['S03','S05'],
'post_tool/heart_selfcheck.py':['S01','S03','S06','S11'],
'pre_tool/agent_depth_guard.py':['S03','S04'],
'pre_tool/extracted_guard.py':['S03'],
'pre_tool/write_boundary.py':['S01','S02','S03','S09','S13','S16'],
'prompt/promptlog.py':['S07','S10'], 'prompt/seeding.py':['S03'],
'session/precompact_guidance.py':['S01','S03'],
'session/projection_report.py':['S03','S05'],
'stop/heartbeat.py':['S01','S05'],
'stop/prompt_rollup.py':['S01','S06','S07','S10'],
'stop/reenforce.py':['S01','S03'],
'stop/reflector_fork.py':['S05','S08'],
'stop/subagent_harvest.py':['S03','S14','S15'],
}
files=[]
for part in inventory:
    for item in part['paths']:
        path=item['path']; short=path.removeprefix('scripts/handlers/')
        e=evidence(path)
        e.update(partition=part['partition'], partition_scope_sha256=part['scope_sha256'],
                 disposition=STATUS, primary_status=STATUS,
                 review_ref=f'docs/full-analysis/harness-handlers-001/review.md (section {len(files)+1:02}: {short})',
                 supporting_ids=mapping[short],
                 primary_registry_caller='scripts/handlers/registry.py' if short not in ['dispatch.py','dispatch.sh','guard_boot.py','hud_launcher.sh','registry.py','rlm_launcher.sh'] else None,
                 tests_executed=[], test_limits='Upstream execution 0. Supporting tests only read at listed ranges. Host behavior, concurrency, complete call graph and Zeus equivalence not validated.',
                 remaining=['Full transitive caller/config/test validation pending','No current execution receipts','Zeus implementation/adoption not approved'],
                 adoption_approved=False)
        files.append(e)
assert len(files)==20 and sum(f['bytes'] for f in files)==154932
assert len(set(f['path'] for f in files))==20
assert len(inventory)==7
save('files.json',files)
missing = [p for p in ['config/runtime.yaml'] if not (SOURCE/p).exists()]
save('remaining.json',dict(
    primary_body_pending=[],
    supporting_unavailable=missing,
    supporting_not_traced=['scripts/engine/tick.py','scripts/cli/hud.py','scripts/engine/rlm_kernel.py','guardian notification delivery consumer','Full paths/ledger/derive_state implementations and host event implementation'],
    unknowns=['Host timeout permissions and child-process cleanup','Windows/Linux/WSL pin parsing, cwd and process lifetime','Concurrent digest/expiry/heartbeat/watermark behavior','Authenticated actor/model qualification and human approval','End-to-end eight-stage SDD verdict and PG runtime SSOT equivalence'],
    tests_executed=[], upstream_execution_count=0,
    blocked_probe_retried=False, whole_analysis_complete=False, adoption_approved=False))
save('checkpoint.json',dict(
    source='harness',revision=manifest['revision'],partitions=[p['partition'] for p in inventory],
    primary_count=20,primary_bytes=154932,primary_body_read_count=20,
    primary_status=STATUS, supporting_count=len(supports),
    supporting_full_body_count=sum(s['body_read_complete'] for s in supports),
    supporting_partial_count=sum(not s['body_read_complete'] for s in supports),
    primary_manifest_sha256_present=sum(bool(f['manifest_sha256']) for f in files),
    supporting_manifest_sha256_absent=[s['path'] for s in supports if not s['manifest_sha256']],
    metadata_validation_correction='An overstrict assertion that every supporting manifest row contained SHA256 failed once; two absent SHA256 fields were confirmed. Computed pinned SHA256 plus matching Git blob and byte length are retained without claiming manifest SHA equality.',
    primary_hashes_and_git_blobs_matched=True, metadata_only_validation=True,
    upstream_execution_count=0,source_edits=0,runtime_edits=0,shared_coverage_edits=0,
    commit_push_count=0,blocked_probe_retried=False,
    bounded_static_review_checkpoint_saved=True,whole_analysis_complete=False,
    adoption_approved=False,stopped_at_bounded_scope=True))
print(json.dumps(dict(primary=len(files),bytes=sum(f['bytes'] for f in files),supporting=len(supports),full=sum(s['body_read_complete'] for s in supports),missing=missing)))

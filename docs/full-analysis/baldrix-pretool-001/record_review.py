"""Inert documentation/hash recorder; no upstream import or execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'
PREFIX = 'docs/full-analysis/baldrix-pretool-001/'
IDS = ['baldrix:scripts/handlers:001', 'baldrix:scripts/handlers/notification:001',
       'baldrix:scripts/handlers/pre_tool:001', 'baldrix:scripts/handlers/tool:001']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['revision'] == 'cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2'
inventory = {r['path']: r for r in manifest['inventory']}
parts = [p for p in json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8')) if p['partition'] in IDS]
assert len(parts) == 4
notes = {}
for block in (OUT / 'notes.md').read_text(encoding='utf-8').split('\n## ')[1:]:
    title, body = block.split('\n', 1)
    if title.startswith('scripts/'):
        notes[title] = body.strip()
assert len(notes) == 16


def identity(path):
    raw = (PINNED / path).read_bytes()
    inv = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert inv['object'] == blob and inv['bytes'] == len(raw)
    expected = inv.get('snapshot_sha256')
    assert expected is None or expected == sha(raw)
    return raw, {
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
        'git_blob': blob, 'pinned_sha256': sha(raw), 'manifest_bytes': inv['bytes'], 'pinned_bytes': len(raw),
        'matches_manifest_git_blob': True, 'matches_manifest_bytes': True,
        'matches_manifest_sha256': None if expected is None else True,
        'manifest_sha256_status': 'absent; fresh SHA, raw Git blob and byte count matched' if expected is None else 'matched',
    }


support_specs = [
    ('settings.json', [(138,223),(228,243),(261,275),(315,333)], 'Windows absolute-path command registrations, tool matchers,5/10sec timeouts. Exact snippets only; full merged/live settings unread.'),
    ('scripts/lib/agent_depth.py', [(1,59)], 'Env inspection helper, invalid/unset reset0, no propagation writer. Full lib-only exact ORCH_DEPTH search found this file only; whole-tree writer closure pending.'),
    ('scripts/lib/webhook.py', [(1,65)], 'POST attempts/retry/backoff/2xx semantics; no delivery acknowledgement,idempotency or global deadline.'),
    ('scripts/lib/hook_io.py', [(1,138)], 'Shared guarded UTF8/schema constructors and malformed-input {}. Claude protocol source claim not externally verified.'),
    ('scripts/handlers/post_tool/agent_outcome_audit.py', [(420,465)], 'Separate-hook env consumption marks decision==invoke as performed; surrounding outcome and ledger closure unread.'),
    ('scripts/lib/guard_patterns.py', [(1,307)], 'Actual policy data and command rewrite lambdas; timeout auto-add doc claim absent. Regex limits and solo early-return interaction examined.'),
    ('scripts/lib/git_flow_override.py', [(1,103)], 'Ancestor six-level policy, two-key solo condition; not Git-root-bound.'),
    ('scripts/lib/critic_policy.py', [(155,210)], 'Resolve override/default and partial mutation function; loader/default lists/remaining token implementation unread.'),
    ('scripts/lib/handoff_drift.py', [(393,440)], 'Advisory fail-open wrapper; render/check transitive bodies unread.'),
    ('scripts/tests/test_on_notification_smoke.py', [(1,57)], 'Full test source: ambient settings/env passed, no-channel assumed rather than enforced; no delivery test.'),
    ('scripts/tests/test_pr_merge_check_guard.py', [(1,220)], 'Classifier copies plus mocked gh JSON; not real check/merge execution. Tail221–223 unread.'),
    ('scripts/tests/test_critic_policy_advisor.py', [(1,148)], 'Stdout decision tests only, no pre→post process/ledger proof. Ambient env copy with CLAUDE_HOME override, not complete isolation.'),
    ('scripts/tests/test_guard_failclosed.py', [(1,137)], 'In-process StringIO/mock selected error-path cases; no actual platform enforcement. Not executed.'),
    ('scripts/tests/test_budget_and_depth.py', [(32,78),(149,211)], 'Env manually injected boundary/deny tests; no nested Agent propagation. Budget body and runner remainder unread.'),
    ('scripts/tests/test_outpos_guard.py', [(1,123)], 'Selected activation/deny/exemption fixtures; inline print exemption case does not exercise anchored print regex.'),
]
support = []
for path, ranges, meaning in support_specs:
    raw, row = identity(path)
    lines = raw.splitlines(keepends=True)
    assert all(1 <= lo <= hi <= len(lines) for lo, hi in ranges)
    row.update({
        'read_extent': 'full' if ranges == [(1,len(lines))] else 'partial',
        'read_ranges': [{'start':lo,'end':hi,'raw_range_sha256':sha(b''.join(lines[lo-1:hi]))} for lo,hi in ranges],
        'meaning': meaning, 'tests_executed': [], 'coverage_promotion': False,
        'remaining': 'Unread ranges and transitive caller/config/test closure remain pending. Static source reading only.',
    })
    support.append(row)
write('supporting-evidence.json', support)

# Prior reviewed support reused explicitly, not represented as fresh body reads.
reuse = [
    ('scripts/lib/paths.py','docs/full-analysis/baldrix-validators-002/supporting-evidence.json', 'Asset/state/telemetry env split and import-time constants; reuse only previously recorded ranges.'),
    ('scripts/lib/telemetry_log.py','docs/full-analysis/baldrix-validators-002/supporting-evidence.json','Append/rotation/fail-open1–86 previously read; timed decorator87+ not newly read, remains transitive gap.'),
]
reused = []
for path, ledger, meaning in reuse:
    earlier = next(r for r in json.loads((ROOT / ledger).read_text(encoding='utf-8')) if r['path'] == path)
    raw, row = identity(path)
    assert earlier['pinned_sha256'] == sha(raw)
    row.update({'prior_ledger': ledger, 'prior_ledger_sha256':sha((ROOT/ledger).read_bytes()), 'reused_read_ranges':earlier['read_ranges'], 'fresh_body_read':False, 'coverage_promotion':False, 'meaning':meaning})
    reused.append(row)
write('reused-support.json', reused)

test_map = {
    'scripts/handlers/pre_tool/guard.py':['scripts/tests/test_guard_failclosed.py'],
    'scripts/handlers/pre_tool/agent_depth_guard.py':['scripts/tests/test_budget_and_depth.py'],
    'scripts/handlers/pre_tool/critic_policy_advisor.py':['scripts/tests/test_critic_policy_advisor.py'],
    'scripts/handlers/pre_tool/outpos_guard.py':['scripts/tests/test_outpos_guard.py'],
    'scripts/handlers/pre_tool/pr_squash_guard.py':['scripts/tests/test_pr_merge_check_guard.py'],
    'scripts/handlers/notification/on_notification.py':['scripts/tests/test_on_notification_smoke.py'],
}
files = []
detail = ['# 파일별 전문 의미 기록\n']
for part in parts:
    for item in part['paths']:
        path = item['path']
        raw, row = identity(path)
        anchor = f'file-{len(files)+1:02d}'
        detail.append(f'<a id="{anchor}"></a>\n\n## {path}\n\n{notes[path]}\n')
        package = path.endswith('__init__.py')
        row.update({
            'partition':part['partition'], 'scope_sha256':part['scope_sha256'],
            'disposition':'semantically_reviewed', 'read_extent':'full',
            'line_count':len(raw.splitlines()), 'read_ranges':[[1,len(raw.splitlines())]],
            'review_ref':PREFIX+'file-reviews.md#'+anchor,
            'semantic_review':notes[path],
            'actual_callability':('Package marker/reexports only; no main hook handler.' if package else 'main entry present; pinned settings direct Python command registrations inspected. Actual Claude runtime dispatch/deny/success receipt unverified.'),
            'caller_config_evidence':PREFIX+'supporting-evidence.json',
            'tests_read_not_run':test_map.get(path, []),
            'tests_executed':[], 'test_limits':'NOT RUN; static-only assignment. Test source and historical claims never establish executed acceptance; full transitive test/config closure pending.',
            'adoption_decision':('No independent behavioral adoption for package marker; imports/reexports separately reviewed.' if package else '원형 권한/인수 게이트 흡수 보류. 제한된 advisory/adapter 발상만 변형 검토; 사용자 승인·모델자격·실행증거와 분리.'),
            'claude_dependencies':'Claude hook payload/permissionDecision/additionalContext/updatedInput, assets/state/env and telemetry dependencies are source DATA; no inherited permissions.',
            'windows_linux':'Pinned settings Windows absolute Python path. Host path semantics, unconditional reconfigure,env propagation,cwd and external git/gh/network noted per file. Windows/Linux/WSL execution0.',
            'zeus_modules':['src/codex_harness/domain/sdd.py','src/codex_harness/application/audit_gate.py','src/codex_harness/adapters/audit_runner.py'],
            'zeus_equivalence':'Architecture mapping only; current Zeus source bodies not newly read. Git definitions/PG runtime identity, authorization/model eligibility and actual immutable receipt are required; no implemented equivalence/adoption claim.',
            'license_status':'Original license, extraction provenance, company conventions, external platform/15x/Cognition claims not verified.',
            'duplicate_status':'Each of16 primary bodies read individually. No generated/duplicate exemption. Supporting fresh/reused records do not promote other primary coverage.',
            'remaining':['Effective merged configuration and complete transitive implementations/callers/tests not read; exact supporting ranges only.','Execution0: platform protocol/real denied tool/network delivery/timeout/branch race/agent lineage and acceptance not verified.','License/external evidence, independent joint exact-revision review and Zeus absorption pending.'],
        })
        files.append(row)
assert len(files) == 16 and sum(r['pinned_bytes'] for r in files) == 68829
(OUT/'file-reviews.md').write_text('\n'.join(detail),encoding='utf-8')
write('files.json',files)
write('checkpoint.json',{
    'partitions':[{'partition':p['partition'],'scope_sha256':p['scope_sha256'],'files':len(p['paths']),'bytes':p['bytes']} for p in parts],
    'source':'baldrix','revision':manifest['revision'],'primary_total':16,'primary_full_body_semantically_reviewed':16,
    'primary_bytes':68829,'primary_remaining':[],'primary_body_review_complete':True,
    'fresh_support_files':len(support),'reused_support_files':len(reused),
    'upstream_executions':0,'tests_executed':[],'probes_executed':0,'partition_complete':False,'repository_complete':False,'adoption_ready':False,
    'files_ref':PREFIX+'files.json','review_ref':PREFIX+'review.md','notes_ref':PREFIX+'notes.md',
    'supporting_ref':PREFIX+'supporting-evidence.json','reused_support_ref':PREFIX+'reused-support.json',
    'remaining':'Transitive/effective config/test closure, all execution, license/external claims, independent joint review and absorption remain unresolved.',
    'manifest_sha256':sha((SOURCE/'manifest.json').read_bytes()),
})
(OUT/'remaining.txt').write_text('Primary full-body unread: 0 / 16.\nPending: transitive caller/config/test closure; upstream execution0; external/license verification; independent joint review and Zeus adoption.\n',encoding='utf-8')
write('artifact-hashes.json',{p.name:sha(p.read_bytes()) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='artifact-hashes.json'})
print(json.dumps({'primary':len(files),'bytes':68829,'fresh_support':len(support),'reused_support':len(reused),'all_primary_manifest_sha_matched':all(r['matches_manifest_sha256'] is True for r in files),'execution':0,'adoption_ready':False}))

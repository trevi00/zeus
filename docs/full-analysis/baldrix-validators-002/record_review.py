"""Inert evidence recorder; no upstream imports, execution, tests or probes."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'
PREFIX = 'docs/full-analysis/baldrix-validators-002/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8'))
inventory = {r['path']: r for r in manifest['inventory']}
partition = next(p for p in json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8'))
                 if p['partition'] == 'baldrix:scripts/validators:002')
assert partition['scope_sha256'] == '52b3115d99350cd64144a35b4b1dc0398ec925bbaf8d24555eba83b42d43743a'
notes = {}
for filename in ['checkpoint-notes.md', 'final-body-notes.md']:
    for name, body in re.findall(r'^- ([a-z_]+): (.+)$', (OUT / filename).read_text(encoding='utf-8'), re.MULTILINE):
        notes[name + '.py'] = {'analysis': body, 'historical_review_ref': PREFIX + filename}

notes['spec_bundle.py']['subsequent_correction'] = (
    'load_bundle 175–205 직접 독해로 parent.parent 경로 산술 자체는 올바름을 확인. '
    '초기 wrong-root 추정 정정: CLAUDE_HOME/spec 한 곳만 찾고 프로젝트 cwd를 발견하지 않는 범위 문제다. '
    'spec_roundtrip의 CLAUDE_HOME/.claude/spec 발견 방식과는 다르다. 원시 checkpoint는 그대로 보존.')
notes['skill_structure_depth.py']['support_update'] = 'lib 전문 1–97: 최소2 content줄/3 bullet. quality_axes는3 ###로 분모 차이; 실행 없음.'
notes['stub_faker_lint.py']['support_update'] = 'lib 194–294: pending Then exempt, 모든 read 실패 빈 report 가능. extract_step_defs/overlay 전이는 미독.'
notes['mock_doc_drift.py']['support_update'] = 'pipeline_gate_runner 1–93: attested_by/docs_sha 무검증 저장, _written은 반환dict만. tests78–144 정적 독해.'
notes['mock_review_skip.py']['support_update'] = 'tests1–126: 임시Git와 직접 JSON marker fixture, unavailableGit SKIP; 사람 인수 실행 아님.'

# Exact support body ranges actually displayed and read; no primary coverage promotion.
supports = [
    ('scripts/lib/staging_guard.py', [(1,83)], 'Runtime resolve/relative_to guard is opt-in SHOULD-call, not automatic write interception.'),
    ('scripts/lib/frontmatter.py', [(1,62)], 'Minimal raw-string parser; YAML lists/quotes unsupported; BOM accepted. Reread, prior validators001 support.'),
    ('scripts/lib/doc_drift_common.py', [(1,57)], 'Shared injectable reader; OSError -> None; Unicode remains exception. Reread prior support.'),
    ('scripts/validators/__init__.py', [(1,123)], 'Prior validators001 primary, reread as support only. Builtins and graduation hooks are not project routing.'),
    ('scripts/lib/pipeline_gate_runner.py', [(1,93)], 'Advisory caller-supplied marker emitter; no execution/probe. Earlier CLI primary overlap, not promoted.'),
    ('scripts/lib/spec_bundle.py', [(85,205)], 'Fail-soft feature parser and project/.claude/spec loader; correction to initial root inference.'),
    ('scripts/lib/testgen.py', [(289,305)], 'ID-set arithmetic only; empty spec metric0, not execution coverage.'),
    ('scripts/lib/stub_faker_lint.py', [(194,312)], 'Framework glob, pending exemption, string tokens, overlay fallback and read skips; extraction transitive body pending.'),
    ('scripts/cli/validate_project.py', [(40,175)], 'Prior CLI primary, reread support only. Four current-primary names in13 routing, stdoutFAIL consumer discards main return.'),
    ('scripts/tests/test_skill_staging_isolation.py', [(1,173)], 'Failures print tokens without raising; named-root synthetic checks do not test traversal/parent/absolute-path guard.'),
    ('scripts/tests/test_subprocess_decode_guard.py', [(1,112)], 'AST fixtures and live-tree scan assertions; no real cp949 child run in read cases. List after112/runner not read.'),
    ('scripts/tests/test_mock_review_skip.py', [(1,126)], 'Temp Git fixture+synthetic attestation; unavailable Git skip; no identity/freshness/actual human acceptance.'),
    ('scripts/tests/test_mock_doc_drift.py', [(78,144)], 'Changed PRD clears and no-marker clean tests. Fixture helpers1–77 and assertion continuation145+ not read.'),
    ('scripts/tests/test_spec_roundtrip.py', [(1,114)], 'Feature-only copy expected100%; no steps/assertion/execution proof. No-bundle/scaffold clean oracle explicit.'),
    ('scripts/tests/test_producer_consumer_coherence.py', [(1,156)], 'Synthetic roots and HIGH0 assertion, import globals changed; no production wiring execution. Runner remainder unread.'),
    ('scripts/lib/graduation.py', [(50,76),(199,224),(408,440)], 'Only two TRACKED names, graduate rejects others: subprocess_decode guard blocking unreachable via normal API.'),
    ('scripts/lib/skill_candidate_detector.py', [(184,211),(540,623)], 'Read write sites have no staging guard; session slug sanitizes but candidate cid origin closure unread. Partial support only.'),
    ('scripts/lib/paths.py', [(1,21),(61,78),(144,158),(178,201),(231,257)], 'Asset/state/telemetry env split and import-time constants. Source comments are historical claims, not our receipts.'),
    ('scripts/lib/telemetry_log.py', [(1,86)], 'Append/rotate and stderr failure paths; no immutable PG authority. Decorator later body not read.'),
    ('scripts/lib/skill_structure_depth.py', [(1,97)], 'Minimumcontent2 and bullets3; shares constants but different Gotchas predicate from quality_axes.'),
]
support_rows = []
for path, ranges, meaning in supports:
    raw = (PINNED / path).read_bytes()
    lines = raw.splitlines(keepends=True)
    row = inventory.get(path, {})
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert not row or (row['bytes'] == len(raw) and row['object'] == blob)
    expected = row.get('snapshot_sha256')
    assert expected is None or expected == sha(raw)
    support_rows.append({
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
        'pinned_sha256': sha(raw), 'git_blob': blob, 'bytes': len(raw),
        'matches_manifest_sha256': None if expected is None else True,
        'matches_manifest_git_blob': bool(row), 'manifest_sha256_status': 'absent; newly computed SHA with blob/bytes check' if expected is None else 'matched',
        'read_extent': 'full' if ranges == [(1,len(lines))] else 'partial',
        'read_ranges': [{'start': lo, 'end': hi, 'raw_range_sha256': sha(b''.join(lines[lo-1:hi]))} for lo,hi in ranges],
        'meaning': meaning, 'tests_executed': [], 'coverage_promotion': False,
        'remaining': 'Unread body outside listed ranges and transitive imports/callers/config; no execution or adoption authority.',
    })
write('supporting-evidence.json', support_rows)

test_links = {
    'mock_review_skip.py': ['scripts/tests/test_mock_review_skip.py'],
    'mock_doc_drift.py': ['scripts/tests/test_mock_doc_drift.py'],
    'skill_staging_isolation.py': ['scripts/tests/test_skill_staging_isolation.py'],
    'subprocess_decode_guard.py': ['scripts/tests/test_subprocess_decode_guard.py'],
    'spec_roundtrip.py': ['scripts/tests/test_spec_roundtrip.py'],
    'producer_consumer_coherence.py': ['scripts/tests/test_producer_consumer_coherence.py'],
}
declined = {'skill_source_liveness.py', 'skill_quality_axes.py', 'skill_staging_isolation.py', 'producer_consumer_coherence.py'}
files = []
for item in partition['paths']:
    path = item['path']
    name = Path(path).name
    raw = (PINNED / path).read_bytes()
    row = inventory[path]
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    expected = row.get('snapshot_sha256')
    assert row['bytes'] == len(raw) and row['object'] == blob
    assert expected is None or expected == sha(raw)
    note = notes[name]
    note['tests_read_not_run'] = test_links.get(name, [])
    note['direct_support'] = PREFIX + 'supporting-evidence.json'
    files.append({
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'], 'git_blob': blob,
        'pinned_sha256': sha(raw), 'manifest_bytes': row['bytes'], 'pinned_bytes': len(raw),
        'matches_manifest_sha256': None if expected is None else True,
        'matches_manifest_bytes': True, 'matches_manifest_git_blob': True,
        'manifest_sha256_status': 'matched' if expected is not None else 'absent; raw blob+bytes matched, SHA freshly computed',
        'read_extent': 'full', 'read_ranges': [[1,len(raw.splitlines())]], 'line_count': len(raw.splitlines()),
        'disposition': 'semantically_reviewed', 'review_ref': PREFIX + 'semantic-notes.json#' + name,
        'semantic_review': note,
        'actual_callability': 'main entry present; registry and CLI support trace distinguish registration from actual routing. Effective live dispatch not verified.',
        'adoption_decision': ('권한/품질/신뢰 게이트로 원형 채택 제외; 제한된 발견 힌트로 재설계 검토.' if name in declined else '변형 검토 후보: 휴리스틱 결과와 skipped/unverifiable/실제 인수 분리; 현재 승인 보류.'),
        'claude_dependencies': 'Source instruction text is DATA. CLAUDE asset/state/telemetry paths, registry and mutation tokens are not Zeus authority. Specific dependencies and side effects in analysis.',
        'windows_linux': '파일별 encoding/BOM/cwd/env/Git/path 비교 참조. Windows/Linux/WSL 실행0; source-relative, env-derived and Path.home roots require separate isolation.',
        'zeus_modules': ['src/codex_harness/domain/sdd.py','src/codex_harness/application/audit_gate.py','src/codex_harness/adapters/source_verification.py','src/codex_harness/adapters/audit_runner.py'],
        'zeus_equivalence': 'Architecture mapping only; current Zeus bodies not newly reviewed. Git definitions/PG runtime authority/immutable actual execution and no mocked acceptance required; no equivalence claim.',
        'tests_executed': [], 'test_limits': 'NOT RUN by assigned static-only scope. Six supporting test files read at exact ranges; all other test body/config trace pending. Past source PASS is not this review execution.',
        'license_status': 'Original license, attribution for ports, linked standards/URLs/debates not verified. No external fetch.',
        'duplicate_status': 'Every primary body individually read; no generated/byte-equivalent exemption. spec_bundle previously support-reviewed and reread here. Supporting prior primary rows not promoted.',
        'remaining': ['Unreviewed direct/transitive caller/config/test ranges remain explicit; supporting ledger is not full closure.', 'Execution0: malformed/empty/skip/encoding/platform/authority/acceptance cases not run.', 'License/external claims, independent joint exact-revision review and adoption approval pending.'],
    })
assert len(files) == len(notes) == 24
assert sum(f['pinned_bytes'] for f in files) == partition['bytes'] == 154041
write('semantic-notes.json', notes)
write('files.json', files)
write('checkpoint.json', {
    'partition': partition['partition'], 'scope_sha256': partition['scope_sha256'],
    'source': 'baldrix', 'revision': manifest['revision'], 'primary_total': 24,
    'primary_full_body_semantically_reviewed': 24, 'primary_bytes': 154041,
    'primary_remaining': [], 'primary_body_review_complete': True,
    'supporting_files_with_read_ranges': len(support_rows), 'upstream_executions': 0, 'tests_executed': [], 'probes_executed': 0,
    'partition_complete': False, 'repository_complete': False, 'adoption_ready': False,
    'limits': 'Bounded body review done; transitive/effective config/test closure, execution, license, joint approval unresolved. No denied probe retry or bypass.',
    'historical_checkpoint_ref': PREFIX + 'checkpoint-notes.md',
    'review_ref': PREFIX + 'review.md', 'files_ref': PREFIX + 'files.json',
    'notes_ref': PREFIX + 'final-body-notes.md', 'supporting_ref': PREFIX + 'supporting-evidence.json',
    'manifest_sha256': sha((SOURCE / 'manifest.json').read_bytes()),
})
(OUT / 'remaining.txt').write_text('Primary full-body unread files: 0 / 24.\nRemaining: transitive caller/config/test closure; executions (0); original license and external evidence; exact-revision joint review and adoption approval.\n', encoding='utf-8')
write('artifact-hashes.json', {p.name: sha(p.read_bytes()) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'artifact-hashes.json'})
print(json.dumps({'primary_full_body_reviewed':len(files), 'bytes':sum(f['pinned_bytes'] for f in files), 'supporting_files':len(support_rows), 'all_primary_manifest_sha_matched':all(f['matches_manifest_sha256'] is True for f in files), 'tests_executed':0,'partition_complete':False}))

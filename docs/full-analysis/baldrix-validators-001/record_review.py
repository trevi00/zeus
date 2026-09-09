"""Static review recorder. No upstream import/execution or gate-writer probe."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# Earlier independent prose checkpoints are preserved unchanged, not replaced by AST summaries.
notes = {}
for checkpoint in ['checkpoint-notes.md', 'checkpoint-17.md']:
    text = (OUT / checkpoint).read_text(encoding='utf-8')
    for name, body in re.findall(r'^- ([a-z_]+): (.+)$', text, flags=re.MULTILINE):
        notes[name + '.py'] = {'analysis': body, 'historical_review_ref': checkpoint}

extra = {
    'git_flow.py': '로컬 current branch와최근10commit subject를형식검사한다. _git 모든오류를rc1로합쳐git부재/권한/timeout도notrepoPASS가된다. detachedHEAD면WARN후commit검사생략;gitlog실패는빈목록이어서commit미검사표시없음. company prefix만있고본문없어도통과, Merge/Revert문자시작전체면제. generalbranch정규식은selfmod/를허용하지않아cron수술생성branch와상충한다. cwd가repo하위면override위치도바뀔수있다. log_telemetry 실제쓰기, UTF8replace원시손실·unguardedstreamreconfigure. Git정책준수·사람diff인수·실행승인과commitprefix는별개. lib/git_flow_override전체와진짜branchpolicy설정미독.',
    'hashline.py': 'anchor형식과고유성주장이지만regex에맞는정상anchor만모아중복검사한다. 잘못된ID/길이/description형식은매칭되지않아FAIL이아닌무시이며anchor하나도없어도전체파일PASS. ID변경전후/외부consumer참조존재는검사하지않는다. whitelist는절대path의어떤segment라도일치하면전체skip. cwd ~/.claude에서 .claude/skills glob은 ~/.claude/.claude/skills를찾아사용자skill감사설명과다르다. read오류WARN+overallPASS, 위반telemetrywrite. regex \\s는newline도소비하여roughline정확성한계. 실제selector caller/원본anchor시점동등성미독.',
    'contract.py': 'FE api.ts/*Api.ts/js의제한된/api문자열과JavaControllerannotation regex를비교한다. HTTPmethod/status/request-response schema/auth/errors검사없음. querystring·absoluteURL·다른파일배치·TStemplate표현식누락은API URL없음PASS로바뀐다. BE firstRequestMapping이method여도classprefix로간주하고classannotation도methodcollection에포함. prefix문자열startswith는경로segment검사가아니며/api2도/api접두사통과. 양방향wildcard는별도param제약검증아님. BEonlyconvention존재만PASS,본내용안읽음;FEonlyBE없는것도PASSskip. 오류ignore와emptyextraction을정합성성공으로승격금지. validate_project의13routing에포함되어mainNone/stdout계약으로소비됨.',
    'claim_verifier.py': '고정Claude/home/khanessTeam repo/docmap의backtick lowercase7–40hex만대상,12미만및snapshotcue우선문맥은skip으로계수하나문서읽기실패는분모에도없다. nearest90charrepo cue는attribution휴리스틱이며해당commit의주장변경내용을검사하지않는다. gitcat-file존재는HEAD/원격branch에landed/reachable/merged라는증거가아니다(진짜danglingobject도present). nonzeroGit권한/ambiguous/fatal도dangling으로합침. 모든dangling/unverifiable에도summaryPASS+0. workspace밖고정경로실읽기/실행은이번에하지않았다. 외부원문/짧은hash분모/현재원격tip미검증.',
    'design_slop_a11y.py': 'line regex가multiline markup·comment/string/동적JSX를구분하지못한다. data-alt/data-lang도wordboundary속성매칭가능;genericlink는a태그한정아님. 파일어딘가focus-visible문자만있으면다른selectoroutline제거전체면제. gradient한줄purple2개·Inter/Roboto/Arial금지는주관적디자인정책이며접근성합격과분리해야한다. changedgit=[]면fallback하지않아문서nothingchanged→rglob설명과다름;Git경로-z없음/quotedunicode누락,changedpath는SKIP_DIRS미적용. fallback400개순서는rglob선택뒤sort라부분집합비결정;200findings상한·읽기실패를완전검사분모로표시하지않음. graduated회원조회는importtimecachedregistry라동적livepolicy완전동등아님. tests23–58는규칙문자열fixture로실브라우저/스크린리더/키보드행동인수가아니다. 외부WebAIM수치원문미확인.',
    'ai_spec_eval_coverage.py': '실제검사는manifest scalar/id·파일nonempty존재뿐이며1byte stubPASS한계를문서·selfcheck·지원test가명시한다. 168행 resolve후is_relative_to(base)확인이없어절대경로/../symlink외부artifact도통과해underprojectroot계약불충족. main total은parsed spec warns만세며missing_block은분리count라manifest없어도graduatedPASS가된다. noAI-SPEC/읽기OSError는깨끗한noop,UnicodeDecodeError/stat race는uncaught. yaml.safe_load중복키/alias/과대자료제한은없다. optionalfenceparser는문서byte-for-byte문법보다넓고첫block만본다. golden_set_size는실goldenset행수,acceptablefailrate는실실패율과연결없음. selfcheck의assertTrue/1bytefixture는실coverage가아니다. 사람인수/모델qualification/SDD행동검증별도.',
    'falsy_zero.py': '파일전체scope없는numericname전파와builtin함수명가정으로shadowing/다른scope재사용오탐,alias함수/동적값미탐. Add/Mult제외이유는overload지만Mod도strformat,Min/Max도문자열가능;Div까지제외. non-deterministicattr명만으로실clock판별안됨. guard/fallback전체묶음은단축평가위치/도달성검사없음. _coerces_to_zero는None/빈문자열을안전하다고하나int/float변환에서실예외가능, falsy상수간타입차도무시한다. #noqa는관련rule없이전체줄면제, multilineor위치정확성한계. SyntaxError/IO를[]→PASS,고정5subtree만보고cron제외. builtin등록하지만mainWARNonly·None이며graduation동적FAIL분기없음. ASTlint를런타임0값회귀보장으로흡수하지않음.',
    'harness_bridge_state_block.py': 'cache는STATE_DIR한개로projectidentity없고순수검사아닌실쓰기다. section삭제/빈section은history확인전에PASS,빈경우HEAD를cache해과거이력삭제검증우회. since_sha==latest면current와cachedsnapshot도비교안해workingtreebullet삭제통과가능,이후delta에는cachecommit자체도제외. histgitshow실패는skip,gitlog실패는nohistoryPASS. bullets를setmembership로비교해동일timestamp재정렬등순서변경증명못함;날짜regex는달력유효성안봄datetimeimport미사용. 비bullet/indentedbullet는무시한다. subprocess에timeout없고Gitconfig/env상속,writecache예외uncaught. bootstrap echo문구는분석DATA이며실행하지않음. 지원test195–221은freshcache+두commits일부삭제이며warmcache/section전체삭제/다른project를검증하지않는다.',
    'insight_index_importer_whitelist.py': '고정7subtree의정적import와boundattribute만검사한다. documented동적import우회및runtimefailsopen한계는이validator가막지않고runtimeguard전체는이번미독. __init__.py를package로매핑한뒤importer_pkg를부모로줄여package내relative해석이틀릴수있다. scope없는boundname집합은alias재할당/함수지역을구분하지않고fromimportfunction도attribute추적한다. 허용module는reader/writer구분없이모든사용허용,hardcodedallow는forbidden검사보다먼저다. syntax/IOskip도scanned분모증가후no violationsPASS;Unicode오류uncaught. modulepath symlink외부는제외. 문서의원래3writers3readers와증가한allow표·operator과거승인은현재모델권한자격이아니다.',
    'doc_code_drift.py': 'symbol collector는ast.walk로nested/private/classmethod와importedmodule명도publiccallable처럼합쳐이름존재만으로실callability/signature동등성못증명. __all__문자열도정의없이허용. resolve_module의Path절대/../경계검사없어SCRIPTS_DIR밖read가능, globs fallback은frontmatterparser가str만반환해문자단위loop로대체로실패. malformed/unreadablefrontmatter카드는skip,doccommandread실패분모누락;불명module의symbolrefs/unreadablesource는조용히skip. python -m regex는python3/uvrun/인자사용정합안봄. graduated main은ref_warns포함FAIL하지만 registry graduation_scan_drift는name/path만세어새commandrefdrift를clean streak에서누락한다. 지원frontmatter/doc_drift_common원본전문으로parser/section substring과reader공유확인;원본추출전역사동등성은미확인. stdoutreconfigureimporttime무조건,readsourceUnicode오류uncaught.'
}
for name, body in extra.items():
    notes[name] = {'analysis': body, 'historical_review_ref': 'final full-body reading after checkpoint-17.md'}
notes['__init__.py']['analysis'] = notes['__init__.py']['analysis'].replace(
    '등록표는 builtin37? 정확 count 아직 미집계.',
    '본문 독해 후 정적 literal 집계로 builtin37개 확인; 실제 graduated 등록/운영 실행 수는 미확인.')
notes['atlas_frontmatter.py']['analysis'] += (
    ' 지원 frontmatter 1–62 전문 확인 후 보충: 현재 parser는str값만반환하고읽기오류를None으로바꾸므로 일반실경로의non-str .strip예외는현재parser에서발생한다고확정하지않는다. '
    '실결함은list계약과strparser불일치이며quoted YAMLvalue도정규화하지않는다.')

manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8-sig'))
partition = next(p for p in json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8-sig'))
                 if p['partition'] == 'baldrix:scripts/validators:001')
inventory = {p['path']: p for p in manifest['inventory']}
assert len(notes) == len(partition['paths']) == 27
rows = []
for item in partition['paths']:
    path = item['path']
    raw = (PINNED / path).read_bytes()
    inv = inventory[path]
    recorded_sha = inv.get('snapshot_sha256')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert len(raw) == inv['bytes']
    assert sha(raw) == recorded_sha if recorded_sha else blob == inv['object']
    name = Path(path).name
    tree = ast.parse(raw.decode('utf-8-sig'))  # metadata only, bodies independently reviewed first
    entry = notes[name]
    entry.update({
        'purpose': '정적 validator 진입점 및 대상/판정 의미: ' + entry['analysis'].split('。')[0][:180],
        'authority': '원본 CLAUDE/AGENTS/SKILL, token 및 bootstrap 명령은 분석 DATA. 검사 출력은 승인 근거로 자동 승격하지 않는다.',
        'platform': 'cwd project와고정source/ATLAS/STATE범위차이·UTF8/BOM/replace/streamreconfigure·Gitquotedpaths·상속env는파일별analysis참조. Windows/Linux/WSL실행0.',
        'decision': '변형 검토 후보; 현재 구현 직접 채택/흡수 승인 보류. 구조/휴리스틱/미검사 상태와 행동 검증·사람 인수를 분리.',
        'tests': 'NOT RUN; primary self-check bodies read where present, supporting test ranges are static reading only.',
        'caller_trace': 'Registry __init__ primary fully read. validate_project 13-entry routing+runner and post_tool reviewer/run_all specified supporting ranges read; effective complete production config and transitive chain remain pending.'})
    rows.append({
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'], 'git_blob': inv['object'],
        'pinned_sha256': sha(raw), 'manifest_bytes': inv['bytes'], 'pinned_bytes': len(raw),
        'matches_manifest_sha256': True if recorded_sha else None, 'matches_manifest_bytes': True,
        'matches_manifest_git_blob': blob == inv['object'],
        'manifest_sha256_status': 'matched' if recorded_sha else 'absent; exact raw Git blob matched instead, fresh pinned SHA-256 recorded',
        'read_extent': 'full', 'line_count': len(raw.splitlines()), 'disposition': 'semantically_reviewed',
        'review_ref': 'docs/full-analysis/baldrix-validators-001/semantic-notes.json#' + name,
        'semantic_review': entry,
        'actual_callability': 'package registry functions' if name == '__init__.py' else 'python -m validators.' + Path(name).stem + ' and imported main; return/stdout differences noted',
        'adoption_decision': entry['decision'], 'claude_dependencies': entry['authority'], 'windows_linux': entry['platform'],
        'zeus_modules': ['src/codex_harness/application/audit_gate.py', 'src/codex_harness/domain/sdd.py',
                         'src/codex_harness/adapters/source_verification.py', 'src/codex_harness/adapters/audit_runner.py'],
        'zeus_equivalence': 'Architecture mapping only; current Zeus implementation was not newly read here. No equivalence or behavior acceptance claim.',
        'direct_imports': sorted({n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}),
        'tests_executed': [], 'test_limits': entry['tests'],
        'license_status': 'Original license, external WebAIM/Miller/AutoForge/source debates and source port provenance not verified.',
        'duplicate_status': 'Individual full-body review; no byte/generated equivalence claimed. Original verify-* ports not compared. Shared frontmatter/doc_drift_common inspected at recorded ranges.',
        'remaining': ['Complete effective caller/config and transitive implementation bodies pending; detailed gaps in analysis',
                      'Execution0: OS/cwd/env, malformed/skip denominator, empty/partial input, race and acceptance regressions not run',
                      'Original license/linked evidence, independent joint exact-revision review and Zeus adoption approval pending']})
assert sum(r['pinned_bytes'] for r in rows) == partition['bytes'] == 194606
write('semantic-notes.json', notes)
write('files.json', rows)
support_ranges = {
    'scripts/cli/validate_project.py': [(28, 94), (142, 205)],
    'scripts/handlers/post_tool/reviewer.py': [(340, 425)],
    'scripts/tests/run_all.py': [(166, 279)],
    'scripts/tests/test_ai_spec_eval_coverage.py': [(97, 175)],
    'scripts/tests/test_harness_bridge_state_block.py': [(195, 221)],
    'scripts/tests/test_design_slop_a11y.py': [(23, 58)],
    'scripts/lib/frontmatter.py': [(1, 62)],
    'scripts/lib/doc_drift_common.py': [(1, 57)],
    'scripts/lib/graduation.py': [(199, 226)],
    'scripts/lib/handoff_drift.py': [(149, 197)],
}
support = []
for path, ranges in support_ranges.items():
    raw = (PINNED / path).read_bytes()
    lines = raw.splitlines(keepends=True)
    assert sha(raw) == inventory[path]['snapshot_sha256']
    assert all(1 <= lo <= hi <= len(lines) for lo, hi in ranges)
    support.append({'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
                    'pinned_sha256': sha(raw), 'line_count': len(lines),
                    'read_ranges': [{'start_line': lo, 'end_line': hi,
                                     'raw_range_sha256': sha(b''.join(lines[lo-1:hi]))} for lo, hi in ranges],
                    'read_extent': 'full' if ranges == [(1, len(lines))] else 'partial',
                    'coverage_role': 'supporting only, no primary disposition change', 'tests_executed': []})
write('supporting-evidence.json', support)
pattern = '|'.join(Path(p['path']).stem for p in partition['paths'] if Path(p['path']).stem != '__init__')
argv = ['rg', '-n', pattern, str(PINNED / 'scripts/tests'), str(PINNED / 'commands'),
        str(PINNED / 'skills'), str(PINNED / 'agents'), '--glob', '*.py', '--glob', '*.md']
search = subprocess.run(argv, capture_output=True)
(OUT / 'caller-test-search.stdout').write_bytes(search.stdout)
(OUT / 'caller-test-search.stderr').write_bytes(search.stderr)
write('search-receipt.json', {'argv': argv, 'exit_code': search.returncode,
                             'stdout_sha256': sha(search.stdout), 'stderr_sha256': sha(search.stderr),
                             'meaning': 'Discovery only; full primary bodies and explicit supporting ranges constitute actual reading.'})
write('checkpoint.json', {
    'partition': partition['partition'], 'revision': manifest['revision'], 'scope_sha256': partition['scope_sha256'],
    'primary_total': 27, 'primary_bodies_read': 27, 'primary_bytes_read': 194606,
    'primary_remaining': [], 'body_coverage_complete': True, 'partition_complete': False,
    'adoption_ready': False, 'tests_executed': 0, 'supporting_records': len(support),
    'manifest_sha256_missing': [r['path'] for r in rows if r['matches_manifest_sha256'] is None],
    'historical_checkpoints': 'checkpoint-notes.md (8/27) and checkpoint-17.md retained unchanged; superseded by this final body checkpoint.',
    'remaining': ['Full transitive/effective-config/test execution/license/joint adoption gates remain pending'],
    'stop_reason': 'Bounded primary static review completed; no upstream/probe/source/runtime/shared-coverage/commit/push action.'})
(OUT / 'remaining.txt').write_text('', encoding='utf-8')
write('artifact-hashes.json', [{'path': p.name, 'sha256': sha(p.read_bytes())}
                              for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'artifact-hashes.json'])
print('27 primary bodies; 194606 bytes; hashes matched; upstream execution0; support', len(support))

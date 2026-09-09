# Atlas validator 문서 전수 의미 검토

38개는 모두 이번 전문 독해다. 코드 카드 28개는 동일 형식을 쓰지만 서로 다른 주장과 대상이 있어 생성/중복으로 면제하지 않았다. 생성 프로그램·원시 토론 이벤트·당시 실행 영수증을 확인하지 않았으며 last_writer/날짜/LOCK/PASS는 문서의 역사 주장이다. 기존 구현 전문은 supporting-reuse.json에 원시 blob/SHA, 원래 원장 행·리뷰 해시·전문 범위로 결속했다. 새 직접 지원 구간은 supporting-evidence.json에 따로 기록한다. 아래 모든 항목의 실행·import·collection·probe·network·Claude는 0, 전체 전이/라이선스/OS/모델 자격/사람 인수/Zeus 채택은 미완료다.

공통 카드의 main()->None, cwd, never raises, stdout-only, 등록이면 실제 검증된다는 계약은 구현별로 다르다. registry는 예외를 막지 않고 반환값을 버린다. Atlas는 cwd 대신 자산 루트이고 일부 검사는 cache·telemetry를 쓴다. 구조·정규식·파일 존재는 사용자의 8단계 SDD나 사람 핵심 시나리오의 실행 증거가 아니다. Zeus에서 Git은 승인된 정의, PG는 실행 시도·분모·증거·자격·인수의 정본이어야 한다.

<a id="file-01"></a>
## 01 README.md

MOC는 concept/decision/artifact/journal을 분류하고 28카드·27등록·1advisory, Layer-A25/Layer-B2/AB1이라는 역사 snapshot을 제시한다. 새 registry 전문 1–123행은 builtin37개와 graduated append를 보여 주며 알파벳 정렬도 유지되지 않는다. bridge-state와 source-liveness를 ModuleSpec runtime guard로 분류한 것은 각각 상태 기록 검사와 HTTP 확인이라는 실제 역할과 다르다. 문서 링크는 탐색에 유용하지만 목록 존재를 전수 실행이나 release gate로 승격할 수 없다. 현재 배포 등록·effective graduated 상태·원시 생성 근거는 미확인이다.

<a id="file-02"></a>
## 02 artifacts/atlas-frontmatter.md

8필수 키·enum·날짜·glob 조건을 설명하며 glob activation으로 Python 파일 변경에 관련 문서를 노출하려는 카드다. 이전 atlas_frontmatter 전문은 실제 고정 ATLAS_DIR, 문자열 parser, globs list 미강제, 날짜 regex/중복 ID 미검사를 확인했다. 이번 test_atlas_frontmatter 전문의 6개 함수는 합성 파일의 누락/enum/id/glob 규칙을 검사하며 실제 vault 전수·적절성은 아니다. 새 paths/atlas_index는 자산 루트와 parse 실패 제외를 보여 준다. Zeus에는 typed 정의 lint를 변형하되 unknown/읽기 실패와 실제 검사 분모를 분리해야 한다.

<a id="file-03"></a>
## 03 artifacts/atlas-structure.md

깊이·디렉터리 용량·도메인 registry를 설명한다. 이전 구현 전문에서 registry 없음/읽기 실패/빈 파싱은 정합 검사 생략이고 md파일만 용량 분모이며 directory component 깊이와 문서의 file 포함 예시가 다르다. 기본 depth 상수 일부도 미사용이다. capacity30/50 기준을 외부 표준이나 효과 측정으로 확인하지 않았다. Zeus topology 정의의 구조 lint 후보지만 구조 통과가 의미 연결·모델 자격·사용자 인수를 증명하지 않는다. 실제 vault/파일시스템 오류·OS별 경로 검증은 미실행이다.

<a id="file-04"></a>
## 04 artifacts/ci.md

트리거·job dependency·환경변수 cross-check를 약속하지만 이전 ci.py 전문은 YAML parsing 없이 push/pull_request/test/tool 단어를 찾고 workflow 부재를 PASS로 처리한다. 주석 단어도 검증 문구를 만들 수 있고 uv-only 설정은 누락 가능하다. 이번 실제 .github/workflows/ci.yml은 path filter·ubuntu만·atlas skip 허용을 명시한다. 따라서 CI 카드의 설명은 실제 runner/권한/환경 동등성을 과장한다. Zeus에서는 Git workflow 정의와 PG 실제 CI run/exit/skip을 연결해야 한다.

<a id="file-05"></a>
## 05 artifacts/codegen.md

설계의 필드·시그니처·endpoint 위반을 검증한다는 카드다. 이전 codegen.py는 Java 이름 관례, DI/Mapper XML 정규식, endpoint 개수 비율을 비교하고 Java src 없음은 PASS다. FQCN 동명 충돌·annotation mapper와 endpoint 분모 차이가 남는다. 이번 validate_project ROUTING은 Java backend에만 codegen을 배치한다. 8–9 stage라는 원문 번호는 Zeus 8단계와 동등하지 않다. 실제 compile·행동·요구 coverage를 별도 영수증으로 요구해야 한다.

<a id="file-06"></a>
## 06 artifacts/collab.md

HANDOFF/SUMMARY 최소 존재·drift를 주장하지만 실제 이전 collab.py는 .github/workflow, CODEOWNERS, PR template, CONTRIBUTING의 위치/존재를 주로 본다. .github가 없으면 PASS이고 HANDOFF 계약과 다른 대상을 검사한다. import 시 stream reconfigure도 never-raises와 다를 수 있다. 협업 파일은 사람 검수나 branch protection 실행 증거가 아니다. Zeus는 역할·책임·승인자를 PG에 결속하고 template 존재를 부가 lint로만 취급해야 한다.

<a id="file-07"></a>
## 07 artifacts/commit-layer-adjacency.md

lib→handlers→engine→validators 단방향 의존을 commit 단위로 강제한다는 설명이다. 이전 구현은 staged 경로를 얻고 index blob 대신 working file을 읽으며 no-staged에서는 마지막 commit 범위로 바뀐다. relative import·복수 alias·dynamic import·syntax/읽기 실패 누락도 있다. 따라서 정확한 commit의 전체 의존 그래프가 아니다. Zeus의 hexagonal 경계 후보에는 Git 대상 blob·삭제파일·미파싱 분모를 고정하고 PG 검사 receipt를 남겨야 한다. 실제 Git/비ASCII 경로 시험은 미실행이다.

<a id="file-08"></a>
## 08 artifacts/contract.md

OpenAPI↔FE type↔BE 시그니처 및 request/response schema를 설명한다. 이전 contract.py는 제한된 FE /api 문자열과 Java Controller annotation 정규식을 비교하며 HTTP method/status/schema/auth를 검사하지 않는다. 없거나 파싱되지 않은 API를 skip/PASS로 바꾸고 문자열 prefix는 경로 segment 경계가 아니다. 이번 validate_project는 root와 Java backend에 중복 배치할 수 있다. Zeus 계약 검사는 versioned schema와 실제 요청·응답·오류 시나리오로 이어져야 하며 이 카드는 인수 게이트로 채택하지 않는다.

<a id="file-09"></a>
## 09 artifacts/convention.md

.claude/conventions.md 기반 naming/directory/import 정책이라는 설명과 달리 이전 구현은 특정 convention 문서의 pipe행·package segment·DTO/error 단어를 휴리스틱으로 읽는다. 없는 문서/Java는 PASS이고 많은 package mismatch는 경고 제한 때문에 숨겨질 수 있다. 규칙의 문자열 존재와 실제 적용은 다르다. Zeus는 Git의 typed 정책과 PG 검사 대상 revision을 결속해야 한다. 일반 Python/TS 프로젝트 동등성, 실제 정책·모델 승인 검사는 미완료다.

<a id="file-10"></a>
## 10 artifacts/ddl.md

SQL과 논리 설계의 테이블/컬럼/FK/index 정합을 약속한다. 이전 ddl.py는 제한된 SQL glob·CREATE 정규식·PK/ENGINE/CHARSET 토큰과 heading 집합을 본다. PostgreSQL quoted/schema-qualified 이름·migration 하위·컬럼 타입/FK 의미를 충분히 검사하지 않으며 MySQL ENGINE/CHARSET 강제는 Zeus PG 정본에 맞지 않는다. 파일 존재나 SQL 텍스트는 DB 적용 receipt가 아니다. dialect별 정의 검증과 실제 격리 migration/rollback 관측을 별도 설계해야 한다.

<a id="file-11"></a>
## 11 artifacts/er.md

Mermaid 문법·orphan entity·cardinality 검증이라고 설명한다. 이전 er.py는 첫 문서의 heading/entity/관계 단어·Mermaid 제목 유무를 검사해 실제 parser/render/참조 해석과 다르다. 임의 heading이 entity 분모가 될 수 있다. Zeus에서는 entity/relationship ID를 Git 정의로 파싱하고 PG 결과를 기록해야 한다. 의미·사용자 도메인 적합성·렌더링은 미검증이며 그림 문법 발견을 모델 평가로 쓰지 않는다.

<a id="file-12"></a>
## 12 artifacts/flow.md

flow가 PRD US/AC를 빠짐없이 담는지 FAIL로 검증한다고 주장한다. 이전 flow.py는 Mermaid fence prefix와 US 문자열 포함을 보며 US-1이 US-10에 부분 일치하고 누락은 WARN이다. 디렉터리 부재는 PASS이며 문법/render나 실제 상태 전이가 아니다. Zeus는 요구 ID와 경로·실행 시나리오를 명시 매핑하고 사용자 인수 결과를 PG에 유지해야 한다. 원문 flowchart 의도는 후보 설계이며 현재 실행 검증으로 승격하지 않는다.

<a id="file-13"></a>
## 13 artifacts/git-flow.md

branch pattern/Conventional Commit lint 카드다. 이전 git_flow.py는 현재 branch와 최근10 subject만 보고 Git 오류를 not-repo PASS로 합칠 수 있으며 detached HEAD는 이후 검사도 생략한다. Merge/Revert 면제와 source selfmod branch 생성 규칙의 상충을 보존한다. telemetry 쓰기가 있어 순수 AST 검사도 아니다. Zeus에서는 정확한 Git 정의 revision·검사 분모·실패 원인을 기록하되 prefix가 diff 검수·실행 승인·사람 인수를 대신하지 않도록 해야 한다.

<a id="file-14"></a>
## 14 artifacts/handoff-drift.md

HANDOFF phase block과 phase-tree의 byte-equivalent 감시를 설명한다. 이전 handoff_drift 전문은 anchor/format/파일 부재 PASS opt-out, import/render 실패 WARN·skip과 CurrentPhaseBlock 외 범위 미검사를 확인했다. 일부 helper 실패가 빈 결과로 사라진다. 카드는 byte 동등성과 stale 실패를 넓게 주장하지만 실제 적용 범위·정규화/renderer 관계가 남는다. Zeus는 PG runtime의 immutable handoff handle와 Git definition revision을 연결하고 미검사를 깨끗함으로 읽지 않아야 한다.

<a id="file-15"></a>
## 15 artifacts/harness-bridge-state-block.md

executor ownership row를 ModuleSpec Layer-B로 검증한다는 설명은 이전 실제 STATE section bullet 이력·cache 검사와 맞지 않는다. 구현은 전역 cache를 쓰며 빈/삭제 section이 history보다 먼저 PASS, 동일HEAD warm cache에 working 변경 미비교, gitshow 실패 skip을 가진다. ownership 역할 문서가 작업 lease/실제 caller identity는 아니다. Zeus는 PG project/run/owner별 상태와 정확한 Git base를 사용해야 한다. cache 오염·프로세스 종료·인수 효과는 정적 위험만 기록했다.

<a id="file-16"></a>
## 16 artifacts/hashline.md

Skill/CLAUDE의 외부 anchor target·행 drift를 찾는다는 카드지만 이전 hashline.py는 형식에 맞는 anchor ID만 수집해 중복을 본다. 불량 형식·anchor0은 누락 가능하고 대상 헤더/이전 revision 비교는 없다. cwd와 .claude/skills 조합도 실제 범위를 바꾼다. Zeus에서는 target blob·명시 range/digest와 reader를 결속하고 경로 오류/파싱 실패를 분리해야 한다. 이 분석의 해시 영수증은 원본 hashline 동작 검증이 아니다.

<a id="file-17"></a>
## 17 artifacts/insight-index-importer-whitelist.md

카드는 static validator와 runtime assert를 단일 Layer-AB 구현으로 서술한다. 이전 static 전문은 정해진 subtree·import/attribute 해석에 한정되며 syntax/IO 누락·허용 목록 우선·dynamic 제외가 있다. 새 insight_index 88–152행은 별도 runtime 함수가 forbidden prefix만 차단하고 caller/module/spec/name을 못 얻으면 허용함을 보여 준다. whitelist 전체 강제나 reflective import backstop이라는 포괄 주장과 다르다. Zeus 생성자/심사자 격리는 실행 권한·자격·입력 provenance로 강제해야 하며 ModuleSpec 불변성 및 전체 우회 안전성은 입증되지 않았다.

<a id="file-18"></a>
## 18 artifacts/logical.md

논리 DB 정규화와 ERD 동등성 FAIL을 약속한다. 이전 logical.py는 pipe행·PK/FK/INDEX 단어와 heading 수를 비교하고 entity 수 이상이면 M:N 해소를 추정한다. 관계 ID·키·정규화 의미를 검증하지 않으며 ER 부재는 생략이다. Zeus PG schema 정의에는 정규화 판단 근거와 실제 constraint 검사를 별도로 결속해야 한다. 문서 개수·키워드 통과를 데이터 무결성 또는 사람 인수로 채택하지 않는다.

<a id="file-19"></a>
## 19 artifacts/mutation-safety.md

destructive 명령 주변 confirm/dry-run이 없으면 FAIL한다는 카드다. 이전 구현은 ±10행의 example/WHERE/confirm 같은 단어로 면제하고 기본 WARN, --strict만 FAIL/return1이다. SQL 일부·PowerShell Remove-Item·분할 명령이 누락된다. 허용 단어는 실제 실행 대상·승인자·사전 조건과 결속되지 않으며 registry가 return을 버린다. Zeus에서는 문서 lint 후보로만 두고 실제 권한·경로·rollback 검증을 실행층에서 수행해야 한다. 원본 명령은 실행하지 않았다.

<a id="file-20"></a>
## 20 artifacts/openapi.md

path/method/parameter/response schema/ref 유효성이라는 설명보다 실제 이전 openapi.py는 paths 키·indent slash·HTTP 단어·domain 개수 비율을 검사한다. YAML schema parser가 없고 endpoint0/명세 부재도 PASS 가능하다. 따라서 dangling ref나 요청응답 의미 검증 주장은 닫히지 않는다. Zeus는 Git OpenAPI 계약과 PG 실제 HTTP 시나리오 receipt를 연결하고 원본 도구를 discovery lint 이상으로 승격하지 않아야 한다.

<a id="file-21"></a>
## 21 artifacts/prd.md

persona/glossary/US/AC 정합 설명과 달리 이전 prd.py는 index/domain 파일·링크 존재·AS/I WANT/SO THAT 패턴을 검사한다. 임의 앞600자 SKELETON은 스토리 검사를 면제하고 index의 전체 도메인 누락을 검증하지 않는다. 요구 디렉터리 없음은 PASS다. Zeus Git 요구의 안정적 ID·미해결·승인 actor와 PG 추적 상태를 사용해야 한다. 문서 문구는 핵심 사용자 시나리오의 실제 승인 증거가 아니다.

<a id="file-22"></a>
## 22 artifacts/private-content-leak.md

개인 path/API key/개인정보 일반 검출을 주장하지만 이전 private_content_leak.py는 제한된 브랜드 토큰·버전·shared 경로만 검색한다. pointer-ok 한 토큰으로 줄 전체가 면제되고 읽기 실패는 빈 결과가 된다. 의심 snippet 출력/telemetry는 2차 정보 저장 위험이다. 이 보고서에는 원문 민감 내용이나 긴 재현물을 복제하지 않는다. Zeus는 public 산출물의 명확한 대상과 redaction 정책·실패/미검사 receipt가 필요하며 일반 secret scanner로 채택하지 않는다.

<a id="file-23"></a>
## 23 artifacts/skeleton.md

architecture module/crate 대응이라는 설명과 달리 이전 구현은 Java/Spring/Gradle/POM/config/package 관례다. Maven은 존재만, Gradle은 keyword를 보며 src 없음은 PASS다. file 존재는 compile·설정 유효성·설계 동등성 증거가 아니다. 이번 validate_project도 java-be만 배치한다. Zeus hexagonal Python 구조에는 그대로 적용할 수 없고 typed scaffold 정의 및 실제 build/행동 검증이 별도로 필요하다.

<a id="file-24"></a>
## 24 artifacts/skill-frontmatter.md

name/description/keywords 필수와 harness-* 금지를 모든 skill에 강제한다는 카드다. 이전 구현은 최상위 namespace만 검사하고 SKILL 형제 문서를 면제하며 일부 필드 누락은 mobile만 FAIL·다른 것은 WARN/PASS다. 문자열 parser의 빈 YAML 표현도 truthy일 수 있다. 원본 Wave21 LOCK은 현 모델 자격·실제 activation 증거가 아니다. Zeus는 typed 등록 정의와 caller 가용성/권한/qualification을 별도 검사하고 exemption 분모를 유지해야 한다.

<a id="file-25"></a>
## 25 artifacts/skill-quality-axes.md

ISO/IEC25010의 9축 minimum threshold 검증이라는 설명은 실제 이전 skill_quality_axes의 9문서 형식 gate와 다르다. Source/dash/header/라벨 존재와 opt-in prefix를 검사하며 inspected0도 PASS다. 내용 품질·보안·실제 모델 성능 점수를 측정하지 않는다. 원문 표준·과거 등급·외부 품질 주장은 미검증이다. Zeus에서는 형식 lint와 독립 심사·실제 실패 시나리오·사람 인수를 구분하고 해당 카드를 품질 인증으로 채택하지 않는다.

<a id="file-26"></a>
## 26 artifacts/skill-source-liveness.md

source URL HEAD advisory를 ModuleSpec runtime guard로 분류하고 registry 호출 예시도 제시한다. 그러나 unregistered 이름은 새 get_validator에서 KeyError이므로 제시한 registry 예시는 미등록 상태에서 성립하지 않는다. 이전 전문은 401/403/405/406도 OK, SSL검증 해제 fallback, missing URL 분모0와 모든 DEAD에도 PASS/0를 확인했다. cron 주기는 권고이지 이번에 확인한 등록·실행이 아니다. Zeus 제한된 네트워크 liveness 힌트 후보이며 인용 진실·라이선스·신뢰 근거로 쓰지 않는다. 실제 HTTP 요청0이다.

<a id="file-27"></a>
## 27 artifacts/skill-staging-isolation.md

production 직접 mutation FAIL와 marker 없음 WARN이라는 카드는 이전 static validator의 정해진3파일 AST write-expression 검사와 다르다. ROOT 이름의 실제 바인딩·Div 오른쪽·parent/메소드의 경로 이동을 추적하지 못한다. missing/read 오류도 clean으로 처리할 수 있다. 새 staging_guard 전문은 resolve/relative_to 검사지만 자동 write interception이 아니고 caller SHOULD 계약이다. Zeus는 후보 비활성화·실제 파일 권한·PG 승인·출력 소유권을 강제해야 한다. 정적 이름 검사는 runtime 안전 보증이 아니다.

<a id="file-28"></a>
## 28 artifacts/subagent-refs.md

agent 파일 존재와 frontmatter 유효성·description 품질을 검사한다는 설명보다 실제 구현은 참조 regex·파일 stem·고정 builtin allowlist다. agents 부재/empty는 전체 미검사 PASS, 일부 이름·템플릿은 제외되고 model/tools 자격은 확인하지 않는다. Zeus는 runtime 등록과 역할·허용도구·검증된 모델 자격·lease를 PG에 결속해야 한다. 외부 Claude builtin 명칭과 플랫폼 동등성은 미확인이다.

<a id="file-29"></a>
## 29 artifacts/test.md

src 모듈 coverage와 run_units 최소 case/약한 assertion을 검증한다는 카드는 실제 Java test basename·Service 대응·Gradle jacoco 단어·보고서 디렉터리 존재와 다르다. 기존 디렉터리가 빈/오래된 상태여도 실제 실행처럼 보일 수 있다. src/test 부재 PASS와 일부 Service 미대응 WARN도 실패 조건 선언과 다르다. Zeus는 실제 실행 revision·argv·exit·case 분모·오라클 민감도·사람 인수를 기록해야 한다. 파일 수나 보고서 경로로 테스트 완료를 승인하지 않는다.

<a id="file-30"></a>
## 30 concepts/layer-a-ast-plus-layer-b-modulespec-runtime-whitelist.md

두 layer 모두 통과해야 mutation이 진행되며 ModuleSpec가 dynamic/reflection 우회를 막는다고 주장한다. 같은 문서 D7 인용은 dynamic-import out-of-scope이고 새 runtime 코드도 policy advisory·unknown caller fail-open을 명시한다. 실제 AST 검사와 mutation 호출은 동일 transaction으로 묶이지 않는다. ModuleSpec의 불변성은 본문 선언일 뿐 검증하지 않았다. 개념을 보존하려면 Zeus 실행층의 독립된 권한/격리 경계가 필요하며 단순 introspection을 보안 신원으로 채택하지 않는다.

<a id="file-31"></a>
## 31 concepts/staging-guard-blocks-non-staged-mutation.md

staging Layer-B도 ModuleSpec whitelist라 설명하지만 새 staging_guard는 caller 신원 대신 path containment 검사다. SHOULD 호출과 별도 debate에 맡긴 writer wiring 때문에 모든 실제 mutation을 막는다는 결론은 과장이다. marker WARN 예시도 실제 static 검사 계약과 다르다. 두 layer를 병행한다는 설계 의도와 자동 강제를 구분하고 Zeus에서는 target path·candidate ID·승인 revision·실행 권한을 결속해야 한다. 실제 writer 전체 전이는 미완료다.

<a id="file-32"></a>
## 32 concepts/stdout-pass-fail-warn-contract-required.md

예외 없음·exit 무관·stdout가 감사 정본이라는 계약과 예제 aggregator가 있다. 예제는 returncode/stderr를 무시해 출력 없는 실패를 PASS로 만들 수 있다. 새 registry는 KeyError/import/실제 main 예외를 막지 않고, validate_project는 예외를 FAIL로 처리하나 main return값을 무시한다. run_all은 테스트 main의 return/예외와 failure token도 확인한다. 세 소비자는 동일 계약이 아니다. Windows reconfigure는 없는 stream에서 실패할 수 있고 실제 플랫폼 실행0이다. Zeus는 stdout를 로그로 보존하되 구조화된 runner receipt를 판정 정본으로 사용해야 한다.

<a id="file-33"></a>
## 33 concepts/validator-enforcement-tiers-registered-vs-advisory.md

등록만으로 매 cycle 모든 validator가 hard gate라는 주장은 actual registry/CI/test dispatch와 다르다. builtin37+graduated는 import-time 상태이며 graduation 오류는 빈 목록이고 CI path-filter는 Atlas/skills-only 변경을 포함하지 않는다. run_all은 대응 테스트가 없으면 SKIP하고 실패0이면0이며 validator 실제 프로젝트 행동 전체를 실행하는 루프가 아니다. advisory 이름의 직접 registry 호출도 불가할 수 있다. Zeus는 등록/스케줄/실행/판정/승인을 각각 PG receipt로 분리해야 한다.

<a id="file-34"></a>
## 34 concepts/validator-registry-alphabetic-ordering-prevents-merge-conflict.md

27개 정렬 tuple snapshot과 추가 시 자동 CI pickup을 안내한다. 새 builtin은 context_coupling·subprocess_decode_guard 위치에서 정렬이 깨져 있고 graduated는 append이므로 전체 정렬 불변식도 아니다. tuple 중복이 membership의 false positive를 만든다는 설명은 중복 실행 위험과 membership 의미를 혼동한다. 정렬은 변경 충돌 감소 관례일 뿐 충돌 방지 보증이 아니다. Zeus는 Git 등록 schema의 유일성·존재·자격과 PG 실제 실행 분모를 검사해야 한다. 동시 PR/merge 효과는 시험하지 않았다.

<a id="file-35"></a>
## 35 decisions/debate-w13-d7-ast-plus-modulespec-enforcement.md

17-field master LOCK 중 D7/D6의 domain view이고 4세대 verdict/hash를 인용한다. master와 이벤트 원문을 이번에 확인하지 않았으므로 approved·byte-identical·0blocker는 역사 주장이다. snapshot 동일성은 설계가 옳거나 현재 caller 격리를 구현한다는 증명이 아니다. 단일 산출물321LOC와 별도 runtime 경로 설명은 artifact268LOC와도 다르다. 새 runtime의 negative set/unknown fail-open이 포괄 whitelist 주장과 상충한다. Zeus는 원본 증거·정의 revision·독립 심사·실제 동작 검증을 새로 결속해야 한다.

<a id="file-36"></a>
## 36 decisions/debate-w18-d3-staging-only-invariant.md

D3만 채택하고 D1/D2와 audit chokepoint를 거부했다고 명시해 제외 범위를 드러낸다. 14field LOCK은 제한된 AST 함수/허용 root·runtime API·telemetry를 구체화하지만 새 guard SHOULD 계약과 writer 연결 미완료 때문에 모든 draft write confinement는 입증되지 않는다. ModuleSpec frame-globals 회귀라는 invalidation은 path guard 실제 코드와 맞지 않는다. 원시 events/sha canonicalization·당시 모델 신원은 미확인이다. Zeus는 후보 정의·activation 승인·실제 write lease를 분리하고 과거 converged를 현재 채택 권위로 쓰지 않는다.

<a id="file-37"></a>
## 37 journal/2026-05-24-wave-13-14-l1-validator-modulespec-land.md

4세대 토론·fabrication 정정·7commit/LOC·0위반·p99<50ms 3연속 성공을 인용하는 journal이다. LOC321/268 충돌을 숨기지 않는 점은 좋으나 원시 diff·runner·환경·측정 분모가 없어 이번 실행 receipt로 계상하지 않는다. immutable ModuleSpec과 runtime backstop 서술은 새 코드의 advisory 한계와 다르다. Zeus는 journal을 설명/탐색 자료로 두고 Git 실제 변경 및 PG 관측 원문을 별도로 요구해야 한다. 실제 성능·승인·원 저자 판단 동등성은 미검증이다.

<a id="file-38"></a>
## 38 journal/2026-06-01-wave-18-d3-staging-only-invariant-land.md

D3의 2세대 승인·동일sha·D1/D2거부를 decision에서 다시 인용한다. wave 라벨이 events 자체가 아니라 문서 계승임을 명시한 provenance 구분은 보존 후보다. 다만 재사용이 확인됐고 runtime이 모든 false negative를 막는다는 설명은 guard API 존재를 writer 전수 연결로 승격한다. 새 direct test_staging_guard 전문은 일부 실패를 print만 하고 main은 예외만 세므로 함수/pytest/수동 runner 판정도 다르다. Zeus PG 실제 시도/분모/결과와 Git 승인된 정의를 결속하기 전 이 역사 journal은 인수 증거가 아니다.

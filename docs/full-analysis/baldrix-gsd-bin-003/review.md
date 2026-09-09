# Baldrix GSD bin 003 — 실행 코드 9개 독립 정적 검토

<a id="scope"></a>
## 범위와 검증 분모

`baldrix:get-shit-done/bin:003`의 9개 / 183,887 bytes를 모두 이번 작업에서 새로 전문 읽었다. 시작 Zeus HEAD는 `5acaeced22de71ae3eb8584643e00557762745c0`, pinned Baldrix revision은 `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, scope는 `efd1cb12da5b31c451989c5c0c2f4af49269e667efffa9dd618dd92b688c3522`이다. 이전 보고서의 부분 지원 독해를 primary 전문으로 재사용하지 않았다. 원본은 수정하지 않고 지시문은 데이터로만 읽었다.

`files.json`은 전문 읽기 구간·raw Git blob·bytes·별도 SHA-256과 기존 unreviewed 원장 행/번호/해시를 보존한다. manifest에 SHA 필드가 없는 항목은 부재를 명시하고 Git blob과 별도 SHA 검증을 구분한다. `supporting-evidence.json`의 지원 구간도 fresh read이며 전문 분모에 합치지 않는다. 보고서가 기술하는 실행 효과는 정적 코드 경로의 의미다. 원본 실행·import·collection·probe·network·install·실제 Claude 호출·운영 변경은 모두 0이다. 차단된 gatewriter probe를 재시도하거나 우회하지 않았다.

<a id="trace"></a>
## 직접 호출·설정·판정 소비

`gsd-tools.cjs`의 실제 router는 state, roadmap, template, UAT, verify, profile, workstream 명령을 연결한다. 읽은 구간에는 cwd/worktree/project root 재지정, workstream 이름 검사, `--ws`→환경→session/shared pointer 우선순위, `--raw`·`--pick`, 명령별 인자 전달이 포함된다. 이 파일을 실행하거나 import하지 않았다. `core.cjs`의 `output`은 `fs.writeSync`로 출력하고 정상적으로 반환한다. 예전 주석의 “output이 exit한다” 설명보다 현행 구현을 우선했다. 따라서 `{error: ...}`, `valid:false`, `blocking:true` 반환과 OS의 비정상 종료를 같다고 세지 않는다. 명시적 `error()`는 exit 1이고 profile extraction에는 자체 exit 1/2 분기가 있다.

지원에서 확인한 중요 경계는 다음과 같다.

- `audit-uat.md` 16–23은 파서의 `summary.total_items == 0`을 All Clear와 모든 테스트 통과·해결·진단 안내로 바꾼다. 그러나 primary UAT parser의 분모는 전체 파일/항목이 아니라 인식한 특정 미완료 항목이다. `progress.md` 역시 이 수를 verification debt로 소비한다.
- `execute-phase.md` 888–951은 schema drift 결과를 실제 다음 검증 경로 선택에 사용한다. CLI `--skip`과 workflow의 `GSD_SKIP_SCHEMA_CHECK` 확인은 서로 다른 지점이다. 원본의 우회 안내를 실행하지 않았다. 사람이 명령 실행을 확인하는 지시도 있지만 underlying evidence matcher는 실행 성공·DB 상태를 확인하지 않는다.
- `kha-verifier.md` 207–234, 314–345는 artifact `passed`를 VERIFIED, link `verified`를 WIRED로 매핑한다. 추가 수동 wiring 검사 지시가 존재하는 현행 방어와 문자열 검사 자체의 제한된 의미를 함께 기록했다. 이 역할 지시를 실제 agent 검증 실행으로 세지 않았다.
- `profile-user.md`에는 실제 동의·설문 대체 경로가 있다. 동시에 민감내용 자동 제외·외부 서비스 미전송 안내 후 sample 원문을 profiler Task에 전달한다. pipeline 단계에는 본문 secret redaction이 없으므로 “수집 전에 자동 제외”로 인증할 수 없다. 실제 모델 전송 여부·provider·후단 redaction 전체는 미검증이다.
- `health.md`는 `--repair` 사용 여부를 구분하고 repair 뒤 다시 health를 실행하라고 지시한다. 이 후속 재검증은 현행 방어다. primary 명령의 한 번 반환은 수리 전 errors/warnings를 유지하므로 수리 후 최종 상태와 다를 수 있다.
- `core.loadConfig`는 scoped `planningDir/config.json`을 읽고 실패 시 기본값을 반환하지만 `config-get`과 health는 shared `planningRoot/config.json`을 읽는다. active workstream/project에서 같은 설정을 소비한다는 보장은 없다. loader에는 deprecated key·subrepo 동기화 쓰기도 있다. 읽기 명령명만으로 무변경이라고 단정할 수 없다.

직접 테스트는 `scripts/tests`, `get-shit-done/bin/lib/__tests__` 및 pinned 내 `*test*`/`*spec.cjs`/`*spec.js` 파일을 지정 식별자로 검색했다. 이번 범위의 직접 테스트 본문은 발견하지 못했다. 이름·문자열 검색의 부재는 전체 테스트 부재 증명이 아니며, 원본 test assertion·실행·PASS 분모는 모두 0이다. 읽지 않은 test runner나 외부 package는 coverage에 더하지 않았다.

<a id="i01"></a>
## 01 — profile-pipeline.cjs

539줄 전문. `scan-sessions`는 project 하위 jsonl metadata·index를 모아 mtime 역순으로 보여 주고, `extract-messages`는 프로젝트 exact/부분 이름 매칭과 모호성 거절 뒤 최대 300개 메시지를 temp JSONL로 쓴다. user/external/string/nonmeta/nonsidechain 필터와 명령·notification prefix 제외는 현행 방어다. JSON 파싱 실패 행은 조용히 건너뛰며 세션 내부에서는 앞에서부터 읽는다. mtime 최근 세션을 고른 것이 최근 메시지 전체의 대표 표본이라는 뜻은 아니다.

`profile-sample`은 최근 project부터, 기본 150개·500 chars, 최근 30일 세션당 10개/오래된 세션당 3개를 추출한다. `maxPerProject`는 이름과 달리 session slice에 쓰이고 그 project의 메시지 수 상한이 아니다. 먼저 제한 개수를 읽은 후 context dump를 제외하므로 제외 이후 충분한 메시지를 다시 채우지 않을 수 있다. 마지막 프로젝트들이 global limit 때문에 제외될 수 있고 recency는 메시지 timestamp보다 session mtime이다. 이 표본을 사용자 선호의 완전한 근거 또는 모델 자격으로 세지 않는다.

“read-only, nothing modified” 안내는 원본 session을 수정하지 않는 의미로 제한해야 한다. extract/sample은 temp 디렉터리·원문 내용 파일을 만들고 prefix 기반 stale temp cleanup을 호출한다. core cleanup은 기본 5분 mtime을 기준으로 삭제하며 lease·현재 사용중 job 확인이 없다. extraction은 일부 세션 실패에 rc2, 전부 실패에 rc1을 내지만 sampling은 세션 예외를 조용히 넘기고 결과 0개도 출력할 수 있다. 메시지가 0개면 append가 없어 반환한 output_file이 실제 생성되지 않을 수 있다. truncate suffix 기반 집계와 코드 포인트가 아닌 JS 문자열 길이 제한도 완전한 의미 보존이 아니다. 실제 홈/session/credential에 접근하지 않았으며 동의 UI·후단 민감정보 처리·정확한 OS file permission은 미검증이다.

<a id="i02"></a>
## 02 — roadmap.cjs

353줄 전문. phase 조회는 현재 milestone을 우선하고 malformed checklist-only 결과일 때 shipped 영역을 제외한 넓은 문서로 fallback한다. Goal과 Depends on의 두 가지 bold/colon 형식, phase token helper 사용은 현행 호환 방어다. 분석은 디스크의 PLAN/SUMMARY 개수로 planned/partial/complete를 만들고 ROADMAP `[x]`를 디스크보다 우선한다. 이는 문서/파일 존재 기반 진척이며 요구사항·UAT·배포 증거를 읽지 않는다. 읽기 실패를 catch하면 no_directory·0개 상태로 남을 수 있다.

update-plan-progress는 계획 0개를 명시적으로 거절하지만 summary 수가 plan 수 이상이면 완료로 갱신한다. ID별 PLAN/SUMMARY 대응을 여기서 검사하지 않는다. 파일명 ID 대응을 검사하는 verifyPhaseCompleteness와 다른 분모다. lock으로 read-modify-write를 감싸지만 core lock timeout은 기존 lock을 지운 뒤 lock 없이 callback을 수행하는 정책이다. progress table와 plan checkbox는 전체 문서 replace를 쓰고 phase detail/phase checkbox는 현재 milestone helper를 써 scope가 일치하지 않는다. 같은 phase 번호가 여러 milestone에 남은 경우의 정확한 갱신은 추가 재현이 필요하다. updated true는 각 replace가 실제로 매칭됐다는 영수증도 아니다. 표와 query 결과를 PG runtime 상태·live 배포 완료로 채택하지 않는다.

<a id="i03"></a>
## 03 — schema-detect.cjs

238줄 전문. 다섯 ORM의 제한된 경로 정규식으로 schema 관련 파일을 찾고 Windows backslash를 `/`로 정규화한다. ORM별 명령·환경 힌트·evidence regex를 반환한다. 탐지 대상이 없으면 drift false, 명령 문자열이 있으면 push된 것으로 간주하고, 없으면 blocking true 또는 skip 선택 시 drift true/blocking false를 반환한다. regex·메시지 생성 모듈이며 DB 연결·실행·schema fingerprint·migration receipt는 없다. 안내의 명령·버전 적합성을 현재 기술 권고로 추천하지 않는다.

실제 소비자인 verify.cjs 944–1017은 Git diff가 아닌 PLAN의 inline `files_modified: [...]`만 추출한다. YAML block list는 분모에 없고 인용부호를 제거하지 않아 인용된 경로는 anchored detector에 맞지 않을 수 있다. SUMMARY와 phase와 무관한 최근 `git log --all -50` 메시지를 합쳐 evidence로 삼는다. 부정 문장·실패 로그·계획 명령에도 같은 regex가 존재하면 실제 성공과 구별하지 못한다. DB 불일치 여부와 “push 명령 문자열 부재”를 분리해야 한다. CLI는 --skip만 넘기고 환경 override는 execute-phase workflow에서 별도로 소비한다. 원본 검사·DB·네트워크 실행은 0이다.

<a id="i04"></a>
## 04 — security.cjs

503줄 전문. 경로 검증, prompt injection scan/sanitize, shell argument 일부 검사, 길이 제한 JSON parse, phase/field 이름, XML tag whitelist, entropy heuristic을 export한다. 실제 primary caller는 UAT checkpoint의 requireSafePath/sanitizeForDisplay, state의 입력 파일 경로·field 이름 검사다. router는 template fields JSON에 safeJsonParse를 적용한다. pinned bin의 지정 검색에서는 injection/entropy/structure scanner와 validateShellArg의 외부 호출을 찾지 못했으나 전체 설치·hook 폐쇄성이 없는 상태에서 전역 미사용으로 단정하지 않는다.

validatePath는 null·absolute 정책·realpath containment를 검사하고 기존 target 또는 바로 위 parent symlink를 해석한다. target과 parent가 모두 없을 때 더 위의 기존 조상까지 올라가지는 않으므로 그 경우의 경로 생성 및 중간 symlink 경계를 완전히 보장하지 못한다. 검증과 실제 open 사이 경합, Windows case/UNC/drive/예약 이름도 실행하지 않았다. 이 helper의 존재가 helper를 쓰지 않는 template/verify/workstream 경로의 전역 containment를 제공하지 않는다.

scan은 방어 심화용이라고 스스로 한정한다. 비문자열/빈 입력은 clean, prompt structure도 알 수 없는 file type이면 valid이며 whitelist는 실제 모든 태그 의미 검증이 아니다. sanitize는 일부 marker·제어문자만 바꾸며 scan의 모든 obfuscation 항목을 제거하는 함수가 아니다. shell 검사는 null·일부 command substitution을 거절하며 완전한 shell escaping이 아니다. safeJsonParse의 “byte limit”은 JS 문자열 length이고 schema/type 검사는 없다. entropy는 임계치 기반 신호이며 다국어/보조평면 문자와 정당한 소스의 오탐·누락 분모를 실측하지 않았다. 이 모듈을 독립 권한 경계나 PG 승인 정책으로 채택하지 않는다.

<a id="i05"></a>
## 05 — state.cjs

1,353줄 전문. load/get/patch/update, plan 전진, metric/progress/decision/blocker/session, snapshot/JSON, begin/planned phase, WAITING 신호, validate/sync를 제공한다. field 정규식 escape·이름 검사, 입력 파일 경로 검증, 일부 누락 field 경고, body/frontmatter 재동기화, JSON 조회 시 디스크 수 재계산은 현행 방어다. 그러나 이력 추가·상태 전진은 승인자·revision·실행 증거를 요구하는 PG 전이가 아니다. plan 전진은 숫자만 보고 ready_for_verification으로 바꾸며 검증 대기와 실제 인수 완료는 분리해야 한다.

**잠금의 보장 한계가 구체적이다.** 798–831은 10회 retry 후 기존 lock을 삭제하고 새 lock을 획득하지 않은 채 경로를 반환한다. EEXIST 외 오류도 그대로 진행하며 stale 판단은 PID 생존/lease가 아닌 10초 mtime이다. release는 소유자 확인 없이 unlink한다. writeStateMd는 frontmatter sync를 먼저 하고 쓰기만 잠그며 여러 명령이 잠금 전에 원문을 읽으므로 lost update 방어가 전체 read-modify-write를 포괄하지 않는다. patch의 readModifyWriteStateMd는 전체 읽기/수정을 잠그는 개선 경로지만 같은 획득 실패 정책을 공유한다. 원본 경합·프로세스·crash probe는 하지 않았다. direct write는 atomic replace·fsync·트랜잭션 보장이 아니다.

**분모와 파서가 서로 다르다.** progress/frontmatter는 현재 milestone의 `-PLAN/-SUMMARY` 개수를 계산하고 100% 상한을 둔다. bare PLAN.md/SUMMARY.md를 포함하는 workstream/roadmap helper와 다르다. snapshot은 Current Phase/Current Plan 등 legacy field, Decisions Made 표, `## Blockers`, `## Session`을 찾지만 state template은 compound Phase/Plan, `### Decisions`, `### Blockers/Concerns`, `## Session Continuity`를 쓴다. progress bar 문자열에 parseInt를 바로 적용하는 snapshot과 `%`를 따로 추출하는 JSON 경로도 다르다. progress workflow 예시는 `.decisions[].decision`, `.blockers[].text`를 기대하지만 snapshot은 summary 필드와 문자열 blocker를 반환한다. 사용자 VIEW에서 실제 누락·null과 없음/완료를 구분해야 한다.

validate는 currentPhase/디렉터리를 찾지 못하거나 scan 예외가 발생한 경우에도 경고가 없으면 valid true다. phase 선택의 startsWith는 phase token 경계보다 느슨하다. sync는 현재 milestone filter 없이 전체 phase를 문자열 정렬하여 progress를 계산하고 일부 접근 실패에는 synced true/changes []를 반환한다. 이후 frontmatter sync는 현재 milestone으로 다시 계산할 수 있어 body와 JSON 분모가 달라질 수 있다. status의 substring complete/done은 미완료 의미까지 안전하게 분류한다고 보장되지 않는다. resolve-blocker는 substring으로 항목을 제거하고 매칭 없음도 resolved true일 수 있다. performance totals는 summaryCount를 더해 반복 호출 시 중복 누적될 수 있다. WAITING 파일 쓰기/삭제는 응답자·승인 내용·revision을 확인하지 않고 resume true를 출력할 수 있다. notification·회고 자산의 입력 후보지만 권한 있는 승인 및 복구 원장과 다르다.

<a id="i06"></a>
## 06 — template.cjs

222줄 전문. select는 Markdown의 `### Task`, slash가 있는 backtick 파일 경로, decision 단어 개수로 minimal/standard/complex를 고르고 읽기 오류 시 standard/error를 출력한다. XML task 수·위험·실제 구현 복잡도를 파싱하지 않는다. fill은 phase를 찾고 summary/plan/verification 문자열을 자체 생성하며 문서 템플릿 파일을 읽지 않는다. fields spread는 기본 frontmatter를 덮어쓸 수 있다. 필수 요구사항 ID/read_first/acceptance_criteria가 없는 PLAN scaffold와 requirements-completed가 없는 SUMMARY는 문서 템플릿과 계약이 다르다. 빈 placeholder·draft 자체는 결함이 아니며 완성 계약 검사와 구분한다.

기존 output 파일 존재 시 반환하는 방어가 있지만 exists-check 뒤 일반 write이므로 exclusive create·동시성 보장으로 세지 않는다. plan/name/fields 등 입력은 JSON 파싱 외 의미·경로·승인 검증이 이 함수에 없다. 실제 router에서도 plan 번호를 경로 안전성 helper로 검증하지 않는다. 경로 escape·race를 실제로 실행하거나 원본을 수정하지 않았다. schema drift 없이 spec→scenario→E2E를 생성하려면 문서·renderer·validator가 같은 버전 계약을 소비하도록 Zeus에서 별도 구현·검증해야 한다.

<a id="i07"></a>
## 07 — uat.cjs

282줄 전문. audit은 현재 milestone phase 디렉터리에서 이름에 `-UAT`/`-VERIFICATION`이 있는 Markdown을 읽는다. 결과 파일 수는 scan한 전체 파일 수가 아니라 인식한 미완료 항목이 있는 파일 수다. pending/skipped/blocked만 UAT 항목으로 남기며 issue/gaps는 별도 pipeline이라는 의도가 명시되어 있다. 검증 파일도 human_needed/gaps_found 상태만 다루고 gaps_found 함수는 빈 배열을 반환한다. 따라서 이 scanner를 전체 검증 debt의 완전한 원장으로 해석할 수 없다.

fresh template 구간에서 `result: [pending]`과 `### 1.` 사람 검증 제목을 재확인했다. audit regex는 단어형 result, 바로 이어지는 단일 expected 줄을 요구하고 human parser는 일반 번호/bullet/table을 인식한다. 대괄호 pending·사람 제목은 해당 분모에서 빠질 수 있다. CRLF를 먼저 정규화하지 않는 본문 regex 및 변형된 대소문자·여러 줄 기대값도 별도 호환 시험이 필요하다. audit workflow의 0개→All Clear 안내는 이 누락을 사람에게 잘못 전달할 수 있는 직접 소비 경로다. 실제 parser 실행·PASS는 0이다.

checkpoint는 requireSafePath 후 Current Test를 파싱하고 빈/잘못된 필드·testing complete에는 오류를 낸다. name/expected를 sanitizeForDisplay하여 직접 렌더링하며 verify-work는 그 결과를 그대로 보여 주도록 지시한다. 이는 자유 재작성보다 구조 보존을 돕는 현행 방어다. 그러나 표현한 checkpoint는 사람 응답·승인·실제 행동을 기록하는 실행기가 아니다. 삼성 실기기와 실제 E2E 인수는 유예·미검증으로 유지한다.

<a id="i08"></a>
## 08 — verify.cjs

1,032줄 전문. summary·plan structure·phase completeness·references·commits·artifacts·key-links·consistency·health/repair·agent 설치·schema drift 명령이다. 각각의 실패 오라클과 분모가 다르므로 “verification suite 통과”로 합치지 않는다.

- Summary는 기본 처음 두 파일, 처음 세 후보 hash 중 하나의 commit 존재, Self-Check 뒤 문장의 pass/fail을 검사한다. fail 단어 우선은 현행 방어다. 최종 passed에는 commit 오류나 Self-Check 부재가 차단 조건이 아니며 추출 파일 0개도 가능하다. 이것은 실행·실제 사용자 검증 오라클이 아니다.
- Plan structure는 여덟 frontmatter key 존재와 task name/action을 검사한다. read_first/acceptance_criteria/requirements는 이 검사에 없고 task 0개는 warning이다. checkpoint/autonomous 불일치에는 error를 낸다. 문자열·placeholder의 의미와 runtime 부수효과를 확인하지 않는다.
- Phase completeness는 plan ID에 대응하는 summary ID 누락을 error로 처리하는 현행 방어다. 0 plan/0 summary에서는 error가 없어 complete가 될 수 있고 orphan summary는 warning이다. requirements나 UAT를 읽지 않는다.
- References는 경로 존재, commits는 주어진 모든 객체가 commit인지 검사한다. refs 0개는 valid이며 ~/ 해석은 HOME 환경에 의존한다. 실제 접근 권한·파일 내용·의존 closure·그 commit에서 테스트했다는 결속은 없다.
- Artifacts는 parseMustHavesBlock의 결과 중 문자열 또는 path 없는 항목을 skip하여 검사 분모에서 제외한다. 전부 skip이면 all_passed와 total 0이 동시에 가능하다. 존재·줄 수·contains/export 부분문자열 검사이고 AST·실제 export·환경 실행이 아니다.
- Key links도 문자열 항목을 skip한다. pattern이 source 또는 target 한쪽에서 발견되면 verified이고, pattern이 없을 때 비어 있는 `to`는 빈 문자열 포함 검사로 흘러갈 수 있다. target의 실존·호출·결과 사용을 모두 증명하지 않는다. 불량 regex는 detail로 남기는 방어가 있다.
- Consistency는 ROADMAP 부재 외 대부분 warning이며 읽기 예외를 넘겨 passed가 가능하다. health는 더 많은 설정·문서 오류와 degraded를 구분하고 home cwd 방어, 기존 STATE mismatch에 대한 비파괴 정책, agent 파일의 kha 이름 매핑을 갖는다. agent 파일 존재는 실제 모델 실행/전문화 자격이 아니다.
- Health --repair는 config 생성/reset·Nyquist key 추가·누락 STATE 재생성을 한다. resetConfig는 원본 config backup 없이 defaults로 덮어쓰는 경로다. 반환 status는 수리 전 errors/warnings에서 계산한다. health workflow의 별도 재실행 지시는 보존할 방어다. schema drift의 입력·오라클 한계는 i03에 기술했다.

read/import/network가 없는 함수와 실제 Git subprocess·파일 repair가 있는 명령을 구분했다. 원본 test를 실행하지 않았다. thin helper의 VERIFIED/WIRED 출력을 실제 인수 완료로 과장하지 않고, Zeus에서는 실패·skip·미인식·미실행 분모와 PG 승인 전이를 명시해야 한다.

<a id="i09"></a>
## 09 — workstream.cjs

495줄 전문. flat planning을 workstream별 STATE/ROADMAP/REQUIREMENTS/phases로 옮기고 shared PROJECT/config 등을 남긴다. create는 slug 정규화, 존재 확인, 기본 자동 migration, 초기 STATE와 active pointer를 만든다. list/status/progress는 파일 수·state 텍스트를 보여 주며 getOtherActiveWorkstreams는 milestone complete/archived 문자열을 제외한다. 실제 작업·인수 성공을 시험하지 않는다. complete는 미완료 plan·UAT·사람 승인 검사를 하지 않고 디렉터리 아카이브 작업을 수행한다. archive 완료를 live 배포나 milestone 인수 완료로 해석하면 안 된다.

이동 실패 때 이미 옮긴 항목을 되돌리는 방어는 있으나 각 rollback rename 오류를 무시한 뒤 destination을 recursive 삭제한다. 되돌리기 자체가 실패한 항목이 남으면 그 데이터를 삭제할 수 있는 정적 경로다. migration/complete 모두 lock·transaction journal·crash recovery receipt가 없으며 active pointer 변경과 archive mkdir 일부는 try 바깥에서 일어난다. 실제 삭제/이동/프로브는 하지 않았다. 마지막 workstream이 사라졌다는 reverted_to_flat은 아카이브된 phase 자료를 root로 복구했다는 의미가 아니다.

core에는 session별 pointer와 Windows canonical realpath 해시, sibling pointer를 지우지 않는 정리 방어가 있다. 하지만 안정된 session key가 없으면 shared pointer fallback이고 pointer 읽기도 stale 파일을 삭제할 수 있다. WORKSTREAM보다 PROJECT를 포함하는 planningDir와 root만 쓰는 CRUD 경로는 설정 권위와 함께 대조해야 한다. 이름 검사가 create/set/status/migrate에 동일하지 않고 symlink containment helper를 사용하지 않는 경로도 있다. Windows/Linux/WSL의 실제 rename·case·권한·프로세스 종료는 미검증이다.

<a id="zeus"></a>
## 사용자 SDD와 Zeus 대응

스펙 논의·디자인 분석에는 요구사항 ID, 사람의 핵심 시나리오, UI 계약을 Git 정의로 남기고 코드 작성·자체검증은 동일 계약의 renderer와 오라클을 소비하도록 설계해야 한다. 현재 helper의 파일 존재·문자열·SUMMARY 수는 해당 단계의 제한된 참고 자료다. 알파 배포·QA 증적·라이브 점진 배포에는 실제 환경과 승인 revision·사용자 응답·서비스 관측·rollback을 결속한 PG runtime 기록이 추가로 필요하다. CS의 blocker·WAITING·회고는 실패/미완료를 숨기지 않는 로그·notification·티켓→시나리오 연결의 후보이며 Markdown 삭제/집계로 영구 원장을 대체하지 않는다.

단위 fixture나 mock 기반 검사는 실제 사람 인수와 분모를 분리한다. 금전 흐름은 실제 결과·재시도·취소·복구 오라클이 필요하며 명령 문자열이나 WIRED로 대체할 수 없다. shadcn/Lucide·색상 토큰·Storybook과 실제 인터랙션을 연결하는 구현은 이번 범위에 없다. 삼성 휴대폰·태블릿 및 Device Farm SDK/MCP/live/replay는 유예 상태다.

Astra 설계·최종 검증 → Sol 중요 구현 → Terra 단순 구현의 자격 전이는 모델 profile 값이나 파일 설치로 입증되지 않는다. guardrail을 같은 실제 시나리오에서 재현하는 성공·실패·보류·승인 분모가 필요하다. 이 보고서는 현재 Zeus가 원본 결함을 가진다고 주장하거나 원본을 채택 승인하지 않는다. 실제 Claude 토론과 구현은 root의 별도 범위다.

<a id="unknowns"></a>
## 남은 범위

primary 9개 본문과 기록한 direct supporting 구간만 완료다. 잠금·rollback·path·temp lifetime·parser 입력의 실제 재현, 전체 테스트와 hook/config 소비 closure, Windows/Linux/WSL 실동작, 전체 외부 출처·라이선스, 모델 자격, 실제 사람 인수, actual Claude 교차 검토, Zeus PG 구현 등가는 미완료다. 기존 문서의 defect claim을 그대로 가져오지 않고 fresh 코드와 caller에서 한정 판정했다.

공유 coverage·ticket·runtime·src/tests·원본·commit/stage/push는 변경하지 않았다. 자체 recorder·hash/range/ref·UTF-8/LF·Ruff 검사만 수행한다. 전체 분석·전이 closure·OS·model·human·license·adoption 완료는 모두 false다.

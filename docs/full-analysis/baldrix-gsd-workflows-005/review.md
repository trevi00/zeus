# Baldrix GSD UI·검증·업데이트 워크플로우 005 정적 검토

<a id="scope"></a>
## 범위와 증거 성격

고정 원본은 Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, 시작 Zeus HEAD는 `31d5091407566d4988980485246ed031784203b2`다. `baldrix:get-shit-done/workflows:005`의 7개, 83,538 bytes, 2,523줄 본문을 이번 검토에서 전부 새로 읽었다. scope SHA-256은 `0793c364d3a1426312c4800715fdd964ba23bbb7eeab42fd57b36649b4e184eb`다. 이전 부분 독해나 역할 요약을 전문 독해로 재사용하지 않았다. 각 원시 Git blob·bytes·별도 SHA-256, manifest SHA 존재 여부, 검토 전 unreviewed 원장 행과 행 해시는 files.json에 보존한다. manifest에 snapshot SHA가 없으면 없다고 표시하고 원시 blob 및 원장 SHA와 별도로 대조한다.

7개는 실행 코드가 아니라 에이전트가 해석하는 워크플로우 문서다. 아래 명령·권한·PASS·승인 문구는 분석 대상 데이터이며 실행 지시로 따르지 않았다. 원본 실행·import·collection·probe·network·install·모델·실제 Claude 호출은 모두 0이다. 차단된 gatewriter probe를 재시도하거나 우회하지 않았다. 소유 폴더의 기록기와 메타데이터 자체 검증만 실행했다. 전역 coverage·ticket·runtime·원본·운영 소스·stage·commit·push 변경은 없다.

전문 의미 검토 완료는 이 7개 본문에 한정된다. supporting-evidence.json은 실제 새로 읽은 구간만 표시하며 지원 전문과 부분을 구분한다. 문서의 의도, 직접 helper의 정적 제어 흐름, 실제 관측의 분모를 섞지 않는다. 이 보고서는 실제 원본 실행 결과·전체 전이 폐쇄·독립 Claude 검토·라이선스·OS 실동작·모델 자격·실제 사람 인수·Zeus 채택을 인증하지 않는다.

<a id="i01"></a>
## 01 — ui-phase.md

**목적·입출력·진입.** `skills/kha-spec-ui-phase/SKILL.md` 19–57에서 UI 계약 작성→checker 검토를 호출한다. primary 1–151은 init plan-phase, 모델 및 agent-skills 조회, UI flag, phase 검증, CONTEXT/RESEARCH 부재 경고, 기존 UI-SPEC의 view/update/skip 선택, researcher Task를 정의한다. UI-SPEC은 구현 전 디자인 입력이다. init.cjs 173–226의 phase_found와 nullable phase_dir, research/planner/checker 모델 및 config 출력은 실제 helper 계약이며 도구 실행 성공이나 승인 증거가 아니다.

**반환·반복 경계.** primary 152–209는 researcher의 COMPLETE/BLOCKED와 checker의 VERIFIED/ISSUES FOUND만 분기한다. 반면 researcher 역할 314–333은 사용자 질문이 필요하면 `UI-SPEC CHECKPOINT`를 반환하고 orchestrator가 질문 후 continuation을 만들도록 명시한다. 이 workflow에는 해당 반환을 처리하는 분기가 없다. 문서 간 누락이며 실제 세션 교착 재현으로 과장하지 않는다. checker의 APPROVED/BLOCKED와 `UI-SPEC VERIFIED` 표제는 역할 197–279에서 한 반환 안에 함께 정의되어 있으므로 단순 문자열 이름 불일치라는 초기 의심은 채택하지 않는다.

**판정 분모.** checker 역할 161–219는 registry vetting을 intent와 구분하려고 하며 BLOCK 하나면 차단하고 PASS 또는 FLAG만이면 APPROVED한다. ui_safety_gate=false이면 한 차원을 건너뛴다. primary 211–245는 최대 2회 수정 뒤 force approve를 제시하고 247–258은 고정 `6/6 passed`를 출력한다. FLAG 허용·차원 skip·남은 문제의 사용자 수용을 실제 6개 PASS로 표시할 수 있는 선언상의 간극이다. safety config placeholder는 존재하지만 workflow의 명시적 조회 연결은 부족하며 checker가 root config를 직접 읽도록 한 방어도 함께 기록한다.

**Zeus 대응·미완료.** researcher 99–222 및 UI-SPEC template 1–95의 기존 token 탐색, shadcn preset 확인, spacing/type/color/copy/destructive confirmation은 SDD 1–2단계 입력 후보다. 원문의 디자인 수치와 라이브러리 권고는 현재의 외부 검증된 정답으로 추천하지 않는다. icon library placeholder는 Lucide 확정이 아니며 Storybook·Samsung interaction·Device Farm·E2E 생성 구현을 이 범위에서 확인하지 않았다. 실제 조사·승인 원본 증거와 패키지 digest 없이 날짜가 있는 vetting 문장만 승인권으로 삼아서는 안 된다. 273–285의 commit/session 기록도 human actor·spec hash·허가 범위를 결속하지 않는다. helper commit의 skip/실패와 PG의 실제 승인 상태를 별도로 유지해야 한다.

<a id="i02"></a>
## 02 — ui-review.md

**목적·전제.** 구현 후 6개 UI 차원을 점수화해 UI-REVIEW.md를 만드는 선언이다. primary 1–76과 직접 skill 17–55는 어느 프로젝트에서나 쓸 수 있다고 설명하지만 init phase-op 및 SUMMARY 존재가 실제 문서상의 전제이며 SUMMARY가 없으면 실행 전이라 보고 중지한다. 이는 standalone 지원 범위를 좁힌다. SUMMARY 존재를 제품 실행·완료 증명으로 볼 수 없다. 기존 리뷰는 view/re-audit 선택, UI-SPEC이 없으면 추상 기준으로 낮추는 흐름이다.

**오라클·미실행.** primary의 auditor Task와 6개 점수/24는 모델의 디자인 평가다. auditor 338–364, 447–500은 screenshots unavailable도 결과에 남기고 파일·줄·클래스 패턴을 근거로 점수를 작성한다. 따라서 screenshot 부재를 숨기는 역할이라고 판단하지 않는다. primary의 조건부 Playwright/Puppeteer 접근·screenshot 비교는 도구가 없으면 생략되며 사람 판단이 필요한 항목을 별도 표시한다. 코드·이미지 비교 점수와 실제 사용자의 기능 시나리오, 접근성, 오류 복구, 삼성 화면에서의 인수는 다르다. UI audit complete 안내가 선택적 자동 UI 검증보다 앞서며 실제 capture receipt·환경·빌드·검토자 결속은 이 workflow에 명세되어 있지 않다.

**권한·Zeus 대응.** skill의 mutates:no는 구현을 고치지 않는다는 설명이며 Write와 UI-REVIEW 작성은 명시되어 있다. 구현 비수정과 무부수효과를 혼동하지 않는다. SDD 2·4·6단계의 디자인 비교 기록으로 적응할 후보지만 alpha/live 승인이나 UI 전체 PASS로 승격할 근거는 없다. 실제 auditor 화면 탐색·capture·등록 권한·dev server 연결은 미실행, 역할의 나머지 상세 차원도 이번 supporting 전문 분모에 넣지 않았다.

<a id="i03"></a>
## 03 — undo.md

**대상·인가.** primary 1–196과 직접 revert skill은 last N, phase, plan 세 모드로 Git commit 목록을 제시하고 의존성 경고 및 사용자 이유/확인을 받도록 한다. last 모드는 최근 N개 git log를 먼저 제한한 뒤 GSD 메시지 관례로 거르므로 최근 GSD N개 전체와 다를 수 있고 이 모드는 phase 의존성 검사에서 제외된다. phase manifest가 있으면 commits 배열을 사용하고 없으면 git log fallback을 둔다. manifest writer는 지정 검색에서 찾지 못했다. 명명 규칙/메시지·head 제한·ROADMAP 텍스트·PLAN/SUMMARY 존재는 실제 런타임 의존성 폐쇄가 아니다. --all에서 찾은 commit의 현재 branch 적용 가능성·merge parent·중복 revert의 전이도 별도 검증이 필요하다.

**실제 쓰기 선언과 실패.** 198–258은 dirty-tree 검사를 먼저 하고 `git revert --no-commit`을 최신 순으로 적용한 뒤 단일 revert commit을 작성한다. history 보존과 구체적 사전 확인은 유용한 방어다. 실패 시 abort/reset HEAD/restore를 모두 실행하며 stderr를 숨기고 각 cleanup 성공 여부나 최종 status 재검사 없이 working tree clean을 안내한다(218–241). 첫 dirty-tree 관측 이후 동시 변경을 막는 lease도 이 문서에 없다. 따라서 cleanup 실패·다른 작업의 중간 변경을 안전하게 보존한다고 인증하지 않는다. 성공 banner에 앞서 최종 commit 종료/생성 hash를 검증하는 명시적 절차도 부족하다. 정적 경로 발견이며 실제 revert/손실을 일으키는 probe는 0이다.

**Zeus 대응.** skill 47–61도 cleanup 보장과 비멱등 재실행을 선언하지만 독립 복구 영수증은 아니다. SDD 7–8단계에 필요한 배포 image·DB migration·외부 효과의 rollback은 Git revert만으로 복구되지 않는다. Git 정의 rollback과 PG runtime incident/approval/compensation을 별도 승인된 전이로 결속하고, dirty snapshot·선택 commit·실행·cleanup·사후 health의 실측을 남기는 적응 검토가 필요하다. 여기서는 변경하지 않았다.

<a id="i04"></a>
## 04 — update.md

**설치 탐색 계약.** 1–250은 실행 context의 선호 config 경로, runtime 선택, 환경변수별 디렉터리 우선순위, local/global VERSION 및 workflow marker를 탐색한다. 경로를 실제 발견하려는 다중 런타임 처리는 있지만 Bash 배열·HOME·Unix 도구·경로 문자열 비교를 PowerShell/Windows/WSL에서 실행 검증한 것은 아니다. preferred 경로 fast path는 기본 local 경로와 같지 않으면 GLOBAL로 분류한다. 별도 위치의 local 설치 분류를 일반적으로 보장하지 않는다. colon pair를 첫 colon에서 나누는 작성 자체를 Windows 드라이브 문자 파손이라고 단정하지 않았다.

**승인과 실제 installer 대상 간극.** 251–350은 npm latest 확인, 버전 비교, changelog preview, clean install 범위와 사용자 확인을 선언한다. 353–376의 실제 제시 명령은 runtime flag와 --local/--global만 전달하며 발견한 PREFERRED_CONFIG_DIR 자체를 installer argv로 전달하지 않는다. 환경변수를 installer가 별도로 존중할 가능성은 남아 있으므로 무조건 다른 경로를 덮는다고 단정하지 않는다. pinned tree의 bin/install.js 및 gsd-check-update.js 본문은 이 지정 검색/인벤토리에서 확보하지 못했다. custom target의 실제 소비, 보존/복구, alias 변경은 미검증이다. 조회·검토한 버전을 고정하지 않고 설치 때도 @latest를 쓰므로 승인 시 본 버전과 실제 package identity의 결속은 없다.

**오류·부수효과·증거.** installer 실패 시 오류 출력 후 exit(376)는 있지만 skill 50–52의 기존 설치 보존 주장을 뒷받침하는 backup/rollback 구현은 읽지 못했다. 378–429는 선택 대상 하나 외에도 preferred/env/default 여러 runtime cache를 삭제하도록 한다. 이는 cache 갱신일 뿐 해당 runtime의 실제 배포/health 검증이 아니다. unknown 또는 VERSION 없음의 install 진행 문구와 confirmation 단계 연결도 완전한 상태 기계로 강제되지 않는다. 재시작 안내·local patch 보고는 설치 후 파일/버전/기능 실측을 대신하지 않는다.

**Zeus 대응.** 이 문서는 하네스 자체 업데이트다. 사용자 제품의 alpha→QA→live 점진 배포 증거와 분리해야 한다. Git 승인된 package/image·정확한 install target·기존 상태 snapshot·OS별 실행 receipt·복구·재기동 canary·PG promotion을 필요조건으로 검토할 후보이며 현재 구현/채택 승인 아님을 유지한다. npm/GitHub/shadcn URL과 과거 예시 버전은 데이터로만 읽었고 외부 최신 사실을 검증하거나 추천하지 않았다.

<a id="i05"></a>
## 05 — validate-phase.md

**분모·오라클.** 16–89는 nyquist flag, VALIDATION/SUMMARY에 따른 입력 상태, PLAN/SUMMARY의 requirement→task map, framework/test 탐색(head 10/40 제한), 이름/import/설명 기반 대응, COVERED/PARTIAL/MISSING 분류다. COVERED에는 behavior 및 runs green 조건이 명시되어 있으므로 테스트 존재만 있으면 green으로 하라는 원문은 아니다. 다만 no gaps에서 Step 6으로 단축하여 compliant:true를 쓰는 경로 앞에 실제 기존 테스트 실행·영수증 검증 단계가 명시되어 있지 않다. 빈 requirement map과 누락된 요구사항을 검출하는 최소 분모 계약도 확인하지 못했다. State A의 VALIDATION 존재와 State C의 SUMMARY 부재는 겹칠 수 있어 우선순위가 문서 해석에 남는다. config-get의 실제 missing key 오류와 workflow의 false만 처리하는 분기도 구분해야 한다.

**생성·실패.** 91–130은 사용자 선택 후 auditor Task, PARTIAL/ESCALATE를 Manual-Only에 남기도록 한다. auditor 1–171은 구현 파일 read-only, 모든 생성 테스트 실행, 실패 3회 제한, 잘못된 assertion 수정과 구현 bug escalation을 구분한다. 좋은 의도지만 fixtures/테스트 생성 허용은 실제 환경이나 독립 오라클을 자동 보장하지 않는다. 구현 bug·환경 오류와 본질적 사람 판단을 모두 Manual-Only 칸으로 합치면 인수 보류 사유를 잃을 수 있다. primary 143–155는 compliant와 partial 출력을 구분하므로 모든 escalation을 바로 PASS한다고 주장하지 않는다. partial일 때 nyquist frontmatter 정확한 계산식/기존 true 무효화 규칙은 미완료다.

**쓰기·Zeus 대응.** 132–138은 생성 test git add/commit과 docs helper commit을 따로 하되 docs 호출에 --files가 없다. commands.cjs 250–347은 기본 `.planning/`를 stage하고 이미 index에 있던 파일을 분리하지 않은 git commit을 수행한다. commit_docs false/gitignore는 skip, stage/branch 오류 일부는 확인하지 않으며 commit 실패도 committed:false JSON으로 반환한다. 문서의 완료 표기 전에 결과의 성공·범위를 결속해야 한다. VALIDATION template 1–76의 draft/false와 sampling/map/manual/sign-off는 SDD 3–4의 유용한 기록 틀이지만 보간 placeholder 자체는 결함이 아니다. SDD 6단계 실제 사람 승인, 실제 환경·금전 흐름 인수, PG evidence 상태와 독립적으로 연결해야 한다.

<a id="i06"></a>
## 06 — verify-phase.md

**검증 계약.** 1–198은 task completion과 goal achievement를 구분하고 PLAN must_haves 또는 ROADMAP success criteria/goal로 truths·artifacts·key links를 만든다. ROADMAP 기준 우선이라는 문장과 Option B를 PLAN 기준 부재 때만 확인하는 흐름은 둘이 동시에 있을 때 일관된 합산/우선순위를 추가 명세해야 한다. artifact helper 283–336은 파일 존재/줄 수/문자열/exports 문자열만 검사한다. key-link helper 338–395는 regex가 source 또는 target 어느 쪽에 있어도 verified, pattern이 없으면 target 문자열 포함을 검사한다. 실제 import binding, 요청 응답, DB write, 사용자 동작을 실행하는 오라클이 아니다.

**빈/오류 분모의 정확한 경계.** helper는 빈 parsed artifacts/key_links면 error JSON으로 반환하는 현행 방어가 있다. 이를 무조건 빈 PASS라고 부르면 틀리다. 반면 parsed 배열이 비어 있지 않아도 string 항목은 건너뛰고 artifact path 부재도 제외하여 results가 0개면 equality로 all_passed/all_verified:true가 된다. key link의 to 부재는 빈 문자열 포함 검사와 연결될 수 있다. 이 조건부 정적 경로는 실제 재현하지 않았다. primary의 CLI JSON 소비는 error/분모와 success를 닫힌 스키마로 강제하지 않으며 grep imported/used도 언어·동적 wiring 전체를 검증하지 않는다.

**테스트 품질·사람 방어.** 199–309는 requirement 연결 테스트의 skip, circular expected, provenance, assertion 강도, active case 수를 검토하며 blocker→gaps_found, 사람 항목 하나라도 있으면 human_needed를 우선한다. 실제 사람 시각/흐름/외부 서비스 확인 필요를 명시한 방어를 보존해야 한다. snapshot/baseline의 존재만으로 모든 regression test가 무효인 것은 아니므로 원문의 circular 규칙도 주장과 한계로 기록한다. 이 단계는 전 테스트 실행 명령이나 수집 receipt를 생성하는 runner가 아니며 미실행 코드의 VERIFIED는 실제 인수 PASS가 아니다.

**후속 소비.** 311–327은 나중 phase의 goal/criteria/name에 대응되면 gap을 deferred로 옮기고 상태를 재계산해 passed가 될 수 있다. 적법한 범위 분리와 현재 요구사항 미이행을 구분할 사람의 spec 변경 승인·revision binding이 없다. actual verifier 역할 494–543에도 human_needed 및 deferred 재계산이 있고, execute-phase 954–1116은 role을 직접 Task로 부른다. 이 caller에서 verify-phase.md를 직접 로드하는 연결까지는 확인하지 못했다(phase-prompt 603–610은 해당 문서를 참조). caller는 human_needed를 HUMAN-UAT partial로 보존하면서 사용자 approved 한 번으로 phase complete로 갈 수 있다. phase.cjs 652–719, 899–920은 검증 부채를 비차단 warning으로 취급하며 roadmap Complete와 결과를 기록한다. warning 존재를 배포 금지의 강제 gate라고 보지 않는다. PG 런타임 인수/승격 상태와 Git 정의의 phase 완료를 별도로 연결해야 한다.

<a id="i07"></a>
## 07 — verify-work.md

**사람 시나리오의 장점과 승인 한계.** 1–169는 사용자가 실제 관측하고 Claude가 기록하는 conversational UAT, SUMMARY에서 사용자 관찰 가능한 기대 결과 추출, cold-start smoke 추가를 정의한다. 다만 SUMMARY만으로 테스트를 뽑으면 미구현/누락된 원래 인간 시나리오가 분모에 빠질 수 있다. empty/next/yes를 pass로 해석하는 17·257–258은 명시적 경험 확인과 침묵을 구분하지 않는다. 이것은 이 검토의 동작 규칙이 아니며 Zeus에서 사람 승인으로 받아들일 근거도 아니다. cold-start의 서버 종료/임시 DB·cache 초기화는 실제 환경에서 영향이 있으므로 정확한 시험 target/격리가 필요한 선언이다. 이 검토에서는 실행하지 않았다.

**도구·상태 연결.** 89–123의 선택적 browser screenshot 자동 PASS는 시각적 checkpoint 일부만 자동 처리하며 사람 판단 항목을 남긴다. 이것이 Samsung 실기기 E2E 전체를 대체하지 않는다. 29–39는 init verify-work에서 uat_path를 기대하고 235–237은 그 경로로 render-checkpoint를 부른다. 실제 init.cjs 538–586 및 withProjectRoot 27–48에는 uat_path가 없고 phase-op 669–695에는 있다. create_uat_file에는 구체적 파일 작성은 있지만 이 변수 대입이 명시되지 않는다. 에이전트가 경로를 복구할 수 있다는 가능성과 계약 누락을 구분한다. renderer는 파일/path/current section을 검사하고 sanitizeForDisplay를 사용한다(uat.cjs 94–178). 이 범위에서 sanitizer 전체의 보안을 인증하지 않는다.

**partial와 안내의 충돌.** 254–338은 pass/skip/blocked/issue를 나누고 blocked를 코드 gap에서 제외한다. skip와 blocked의 자연어 조건이 겹치고 server라는 단어 포함만으로 실제 서버 bug가 prerequisite blocked로 분류될 가능성이 남는다. 365–377은 pending·blocked·이유 없는 skip이면 partial, issue나 이유 있는 skip도 resolved라면 complete로 계산한다. 따라서 complete 자체를 all pass라고 부르면 안 된다. 그런데 397–447의 결과 표는 blocked/pending을 보이지 않고 issues==0 경로는 partial 여부를 확인하지 않은 채 All tests passed/Ready to continue를 제시한다. security 파일 없음을 경고하면서도 next phase 링크를 제시하며 파일 존재·threats_open=0은 실제 보안 인수와 다르다.

**실제 parser와 실패 복구.** uat.cjs 181–209는 `result: (word)` 정규식으로 pending/skipped/blocked를 읽으나 workflow와 UAT template의 literal `result: [pending]`은 매칭되지 않는다. issue는 이 scanner에서 제외되고 별도 gaps pipeline으로 맡기는 설계다. VERIFICATION template 75–90의 `### N.` 사람 항목도 scanner 211–251의 table/bullet/numbered 평문 패턴과 다르다. audit는 items가 없는 파일을 결과에 넣지 않으므로 부재/미파싱과 해결됨을 분리해야 한다. 현행 renderer에는 malformed/complete 오류 방어가 있어 이를 감사 scanner 전체와 혼동하지 않는다. 원본 실행 0으로 정적 조건만 기록했다.

**수정 반복·지속성·Zeus 대응.** 450–648은 issue→parallel diagnosis→planner→checker 최대 3회 수정→force proceed 선택을 정의한다. force 선택 후 plan verified 문구로 향하는 경우 남은 문제의 예외 승인을 따로 남길 계약이 필요하다. 653–670은 issue 즉시/5 pass마다/완료 시에만 파일을 써서 중단 시 마지막 checkpoint 이후 결과 재질문이 생길 수 있으며 완전한 durable event log가 아니다. PG에 scenario/spec/build/device/actor별 append-only 측정과 재시도 id를 결속하고 Git E2E 정의로 환류할 후보지만 replay SDK나 실제 사용자 인수 구현을 이 문서에서 흡수 완료로 볼 수 없다.

<a id="trace"></a>
## 직접 지원 구간과 검색 한계

지원 원장에는 이번에 새로 읽은 CLI router, init/commit/config/model/path helper, UAT parser, phase-complete 일부, UI 역할/검증 역할, 관련 template, 여섯 skill 진입 문서를 기록한다. 모든 항목은 같은 pinned revision의 원시 blob/bytes/SHA와 exact line/range SHA로 결속된다. 과거 보고서의 의미 판정을 근거로 대체하지 않았다. metadata recorder 형식 재사용만 가능하며 원본 본문 재사용은 0이다. primary를 뒤에 다시 읽은 구간은 supporting 파일 수나 전문 분모에 중복 가산하지 않는다.

지정된 test/spec 경로에서 `cmdRenderCheckpoint`, `parseCurrentTest`, `cmdVerifyArtifacts`, `verify artifacts`, `render-checkpoint`, `ui_safety_gate`, workflow 파일명 등을 검색했으나 직접 test 본문을 확보하지 못했다. 처음 넓은 `uat` 검색은 unrelated evaluate/graduation까지 걸렸고 출력 제한도 있어 부재 증거로 쓰지 않는다. bin/install.js 경로 탐색은 디렉터리 없음 오류를 기록했고, phase-manifest/gsd-check-update 이름은 지정 JS/CJS/MD/JSON 검색에서 선언/manifest 참조만 보였다. 전체 tree에 어떤 테스트나 외부 installer도 없다고 주장하지 않는다. 실제 hook 등록·패키지 설치 구현·frontmatter parser 전체·권한 host 강제·lock/원자성·모든 후속 caller는 미독 범위다.

<a id="zeus"></a>
## 사용자 요구와 적응 경계

| 사용자 8단계 | 이 범위에서 얻은 후보 | 추가로 결속해야 하는 실제 증거 |
|---|---|---|
| 1 스펙 논의 | 원래 사용자 결정·goal·requirements와 관측 가능한 기대 결과 | SUMMARY 밖의 누락 시나리오, 인간의 범위·변경 승인, 고정 spec ID |
| 2 디자인 분석 | UI-SPEC, tokens·copy·registry 검수 | shadcn/Lucide 확정값·Storybook 상태·인터랙션·접근성·검토자 증거 |
| 3 코드 작성 | 계획·갭 수정·Nyquist 생성 테스트 | 구현 revision과 spec/scenario/테스트 정의 추적, 모델별 자격 |
| 4 자체 검증 | artifact/wiring/test 품질 점검, cold-start | actual runner 분모·실패·skip·환경·실서비스 경로 및 no mocked acceptance |
| 5 알파 배포 | 이 7개에 제품 alpha promotion 구현 없음 | immutable image·배포 target·health·rollback 실측 |
| 6 QA 및 증적 | conversational UAT·human_needed·partial | 명시적 실제 사람 승인, 빌드/환경/actor/시간/증적 해시, 돈 흐름 실패 경계 |
| 7 라이브 배포 | update는 하네스, undo는 Git 작업으로 분리 | 점진 배포 권한·stale 승인 무효화·PG 전이·동시성 fence |
| 8 CS 대응 | issue→진단→수정 계획·다음 검증 루프 | incident receipt·알림·로그→scenario→실제 E2E·복구 실측의 누적 |

AGENTS/research-standard의 Git 정의 정본 및 PostgreSQL 런타임 정본에 따라 `.planning` 문서·모델 선언·Git commit 존재를 PG 승인·실행 receipt와 등가로 취급하지 않는다. resolveModelInternal 1303–1334는 override/profile/alias/omit 선택을 구현하지만 Astra가 검증한 가드레일을 Sol에, 자격을 갖춘 Sol을 Terra에 전수하는 실행 자격 증거는 아니다. 역할 이름의 분리만으로 독립 검토자를 인증하지 않는다. 모델 자격·실제 Claude 검토는 parent가 별도로 수행할 범위다. 삼성 폰·태블릿의 실제 기기 단계는 유예이며 Device Farm SDK/MCP/live/replay를 구현하거나 실제 기기에서 검증했다고 주장하지 않는다.

<a id="unknowns"></a>
## 미완료와 후속 검증

7개 본문 미독은 0개다. 직접 지원에 명시하지 않은 구간과 전체 consumer/config/test 전이 폐쇄, 외부 installer/업데이트 hook/manifest writer, 실제 CLI·원본 tests, 오류/빈 분모/기기·OS·동시 변경·복구 실측은 미완료다. 원본 동작의 실행 관측은 이 보고서에 0건이다. 명명 테스트 부재 탐색과 메타데이터 검사를 upstream PASS로 계상하지 않는다.

라이선스·출처/저작권·dependency 적용 가능성, 외부 최신 자료 검증, 독립 actual Claude, OS/모델 자격, 실제 사람 인수, 전체 분석과 채택 승인 모두 false다. parent의 추후 별도 격리 관측을 연결하려면 그 실제 receipt와 고정 revision을 새 근거로 구분해야 한다. 이 폴더는 bounded 정적 검토 checkpoint이며 Zeus 구현·배포·현재 운영 결함 재현 또는 흡수 등가 인증이 아니다.

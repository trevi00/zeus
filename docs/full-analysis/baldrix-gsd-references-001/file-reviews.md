# 파일별 독립 정적 검토

<a id="file-01"></a>
## get-shit-done/references/agent-contracts.md

1–79 전문. 역할별 H2 완료 marker와 PLAN/SUMMARY handoff 필드를 정리한다. 대소문자·marker 없음·PARTIAL/ESCALATE 차이를 보존한 점은 유지 후보지만 문서의 what IS 주장은 실제 구현 대조 전 정본이 아니다. executor PLAN COMPLETE를 regex로 검사하지 않고 SUMMARY 존재와 Git 상태 spot-check로 대신한다는79행은 자기 보고와 실제 완료의 간극을 직접 드러낸다. 요구 ID·task hash·독립 수행자·실행 원시 결과·사람 인수 사건은 schema에 없다. Zeus는 문자열 marker를 라우팅 힌트로만 받고 Git 정의/PG 실행 상태의 검증된 전이를 별도로 둬야 한다. 명명된 역할 전체와 parser 전이 폐쇄·시험 실행은 미완료다.

<a id="file-02"></a>
## get-shit-done/references/artifact-types.md

1–113 전문. core/extended/standing artifact의 위치·생명주기·소비자를 열거하고 소비되지 않는 문서는 inert라고 명시한다. 이는 유용한 연결 검토 출발점이지만 STATE·REQUIREMENTS 완료·HANDOFF는 mutable 파일이며 replacement 뒤 과거 세대 보존·fencing·서명/해시가 없다. DISCUSSION-LOG는 인간만 읽고 자동 workflow 미소비라 자동 승인 근거가 될 수 없다. HOME Claude의 USER-PROFILE은 프로젝트 밖 의존이고 METHODOLOGY를 로드하는 것만으로 실제 추론 적용은 증명되지 않는다. Bayesian 예시의 반증 질문은 유지하되 Confident 명칭은 사실 승인으로 쓰지 않는다. Zeus에서는 Git 정의와 PG 사건/승인을 분리하고 문서들은 파생 view로 변형한다. 초기 printer cp949 오류 뒤 UTF8로 전문 재독했으며 소스 실행은 아니다.

<a id="file-03"></a>
## get-shit-done/references/checkpoints.md

1–778 전문. ca5f9f 출력의 중간 절단을280–340 재독(f8b8d5)으로 닫았다. human-verify/decision/human-action XML과 구체 URL·기대 결과·준비된 환경·오류 시 멈춤을 제시한다. 하지만11행 auto mode는 human-verify 자동 승인, decision 첫 옵션 자동 선택으로 blocking gate와278행 실제 응답 대기를 우회한다. 기능/접근성/핵심 사용자 흐름을 인간 판단으로 분류한 취지를 스스로 무효화하므로 Zeus 사람 인수에 채택할 수 없다. CLI 가능 여부는 배포·비밀 처리·전역 설치·DB seed·포트 점유 프로세스 종료 권한이 아니며 인증 성공도 원래 작업 승인과 다르다. fetch200/ready 문자열은 정확 서비스 revision이나 기능 성공을 보장하지 않는다. timeout/bash/lsof/xargs 예시에 cross-platform fetch만 넣어도 Windows 동등성이 성립하지 않는다. npx를 no install로 분류하거나 vendor 가격·curl Windows 결함을 일반화한 주장도 원문/환경 미확인이다. 실제 사람 핵심 시나리오와 환경 준비는 유지 후보지만 exact artifact/revision/확인자/실패·skip 사건에 결속하고 auto 승인과 분리해야 한다. 예시 자동화·외부 호출·credential 접근0.

<a id="file-04"></a>
## get-shit-done/references/common-bug-patterns.md

1–114 전문. null/boundary/async/state/import/type/env/data/regex/error/closure의 구체 후보와 증상 매핑이다. 각 hit를 가설로만 보고 증거로 제거/확인하라는97행은 유지 후보다. 전 기술 stack의 약80%를 다룬다는 빈도 주장에는 분모·자료가 없다. JS 중심 예시를 Python/Windows/Linux에 보편 적용하면 오탐하며 OS 경로 대소문자도 파일시스템 설정에 따른다. 문자열 스캔은 동시성·권한·실제 callgraph 전체를 검사하지 않는다. Zeus에서는 SDD 결함 후보 분류로만 사용하고 실행 근거·반증·PG 사건·회귀/사람 인수를 별도로 보존한다. 시험·빈도 검증 미실행이다.

<a id="file-05"></a>
## get-shit-done/references/context-budget.md

1–49 전문. context_window_tokens 설정에 따라500k 미만이면 SUMMARY/VERIFICATION/RESEARCH 전문 금지, 큰 모델이면 허용한다. PEAK tier의 body/inline 허용과 보편 금지 조항은 충돌하고 설정 숫자가 실제 모델 context 자격을 증명하지 않는다. subagent_type 자동 로드를 이유로 역할 MD를 절대 읽지 말라는 규칙은 generic prompt 호출 및 원문 전수 감사에 부적합하다. 마지막의 orchestrator는 의미 검증 불가능하고 구조만 검사한다는 단정은 독립 검수의 책임을 축소한다. 미완료·누락·모호화 경고는 유지하되 Zeus는 immutable checkpoint와 미독 분모로 이어 읽고 요약을 전문 검토로 승격하지 않는다. 토큰 측정·실제 역할 자격·전이 검사 미완료다.

<a id="file-06"></a>
## get-shit-done/references/continuation-format.md

1–249 전문. 다음 phase/plan의 이름·목적·선택지를 ROADMAP/PLAN에서 가져오는 표시 템플릿이다. 예시 3/3 executed, all shipped는 실행 영수증이 아니며 표시 형식 자체에 상태 검증이 없다. /clear를 항상 먼저 요구하지만 immutable handoff 저장·revision·남은 worker/실패의 인계는 필수가 아니다. inline command가 clickable이라는 주장도 client 종속이다. Zeus에서는 연속성 UI로 변형하되 PG의 실제 잔여 작업과 Git 정의를 읽어 표시하고 context 초기화 전 artifact 핸들을 보존한다. 명령 존재·실제 클라이언트 동작·인수는 미확인이다.

<a id="file-07"></a>
## get-shit-done/references/decimal-phase-calculation.md

1–64 전문. phase next-decimal CLI의 next/base_phase 및 gap 뒤 max+1 예시, generate-slug와 mkdir 조합이다. 두 번 별도 조회하면 동시 phase 삽입 사이 값이 달라질 수 있고 계산 후 디렉터리 생성은 예약·중복 방지가 아니다. --raw scalar/--pick 필드의 실제 구현·잘못된 base/다중 소수/정렬은 직접 대조가 필요하다. HOME Claude/Bash 경로는 Windows 네이티브와 다르다. Zeus는 사람용 phase label과 불변 요구/작업 ID를 분리하고 PG unique constraint·세대 예약 및 Git 정의 변경 검토에 결속한다. 원문 CLI/mkdir 실행0.

<a id="file-08"></a>
## get-shit-done/references/domain-probes.md

1–125 전문. auth/realtime/dashboard/API/DB/search/upload/cache/testing/deployment 키워드별 질문 후보이며2–3개를 선택한다. TTL·권한·경합·rollback·인수 범위를 발견하는 질문은 유용하지만 답을 저장하는 schema·요구 ID·누락 분모·사용자 승인 계약이 없다. mock/container와 coverage gate 선택은 질문일 뿐 실제 검사나 무mock 사람 인수를 보장하지 않는다. 플랫폼 이름은 자격 확인 없이 추천으로 채택하지 않는다. Zeus에서는 8단계 SDD 요구 발견 후보로만 사용하고 Git 요구 정의/PG 답변·승인 및 실제 핵심 시나리오를 연결한다. 직접 소비/모델 실행·외부 사실은 미완료다.
<a id="file-09"></a>
## get-shit-done/references/few-shot-examples/plan-checker.md

1–73 전문. 모호한 action과 same-wave 파일 충돌을 blocker로, empty/echo verify를 실패 구분 불가능으로 제시한다. 검사명·구체 대상·수정 후보는 유지할 수 있지만 예시의 경로/line은 합성 입력이며 실제 실행 영수증이 아니다. last_calibrated 날짜만 있고 corpus/hash/수행 모델·정확도 측정이 없다. task3개 허용은 개인 취향 오탐을 줄이나 규모 숫자가 실제 난도/분모를 대신하지 못한다. Zeus에서는 검수자 자격 평가의 후보 문항으로 분리하고 오라클을 독립 정의·실제 출력과 결속한다. calibration/모델 실행0.

<a id="file-10"></a>
## get-shit-done/references/few-shot-examples/verifier.md

1–109 전문. 존재·실질·연결의3단계, 잘못된 regex 입력, config schema/default/consumer 차이와 개별 기준 증거를 강조한다. 원문에 Ran/PASSED가 있어도 이 파일은 예시이며 실행으로 계상하지 않았다. grep 무hit만으로 동적 import까지 orphan이라고 단정하거나 schema 미등록이면 strip한다는 추론은 구현 대조가 필요하다. 전체 must-have가 미충족인데 계획 이후 생긴 gap이라는 이유로 PASS_WITH_NOTES를 주는73행은 담당자 책임 평가와 최종 요구 인수를 혼동한다. corpus80%/8gaps/37%는 raw corpus·revision·모델 자격 미확인이다. Zeus는 결함 발생 책임과 현재 SDD 요구 충족을 별도로 기록하고 changed source의 기존 승인을 무효화한다.

<a id="file-11"></a>
## get-shit-done/references/gate-prompts.md

1–100 전문. header12자·single select·Other 처리 및 approval/retry/skip/override/accept-gaps 양식을 정의한다. 결정 선택지를 명확히 하는 UI 후보지만 표시가 권한 강제는 아니다. stale Continue anyway와 verification Accept gaps는 exact revision·위험 소유자·허용 가능한 예외·유효기간 없이 사용하면 미검증을 승인으로 승격한다. Let Claude decide는 위임 범위와 모델 자격이 없다. 질문 도구의 옵션/길이 제한은 runtime 종속이며 자유 응답이 승인인지 수정 요구인지 별도 판별해야 한다. Zeus는 PG 승인 사건과 Git 정책을 결속하고 skip을 완료 분모에서 숨기지 않는다. 실제 UI/승인/도구 호출0.

<a id="file-12"></a>
## get-shit-done/references/gates.md

1–70 전문. preflight/revision/escalation/abort 분류와 단계별 행렬이다. 실패 때 상태 보존·iteration cap·남은 이슈 전달은 유지 후보지만 파일 존재 preflight로 No partial work created를 일반 보장하지 못한다. issue count 비감소를 stall로 간주하면 severity·새로 발견한 독립 결함·부분 진전이 사라진다. 분류/행렬은 실제 상태 머신·권한/세대·rollback 구현 증거가 아니다. Zeus는 entry 정의·실행 결과·독립 검수·사람 인수의8단계 전이별 guard와 PG receipt로 변형한다. caller 전체/실제 gate 시험은 미완료다.

<a id="file-13"></a>
## get-shit-done/references/git-integration.md

1–295 전문. task별 commit·plan metadata·WIP 및 subrepo prefix 라우팅을 제안한다. 정확 파일 stage와 실패 위치 식별은 유용하나 .git 디렉터리 검사29행은 worktree의 .git 파일을 놓치고 silent init으로 이어질 수 있다. parallel --no-verify 뒤 orchestrator hook 검증은 실제 연결 확인 전 강제가 아니다. PLAN/RESEARCH 생성 commit 금지와 별도 planning-commit/revision 문서의 즉시 commit이 충돌한다. RED 실패 test commit과 working-code-only 주장, 각 commit 독립 revert/bisect 가능 주장도 무조건 성립하지 않는다. reset --hard·branch 삭제는 권한/dirty/stale 방어 없이 자동 회복으로 채택 불가다. subrepo별 성공은 전체 다중 repo 원자성/인수를 보장하지 않고 config load가 설정을 자동 재작성한다는 부작용도 있다. Zeus에서는 Git 정의를 실행 전에 pin하고 PG 실행/승인 사건을 별도로 유지한다. Git/CLI 실행0.

<a id="file-14"></a>
## get-shit-done/references/git-planning-commit.md

1–38 전문. CLI가 commit_docs/gitignore를 검사하므로 수동 분기가 필요 없다는 호출 계약이다. skipped 반환은 실제 commit 성공이 아니고 호출자가 구분해야 한다. 빈 메시지 --amend는 이전 commit identity·공유 여부·다른 staged 파일 경계를 보장하지 않는다. plan-phase create-plans commit 예시는 git-integration의 생성 시 commit 금지와 다르다. glob은 Bash와 Windows argv 확장 차이가 있다. Zeus에서는 정의 변경을 exact base/대상/승인에 결속하고 skipped·failure·success를 PG 사건으로 분리한다. 구현 직접 지원과 실패 전파·인수는 별도로 기록한다.

<a id="file-15"></a>
## get-shit-done/references/model-profile-resolution.md

1–38 전문. config grep pipeline으로 profile을 한 번 정하고 Task model에 전달한다. pipefail 없는 pipeline은 마지막 tr 성공으로 missing config에서도 echo balanced fallback을 실행하지 않아 빈 문자열이 될 수 있다. JSON 파싱도 아니며 복수 key/중첩/escape를 구분하지 않는다. inherit는 실제 부모가 opus임을 보장하지 않는데 opus-tier 우회로 설명한다. 한 번 읽은 설정은 중간 policy/revision 변경을 반영하지 않는다. Zeus에서는 provider/model exact ID·기능/자격·정책 revision·위임 scope를 dispatch 직전 검증하고 PG receipt에 실제 사용 모델을 기록해야 한다. shell/model 실행0.

<a id="file-16"></a>
## get-shit-done/references/model-profiles.md

1–145 전문. quality/balanced/budget/adaptive/inherit 및 override/omit를 설명한다. cost/quality 배치는 corpus 없는 경험적 주장이고 mapper에 reasoning 불필요라는139행은 전수 의미 검토와 맞지 않는다. explicit alias→inherit가 부모 opus라는 가정, non-Claude installer omit 기본과 inherit 필수의 서로 다른 경로를 구분해야 한다. override에 임의 provider ID 허용은 자격·조직 승인·실제 사용 모델 검증이 아니다. 문서12역할 표와 실제 등록 표의 동등성, 설치 원문은 직접 대조 전 미확인이다. Zeus는 사용자 지정 고성능 작업/독립 검수 자격을 비용 profile과 분리하고 evidence-bound delegate 계약으로 변형한다. 실제 모델/가격/installer 실행0.

<a id="file-17"></a>
## get-shit-done/references/phase-argument-parsing.md

1–61 전문. 첫 숫자·flag·잔여 description을 추출하고 find-phase/roadmap으로 정규화·존재를 확인한다. legacy printf의 선행0 숫자는 shell의 octal 해석에 영향받고 invalid 입력은 그대로 남을 수 있다. found가 정확 false일 때만 실패하므로 명령 실패/빈 결과/parse 오류는 통과 가능하다. directory와 roadmap 두 정본이 달라질 때의 상태는 없다. --raw 출력 shape·custom phase·다중 소수·동시 생성은 구현 대조 대상이다. Zeus는 불변 ID와 표시용 phase를 분리하고 실패한 lookup을 fail closed로 다룬다. Bash/Windows 실제 실행0.

<a id="file-18"></a>
## get-shit-done/references/planner-gap-closure.md

1–62 전문. VERIFICATION gaps/UAT diagnosed를 모아 기존 plan 다음 번호·artifact/concern/dependency로 묶고 autonomous gap_closure PLAN을 쓴다. deferred는 무조건 무시하므로 누가 어떤 요구를 언제 승인해 연기했는지 확인하지 않으면 분모가 축소된다. grep status 문자열은 실제 diagnosis·사람 인수 실패 증거가 아니고 SUMMARY는 코드 정본을 대신하지 못한다. next 번호·wave 계산은 동시 예약/순환 의존 검증을 제시하지 않는다. Zeus에서는 gap과 승인된 defer를 별도 불변 요구 ID/PG 사건으로 유지하고 closure에 실제 회귀·핵심 사람 시나리오를 요구한다. 원본 생성/시험0.

<a id="file-19"></a>
## get-shit-done/references/planner-reviews.md

1–39 전문. REVIEWS 피드백으로 새 계획을 만들며 HIGH consensus 필수, MEDIUM2명 이상 우선, 개인 제안은 consider로 분류한다. reviewer 수·합의는 독립성/자격/증거 강도가 아니다. 단독으로 발견한 심각 결함을 약화할 수 있다. 기존 계획·요구 ID/승인·폐기 이력 보존 없이 fresh replan하면 추적이 끊긴다. addressed/deferred 표는 유지 후보이나 계획 task가 있다는 사실은 실제 결함 해결이 아니다. Zeus는 consensus와 증거 타당성을 구분하고 source/target revision 및 개별 검수자 lease와 실제 인수 결과를 결속한다. 실제 reviewer/시험0.

<a id="file-20"></a>
## get-shit-done/references/planner-revision.md

1–87 전문. structured issue별 최소 수정·wave 재계산·미해결 표·N/M를 요구한다. 그러나 체크박스 No new issues는 재검사 oracle이 아니고 수정 후 commit 결과 확인 없이 REVISION COMPLETE를 반환할 수 있다. issue schema description/fix_hint는 revision-loop의 finding/suggested_fix와 달라 소비자 정규화가 필요하다. glob으로 전체 plan을 읽고 stage해 동시 변경·비대상 변경·미완료 plan 포함 가능성이 있다. Zeus는 revision 변경을 기존 승인 무효화와 연결하고 독립 재검수·실제 요구 인수 완료를 별도 유지한다. 실행0.

<a id="file-21"></a>
## get-shit-done/references/planning-config.md

1–432 전문. planning/git/workflow/model/search/manager 설정과 자동 migration·subrepo 동기화를 설명한다. complete generated table이라는221행은 생성기·동등성 확인 없는 선언이다. context_window와 context-budget의 context_window_tokens가 다르고 model_profile 허용 목록에 adaptive가 없다. gitignore는 config와 무관하게 false라는73행과 명시값이 항상 우선인333행이 상충한다. config load가 depth/subrepos를 자동 저장한다면 읽기가 부작용 없는 관측이 아니다. branch fallback은 base identity/dirty/동시 권한을 닫지 않고 squash뒤 branch삭제는 전체 개발 이력을 보존하지 않는다. false use_worktrees와 timeout 숫자는 프로세스 격리/종료 증명이 아니다. @file 출력도 immutable handle이 아니라 mutable 경로다. Zeus는 Git 설정 정의와 PG 활성 정책/실행 상태를 분리하고 schema/default/consumer/실행 연결이 모두 닫힐 때만 변형한다. 생성물로 제외하지 않고 전문 검토했으며 generator 동등성·외부/OS 실행은 미완료다.

<a id="file-22"></a>
## get-shit-done/references/questioning.md

1–162 전문. 열린 질문→구체 시나리오·누구/왜/done→PROJECT 작성 동의를 요구한다. 자유 응답을 선택하면 메뉴를 멈추는 방식은 사용자 의도 보존 후보지만 목적 발견과 요구 계약을 구분한 만큼 이 단계 자체가 인수 조건 승인이라는 주장은 불가하다. 머릿속4개 checklist는 미해결 요구·안전/운영 제약 분모를 저장하지 않는다. 기술 경험 절대 묻지 않음은 실제 사용자의 접근성·운영 책임 확인까지 막는 보편 규칙으로 채택하지 않는다. Zeus는 대화 요약을 Git 요구 후보로 옮겨 사용자 확인/변경 이력을 PG에 결속한다. UI 도구 제약·실제 사용자 확인은 미검증이다.

<a id="file-23"></a>
## get-shit-done/references/revision-loop.md

1–97 전문. initial checker 후 최대3회 revision,4번째 issue 검사에서 escalation하며 count 비감소면 일찍 멈춘다. max3은 checker 실행3회를 뜻하지 않는다. INFO는 무조건 허용하고 WARNING은 feasible/전부처리/정당화 가능 지시가 섞여 있다. 동일 count에도 심각도가 줄거나 새 결함을 발견할 수 있어 count만으로 stuck을 단정할 수 없다. raw YAML inline은 exact bytes/revision/신뢰 경계를 보존하지 않으며 Proceed anyway는 실제 해결과 다르다. Zeus는 bounded 재시도·미해결 공개를 유지하고 개별 issue ID/세대/심각도/검증 결과와 승인된 예외를 분리한다. 동일 fresh spawn이 독립 모델 자격을 보장하지 않는다. 실제 loop 실행0.

<a id="file-24"></a>
## get-shit-done/references/tdd.md

1–263 전문. 행동 중심 RED 실패→GREEN 성공→REFACTOR 회귀, 실패 시 조사·무관 시험 깨짐도 중단하는 방어는 유용하다. RED가 의도한 assertion 때문인지 import/환경 오류 때문인지 영수증 구분이 없다. empty suite가0tests PASS라고 일반화한172행은 framework별 no-tests exit 차이를 무시한다. 설치/전역 pip·npm 명령은 격리/lockfile/권한 조건이 없고 TDD 제외에 migration/config/glue를 포함해도 그 검증을 제외할 수는 없다. 2–3commit 존재나40%context는 품질 오라클이 아니다. Zeus는 Git 행동 계약과 PG 실제 argv/exit/stdout·fixture/mock 경계/회귀·사람 인수를 연결한다. 예시 시험/설치 실행0.

<a id="file-25"></a>
## get-shit-done/references/thinking-models-debug.md

1–44 전문. fault tree→가설 예측/시험/관측·한 변수 반증은 유지할 방법 후보지만 한 번 결과 불일치=ELIMINATED, targeted 변경에도 재현=가설 틀림은 nondeterminism·복합원인·불완전 intervention을 무시한다. stacktrace에 위치가 있으면 즉시 fix하는 예외는 원인 규명과 다른 층이다. 빈도/외부 catalog150+ 주장은 원문 미확인이다. Zeus의 diagnose-only/승인된 probe와 충돌하지 않도록 실행 요청·불확실성·원시 결과를 PG 사건으로 분리한다. 외부 링크/실제 probe0.

<a id="file-26"></a>
## get-shit-done/references/thinking-models-execution.md

1–50 전문. scope 경계·왜 존재하는 코드인지 확인·컴파일 시 error handling 강제는 유지 후보지만 plan의 done이 유일한 정답이라는33행은 사용자 요구 누락/잘못된 oracle까지 합리화할 수 있다. 결정이 없으면 checkpoint로 보내는 규칙은 자동 결정 예외와 대조해야 한다. 기존 패턴 복사 전에 이유를 확인하라는27행과 명확한 패턴이면 그대로 따르라는48행이 달라 위험 기준이 필요하다. 버전 변경을 기계적인 trivial edit로 일반화하면 의존성/보안/OS 영향이 누락된다. Zeus는 승인된 Git scope와 실제 PG 실행 guard를 강제하고 plan을 운영 권한으로 쓰지 않는다. 외부 원문/실행0.

<a id="file-27"></a>
## get-shit-done/references/thinking-models-planning.md

1–62 전문. constraint 우선·premortem·요구 단위MECE·가역성·명확한 action과 LOW caveat 처리는 유용하다. 요구를 정확히 한 task에만 매핑하면 복수 검증/통합 작업의 기여가 사라질 수 있고 같은 파일의 다른 section은 동시 쓰기 안전 보장이 아니다. HIGH research면 불확실성 해소라는60행과 config/version/doc에는 실패 양상이 없다는62행은 검증되지 않은 shortcut이다. 한 번 why로 root cause를 확정할 수 없다. Zeus는 요구 ID별 여러 evidence edge와 검토·실행·사람 인수 단계, Git 정의 변경/PG 세대 검증을 유지한다. 외부 catalog/실제 plan 검증0.

<a id="file-28"></a>
## get-shit-done/references/thinking-models-research.md

1–50 전문. 제약부터 분해·version/workload별 상충 분리·반대 근거·대안 강화를 요구한다. source count보다 설명 가능성을 보지만 negative evidence를 무조건 더 무겁게 두거나 criticism이 없으면 검색 실패라고 단정하면 다른 편향이 생긴다. locked choice는 존중해야 하나 반증된 위험/폐기된 버전의 보고까지 막아서는 안 된다. codebase-only에는 reasoning 가치가 없다는50행은 실제 의미·전이 감사와 충돌한다. Zeus에서는 discovery/전문 원문 취득/독립 검수/제안·인수를 분리하고 반증과 provenance를 PG/Git에 결속한다. 외부 검색/네트워크0, 원문 라이선스 미확인이다.

<a id="file-29"></a>
## get-shit-done/references/thinking-models-verification.md

1–55 전문. 실패 가능성·오도하는 test·미검사 error path를 찾고 purpose unknown은 보존하라는 방어가 있다. 반면 매번 하나씩 반드시 찾으라는 지시는 사실 없는 결함 생성 압력이 되고, deviation에 맞춰 must-have를 재해석하는20행은 독립 승인 없이 oracle을 낮출 위험이다. 이전 PASS는 존재/basic sanity만 재검사하라는52행은 source/의존/정책 변경 시 무효화를 누락한다. exit0/testPASS 즉시 수용과 INFO무조건허용도 실제 분모/skip/mock·심각도 오분류를 놓친다. Zeus는 요구 정의 변경을 Git 승인으로 분리하고 exact revision의 독립 evidence·실제 사람 인수까지 검증한다. 실행0.

<a id="file-30"></a>
## get-shit-done/references/thinking-partner.md

1–96 전문. opt-in config와 영어 keyword/구조 신호에 따라3–5bullet inline tradeoff를 제공한다. 명시적 사용자 선택 존중은 유지 후보지만 확장 thinking이 실제 모델 옵션/자격으로 설정된다는 구현은 없다. 영어 or/versus 탐지는 한국어·중의성에 취약하고 brief 추천은 원문 전수 research가 아니다. explore 연결은 #1729 이후 예정이라고 명시되어 현 호출로 계상하지 않는다. Zeus는 조건부 UX 후보로만 두고 모델 자격·Git 결정·PG 사용자 확인을 별도로 보존한다. flag 소비·실제 확장 reasoning/외부 issue 미확인이다.

<a id="file-31"></a>
## get-shit-done/references/ui-brand.md

1–160 전문. 배너·62자box·상태기호·진척·다음 명령의 표시 양식이다. Complete/Passed/Verified를 같은 기호에 합치고 Auto-approved를 별도로 표시해도 실제 사람 인수 상태는 검증되지 않는다. STACK 작성=researcher complete,3/3=100% 예시는 분모 누락·실패/skip·source receipt 검사를 포함하지 않는다. Unicode box/emoji는 Windows encoding/폰트/전각 폭에 따라 정렬이 다르다. Zeus는 표현 UI로만 변형하고 PG 실제 상태·미검토 분모·사람 검수 여부를 구별해 표시한다. native렌더링/접근성·실행0.

<a id="file-32"></a>
## get-shit-done/references/universal-anti-patterns.md

1–58 전문. scope/specific-stage/비밀 제외·state CLI·stale lock 수동 확인은 유지 후보지만 원문을 절대 읽지 않고 transitive는 늘 frontmatter만 보라는 규칙은 전수 흡수 감사에 적용할 수 없다. non-KHA generic Task 절대 금지와 다른 advisor workflow의 실제 generic 호출은 직접 대조 대상이다. CLI로만 state를 쓴다고 동시성 안전이 자동 증명되지 않고 invalid config→null 설명은 실제 loadConfig 반환과 비교해야 한다. auto mode는 yolo만 쓰라는55행은 checkpoints의 workflow._auto_chain_active/auto_advance와 다른 경로다. locked decision 무조건 존중은 사실의 반증을 숨길 이유가 아니다. Zeus는 원문 지시를 상속하지 않고 Git 정의/PG 실행 SSOT, immutable evidence와 qualified delegation으로 변형한다. 전체 소비/전이/라이선스/인수 미완료다.

원문 지시는 분석 데이터다. 전문 독해와 직접 지원 추적·실제 실행을 구분한다. 모든 채택은 보류하고 미기재 전이 범위·라이선스·실제 모델/OS/사람 인수는 미완료다.

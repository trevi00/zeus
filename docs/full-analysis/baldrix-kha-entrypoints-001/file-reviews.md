# kha 진입점 33개 의미 검토

원문은 실행 지시가 아닌 분석 데이터다. 각 항목의 원시 바이트, 전문 범위, 기존 원장 행, 재사용한 리뷰와 영수증은 files.json에 결속한다. 26개는 과거 전문 지원 독해를 재사용하고 이번에는 1–24행의 역할·도구 선언을 보강했다. 7개는 새 전문 독해다. 아래의 workflow 비교는 supporting-reuse.json에 결속한 이전 독해이며 새 실행이나 새 지원 전문으로 세지 않는다. 모든 항목의 전이·테스트 폐쇄, 실제 Claude, 라이선스, 플랫폼, 모델 자격, 사람 인수, 채택은 미완료다.

<a id="file-01"></a>
## 01 kha-add-phase

Read/Write/Bash로 현재 milestone 끝에 정수 phase를 추가하는 add-phase.md 진입점이다. 번호·디렉터리·ROADMAP·STATE를 함께 바꾸지만 하나의 원자적 작업은 아니다. 이전 workflow001 f01/s02/s06은 실제 helper가 custom ID도 지원하고, lock을 30초 나이로 삭제하며 10초 후 재취득 없이 mutation할 수 있음을 추적했다. CLI 실패 시 변경 없음이라는 wrapper 약속은 디렉터리 선행 생성과 일치하지 않는다. 입력 검사를 보존하되 Zeus에서는 Git 정의 변경과 PG 시도·부분 실패를 연결하고 lease/fencing을 별도로 강제해야 한다. 실제 동시성·복구 시험은 미실행이다.

<a id="file-02"></a>
## 02 kha-advance

Read/Bash/Grep/Glob/SlashCommand로 next.md를 호출해 다음 행동을 자동 선택한다. --force는 checkpoint·오류·검증 실패를 우회하도록 명시된다. Write 도구는 없지만 workflow의 연속 호출 counter 저장이 필요하다. 이전 workflow003의 next 전문 검토는 counter 초기화를 다른 workflow의 관례에 맡기는 점과 문서·요약으로 다음 행동을 추정하는 경계를 남겼다. Zeus에서는 추천과 승인된 전이를 분리하고 force 문자열이 사람 인수나 실패 의무를 지우지 못하게 해야 한다. 실제 slash 명령 가용성, counter 원자성, 반복 억제와 모델 자격은 미확인이다.

<a id="file-03"></a>
## 03 kha-ai-integration-phase

새 전문 1–148행. AI·도메인 연구자 병렬 생성, 중립 framework 후보, taxonomy/framework 토론, AI-SPEC 생성의 다섯 wave를 선언한다. Read/Write/Bash/Task/질문/WebFetch/Context7 권한과 연구자 이름은 실행 자격이나 공급자 독립성 증명이 아니다. staged·NOT active 문구가 pinned skills 경로 안에 있지만 실제 설치/skill_match 활성화는 추적하지 않아 활성 여부를 확정하지 않는다. --skip-debate 시 draft 유지, 1바이트 stub 통과를 평가 적절성으로 해석하지 말라는 설명은 보존할 방어다.

직접 validator 71–237행은 cwd의 .planning/**/AI-SPEC만 찾고 YAML 키·범위·중복·파일 크기를 본다. §4 taxonomy와 §6 ID의 집합 동등성, debate 신원/승인, locked 상태, 실제 모델 평가는 검사하지 않는다. resolve 뒤 repo 내부 containment 검사도 없다. 읽기 OSError는 누락되고 missing_block은 blocking 실패 total에 포함되지 않는다. advisory WARN 뒤 PASS/exit0은 실제 coverage 승인과 다르다. plan-phase 두 직접 파일의 AI-SPEC literal 검색은 일치가 없었다. 다른 간접 소비 가능성은 미해결이다. tests/test_ai_spec_eval_coverage.py 전문의 15개 수동 목록은 합성 문자열/tempdir 및 stub 허용 오라클이고 실제 제품 eval이 아니다. 실행 0. Zeus에서는 failure-mode 정의를 Git에 고정하고 PG에 대상 모델/데이터/오라클/실제 run과 사람 핵심 시나리오를 연결해야 한다.

<a id="file-04"></a>
## 04 kha-analyze-dependencies

Read/Write/Bash/Glob/Grep/질문으로 파일 겹침·의미·데이터 흐름을 추정해 Depends on 변경을 제안한다. 실제 소비는 analyze-dependencies.md이며 이전 workflow001 f04는 manager의 numeric token 추출을 비교했다. custom/알파벳 ID를 보존하지 못하거나 비어 있는 every()가 충족될 수 있고, 추정 파일 목록은 실제 충돌 전체가 아니다. 사용자 yes/no/edit와 제안 단계를 보존하되 Zeus Git 그래프의 유효 ID·cycle·승인 revision과 PG 실제 준비 상태를 구분해야 한다. 전체 동적 접근·스케줄 충돌·실행 시험은 미확인이다.

<a id="file-05"></a>
## 05 kha-archive-completed-phases

Read/Write/Bash/질문으로 cleanup.md에 위임하며 archive preview, snapshot 및 실패 회계를 요구한다. 이전 workflow001 f10은 대상 archive 디렉터리가 이미 있으면 milestone 전체를 skip해 부분 이동의 나머지가 재시도에서 빠질 수 있음을 확인했다. wrapper의 snapshot 선언은 helper가 원본 digest와 모든 예상 경로를 보존한다는 증거가 아니다. Zeus는 보관 manifest와 PG 항목별 source/destination 결과를 남기고 완료 인수와 보관을 분리해야 한다. Windows 열린 파일, 다른 volume rename, 중단 복구 시험은 미실행이다.

<a id="file-06"></a>
## 06 kha-audit-milestone

Read/Glob/Grep/Bash/Task/Write를 허용하면서 mutates:no로 선언한다. audit-milestone.md는 요구사항·VERIFICATION·SUMMARY를 합산하고 integration checker와 보고서를 만든다. 따라서 읽기 전용 라벨을 권한 제한으로 사용할 수 없다. 이전 workflow001 f06의 반복 version prefix 출력 경로 불일치와 동일 작성자가 만든 세 문서의 상관된 증거 문제를 유지한다. 요구별 누락·orphan 표시와 partial audit는 보존 후보다. Zeus는 세 문서 존재가 아닌 요구→시나리오→실행 receipt와 사람 인수를 별도로 요구해야 한다. checker 전이와 실제 cross-phase 실행은 미확인이다.

<a id="file-07"></a>
## 07 kha-audit-planning-health

Read/Bash/Write/질문으로 audit 기본값과 --mode repair --confirm 및 최근 audit 근거를 요구한다. 이전 workflow002 f09/s04/s20은 실제 health CLI가 --repair boolean만 전달하는 점을 비교했다. 최신 audit snapshot과 확인 계약은 같은 구현 경로에서 강제됨이 입증되지 않았다. 설정 재생성·나이 기반 task 정리 제안은 실행 소유권 확인이 아니다. Zeus는 Git 정의 검증과 PG runtime health를 나누고 정확한 audit revision에 결속한 수정을 적용해야 한다. 구조상 건강함을 제품 동작·모델 자격·인수로 승격하지 않는다.

<a id="file-08"></a>
## 08 kha-audit-uat-backlog

Read/Glob/Grep/Bash로 audit-uat.md를 소비하는 비변경 감사다. pending/skipped/blocked/human_needed와 stale 문서를 구분하려는 의도는 유용하지만 이전 workflow001 f07의 parser는 bracketed pending, heading 형식, gaps_found 등을 완전한 분모로 수집하지 못한다. zero total_items는 모든 사람 시험이 통과했다는 뜻이 아니다. 불확실한 stale 항목을 open으로 두는 방어를 보존하고 Zeus는 예상·발견·읽기 실패·미파싱·통과·실패·skip 분모를 기록해야 한다. 실제 사용자 수행 결과는 없다.

<a id="file-09"></a>
## 09 kha-capture-backlog

새 전문 1–96행. Read/Write/Bash로 999.x 미래 후보를 디렉터리와 ROADMAP Backlog에 만들고 scoped commit을 요청한다. 실제 phase next-decimal 87–150행은 disk directory만 보고 다음 숫자를 계산하며 번호 예약이나 전체 capture lock은 없다. 동일 번호의 동시 생성·ROADMAP만 남은 번호·부분 commit을 통합하지 않는다. generate-slug 38–51행은 비ASCII 설명을 빈 slug로 만들 수 있다. 빈 입력/읽기 실패 전 쓰기 금지와 부분 artifact 보존은 좋은 계약이나 shell 조각 자체에 checked exit 흐름은 없다. Zeus PG 후보 ID/원문과 Git 승인 정의를 분리하고 999 라벨만으로 비실행을 강제하지 말아야 한다. Bash/mkdir/touch/환경 변수의 Windows 동등성은 미실행이다.

<a id="file-10"></a>
## 10 kha-capture-note

Read/Write/Glob/Grep만으로 note.md에 위임하며 append/list/promote를 inline 수행한다. Bash/Task/질문을 사용하지 않는 좁은 의도가 보존 후보다. 이전 workflow003 note 검토는 global fallback, 번호 목록의 불안정성, todo 목적지 명칭과 YAML quoting, promote 두 쓰기의 부분 실패를 기록했다. wrapper는 부분 실패 때 원본/목적 경로를 보존한다. Zeus에서는 대화 원문을 PG 후보로 저장하고 승격은 안정적 note ID와 source digest에 묶어야 한다. 실제 global 위치·동시 append·한국어 경로·쓰기 권한은 확인하지 않았다.

<a id="file-11"></a>
## 11 kha-capture-seed

새 전문 1–48행. Read/Write/Edit/Bash/질문으로 plant-seed.md에 위임해 why/trigger/scope를 가진 미래 아이디어를 만든다. 직접 workflow 전문 1–169행은 질문 전에 디렉터리를 만들며 번호를 파일 개수+1로 정한다. 삭제·병렬 호출·다른 slug의 동일 ID를 막지 못하고 breadcrumb 검색은 ts/js/md 앞 10개다. commit 실패의 seed 보존은 좋은 wrapper 계약이다. new-milestone이 자동으로 seed를 제시한다는 약속은 이전 전문의 소비 동작에 확인되지 않았고 이번 exact seed 검색도 일치 0이다. 이는 별도 scheduler를 관측했다는 뜻이 아니다. Zeus는 trigger 정의를 Git, dormant/제시/선택/재시도와 dedup을 PG에 두어야 한다.

<a id="file-12"></a>
## 12 kha-capture-todo

Read/Write/Bash/질문으로 add-todo.md를 실행한다. 대화의 문제/해법/파일/분야를 저장하고 키워드 중복에 선택을 받는다. 이전 workflow001 f03/s07의 발견 수는 읽을 수 있었던 pending 파일만 포함한다. 날짜/slug와 사전 중복 확인은 원자적 ID가 아니며 commit helper는 disabled/empty/error로 false를 반환할 수 있다. 부분 생성된 todo를 유지하는 방어를 보존한다. Zeus PG에서 후보·진행·해결을 나누고 추정 해법이 사용자 요구 정의로 승격되지 않도록 해야 한다. 실제 중복 경합·commit receipt는 미실행이다.

<a id="file-13"></a>
## 13 kha-clarify-phase

Read/Write/Bash/Glob/Grep/질문/Task/Context7로 discuss 설정에 따라 context와 locked 결정을 만든다. --auto는 모델 권고를 선택하고 --chain은 후속 plan/execute를 연결한다. 이전 workflow001 f16/f17와 workflow002 f01은 기존 context 덮어쓰기, --power의 기존 gate 앞 분기, 자동 선택을 confirmed/locked로 바꾸는 문제를 분석했다. locked 텍스트는 사람 선택의 증거가 아니다. 질문과 영향·미해결을 남기는 장점은 보존하되 Zeus는 자동 제안/사람 결정/보류 provenance와 8단계 진입 조건을 PG로 구분해야 한다. 실제 질문 API·모델 자격·파일 UI 안전성은 미검증이다.

<a id="file-14"></a>
## 14 kha-complete-milestone

Read/Write/Bash로 archive, PROJECT/ROADMAP/REQUIREMENTS 갱신과 Git tag를 요청한다. 질문·snapshot·lock의 선언만으로 프로세스 승인 강제는 확인되지 않는다. 이전 workflow001 f13은 알려진 gap을 둔 shipped/complete, roadmap 보존 약속과 삭제의 충돌, 최종 commit 전에 다른 branch에서 tag하는 순서, 삭제 파일 commit 범위 누락을 확인했다. 모든 archived 요구를 complete로 만드는 규칙은 실제 인수와 다르다. Zeus에서는 accepted/waived/shipped/archived를 분리하고 Git tag 대상 및 archive bytes와 PG 전이 receipt를 결속해야 한다. 원격 게시·merge·rollback은 실행하지 않았다.

<a id="file-15"></a>
## 15 kha-context-thread

새 전문 1–147행. Read/Write/Bash로 list/create/resume를 나누고 재개하면 OPEN을 IN PROGRESS로 바꾼다. 목록 ls의 stderr를 버려 접근 오류와 빈 목록을 구분하지 못할 수 있다. template에 Last Updated 값은 명시 생성되지 않고 resume 질문 도구도 허용 목록에 없다. 기존 이름 조회와 slug 생성은 다른 분기이며 비ASCII 제거/60자 절단으로 다른 설명이 같은 파일에 쓰일 수 있다. heredoc과 사용자 문자열의 안전 처리·경로 containment·원자성이 보이지 않는다. 부분 생성 보존 및 status 쓰기 성공 요구는 유지 후보다. Zeus는 immutable context handle와 PG session revision을 사용하고 narrative status를 작업 완료로 해석하지 않아야 한다. thread를 phase/backlog로 승격하는 전체 연결은 미완료다.

<a id="file-16"></a>
## 16 kha-debug

새 전문 1–291행. Read/Bash/Task/질문으로 기본 diagnose, 명시 hypothesis ID fix, 한 번에 한 가설의 interactive를 분리한다. agent 이름과 model resolver는 정해졌지만 fresh 200k 주장과 실제 위임 자격은 검증되지 않았다. HYPOTHESIS 외 상태 변경 금지, dirty tree 거부, 실제 사용자 workflow에서 확인 후 resolved라는 agent 지원 1065–1128행의 원칙은 보존 후보다.

직접 debugger 913–941/1022–1063은 flat .planning/debug/{slug}.md와 ROOT CAUSE FOUND를 쓰지만 skill은 session/HYPOTHESIS.md 및 ROOT CAUSE CANDIDATES를 소비한다. agent 1364–1380에는 새 계약도 공존한다. 실패 후 investigation_loop로 돌아가는 1087행과 같은 가설 checkpoint로 멈추라는 1375행도 일관되지 않다. 이는 실제 우회 재현이 아니라 상충하는 지시 흐름이다. Zeus는 read-only 진단 권한을 실행층에서 강제하고 PG hypothesis/attempt/증거/선택자와 Git diff를 결속해야 한다. 실제 테스트·원자 commit·중단 후 재개·사람 인수는 미실행이다.

<a id="file-17"></a>
## 17 kha-dispatch

Read/Bash/질문으로 do.md에 위임하는 자연어 router이며 작업 자체를 하지 않겠다고 선언한다. 도구 목록에 Skill/SlashCommand가 없고 workflow의 최종 /gsd-* 명칭과 표의 kha 명칭도 다르다. 이전 workflow002 f02는 first-match 우선순위, 확인과 표시의 차이, state load 오류 억제를 확인했다. 원문 보존·모호성 질문을 보존하되 Zeus는 typed target/인수/권한 제안과 실제 dispatch receipt를 구분해야 한다. 라우팅 성공이 구현·SDD 완료는 아니며 실제 명령 등록은 미확인이다.

<a id="file-18"></a>
## 18 kha-execute-phase

Read/Write/Edit/Glob/Grep/Bash/Task/TodoWrite/질문으로 phase plan wave 실행·수집을 지시한다. 이전 workflow002 f04 및 지원 helper는 SUMMARY 존재를 완료로 세고 human UAT를 비차단 경고로 남긴 채 phase complete를 쓸 수 있다. worker run 소유권 없이 다른 worktree를 열거·정리하는 흐름과 자동 human-verify approved 문자열은 실제 사람 인수와 양립하지 않는다. 충돌 파일 선언·sequential fallback·partial wave 표시는 유지 후보다. Zeus는 PG worker lease/expected base/종료·결과 receipt와 8단계 의무를 유지하고 summary·commit 추정으로 미수집 worker 결과를 대체하지 않아야 한다. 실행·hook·merge·OS 검증 0이다.

<a id="file-19"></a>
## 19 kha-explore-idea

Read/Write/Bash/Grep/Glob/Task/질문으로 explore.md의 소크라테스 대화와 선택적 연구 후 artifact 목적지를 선택한다. 이전 workflow002 f06은 요구사항 경로와 todo frontmatter 소비 계약 불일치, slug 충돌·ID 할당의 비원자성·미확인 commit flag를 남겼다. 질문 뒤 사용자가 저장 목적지를 선택하는 경계를 보존한다. Zeus에서는 후보 연구·근거·미확실성을 PG로 저장하고 Git 요구 승인은 별도다. 짧은 연구 시간 목표·생성된 인용·저장 선택을 근거 검증이나 구현 승인으로 승격하지 않는다.

<a id="file-20"></a>
## 20 kha-forensics

Read/Write/Bash/Grep/Glob을 허용하면서 mutates:no이며 report 저장과 선택적 issue 생성을 명시한다. 이전 workflow002 f08은 read-only 조사 뒤 state record-session 호출, 제한된 commit/파일/mtime heuristic과 절대 경로 일부 redaction의 한계를 기록했다. 과거 테스트 단어는 실행 receipt가 아니며 extra worktree는 사망 worker의 증거가 아니다. Zeus는 PG 사건·시도 receipt와 Git immutable history로 가설을 재구성하고 public issue 게시를 별도 권한 행위로 취급해야 한다. 현재 live state나 credentials는 읽지 않았다.

<a id="file-21"></a>
## 21 kha-generate-tests

Read/Write/Edit/Bash/Glob/Grep/Task/질문으로 완료 phase의 SUMMARY/CONTEXT/VERIFICATION을 기반으로 add-tests.md에 위임한다. 단위/E2E/Skip 분류와 사전 계획 승인은 유지 후보다. 이전 workflow001 f02는 config/route/migration/CRUD를 넓게 skip할 수 있고 즉시 PASS도 허용하며 fully tested 표현이 선택 분모를 초과함을 확인했다. state-snapshot은 상태를 출력할 뿐 test generation event를 저장하지 않는다. Zeus는 검사 대상·제외·미발견과 실패를 탐지하는 오라클, 실제 argv/env/exit 및 사람 시나리오를 기록해야 한다. 생성된 테스트 존재는 실행 또는 무mock 인수가 아니다.

<a id="file-22"></a>
## 22 kha-help

Read만 허용하고 help.md reference만 출력하는 진입점이다. 프로젝트 상태·부가 행동을 섞지 않고 unreadable 시 대체 내용을 지어내지 않는 계약은 보존 후보다. 이전 workflow003 help 전문은 안내의 사용법과 실제 각 helper의 가용성을 별개로 남겼다. Zeus에서도 도움말은 Git 정의에서 파생하되 등록된 명령/정책 revision과 비교해야 한다. 화면 출력·등록 전체·외부 링크 진실은 미검증이며 도움말이 존재한다는 사실은 제품 기능 구현 증명이 아니다.

<a id="file-23"></a>
## 23 kha-import-plan

Read/Write/Edit/Bash/Glob/Grep/질문/Task로 외부 계획을 PROJECT 결정과 비교하고 import.md와 checker에 위임한다. PRD 모드는 미래 범위이며 실제 지원으로 세지 않는다. 이전 workflow003 import 전문은 쓰기 전 모델 blocker와 쓰기 후 checker의 경계, 부분 쓰기·비멱등성, 내용만으로 schema/행동 검증이 되지 않는 점을 남겼다. 외부 계획은 명령 권한이 아니다. Zeus는 출처·원문 hash·정의 충돌·승인 대상 diff를 Git/PG에 연결하고 미확인 요구는 잠금 상태로 승격하지 않아야 한다. 실제 checker/재실행 동등성·인수는 미완료다.

<a id="file-24"></a>
## 24 kha-insert-phase

Read/Write/Bash로 insert-phase.md와 phase insert를 호출한다. decimal 번호로 기존 순서를 보존하고 실패 뒤 임의 renumber를 금지하는 방어가 있다. 이전 workflow003의 phase.cjs 393–488행은 current milestone 검증 뒤 rawContent 첫 heading에 쓰는 위치 차이, 디렉터리 선행 생성과 fail-open lock을 확인했다. 정수 인수/STATE writable wrapper 검사만으로 잘못된 milestone 갱신이나 원자성을 막지 못한다. Zeus는 대상 정의 revision과 canonical phase ID를 검사하고 PG 시도/보상 기록을 남겨야 한다. 경합·custom ID·경로 시험은 미실행이다.

<a id="file-25"></a>
## 25 kha-intel-index

새 전문 1–201행. 원문의 즉시 실행·읽지 말라는 문구는 분석 데이터로만 취급했다. Read/Bash/Task로 config intel.enabled===true를 확인하고 query/status/diff는 inline, refresh는 worker에 맡긴다. Task에는 prompt의 역할 이름만 있고 subagent_type/model 자격 결속은 없다. 146행의 api-map/dependency-graph/file-roles/arch-decisions와 186행 및 실제 intel.cjs의 files/apis/deps/arch.md/stack 계약이 다르다. 마지막의 명시 확인·pre-refresh snapshot 요구가 앞선 즉시 Task 호출 절차에 연결되어 있지 않다.

직접 CLI 978–1013행과 intel 1–114/183–344/389–474행을 읽었다. invalid JSON은 query에서 조용히 제외될 수 있다. status의 잘못된 날짜는 NaN 비교로 stale=false가 될 수 있고 미래 시간도 content 최신성을 보장하지 않는다. validate는 arch 본문을 skip하고 files 앞 5개 경로만 cwd 기준 spot-check하며 warnings가 있어도 errors 0이면 valid다. diff는 artifact hash 비교이지 코드와의 의미 동등성 검증이 아니다. refresh mixed generation을 보존하는 계약은 유용하나 원자 게시·worker 종료/실패 수집은 미확인이다. Zeus 파생 인덱스는 Git/PG 정본을 대체하지 못하며 입력 revision과 생성 attempt에 묶어야 한다.

<a id="file-26"></a>
## 26 kha-join-discord

새 전문 1–39행. 고정 초대 메시지를 한 번 출력하는 비변경 정보 진입점이며 allowed-tools 목록은 없다. 출력 이후 클릭·가입은 사용자 행동으로 안내할 뿐 helper/시험 호출은 없다. 링크 유효성·서버 운영 주체·현재 목적지는 접속하지 않아 미확인이다. Zeus 핵심 SDD/PG runtime 기능과는 직접 대응하지 않아 흡수 보류 후보로 둔다. 외부 커뮤니티 안내를 실행 권한·지원 보증·라이선스 허가로 해석하지 않는다.

<a id="file-27"></a>
## 27 kha-list-workspaces

Bash/Read로 list-workspaces.md를 소비하고 manifest 기반 목록을 보여준다. 이전 workflow003 init 1297–1387행은 immediate directory와 WORKSPACE.md 존재, ASCII 표 행으로 repo 개수를 추정하며 읽기 오류를 빈 inventory로 바꾸는 경계를 확인했다. helper 시작 시 공통 core 효과도 있어 mutates:no만으로 운영상 읽기 전용을 증명하지 않는다. init 실패 abort를 보존하되 Zeus는 PG 소유 workspace registry와 Git worktree 참조를 대조하고 미발견/오류를 빈 목록과 구분해야 한다. 실제 디스크·한국어 이름·Windows/WSL 경로는 읽지 않았다.

<a id="file-28"></a>
## 28 kha-map-codebase

Read/Bash/Glob/Grep/Write/Task로 mapper가 직접 7개 문서를 생성하는데 mutates:no다. 이전 workflow003 map 전문은 TaskOutput/질문 도구 계약 차이와 worker 부분 결과를 허용하면서 wrapper는 agent 오류 없음으로 성공을 좁히는 충돌을 기록했다. 파일 존재와 20행 같은 검사는 전체 소스 의미 독해의 증거가 아니다. Zeus에서는 파생 map에 실제 읽은 경로·범위·blob과 누락을 붙이고 PG worker 시도/결과를 독립 수집해야 한다. 문서 개수로 전체 분석·모델 자격·실행 인수를 승인할 수 없다.

<a id="file-29"></a>
## 29 kha-milestone-manager

Read/Write/Bash/Glob/Grep/질문/Skill/Task로 manager.md dashboard와 background 실행을 운영한다. long-running:no와 지속 loop 의도가 상충하며 직접 파일 없음도 downstream mutation이 없다는 뜻은 아니다. 이전 workflow003 init-manager는 숫자 phase·SUMMARY 수·checkbox·최근 5분 mtime를 상태로 추정하고 파일 겹침/worker lease 없이 추천한다. dashboard를 snapshot/dry-run이라 부르는 것은 immutable 증거와 다르다. Zeus는 PG 예약·lease·자격·종료 receipt와 Git dependency graph를 사용해야 한다. 실제 background 결과 수집과 취소·중복 실행은 미검증이다.

<a id="file-30"></a>
## 30 kha-milestone-summary

Read/Write/Bash/Grep/Glob으로 milestone-summary.md 보고서를 저장하면서 mutates:no다. 과거 문서를 onboarding 설명으로 재구성하는 목적은 유용하나 shipped/verified 문서의 상태를 실제 결과로 재검증하지 않는다. 이전 workflow003 전문은 report 이후 commit/state 변경과 파일 단위 idempotent 약속의 한계를 남겼다. Zeus는 생성 요약을 파생 view로 표시하고 각 주장에 Git 정의와 PG 실제 receipt를 연결해야 한다. 반복 호출의 side effect·stale artifact·사람 검토는 미완료다.

<a id="file-31"></a>
## 31 kha-new-milestone

Read/Write/Bash/Task/질문으로 new-milestone.md의 연구→요구→roadmap을 시작한다. wrapper의 archive 없이는 clear 금지와 실제 workflow Step6 clear/Step7.5 archive gate 순서는 충돌한다. 이전 workflow003 milestone.cjs 249–282행은 --confirm으로 999 prefix 제외 모든 phase directory를 recursive force 삭제하며 archive·작업 소유권·인수를 검사하지 않음을 확인했다. capture-seed가 약속한 seed 소비도 이번 literal 검색과 기존 전문에서 확인되지 않았다. Zeus는 Git 다음 정의 제안과 PG 완료/미완료 runtime를 유지하고 archive digest가 닫히기 전 제거를 허용하지 않아야 한다. 실제 삭제/복구는 실행하지 않았다.

<a id="file-32"></a>
## 32 kha-new-project

Read/Bash/Write/Task/질문으로 프로젝트 context·설정·연구·요구·roadmap을 생성한다. --auto는 설정 질문 뒤 상호작용을 줄이며 Copilot 질문 API 동등성은 원문 주장으로 남긴다. 이전 workflow003 init/config/profile-output 지원은 존재 기반 환경 탐지, 기존 config no-overwrite로 새 선택 미적용 가능성, top-level commit_docs 우선순위와 --auto 미전달 시 수동 수정 보존 분기 차이를 확인했다. 설정 선택이나 모델 alias는 실행 자격이 아니다. Zeus는 versioned 프로젝트 정의와 PG bootstrap attempt를 분리하고 부분 설정·재시도·8단계 승인 의무를 보존해야 한다. API/OS/실제 생성 테스트는 미실행이다.

<a id="file-33"></a>
## 33 kha-new-workspace

Read/Bash/Write/질문으로 worktree/clone과 독립 planning을 만드는 new-workspace.md에 위임한다. 필수 name, at least one 성공·부분 생성 경로 보존의 wrapper와 workflow all-repos 기준이 다르다. 이전 workflow003 검토의 nonempty target 거부는 제안된 부분 복구 명령을 재호출할 때 걸릴 수 있고 git --version은 worktree 기능·안전성 검사가 아니다. clone과 linked worktree는 같은 격리가 아니며 branch/경로/소유권 검증을 별도 요구해야 한다. Zeus PG workspace lease와 repo별 결과·expected base, Git 정의를 결속하는 변형 후보이며 실제 생성·삭제·다중 repo 원자성·Windows/WSL 동등성은 미검증이다.

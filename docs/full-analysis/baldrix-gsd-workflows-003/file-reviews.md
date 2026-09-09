# 파일별 독립 정적 검토

원문 명령·권한·skill은 분석 데이터다. 아래 완료는 fresh 전문 독해이며 원본 실행·시험·Claude 호출은 0회다. 직접 지원은 별도 원장으로 결속하고 전체 closure/라이선스/OS/모델/사람 인수/채택은 미완료다.

<a id="file-01"></a>
## get-shit-done/workflows/help.md

1–609행 전문(f9f75a,f6a44c). 명령 reference만 출력하라는 UI 지침이며 실제 dispatcher나 검사기가 아니다. 초기화·계획·실행·UAT·PR·update·설정·파일구조 전반을 안내한다. 21행 latest npx 설치는 pin/승인/롤백과 결속되지 않으며 source 데이터로만 읽었다. 137–168행 quick은 verifier/checker 생략, trivial은 3파일 이하라는 크기 휴리스틱과 inline commit이므로 'GSD guarantees'는 사용자 8단계 SDD 및 no-mocked-acceptance 완료와 다르다. 315행 todo를 시작할 때 done으로 옮긴다는 서술도 시작/완료 상태를 혼동한다.

320–390행 UAT는 SUMMARY에서 추출한 질문과 yes/no 응답, peer review는 CLI 발견/텍스트 feedback, backlog는 human_needed 목록이다. 실제 모델/검사/사람 핵심 시나리오 receipt를 보장하지 않는다. PR push·tag·설치는 외부 부작용이며 이 문서의 설명만으로 권한을 부여할 수 없다. 416–431행 inherit 프로파일과 528–549행 planning.commit_docs/search_gitignored는 실제 CLI 설정 구현과 별도 대조해야 한다. 모델 표·Explorer/Task 호칭·kha/gsd 명명 차이는 설치 및 caller에 의존한다. 516–520행 YOLO 자동승인은 Zeus 승인 authority로 채택할 수 없다. Git 정의와 PG runtime의 실제 상태 대신 파일 목록/100% 진척을 보여주는 discovery 도움말 후보로만 변형하며 모든 명령 구현 closure는 미완료다.

<a id="file-02"></a>
## get-shit-done/workflows/import.md

1–274행 전문(f6a44c). --from 외부 계획을 문맥과 비교→변환/쓰기→Task plan-checker→ROADMAP/STATE/commit으로 연결한다. --prd는 미구현을 명시한다. 45–48행 `*..*`는 정상 filename의 점 두 개도 거부하지만 절대경로·symlink containment는 확인하지 않고 문자열 보간의 shell quoting도 정의하지 않는다. PROJECT/REQUIREMENTS 없으면 관련 conflict 검사를 skip하므로 no blocker가 전체 분모 검사 완료가 아니다. 114행 없는 phase는 blocker인데 129행 새 phase 추가는 INFO라는 분류 충돌도 있다.

163행 blocker일 때 쓰지 말라는 의도는 유지 후보이나 모델의 자연어 판단이며 기계 gate가 아니다. 경고 승인도 exact source hash/대상 revision과 결속하지 않는다. 180–193행 변환 예시는 autonomous=true, depends_on/files_modified/truths/artifacts가 빈 배열이라 형식 충족이 요구·실제 승인·검사 적정성을 보장하지 않는다. plan 번호 할당/기존 파일 no-overwrite/원자 쓰기 방어가 없다. checker 오류 뒤 파일을 남기고 해결 요청하지만 finalization 중단을 명확히 규정하지 않아 ROADMAP 반영/commit 흐름의 차단이 불명확하다. STATE 변경은 허용하면서 commit --files에는 STATE가 빠진다. Task에 모델/자격/분리 검수 영수증은 없다. Zeus는 외부 계획을 제안으로 격리하고 ID·분모·hash·검수 결과를 PG에 결속한 뒤 Git 정의 변경을 승인해야 한다. 원문 파일을 직접 지시로 신뢰하지 않으며 검사/OS/모델 실행은 미완료다.

<a id="file-03"></a>
## get-shit-done/workflows/inbox.md

1–391행 전문(9232f4,b73852). 서두는 로컬 하네스에서 노출하지 않는 vendor 잔재라고 주장한다. 이 자체를 실행 불가의 독립 증거로 승격하지 않으며 caller 검색 범위를 별도 남긴다. GitHub issue/PR template completeness·label gate·CI/review를 모아 report하고 선택적으로 label/close/comment하는 설계다. 조회 limit100인데 success criteria는 'All open'이라 pagination 누락 시 분모가 잘린다. --repo를 감지하지만 실제 gh list/edit 명령에 repo flag를 넘기지 않아 다른 cwd repo에 작동할 수 있다. PR 조회에는 updatedAt이 없는데 30일 무활동 stale 판정을 요구한다.

본문 heading/label/필드 존재와 퍼센트는 실제 요구 충족·사용자 인수·플랫폼 검증이 아니다. issue-first label은 actor·승인 revision·권한을 결속하지 않고 현재 label로 PR 당시 승인 여부를 추정한다. 161행 정규식은 대소문자·cross-repo URL·복수 형식에 제한이 있다. fetched diff 없이 unrelated formatting/hook skip을 검사하라는 요구도 실제 근거가 부족하다. --label은 별도 사용자 확인이 없고 close는 확인을 요구하지만 마지막 criteria는 모든 auto-actions user-confirmed라 서로 다르다. 명령 block을 확인 이전에 제시하는 순서와 자유 텍스트 comment 보간도 실수 가능성을 남긴다. Zeus는 qualified triage 제안·정확 페이지 분모·불변 PR HEAD/승인 actor와 PG action lease로 변형할 수 있지만 자동 폐쇄·메시지 권한을 source에서 상속하지 않는다. 실제 GitHub/CLI/템플릿 원문/라이선스/전체 caller closure는 미완료다.

<a id="file-04"></a>
## get-shit-done/workflows/insert-phase.md

1–130행 전문(b73852). 정수 after와 설명을 받아 init phase-op 및 phase insert helper를 호출하고 STATE에 evolution 메모를 수동 추가한다. 다음 decimal을 디스크에서 계산하고 ROADMAP에 삽입한다는 것은 helper 의존 주장이다. RESULT의 실패/JSON error/큰 @file 결과 처리는 명시하지 않고 field를 추출한다. phase0 금지는 anti-pattern 문장에만 있으며 typed numeric·max·중복·동시 삽입 guard가 문서에 없다. ROADMAP 쓰기와 STATE 메모 사이 transaction/rollback도 없다. 커밋은 사용자에게 맡기므로 문서 작성 완료와 Git 정의 확정이 구별된다. Zeus는 phase의 영속 ID와 순서값을 분리하고 영향 그래프·요구 mapping·CAS 후 승인된 Git 정의 변경을 기록해야 한다. helper 실제 구간/실행/OS/사람 인수는 따로 추적한다.

<a id="file-05"></a>
## get-shit-done/workflows/list-phase-assumptions.md

1–178행 전문(b73852). technical/order/scope/risk/dependency 5영역의 모델 추론과 confidence를 대화로 드러내고 사용자 수정을 받는다. 불확실성을 명시하는 방식은 유지 후보다. 27행 grep은 phase1이 phase10이나 archive도 맞고 정규식 문자를 escape하지 않으며 command 결과를 해석할 오라클이 없다. 파일을 만들지 않아 다음 /clear 이후 수정·승인·원문 revision을 재구성할 영속 근거가 없는데 'assumptions validated'로 표현한다. 이는 사용자와의 이해 정렬이지 코드 검증/핵심 시나리오 인수가 아니다. Zeus에서는 SDD 요구 clarification의 가설/수정 이력을 Git 정의 참조와 PG 대화 결정으로 결속하되 모델 자격·실제 검증을 따로 요구한다. 운영 쓰기·모델 실행 0, downstream 계획 반영 closure는 미완료다.

<a id="file-06"></a>
## get-shit-done/workflows/list-workspaces.md

1–56행 전문(b73852). init list-workspaces JSON을 받아 count0 안내 또는 name/repos/strategy/PROJECT 존재 표만 출력한다. @file 읽기를 처리하지만 JSON parse 실패·오류와 0개를 구분하는 명시 gate는 없다. PROJECT 존재는 GSD Project 신호이며 health/정본 revision/worker 활성·실제 repo 유효성은 아니다. 표시 경로는 workspace_base 값을 받으면서도 ~/gsd-workspaces로 고정한다. Bash HOME/.claude/Node/cat에 의존하고 OS path·runtime 구성 차이는 native 검증 전까지 미확인이다. Zeus에서는 PG workspace/task lease와 Git repo identity를 결합한 조회 adapter 후보이며 목록 출력을 실제 인수로 보지 않는다. helper 및 caller 지정범위 외 전체 closure는 미완료다.
<a id="file-07"></a>
## get-shit-done/workflows/manager.md

1–363행 전문(73e88d,c6e077). init manager의 디스크 상태/추천을 대시보드로 바꾸고 Continue 한 번으로 모든 plan/execute background Task와 inline discuss를 시작한다. disk_status complete는 D/P/E 모두 체크로 표시하고 UAT는 all_complete 이후 선택지이므로 milestone complete가 사람 인수 완료와 다르다. success criteria는 D/P/E/V라지만 실제 표는 V가 없다. free-text 임의 phase/action dispatch의 의존성 재검사와 이미 실행 중인 task dedup/lease는 문서에 없다.

Task에는 model/subagent_type/격리 scope가 없고 full Skill pipeline이라는 프롬프트 선언에 맡긴다. 60초 무입력 refresh는 timer/실제 도구 지원이 명시되지 않은 지침이다. background 완료 통지는 먼저 체크 기호로 표시한 뒤 error를 분류한다. worker에게 권한 오류 우회 금지를 지시하면서 manager는 settings.local.json 권한 추가와 inline 재시도를 제안한다. 이 문서는 차단 우회 권한이 아니며 검토에서는 실행하지 않았다. 다른 오류 재시도에도 generation/부분 쓰기 rollback/정본 재검증이 없다. 종료 후 worker가 계속 완주하고 다음 실행에서 결과가 보인다는 주장은 durable collector/취소/결과 handle 결속이 없으면 보장되지 않는다. Zeus는 PG task lease와 재발 dedup·실패 receipt·사용자 명시 변경권한을 갖춘 관리 UI로 변형하고 모델 위임 자격과 실제 인수는 별도로 요구해야 한다.

<a id="file-08"></a>
## get-shit-done/workflows/map-codebase.md

1–379행 전문(c6e077,19412c). 네 mapper를 분리해 7개 문서를 직접 쓰게 하고 parent는 path/줄 수만 받는다. Task 미지원 시 같은 4영역을 순차로 수행하며 Explore/browser 대체를 금지해 help의 Explore 설명과 다르다. refresh는 기존 디렉터리 삭제, update는 일부 문서만 갱신하므로 기존 문서의 source revision을 새 결과와 섞을 수 있다. task_id/TaskOutput timeout은 있으나 timeout이 worker 종료를 뜻하지 않고 실패 agent를 기록한 뒤 성공 문서만으로 계속한다. 활성 쓰기와 다음 commit의 경합을 막을 lease/fencing은 없다.

오라클은 7개 파일 존재와 각 >20줄이다. 실제 원문 전수 독해/경로 hash/semantic 정확성은 증명하지 못한다. 누락/empty를 기록해도 scan/commit과 complete 배너로 넘어간다. 비밀 패턴 grep은 오류도 SECRETS_FOUND=false로 처리하고 실제 일치 원문을 화면에 노출하도록 요구한다. 패턴 미일치가 비밀 없음의 증거는 아니며 사람이 safe to proceed라고 답해도 revision/hash 결속은 없다. 모델 결과·줄 수는 사용자 SDD의 원문 분석, 실제 테스트, 사람 인수와 별개다. Zeus에는 map을 파생 index로만 두고 path별 pinned 독해 원장과 실패 분모·비동기 종료/회수·민감 출력 비공개를 결속해야 한다. 지원 agent/config/test 외 전체 closure와 실제 OS/model 실행은 미완료다.

<a id="file-09"></a>
## get-shit-done/workflows/milestone-summary.md

1–223행 전문(19412c). version을 STATE→archive→current로 추정하고 존재하는 문서만 읽어 onboarding summary를 생성한다. 없는 자료는 허용하므로 'entire project/full context'는 원문 전수나 실제 구현 인수가 아니다. archive 여부는 ROADMAP 한 파일로 정하고 phase 탐색은 init progress의 현 상태를 이용하므로 requested version과 실제 phase scope 연결이 약하다. `{padded}-SUMMARY.md` 단일 이름 가정은 plan별 XX-YY-SUMMARY 누락 가능성을 남긴다. version 입력 경로/중복 v 접두사·tag 옵션 처리가 없다.

tag 방식은 tag까지 전체 git log를 milestone commit수로 세고 첫 역사 commit부터 diff해서 이전 milestone을 포함하고 첫 커밋 내용은 diff에서 제외한다. date fallback은 upper bound/ancestor 결속이 없고 현재 STATE를 archived milestone에 쓰면 시간 범위가 틀릴 수 있다. stdout 줄 수는 Git 명령 실패와0을 구분하지 않는다. Step5에 Write를 명시한 뒤 Step6에 overwrite guard가 있어 순서가 모호하며 no-overwrite는 원자적이지 않다. 최종 session state 기록은 summary commit 이후 별도 mutation이다. Zeus는 출처/누락/기간·정본을 표시한 파생 보고서로 변형하고 실제 요구 completion·모델 검수·사람 인수·PG runtime authority를 파일 서술에서 추정하지 않는다.

<a id="file-10"></a>
## get-shit-done/workflows/new-milestone.md

1–492행 전문(004ced,d07a55). 목표·version·요구 목록·roadmap 사용자 확인, 기존 REQ 번호 유지, category별 scope와 observable success criteria는 유지 후보이다. 그러나 Step6에서 context 삭제와 phases clear --confirm을 **먼저** 수행하고 Step7 init 뒤 reset archive safety를 확인한다. 후반 archive 경고가 앞선 삭제를 막는다고 볼 수 없다. clear 실제 helper를 직접 추적해야 하며 active/미검수 phase가 이전 milestone이라는 가정을 승인하지 않는다. context 삭제는 commit --files에서 빠지고 PROJECT/STATE를 이미 변경한 후 향후 오류가 생겨도 전체 rollback은 없다.

4개 researcher→synthesizer는 source 파일을 쓰고 commit하도록 지시하지만 timeout/부분 실패/모델 자격·각 결과 hash 결속이 없다. 기존 PROJECT의 validated capability와 codebase map을 이미 검증된 문맥으로 삼고 재조사를 금지한다. 연구 skip 시 기존 FEATURES/SUMMARY 존재만으로 예전 연구를 소비할 수 있어 generation 구분이 필요하다. 일회 연구 선택을 persistent config에 쓰지 않는 방어는 좋다. 요구 1개당 phase1개 mapping 및100%는 작성자가 검증하는 선언이며 빈 요구 분모/중복 ID/교차 phase 시나리오 검증을 구현하지 않는다. roadmapper는 승인 전 파일을 즉시 쓰고 parent는 문자열 ROADMAP CREATED를 처리한다. Zeus에서는 Git 정의 proposal과 PG 승인 상태를 분리하고 prior artifact의 실제 검증 여부, source revision, 활성 worker lease, archive no-overwrite를 확보해야 한다. 원본 실행/연구/인수/채택은 미완료다.

<a id="file-11"></a>
## get-shit-done/workflows/new-project.md

1–1273행 전문(d07a55,ee586c,8c6ac1,07c0ba,beca9f). 질문→설정→4영역 연구→요구→roadmap→프로젝트 지시 파일 생성의 선언이다. auto는 brownfield를 greenfield로 가정하고 원문 아이디어로 요구·roadmap을 자동 승인한다. Step2의 Step4 jump와 Step2a config 선행 요구가 충돌한다. interactive checklist의 deep questioning/user scope는 auto에서 skip하므로 공통 success 분모가 실행 경로와 다르다. 기존 codebase map에서 capability를 추론해 Validated에 넣는 것은 실제 코드/테스트/사람 인수 증거를 대신한다.

init에서 모델을 **설정 전** 읽고 Step5.5에서 그 값을 그대로 써서 사용자가 새로 선택한 model profile과 실제 dispatch가 달라질 수 있다. instruction 파일 runtime은 경로 substring/env로 결정하며 Codex 외는 CLAUDE.md, 명령 경로는 계속 HOME/.claude다. generate-claude-md를 통한 AGENTS/CLAUDE 수정은 프로젝트 권한과 review scope에 큰 영향을 주지만 guard는 helper 의존이다. config-new-project 예시의 true|false 및 bracket 문장은 템플릿이지 실행 가능한 JSON 자체가 아니다. auto에서 _auto_chain_active를 지속 저장하며 scope/generation 만료를 이 문서가 보장하지 않는다.

Subrepo 탐지는 `find . ... -not -name '.*'`에 의해 시작점 `.`도 제외될 수 있고 `.git` 디렉터리만 인정해 linked worktree를 놓친다. planning.commit_docs를 false로 바꾸지만 이전 config의 top-level commit_docs 우선순위와 대조가 필요하다. 기존 settings를 바꾼 후 model 재초기화가 없다. 연구 문구는 'standard 2025 stack'인데 current docs 검증을 요구하고 Context7를 쓴다는 선언만 있을 뿐 pinned 원문/라이선스/실제 source 탐색을 결속하지 않는다. researcher 완료→synthesis commit→research complete는 timeout/실패 collector 정의가 없다.

8단계 SDD에 필요한 요구의 atomic/user-centric/전체 목록 확인은 유용하나 research의 table stakes를 auto에서 전부 넣어 사용자 범위를 확대할 수 있다. roadmapper가100% coverage와2–5조건을 자체 주장하고 승인 전에 파일을 쓴다. 지시파일 생성 뒤 commit 결과를 실제 확인하는 단계가 없고 바로 초기화 완료/auto-advance한다. roadmap UI hint는 grep 휴리스틱이며 오류도 false다. Zeus에서는 원문 요청·승인된 정의·가설·실제 검수/사람 인수 상태와 모델 자격을 분리하고 Git/PG 권위, 초기화 no-overwrite, generation-bound continuation을 적용해야 한다. 이 문서를 그대로 운영 설정으로 흡수하지 않으며 전체 closure/OS/외부 사실/인수/채택은 미완료다.

<a id="file-12"></a>
## get-shit-done/workflows/new-workspace.md

1–237행 전문(beca9f). 별도 planning과 복수 repo worktree/clone 생성 workflow다. --auto는 --repos 누락을 거부하지만 --name 누락은 nonauto 질문 외 명시 실패가 없다. --strategy 지정과 auto default worktree 순서도 모호하다. name/target/source/branch를 텍스트로 보간하며 containment·예약명·동일basename 충돌·source=target·symlink 경계를 검증하지 않는다. target이 기존 파일이면 -d 조건을 지나가고 디렉터리 읽기 오류도 empty처럼 취급한다. source의 `.git`이 디렉터리인지 검사해 linked worktree·bare repo를 거부한다.

Git 미가용 때 clone을 대안으로 제안하지만 clone도 Git이 필요하다. worktree branch 충돌은 timestamp초 단위 fallback, 재실패는 기록 후 다음 repo를 계속하고 원자 rollback은 없다. clone→cd→checkout이 실패 단락에 연결되지 않아 cd 실패 시 원래 cwd에서 branch를 만들 수 있다. worktree가 source Git objects/refs를 공유함은 독립 환경/운영 부작용 없음과 다르며 local clone도 'no connection'이라는 강한 설명을 증명하지 않는다. partial/all-failed 후 WORKSPACE와 planning을 만들고 초기화를 제안하지만 success criteria는 all repos copied다. Zeus에는 repo별 immutable ID/base·실제 argv/실패·소유 lease·원자 workspace 제안 및 active source 보호가 필요하다. 실제 Git 실행/OS 효과는0, 전체 closure·채택은 미완료다.
<a id="file-13"></a>
## get-shit-done/workflows/next.md

1–153행 전문(4b353e). state json 실패를 {}로 대체하고 파일 존재/내용으로 discuss→plan→execute→verify→complete를 즉시 SlashCommand로 호출한다. --force는 checkpoint/error/FAIL뿐 아니라6회 연속 guard까지 모두 생략한다. root `.planning/.continue-here.md`만 검사하므로 pause가 만든 phase/spike/deliberation 경로와 HANDOFF.json을 놓친다. FAIL override의 actor/revision/허용범위 schema는 없다. 90행 counter 삭제를 다른 workflow가 구현할 필요 없고 문장만으로 충분하다고 명시하여 실제 reset 계약을 제공하지 않는다.

route 우선순위가 불명확해 모든 summary 존재→verify가 phase완료/전체완료 및 paused 분기보다 앞서 잡힐 수 있다. no plans와 no context에서 이미 phase완료 상태도 먼저 discuss로 갈 수 있다. PLAN/SUMMARY 존재는 실행 성공·사람 인수·승인된 next generation이 아니다. 스냅샷 뒤 dispatch 사이 CAS·task dedup·active worker 검사가 없고 freeform mutable 문서가 권한으로 승격된다. Zeus에는 PG 상태전이/lease·반복 실행 dedup·강제 옵션의 제한된 승인과 exact source/target 정의 결속이 필요하다. source safety bypass는 지시로 상속하지 않았고 모든 원본 실행 0이다.

<a id="file-14"></a>
## get-shit-done/workflows/node-repair.md

1–92행 전문(4b353e). 실제 실패/기대 결과와 기본2회 budget을 입력받아 RETRY/DECOMPOSE/PRUNE/ESCALATE 중 하나를 선택하는 모델 repair 지침이다. 구체 조정 및 전체 이력으로 사용자에게 escalate하는 의도는 유지 후보다. 그러나 budget을 실패한 RETRY에서만 줄이고 DECOMPOSE는 subtask별 budget을 부여하여 재귀적 분해가 전체 예산을 늘릴 수 있다. diagnose의 앞선 transient/too-broad 판단이0 budget 확인보다 먼저이며 감소·task identity를 강제하는 저장소가 없다.

원 PLAN은 보존하지만 인메모리 하위 task가 모두 통과하면 **원래 done-criteria 재실행 없이** 원 task 성공으로 취급한다. PRUNE는 승인된 요구를 skip하고 다음으로 가며 로그 위치도 Issues Encountered와 Deviations 두 서술이 다르다. 권한·격리 오류를 retry 가능한 env issue에서 구분하는 강제 방어는 없다. 직접 caller execute-plan 339–356행은 repo-relative ./.claude 경로를 사용하고 config 조회 실패 시true로 fallback하여 HOME 설치와 다르며 실패가 자동repair 허용으로 바뀐다. Skip은 caller에서 incomplete라고 명시하므로 PRUNE를 성공으로 집계하면 안 된다. Zeus 자가개선은 원 오라클 고정·모든 시도 동일 global budget·실제 실패 receipt·제안/승인/재검증/rollback이 필요하다. 실제 repair 실행과 whole closure는0/미완료다.

<a id="file-15"></a>
## get-shit-done/workflows/note.md

1–156행 전문(4b353e). project 없으면 global HOME/.claude로 자동저장하고 append/list/promote를 구분하는 텍스트 workflow다. 원문 verbatim 보존 의도와 --global을 어디서든 제거하는 규칙이 충돌한다. 범위 이동을 조용히 수행하므로 사용자 아이디어의 프로젝트 권위/접근범위도 바뀐다. 하루+4단어 slug와 존재시 suffix는 concurrent no-overwrite·영속ID를 보장하지 않는다. local minute 시간에는 zone/순서 tie-break가 없고 번호는 재계산되어 list→promote 사이 다른 note가 추가되면 대상이 달라질 수 있다.

active만 번호 매긴다는 규칙과 promoted 예제에도 번호를 붙이는 출력이 상충하며 >20개에서 last10만 보여도 promote 전체 index를 어떻게 유지하는지 모호하다. --global list도 두 scope를 읽는다. todo 번호는 pending/completed를 검색하지만 다른 workflow는 done을 사용하여 ID 재사용 가능성이 있다. title에 verbatim text를 인용하되 quote/newline YAML escaping을 정의하지 않는다. promote는 todo 쓰기와 source promoted 변경이 비원자적이며 승인 기준을 모델이 새로 도출한다. wrapper는 부분 실패를 두 경로로 보고하라는 유용한 회복 지침을 추가하지만 durable transaction은 아니다. Zeus는 원문 note를 immutable capture로, todo 전환을 별도 proposal·stableID·PG 상태전이로 결속하고 실제 인수 조건은 사용자의 요구로 검토해야 한다. 원본 실행·live notes 접근 0이다.

<a id="file-16"></a>
## get-shit-done/workflows/pause-work.md

1–239행 전문(700253). HANDOFF.json과 사람용 continue-here를 작성·WIP commit하는 설계다. phase/spike 탐지 예시는 `$(( ls ... ) | ...)` 형태로 command substitution과 arithmetic syntax가 모호하고 실행 검증하지 않았다. PLAN.md 단일명/mtime 첫 항목에 의존해 통상 XX-YY-PLAN을 놓칠 수 있고 GNU grep -P는 OS 차이가 있다. placeholder 검사는 SUMMARY만이 아니라 모든 phase Markdown에 적용해 정상 계획의 TBD도 false completion으로 분류할 수 있다.

JSON은 phase 중심 필드여서 nonphase handoff를 충분히 표현하지 못하고 completed_tasks에 in_progress도 들어간다. 원래 실패로 발견한 제약·severity/infra/background process는 수집하지만 JSON schema에는 없어 사람 문서와 권위가 갈린다. short hash와 mutable path만 있으며 실제 Git revision/소유 task generation/lease/잔여 프로세스 handle이 없다. 두 파일의 원자 쓰기·검증·기존 handoff 병합이 없어 동시 pause가 덮어쓸 수 있다. STATE continuity 갱신은 help가 주장하지만 이 본문에 실제 state 호출이 없다. commit_docs false 또는 commit 실패를 확인하지 않고 WIP committed로 출력한다.

resume-project 62–104행은 HANDOFF를 우선하고 uncommitted_files↔git status 차이를 보는 방어가 있지만 JSON schema/hash/revision 검증은 없고 성공 resume 후 삭제한다. fallback glob은 phase만 찾아 spike/deliberation/root를 놓친다. next는 반대로 root만 검사하므로 handoff 작성/조회/guard 범위가 다르다. source의 제약 체크박스는 자체 이해 선언이지 실행 권한이나 실제 구조적 완화 증거가 아니다. Zeus에는 immutable handoff/ref·PG fenced continuation·실제 worker 상태/종료·실패 원시 영수증을 보존하고 사람 인수/검수는 따로 기록해야 한다.

<a id="file-17"></a>
## get-shit-done/workflows/plan-milestone-gaps.md

1–273행 전문(700253). 최신 mtime audit의 requirements/integration/flows를 묶어 phase를 만들고 미충족 요구를 Pending/unchecked로 되돌리는 계획 작성 workflow다. 실패 요구를 성공으로 유지하지 않는 점과 사용자 phase 제안 확인은 유지 후보다. 최신 audit는 current milestone/source revision/승인된 전체 분모와 결속하지 않아 다른 version·손상·오래된 code 결과를 쓸 수 있다. no gaps와 audit없음을 같은 오류로 처리하고 알 수 없는 priority·parser failure 처리는 없다. numbered disk 마지막 directory를 다음 번호 근거로 써서999 backlog/custom/decimal·로드맵에만 있는 phase와 충돌할 수 있다.

요구의 phase column을 새 번호로 바꾸면 원래 구현·검수 attribution을 잃기 쉽고 중복 gap/ID·이전 closure phase와 dedup이 없다. 검사는 grep -c Pending뿐이라 정확 행/분모/요구의 내용·상태전이를 검증하지 않는다. ROADMAP→REQUIREMENTS→mkdir→commit은 비원자적이며 wrapper의 'traceability 불일치면 roadmap 전 stop' 선언이 본문 순서에 구현되지 않는다. 생성 후 Gaps addressed라고 하지만 실제 fix 실행·integration/E2E·사람 인수는 아직 계획 이후이며 re-audit를 별도로 요구한다. Zeus에는 old/new requirement mapping과 exact gap evidence를 PG 이력으로 보존하고 Git 정의 제안 변경, global ID·scope·no-overwrite·실제 오라클 재검증을 적용해야 한다. 실행/전체 closure/채택 미완료다.

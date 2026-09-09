# Baldrix kha 진입점 002 — 잔여 36개 정적 검토

<a id="scope"></a>
## 범위·재사용·미실행

Zeus 시작 HEAD `7eaa42737d0cce4e675c9f309c215ce1e1d97ed4`, Baldrix 고정 revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`다. manifest/partitions/path-ledger에서 `skills/kha-*` 디렉터리 이름이 `kha-new-workspace`보다 큰 36개 SKILL.md, 117,515 bytes를 확정했다. 모두 기록 전 원장에서는 unreviewed였다. 각 단일파일 partition과 scope, 원시 Git blob·bytes·SHA, 이전 원장 행/index/행 hash는 files.json 및 checkpoint.json에 보존한다.

30개는 이번에 새로 전문을 읽었다. 여섯 파일(revert-work, review-ui, self-update, spec-ui-phase, validate-nyquist-phase, verify-uat)은 직전 baldrix-gsd-workflows-005의 supporting 전문 독해와 파일별 의미/호출/위험 기록을 재사용했다. 이들은 **prior_full_body_reused**이며 fresh로 세지 않는다. 원래 supporting 원장의 row/index/hash, full range, original receipt, review anchor와 review SHA, 원본 revision/blob/raw SHA를 다시 대조한다. 해당 여섯 workflow 본문도 같은 이전 primary 전문 증거를 supporting으로 연결한다. 부분 독해/검색/요약을 전문 재사용으로 승격하지 않았다.

source SKILL은 상류 지시 데이터다. 분석 중 이를 설치·적용하지 않았다. 원본 실행/import/collection/probe/network/install/모델/실제 Claude/운영 변경은 0이고 차단 probe 재시도·우회도 0이다. 소유 폴더의 메타데이터 기록·검사만 실행했다. 전역 coverage/tickets/stage/commit/push 및 이전 완료 보고서를 변경하지 않았다. 실제 tests PASS, 전체 전이 폐쇄, OS/모델 자격, 라이선스, 실제 사람 인수, independent Claude 및 채택은 미완료다.

<a id="i01"></a>
## 01 kha-pause-work/SKILL.md — fresh

Read/Write/Bash로 HANDOFF.json과 사람용 continue-here를 기록하고 WIP commit을 요구한다(1–63). pause-work.md 61–103의 구조는 완료/진행중 task, blockers, human_actions, uncommitted files, next action을 보존해 SDD 반복 작업의 인계 후보가 된다. 204–224는 helper commit 후 고정 WIP 완료 안내를 내므로 committed:false/skip와 실제 commit 성공을 구분해야 한다. JSON 존재는 원본 실행 증거나 PG lease가 아니며 전체 문맥·증적을 완벽히 복원한다는 설명은 검증되지 않았다.

<a id="i02"></a>
## 02 kha-phase-assumptions/SKILL.md — fresh

Read/Bash/Grep/Glob, mutates:no로 phase/roadmap을 확인하고 접근·순서·범위·위험·의존성 다섯 영역의 가정을 대화로 제시한다. user correction은 저장하지 않는다는 59–61의 경계와 list-phase-assumptions.md 129–150의 대화 acknowledgement가 연결된다. SDD 1단계 인간 핵심 시나리오와 가정 정정에 적합한 선언이나 Assumptions validated 문구는 승인된 spec revision 기록이 아니다. 후속 clarify/plan이 그 수정을 확실히 수용하는 전이와 persistent evidence는 미완료다.

<a id="i03"></a>
## 03 kha-plan-gap-phases/SKILL.md — fresh

최근 milestone audit gaps를 must/should/nice로 분류하고 사용자 확인 후 ROADMAP/REQUIREMENTS와 phase directory를 바꾸도록 한다. skill 47의 traceability 불일치 시 roadmap 쓰기 전 중단과 달리, 직접 plan-milestone-gaps.md 100–151은 roadmap 갱신 뒤 requirements를 재배정/unchecked로 돌리고 Pending 문자열 개수를 확인한다. 확인 질문은 있지만 사전 검사·다중파일 원자성·중복 phase 생성 방지는 이 구간에서 강제되지 않는다. SDD 6→1의 잔여 인수 항목 재기획 후보이며 gap 이동은 충족·승인과 다르게 기록해야 한다.

<a id="i04"></a>
## 04 kha-plan-phase/SKILL.md — fresh

Task/WebFetch/Context7 등을 허용하며 research→plan→checker, --prd/--reviews/--gaps와 skip flags를 정의한다. graph post-step은 실제 scripts/cli/phase_graph.py 1–86의 build/query로 연결되지만 모듈 실행은 scripts import path와 `--root .planning`의 cwd에 의존한다. workflow 868–934는 null/TBD requirement 분모를 skip하고 문자열 ID/CONTEXT objective 대응 뒤 gap 수용·다음 phase 이월을 허용한다. planned-phase 기록은 실제 인수 PASS가 아니다. 읽은 graph tests는 합성 ROADMAP/graph fixture의 노드·edge·query assertion 및 수동 runner 일부이며 미실행이다. 그래프는 Git 정의의 파생 투영으로 적응할 후보이지 PG 실행 권위나 모델 자격 증명은 아니다.

<a id="i05"></a>
## 05 kha-prepare-pr-branch/SKILL.md — fresh

Bash/Read/AskUserQuestion으로 planning-only commit을 제외한 PR branch를 만들며 mixed commit의 `.planning`을 제거한다. pr-branch.md 72–129는 cherry-pick --no-commit 후 `git rm -r --cached .planning/`와 원 commit 메시지 commit, diff count 표시를 한다. base가 이미 planning 파일을 추적하면 이 명령은 기존 파일 삭제까지 stage할 수 있으며 count가 0인지 차단하는 분기가 이 구간에는 없다. skill은 실패 중간 branch 보존/비완료를 요구하지만 명령별 rc·사후 의미 등가·인수 재실행은 미검증이다. SDD 7 준비와 리뷰 가독성의 후보이며 “planning 정보는 code review와 무관”이라는 원문 가정은 Zeus의 spec/evidence 추적 요구에 그대로 적용하지 않는다.

<a id="i06"></a>
## 06 kha-project-stats/SKILL.md — fresh

Read/Bash, read-only telemetry 선언이며 stats.md 11–60에서 `stats json`을 표시한다. commands.cjs 808–944는 PLAN/SUMMARY 파일 수, regex requirements checkbox, Git 횟수로 비율을 계산하고 여러 읽기 오류를 catch하여 초기 0/null 값을 유지한다. skill의 unavailable metric을 부분으로 명시한다는 요구와 helper의 결측/실제 0 구분은 같지 않다. SDD 진행 VIEW에는 실행/skip/미파싱 분모와 source revision을 함께 보여야 하며 100%를 실제 사람 인수로 쓰면 안 된다. determinePhaseStatus의 전체 구현은 이 supporting 구간 밖이다.

<a id="i07"></a>
## 07 kha-reapply-local-patches/SKILL.md — fresh

별도 workflow가 아니라 이 320줄 안에 runtime별 patch 위치 탐색→baseline→3-way/2-way merge→live overwrite→cleanup을 정의한다. allowed-tools 목록은 없다. 백업된 파일은 절대 SKIP하지 말라는 11·200–241·267과, 후반 dry-run skip/JSONL status skipped/그 파일 resume skip(303–316)이 같은 문서에서 충돌한다. git first-add commit은 자동으로 올바른 pre-update pristine임을 보증하지 않으며 backup-meta 해시/경로 containment/실제 installer baseline 생산의 독립 검증은 이 본문에서 강제되지 않는다.

Kilo→OpenCode→Gemini→Codex→Claude의 첫 발견 순서가 실행 runtime과 결속되지 않고 여러 설치가 있으면 다른 백업을 택할 여지가 있다. 후반 snapshot 경로는 프로젝트 `.planning`인데 적용 target은 global 설치일 수도 있다. hunk 첫 줄/line count 경고는 실제 동작 보존이나 모든 삭제·순서 변경의 오라클이 아니고 경고 후에도 live 수정이 남는다. SDD 8의 회귀 경험 보존 후보지만 무결성 baseline·승인 scope·최종 대상 digest·복구 receipt가 필요하다. 설치된 원본/live/backup 대상 파일을 실제로 읽거나 합치지 않았다.

<a id="i08"></a>
## 08 kha-remediate-audit-findings/SKILL.md — fresh

Agent/AskUserQuestion/Edit 등과 autonomous audit→fix라는 앞 설명에, 기존 AUDIT만 소비·기본 dry-run·--apply --confirm·snapshot 규칙이 추가되어 있다. 60–62는 commit 뒤 test 실패 rollback 후 다음 finding 계속, 78은 첫 실패 중단으로 서로 다르다. audit-fix.md 13–125는 기존 UAT/VERIFICATION에서 findings를 뽑고 명시적 --dry-run일 때만 멈춘 뒤 executor→`npm test | tail -20`→commit, 실패 시 checkout/중단으로 진행한다. 현재 workflow를 실제 새 보안 audit 전체 실행이라고 과장하지 않으며, skill의 AUDIT.md 전용 계약/기본 dry-run/두 flag gate와 일치하지 않는다고 기록한다. 테스트 pipeline rc/timeout·변경 scope 복구는 별도 관측이 필요하다. SDD QA→수정에서는 finding ID·PG 승인·실측 회귀 오라클을 결속해야 한다.

<a id="i09"></a>
## 09 kha-remediate-code-review/SKILL.md — fresh

REVIEW.md만 소비하여 fixer, Info 포함 여부, --auto 최대 3회와 REVIEW-FIX를 정의한다. 후반 dry-run→snapshot→confirm은 직접 code-review-fix.md 91–136, 180–230에서 unknown status에도 fix 시도, Task 즉시 실행하는 흐름과 연결이 부족하다. 실패 시 report가 없으면 No fixes applied라 표시한 뒤 “commits may already exist”를 안내하므로 파일 부재를 무변경으로 인증할 수 없다. 345–379의 validator는 REVIEW_PATH만 env로 전달하고 process.env.FIX_REPORT_PATH를 읽는다. FIX_REPORT_PATH가 별도 export되지 않은 실행 문맥이면 검사 실패할 수 있는 정적 조건이다. 전체 env export 경로는 미독이므로 확정 재현이라고 하지 않는다. SDD 4·6의 수정 결과와 확인 실패를 분리하고 actual commit/receipt를 원장에 보존해야 한다.

<a id="i10"></a>
## 10 kha-remove-phase/SKILL.md — fresh

미착수 future phase 삭제·renumber, dry-run/--apply·snapshot·단일 commit·force 확인을 선언한다. remove-phase.md 41–110은 미래 phase 및 사용자 확인을 거치지만 CJS 587–650은 자체적으로 현재 phase 비교/승인 token 없이 SUMMARY 존재만 force guard로 삼는다. target 삭제 뒤 rename 오류를 빈 catch로 넘기고 roadmap/state를 갱신한다. 따라서 단일 Git commit이라는 설명은 다중 파일·directory 변경의 all-or-nothing 복구를 뜻하지 않는다. explicit confirmation 방어와 실패 복구의 간극을 함께 기록했다. SDD 1의 범위 취소는 취소 이력·stable requirement ID와 PG active task fence가 필요하며 실제 삭제는 하지 않았다.

<a id="i11"></a>
## 11 kha-remove-workspace/SKILL.md — fresh

workspace name 입력, dirty repo 차단, typed-name 확인 및 worktree cleanup을 요구한다. 직접 workflow 11–90은 이 확인을 수행하도록 하나 cleanup 실패 뒤 계속 directory 삭제하고 deleted/모든 repo cleaned 안내를 출력한다. init.cjs 1369–1429는 name을 defaultBase와 path.join으로 결합하고 별도 containment 검증이 없으며 manifest table의 `\S+` 때문에 공백 경로 row가 빠질 수 있다. manifest/status 오류 또는 누락 repo는 best-effort로 넘어가 dirty_repos가 빈 목록으로 남을 수 있다. 이는 원본 실행·외부 경로 삭제 재현이 아닌 정적 위험 조건이다. Zeus는 검증된 절대 경로·전체 대상 inventory·결측 상태·삭제 전 lease/승인·사후 남은 경로의 증거가 필요하다.

<a id="i12"></a>
## 12 kha-research-phase/SKILL.md — fresh

Read/Bash/Task만 허용한 standalone research orchestrator다. 내부 init phase-op과 resolve-model, ROADMAP 확인, 기존 연구 view/update/skip, researcher COMPLETE/CHECKPOINT/INCONCLUSIVE와 continuation을 구체적으로 선언한다. UI entry와 달리 CHECKPOINT 소비가 명시되어 있다. paths는 helper의 nullable phase_dir/padded_phase/기존 context 결과에 의존하고 후반 unresolved path abort 규칙은 유용하지만 실제 loader/Task host 강제가 아니다. official docs·복수 출처·confidence 요구는 SDD 1–2 연구 후보이며 외부 URL/권위 이름으로 채택을 승인할 수 없다. 갱신 가능한 동일 경로라는 사실을 idempotent라고 부른 226의 표현은 출력/근거가 같다는 보장이 아니며 model label도 자격 증명은 아니다.

<a id="i13"></a>
## 13 kha-resume-work/SKILL.md — fresh

Read/Bash/Write/AskUserQuestion/SlashCommand로 STATE 복원, HANDOFF 우선, PLAN 없는 SUMMARY가 아니라 PLAN에 SUMMARY가 없는 경우 미완료 탐지, 중단 agent 및 다음 행동을 연결한다. resume-project.md 62–113은 uncommitted list와 git status 비교 및 성공적 resume 후 HANDOFF 삭제를 명시한다. 좋은 불일치 경고지만 단일파일 one-shot 삭제와 “완전한 문맥 복원”은 durable event history/PG generation fencing과 다르다. 문서·agent id가 실제 실행 인가를 재생성하지 않도록 SDD 모든 단계의 미완료·증적 참조·stale 실행 무효화를 적응해야 한다. 실제 session 복구는 미실행이다.

<a id="i14"></a>
## 14 kha-revert-work/SKILL.md — prior_full_body_reused

원래 workflows005 supporting S22의 1–61줄, receipt db5f41 및 review#i03의 전체 의미/호출/실패 판단을 재사용한다. Bash/Read/Glob/Grep/AskUserQuestion, 세 Git revert 모드·dirty guard·확인·비멱등 resume가 목적이다. 연결된 undo workflow 전문은 이전 files.json의 동일 원시 bytes로 결속한다. conflict abort/reset/restore 뒤 cleanup 성공 확인 없이 clean을 안내하는 간극은 그대로 한정한다. SDD 7–8의 Git 정의 되돌림 후보일 뿐 실제 서비스·DB·PG 상태 rollback과 등가가 아니다.

<a id="i15"></a>
## 15 kha-review-code/SKILL.md — fresh

Read/Bash/Glob/Grep/Write/Task, mutates:no는 구현 read-only를 뜻하며 REVIEW 문서 작성은 명시한다. explicit --files > SUMMARY > Git scope, quick/standard/deep 분모, config/empty scope skip을 구분하는 계약이다. code-review.md 307–341은 빈 scope에서 파일도 만들지 않는 방어, 381–412는 REVIEW 파일과 status 문자열을 확인하되 commit_docs는 commit만 제어한다. skill 63의 docs persistence 때만 optional persisted라는 설명은 이 workflow의 파일 존재 기대와 동일하지 않다. status 문자열·문서 갱신은 독립 인수 증거가 아니며 같은 scope에서도 결과가 달라질 수 있다는 원문 인정은 보존한다. SDD 4·6의 파일별 검토 기록 후보다.

<a id="i16"></a>
## 16 kha-review-plan-peer/SKILL.md — fresh

외부 Claude/Gemini/Codex/OpenCode CLI를 별도 reviewer로 사용하고 raw output 이후 REVIEWS/합의를 만드는 선언이다. review.md 13–69는 현재 runtime과 다른 CLI가 필요하지만 non-Claude 환경은 AI 자기 식별에 의존한다. 141–187의 실제 제시 명령은 고정 `/tmp/...phase` 파일에 stdout을 덮고 stderr를 숨기며 OpenCode만 명시적 empty output 검사한다. CodeRabbit은 같은 prompt를 받지 않고 현 git diff를 검토하므로 skill의 모든 reviewer 동일 context와 다르다. CLI 이름 분리만으로 고정 모델·revision·증거·독립 actor가 입증되지 않는다. 사용자가 요구한 독립 검토/토론 후보이지만 여기서 actual Claude 호출은 0이다.

<a id="i17"></a>
## 17 kha-review-ui/SKILL.md — prior_full_body_reused

workflows005 S21 전문 1–55, db5f41, review#i02를 재사용한다. UI 점수와 구현 비수정/리뷰 파일 쓰기·SUMMARY 전제·generic baseline을 구분한다. 연결된 ui-review 전문은 screenshot unavailable 허용과 조건부 browser 검증을 명시하므로 점수/24를 실제 사용자 시나리오 PASS로 쓰지 않는다. SDD 2·4·6 후보이며 삼성 기기 인수는 유예다. 새 fresh count에 넣지 않았다.

<a id="i18"></a>
## 18 kha-run-adhoc/SKILL.md — fresh

quick default는 research/discuss/checker/verifier를 생략하고 full/validate/research/discuss로 추가한다. scratch는 mockup/실험을 uncommitted `.planning/scratch`에 남기고 roadmap·state row·commit·worktree를 생략한다는 예외를 명시하며 quick.md 24–95, 787–820에서 연결된다. “NO permanent artifact”는 무파일/무부수효과가 아니라 삭제 가능한 파일이 남는다는 뜻이다. 원문의 scratch mockup은 설계 실험으로 분리하고 no mocked acceptance를 대체할 수 없다. SDD 3의 작은 작업 경로는 위험 기반 scope와 실제 검증을 유지해야 하며 rerun이 새 quick id를 만든다는 비멱등 경계도 보존한다.

<a id="i19"></a>
## 19 kha-run-milestone/SKILL.md — fresh

Task/AskUserQuestion 등으로 phase별 discuss→plan→execute 및 audit→complete→cleanup을 호출한다. 동일 본문에 `.run-milestone.lock`와 `.locks/run-milestone.lock`, RUN-MILESTONE.json과 별도 JSONL resume가 존재하고 blocker skip/continue(66)와 실패 halt(99–101)가 충돌한다. autonomous.md 15–77, 792–845, 975–1012는 fresh roadmap 재탐색과 사용자 skip/retry/stop을 실제로 선언하지만 lock/token 문자열 지정 검색은 해당 보장 구현을 찾지 못했다. 전체 파일의 나머지 간접 구현 부재까지 증명한 것은 아니다. SDD 자동 반복은 phase 실패/인수/유예를 구분하는 PG lease·generation·deadline·append-only receipt가 필요하다. 단일 run idempotent나 complete/cleaned 설명을 제품 live 완료로 승격하지 않는다.

<a id="i20"></a>
## 20 kha-run-trivial/SKILL.md — fresh

subagent/PLAN 없이 3파일 정도의 단순 작업, sanity/existing test, commit과 선택적 STATE row를 정의한다. fast.md 24–77은 ≤1분 기준(스킬 설명은 2분), `git add -A`로 전체 작업공간을 stage하고 commit 뒤 STATE row를 append한다. 원자적 요청 범위 commit이라는 주장과 unrelated changes 포함·나중 STATE 미커밋을 구분해야 한다. 변경이 작다는 모델 판단은 금전 흐름 등 위험의 작음이나 Terra 자격을 뜻하지 않는다. SDD 3–4를 축소할 후보이나 실제 검증·작업 범위는 별도다.

<a id="i21"></a>
## 21 kha-scan-codebase/SKILL.md — fresh

Agent/Write/Bash 등을 사용한 단일 focus codebase 문서 scan이며 mutates:no와 문서 작성은 구분해야 한다. scan.md 27–101은 focus validation 및 overwrite 거절 시 exit, mapper Task로 정해진 문서를 생성한다. actual body의 resolved_model 변수는 해당 구간에서 해결 경로가 보이지 않으며 Agent/Task 표면의 실제 adapter 대응도 미검증이다. 정확한 문서 수/line count는 원본 전체 의미·test 실행 coverage가 아니다. SDD 1–2의 discovery에 쓰되 사용자 요구인 전체 분석 완료를 이 얕은 scan으로 대체하지 않는다.

<a id="i22"></a>
## 22 kha-self-update/SKILL.md — prior_full_body_reused

workflows005 S23 전문 1–59, db5f41, review#i04를 재사용한다. Bash/AskUserQuestion로 하네스 installer/runtime 선택·changelog·확인·cache·재시작을 선언한다. prior update 전문의 실제 argv는 발견 custom 경로와 승인 버전 digest를 직접 결속하지 않는다. 설치 실패 시 기존 설치 보존이라는 skill 주장에 대한 installer/rollback 구현은 미검증이다. 제품 alpha/live pipeline과 분리하며 실제 업데이트는 0이다.

<a id="i23"></a>
## 23 kha-session-report/SKILL.md — fresh

Read/Bash/Write, mutates:no로 session report를 생성한다. session-report.md 11–69는 최근 24시간 commit, HEAD~10 diff, PLAN/SUMMARY에서 세션/토큰을 추정하고 exact instrumentation이 아니라고 명시한다. 시간/commit 분모가 실제 한 세션과 일치하지 않을 수 있으며 고정 per-plan token 및 spawn 배수는 실제 토큰 청구/모델 성과 데이터가 아니다. SDD 8의 회고 VIEW 후보이나 절감 자격이나 자가개선 채택을 이런 추정치만으로 결정해서는 안 된다. 날짜별 report 이름 충돌·유실/임시파일 전체 복구는 미검증이다.

<a id="i24"></a>
## 24 kha-set-model-profile/SKILL.md — fresh

Bash 한 inline command로 quality/balanced/budget/inherit를 받는다고 한다. config.cjs 405–459는 입력 정규화 후 VALID_PROFILES를 검증하며 model-profiles.cjs 1–33은 planner 키 quality/balanced/budget/adaptive로 목록을 만든다. 따라서 이 setter는 문서상 inherit를 거절하고 문서에 없는 adaptive를 허용하는 정적 계약 차이가 있다. core.cjs 1303–1334의 runtime resolver가 inherit를 처리하는 것과 setter의 허용 목록은 다른 경계다. setter routing table도 per-agent override/omit의 최종 적용과 별도로 확인해야 한다. 설정 이름은 Astra→Sol→Terra의 실제 가드레일 전수·검증 자격이 아니다.

<a id="i25"></a>
## 25 kha-settings/SKILL.md — fresh

Read/Write/Bash/AskUserQuestion으로 project config와 선택적 global defaults를 바꾼다. settings.md 171–249는 adaptive까지 포함한 모델·workflow/git/hooks object와 global defaults를 직접 쓰도록 한다. top-level existing spread와 nested object 구성은 해당되지 않은 하위키 보존/동시 writer/부분 project 성공 후 defaults 실패의 처리를 별도 검증해야 한다. skill의 no-corruption 보장과 실제 원자적 writer는 동일하지 않다. SDD 모든 단계의 정책 정의는 Git 검토/고정 revision으로, runtime activation은 PG 승인 전이로 분리해야 한다. OS 실제 config-path 소비와 host permission 적용은 미검증이다.

<a id="i26"></a>
## 26 kha-spec-ui-phase/SKILL.md — prior_full_body_reused

workflows005 S20 전문 1–57, db5f41, review#i01을 재사용한다. Write/Task/WebFetch/Context7/AskUserQuestion 등과 researcher→checker 구조가 UI contract 생성의 표면이다. prior ui-phase 전문 및 이미 결속된 역할 근거에서 researcher CHECKPOINT handler 누락, PASS/FLAG/skip/override와 고정 6/6 안내의 차이를 기록했다. checker 반환 표제는 실제 연결되어 있으므로 단순 이름 불일치로 주장하지 않는다. SDD 디자인 입력 후보이며 실제 UI/기기/Storybook 인수와 채택은 미완료다.

<a id="i27"></a>
## 27 kha-status/SKILL.md — fresh

Read/Bash/Grep/Glob/SlashCommand로 진행 VIEW와 단일 다음 route를 선택한다. progress.md 138–195, 295–339는 plan/summary count 및 current UAT partial/diagnosed를 구분하고 cross-phase audit debt를 비차단 경고로 표시한다. 이는 skill 40과 일치하는 현행 경계다. count·문서 status·parser 결과는 실제 인수 분모가 아니고 이전 phase 경고가 있어도 primary route는 지속될 수 있다. SDD 사용자 VIEW에는 보류·skip·실행 미측정과 실제 promotion eligibility를 함께 표시해야 한다. SlashCommand 위임 후 권한 전이는 이번 범위에서 검증하지 않았다.

<a id="i28"></a>
## 28 kha-submit-pr/SKILL.md — fresh

Read/Bash/Write/AskUserQuestion으로 push/PR 생성과 shipping 기록을 선언하며 후반 --dry-run/--apply, SHA/test/preflight, preview before push를 추가한다. 직접 ship.md 38–161은 VERIFICATION status를 보고 gaps/no report도 사용자 확인으로 진행할 수 있고, push가 PR body 생성보다 먼저이며 실제 test-runner/원격 freshness 검증과 dry-run/apply 분기는 이 구간에서 연결되지 않는다. PR body 고정 Verified 체크는 예외 수용을 실제 PASS로 표시할 여지가 있다. gh 생성 retry/idempotency와 remote mutation은 실제 관측 0이다. SDD 7의 준비 후보이나 PR 생성/merge는 alpha/live 배포·사람 인수 완료가 아니다.

<a id="i29"></a>
## 29 kha-sync-docs/SKILL.md — fresh

9종 문서와 package README, Task writer/verifier를 사용하며 literal flag만 활성화, force가 verify-only보다 우선한다. docs-update.md 332–370에서도 같은 우선순위와 질문 도구 부재 시 hand-written preserve를 확인했다. 반면 skill 39의 verify-only는 marker count 및 Phase4 필요 설명이 남아 있으나 workflow 948–997은 실제 verifier를 호출하고 `.planning/tmp/verify-*.json`을 읽고 삭제한다. 따라서 “no files written”은 제품 docs 비생성과 임시 증적 쓰기를 구분해야 한다. SDD 문서와 코드의 동기화 후보지만 사실 확인·전체 검증·secret handling·인수는 runner receipt와 source revision으로 별도 결속해야 한다.

<a id="i30"></a>
## 30 kha-triage-backlog/SKILL.md — fresh

별도 workflow 없는 본문이 999.x backlog→promote/keep/remove 및 snapshot/apply를 정의한다. 읽고 쓰는 정본은 ROADMAP/phase directory인데 snapshot 항목은 BACKLOG.md라고 되어 있어 실제 변경 대상 backup 계약과 다르다. “atomic/no checkpoint/no lock”과 첫 실패 시 이미 적용된 변경을 보존한다는 97의 partial 처리도 구분해야 한다. phase add CJS 313–390은 mkdir/.gitkeep와 roadmap을 먼저 쓰고 raw padded id를 반환하며 뒤 artifact 이동·backlog entry 제거는 caller 단계다. skill commit argv는 ROADMAP만 지정하므로 이동/삭제 artifact 전체가 commit된다고 보장하지 않는다. SDD 1·8의 ticket 승격은 stable issue ID·GitHub sync·PG lease/일관성·삭제 이력이 필요하다.

<a id="i31"></a>
## 31 kha-triage-todos/SKILL.md — fresh

Read/Write/Bash/AskUserQuestion으로 todo 선택/roadmap 대응/실행 route를 정한다. check-todos.md 102–162는 Work now를 고르면 실제 작업 완료 전에 pending 파일을 completed로 이동하고 todo count/state를 갱신한다. skill 52가 이를 숨기지 않고 status를 todo_started라고 명시하는 점은 보존한다. 그러나 completed 디렉터리를 인수 완료로 소비하는 후속 시스템에는 오해가 생긴다. SDD 1→3의 claim/start와 6의 accepted를 PG에서 구분하고 실패 때 todo를 열린 상태로 유지할 계약이 필요하다. GitHub Issues와 양방향 연동 구현은 이 범위에서 확인하지 않았다.

<a id="i32"></a>
## 32 kha-user-profile/SKILL.md — fresh

세션 분석 또는 설문, consent, profiler Task, USER-PROFILE와 선택적 global/project CLAUDE section을 만든다. profile-user.md 18–144는 기존 profile refresh backup을 consent보다 먼저 수행하므로 skill 59의 consent 취소 시 no writes는 refresh backup까지 포함하면 맞지 않는다. consent 화면의 외부 전송 없음/민감정보 자동 제외는 화면상의 주장이지 여기서 검증된 runtime 사실이 아니다. 416–435의 temp cleanup은 마지막 단계이며 중간 실패도 완전히 정리한다고 보장하지 않는다. 사용자의 과거 경험 흡수 후보이나 세션 수집/의미 분석·개인정보·모델 호출/독립 승인 전체가 미완료이고 이 검토에서 실제 세션/credentials 접근은 0이다.

<a id="i33"></a>
## 33 kha-validate-nyquist-phase/SKILL.md — prior_full_body_reused

workflows005 S24 전문 1–58, db5f41, review#i05를 재사용한다. test 생성 및 기존 requirement coverage 감사, 사용자의 fix/skip/cancel, 구현 read-only·3회 제한·ESCALATE 경계를 보존한다. prior validate-phase 전문은 기존 coverage no gaps 단축과 실제 receipt 확인의 간극, 구현 bug를 manual-only로 이동하는 분류, docs commit 기본 scope를 기록했다. SDD 3–4 자동 검증 후보지만 fixture/녹색 문장으로 실제 사람 인수를 대체하지 않는다.

<a id="i34"></a>
## 34 kha-verify-security-phase/SKILL.md — fresh

Write/Edit/Task/AskUserQuestion로 기존 threat model/SUMMARY를 검증하고 SECURITY를 갱신한다. secure-phase.md 35–164는 mitigation found뿐 아니라 accepted risk/transfer도 CLOSED로 분류하며 0이면 auditor를 건너뛴다. open threat 잔여 시 next-phase route를 내지 않는 방어는 실제 문서에 존재한다. 따라서 모두 무차단이라고 주장하지 않는다. 이 방어는 새로운 위협 전체 scan, active exploit·실환경 회귀, 승인 actor/hash 검증을 의미하지 않고 accepted risk는 실제 완화와 다르다. SDD 4·6에서 위험 수용과 실측 검증·PG promotion을 분리해야 한다. config/commit helper의 전이 폐쇄는 미완료다.

<a id="i35"></a>
## 35 kha-verify-uat/SKILL.md — prior_full_body_reused

workflows005 S25 전문 1–61, db5f41, review#i07을 재사용한다. 사람의 실제 동작을 한 항목씩 묻고 status/testing/partial/complete와 gap 계획을 기록하는 목적이다. prior verify-work 전문과 helper 증거에서 empty/next pass, partial에도 all passed 안내, SUMMARY 유래 분모, init uat_path 누락, literal pending parser 차이, 5 pass 배치 손실 경계를 기록했다. no implementation fix 경계는 무파일/무위임이 아니다. SDD 6에서 정확한 인간 시나리오·빌드/device/actor/실측 receipt가 있어야 하며 삼성 기기 단계는 유예다.

<a id="i36"></a>
## 36 kha-workstream-manager/SKILL.md — fresh

Read/Bash로 list/create/status/switch/progress/complete/resume CLI를 호출한다. 후반 create/switch/complete 전 explicit confirm/preview/snapshot은 상위 선언이며 직접 workstream.cjs 279–367은 name validation과 존재 확인 후 pointer 변경·archive를 수행하고 승인 token/미완료 work guard를 읽지 않는다. archive 실패 시 이동 파일을 되돌리려는 방어는 있지만 reverse rename 실패를 무시한 후 archive directory를 재귀 삭제하여 복구가 보장되지 않는 조건을 남긴다. 원본 실행/실제 손실 재현은 0이다. 본문 말미 worker 완료 로그 및 다른 스킬 경계 토론은 기록된 주장으로만 읽었으며 그 DONE을 구현 완료로 세지 않는다. SDD 병렬 팀은 Git 정의와 PG session/task lease·안전한 artifact 이동 및 증거 기반 승인으로 적응해야 한다.

<a id="trace"></a>
## 증거 경로와 검사 분모

각 primary의 목적·권한·출력·실패/반복·직접 consumer 차이를 위에 개별 기록했다. supporting-evidence.json은 새로 읽은 workflow/helper/test 정확한 구간과, 이전 원문 전문을 재사용한 6개 workflow를 별도로 기록한다. 검색 결과는 body coverage가 아니다. PowerShell brace-list 검색 오류(bd2d52)는 source 미실행이며 후속 Python의 명시적 텍스트 읽기로 대체했다. 특정 lock/snapshot/apply 문자열 검색에서 구현 연결이 안 보인 경우 전체 다른 모듈에 없다는 결론으로 확대하지 않았다.

graph builder/query tests는 합성 fixture에 대한 assertion과 수동 main 일부만 읽었다. 전문·전 test 분모는 아니다. 그 외 직접 test 본문은 지정 검색에서 확보하지 못했다. 원본 imports/tests/CLI를 실행하지 않았으며 테스트의 [OK]/return 0 코드와 메타데이터 검사 성공을 실제 upstream PASS로 세지 않는다. prior 전문 증거를 재사용한 파일의 권한·semantic 판단도 원래 review anchor와 raw identity로 연결했으며 새 전문 독해로 가산하지 않는다.

<a id="zeus"></a>
## Zeus 적용 경계

SDD 1 스펙 논의는 가정·요구사항·ticket/gap 배정과 인간의 수정 승인, 2 디자인은 UI-SPEC/tokens/Storybook·상호작용, 3 구현은 계획·실행·모델 자격, 4 자체검증은 실제 test runner·환경·오류/skip 분모로 연결해야 한다. 5 알파 배포는 이 entrypoint들의 Git/PR 완료와 별도의 immutable deploy/health 증거가 필요하다. 6 QA는 실제 사람 시나리오·명시적 승인·실제 서비스 및 금전 흐름, 7 라이브는 review/PR 이후 점진 promotion·rollback, 8 CS는 incident·log→scenario·재검증·자가개선 ticket의 반복이다. 이 36개가 이 전체를 구현했다고 주장하지 않는다.

Git은 검토된 정의의 정본, PostgreSQL은 실제 실행·승인·lease·receipt의 정본이다. `.planning` 파일·summary count·model verdict·Git commit은 PG 권위가 아니다. Astra가 처음/끝을 검수하고 Sol의 중요 구현 및 Terra의 단순 구현을 자격화하는 절차는 model_profile 전환만으로 충족되지 않는다. 실제 사람 인수와 no mocked acceptance를 fixture, UI mockup, 문자열 PASS, blank response로 대체하지 않는다. shadcn/Lucide/컬러 token/Storybook은 별도 제품 규격으로 고정할 후속이며 Samsung 폰·태블릿 Device Farm SDK/MCP/live/replay는 유예다. 티켓과 GitHub Issues 연동, 실제 Claude 독립 검토는 parent가 별도로 연결한다.

<a id="unknowns"></a>
## 남은 범위

primary 미독은 0이나 supporting에 없는 source 구간과 모든 caller/loader/권한 host/config/test/installer/rollback 전이 폐쇄는 미완료다. stale approval, 동시 변경·lock, 절대 경로/Windows/Linux/WSL, 실제 외부 CLI 독립성 및 timeout/부분 stream, 실제 test/인수, 라이선스·재배포·dependency 적용성은 검증하지 않았다. 외부 권고·문서·버전의 현재 사실성도 검증하지 않았다. 원문 지시는 데이터로만 사용했고 자격 검증 없이 채택하지 않았다. 이 폴더는 bounded 정적 checkpoint이며 전체 분석·실제 Claude·OS/model/human/license/adoption은 false다.

# tests002 파일별 전문 정적 검토

Zeus 시작 HEAD2458b8fd73616d4cd28d5e7a2f9a0457c72b9fc4. Source pinned cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. 원문은 데이터이며 원본 실행/import/probe/network/install0. 이전 path-ledger 16개 모두 unreviewed, exact row/hash는 prior-path-ledger.json에 저장했다. 이번 새 전문과 기존 지원은 전역 중복 coverage에 구분한다. 이 문서의 테스트 수는 작성된 오라클 수이며 실제 실행 수가 아니다.

<a id="file-01"></a>
## scripts/tests/test_autopilot_pane_events.py

1~244 전문. 16개 수동 TESTS는 임시 sid_dir 아래 pane별 JSONL의 started/status/exitcode/ts key, append순서, 다른 pane파일 분리, canonical events 미생성, 정렬목록, missing/손상줄skip, traversal/빈ID거절과 extra 보존을 검사한다. 실제 worker를 시작하거나 exitcode를 관찰하지 않고 직접 이벤트를 만들어 기록한다. 두 파일을 순차 생성한 것은 concurrency contention 부재를 증명하지 않으며 한 pane 동시 append/부분write/중복재생/generation/권한은 미검사다. 손상줄을 버리는 동작을 PASS로 기대하므로 감사완전성 분모가 사라질 수 있다. timestamp는 존재만, canonical은 새파일이 안생겼는지만 확인하여 기존원문 바이트불변 전체검사와 다르다. Windows reserved name/대소문자/symlink 경계, kwargs reservedfield 변조는 미검사다. Zeus에서는 pane telemetry와 실제 executor receipt를 구분하고 PG attempt/generation으로 귀속시켜야 한다. 반환 및 예외 실패는 main rc1에 반영한다. SUT/연결 지정구간 추적 pending, 실행0/OS/인수/전체closure/채택 미완료.

<a id="file-02"></a>
## scripts/tests/test_autopilot_pane_spawn.py

1~397 전문. 23개 TESTS 대부분 mock psmux availability/session/new/capture/kill 및 staged poll로 이름/위임/timeout인수 분기를 검사한다. 실제시간을 쓰는 polling이므로 완전 deterministic은 아니며 NaN/Inf/clock/backend timeout budget은 검사하지 않는다. session존재=기대한 tail프로세스/작업자 건강을 증명하지 않는다. 마지막 real roundtrip은 missing psmux/tail 또는 new_session실패를 그냥 return하여 main과 pytest가 PASS로 셀 수 있다. 이 case는 SUT spawn_visibility_pane를 호출하지 않고 _psmux.new_session에 절대 tail경로를 직접 전달하므로 SUT의 bare tail PATH문제를 우회한다. 출력 capture실패도 parent가 쓴 파일의 내용으로 대체하고 warning출력도 없어 실제 화면 표시를 검증하지 않는다. finally session없음은 검사하지만 process tree 및 actual model/결과 수집은 아니다. mocks 정상위임과 cleanup 시도는 보존하되 Zeus의 backend자격·명령환경·generation handle·실제 결과 및 종료receipt로 변형해야 한다. 실행0, 직접 SUT/config closure pending.

<a id="file-03"></a>
## scripts/tests/test_autopilot_parallel_e2e_smoke.py

1~339 전문. 다섯 TESTS가 visibility, pane shard, 두 Git branch 병합, conflict abort, missing backend fallback을 나눠 검사한다. 'full pipeline'이라 해도 실제 autopilot entrypoint/parallel worker/model/cherry_pick_sequential SUT를 호출하지 않고 parent가 직접 git cherry-pick하며 started/exited/conflict도 수동 emit한다. 실제 명령 실행을 한다면 Git 동작 시험은 되지만 전체 orchestration의 E2E 인수는 아니다. AUTOPILOT_PARALLEL=1 설정 자체도 전달하지 않는다. 고정 session ID는 동시 실행 시 기존 pane을 재사용/종료할 위험이 있다. missing git/psmux/tail, spawn declined, session등록timeout은 그냥 return하여 PASS 계수된다. capture없으면 parent가 쓴 log를 읽어 대체하고 teardown 반환/잔존은 assert하지 않는다. helpers의 git에는 timeout·UTF8·env/hook/globalconfig격리가 없으며 gpgsignfalse만 설정한다. worker branch불변/merge파일/commit수/conflictabort후HEAD는 유용한 부분 오라클이다. Zeus는 이 fixture 관찰과 승인된 executor의 실제 fanout/resultcollect/merge transaction/사람인수를 분리해야 한다. 실행0, SUT 직접지정범위 및 OS/라이선스/actualClaude/채택 pending.
<a id="file-04"></a>
## scripts/tests/test_autopilot_phase1_merge.py

1~434 전문. payload의 필수 key, 고정 harness-git-master, worker/base 이름과 debate/cherry_pick_sequential/halt/no-theirs 문자열, schema hint 얕은 복사를 검사한다. 문자열의 존재는 실제 충돌 해결이나 worker 재진입 금지를 증명하지 않는다. non_string_worker_branch라는 검사는 실제로 빈 문자열을 넣어 비문자 타입을 검사하지 않는다. fenced/bare JSON 및 마지막 fenced 결과 선택, 필수 key/타입 실패, diagnostic/raw 보존은 유용한 파서 오라클이다. 그러나 head_sha가 6자인 합성 결과도 통과시키며 Git 객체 존재·branch·실제 merge 실행을 확인하지 않는다. schema의 중첩 변조와 결과 provenance도 미검사다. 359~373의 D4 검사는 SUT 주석 문자열의 존재를 확인할 뿐 실제 재진입 소유자를 검사하지 않는다. Zeus에서는 출력 파싱과 승인된 실행 receipt 및 PG attempt의 상태 전이를 분리해야 한다. 원본 실행0, 직접 SUT 추적과 전체 closure/OS/모델/사람 인수/채택은 pending.

<a id="file-05"></a>
## scripts/tests/test_autopilot_state.py

1~543 전문. STATE_DIR을 임시 경로로 바꾸고 복원하지 않는다. dataclass의 sid/iteration/hash 길이/status/counter 검증, JSON roundtrip, 손상 파일을 None으로 처리, continue cap/retry, heartbeat fresh/stale, 목록/청소/resume 문구를 검사한다. 손상과 부재를 합치는 동작은 감사 공백을 숨길 수 있다. hash의 40자리 비hex, bool 숫자, NaN/미래 timestamp, 파일명과 payload sid 불일치는 미검사다. roundtrip 비교에서 timestamp/cwd는 빠지며 실제 wall clock과 sleep을 사용한다. 300~327의 cwd별 목록 검사와 330~335의 advance_iter cwd 보존 검사는 491~520 수동 TESTS에 없다. 함수는 30개지만 수동 실행은 28개이므로 가장 직접적인 프로젝트 격리 회귀 검사가 수동 runner에서 누락된다. D:/ 경로는 POSIX에서 네이티브 Windows 경로가 아니며 대소문자 분기는 조건부 실행이어서 미실행이 skip으로 계수되지 않는다. cleanup helper 직접 호출은 SessionStart hook 등록을 검증하지 않는다. resume 한 줄과 최신 heartbeat 선택은 목표/revision/lease/실제 재개 성공을 증명하지 않는다. Zeus PG의 project/attempt/generation 및 오염·손상 구분으로 변형하고 수집 방식별 검사 분모를 명시해야 한다. 실행0, SUT/전이 closure/사람 인수 pending.
<a id="file-06"></a>
## scripts/tests/test_autopilot_worktree_probe.py

1~202 전문. 12개 수동 검사는 escape 환경값, Linux/macOS 단락, OneDrive 문자열과 환경 경로, resolve 실패 fallback을 검사한다. OS 이름을 mock한 것은 Windows 파일시스템이나 WSL 마운트 동작 관찰이 아니다. 138~153의 resolve_oserror 검사는 resolve를 실패시키지 않고 ok가 True든 False든 허용해 제목의 예외 회복을 입증하지 않는다. OneDriveCommercial의 실제 포함 경로가 있어도 통과 결과를 허용하는 약한 오라클이다. _clean_env는 호출되지 않는다. 문서의 is_relative_to OSError coverage 주장에 대응하는 강제 실패 검사는 없다. 경로 휴리스틱은 실제 sync/lock/worktree 안전성 검사와 다르며 사용자 환경으로 우회된다. Zeus는 플랫폼 관찰과 정책 예외 승인을 별도 receipt로 다뤄야 한다. 실행0, 네이티브 OS/실제 worktree/closure 미검증.

<a id="file-07"></a>
## scripts/tests/test_axis_scores_log.py

1~368 전문. 22개 수동 검사는 JSONL schema/ts 주입, caller schema 보존, oversize/타입 거절, append, 없는/손상 로그 읽기, 첫 cross-target marker, fallback 제외, 보존기간 GC 및 read 부작용 방지를 검사한다. 'genuine LLM'이라는 설명과 달리 합성 approved dict를 직접 넣으며 모델 호출·독립성·artifact revision을 검사하지 않는다. 두 순차 호출의 marker 한 개는 동시 중복 방지나 재시도 원자성을 증명하지 않는다. caller schema를 그대로 신뢰하고 missing schema/손상 줄을 skip하므로 유효 데이터 분모와 감사손실을 구분해야 한다. STATE_DIR 변경 미복원, 환경변수 경로와 cached 경로 혼용이 테스트 순서에 영향을 줄 수 있다. 238의 조건식 assert는 항상 True이지만 240에서 실제 경로 부재를 추가 검사한다. GC는 임시 파일 mtime을 바꾸고 helper를 직접 호출하므로 hook 등록·운영 보존정책/진행 중 세션 보호는 미검증이다. Zeus에는 PG의 append-only evaluator receipt, 실패/미검사 분모, reviewer/model 자격을 결속해야 한다. 실행0, 실제 승인/인수 아님.

<a id="file-08"></a>
## scripts/tests/test_bash_tool_routing.py

1~269 전문. 고정 5개 도구 rule과 grep/rg/find/ls/cat/head/sed/echo 문자열, 첫 match 우선, heredoc/commit -m/echo 인용문 제거를 검사한다. shell을 실행하지 않는 순수 문자열 검사다. echo >>를 regex 역추적으로 Write에 매칭하는 현재 동작을 의도적으로 승인하며, 214~228은 None이어도 통과하는 제한적 오라클이다. heredoc 본문과 큰따옴표는 언제나 비실행 문자열이 아니므로 command substitution·unquoted heredoc 확장·nested quoting·PowerShell/CMD 의미는 미검사다. main은 test_ 전역 이름을 수집해 예외를 실패로 세지만 callable 검사는 없다. routing feedback을 권한 차단으로 승격하면 안 된다. Zeus의 도구 선택 조언으로만 변형하고 shell별 실제 구문과 executor 정책/권한 판정을 분리해야 한다. 실행0, 실제 tool API/환경/인수 pending.

<a id="file-09"></a>
## scripts/tests/test_boilerplate.py

1~252 전문. 12개 검사는 filename/content 이중 휴리스틱 및 worst-case 집계, malformed/무증거 SKIPPED, 읽기 실패를 검사한다. 정상 코드로 쓰인 fixture도 실행하거나 의미를 검사하지 않는다. LICENSE와 긴 실제 코드가 섞여도 BOILERPLATE라는 결과를 기대하여 산출물의 요구 충족 여부와 다르다. 짧은 __init__ 및 lockfile을 낮게 평가하지만 해당 파일이 실제 요구사항일 가능성은 미검사다. 없는 정상 파일은 errors를 남겨도 per_file 분모에서 빠져 SKIPPED가 된다. 절대 nonexistent 경로는 Windows에서 동일한 경로 의미가 아니며 상대경로 cwd, symlink/허용root, 권한·인코딩·대형 파일 경계는 미검사다. Zeus SDD에서는 휴리스틱 경고를 요구별 증거 존재/해시/실행/사람 인수의 오라클로 삼지 않아야 한다. 실행0, 직접 validator 호출 밖 전체 gate 정책은 pending.
<a id="file-10"></a>
## scripts/tests/test_brain_autopush.py

1~142 전문. 5개 검사는 temp bare remote와 work clone을 만들고 실제 Git init/commit/push/fetch로 brain-only snapshot, 호출자 HEAD/branch/clean tree 보존, 동일내용 no-change, 두 번째 commit 및 서로 다른 ID의 union을 기대한다. 실행한다면 원격 네트워크가 아닌 로컬 Git 통합 시험이나 이번에는 실행0이다. orphan이라는 설명과 달리 부모 commit 부재는 직접 assert하지 않으며 root tree만 검사한다. cross-machine 검사는 순차 clone/push이고 a의 보존·중복·동일 ID의 내용충돌·retraction·동시 push 경쟁을 모두 검사하지 않는다. helper에는 timeout/명시 UTF8/환경·hooks·globalconfig 격리가 없어 설치 Git 정책에 종속된다. dirty index/untracked 파일 보존, 실패 후 worktree cleanup, symlink/credential 포함 데이터는 미검사다. Zeus PG 정본의 게시 파생물로만 고려하고 no-code 범위 필터와 사용자 승인·민감자료 제외를 별도 검증해야 한다. 실제 원격 내구성/인수/채택 미완료.

<a id="file-11"></a>
## scripts/tests/test_brain_git_status.py

1~140 전문. 6개 검사는 temp Git 저장소에서 fallback clean/dirty, snapshot remote-tracking ref와 live 내용 비교, autopush 후 위험 flag 해제를 기대한다. 원격 ref를 명시 fetch한 fixture여서 offline/stale ref의 실제 서버 내구성을 입증하지 않는다. 비저장소에서 at_risk=False를 성공으로 기대해 관측불가와 안전을 합친다. fallback의 unpushed commit/behind/divergence/없어진 upstream, ignored 파일, 삭제·symlink·부분 read 오류는 미검사다. autopush 반환을 확인하지 않는 helper가 있고 Git env/hook/signing/timeout/encoding 격리도 없다. 사용자 HEAD 불변은 이 파일에서 검사하지 않는다. Zeus는 보존 receipt와 unknown을 별도 상태로 두고 PG에서 파생 snapshot의 실제 원격 확인 시각/revision을 결속해야 한다. 원본 실행0, 서버/OS/전체 closure 미검증.

<a id="file-12"></a>
## scripts/tests/test_brain_store.py

1~268 전문. 10개 t_ 시나리오를 main이 호출하고 _check가 전역 pass/fail 카운터를 올려 최종 rc로 실패를 반영한다. pytest 기본 test_ 수집에서는 이 시나리오들이 수집되지 않는다. _fresh_home은 mkdtemp 후 삭제·환경 복원하지 않고 _import_brain_store는 모든 lib 모듈을 sys.modules에서 지워 같은 프로세스의 다른 참조를 불일치시킬 수 있다. save/restore union-by-id, live-present index no-op, retraction sidecar 전파, schema mismatch 예외, torn-line skip, graduation max streak와 재검사 timestamp reset을 검사한다. retraction sidecar 존재는 실제 consumer의 부활 방지를 검사한 것이 아니라고 본문도 명시한다. 반환값 대부분 미검사이며 상태 helper가 손상 행을 버려 oracle도 같은 누락을 허용한다. 동일 ID의 상충 내용·복수 파일 atomicity·중간 실패·동시 writer·모든 L2/부록, operator 호출 권한 및 실제 graduation 재검사는 미검사다. 과거 clean 횟수 max를 가져온 것은 새 환경의 승인 근거가 될 수 없다. Zeus는 PG provenance와 철회 tombstone, transaction 및 새로운 검증 receipt로 변형해야 한다. 실행0, 라이선스/실제 모델/8단계 인수 미완료.

<a id="file-13"></a>
## scripts/tests/test_breaker_config.py

1~325 전문. 16개 검사는 기본 상수, 소형 YAML override parser, 잘못된 key/value 무시, safe/strong 문자열 방향 구분, no-op, 임계 변경 후 CompositeBreaker trip, CLI rc를 검사한다. CONFIG_PATH를 복원하지 않는다. 토큰은 공개 상수 문자열을 넣는 것으로 실제 사용자 권한·승인·만료·replay 검증이 아니다. window는 양 방향 safe로 통과하고 상수/임계 간 일관성, bool/0/큰 값, 원자적 갱신·동시 writer·수동 파일 편집 우회는 미검사다. 270~282는 SystemExit가 발생하지 않아도 실패하지 않아 unknown-key 오라클이 불완전하다. bogus YAML을 default로 바꾸는 관측은 설정 손상을 정상 설정과 합친다. 3/5회 실패는 합성 record_failure 호출이며 운영 실패 분류 정확성과 model 자격을 증명하지 않는다. Zeus는 PG의 승인된 정책 revision·명시 unknown·실제 호출 실패 receipt와 연결하고 static 문자열을 권한으로 채택하지 않아야 한다. 실행0, 직접 CLI 프로세스/OS/인수 pending.

<a id="file-14"></a>
## scripts/tests/test_breaker_proposer.py

1~331 전문. 14개 수동 검사는 합성 breaker JSON의 filename 구분, 짧은 이력 제외, 잦은 trip에서 임계 상향, reopen에서 backoff 상향, advisory 및 project 필터, CLI 형식과 apply-command 문자열을 검사한다. malformed 분석이라는 상단 coverage에 대응하는 실제 malformed fixture는 없다. 215~249의 CLI는 STATE_DIR을 patch하지 않으며 temp project-root만 전달해 실제 기본 상태 경로 의존을 남긴다. 첫 CLI test는 'breaker 1' 이름과 달리 rc0만, 다음은 key 존재만 검사한다. 증거 오염·동일 attempt 중복·경과시간·현재 override와 제안 기준의 일치·파일 타입 오류/NaN은 미검사다. 실제 오탐 정답 없이 자주 trip했다는 이유로 방어를 완화하는 것은 자가개선 승인이 아니다. 출력되는 토큰 문자열은 권한도 아니다. Zeus에서는 PG 관측표본/정책 revision/독립 반례 검토를 요구하고 제안·승인·적용을 분리해야 한다. 원본 실행0, live state 접근0, 직접 reader/CLI 지정구간 밖 closure pending.

<a id="file-15"></a>
## scripts/tests/test_budget_and_depth.py

1~244 전문. 15개 수동 검사는 ORCH_DEPTH의 default/invalid/negative 및 경계, prompt 문자수·호출수 JSON 누적/reset, sid sanitize containment, hook subprocess의 silent/deny/malformed fail-soft를 검사한다. 환경값을 원래대로 복원하지 않고 pop하므로 같은 프로세스 테스트 환경을 바꾼다. 문자수는 실제 token/cost/출력 사용량과 다르며 equal cap·동시누적·손상·쓰기 실패·symlink·정규화 ID collision/Windows reserved name은 미검사다. traversal test가 base.parent의 다른 temp 이름까지 검사해 관계없는 escape 이름에 영향받을 수 있다. subprocess는 UTF8/15초가 있으나 parent env를 그대로 복사하고 cwd/실제 hook 등록 및 손자 depth 전달은 검사하지 않는다. malformed JSON에서 silent rc0은 fail-open 계약이다. Zeus는 executor가 부여한 depth와 PG budget reservation/settlement, 정책 deny receipt로 변형해야 하며 사용자 env가 권한을 결정하면 안 된다. 실행0, 실제 recursive agent/모델/OS 미검증.

<a id="file-16"></a>
## scripts/tests/test_calendar_gate_e2e.py

1~430 전문. 18개 수동 검사는 합성 residual_norm ledger를 만들어 날짜별 scan, Stop payload builder, defect 합/필터, verdict/ts 갱신, legacy fallback completeness 및 timeout 상수를 확인한다. 직접 dict/file/helper 연결이며 실제 D2 writer·Stop event·subagent/validator/unit 실행은 없다. validators_passed/units_passed=True를 직접 전달한 completeness는 실행 receipt나 사람 인수가 아니다. PARADOX_GUARD_FAIL도 defects가 있으면 iterate로 바꾸는 우선순위를 기대한다. clean/defective 날짜 경계와 post-dispatch에도 defect block을 유지하는 방어는 보존할 수 있다. today를 달리 넣는 검사는 내부에서 시계를 전혀 호출하지 않는다는 명제를 증명하지 않으며 300초 provider cap은 다른 SUT를 읽지 않고 테스트에 하드코딩한다. 270초 상수 차이만으로 실제 취소/worker 종료·결과 회수 buffer를 검증할 수 없다. fixture read/write encoding 일부 미지정, gate filename과 payload 불일치/손상·없는 ledger·음수/bool defect·동시 갱신·권한은 미검사다. Zeus SDD에는 PG 요구/defect/실행 provenance와 명시 미검사 상태, 별도 사람 인수로 적응해야 한다. 실행0, 전체 E2E/OS/모델/채택 미완료.

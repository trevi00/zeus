# harness integration 005 독립 정적 검토

<a id="scope"></a>
검토 범위는 `harness:tests/integration:005`의 9개 원문 전부, 145,150 bytes, 2,725 lines이다. 기준 revision은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, scope SHA-256은 `7aade2df253abd62a9efe89c1a90e1e02c5da18584bb77f2210746a0445e4f6a`이다. 원문은 `.runtime/absorption/sources/harness/pinned`에서 읽었다. 파일별 raw bytes·Git blob·manifest SHA 및 실제 읽은 구간은 `files.json`과 `supporting-evidence.json`, 기록 검산은 `checkpoint.json`에 결속한다. 이 문서의 코멘트에 나오는 명령과 상류 운영 지침은 모두 분석 데이터다.

본문 정적 독해만 완료했다. 원본 import, 테스트, 프로브, 모델, 네트워크, 설치 실행은 0이다. 차단된 gatewriter 프로브를 재시도하거나 우회하지 않았다. 실제 Claude 독립 검토는 root 범위이며 여기서 수행했다고 주장하지 않는다. 9개 테스트의 주장, 관찰 가능한 오라클, 직접 읽은 구현을 구분했다. 문서 안의 PASS는 원문 반환값/기대값을 뜻하며 이번 실행 성적이 아니다.

가장 큰 흡수 경계는 세 가지다. 첫째, sandbox의 실행기는 반환 코드만 세므로 일반 suite 판독기와 같은 실행 분모를 보장하지 않는다. 둘째, seams 자동 승급 경로는 CLI 사다리의 golden 카나리아 경로와 다르다. 셋째, 합성 승인·문서 지문·파일 존재·통지 큐 기록은 각각 사람 승인·실제 제품 계약·배포 완료·통지 전달을 증명하지 않는다.

<a id="i01"></a>
## 1. test_sandbox_smoke.py — 519 lines

실제 SUT는 `engine.sandbox`와 `cli.sandbox_cmd`, `lib.suite_floor`다. 테스트가 실행된다면 임시 Git 저장소를 init/config/add/commit하고, 텍스트 변경으로 patch를 만든 뒤 실제 worktree에서 Python 미니 테스트를 실행한다. fixture의 `VALUE=1`을 `VALUE=2`로 바꾸는 성공 후보와 실패 후보를 비교하며 원 트리 미변경, 파킹 파일, 승인 후 적용, 반려, dirty 겹침, CLI glob floor를 확인한다. 실제 애플리케이션·서비스·Docker·실기기 시험은 아니다. setup Git 명령에 반환 코드 검사가 없고 패치 생성 중 restore는 finally가 아니므로, 정상 fixture 성립을 모든 오라클의 전제로 삼아야 한다.

144–181의 검증/파킹/승격 분리가 유용하다. 그러나 160–163에서 테스트가 `session_id="human"` 승인 이벤트를 직접 append한다. 173–176의 `bake_s > 0`은 메타데이터 검사이며 시간 경과·관찰·배포 승인 검사가 아니다. 실제 `promote` 497–533은 최신 pending 승인 상태, patch 존재, 대상 경로 dirty, Git apply 결과를 보고 즉시 적용 후 bake 메타데이터를 적는다. 승인 payload의 사람 신원/서명이나 검증 당시 patch 해시의 동일성 검사는 이 함수에 없다. CLI approve도 193–228에서 드라이버 스탬프를 거부한 뒤 승인 기록과 promote를 연속 호출한다. 자동 판정기 전체의 자격과 동등하다고 세면 안 된다.

반려 검사는 discard 후 promote를 호출하므로 승인 상태 거부와 파킹 부재 거부를 한 오라클에서 완전히 분리하지 않는다. PRESERVED_EVENTS membership 검사는 해당 이벤트의 실제 compaction 재생 시험이 아니다. pending의 stale/missing 구분은 실제 임시 Git apply-check/CLI 표면을 사용하지만 health 연결은 소스 문자열 검사다.

현행 방어를 보존해야 한다. 310–368은 좁힌 glob가 실패 테스트를 빼는 현상을 미니 fixture로 드러내고 CLI floor가 정규 집합 포함/공집합 거부를 수행하는지 확인한다. 369–506은 관련 없는 dirty를 허용하고 겹치는 dirty만 거부하는 현행 수정의 양방향 대조다. `-uno` 때문에 untracked는 분모 밖이라고 원문도 명시한다. 이를 과거의 전 트리 dirty 차단 결함으로 쓰면 잘못이다.

다만 `run_suites` 172–250은 개별 프로세스 rc만 보며 stdout의 skip/실제 assertion 수를 읽지 않는다. 따라서 아래 token-notify가 fixture 부재에서 skip_axis 후 rc=0을 반환하는 조건에서는 실패 목록에 들어가지 않는다. CLI glob floor는 파일 집합 포함만 보므로 이 내부 미실행 분모를 고치지 않는다. `apply_via_sandbox` 325–394는 이 실패 목록이 비면 verified 파킹을 만든다. 다른 게이트까지 포함한 최종 자동승격 가능성은 별도 closure이며, 여기서 실제 승격/결함 재현을 했다는 뜻은 아니다. 현재 재확인 실패 교집합이 비면 deferred/verified=False인 방어도 존재한다.

<a id="i02"></a>
## 2. test_scaffold_smoke.py — 216 lines

24개 템플릿 수, frontmatter 시작과 gate 힌트 문자열, `scaffold issue` 파일 발급·프로젝트 치환·덮어쓰기 거부, intent floor, 합성 Python 파일의 구조 추출, seed·분류·재추출 일치를 검사한다. 템플릿 원문을 이 리뷰가 전부 지원 본문으로 읽었다고 중복 계상하지 않는다. 원문 테스트가 읽는 대상과 리뷰어가 직접 읽은 대상은 다르다.

110–115는 특화 파일을 실제로 생성하지 않고 공통 fallback만 확인한다. 구현 `inventory` 35–44에는 동일 이름을 stack 디렉터리에서 덮는 동작이 있지만 이 테스트가 특화 우선 회귀를 실행 검증하는 것은 아니다. `doc_classifier` 단언은 리스트 타입만 확인하므로 빈 리스트도 통과하며 README의 올바른 유형·비어 있지 않은 후보를 보장하지 않는다.

intent floor의 정상 fixture는 authored 라벨과 REQ 앵커·존재하는 evidence 파일이다. 실제 validator 46–73은 `origin: extracted`만 거부하며 authored 라벨/서명/사람 정체를 강제하지 않는다. evidence는 첫 콜론 앞의 경로 존재만 확인하므로 범위·라인·관련성 검증은 아니다. Windows drive-colon 및 프로젝트 밖 evidence 처리도 별도 검증이 필요하다. placeholder 정규식은 한글 포함 꺾쇠 패턴이라 모든 영어 잔재 검사는 아니다. 이 제한은 이번 정적 독해이며 오류 재현/수정이 아니다.

Python API/모델 fixture는 실행되지 않는 소스 텍스트다. conceptual은 클래스·FK·Enum, flows는 decorated route와 관찰 호출, convention은 파일/이름 통계를 문서로 만든다. confidence 0.9/0.6/0.7과 span 수는 생성기가 적는 값이지 실환경 정확도 측정치가 아니다. reverse `verify` 195–210은 같은 추출기의 재실행 결과와 디스크 문서 일치만 검사하고 대상 소스가 없는 결과는 건너뛴다. 원문은 등록 추출기의 필수 부분집합과 callable을 검사하여 과거의 정확한 7개 수 고정 문제를 피하고 있다. 아직 스펙 의미·실제 사용자 여정·인수 오라클의 독립 검증은 없다.

<a id="i03"></a>
## 3. test_seams_ladder_smoke.py — 199 lines

fabricated `gate_check.evidence`의 OK/DRIFT/미판정 이력으로 streak와 query 필터를 시험한다. 미판정은 중간이면 streak를 동결하고 후행이면 승급을 막는다. scope 제외 사유·50% 상한·낡은 제외 표기, 문서 상태 다양성, manual 스위치, DRIFT 후 자동 강등이 검사 축이다. 이벤트의 실행 신원·실제 스펙 변경·서명된 측정 receipt는 fixture에 없다.

104–123은 실제 `probe_seams_blocking.py`를 자식으로 실행하도록 작성되어 있다. 지원 원문 1–65를 읽어 같은 합성 producer/consumer에 실제 `_contract_parity`를 호출하고 advisory PASS와 blocking FAIL을 양방향 비교함을 확인했다. 이번에는 실행 0이다. primary의 held-out 등록 단언 자체는 케이스 이름 문자열만 보지만, 정본 cases.yaml 45–51에는 실제 `held_out: true`와 command·expect_exit·expect_contains가 있다. 등록 부재라고 쓰면 안 된다.

CLI `ladder_cmd` 53–84는 readiness와 `passed, gr = golden.gate()`를 모두 판정하고 실패/예외를 거부한다. 별도 PR4 tuple 진리값 문제를 이 분기에 옮겨 주장하면 안 된다. 반면 `graph_queries` 678–681의 자동 실효 blocking은 `seams.auto_promotion`만 소비하며 이 CLI golden 카나리아를 호출하지 않는다. 원문 primary의 소스 문자열 배선 확인으로 자동 경로까지 golden gate가 결속됐다고 할 수 없다. 자동승급의 운영 권한과 카나리아 증거 정책은 Zeus에서 별도 설계해야 한다.

자동승급의 서로 다른 문서 상태는 해시 dict의 유일값 수이며 독립 실행 횟수/사람 승인 증거가 아니다. 읽을 수 없는 프로젝트 원장은 빈 이력이 되어 자동승급이 꺼진다. 이것은 선언 blocking까지 해제하지는 않지만, 자동으로만 강화된 검사는 advisory로 돌아갈 수 있다. DRIFT 후 streak reset도 의도된 자동 강등이므로 이를 무조건 지속 blocking 보장으로 인수하면 안 된다.

<a id="i04"></a>
## 4. test_seams_smoke.py — 115 lines

합성 API JSON 블록에서 얻은 필드와 논리 설계 Markdown 표 컬럼의 집합 정합을 검사한다. snake_case 변환, 불일치, transform 미선언, 낮은 fidelity, 비단사 mapping을 구분하고 임시 문서에 실제 catalog query를 실행하도록 작성되어 있다. 소스 부재는 현행 `graph_queries` 669–670에서 ERROR다. 과거의 공허 PASS 주장과 혼동하지 않는다.

동일 필드 집합이라는 결과는 요청/응답의 역할, 필드 타입/필수 여부/금액 단위, 실제 HTTP·DB·사용자 동작의 동일성을 뜻하지 않는다. `blocking:false` 카탈로그라도 관측 이력에 따라 자동 강화될 수 있으며, LOW_FIDELITY/NEEDS_TRANSFORM은 원문 소비자가 PASS+advisory로 표현한다. 파이프라인의 PASS만 읽는 인수 완료선에는 적합하지 않다. 이 테스트의 E2E 표기는 로컬 문서-질의 연결을 뜻한다.

<a id="i05"></a>
## 5. test_small_batch_smoke.py — 780 lines

주요 SUT는 skill_router, red_flags_scan, write_boundary, external_text, git_flow, reenforce, scaffold/testgen, agent card renderer다. fixture는 임시 project/state/ledger, synthetic PreToolUse/Stop payload와 policy 읽기, 짧은 자식 스크립트다. 주석 속 과거 코퍼스 횟수는 원문 역사 주장으로만 읽었다. 그 숫자를 현재 재측정 결과로 상속하지 않았다.

상당한 분모가 셸 휴리스틱의 양방향 사례다. 데이터 인용과 명령, copy source와 destination, segment 경계, 미닫힘 quote, interpreter argument, heredoc, collaboration/unattended 리그를 대조한다. 도구 payload로 문자열을 넘겨 handler의 allow/ask/deny를 검사하며 그 문자열의 실제 PowerShell/Bash 실행 결과를 재현하는 것은 아니다. `PowerShell` 도구 자체 분기는 구현 1015에 있지만 이 테스트의 helper는 Bash tool_name을 사용한다. 단어 목록/정규식 사례가 OS 실행 sandbox나 전역 권한 허용과 동등하지 않다.

현행 small-batch는 두 STATE_DIR 임시 교체 후 기존 값을 복원하고, 토큰 프록시 cap도 복원한다. 이전 env pop 누출 결함을 현재형으로 쓰면 안 된다. source HOME 정책·전체 skill 파일·AGENTS 드리프트를 읽는 검사는 여전히 live source 상태 의존이며 `_isolate`가 STATE만 고정하는 것과 구분한다. red_flags_scan 25–44는 skills 디렉터리 부재를 실패시키지만 존재하는 빈 디렉터리/README만 있는 경우 실제 검사 파일 수의 바닥은 없다. primary의 actual HOME와 bad 한 개 fixture가 빈 디렉터리 조건까지 검증하지 않는다.

push 게이트 623–682는 real lint 대신 PUSH_GATES를 red/green/missing/slow 스크립트로 교체하고 finally 복원하여 차단 기구를 잰다. 실제 push/network·원격 GitHub CI·배포를 시험하지 않는다. 구현은 미선언이면 게이트가 없고, 선언된 알 수 없는 이름/실행 실패/timeout이면 deny이며 rc=0이면 통과한다. GitHub 실패 원인의 실측 자료로 사용할 수 없다.

token cap은 transcript 100 bytes에 10/8,000,000 bytes cap을 주고 reenforce의 non-block/block을 본다. 실제 토큰 사용량·가격·모델 자격·전체 goal budget은 아니다. skill_usage의 NO_HIT 기록도 소비 효과/학습 승격 증거가 아니고 `_record_usage` 377–397은 오류를 통째로 삼킨다. 외부 텍스트는 marker substring과 배너를 붙이는 단계이며 악성 지시를 실행하지 않는 런타임 권한 분리는 이 검사 밖이다.

testgen 738–752는 GWT 두 건으로 `xfail` 스켈레톤 두 개와 바이트 멱등을 확인한다. 실제 생성기 31–39는 `strict=False` xfail와 NotImplementedError이고 68–69에서 G/W/T를 각각 120자로 자른다. 따라서 생성 수와 pytest exit만으로 인수 통과를 주장하면 안 된다. 원문 planner 카드의 `model_tier:fable` 문자열은 Claude 역할 선언이고 Astra→Sol→Terra 자격 이전의 실측 자료가 아니다.

<a id="i06"></a>
## 6. test_spiral_smoke.py — 169 lines

두 단계 synthetic pipeline과 파일 존재 gate, 직접 append한 dispatch/stage_started, 실제 gate_runner/tick/cycle와 ledger compaction이 시험대상이다. risk high 우선은 같은 depth에서만 적용하며 waterfall 기본 순서는 유지한다. 재개방 zeta의 파일 내용은 v1 그대로 존재하여 두 번째 PASS가 가능하다. 이것은 새 구현/새 사용자 인수 수행의 증거가 아니다.

REDO가 없으면 converged, 유령 REDO/비spiral은 거부한다. 현재 cycle 실행기는 circuit open에서 새 cycle_started를 쓰지 않는 방어가 있다. 다만 cycle_plan/cycle_finished는 circuit 판단보다 먼저 append(52–78)하고, 이 테스트는 circuit open·계획 부재·pipeline_started 부재·중복 REDO·실제 미완료 상태에서의 cycle 요청 축을 다루지 않는다. `is_done`은 PASS뿐 아니라 SKIPPED와 선택되지 않은 optional을 완료 분모에서 제외한다. 따라서 도출된 done/converged를 8단계 SDD의 사람 QA·라이브 배포 완료와 동일시하지 않는다. compaction 후 stage/cycle 검사는 유용한 이벤트 fold 자산이지만 PG 트랜잭션·동시성 동등성은 별도다.

<a id="i07"></a>
## 7. test_stuck_smoke.py — 191 lines

순수 목록 fixture로 동일 FAIL 4회, ERROR 3회, barren spawn 3회, 두 stage 왕복 6회, fresh driver_error 3회와 반례를 시험한다. 실제 stuck 함수는 실패 문장을 정렬 집합이 아닌 tuple로 fingerprint하며, `stage_started`뿐 아니라 gate_check·dispatch 등도 진행으로 인정한다. 반복 재시작이 실제 가치 있는 진전인지는 별도 판정이다. primary의 실패 문장 한 개 fixture는 순서가 다른 같은 집합을 시험하지 않는다.

re_anchor는 임시 HOME에 goal/완료선/원장을 만들고 Python 자식 compose를 호출하도록 되어 있다. 50%는 evidence 두 파일 중 하나의 존재율이며, 테스트가 직접 쓴 unsigned spiral_approved를 승인 어휘로 표시한다. 두 번째 결정론 검사는 stdout 동일성만 보며 r2 성공 rc는 따로 확인하지 않는다. 테스트의 무인자 compose와 실제 드라이버의 `compose(binding)`은 구분해야 한다.

지원 원문에서 실제 연결은 driver→circuit.gate→stuck.assess이고, 드라이버는 open 통지와 halt marker를 쓰며 현재 바인딩을 re_anchor/완료선에 전달한다. primary 160–177은 문자열 검사라 실행 배선·알림 전달까지 증명하지 않는다. re_anchor 현재 autonomous 승인은 제외하지만 긍정적인 사람 승인 증명 검증은 이 함수에 없다. 이 범위에서는 arming 전체 키/정책 closure까지 다시 독해하지 않았으므로 자동 장전이 같은 unsigned 승인을 허용한다고 확장하지 않는다.

<a id="i08"></a>
## 8. test_token_notify_smoke.py — 250 lines

누락/만료/JSON 손상/비수치 만료의 mutation token과 notification dedup를 임시 guardian/home/state 위에서 시험한다. 유효 토큰은 임의 `token:"t"`와 미래 expires_ts이며 stub_claude.py가 marker 파일 하나 쓰는 것으로 spawn을 확인한다. 실제 Claude 동작·모델 자격·실제 guardian 서명 발급·사용자 전달을 확인하는 시험이 아니다. `_cycle_spawn`만 호출하여 curator/autoheart 전체 cycle은 의도적으로 제외한다.

실제 driver token gate 1805–1826은 expires_ts float 비교이며 이 구간은 token 값의 인증을 검사하지 않는다. 파싱 실패와 ValueError를 잡지만 null/구조형/비유한 값의 계약은 여기서 따로 검증하지 않았다. fixture는 이 경계의 세부 전부를 커버하지 않는다. `_notify_halt`는 code+detail 앞 200자의 마지막 key로 dedup하고 큐에는 앞 300자를 적는다. 원문은 큐 전후 차분과 사유 전환을 검사하지만 relay ack, restart, 큐 truncation/rotation, 재전송 내구성은 보장하지 않는다.

107–112의 추적 fixture 자산 부재는 `skip_axis` 후 rc=0 조기 반환으로 전체 본문 검사를 하지 않는다. 일반 suite 판독기가 이를 SKIP으로 분리하는 것과 sandbox의 rc-only 처리는 다르다. fresh_state와 saved env 복원은 현행 긍정적 방어다. 비동기 stub는 marker 대기와 0.5초 sleep으로 cleanup을 보조하지만 자식 exit/wait/process-tree 종료의 완전한 보장은 아니다. Windows detached flag와 Linux 기본 process 분기는 실제 드라이버에 있으나 OS 행렬 실행은 0이다.

5–12에 원문 스스로 과거 367건/현재 재측정 50줄을 구분하는 정정이 있다. 여기서는 어느 수도 현재 Zeus 상태로 인용하지 않는다. REISSUE 문자열은 직접 읽은 unattended.md 8 및 driver 상수와 일치하지만 경로별 설치·상주 서비스 등록·토큰 갱신 성공을 뜻하지 않는다.

<a id="i09"></a>
## 9. test_unattended_fence_smoke.py — 286 lines

임시 home/project/other/state와 copied policy로 synthetic Write/Bash payload의 같은 경로 판정을 비교한다. shell은 하네스 홈 안 쓰기만, file tool은 project 밖 쓰기까지 막는 선언된 비대칭을 양방향 검사한다. /tmp/남의 프로젝트/하네스 읽기-source 허용은 test가 의도한 계약이며 OS 격리 보장으로 흡수하면 안 된다. 실제 셸 파일 동작은 수행하지 않고 `handle(Ctx)` 반환값을 본다.

현재 human-channel hook는 쓰기 의도 검사 전에 승인/반려/resolve를 검사하고, CLI 자체도 드라이버 스탬프를 거부한다. 예전 approve 무방비 주석을 현행 상태로 쓰면 안 된다. 그러나 협업/스탬프 부재는 긍정적인 사람 신원 증명이 아니다. 환경 변수가 없는 프로세스의 판단과 authenticated human acceptance는 별도다.

219–255의 CLI 이중 방어 검사는 중요한 격리 잔여가 있다. 자식 env의 HARNESS_HOME을 실제 원문 HOME으로 되돌리고 HARNESS_STATE_DIR를 제거하며 cwd도 HOME/scripts다. 현재 spiral/sandbox CLI는 미지 candidate/pending을 먼저 거부하므로 지정된 nonexistent fixture가 곧 활선 승인 쓰기를 만들었다고 주장하지 않는다. 하지만 unstamped 경로는 실제 HOME 원장을 읽을 수 있고, subprocess timeout이 없으며, 테스트 끝의 env 복원이 finally가 아니어서 예외 시 복원이 보장되지 않는다. INV-T의 전체 live read/write 비접촉을 이 시험만으로 승인할 수 없다. 이번 검토는 해당 CLI를 실행하지 않았다.

<a id="trace"></a>
## 직접 지원 경로와 기록 규칙

`supporting-evidence.json`은 실제 표시하여 읽은 정확한 행 범위와 raw SHA-256을 보존한다. 파일 전체가 아닌 지원 구간은 primary 전수 분모에 넣지 않는다. 원문 테스트의 문자열 검색/파일 읽기 자체도 그 대상의 실행 검증이 아니며, 리뷰어가 호출 이름만 찾은 rg 결과를 본문 독해로 승격하지 않았다.

공통 runner/격리/원장/path/derive 지원은 integration001의 동일 바이트 구간을 재사용했다. 각 행에 이전 ledger 전체 hash·source row·revision·range·review anchor를 결속하고 이번 raw hash 동일성을 검사한다. 이 재사용은 전체 파일이나 전체 전이 closure를 다시 읽었다는 주장이 아니다. `tests/_isolate.py`는 STATE_DIR 경계, suite_cmd/test_outcome은 실행/분모 분류, ledger/path는 HOME과 STATE의 구분을 확인하는 근거다. 추가 지원은 sandbox·CLI, seams·graph query·golden fixture/case, scaffold/floor/추출기, testgen, cycle/select-ready, stuck/circuit/re_anchor/driver, write_boundary/git_flow, reenforce/router 및 직접 참조한 정책·카드의 한정 구간이다.

원문 selftest의 check 호출은 loop/분기/조기 반환으로 동적이다. 전문 행 수나 정적 check 토큰 수를 실행 assertion 분모로 발표하지 않는다. unhandled exception/timeout은 정상 FAILS 누적과 다르게 스크립트를 중단할 수 있다. 모든 primary의 __main__과 출력/종료를 읽었으나 이번 실행 횟수와 실제 assertion 수는 0/미측정이다.

<a id="zeus"></a>
## Zeus 8단계 SDD 및 런타임 권위와의 연결

기존 Zeus 지원 구간은 integration001의 AGENTS, domain/application SDD, model_routing과 동일 raw bytes임을 다시 확인하여 재사용한다. 그 제한된 구간에서 정의/런타임 PG 권위, 단계 enum 및 승인 증거/모델 역할을 대조했다. 전체 현재 Zeus 구현과의 동등성은 검증하지 않았다.

| 사용자 단계 | 이번 자산이 제공하는 것 | 흡수 전에 필요한 경계 |
|---|---|---|
| 1 스펙 논의 | scaffold, origin/anchor 바닥, 인용 seed | 사람이 가진 핵심 시나리오와 승인한 스펙 버전; origin 라벨만으로 승인하지 않기 |
| 2 디자인 분석 | 구조 역추출, 필드/컬럼 parity, gap/advisory | 인터랙션·금액/권한/실패 시나리오의 의미와 독립 검수; 자동 blocking과 카나리아 결속 |
| 3 코드 작성 | 위험 순서·GWT skeleton·역추출 drift | xfail 잔여와 실제 구현 분리, Astra 설계→자격 Sol→자격 Terra 수행 조건 |
| 4 자체 검증 | 임시 Git/worktree, 오라클 반례, 동일 바이트 재생 | rc+수행/skip 분모+환경 receipt; mock/fixture 결과를 실제 인수와 분리 |
| 5 알파 배포 | 검증된 후보 파킹/승인 후 적용이라는 분리 | 적용을 배포로 세지 않기; 실제 알파 배포/환경/롤백 증거 |
| 6 QA 및 증적 | 사건/문서 지문·명시 미검증·사람 채널 가드 | 양성 사람 승인 증거, 버전/테스트 run 결속, 금전 핵심 흐름 실제 검증 |
| 7 라이브 배포 | 부분 청결 검사·승격 메타데이터 | prod 점진 배포·bake 실측·관찰/복구; 이벤트명/타이머 값은 완료가 아님 |
| 8 CS 대응 | stuck/circuit/통지 큐/re_anchor | 실제 수신 ack와 장애/누락 알림, 큐 유실 복구, ticket와 PG runtime 상태 연결 |

JSONL append/원장 fold를 그대로 PG SSOT라고 부를 수 없다. PG의 원자적 상태 전이, receipt/승인/실행 identity, 재시도·중복·concurrency를 연결한 뒤 검증해야 한다. 삼성 휴대폰/태블릿 실기기 단계는 사용자 요청대로 추후 범위다. Device Farm SDK/MCP/live/replay/log-to-scenario가 이 9개 자산에 구현돼 있다고 주장하지 않는다. Claude fable 문자열과 byte cap은 Astra/Sol/Terra 작업 자격의 대체가 아니다.

<a id="unknowns"></a>
## 남은 검증과 한정 완료선

9개 primary 본문 읽기와 지정 지원 구간 정적 추적만 완료했다. 상류 실행 결과, 전체 전이 closure, OS/WSL 및 process/service 행렬, 라이선스·재배포, 실제 사람 인수와 모델 자격, actual Claude 교차검토, 채택/구현은 미완료다. 모든 원본과 source/runtime/shared coverage는 수정하지 않았다. 이 폴더 기록기와 문서만 작성했으며 commit/push는 하지 않았다.

구체적으로 전체 autoheart gate/guardian 인증·릴레이, 나머지 추출 helper/parser 품질, testgen 생성물 실행/충돌과 escaping, 셸 parser 모든 변형, 커맨드 launcher 등록, 전체 template/skill 내용, 실제 deployment trigger 및 PG 소비자가 남아 있다. 발견은 root의 이슈/설계 논의 재료이며 실제 결함 재현이나 채택 승인으로 취급하지 않는다.

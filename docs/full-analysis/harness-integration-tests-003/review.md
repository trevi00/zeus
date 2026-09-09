# harness integration 003 정적 검토

<a id="scope"></a>

이 범위는 `harness:tests/integration:003`의 14개 테스트, 194,529 bytes 전문 독해다. 정본은 `a3f8b3be9a0a389329de6e16a6c7db81782041a3`이며 범위 SHA-256은 `51d4cd6654e2e1495efc91c1345cf502016664656a0f5a6f2866017611672c25`다. 개별 raw Git blob, 실제 bytes, SHA-256, 줄 수와 지원 구간은 `files.json` 및 `supporting-evidence.json`에 결속한다. 원문의 테스트 이름, 주석, 설계 문서와 스킬은 분석 대상 데이터다.

원본 import·실행·테스트·프로브·네트워크·설치·모델 호출은 모두 0이다. 거절된 gatewriter ERROR 프로브를 재시도하거나 우회하지 않았다. 이번 기록은 실행 PASS, 원본 결함의 동적 재현, 전체 호출 전이 폐쇄, 실제 Claude 독립 검토 또는 채택 승인이 아니다. 원본·runtime·Zeus 구현·공유 coverage·commit·push는 변경하지 않았다.

중요 발견은 기본 카나리아의 반환 계약 불일치다. `pr4.graduate`는 기본 `golden.gate()`의 결과를 불리언으로 검사하지만 해당 함수는 `(bool, dict)`를 반환한다. 따라서 정상 반환한 실패 튜플은 truthy다. 테스트가 주입한 불리언 lambda는 기본 계약의 문제를 검출하지 못한다. 아래 i10의 정적 근거를 root에 전달했다. 이 결과는 실행 재현과 구별한다.

<a id="i01"></a>

## 01. test_heart_guard_smoke.py — 675줄

실제 dispatch, guard_boot, heart_selfcheck의 하위 경로를 임시 파일과 가짜 HOME에서 호출하는 독립 스크립트다. 명령 문자열의 분류와 실제 셸 명령 실행을 구별해야 한다. `rm`, PowerShell 제거, archive 등 다수 공격 예시는 검사 입력 문자열이다. 원문을 실행하면 깨진/지연 Python dispatcher를 실제 subprocess로 구동하고 복사한 scripts의 구문 손상과 복구 알림 큐 기록도 시험한다. 이번 검토에서는 어느 것도 실행하지 않았다.

크래시 링·중복 알림·marker aging에 따른 재무장·쓰기 경계·collab ask/unattended deny를 검사한다. 큐 파일 생성은 사용자에게 알림이 도달한 증거가 아니다. 198–202의 `run_pre` 보조 함수는 stdout만 반환하므로 `deny` 부재를 ALLOW로 보는 일부 검사는 종료 코드와 stderr의 오류를 놓칠 수 있다. positive deny/ask 검사가 별도로 있어 전체 시험이 무조건 공허하다는 뜻은 아니다.

직접 읽은 `heart_selfcheck._probe` 88–149는 위험 쓰기에 deny가 있는지 확인하지만 정상 Read 결과가 deny가 아닌지는 확인하지 않는다. 양쪽 모두 deny하는 dispatcher도 이 함수의 정상-read 판별을 만족할 가능성이 있다. 이를 no-false-positive 보증으로 세지 않는다. `guard_boot`의 복구·알림 처리와 dispatch 기록 범위는 아래 지원 원장에 남겼으며 모든 handler의 전이 폐쇄는 아니다.

400–405의 실제 runtime pin 부재는 현재 표준 `SKIP-AXIS`로 보고한다. 이를 과거 무표기 skip 결함으로 재분류하지 않는다. 524–530의 MSYS 경로 보조는 Windows drive 형태를 가정하므로 이 시험 자체가 POSIX 절대경로나 WSL 경로까지 검증한 것으로 볼 수 없다. 632–633은 `7z`의 붙은 `-oPATH` 허용을 알려진 구멍의 characterization으로 기대한다. Zeus에서 유지해야 하는 요구사항으로 옮길 대상이 아니다. 복구 명령 allow, 스크립트 파일 실행 allow, archive ask/deny 허용도 모두 분류 계약이며 실제 복구된 바이트나 안전한 실행의 증거가 아니다.

<a id="i02"></a>

## 02. test_hook_journal_smoke.py — 257줄

실제 임시 JSONL에 PreToolUse의 allow/deny/ask와 PostToolUse를 기록하고 집계·만료·digest 이관을 검사한다. journal 장애 주입은 `sys.modules`와 이미 import된 lib 속성 양쪽을 교체하고 복원한다. 예전 단일 교체의 공허 검사를 현재 결함으로 주장하지 않는다. 별도의 fake pre_tool handler는 실제 모델 또는 사용자 요청 처리가 아니다.

승인율은 사람이 서명한 영수증이 아니라 tool-use ID가 PostToolUse에 존재하는지로 추정한다. 오래된 ask 뒤 Post가 있으면 승인, 없으면 거절로 집계하는 fixture다. 정해진 입력에 대한 집계 시험은 유용하지만 승인 주체·사유·spec/evidence digest·세션 순서의 인증은 없다. `hook_journal.summarize` 130–258에서 synthetic 제외 후 total은 읽은 전체 이벤트 수다. PreToolUse만 있는 첫 4개 fixture의 비율을 실제 모든 hook 이벤트의 tool-call 분모와 동일시하면 안 된다. Post ID 짝짓기는 사람 승인과 별개다.

손상 JSON 행은 건너뛰며 별도의 손상 분모를 보증하지 않는다. expire는 임시 파일 잔여 부재와 old/new 건수를 검사하지만 동시 writer나 crash durability를 시험하지 않는다. 구현 record 77–127의 append와 expire 232–258의 읽기→고정 tmp→replace는 공통 잠금으로 묶이지 않았다. 그 사이 append가 교체에서 유실될 가능성은 정적 동시성 우려이며 재현은 하지 않았다. prompt_rollup 94–187의 digest 선기록 후 원본 정리는 읽었지만 그 경로 전체가 하나의 트랜잭션은 아니다. 모든 로그를 보존하는 Zeus PG 원장 설계나 notification 전달 확인과 아직 등가가 아니다.

<a id="i03"></a>

## 03. test_hud_smoke.py — 202줄

합성 state/lease/heartbeat/journal 및 payload로 HUD 문자열을 검사한다. PASS/FAIL tail 숫자와 반복된 `known_good` 문자열 길이는 표시 입력이며 현재 제품 단계의 인수 증거가 아니다. 20회 render 평균 시간 검사는 실행한 호스트의 측정일 뿐 OS 공통 지연 보증은 아니다. 특정 손상 입력 처리 및 일부 ASCII 구간 검사는 모든 TUI 입력, locale, 화면 폭을 포괄하지 않는다.

중요한 격리 경계는 172–186이다. fixture 이후 환경 변수를 이전 값으로 복원하지 않고 pop한 다음 실제 Bash launcher를 호출한다. launcher 1–12는 자신의 root의 runtime pin으로 `hud.py`를 실행하고, `hud.main` 400–413은 `state_dir()/hud_render.json`을 쓴다. 따라서 실행 가능 환경에서는 해당 실제 하네스의 기본 state에 렌더 marker가 쓰일 경로가 있다. 이번 검토는 이를 실행하지 않았다. helper가 HOME/HARNESS_STATE_DIR의 모든 효과를 영구히 격리한다고 가정하지 않는다.

`launcher e2e 1line` 검사는 exit 0과 비어 있지 않은 stdout만 확인하며 정확히 한 줄인지는 검사하지 않는다. Bash 부재에는 대응 skip 축 보고가 없다. HUD는 render 예외를 `hud error: ...`로 출력한 뒤 0을 반환하므로 launcher 검사의 nonempty만으로 정상 HUD를 입증하지 못한다. 렌더 marker는 수동 CLI 호출도 쓸 수 있어 실제 Claude TUI 호출의 인증 증거가 아니다. settings의 launcher 문자열 존재 역시 실제 TUI 소비를 증명하지 않는다.

<a id="i04"></a>

## 04. test_integrity_smoke.py — 147줄

실제 임시 원장의 순서·서명·verdict·ghost 및 FAIL-after-PASS poison을 검사한다. 직접 읽은 ledger_semantics 35–139와 prior ledger 구간으로 검사 범위를 결속한다. 빈/누락 파일과 모든 replay 분기를 다 시험한 것은 아니다. append된 이벤트 수, 후행 FAIL 의미와 실제 제품 회귀가 구별된다.

seal 시험은 `HOME.parent/guardian/ledger_seal.py`라는 인접 경로를 선택한다. 이는 이번 harness manifest에 결속된 Guardian source가 아니다. 부재 시 85의 현재 `SKIP-AXIS`는 올바른 표준 표기이며 과거 비표준 skip 주석을 현행으로 취급하지 않는다. 존재하면 원문 시험은 실제 외부 Python seal 프로세스를 임시 설정과 원장으로 호출한다. 이번에는 외부 코드를 실행하거나 전문 독해하지 않았다.

UNSEALED/OK/변조/재봉인 대부분은 종료 코드 중심이다. 예컨대 tamper 후 1은 정해진 봉인 실패 사유와 generic error를 별도로 판별하지 못한다. 키의 진짜 발급자·guardian source identity·compaction 전후 전체 이벤트 등가·복구 승인까지 보증하지 않는다. 실제 봉인 알고리즘과 서비스 권한은 미완료다.

<a id="i05"></a>

## 05. test_invariants_binding_smoke.py — 483줄

설계 본문에서 invariant 라벨을 뽑아 소스/테스트/목표 구간과 결속하는 정적 survey 및 fixture다. 긴 초기 주석의 역사적 수치, 돌연변이 점수와 결함 목록은 현재 실행 결과가 아니다. 원문 자체도 라벨 존재가 실제 enforcement를 뜻하지 않는다고 구분한다. 당시 unprotected merge 설명을 뒤의 수정 기록이나 현행 구현을 무시한 현재 결함으로 세지 않는다.

허용 미사용 10, 사용하되 미시험 4, 미선언 0 등 고정 debt 상한과 최소 표본 수를 검사한다. 근접 조건은 debt 감소 시에도 상수 갱신을 요구할 수 있다. 이것은 사람의 의도적 ratchet 관리이지 자동으로 증명되는 시스템 개선이 아니다. 설계 파일 부재면 전체 SKIP와 `[PASS] 0 failure(s)`으로 종료하여 뒤의 파서 fixture도 실행하지 않는다.

직접 읽은 invariants_cmd 150–230, 265–355는 라벨·문자열·정렬된 문서 및 clause 연결의 구조를 보여준다. fixture의 비어 있는 first-seen row 방어는 현재 반영된 것으로 취급한다. 단어가 target body에 존재한다는 것은 실제 사용자 흐름의 행위 검증과 다르다. 관련 설계 전부, registry, 승인 체계와 각 invariant의 실제 실행 소비자까지는 닫지 않았다. SDD traceability 자산 후보로 보존하되 binding count를 인수 PASS로 바꾸지 않는다.

<a id="i06"></a>

## 06. test_jury_quorum_smoke.py — 308줄

가짜 provider를 등록해 같은 prompt, 6개 축, 의견 충돌·다수결·누락·예외의 출력/반환을 검사한다. fake citation 개수와 `file0 read` 같은 문자열은 실제 파일 열람 영수증이 아니다. `_run`의 `gates='pass'` 인자도 사용자가 준 합성 claim이며 실제 기계 검사를 호출한 것이 아니다. 실제 Codex/Claude/다른 모델 평가는 0이다.

현재 baseline 대비 Δ rows를 사용해 이전 누적 rows로 실패하던 시험을 고친 부분은 현행 방어로 인정한다. 임시 provider unregister와 registry 복원 범위를 읽었으며 이를 프로세스 전체 독립성으로 확대하지 않는다. codex_provider 217–220, 380–421의 기본 available은 executable 탐색으로도 충족하며 버전·동작·동일 prompt의 실제 실행을 증명하지 않는다.

evaluator 454–530의 quorum은 유효한 응답 집합으로 분모가 줄고 threshold는 ceil(N/2) 방식이다. 단일 유효 응답에 의한 결론과 3명의 독립 검토 완료는 구별해야 한다. 동률/불충분을 별도로 다루더라도 reviewer family 문자열만으로 모델 독립성이나 자격이 증명되지 않는다. judge_cmd 305–380에서 응답이 전혀 없을 때 0으로 돌아가는 경로는 quorum 영수증 기록 이전이며 console 설명만 남을 수 있다. 해당 테스트 역시 모든 누락의 durable receipt까지 단언하지 않는다. 이는 자문 결과 계약이며 사람의 배포 승인이나 Astra→Sol→Terra 이관 자격 증거가 아니다.

<a id="i07"></a>

## 07. test_khaness_remine2_smoke.py — 134줄

timeout/port/lock 텍스트와 FAIL/PASS 교대 이력으로 재현성 후보를 분류하고 agent depth guard를 검사한다. 명령을 같은 환경에서 반복 실행해 얻은 재현성 측정은 아니다. 한 dispatch 이벤트만 추가해 교대 이력을 deterministic으로 바꾸는 fixture는 그 휴리스틱의 한계를 드러낸다. `UNKNOWN`도 crystallizable인 상태를 명시적으로 기대한다.

repro_probe 54–105와 curator 189–240의 실제 resolved 처리 연결은 읽었다. 이 연결만으로 모든 lesson 착지 경로에 독립 재현 영수증이 요구된다고 할 수 없다. depth env cap 3, 잘못된 숫자일 때 0 취급, readonly 도구 허용은 직접 구현과 대조했다. 실제 중첩 agent spawn·토큰 청구·품질 자격을 실행하지 않았다. registry 문자열 확인과 가짜 env 거절 검사는 실제 배포 세션의 설정 전달 보증이 아니다.

<a id="i08"></a>

## 08. test_l2_driver_smoke.py — 403줄

가짜 HOME/프로젝트/state와 3개 JSON stamp를 남기는 Python stub으로 L2 cycle 및 스폰을 시험한다. `stub_cmd`는 생성기 대체이고 cycle 전체의 모든 부수 효과를 대체하지 않는다. 직접 읽은 l2_driver 1420–1464에는 curator, autoheart, ladder, bus, topic reaper, archive, latency 관리 호출이 있다. 일부는 가짜 HOME의 부재 설정 때문에 멈추거나 예외 처리되지만 모든 서비스 경로의 폐쇄를 이번 범위에서 증명하지 않았다.

132 이후 role request가 pending 되지 않는다는 assertion은 arming 규칙·guardian 토큰 등 앞선 전제에 막힐 수 있다. 현재 구현에는 `_arm_role_request` 893–952와 호출 1258이 존재한다. 따라서 오래된 ‘idle 창이 없어 role을 받을 수 없다’ 설명을 현재 실행기 결함의 증거로 세지 않는다. 규칙 로딩부터 arm/consume/종료까지 전체 역할 수명주기는 추가 독해·안전한 별도 실행 계획이 필요하다.

safe-mode fixture가 쓰는 future-expiry 토큰은 시험 작성자가 만든 JSON이다. 직접 읽은 1790–1835의 해당 reader는 만료 값 확인 중심이며 그것만으로 사람 발급 인증이 성립하지 않는다. done fixture의 PASS 이벤트도 실제 검사자 실행 영수증이 아니다. stub marker는 파일 존재 후 바로 JSON을 읽어 완료 쓰기와 존재를 혼동할 가능성이 있다.

원문 실행 시 300초 sleep subprocess를 실제 만들고 stale heartbeat로 죽이는 시험이 있다. 해당 child cleanup은 모든 실패 경로의 finally로 둘러싸이지 않으며 환경 변수도 이전 값을 복원하지 않고 pop한다. `_pid_alive/_terminate` 137–184는 Windows tasklist/taskkill에 의존한다. POSIX에서 같은 동작을 보증하는 분기가 이 구간에 없으므로 Linux/WSL 승인 근거가 아니다. deferred autoheart의 console 문자열을 실제 원장 변경 없음의 바이트 증거로 세지 않는다. 설치·스케줄러 등록·서비스 재시작·실제 LLM 호출은 시험 범위를 넘는다.

<a id="i09"></a>

## 09. test_ladder_probe_smoke.py — 97줄

4개 조건의 positive/negative fixture와 실제 인접 Guardian watchdog 호출을 연결하는 시험이다. guardian 파일 부재면 표준 전체 SKIP로 끝나며 이후 driver 연결 및 live marker 시험도 생략한다. `ladder_probe._fires` 100–111은 subprocess 종료 코드보다 alerts 파일의 progress 포함 여부를 판정한다. 특정 negative fixture에서 watchdog 오류가 나도 non-fire로 보일 수 있다. positive fixture가 항상 오류인 전체 실행은 걸러낼 수 있으므로 양쪽을 구별한다.

임시 guardian config의 auto_restore=false는 원문 의도이며 실제 watchdog source, 모든 알림·외부 서비스 호출을 읽은 것이 아니다. harness pin이 외부 Guardian 실행 바이트를 고정하지도 않는다. 실제 marker가 없으면 현재 `SKIP-AXIS`를 쓴다. marker 존재의 검사는 actual continue 결과나 전체 audit 내용까지 검증하지 않는다. 직접 읽은 audit parser는 손상 파일에도 present=true와 parse_error를 줄 수 있어 존재 alone은 유효한 운영 영수증이 아니다.

<a id="i10"></a>

## 10. test_ladder_smoke.py — 201줄

정책 seed 보존, fake run의 streak/FP/pending, ack, 승급/강등을 임시 policy와 원장으로 시험한다. 주입 카나리아는 `lambda: True/False`다. 이는 임시 상태 전이의 유용한 검사지만 기본 카나리아 실행과 같은 계약이 아니다. 직접 읽은 `pr4.py` 156–182는 `canary=None`이면 `golden.gate`를 대입하고 174에서 `if not canary()`로 거절한다. `golden.py` 73–76은 `(not failures, report)`를 반환하므로 실패 결과도 비어 있지 않은 튜플이다. 정상 반환한 골든 실패가 이 분기에서 거절되지 않는 정적 계약 불일치가 확인된다. golden의 예외까지 모두 허용한다는 주장은 하지 않는다. 원본 실행·프로브·재현은 0이다.

추가로 golden 36–76은 케이스 파일 부재/0건을 성공 bool로 반환하고 명령을 shell=True로 실행한다. 이번 검토는 실제 케이스 목록·held-out 접근 차단·실행 환경을 검증하지 않았다. 문서의 fail-closed라는 명칭을 검사 분모 보증으로 대체할 수 없다.

ack는 reason 존재를 요구하지만 actor='operator'를 자체 기록하는 구조다. 사람 인증 영수증과 다르다. 정책 저장 후 heart_change 원장 append는 서로 다른 쓰기여서 실패 원자성을 이 시험이 보증하지 않는다. PR4 sweep 83–140은 실행 rc=0을 PASS로 기록하며 SKIP/vacuous 분모 판정을 공유하지 않는다. 현재 정책 1–66에서는 일부 이미 승급된 validator가 있고 advisory인 pattern_decisions는 cmd=null이라 sweep 제외된다. 테스트의 ‘advisory가 반드시 남는다’라는 과거 조건은 현재 완화됐으며, sweep 0건도 메시지로 만족할 수 있다. 이를 현재 빈 검사의 차단 결함 재현 또는 승급 완료로 오인하지 않는다.

Zeus의 모델 자격 승급도 같은 위험을 피하려면 구조화된 검사 결과와 실행 분모, 동결된 입력, 독립 검토와 사람 승인 영수증이 필요하다. 이는 설계 대조이며 이번에 구현한 기능이 아니다.

<a id="i11"></a>

## 11. test_latency_budget_smoke.py — 198줄

registry 선언과 settings timeout을 먼저 확인한 뒤 실제 cache 파일을 소비하는 시험이다. 실제 latency 측정을 새로 실행하지 않는다. cache 부재/오래됨에서 `SKIP:` 및 `[PASS] 0 failure(s)`을 출력하고 return 0으로 끝나므로 앞서 발생한 FAILS가 종료 코드에 반영되지 않을 수 있다. 다만 현재 suite의 `test_outcome.classify_suite` 189–252는 bad text+rc0를 silent_fail로 분류한다. 이 기존 방어를 무시해 표준 suite가 동일하게 잘못 통과한다고 주장하지 않는다.

반대로 선행 positive checks가 있고 cache 축만 `SKIP:`인 경우 현재 분류기는 zero-check skip 중심이라 부분 축 생략이 표준 SKIP-AXIS와 같이 집계된다고 단언할 수 없다. 원문 실행이 없어 실제 check 분모는 산출하지 않았다. timeout 수집은 마지막 해당 값 및 누락 timeout 처리에 의존하며 Stop 예외는 수동 허용 목록이다.

신선도는 mtime 중심으로 source/spec digest에 결속되지 않는다. `over_budget`/`rc_nonzero`의 `.get` 기본값, cache 필드와 실제 샘플 계산의 연계는 receipt schema 검증과 구별해야 한다. hook_latency_probe 87–129는 실제 호출과 측정 캐시 작성 경로를 보여주지만 이 시험이 그 호출을 재실행한 것은 아니다. 과거 알려진 초과 이벤트 주석은 현재 측정 실패의 증거가 아니다. Windows/Linux/WSL별 지연 상한, 완전한 samples, 실제 pin과의 결속은 미검증이다.

<a id="i12"></a>

## 12. test_lease_smoke.py — 204줄

실제 임시 파일에 순차 acquire/revoke/grace/fence 및 idempotency 기록을 검사한다. 여러 worker가 동시에 경합하는 시험은 없다. 직접 읽은 lease 43–144는 acquire를 file_lock으로 둘러싸지만 이번에 플랫폼별 잠금 구현과 경합·크래시·재시작을 실행한 것은 아니다. 손상/누락 lease를 초기화하고 epoch를 다시 만드는 경우, stale owner 또는 외부 삭제와의 안전 전이도 이 fixture만으로 닫히지 않는다.

idempotency 1–39는 기존 key 읽기 후 append를 별도 수행한다. append 자체의 잠금이 read-check-append 전체를 하나의 임계구역으로 만드는 것은 아니다. 이 코드 alone의 동시 at-most-once 보증은 성립하지 않으며 상위 lease 규약·전체 caller를 더 확인해야 한다. 시험의 `git push`는 key/문자열로 쓰이며 실제 원격 push는 실행하지 않는다. key 선기록 후 실제 action 이전 crash의 누락 가능성은 외부 작업의 영수증 문제다. compaction 후 같은 key 차단도 실제 외부 액션 완료 증거와 다르다.

모델/effort와 tick directive JSON 기대값은 라우팅 매핑 시험이다. Astra 설계/최종 검증, Sol 가드레일 이관, Terra의 동일 시나리오 자격을 입증하지 않는다. PG의 트랜잭션 원장과 프로세스/외부 action fencing 도입 여부는 root의 별도 설계·구현 범위다.

<a id="i13"></a>

## 13. test_mirror_smoke.py — 124줄

임시 API/spec/ER 문서와 `app=1` 수준의 파일을 사용해 정적 index, ID/bytes 안정성 및 CLI pass/fail을 검사한다. 실제 API·DB·주문 흐름이나 사용자 시나리오 실행은 없다. 빈 wiki 디렉터리를 실패시키는 현재 fixture는 인정한다.

mirror 40–147의 경로 참조는 `path:line`에서 경로 존재를 확인하는 수준이다. 특정 줄 내용, 실행 코드의 의미 또는 모든 claim의 참·거짓을 증명하지 않는다. 읽은 판정은 docs가 존재하고 orphan/blocked/absent가 없으면 ready가 될 수 있어 제목뿐인 문서에서 claim 0건인 경계까지 이 테스트가 차단했다고 볼 수 없다. 이 0-anchor 경계는 코드 독해에 따른 가능성이며 실행 재현은 하지 않았다.

문서 정렬과 첫 anchor owner, git 없는 임시 프로젝트의 source commit 처리, 정적 atlas 쓰기는 유용한 traceability 출발점이다. 그러나 spec→scenario→실기기 관찰→E2E 코드→사람 승인까지 이어진 자산은 아니다. 인간 친화적 VIEW나 Device Replay가 구현됐다고 주장하지 않는다.

<a id="i14"></a>

## 14. test_monitor_readonly_smoke.py — 221줄

원문을 실행하면 실제 HTTP server subprocess와 로컬 요청을 만든다. 현재는 health의 service 문자열을 검증하므로 어떤 응답이든 200이면 같은 서비스라고 하던 약한 조건과 구별한다. 다만 임시 free port를 반환한 후 실제 bind 사이의 race가 있고 동일 service 문자열은 해당 run의 nonce/pid/source digest 인증까지는 아니다.

서버 기동 실패/다른 identity는 SKIP와 0으로 처리될 수 있어 테스트 자체가 야기한 기동 회귀와 환경 불가용을 명확히 분리하지 못한다. GET state의 key와 root HTML, POST/PUT/PATCH/DELETE 405, unknown 404를 확인한다. `do_*` body regex와 HOST 문자열은 제한된 정적 보조 검사다. GET 전후 상태 bytes나 외부 서비스 effect를 비교하지 않으며 SSE stream, 재연결, 중복 이벤트, 실제 브라우저 화면은 시험하지 않는다.

monitor source 45–88, 237–295, 317–362, 375–463, 757–795와 board 지원 구간을 읽었다. Collector의 deep 경로에는 실제 docker ps, PowerShell scheduled task 및 health 호출이 있다. 단순 fixture 메모리 서버로 분류할 수 없다. backlog 기본 경로가 HOME/state를 사용하여 HARNESS_STATE_DIR만으로 모든 read를 격리하지 않는다. 이 호출들의 전이 전체가 read-only라는 증명은 아직 없다. 임시 backlog 디렉터리 정리와 kill 뒤 최종 reap에도 미검증 경계가 있다. 실제 서비스, 기기, alpha/live 배포 상태를 바꾼 것은 없으며 배포 인수로 세지 않는다.

<a id="trace"></a>

## 직접 소비와 증거 경계

`files.json`의 full_body는 위 14개만 포함한다. `supporting-evidence.json`의 지원 파일은 표시해 읽은 정확한 구간만 기록하며 primary coverage에 합산하지 않는다. SHA는 파일 전체 raw bytes에 대한 식별자이며 전체 파일을 의미적으로 읽었다는 의미가 아니다. 직접 읽은 핵심 연결은 다음과 같다.

| 경로 | 실제로 추적한 소비 | 남은 경계 |
|---|---|---|
| heart 시험 → dispatch/guard_boot/heart_selfcheck/write_boundary | handler 판정, 복구 marker, journal 기록, `_probe` oracle | 모든 handler, 원본 실행, 복구된 파일 동일성, 알림 도달 |
| journal 시험 → hook_journal/prompt_rollup | 기록/집계/만료/digest 이관 | 승인 인증, 동시성, 전체 로그 손실 분모 |
| jury 시험 → judge_cmd/evaluator/codex_provider | fake provider, parse/quorum/누락 기록 순서 | 실제 Claude·Codex, 독립성과 모델 자격 |
| L2 시험 → l2_driver/role_supervisor | stub 스폰, role arm, maintenance, PID 종료, token reader | 외부 서비스 전체, 모든 스케줄러, OS 실행 |
| ladder 시험 → pr4/golden/ladder_cmd/policy | 승급·ack·카나리아 반환·sweep 분모 | 실제 golden cases와 단계 전이의 원자성 |
| monitor 시험 → server/board | HTTP 표면, read 경로, docker/PowerShell 호출 | 실제 service identity, GET effect, SSE/브라우저 |
| mirror/lease/invariants/probe | 실제 임시 파일/정적 claim/순차 fencing/oracle | 제품 E2E·동시성·외부 Guardian identity |

공통 isolate/path/runner/outcome/ledger/derive_state와 Zeus 경계 4개는 integration001에서 읽은 동일 raw bytes 구간을 재사용한다. 각 행은 현재 SHA 검증, 고정 revision, prior ledger SHA 및 prior review anchor를 보존한다. 이번에 다시 전체를 읽은 것으로 세지 않는다. 특히 runner의 silent_fail 방어와 표준 skip 분류를 현재 소비자 기준으로 해석한다. 테스트 안의 PASS 문자열, docstring의 E2E/atomic/CAS 명칭은 실행 결과가 아니다. `check()` 수가 환경·선행 return·조건부 경로에 따라 달라져 고정적인 전체 통과 분모를 만들어내지 않았다.

<a id="zeus"></a>

## Zeus 요구와의 대조

동일 바이트로 재사용한 Zeus `AGENTS.md`, domain/application SDD, model_routing의 정확한 구간과 SHA는 지원 원장에 있다. 이 범위에서 새로 Zeus 구현을 실행하거나 현재 전체 방어를 평가하지 않았다. PG runtime SSOT/Git 정의 권위, 합성 증거와 승인자의 행위 분리, 모델 선택과 자격 증거의 분리를 설계 기준으로 삼았다. 원본의 JSONL·local policy·operator 문자열을 그 권위와 자동으로 등치하지 않는다.

| 사용자 SDD 반복 단계 | 이 범위의 후보 자산 | 실제로 더 필요한 증거 |
|---|---|---|
| 1 스펙 논의 | invariant binding, mirror claim, jury 의견 | 사람의 핵심 시나리오·제외 범위·승인자와 spec digest |
| 2 디자인/인터랙션 분석 | 정적 claim/문서 연결 | 실제 화면·토큰·상태 전이·사람 검토 VIEW |
| 3 코드 작성 | depth/role/lease/dispatch | 자격 있는 실행자, 격리 환경, 작업 영수증 |
| 4 자체 검증 | guard·journal·ladder·latency smoke | 실제 도구 실행, 알려진 분모, skip/error 구분, 고정 환경 |
| 5 알파 배포 | L2/monitor의 일부 운영 경로 | 배포 artifact/environment identity, install/rollback receipt |
| 6 QA/사람 증거 | jury·approval 집계의 구조 후보 | fake claim 없는 실제 시나리오 관찰과 인증된 승인 |
| 7 라이브 점진 배포 | 승급/lease/fence의 구조 후보 | 실패 카나리아 차단, 최소 표본, 트랜잭션 전이, 점진 rollout |
| 8 CS/모니터링 | journal·HUD·mirror·repro 후보 | 전달된 알림, 원본 로그 보존, 사고→시나리오의 재현 증거 |

엄격한 금전 흐름에서는 성공 문자열, fake gate, 출처 없는 operator actor, 순차 멱등키 검사만으로 승인할 수 없다. mock은 fixture의 계약 검증으로 표시하고 사람 인수와 분리해야 한다. 실제 Samsung 기기, Device Farm SDK/MCP, live/interact/Replay는 유예된 범위다. 구현하거나 기기 테스트를 통과했다고 기록하지 않는다. 토큰 효율화는 모델 이름/effort의 라우팅만으로 완료되지 않는다. Astra의 설계·최종 평가, Sol 가드레일과 자격 이관, Terra의 같은 입력/오라클 재현을 별도 자산으로 결속해야 한다.

로컬 티켓+GitHub Issues는 이 발견을 다룰 후보 인터페이스이지만 이 subtask는 티켓을 전송하지 않았다. root가 실제 Claude 독립 검토와 대조하고 구현/채택을 결정한다. 원문의 기술 주장과 역사적 수치를 현재 권장 정답으로 소개하지 않았다.

<a id="unknowns"></a>

## 미완료와 종료 조건

14개 전문 독해와 명시된 지원 구간의 정적 검토만 완료했다. 아직 남은 항목은 전체 전이 및 모든 caller/config/fixture 몸체, 원본 실행과 안전한 격리 계획, 동시성·프로세스 회수·환경 복원, Windows/Linux/WSL 매트릭스, 외부 Guardian/Kafka/PG/Docker/스케줄러 identity, 실제 사람 인수와 모델 자격, Device Farm, 라이선스·재배포 및 실제 Claude 교차 검토다. 구체적인 미완료 경로는 `remaining.json`에 보존한다.

자체 검사는 기록기만 실행해 partition 일치, raw Git blob/size/SHA, 줄 범위, UTF-8, `.py` LF, review anchor와 artifact hash 및 own Ruff를 확인한다. 이는 upstream test PASS가 아니다. 결과와 최종 review SHA는 `checkpoint.json`, `verification.json`, `record-validation.json`을 참조한다. 이 bounded 범위를 넘는 source 수정·시험 실행·흡수는 하지 않고 root에게 결과를 전달한 뒤 중지한다.

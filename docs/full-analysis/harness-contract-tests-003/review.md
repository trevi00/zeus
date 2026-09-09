# Harness contract 003 정적 검토

정본은 harness `a3f8b3be9a0a389329de6e16a6c7db81782041a3`, partition `harness:tests/contract:003`이다. 16개, 178,523 bytes의 전문을 이번에 읽었다. 경로 원장 확인 당시 16개 모두 unreviewed였고 기존 의미 보고서나 전문을 재사용하지 않았다. supporting은 이번에 읽은 구간만 기록한다. 이전 범위와 같은 파일도 새 primary로 중복 계상하지 않는다. 모든 primary의 상태는 `body_reviewed_call_test_trace_pending`이다.

원본 실행·import·probe·network·install은 0회이며 live 트리, 사용자 설정, guardian 실토큰·인증정보에 접근하지 않았다. 원문 명령과 승인 문장은 데이터로만 읽었다. 아래 역사적 수치와 성공 설명은 소스의 주장이다. 이번 실행 결과가 아니다. 공개 보고서에는 긴 원문과 인증정보를 복제하지 않는다.

## common

시험 분모는 16파일이다. 시험이 출력하는 단언 수, 루프 시나리오 수, subprocess 실행 수, 사람이 실제 인수한 수는 서로 다르다. `test_outcome.py` 96–101, 189–251은 출력 줄과 종료값으로 pass/silent_fail/vacuous/skip을 가른다. `suite_cmd.py` 75–99의 SKIP-AXIS는 pass와 공존하는 미검증 축이다. 따라서 이 검토에서 예상 단언을 실행 단언으로 세지 않는다. 각 파일의 루프·조건부 축은 아래에서 명시하고 실제 실행 분모는 0으로 남긴다.

`tests/_isolate.py` 47–107은 L2 스탬프와 HARNESS_HOME을 제거하며 STATE_DIR만 임시 경로 또는 기존 주입값으로 돌린다. 이것은 OS 격리가 아니다. 원본 코드 import는 환경 변경과 파일·subprocess 부작용을 일으킬 수 있다. 원본을 실행하지 않은 제한은 결함 회피나 시험 통과가 아니다.

## f01

`tests/contract/test_gate_executable_contract.py` 1–208. 게이트 작성 시 필수 인자를 잡는 lint를 잠근다. 8종 bad/good 쌍, value=0, 미등록 type, 등록부 연결, 실제 트리, 사본 주입·제거, 빈 덤프 표면을 검사한다. 고정 TYPE_TABLE과 실제 CHECK_TYPES의 비교는 lint 표와 enum 비교이며 TYPE_TABLE 자체의 집합 비교는 없다. 새 type에 lint 표만 추가되면 그 type의 양방향 fixture가 자동 추가되는 것은 아니다.

SUT `harness_lint.py` 1642–1780은 덤프 부재·비정상 종료·JSON 실패·분모 0을 위반으로 만들고, origin=derived의 결손은 오류 목록에서 빼고 산문으로 출력한다. 해당 유예는 SKIP-AXIS 형식이 아니므로 runner의 미검증 축 목록에 자동 포함되지 않는다. 시험 155–157은 파생 결손이 현재 존재해야 통과하므로, 파생분을 모두 정상화하는 정당한 수리에도 fixture 갱신이 필요하다. checks.py의 읽은 분기는 인자 이름 대응을 뒷받침하지만 유효 URL·정규식·명령 성공·실제 자격까지 lint가 증명하지 않는다. `trigger_effect`의 관측 출력 일치도 명령 성공 및 실제 배포 성공과 분리해야 한다. Zeus에서는 8단계 각각의 구조화 게이트 입력을 정의 스키마로 검증하고 실행 영수증은 PG에 별도로 보존하는 적응 후보다.

## f02

`tests/contract/test_guardian_contract_smoke.py` 1–270. 실제 writer를 임시 state에 호출하는 heartbeat·run marker·lease 축, 손상 객체 판정, 소스 문자열 연결, 외부 guardian drift, 7채널 감사, 사용자 전역 훅 실행이 한 파일에 섞인다. guardian 부재와 전역 설정 부재는 skip_axis로 드러낸다. 역사적 30→22 단언 감소와 전역 훅 미적재 사고는 주석의 과거 주장으로만 남긴다.

`guardian_contract.py` 36–134는 필수 키·정확 bool/int·일부 enum·빈 문자열을 확인하는 형태 계약이다. 실행 주체 인증, 토큰 서명·만료, 실 PID 생존을 증명하지 않는다. 잘못된 JSON 상위 타입·list outcome 같은 입력은 판정 자체가 예외를 낼 수 있는데 fixture는 주로 dict의 특정 키 변형이다. `run_cmd.py` 123–147은 형태 검사 뒤 원장 append 후 바인딩 파일을 쓴다. 둘 사이 실패의 원자성은 이 시험에서 닫지 않는다. `_write_run_marker` 1372–1377은 계약 위반이어도 생존 마커를 기록하는 정책이므로 검사 존재를 차단으로 읽으면 안 된다. `ladder_probe.audit_boundary` 183–224는 전부 부재인 경우에도 총 위반 0일 수 있다.

전역 훅 축 216–256은 홈 설정의 command를 shell=True로 실행하며 stdout permissionDecision만 본다. 종료값·실제 파일 거부·등록 matcher의 전체 의미는 검증하지 않는다. 이 검토에서는 해당 live 설정을 읽거나 실행하지 않았다. Zeus에서는 lease/권한과 형태 검사를 나누고 실행 직전 PG fencing을 요구해야 한다. 호스트별 실제 hook 효과는 미완료다.

## f03

`tests/contract/test_harness_lint.py` 1–40. lint subprocess의 stdout을 전달하고 rc를 반환하는 래퍼다. timeout 120초, UTF-8 환경/콘솔 재설정은 과거 인코딩 오판을 줄이는 방어다. stderr는 보고하지 않고 timeout 예외도 별도 결과로 바꾸지 않는다. 실제 단언 분모는 하위 lint CHECKS가 찍는 줄에 의존한다.

`harness_lint.py` 2044–2092의 현재 등록부와 main을 읽었다. 각 검사 결과를 집계하지만 개별 검사 예외를 흡수하지 않는다. 이 범위에서 26개 등록 검사 전부의 함수 본문이나 guardian restorer의 known-good 등록 경로를 닫은 것은 아니다. docstring의 known-good 차단 주장은 이 파일의 실행 증거가 아니다. Zeus는 하위 stderr·timeout·실행 영수증 및 유예 축을 결과 계약으로 전달해야 한다.

## f04

`tests/contract/test_health_alerts_surface_contract.py` 1–156. 합성 4줄 로그에서 개입 2건·총수·마지막 행, 0건, 부재, PermissionError를 갈라 읽는다. 이는 누적 요청이지 미해결 건수가 아니라는 좋은 방어다. 95줄/8건과 SUT 주석의 98줄/8건은 각 시점의 역사적 주장이고 이번에 운영 로그를 읽지 않았다.

`health_cmd.py` 328–340은 비어 있지 않은 행과 부분 문자열을 세며 마지막 파일 순서를 최신으로 취급한다. 구조화 시각 정렬·중복·실제 수신·해소 상태는 없다. 873–886에서 해당 구별이 실제 출력에도 연결된다. 시험의 전체 소스 금지어 검사는 줄 시작 주석만 제거하므로 docstring/다른 산문의 영향은 남는다. sec_safety의 다른 경계 읽기와 외부 seal subprocess도 존재하므로 helper를 호출하는 것이 순수 단위시험은 아니다. `_guardian_home` 복원은 전체 finally가 아니며 temp 디렉터리는 mkdtemp 후 제거하지 않는다. Zeus 운영 알림은 요청/배달/확인/해소를 각 PG 영수증으로 구분하고 정보 부재를 0으로 접지 않는 원칙을 보존한다.

## f05

`tests/contract/test_heredoc_guard_contract.py` 1–168. 인용 여부, 백슬래시·백틱, 탭 제거형, 순수 텍스트, 종료 경계·유사어·잘림, 자기검출, 실제 트리와 임시 트리 rc를 양방향으로 검사한다. chr 조립은 fixture가 자기 스캐너를 오염시키지 않게 한다. 성공 출력 추가는 과거 rc=0/단언 0 회계를 개선한다.

`heredoc_guard.py` 70–132는 정규식 스캐너이며 셸 파서가 아니다. 확장 표지는 백슬래시·백틱만 포함하므로 달러 기반 확장만 있는 본문은 검출 범위 밖이다. 종료를 strip으로 비교해 일반 heredoc의 공백 종료 의미와도 다를 수 있다. scripts/tests의 지정 확장자만 읽고 OSError는 건너뛰며, 대상 디렉터리가 비어도 깨끗으로 끝난다. 문서의 커밋된 파일 범위 설명과 실제 rglob은 정확히 같지 않다. 대화형 도구 호출·PowerShell은 이 시험이 덮지 않는다. 현재 정책은 heredoc_guard를 blocking으로 둔다. 따라서 역사적 '승급 전' 설명을 현재 등급으로 읽으면 안 된다. Zeus에는 언어별 명령 계약과 불가용 분모를 적응해야 한다.

## f06

`tests/contract/test_hollow_audit.py` 1–162. 주석 제거의 위치·인접성 보존, hollow/weak/absent, 미상 경로, ratchet 증감, 실제 코퍼스 최소 분모를 검사한다. 과거 32 대 2라는 오탐 주장은 현재 재측정이 아니다. `ontology/contracts.yaml` 515–524의 freeze는 빈 사전이며 이는 설정상 허용 공허 0이다.

SUT `hollow_audit.py` 56–166은 tokenize와 AST를 쓰지만 문법 실패를 원문 또는 빈 탐지 목록으로 접는다. Finder의 변수 맵은 범위·재대입 분석을 하지 않고 target_path_parts는 HOME 문자열과 큰따옴표 부분만 추출한다. `hollow_cmd.py` 39–73은 파일 basename으로 집계해 동명 파일을 합칠 수 있다. 또한 hollow 총수는 부정 단언을 제외하지만 py_targeted에는 포함하므로, negated hollow가 생기면 세 판정 합계 계약과 불일치할 수 있다. fixture에는 이 조합이 없다. 인식되지 않은 문법·경로의 분모를 별도 남기는 방향은 보존하되 문자열 존재를 실행 coverage로 승격하지 않는다.

## f07

`tests/contract/test_hook_adversarial.py` 1–209. KNOWN_EVENTS와 15개 payload의 곱을 돌리는 의도이며 현 enum이면 Python dispatcher 120조합, bash launcher는 8×3조합이다. 이 숫자는 정적 계획이고 이번 실행 수는 0이다. rc/traceback/내부 오류/JSON 형태 및 state 쓰기를 합계 단언으로 검증한다. combos는 실행 전 증가하므로 시도 수이고 timeout은 별도 실패 목록이다. 거부 의미나 실제 도구 부작용 차단은 오라클이 아니다. 이벤트 8개 고정 단언과 JSON_EVENTS의 자동 보집합 분류가 있어 '새 이벤트 분류 강제' 주장은 제한적이다.

`dispatch.py` 160–311과 `hook_protocol.py` 30–167을 읽었다. handler budget은 실행 후 측정하는 soft budget이며 중단 타이머가 아니다. 잘못된 handler 반환형의 res.get은 handler try 밖에 있고 dispatcher 외곽 방어로 간다. registry의 fail-open/closed, 결정 우선순위와 최소 보호 경로는 존재하나 모든 입력에 같은 deny를 보장하지 않는다. `.claude/settings.json`은 프로젝트 경로 런처를 등록한다. `dispatch.sh` 13–25는 자신의 위치에서 runtime pin을 읽고 없으면 rc0으로 끝난다. launcher 축은 rc만 보므로 무발화 fail-open도 통과 가능하다. bash 부재 때 SKIP:를 쓰지만 다른 단언이 있으면 suite pass이며 SKIP-AXIS 목록에도 안 실린다. 주입 HOME/state는 실제 무접촉의 완전 증명이 아니다. Zeus는 hook 출력 형식과 host가 집행한 결과를 구분해야 한다.

## f08

`tests/contract/test_idle_role_arm_contract.py` 1–279. 요청 없음/있음, pipeline 선검사, 역할별 원장, 3회 재장전과 상한, index 접두 충돌, 읽기 불가 상한을 검사한다. home monkeypatch는 과거 원본 원장 오염을 줄이는 현재 방어다. 기존 주석의 '한 요청 한 번'보다 실제 시험은 회차별 재시도를 요구한다. 8건·9건 같은 형제 주석의 과거 오염 수치는 별도 원장 대조 없이 확정하지 않는다.

`l2_driver.py` 863–1132는 소비 게이트 실패를 로그 후 통과시키며, 차단 요청은 소비 표시하고 스폰하지 않는다. preflight 다음 idempotency 기록, 다음 원장 디렉터리 생성·run_cmd.arm 순서라 뒤 실패는 시도 예산을 소비한다. 1127–1129의 자동 재시도 불가 문구는 현재 3회 정책과 맞지 않는다. 요청별 원장은 서로 다른 회차에서는 재사용하고 run 간 gate ratchet의 손실도 주석에 명시한다. 시험은 동시 장전, 실제 `_try_arm`의 안전 전제 및 소비 실패 경로를 완전히 검증하지 않는다. ②는 상한 뒤 무증가를 재며 활성 회차 경합을 직접 재는 것은 아니다.

`role-request.yaml` 54–83은 report 1단계, 문자열 ROLE-REQUEST:와 카나리아의 존재만 강제한다. 요청 ID 일치·실제 카나리아 설계의 질·사람 인수는 강제하지 않는다. Zeus 8단계 SDD의 완료 계약으로 그대로 쓸 수 없고 요청/회차/generation 및 산출물 귀속을 PG로 결속해야 한다.

## f09

`tests/contract/test_inv_bite_smoke.py` 1–117. 실제 mutation 실행을 명시적으로 제외하고 강제 구역 도출과 변이 귀속만 잰다. 합성 placed 3개와 미배치 구역 0개를 구분하며 loose 생존을 유지한다. 실제 ontology validator의 태그가 4개 이상이라는 코퍼스 단언은 의미 검증보다 탐지기 생존 검사다.

`invariants_cmd.py` 390–438은 AST 함수 범위를 얻은 뒤 원문 함수 문자열에 regex를 적용한다. 대괄호/따옴표로 INV를 언급한 주석·docstring도 강제로 분류될 수 있고 중첩 함수 구간은 중복 귀속될 수 있다. '자유 주석의 INV-71' 음성 fixture만으로 주석 일반 배제가 증명되지 않는다. placed와 survived는 호출자가 준 목록이며 독립 실행 영수증이 아니다. Zeus에서 분모 0과 전량 적발을 가르는 원칙은 보존하되 mutation 생성·선별·실행·실패 원인을 각 receipt로 연결해야 한다.

## f10

`tests/contract/test_isolation_deferred_contract.py` 1–107. 승격 시 home suite 재검사 자리가 있다는 정적 계약과 16건 역사 기준·상한 20을 잠근다. 현재 스킵 수를 수집하지 않으며 synthetic count를 전달한다. 문서도 실제 미래 통과는 보장하지 않는다고 한정한다.

핵심 공백: `isolation_deferred.py` 64–106의 ast.literal_eval은 현재 `autoheart_cmd.py` 1057의 frozenset 호출식을 읽을 수 없다. `_literal`은 None을 반환하고 deferral_path는 PATCH_GATES가 None일 때 오류를 내지 않아 경로를 유효로 만든다. 시험 70–87은 `_literal`을 목록/None 반환 함수로 교체하여 이 실제 표현식 연결을 놓친다. None 축은 GATES 실패만 본다. 현재 gate_plan 1116–1131에는 실제 `_g_suite(home)` 호출이 있으므로 지금 suite가 patch를 잰다는 결함을 주장하는 것은 아니다. 검사기의 실패 감지가 불완전하다는 정적 발견이다. Zeus는 실제 실행계획과 누락 축 목록을 immutable receipt로 결속하고 재검사 슬롯 존재를 완료로 처리하지 않아야 한다.

## f11

`tests/contract/test_judge_integrity_league.py` 1–237. 메모리 스냅샷 7변이·2대조군을 만들고 분류율과 자동 차단률을 분리한다. 변이 G는 분류 미탐이어도 판정불능 차단을 요구한다. 이 fixture의 JUDGE는 check가 pass인 문자열이며 실제 gate 시험 실행이 아니다. 과거 삭제 센티널 오류와 67%는 fixture 역사다. 현재 리그를 사람이 승인했거나 D-046에 집행했다는 뜻이 아니다.

`judge_integrity.py` 68–157은 tests 경로·test_ 이름을 판정 대상으로 삼고 감소/상수참/skip 증가를 regex로 분류한다. 기존 내용이 조금만 바뀌어도 판정불능으로 차단하는 방어가 있지만, 새 파일은 내용 분석 없이 강화로 분류하고 실제 gate 소스·runtime·정책 변경은 별도 축이다. 테스트의 '순수' 검사는 금지 문자열 검색이어서 간접 I/O나 주석 오탐을 해결하지 않는다. Zeus에서 독립 판정기와 revision 결속은 적응 후보이나 이 분류율을 전체 자기수정 안전성·모델 자격으로 계상하면 안 된다.

## f12

`tests/contract/test_judgment_paths_contract.py` 1–182. 알려진 4개 판정기, 근거 비어 있지 않음, 경로/등록부 부재, AST 읽기, 외부 guardian glob, SELF_BLIND, CLI JSON 집합을 검사한다. guardian 부재는 현재 명시 유예로 바뀌어 과거 환경 결함의 영구 반려를 피한다. 외부 guardian 원문은 이번 범위에서 접근하지 않았다.

`judgment_paths.py` 44–150은 pipeline YAML을 파서가 아닌 줄의 cmd: 및 regex로 읽고, 존재하는 파일만 add한다. 주석에 있는 cmd나 복수행·다른 이름·확장자·동적 조합은 오탐/미탐 범위다. AST 등록부는 import하지 않으나 항목별 부재는 조용히 생략한다. covered_by_anchor의 소문자/숫자/밑줄 regex는 guardian의 일반 test_*.py glob과 집합이 정확히 같지 않을 수 있는데 시험의 4개 예는 그 차이를 안 다룬다. `harness_lint` 1484–1521은 빈 도출은 실패하지만 반환 등급이 limb인 경우만 위반으로 삼아 누락/미등록 등급을 닫지 않는다. SELF_BLIND 문서 문자열 확인과 실제 등록 tuple 773–778을 대조했지만 전체 집행 closure는 미완료다. Zeus는 등급·자격을 역할 이름과 분리하고 정의 graph에 대한 독립 승인을 요구해야 한다.

## f13

`tests/contract/test_known_issues_contract.py` 1–254. 임시 git 트리에 합성 발의를 넣고 겹침/정렬/상한/잘림/손상/git 실패, 정보 문구, 고정 역사 신호, 실제 코퍼스의 동적 분모를 검사한다. git init/add rc는 확인하지 않는다. 기존 source는 90분의 중복 진단을 회피하려는 정보 표면이며 승인 확대가 아니다. 시험은 제목에 명령형 문구가 들어오는 공격이나 실제 세션의 오독을 검증하지 않는다.

`known_issues.py` 73–173은 git 실패를 빈 문자열로 흡수하고 porcelain 경로 및 최근 6커밋 diff를 합친다. 깨끗한 트리가 반드시 신호 0은 아니다. 반대로 모든 git 명령이 성공해도 변경 없음·대상 불일치로 선택 0일 수 있어, 시험의 빈 결과 사유 설명은 완전하지 않다. JSON syntax 오류는 건너뛰지만 상위 list/scalar는 `_load`에서 실패할 수 있다. target_project substring과 제목/slug를 그대로 brief에 넣으므로 신뢰 경계는 산문 경고뿐이다. driver 1921–1924는 예외를 로그 후 넘어가므로 정보가 빠져도 스폰은 진행한다. Zeus에서는 제안을 신뢰도와 출처를 가진 데이터로 주입하고 사람이 승인한 작업 scope와 분리해야 한다.

## f14

`tests/contract/test_l2_driver_latency_gate.py` 1–454. 초기 '소비자 0' 설명과 2026-09-04/05 착지 수정이 공존한다. 현재 단언은 fresh over→rc2/무스폰, fresh clean→rc1/stub marker, stale 통과, timestamp 대 mtime, idle 재측정과 위치를 요구한다. 판정 분모는 각 helper의 check 출력이며 토큰 파일 수는 호출 횟수가 아니다.

직접 읽은 host fixture는 Python stub이 argv/env를 marker에 쓰는 구조다. 합성 만료 토큰, 최소 pipeline, 조건부 runtime pin 복사이며 실제 Claude나 실제 사람 승인, 실제 모델 자격을 검증하지 않는다. `_binding`은 unattended/reflector 필드를 생략하여 정식 run_cmd의 형태 계약을 통과한 바인딩과도 다르다. marker가 생겼다는 것으로 프로세스 성공 종료·작업 완료까지 알 수 없다. 스케줄 축은 파일/시각 변화이지 모든 이벤트 성공을 요구하지 않는다.

driver 1754–1788과 1857–1875에서 지연은 cap 뒤, token·lease·idempotency 앞에 있다. 이 위치의 현재 방어는 확인했지만 토큰 위치 문자열 검사는 제어흐름 증명은 아니다. `_latency_pass` 321–334는 probe 반환 error 사전을 보지 않고 갱신 로그를 찍을 수 있다. `hook_latency_probe.run` 87–91은 bash가 없으면 error를 반환하므로 실제 갱신 없는 성공 문구 가능성이 있다. 또한 손상 시각에서 sec_latency가 probed=True를 내면 재측정을 안 하며 소비자는 unknown으로 흘리는 연결이 남는다. Zeus에는 측정 receipt의 revision·시각·실행 품질과 재측정 상태를 명확히 나눌 필요가 있다.

## f15

`tests/contract/test_ladder_sweep_contract.py` 1–255. HEAD/24시간/부재·손상·safe mode·spawned/실패/0건을 fake sweep으로 검사하고 실제 todo_scan subprocess 대조를 더한다. 역사적 '9개 advisory streak 0'과 현재 정책은 다르다. 읽은 validator-ladder 설정에서 todo_scan·heredoc_guard는 blocking이고 남은 advisory는 cmd:null이므로 이 설정의 advisory 스윕 실행 대상은 0개다. 성공 fixture의 advisory todo_scan은 현재 설정 실물이 아니다.

driver 394–439는 스윕 예외 때 marker를 안 쓰지만 결과 0건이면 로그 후 marker를 갱신한다. 시험은 0건 로그만 확인하여 다음 24시간 억제까지 검증하지 않는다. '마커 무변경' 축은 ts가 비어 있지 않은지만 비교하여 같은 값 보존을 증명하지 않는다. 183행 True 단언은 앞 호출이 예외 없이 반환했다는 약한 경로 증거이며 독립 상태 검사로 세지 않는다. timezone 없는 유효 ts나 상위 JSON 타입 오류는 바깥 catch로 흘러 재측정도 막힐 수 있고 fixture는 주로 syntax 오류다.

`pr4.py` 83–182의 실적은 PASS 누적과 ack에 따라 도출되며 HEAD/시간은 독립성의 대리 지표일 뿐이다. ack의 actor=operator 문자열은 인증이 아니다. graduate는 정책 저장 뒤 원장 이벤트 순서이고 실제 CLI 권한/사람 토큰 경로는 여기서 닫지 않았다. Zeus는 validator 입력 해시와 반복 generation, 실제 승급 승인 및 PG 영수증을 결속해야 한다.

## f16

`tests/contract/test_latency_consumer_contract.py` 1–352. synthetic 측정으로 block/ok/unknown/stale, 기동 바닥, 경계값, 오염·혼합·산포를 검사한다. live 측정이 없으면 계산 대조를 skip_axis로 명시하는 현재 방어가 있다. '못 재면 안 막되 말한다'는 운영 정책이지 검증 성공은 아니다.

AST `_blocks_on` 162–174는 조건 원문에 lat[block] 문자열이 있고 하위에 return2가 있으면 참이다. 바깥 if False나 조건의 and False, 도달 불가능한 하위 반환을 제거하지 않으므로 '죽은 분기는 안 센다'는 설명보다 약하다. SUT의 현재 정상 branch는 직접 읽어 확인했지만 이 검사 일반성은 미완료다. `latency_gate.over_budget` 90–99는 body>budget만 비교하고 프로브 120–121은 budget>0도 요구한다. 0/음수 예산의 교차검증 차이는 현재 fixture가 다루지 않는다. 실 gate는 이 순수 재계산 함수를 쓰지 않고 파일의 over_budget 필드를 믿으므로 재계산 시험 통과가 판정 경로의 같은 수식 사용을 증명하지 않는다.

health 판독기는 구조화 필드 타입·유한수·미래 timestamp·event 분모 전체를 검증하지 않는다. gate는 None age/오염/산포를 unknown으로 구분하지만 파일 품질·측정 실행 주체·현재 revision을 인증하지 않는다. 손상 시각에 대한 판독기와 소비자의 차이를 fixture로 고정한 것은 역사 보존이지만, 판독기 수리 후 기대값을 갱신해야 한다. Zeus의 운영 budget 판단과 8단계 SDD acceptance는 별도 권한이며 unknown을 성공으로 세지 않아야 한다.

## supporting

supporting.json은 이번에 실제 읽은 모든 지원 파일의 구간·SHA-256·Git blob·bytes를 기록한다. files.json의 supporting_ids는 파일별 직접 연결이다. 새 구간을 읽었으며 이전 보고서 의미나 body를 재사용한 항목은 0개다. 검색만 한 항목을 전문 검토로 계상하지 않았다. 지원 파일은 global primary coverage에 더하지 않는다. 외부 guardian·사용자 홈·runtime pin·운영 원장·실측 latency 파일은 접근하지 않았으며, primary에서 그 경로를 호출한다는 사실만 확인했다.

## zeus

사용자가 정의한 8단계 SDD와 이 원본의 report 단일 단계·자기개선 단계는 등가가 아니다. 요구/설계/계획/구현/검증/인수/배포·운영 등 단계 이름이나 순서를 이 범위에서 새로 확정하지 않는다. 실제 사용자 정의의 각 단계에 입력 정의, 산출물 handle, 독립 gate, 승인 주체, revision, execution receipt를 연결하는 적응이 필요하다. 문자열 카나리아·known-good·operator·approve가 그 연결을 대신할 수 없다.

Git 정의와 PG runtime 권위 원칙에 맞추려면 원본의 JSONL 실적·별도 바인딩·스케줄 marker를 현재 Zeus 구현과 직접 대응시켜야 한다. 이 보고서는 구현 등가성을 주장하지 않는다. unknown/부재/실패를 나누는 방어, 동일 실행의 분모 보존, 판정기 독립성, 재시도 예산, source와 제안의 권한 분리는 보존 후보다. 실제 Claude 공동 검토·모델 자격·라이선스·Windows/Linux/WSL·전체 전이 closure·사람의 실제 인수·채택 승인은 모두 미완료다.

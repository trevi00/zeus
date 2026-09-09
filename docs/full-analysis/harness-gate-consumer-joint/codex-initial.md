# Codex 판정 소비 경로 검토 — Claude 초기 결과 열람 전

대상 revision `a3f8b3be9a0a389329de6e16a6c7db81782041a3`. `checks.py`, `gate_runner.py`, `select_ready.py`, `testgen.py`, `tick.py` 전문을 읽었다. 기존 Codex 엔진 파티션 보고서에서 후보를 발견한 뒤 root가 원문과 직접 연결부를 다시 읽은 검토이며, Claude 독립 보고서는 아직 읽지 않았다. 출력 절단이 있었던 tick 후반은 별도 재독했다. 원본 실행·테스트 실행 0건, 새 실제 PASS 증거 없음. 과거 차단된 정상 gate-writer ERROR probe는 재시도하지 않았다.

## 확인한 방어

checks는 미등록 실행기·예외를 ERROR로 반환하고 db_query는 비정상 종료를 FAIL로 판단한다. exit_code repeat는 첫 실패에 중단한다. 옛 독스트링의 미구축 4종과 달리 현재 실행부가 존재한다. gate_runner는 ERROR를 PASS/FAIL로 바꾸지 않고 stage_finished(error)를 기록하며 외부 None/PARTIAL을 대기로 남긴다. cycle_started.redo는 외부 판정을 철회한다. select_ready는 단계 의존을 파일 존재가 아닌 derive_completed로 계산한다. 명령 표면에는 렌더 문장의 모호성·근거 공백 거부가 실제 있다. pipeline_loader는 ID 중복·DAG 순환·미해석 의존·실행기 enum 등을 거부한다. reenforce는 자식 stdout 인코딩 지정, cwd/무인 세션 바인딩, 결과 JSON의 outcome 소비를 수행한다.

## C01 — 문장·실행 귀속과 철회의 소비 불일치

`step_cmd judge`는 복수 render 문장에서 statement를 필수화한다. `residual_cmd`도 stage+mode에 속하는 statement만 기록한다. 그러나 `gate_runner._external_verdict(events, stage_id, mode)`는 statement를 받지 않으므로 A=FAIL 뒤 B=PASS면 같은 mode의 두 게이트가 최신 B=PASS를 소비하는 정적 경로다. 이것은 기록 누락 문제가 아니라 이미 기록된 귀속을 소비하지 않는 문제다. actor/by/실행·후보·산출물·정의 해시를 이 소비자는 대조하지 않는다. writer의 자율 by 스탬프는 존재하므로 '귀속 장치 전무'라고 표현하지 않는다.

`ledger.read_events`는 원시 레코드 목록을 반환한다. derive_state의 reducers는 apply_retractions를 통과하지만 `_external_verdict`와 tick의 다수 직접 주사는 이 필터가 없다. 외부 판정 이벤트에 tombstone이 붙어도 해당 helper에서는 살아 있고, 재개방 이벤트가 철회된 경우에도 raw scan은 철회를 수행할 수 있다. 전체 복구/컴팩션·권한 흐름은 이번에 실행하지 않았다.

## C02 — PARTIAL의 대기 계약과 재실행 지시

gate_runner와 residual 목록은 None 또는 PARTIAL을 미종결로 본다. tick._pending_external은 None만 찾는다. 따라서 PARTIAL gate_check로 상태가 GATING인 경우 human 대기로 분류하지 않고 gate 재실행 지시를 만들 수 있다. gate 재실행은 다시 PENDING_HUMAN이므로 자동 재지시가 발생할 정적 경로다. iter는 stage_started만 세므로 게이트 재시도 그 자체의 횟수 캡이 아니다. wallclock과 Stop transcript bytes 등 외곽 제한이 있어 '항상 무한 루프'로 일반화하지 않는다.

## C03 — ERROR 이후 완료 집합과 순서

기존 harness-lib 검토의 PASS→ERROR reducer 불일치를 호출부에서 다시 확인했다. 정상 gate_runner ERROR 분기는 gate_verdict(ERROR)가 아니라 gate_check(ERROR)+stage_finished(error)를 쓴다. derive_stage_states는 FAILED가 되지만 fold_latest_verdicts는 이 이벤트들로 과거 PASS를 철회하지 않는다. is_done은 completed를 먼저 인정하고 tick은 is_done을 last_status error 검사보다 먼저 호출한다. 이들은 정적 코드 연결이며, 차단된 정상 writer 실행 재현의 대체 증거로 표시하지 않는다. 선언 precondition의 변경 등 앞선 분기가 있으면 결과가 달라질 수 있다.

## C04 — 검사 성공·검사 모집단·프로세스 성공의 차이

metric_threshold는 명령 exit를 meta에 담고도 비교에 사용하지 않는다. trigger_effect는 stdout+stderr의 regex만 보고 exit를 검사하거나 evidence에 보존하지 않는다. 비정상 명령의 출력이 기준을 만족하는 입력은 PASS 경로다. 이는 모든 명령 검사가 같다는 뜻이 아니며 db_query/exit_code는 종료 코드를 본다.

file_exists는 디렉터리도 허용하고 file_content는 여러 파일을 합쳐 존재 규칙을 적용한다. forbid가 있으면 expect/against보다 먼저 반환한다. 이번에 전문 읽은 pipeline_loader도 forbid+expect 조합을 거부하지 않는다. 금지 검사의 0파일 PASS는 의도된 의미지만 파일 존재 의무와 결합하지 않으면 요구 충족을 입증하지 않는다. loader는 gate 누락/빈 목록을 최소 1로 강제하지 않아 run_stage_gate의 빈 반복이 PASS 분기에 도달할 수 있다. stages가 없으면 is_done도 공허하게 true이다. 실제 arm의 추가 검증이나 현행 정본이 빈 목록을 사용하는지는 아직 미확인이다.

HTTP 기대 404 등은 urlopen 예외 경로 때문에 실제 상태 비교 이전 FAIL이 된다. subprocess timeout은 명령 1회당 600초이며 전체 repeat/자손/메모리 상한은 아니다. Windows shell=True 기본 셸, PowerShell/Bash 선택, {harness} 공백 경로, 전체 출력 수집의 이식성은 따로 검증해야 한다.

## C05 — 선언 변화·검사 도중 변화·한도

gate_ratchet는 stage+statement 삭제만 본다. 같은 문장으로 cmd/regex/threshold/scope를 바꾸는 약화를 탐지하지 않는다. waiver는 키 존재로 면제하며 읽은 loader/consumer는 비어 있지 않은 사유나 승인 서명을 강제하지 않는다. tick은 ratchet/staleness 예외를 빈 결과로 바꾸고 staleness 재지시를 캡보다 먼저 반환한다. preconditions는 게이트 후 계산하므로 실행 전후 대상이 같았다는 증거가 아니다. 파일 텍스트 SHA16과 unknown/absent sentinel, 선언 미도입 이전 기록 허용은 실제 bytes/runtime 환경 봉인과 다르다.

tick의 완료 detail은 PASS만 말하지만 is_done에는 SKIPPED도 포함된다. running 의존 probe를 tick이 주입하지 않아 이 표면에서는 미충족이다. skip된 단계를 downstream 완료로 취급하지 않는 설계의 의미는 별도 계약 확정이 필요하다. select_ready는 관측 함수이며 원자적 claim이 아니므로 'RUNNING/GATING 제외'만으로 동시 dispatch를 막았다고 할 수 없다.

## C06 — GWT 골격과 실제 인수 증명

testgen은 AC 단락에서 단일 줄 Given/When/Then을 추출하고 각 내용을 120자로 잘라 docstring에 넣는다. 문단별 첫 AC에 연결하고 UNANCHORED도 허용한다. literal escaping 없이 삼중 따옴표를 삽입하므로 특수 입력에서 잘못된 코드가 생길 정적 경로가 있다. generated tests는 xfail(strict=False)+NotImplementedError이며 행동 oracle이 없다. 명시한 '구현 전 그린 금지'가 프로세스 exit0 차단으로 구현된 것은 아니다. CLI는 GWT0을 rc1로 거부하는 방어가 있고, 기존 출력 파일은 직접 덮어쓴다. small_batch 테스트는 개수·xfail 문자열·멱등을 검사하며 실제 주문/결제 인수가 아니다.

## Zeus 적응 방향과 남은 검증

추가로 `usecase_lint.py`와 `templates/_common/usecase.template.md` 전문을 읽었다. lint의 gwt-min은 UC 본문에 Given/When/Then 문자열과 실패 문자열이 존재하는지만 확인한다. testgen은 세 요소 사이에 실제 개행을 요구한다. integration smoke의 합격 예시와 실제 usecase 템플릿의 한 줄 `Given a / When b / Then c`는 lint와 생성기가 같은 구문을 소비하지 않는 경계다. AC 전역 고유 검사도 같은 UC 안의 같은 ID 재등장은 허용한다. 의미 oracle을 공유하는 구조화 시나리오 파서와 독립 실행 검증이 필요하며, 이는 정적 비교로서 테스트 실행 결과가 아니다.

판정의 공통 좌표에 spec revision, run/cycle, stage, 고정 statement ID, gate 정의 해시, 산출물·환경 식별자, 원본 실행 receipt를 묶고 PG에서 최종 승급을 원자적으로 판단하는 후보가 필요하다. 계획된 전체 시나리오 대비 실행/미실행/skip/partial/error를 별도로 계산해야 한다. 실제 사람이 승인한 내용과 agent render 검토를 섞지 않는다. SDD→scenario→실기기 기록→E2E의 연결은 이 skeleton만으로 충족되지 않는다. 모델 이름과 effort 선언도 Sol/Terra 자격을 증명하지 않는다.

이번에는 source gate/CLI/외부서비스를 실행하지 않았다. supporting 읽기 범위와 해시는 별도 기록한다. 차단 이력의 실행 과제, 전이 의존성/인증/컴팩션/동시성, 실제 Win/Linux/WSL 설치 및 실행, device·결제 인수, 전체 소스 검토와 채택 결정은 남아 있다.

Zeus 현재 `domain/sdd.py` 1–75 및 169–204행, `docs/sdd/README.md`와 `docs/zeus/full-delivery-scope.md`를 대조했다. 현재 gate_report는 모든 단계 blocked/acceptance_passed=false이며 propose_scenarios는 관측과 검토 요청만 만든다. 이것은 잘못된 upstream PASS를 흡수한 운영 상태가 아니라 구현 전 준비 상태다. 개선 완료를 위해서는 실제 runner/사람 승인 제공자와 반복 전이를 구현해야 하며, 계속 blocked를 반환하는 것만으로 목표를 달성했다고 할 수 없다.

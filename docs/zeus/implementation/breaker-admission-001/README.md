# 차단기 admission은 커밋된, 세대로 fence된 전이다

기존 FA-020 / GitHub [#21](https://github.com/trevi00/zeus/issues/21) / `ZEUS-0ecf8213b0da` 개정 1의 구현·검증 기록입니다.
상류 composite breaker의 격리 실측([resolution](../../../full-analysis/baldrix-breakers-001/resolution.md))에서 상태 파일을 쓸 수
없어도 `try_acquire`가 두 번 true를 돌려주고, 시각상 오래된 예약을 새 객체가 회수한 뒤 이전 객체의 성공이 현재 슬롯을 닫고,
sibling 중복·나열 순서가 cross-mode 판정을 바꾸고, bool 정책 덮어쓰기가 "성공"인데 유효값은 기본값이며, alias/슬래시 치환이
같은 경로를 만드는 것이 확인됐습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus에는 provider 장애에 대한 차단기가 없었습니다(`health_failure_threshold`는 배포 health probe 전용). 모델 호출은
  실패하면 attempt/재시도 정책으로만 다뤄졌습니다.
- `domain/breaker.py` (stdlib만):
  - `parse_policy()`: 닫힌 스키마(version 1, `failure_threshold`, `window_seconds`, `cooldown_seconds`, `probe_ttl_seconds`,
    `max_history`, `revision`). 정수는 `type is int`(bool 거절), 양수, NaN/Infinity 거절, 교차 조건(threshold ≤ 보관 이력,
    probe TTL ≤ 실패 window), revision은 40-hex 커밋 또는 명시적 `unversioned`. `policy_hash`를 붙입니다.
  - `breaker_key(provider, scope)`: 소문자 토큰 두 개를 digest한 identity. alias/대문자/공백/슬래시/경로는 정규화하지 않고
    거절하므로 충돌도 우회도 없습니다. 파일 경로를 만들지 않습니다.
  - `parse_state()`: 상태 레코드 검증(상태 이름, 정수 generation, 실패 이력 목록·id·aware 시각, 예약 shape, half-open만 예약
    보유). 실패하면 손상입니다.
  - `fold_failures()`: 실패 이벤트를 id로 유일화하고 (시각, id)로 정렬한 뒤 window 안만 셉니다 — 중복·입력 순서 무관.
  - `decide()`: 순수 전이 결정 — closed→admit, open→cooldown 전 refuse/후 probe, half-open→예약 생존 시 refuse, TTL 경과
    시 reclaim, 예약 없음이면 probe.
- `application/breaker.py`: `Breaker(store, policy)`.
  - `admit(key, lease, now)`: 한 트랜잭션에서 상태를 읽고 전이를 커밋한 뒤에만 토큰(`generation`, `probe`, `policy_hash`,
    `policy_revision`, task/attempt, 시각)을 돌려줍니다. probe/reclaim은 generation을 올리고 예약(owner/task/attempt/TTL)을
    씁니다. 커밋에 실패하면 토큰이 없습니다. 손상 레코드는 `breaker_notices`에 알림을 남기고 `requires repair`로 거절합니다.
  - `report(token, result)`: 토큰 generation이 현재와 다르면 `stale_result` 이벤트만 남기고 상태를 바꾸지 않습니다. probe
    토큰의 success→closed, failure→open, unknown→슬롯만 해제. closed 토큰의 failure는 유일 이벤트로 이력에 들어가고 window
    안 개수가 threshold에 닿으면 open(generation 증가). 상태가 바뀔 때마다 generation이 올라가므로 이전 세대의 결과는 모두
    stale입니다.
  - `inspect(key)`: `missing`(새 것, 증명 없음)/`corrupt`/`unreadable`/실제 상태를 구분하고, 어느 경우에도 "admission only;
    never acceptance, graduation or deployment"를 명시합니다.
  - `update_policy(doc, revision)`: 쓰기 전 검증 → 저장 → 다시 읽어 같을 때만 `applied`. 거절된 쓰기는 유효 정책을 바꾸지
    않습니다.
  - `result_of()`/`result_of_exception()`: provider 원인 실패(`codex-provider-*`)와 transport 사망/timeout(`Codex …`
    ContractError)만 failure, 출력 계약 위반·interrupted·inspection_blocked·기타 예외는 unknown.
- `adapters/executor.py`: `_run`에서 호출 전 `breaker.admit(breaker_key('codex-app-server', workload), lease)`, transport
  예외 시 `report(result_of_exception)`, 결과가 오면 `report(result_of(result))`를 증거(`result['breaker']`)에 남깁니다.
  open 상태면 transport에 닿지 않고 `Breaker refuses admission`으로 거절됩니다.
- `docs/contracts.md`: `INV-BREAKER-001` 추가.

## 재현과 검증

- `tests/test_breaker.py`(13 검사; 원장 검사는 MemoryStore + 이 PC의 PostgreSQL 일회용 스키마):
  - 정책 검증 13종(bool threshold, 0/음수 window, NaN/Infinity cooldown, 미상 version, 교차 조건 2종, revision 2종, 키
    누락/추가).
  - 키: 다른 부분 분할이 다른 identity, alias/공백/슬래시/`..`/Windows 경로 거절, 경로 없음.
  - 이력 fold: 순서·중복 무관, window 밖 제외, 잘못된 시각 거절. 상태 레코드 손상 12종 거절, 결정 함수의 refuse/probe/
    reclaim 경계(cooldown 119/120초, TTL 299/300초).
  - 단일 probe 슬롯 (memory+PG): closed에서 실패 2회 → open(gen 1) → cooldown 전 거절 → probe(gen 2) → 다른 holder 거절
    ("probe in flight") → TTL 경과 후 다른 holder가 reclaim(gen 3) → **이전 holder의 늦은 success는 stale**(적용 안 됨,
    half-open 유지) → unknown은 슬롯만 해제 → 새 probe(gen 4) success → closed(gen 5). 이벤트에 stale_result 1, probe_reserved 3.
  - 동시 admission 8스레드(memory+PG): open→cooldown 후 정확히 1개 probe, 나머지 "probe in flight", 예약 holder·generation 일치.
  - 저장 실패: 커밋이 실패하는 store로 admit → 예외, 예약 없음, 상태 불변; 정상 store로는 곧바로 probe 가능.
  - `missing`/`corrupt`(`failures: null`, NaN generation)/`unreadable`(닿지 않는 DSN) 구분, 손상 시 admit 거절 + 알림 1건(재시도해도 1건);
    **실제 PG**에서 `UPDATE documents`로 `state: "true", history: null` 주입 → corrupt + repair 요구.
  - 정책 쓰기: 검증 통과분만 적용되고 read-back 확인, bool 덮어쓰기는 거절되며 유효값 불변; 토큰이 정책 revision/hash를 실음.
  - 결과 매핑 7종. Executor 배선: transport가 `Codex App Server exited` 예외를 2회 내면 open, 세 번째 호출은 transport에
    닿지 않고 거절(호출 횟수 2 그대로), 정상 호출은 증거 `breaker.verdict == 'success'`·key·admitted_generation 기록.
- 기존 Executor 검사 4개 파일과 함께 90 passed.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`): stale generation을 그대로 적용하면 1 실패, 이력을
  입력 순서·중복 그대로 세면 1 실패, bool을 정수로 받으면 1 실패, Executor가 admission을 건너뛰면 1 실패.

| 항목 | 결과 |
|---|---|
| `tests/test_breaker.py` + Executor 4개 파일 (HARNESS_INTEGRATION=1, PG 격리 스키마) | 90 passed |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 961 passed, 313 skipped (162s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 실제 모델 호출·자식 프로세스 kill·재시작·시계 변경을 포함한 Windows/Linux/WSL 실측은 하지 않았습니다. 예약 TTL은
  durable 시각 기준이며 holder 프로세스 생존을 직접 확인하지 않습니다(lease 만료·TTL·결과 도착은 각각 별개 이벤트로 기록).
- 정책의 Git 정의 파일과 인증된 변경 이력(사용자 승인 토큰)은 이 PR 범위 밖입니다. `update_policy`는 revision을 받아
  검증·저장·read-back만 합니다.
- 차단기 상태는 admission 전용입니다. SDD 인수·모델 자격 이전·배포 승인의 근거가 아니며(`inspect().authority`), FA-019의
  사용량 원장·FA-018 완료 권위와는 분리된 토픽입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

# 모델 호출은 타입이 있는 요청, 예약된 시도, 실측으로 분류된 결과다

기존 FA-019 / GitHub [#20](https://github.com/trevi00/zeus/issues/20) / `ZEUS-15c0d970315a` 개정 1의 구현·검증 기록입니다.
상류 provider 5개의 공동 검토([resolution](../../../full-analysis/baldrix-providers-001/resolution.md))에서 CLI 경로가
`max_tokens`/`temperature`를 조용히 버리고, 응답 모델 필드가 요청 라벨이며, rc0 빈 stdout이 정상 응답이 되고, usage
`None`이 0으로 소비되며, registry 조회 성공이 backend 없이도 인스턴스를 돌려주고, `call_budget_sec`가 읽히지 않는
선언 필드라는 사실이 확인됐습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus의 모델 호출은 `adapters/app_server.AppServer.run`(Codex app-server 프로토콜) 하나이며, Executor가 `model`·
  `timeout`·`outputSchema`·`read_only`만 넘깁니다. 지금까지는 어떤 옵션을 지원하는지, 결과가 무엇을 증명하는지, 사용량이
  어디서 왔는지가 계약으로 적혀 있지 않았고, 호출 전 예약도 없었습니다.
- `domain/invocation.py` (stdlib만):
  - `SUPPORT` 지원 행렬(transport별 supported/unsupported)과 `parse_request()`. 모르는 옵션·미지원 옵션(`system`,
    `temperature`, `max_output_tokens`, `response_format`)은 실행 전에 이름을 들어 거절합니다(무시 없음). 잘못된 타입/값
    (빈 model, 0·NaN·문자열 timeout, 빈 schema, 비bool read_only)도 거절합니다.
  - `availability(probe)`: 실행 파일 없음/발견/버전 확인만 구분하고 `model_ready='unknown'`, `qualified=False`를 고정합니다.
    registry/probe 성공은 모델 가용성이나 자격이 아닙니다.
  - `classify_result()`: 관측된 것으로만 결과를 이름 붙입니다 — `accepted`, `empty_answer`, `invalid_output`(rc0 빈 출력·
    깨진 JSON·schema 불일치), `tool_only`, `interrupted`, `inspection_blocked`, `provider_failure`. 빈 답은 수용이 아닙니다.
  - `usage_record()`: `thread/tokenUsage/updated` 이벤트가 있을 때만 `source`와 `basis`(`total`/`last_only`)를 붙여
    계수하고, 없으면 `unknown`(총합 `None`)입니다. 0으로 바꾸지 않습니다. `requested_model`(우리가 요청한 것)과
    `confirmed_model`(transport가 이벤트로 보고한 것; 없으면 `None`, `model_confirmation='unknown'`)을 분리하고, 원본
    이벤트 스트림 해시(`stream_hash`, 대리쌍 보존)를 남깁니다.
- `application/invocation_ledger.py`: `InvocationLedger`.
  - `reserve(lease, request, budget_seconds, guard, stage)`: 현재 소유권(`Workflow._owned`)을 **같은 트랜잭션**에서
    다시 증명한 뒤 (bucket, task, generation, attempt, invocation 순번) 행을 만듭니다. 한 시도는 열린 예약을 하나만 갖고,
    열린 예약 수가 `POLICY.max_active_executions`에 닿으면 거절합니다(읽히는 예산). 이전 시도의 미정산 예약은 새 시도가
    예약할 때 `unsettled_unknown`(usage unknown)으로 닫힙니다.
  - `settle(id, outcome, usage)`: 멱등, 다른 결과로의 재정산은 거절, usage는 출처를 명시해야 하고 unknown은 계수를 가질 수
    없습니다. `abandon(id, reason)`: 예외/timeout 경로에서 usage unknown으로 닫습니다. `summary()`는 unknown을 측정 합계에서
    제외해 따로 셉니다.
- `adapters/executor.py`: 호출 전에 `parse_request` → `reserve`(lease가 있을 때), transport가 예외를 내면 `abandon`,
  결과가 오면 `result['invocation'] = {request, outcome, usage, reservation}`를 증거에 넣고 `settle`. 시간 예산은 기존
  `remaining_seconds`를 그대로 전달합니다.
- `docs/contracts.md`: `INV-INVOCATION-001` 추가.

## 재현과 검증

- `tests/test_invocation_ledger.py`(11 검사; 원장 검사는 MemoryStore + 이 PC의 PostgreSQL 일회용 스키마):
  - 지원 행렬: `temperature`/`max_output_tokens`/`top_p` 등을 이름을 들어 거절, 타입/값 8종 거절, 모르는 transport 거절.
  - probe → 어떤 경우에도 `model_ready='unknown'`, `qualified=False`.
  - 결과 분류 7종(실제 `replay` 프로토콜 픽스처의 정상/빈 출력 포함), usage unknown 보존·`total`/`last_only` 근거,
    문자열 토큰 수 거절, transport가 보고한 모델만 `confirmed_model`, 스트림 해시 결정성.
  - 예약: stale 소유자는 같은 트랜잭션에서 거절되고 행이 남지 않음; 한 시도에 열린 예약 하나; 용량 초과 거절 후 정산하면
    허용; 같은 시도의 다음 stage는 invocation 2.
  - 정산 멱등/충돌 거절/알 수 없는 outcome 거절/unknown+계수 거절; lease 만료 후 재claim(attempt 2)이 예약하면 이전
    예약은 `superseded_by_new_attempt`로 unknown 종료; `abandon` unknown; summary가 unknown 3·측정 42를 분리.
  - 동시 예약 8스레드(용량 1): 정확히 1개만 열리고 나머지는 거절, 행 1개 — 검사와 쓰기가 한 트랜잭션.
  - Executor 배선: 가짜 transport가 실행되는 **동안** 예약 상태가 `reserved`, 끝나면 `settled/accepted`, 증거 아티팩트에
    `invocation` 블록과 요청 모델; transport가 `OSError`를 내면 `unsettled_unknown`(`exception:OSError`) + usage unknown.
- 기존 Executor 검사(`test_execution_output`, `test_executor_research`, `test_model_routing`, `test_context_recovery`)
  87 passed — 단계별(collect/shortlist/detail/final) 호출이 각각 예약·정산됩니다.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`): unknown usage를 0으로 읽으면 1 실패, 용량
  검사를 끄면 2 실패, Executor가 예약하지 않으면 2 실패.

| 항목 | 결과 |
|---|---|
| `tests/test_invocation_ledger.py` + Executor 4개 파일 (HARNESS_INTEGRATION=1, PG 격리 스키마) | 87 passed |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 957 passed, 313 skipped, 1 failed — 실패는 이 변경과 무관한 간헐 실패 `test_github_tickets…manual_close[memory]`(cp949 디코딩 경합; 단독 재실행 통과) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 실제 Codex app-server/모델 호출, Windows/Linux/WSL 설치 형태·Unicode·경로 공백·cmd/bat·프로세스 종료, SDK 내부
  재시도, vendor 옵션·모델 ID의 공식 규격 대조는 이번에 실행하지 않았습니다. `confirmed_model`은 transport가 이벤트에
  모델을 실을 때만 채워지며 현재 픽스처에서는 `unknown`입니다.
- Astra→Sol→Terra 자격 이전(동일 시나리오·환경·guardrail revision의 독립 실측과 사람이 정한 수용 기준)은 이 원장이
  제공하는 실측 회계의 **소비자**이지 이번 변경의 일부가 아닙니다. INV-MODEL-001의 "미자격은 Astra"는 그대로입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

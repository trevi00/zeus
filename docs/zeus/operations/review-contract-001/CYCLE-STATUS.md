# `zeus cycle status` 운영자 예제

review-contract-001의 작은 실제 canary. 운영자가 로컬 cycle의 예산 상태를 읽는 방법만 다룬다. 런타임 변경은 없다.

## 명령

```text
zeus cycle status <cycle-id>
```

## 대표 출력 (예시)

아래 JSON은 **설명용 예시**이며 실제 실행 영수증이 아니다. 시각·id·correlation은 임의 값이다.

```json
{
  "id": "review-contract-001",
  "correlation_id": "improvement:review-contract-001",
  "max_executions": 2,
  "executions": 2,
  "status": "awaiting_operator",
  "in_flight": null,
  "stopped_reason": null,
  "last_execution": {
    "agent": "lead:improvement",
    "kind": "decision",
    "id": "decision-example",
    "status": "succeeded",
    "claimed": true,
    "result_id": "decision-example",
    "at": "2026-09-16T00:00:00+00:00"
  },
  "created_at": "2026-09-16T00:00:00+00:00",
  "updated_at": "2026-09-16T00:00:00+00:00",
  "remaining_executions": 0
}
```

## 읽는 법

- `remaining_executions`는 `max(0, max_executions - executions)`로 CLI가 출력 시점에 계산하는 표시 값이다. 저장된 `local_cycles` 행에는 기록되지 않는다.
- `remaining_executions`는 **예산 여유**이지 실행 허가가 아니다. 값이 0보다 커도 cycle의 `status`가 `active`가 아니면 `cycle step`은 실행하지 않고 `action: none`을 돌려준다.
- `stopped` 또는 `awaiting_operator` 상태의 cycle은 자동으로 재실행되지 않는다. 다음 조치는 운영자가 결정한다. `stopped`이면 `stopped_reason`을 먼저 확인한다.
- `executions`는 executor 시작 시점에 durable하게 증가하며 재기동 후에도 유지된다. 같은 id로 `cycle start`를 다시 호출하면 같은 policy는 기존 행을 그대로 돌려주고, 다른 policy는 거절된다. 재기동으로 예산이 초기화되거나 늘어나지 않는다.
- `executions`가 `max_executions` 이상인 `active` cycle에서 실행 후보가 있으면 `cycle step`은 `budget_exhausted`로 정지하고 실행하지 않는다.
- `in_flight`가 null이 아니면 다른 프로세스가 남긴 마커이다. `cycle step`은 이를 해제하지 않고 `in_flight_residue`로 거절한다.

## 검증

- `python -m pytest tests/test_cycle_remaining.py -q`
- `python -m ruff check src/codex_harness/cli.py tests/test_cycle_remaining.py`

전체 pytest(PG/Redis)와 CI는 Codex가 소유한다. 이 문서 canary는 위 집중 명령만 실행한다.

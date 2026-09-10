# 같은 키의 중복 검사와 기록은 한 트랜잭션이다

기존 FA-004 / GitHub [#5](https://github.com/trevi00/zeus/issues/5) / `ZEUS-6d62d42d9333` 개정 1의 검증·계약 기록입니다.
상류 `idempotency.once`는 `already_done` 검사 뒤 intent를 append하는데 검사와 기록이 단일 lock/CAS가
아니라서, 격리 프로브에서 같은 키를 두 실행이 모두 허용하고 이벤트 2건을 남겼습니다
([review-probes 영수증](../../../full-analysis/harness-lib/review-probes.receipt.json) `idempotency_concurrent_check_append`).
또 intent를 기록한 뒤 crash하면 영구 완료로 간주돼 작업이 빠질 수 있습니다. 교차검토 합의는 "PG 트랜잭션과
실행 멱등키, 외부 side effect lost-ack 별도 설계"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태

- 같은 키 중복 검사와 기록은 `Store.transaction()` 하나 안에서 일어나고, PostgreSQL은 제어면 advisory lock
  (`pg_advisory_xact_lock`)으로, MemoryStore는 RLock으로 트랜잭션 전체를 직렬화합니다(`adapters/store.py`).
  `record_incident`의 inbox 영수증, `Workflow.submit`의 task identity, `Workflow.handle`의 workflow_inbox,
  `fail`의 execution_failures, 복구 패킷 영수증이 모두 이 형태입니다.
- 외부 side effect는 두 형태로만 다룹니다: **intent 선기록 → 호출 → receipt 후기록**(outbox attempts;
  receipt 없는 intent는 pending이며 완료가 아님, [outbox-isolation-001](../outbox-isolation-001/README.md))과
  **외부 상태로부터 재조정**(GitHub PR은 head revision으로 재발견, 병합 불확실은 `blocked_remote`, 이미지는
  digest). 상류의 "intent 기록 = 완료" 해석은 Zeus에 없습니다.

따라서 런타임 코드는 바꾸지 않았고, 상류 결함 형태를 Zeus에서 **실제 다중 프로세스**로 재현해 어느 결속이
막는지 확인하고 계약으로 고정했습니다.

## 재현과 검증

- `tests/test_idempotency_races.py`: 이 PC의 PostgreSQL 원장 컨테이너에 일회용 스키마를 만들고, 연산마다
  **인터프리터 4개**를 동시에 출발시킵니다. 각 자식은 import를 마치고 `ready-<i>` 표식을 쓴 뒤 게이트를 기다리고,
  부모는 표식 4개를 모두 확인한 뒤에만 게이트를 엽니다(고정 sleep 없음). 상류 프로브의 barrier와 같은 위치에
  "트랜잭션 안 읽기 직후 0.4초 정지"를 둡니다. 실패 대조군은 여기에 더해 읽기 직후 `read-<i>` 표식으로
  **rendezvous**해 4개 모두 읽기를 마친 뒤에야 쓰기로 진행하므로 교차는 스케줄러가 아니라 검사가 고정합니다
  (advisory lock 경로에는 이 장벽을 넣지 않습니다 — 넣으면 lock 안에서 서로를 기다려 교착합니다). 시작 실패·
  assertion·timeout 어느 경우에도 `finally`에서 남은 자식을 모두 회수합니다(PR #38 검토 반례: 자식 하나의
  시작을 2.5초 늦추면 고정 sleep 방식은 대조군이 `[1,1,1,4]`가 됨).
  - 기본 store(advisory lock): 같은 원인의 서로 다른 occurrence 4건 → occurrences `1,2,3,4`, `hook_created`
    정확히 1회, hooks 1·outbox 1·incidents 4. 같은 task.assign 4회 제출 → 4개 결과 동일, task 1개. 같은
    agent claim 4회 → 정확히 1개만 lease. → `postgres-processes.json`
  - **실패 대조군**(프로브 전용 패치로 advisory lock 제거, 정지는 동일): 4건 모두 occurrences 1, hook 0 —
    두 번째 strike가 유실되는 상류와 같은 형태. 행 upsert는 키를 중복시키지 않지만 파생 결정이 틀립니다.
    → `unlocked-control.json`
  - MemoryStore 스레드 4개 + 같은 정지: 직렬화 확인(`record_incident`, `claim`).
- 기존 검사 `test_concurrent_second_strike_is_atomic`, `test_concurrent_flush_uses_committed_receipts`,
  `test_concurrent_controllers_claim_only_one_release`, `test_concurrent_same_packet_commits_one_decision`은
  스레드 수준 동일 결속을 이미 검사하며 그대로 통과합니다.
- `docs/contracts.md`: `INV-IDEMPOTENCY-001` 추가(단일 트랜잭션 검사+기록, 내구 identity 영수증, 외부 효과의
  두 형태, "receipt 없는 intent는 pending").

| 항목 | 결과 |
|---|---|
| `tests/test_idempotency_races.py` (PG 프로세스 4개 ×3 연산 + 대조군 + memory 스레드) | 4 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14, PG 검사는 skip) | 919 passed, 307 skipped (160s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 정지 0.4초와 rendezvous는 결정론적 교차를 위한 프로브 입력이며 실제 부하에서의 경쟁 빈도를 측정한 것은 아닙니다.
- 외부 시스템 자체의 중복(예: GitHub가 같은 head에 PR을 두 번 만드는 경우)은 그 시스템의 제약에 의존하며
  Zeus는 재발견으로만 대응합니다. Codex 실행 자체는 at-least-once이고 attempt·증거로 계수됩니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

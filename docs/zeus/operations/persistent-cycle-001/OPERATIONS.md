# persistent-cycle-001 운영 메모

`zeus cycle start/status/step`은 한 correlation에 대한 제한 실행 루프다. 기존 settings/프로필 환경을 그대로 쓴다.

```
zeus cycle start <cycle_id> --correlation <correlation_id> --max-executions <n>
zeus cycle status <cycle_id>
zeus cycle step <cycle_id>
```

- `start`는 `local_cycles` 행을 한 번 만든다. 같은 요청은 멱등, 다른 correlation/한도는 거절한다.
- `step`은 한 턴이다. 메시지 전달·원장 수락·outbox·ACK 후 executor를 최대 한 번 시작한다. 시작 전 슬롯을 증가시키고 `in_flight`를 기록한다. `max_executions`는 executor 시작 허용 횟수이며 청구 횟수가 아니다.
- 중단 사유(`stopped_reason`): `budget_exhausted`, `execution_<status>`, `exception:<Type>`, `execution_notice:<reason>`, `diagnose_pending`, `foreign_correlation`, `foreign_queue:<id>`, `in_flight_residue`, `no_execution_claimed`. 자동 재시도·증액은 없다.
- `awaiting_operator`: accepted review_lead 결과가 conductor에게 넘어간 상태. conductor 소비·병합·배포는 하지 않는다.
- `in_flight`가 남아 있으면 다른 step은 실행하지 않으며 자동 해제하지 않는다. 운영자가 원장을 확인한 뒤 수동으로 처리한다.
- 단위 시험의 executor/bus는 대역이며 실제 Claude/Codex 호출이 아니다. PG+Redis 경로는 Codex 격리 환경에서 독립 검증한다.

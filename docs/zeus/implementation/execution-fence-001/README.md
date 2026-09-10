# 실행 세대의 내구 fence 원장

기존 FA-003 / GitHub [#4](https://github.com/trevi00/zeus/issues/4) / `ZEUS-429c533aab0e` 개정 1의 구현입니다.
상류 파일 lease는 파일이 삭제되면 epoch를 1부터 다시 발급하고 guard가 owner를 비교하지 않아, 이전
소유자의 epoch 1 핸들이 새 lease를 통과했습니다([review-probes 영수증](../../../full-analysis/harness-lib/review-probes.receipt.json)
`lease_deleted_reissued_ABA`: old 1 / new 1 / 이전 핸들 guard·release 통과). 교차검토 합의는 "단조 fencing·owner·generation·CAS를
묶고 source 파일 lease는 직접 이식하지 않는다"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 남아 있던 틈

Zeus는 이미 PostgreSQL 트랜잭션 안에서 `id·generation·attempt·lease_owner·agent/actor·recovery_sequence`를
모두 비교하고(`Workflow._same_execution`), 실행자는 claim마다 `uuid4()` owner를 쓰며, 문서를 삭제하는
코드 경로가 없습니다. 그래서 "만료 후 재claim된 작업에 이전 holder가 개입"하는 상류 ABA는 그대로 재현되지
않았습니다. 남아 있던 틈은 상류와 같은 형태 하나입니다: **행이 사라졌다가(운영자 퍼지·부분 복원·우회 도구)
다시 만들어지면 generation이 0부터 재발급**되고, owner 문자열까지 같으면 이전 핸들이 다시 통과합니다.
아래 프로브의 `no_fence` 변형이 MemoryStore와 실제 PostgreSQL 양쪽에서 이를 재현했습니다.

## 변경

- `application/execution_fence.py`: 행과 별개로 살아남는 `execution_fences` 버킷. `advance(tx, bucket, id,
  generation, owner)`는 이전 fence보다 큰 generation만 허용하고, 손상된 fence(정수 아님)는 fail-closed로
  거부합니다. `require_unused`는 fence가 있는 identity의 재생성을 막습니다.
- `Workflow.submit`: 새 task를 만들기 전 `require_unused` — 퍼지된 identity의 재제출은 명시 거부.
- `Workflow.claim`·`Executor.decide_one`·`ReleaseQueue.claim`: generation을 올리기 전 `advance`. 후퇴하면
  그 행만 `ExecutionGenerationRegressed`로 차단(`block_execution`, release queue는 `failed`+사유)하고 다른
  작업은 계속 서빙합니다. `Workflow.cancel`·`ExecutionRecovery`의 generation 증가도 fence를 통과합니다.
- `docs/contracts.md`: `INV-EXECUTION-IDENTITY-001`에 내구 fence 문단 추가. 파일 lease는 이식하지 않습니다.

기존 행(fence 없는 레거시)은 첫 claim에서 fence를 만들며 동작이 바뀌지 않습니다. PG를 예전 덤프로 복원하면
fence도 함께 되돌아가므로 거짓 거부는 없고, 그 경우의 보호 범위는 덤프 시점까지입니다.

## 재현과 검증

- `probe.py` / `receipt.json`: 실제 `Workflow`로 (1) 만료된 holder가 재claim 뒤 heartbeat/complete/세대
  위조 시도, (2) 퍼지된 행을 generation 0으로 재생성하고 **같은 owner 문자열**로 claim. 변형은 `current`,
  `owner_blind`, `generation_blind`, `no_fence`(프로브 안 패치, 배포 코드 아님). MemoryStore와 이 PC의
  실제 PostgreSQL(일회용 스키마, 운영 테이블 미접촉) 각각 실행.
  - `current`: 8개 시도 모두 거부. 재생성된 행은 `ExecutionGenerationRegressed`로 차단.
  - `owner_blind`/`generation_blind`: 여전히 전부 거부 — `attempt`가 generation·owner와 함께 움직이므로
    비교 하나를 빼도 ABA가 열리지 않습니다(결속은 셋의 논리곱).
  - `no_fence`: 재제출 **수락**, 재생성 행 claim이 **generation 1·attempt 1로 수락**, 이전 첫 holder의
    heartbeat **수락** — 상류 epoch 1 재발급과 같은 결함이 Zeus에서도 fence 없이는 재현됩니다.
- `tests/test_execution_fence.py`(memory + postgres 매개변수, 8 검사): 실제 lease 만료(1초) 후 재claim과
  4종 stale 핸들의 heartbeat/complete/fail 거부와 무흔적, 퍼지 후 재제출 거부·우회 재삽입 행 차단·정상 작업
  계속 서빙, cancel의 fence 전진과 손상 fence fail-closed, release 컨트롤러 잠금 만료·재claim·행 재생성,
  decisions_pending 재생성 차단(`Executor.decide_one`). PostgreSQL 변형은 이 PC의 원장 컨테이너에
  격리 스키마로 실행했습니다.
- 기존 `tests/test_execution_identity.py`(실제 자식 프로세스·PG)와 `test_retry_state` 등 generation 의존
  검사는 그대로 통과합니다.

| 항목 | 결과 |
|---|---|
| `tests/test_execution_fence.py` memory+postgres (`HARNESS_INTEGRATION=1`) | 8 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14, PG 변형 skip) | 922 passed, 308 skipped (173s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- fence는 같은 데이터베이스 안의 원장이라 DB 전체 삭제·구버전 복원에는 함께 되돌아갑니다. 그 경계는
  `INV-RECOVERY-001`/호스트 복구 증적(#18)의 범위입니다.
- 다중 호스트에서 같은 원장을 쓰는 구성은 검증하지 않았습니다(현재 사용 범위는 단일 PC).
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

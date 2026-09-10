# 실행 진행 기록의 세대·순서·두 시각·손상 원문 보존

기존 FA-016 / GitHub [#17](https://github.com/trevi00/zeus/issues/17) / `ZEUS-e36daeb984c1` 개정 1의 구현입니다.
고정 Baldrix engine001의 pane 로그 병합기를 격리 실행하면 gen2 running 정본에 과거 gen1 exited shard를 병합했을 때 최종
상태가 gen1 exited로 **역행**했고, 병합기는 원래 발생 시각을 버리고 병합 시각을 부여해 replay가 timestamp 기준으로 상태를
덮었습니다. `not-json`만 있는 shard는 병합 0건으로 보고되고 **삭제**돼 조사할 손상 원문이 사라졌습니다
([engine-001 공동 검토](../../../full-analysis/baldrix-engine-001/resolution.md), [관측 stdout](../../../full-analysis/baldrix-engine-001/components-UTC0.stdout.txt)).
교차검토 합의는 "Zeus PG runtime 원장에 task/attempt/pane generation과 고유 event ID, 발생 순서, 발생 시각과 수집 시각을
분리해 결속"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus 상태와 변경

Zeus의 실행 진행 기록(`execution_progress`)은 lease 소유 검사 아래에서만 쓰여 이전 세대의 실행자가 덮어쓸 수는 없었지만,
레코드에 세대·시도·순번이 없었고 시각은 수집 시각(`at`) 하나뿐이었으며, 런타임 이벤트가 dict가 아니면 `event.get`에서
예외로 실행이 끊겼습니다(원문 보존 없음).

- `adapters/executor.py` `observe()`:
  - 레코드에 `generation`/`attempt`(현재 lease), 레코드별 `sequence`(단조 증가), `event_id`(런타임 item 신원 또는 보관
    바이트 참조), `occurred_at`(이벤트 자체의 `completedAtMs`/`emittedAtMs`, 없으면 **null** — 수집 시각으로 대체하지
    않음), `collected_at`을 기록합니다. `last_completed`에도 `sequence`와 `occurred_at`을 넣습니다.
  - dict가 아니거나 `params`가 매핑이 아닌 이벤트는 원문(repr)을 `runtime-event` 아티팩트로 보관하고 `malformed_events`
    카운트와 `malformed_recent` 참조에 남기며, 정상 상태(`sequence`, `last_completed`)는 건드리지 않습니다.
  - 모듈 함수 `progress_occurrence`, `progress_event_id`로 규칙을 분리했습니다.
- `docs/contracts.md`: `INV-EXECUTION-IDENTITY-001`에 진행 기록 결속 문단 추가.

## 재현과 검증

- `tests/test_execution_progress.py::test_progress_records_generation_sequence_identity_and_two_clocks`: fixture 런타임이
  완료 이벤트(발생 시각 포함), 토큰 사용량, 문자열 shard, `params: 'garbage'` 이벤트, 발생 시각 없는 완료, 무관 이벤트를
  순서대로 보내면 — `generation=1/attempt=1`, `sequence=3`(손상·무관 이벤트는 순번을 올리지 않음), 손상 2건은 원문 보관과
  카운트, 마지막 완료의 `occurred_at=None`, 첫 이벤트의 발생 시각은 ms 값에서 UTC로 복원.
- `::test_stale_generation_cannot_write_progress_and_replay_keeps_order`: 세대 2가 발생 시각이 역순인 두 이벤트를 기록하면
  도착 순서가 `sequence`이고 더 이른 발생 시각은 데이터로 남음; 만료된 세대 1 lease로 실행하면 `Stale or expired`로
  거부되고 진행 기록은 바이트 단위로 불변.
- 기존 `test_project_skills`·`test_execution_output`·`test_context_recovery` 통과.
- 음성 대조: `executor.py`를 수정 전으로 되돌리면 두 검사가 실패합니다(문자열 shard에서 AttributeError).

| 항목 | 결과 |
|---|---|
| `tests/test_execution_progress.py` + 실행자 관련 3개 모듈 | 54 passed, 8 skipped |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 919 passed, 305 skipped (187s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이는 실행자 프로세스 안의 진행 기록입니다. 여러 pane/프로세스의 로그를 하나로 병합하는 상류 형태의 병합기는 Zeus에 없고
  만들지 않았습니다; 모든 진행은 lease 아래 단일 작성자입니다.
- 실제 Codex 앱 서버 이벤트의 시각 필드 이름(`completedAtMs`, `emittedAtMs`)은 기존 훅 매니페스트 fixture에서 관측한 것이며
  운영 버전 변화는 별도 확인 대상입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

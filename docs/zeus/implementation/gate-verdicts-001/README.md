# 게이트 판정의 문장 귀속·PARTIAL·철회 — 하나의 fold

기존 FA-013 / GitHub [#14](https://github.com/trevi00/zeus/issues/14) / `ZEUS-fb2ab61807b4` 개정 1의 구현입니다.
상류 harness에서 judge/residual CLI는 문장별 판정을 쓰지만 `_external_verdict`는 stage+mode 최신값만 소비했고,
PARTIAL은 gate_runner/residual에서 대기인 반면 tick은 None만 대기로 분류했으며, retraction 필터와 외부 판정 소비,
컴팩션 뒤 render 원본, ERROR 뒤 completed 유지, 종료 코드 무시, 빈 검사 모집단이 갈렸습니다
([판정 소비 공동 검토](../../../full-analysis/harness-gate-consumer-joint/resolution.md)). 교차검토 합의는 "고정 문장 ID와
run/cycle·정의·산출물·환경에 판정을 결속하고 해당 판정만 소비, 공통 미종결 상태, 모든 소비의 동일 view와 replay 등가,
ERROR의 유효성 철회, 종료 상태 검증, 계획한 필수 검사 분모"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus 상태와 변경

Zeus SDD는 8단계 보고서가 전부 `blocked`이고 `advance`는 blocked만 기록했습니다. 판정을 문장 단위로 받는 계약 자체가
없었으므로 위 불일치는 "아직 없음"이었고, 이번에 계약과 소비 경로를 만들었습니다.

- `domain/gate_verdicts.py`(신규, 표준 라이브러리만):
  - `GateVerdict(statement_id, stage, run_id, cycle, definition_hash, artifact_hash, environment_hash, verdict, origin,
    receipt_ref, exit_status, actor, authority, sequence, retracts)`. `runner_receipt`는 불변 영수증 참조와 프로세스 종료
    코드를 요구하고 **0이 아닌 종료는 PASS일 수 없음**; `reviewer_decision`은 actor와 authority
    (`authenticated_provider | unauthenticated_claim`)를 요구하며 **미인증 주장은 문장을 종결하지 못함**(pending).
    `RETRACT`는 같은 문장의 살아 있는 판정 하나만 지목하고 actor를 남깁니다.
  - `fold_verdicts(verdicts, statements, run_id, cycle)`: 계획한 문장→정의 해시 맵이 **분모**라 판정 없는 문장은
    `not_run`으로 남고, 다른 run/cycle/정의의 판정은 `foreign`으로 세고 무시하며, 철회된 판정은 제거하고, 문장별 최신
    판정이 이깁니다. ERROR→`error`(이전 PASS 철회), PARTIAL→`pending`, FAIL/REJECT→`failed`, PASS→`passed`.
    `complete`는 모든 문장이 passed일 때만.
  - `compact()`: 철회 쌍을 제거한 view. 테스트로 `fold(compact(events)) == fold(events)`를 고정합니다(replay 등가).
- `application/sdd.py`:
  - `statement_definitions(row, stage)`: 단계 검사 이름을 spec_hash에 결속한 정의 해시(스펙 개정이 바뀌면 이전 판정은 foreign).
  - `record_gate_verdict(iteration_id, document)`: run_id=반복 ID, cycle=스펙 revision, sequence=저널 순번, 정의 해시는
    서비스가 채웁니다(호출자가 다른 정의를 주장할 수 없음). 영수증은 아티팩트에서 검사하고 해시 체인 이벤트
    `gate_verdict_recorded`로 남깁니다. `authenticated_provider`는 결정 제공자가 설정된 경우에만 허용됩니다(현재 없음).
  - `status()`에 단계별 `gates`(fold) 추가, `request_advance()`는 같은 fold를 소비해 문장별 상태로 차단 사유를 씁니다.
    사람 인증 제공자가 없으므로 `human_*` 문장은 통과할 수 없고 전이는 여전히 blocked이지만, 이제 **무엇이 not_run/
    pending/error인지** 기록합니다.
- `docs/contracts.md`: `INV-GATE-001` 추가.

## 재현과 검증

- `tests/test_gate_verdicts.py`: 문장 귀속과 분모(`not_run`), 다른 run/cycle/정의의 foreign 계수, ERROR의 PASS 철회·
  PARTIAL 대기·최신 우선, 철회와 컴팩션 fold 동일성·잘못된 철회 거부·중복 순번 거부, 종료 코드/영수증/리뷰어 권한 규칙,
  알 수 없는 필드(`human_approved`) 거부; 애플리케이션: 실제 스펙 등록 → 판정 기록 → `status.gates` → `advance`가
  문장별 사유로 차단 → 뒤늦은 ERROR가 모든 읽기 경로에서 PASS를 철회 → 미인증 리뷰 주장은 pending, 인증 권한은 제공자
  없이는 거부, 단계 밖 문장·비0 종료 PASS·없는 영수증·잘못된 철회 거부.
- 기존 `test_sdd.py`(PG 검사 제외) 통과. 저널 해시 체인 검사(FA-007)는 판정 이벤트에도 그대로 적용됩니다.
- 음성 대조: `application/sdd.py`를 수정 전으로 되돌리면 애플리케이션 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| `tests/test_gate_verdicts.py` + `test_sdd.py` + `test_architecture.py` | 18 passed, 6 skipped(PG) |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 923 passed, 305 skipped (200s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이 계약은 **판정의 기록과 소비**입니다. 실제 8단계 전이, 인증된 사람 결정 제공자, 러너가 영수증과 함께 판정을 자동
  기록하는 경로, 알파/라이브 배포 결속은 별도 구현이며 전이는 여전히 blocked입니다(교차검토: "blocked만 계속 반환하는
  것은 목표 달성이 아니다").
- 시도·재개방의 수명과 예산(한도·재시도 항목), 면제(waiver)의 별도 검증은 이번 계약에 없습니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

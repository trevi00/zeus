# 완료 판정은 실제 평가 실행·대상·시도에 결속된 증거다

기존 FA-018 / GitHub [#19](https://github.com/trevi00/zeus/issues/19) / `ZEUS-07f94a1a4390` 개정 1의 구현·검증 기록입니다.
상류 completion helper의 격리 실측([resolution](../../../full-analysis/baldrix-completion-authority-001/resolution.md))에서
`schema_version=null`·무관한 event·caller `ts`·`completeness=false`가 붙은 approved 기록이 저장·선택됐고, NaN
timestamp/floor도 approved였으며, pure gate는 문자열 `"false"`를 참으로 소비했습니다. verdict와 timestamp만 보는
selector로는 실제 평가 대상·시도·검사 분모를 증명할 수 없다는 것이 공동 검토 결론입니다. 새 이슈나 분석 후보는 추가하지
않았습니다.

## Zeus의 현재 상태와 변경

- Zeus에서 task의 `succeeded`는 `Workflow.complete`가 남기는 **실행자 자기보고**이며, 지금까지 그 이상의 완료 권위 개념은
  없었습니다. 이번 변경은 그 자기보고를 권위로 승격하지 않고, 별도 원장으로 **결속된 완료 판정**을 도입합니다.
- `domain/completion.py` (stdlib만): 닫힌 스키마 `parse_verdict`. 정확한 키 집합, `schema_version == 1`, `event ==
  completion.verdict`, verdict ∈ {approved, iterate, escalate}(문자열 `"false"`·배열 거부), `target`(task/generation/attempt
  양의 정수, bool 거부), `spec_revision` 40-hex, `evaluation_artifact` `sha256:`, `runner_receipt`(id·digest, target과
  동일해야 함 — cross-target은 caller 플래그가 아니라 영수증에서 도출), `reviewer`(actor, kind ∈ model/human),
  `scenarios`(expected/passed/excluded; excluded는 사람 승인자·revision·이유 필수), `observed_at`(aware ISO 문자열만;
  숫자·NaN·naive·미래 거부), 64KiB 상한. 완료(`complete`)는 expected가 비어 있지 않고 모두 passed 또는 승인된 excluded일
  때만 참입니다. identity는 observed_at을 제외한 전체 내용의 digest입니다.
- `application/completion.py`: `CompletionAuthority`.
  - `record()`: 파싱 실패는 `completion_rejections`에 구조화 알림(사유·발췌·task)으로 남기고 예외를 올립니다. 같은 잘못된
    기록의 재전송은 같은 알림 행에 떨어져 부풀지 않습니다. 유효한 기록은 같은 트랜잭션에서 `tasks` 행을 읽어 현재
    generation/attempt와 같은지 확인하고(다르면 거절), task별 기록 순서 `sequence`를 붙여 `completion_verdicts`에 넣습니다.
    같은 identity 재전송은 원래 행과 sequence를 그대로 돌려줍니다(timestamp를 바꿔도 재정렬 없음).
  - `inspect(task_id, spec_revision, evaluation_artifact)`: 상태를 이름으로 구분합니다 — `unreadable`(store 예외),
    `no_ledger`(task 없음), `corrupt`/`partially_corrupt`(저장 행이 닫힌 스키마를 다시 통과하지 못함; 부분 손상도 권위
    없음), `rejected_only`, `not_evaluated`, `stale`(현재 실행·spec·artifact에 결속된 판정 없음), `not_approved`(최신이
    iterate/escalate), `incomplete`(분모 미충족), `not_succeeded`(실행자 자기보고 전), `authoritative`. 최신은 observed_at이
    아니라 sequence의 최댓값입니다.
  - `require_authority()`: `authoritative`가 아니면 `No completion authority: <state>`로 거절합니다.
  - dispatch/승격 경로는 아직 이 원장을 읽지 않습니다(이슈 Rollback: "자격 검증 전 비활성"). 소비자가 명시적으로 옵트인합니다.
- `docs/contracts.md`: `INV-COMPLETION-001` 추가.

## 재현과 검증

- `tests/test_completion_authority.py`(17 검사, MemoryStore + 이 PC의 PostgreSQL 일회용 스키마):
  - 잘못된 기록 21종 + cross-target 영수증이 모두 구조화 오류로 거절되고, 원장에는 아무것도 들어가지 않으며, 재전송해도
    알림 행 수가 22에서 늘지 않음(`rejected_only`).
  - `succeeded` 자기보고만으로는 `not_evaluated`; 모르는 task는 `no_ledger`.
  - 현재 generation보다 앞선 판정은 기록 거절; 승인 후 `not_succeeded` → complete 후 `authoritative`; 다른 spec/artifact로
    물으면 `stale`; 같은 시나리오 문구라도 다른 spec은 다른 identity.
  - lease 만료 후 재claim(gen 2)되면 gen 1 판정은 `stale`, 늦게 도착한 gen 1 판정은 거절, 같은 gen 1 판정 재전송은 멱등.
  - 뒤늦게 기록된 더 이른 observed_at의 iterate가 최신 → `not_approved`; 옛 approved를 timestamp만 바꿔 재전송해도 seq 1
    그대로이고 거절 유지(FA-005 형태); 같은 초의 판정은 sequence로 선택.
  - 빈 분모·부분 통과는 `incomplete`; 사람 승인 exclusion이 있으면 완료.
  - 같은 판정 8회 동시 기록(스레드 4) → 행 1개·seq 1; 저장 행 내용을 바꾼 뒤 재전송은 `identity reused` 거절.
  - MemoryStore 행 손상 → `corrupt`, 유효 행 추가 후 `partially_corrupt`; **실제 PG**에서 `UPDATE documents`로
    `observed_at: 200` 주입 → `corrupt`, `reviewer` 키 삭제 → `partially_corrupt`; 닿지 않는 DSN → `unreadable`
    (`require_authority`도 거절).
  - 이름 붙인 11개 상태가 모두 검사에서 도달됨.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`): 모듈 제거 → 수집 오류; `latest()`를 observed_at
  정렬로 바꾸면 순서 검사 2건 실패; `record()`의 generation/attempt 결속을 끄면 결속·재claim 검사 4건 실패.

| 항목 | 결과 |
|---|---|
| `tests/test_completion_authority.py` + `test_architecture` (HARNESS_INTEGRATION=1, PG 격리 스키마) | 21 passed |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 959 passed, 318 skipped (177s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이 기록의 runner receipt·evaluation artifact·reviewer는 픽스처 값입니다. 실제 evaluator provider 실행, hook host, 사람
  시나리오 인수, Linux/WSL 실행은 하지 않았고 대체하지도 않았습니다(이슈 AC의 실제 실행 항목은 미충족으로 남김).
- `spec_revision`·`evaluation_artifact`가 실제 Git/아티팩트 저장소에 존재하는지는 이 원장이 확인하지 않습니다(형식만).
  존재·불변성 확인은 소비자가 아티팩트 저장소와 함께 해야 합니다.
- 완료 권위를 실제로 소비하는 dispatch/승격/학습 자격 경로 연결은 자격 검증 뒤의 별도 단계입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

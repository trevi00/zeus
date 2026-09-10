# 최신 판정이 이전 PASS를 이긴다 — 연구 채택 승인 철회

기존 FA-005 / GitHub [#6](https://github.com/trevi00/zeus/issues/6) / `ZEUS-f550e11eb0c4` 개정 1의 구현입니다.
상류 `derive_state`는 `fold_latest_verdicts`가 PASS/FAIL만 소비해서 PASS 뒤 ERROR가 와도 `derive_completed`가
과거 PASS를 유지했고, stage-state(FAILED)와 completed 집합의 의미가 갈렸습니다([harness-lib review](../../../full-analysis/harness-lib/review.md)
`derive-state`, [review-probes 영수증](../../../full-analysis/harness-lib/review-probes.receipt.json) `derive_PASS_then_ERROR`).
교차검토 합의는 "최신 판정·revision·ERROR/PARTIAL/REJECT를 읽기 경로 전체에서 일관 처리"입니다. 새 이슈나
분석 후보는 추가하지 않았습니다.

## Zeus 읽기 경로 점검

Zeus는 이벤트 fold 대신 행마다 현재 status를 저장하므로 대부분의 경로는 최신 상태를 그대로 읽습니다.

| 읽기 경로 | PASS 뒤 실패의 처리 | 근거 |
|---|---|---|
| 릴리스 검증 `Releases.verify` | 검사 하나라도 실패면 `rejected`, 승격 거부 | `test_release_runner`, `test_release_health` |
| 작업 시도 `attempt_outcomes` / 측정 | 첫 시도와 최종 결과를 분리 계수, 시도 이력 손상은 unknown | `test_measurements` |
| 역공학 진행 `ReverseProgress` | 완료 stage는 불변(같은 source), source 변경 시 명시 rebaseline | `test_reverse_progress` "immutable" |
| 실행 fence `_owned` | 만료·재claim 뒤 이전 holder 거부 | `test_execution_identity` |
| **연구 채택 `require_adoption`** | **결함**: 승인 뒤 도착한 거절 리뷰를 무시 | 이번 수정 |

`Research.review()`는 `accepted=False` 리뷰를 저장만 하고 같은 binding의 `research_approvals`를 그대로 두었고,
`require_adoption`은 승인 시점에 묶인 **승인** 리뷰 목록만 재검사했습니다. 그래서 conductor나 lead:research가
같은 binding을 나중에 거절해도 `coverage()['adoption_eligible']`가 True로 남고 plan/implement 작업이 계속
제출·claim됐습니다 — 상류의 "PASS 뒤 ERROR 무시"와 같은 형태입니다.

## 변경

- `application/research.py`: 리뷰 레코드에 binding·actor별 `sequence`와 `at`을 붙입니다. 거절 리뷰가 승인된
  binding에 도착하면 승인을 `status: revoked`(+`revoked_by`, `revoked_at`)로 바꾸고 리뷰 자체는 보존합니다.
  재승인 시 이전 철회 이력을 `revocations`에 남깁니다.
- `application/audit_gate.py::require_adoption`: `status != approved`면 거부하고, 승인에 묶인 각 actor에 대해
  같은 binding의 **최신 리뷰**(sequence, at)가 accepted인지 다시 검사합니다. 상태 플래그가 유실돼도 최신
  리뷰 규칙만으로 거부됩니다. 레거시 승인(status 없음)은 approved로 읽되 최신 리뷰 규칙은 동일 적용됩니다.
- **검토 반례 반영(PR #39 P1)**: 승인 → 거절(seq 2) 뒤 **같은 승인 리뷰 객체를 재전송**하면 같은 digest 레코드가 seq 3으로
  덮여 최신 거절이 뒤집혔습니다. 이제 이미 기록된 review digest의 재전송은 멱등(원래 sequence·시각 유지, 승인 상태 불변)
  이고, 재승인은 새 inspection 영수증(새 execution_id)에 결속된 새 리뷰로만 가능합니다.
- `docs/contracts.md`: `INV-RESEARCH-004`에 "리뷰는 binding·actor별로 순서가 있고 승인 뒤 거절은 승인을 철회하며
  최신 리뷰가 판정" 문장 추가.

## 재현과 검증

- `tests/test_research_audits.py::test_later_rejecting_review_revokes_approval[conductor|lead:research]`: 실제
  fixture 감사 흐름으로 승인 → `adoption_eligible` True → 같은 task·receipt로 거절 리뷰 → eligible False, 승인
  `revoked`, `require_adoption`이 `approval revoked`로 거부, 상태 플래그를 지워도 `rejected by a later review`로
  거부, plan 작업 제출이 `Research adoption deferred`로 거부. 승인 리뷰 레코드는 삭제되지 않습니다.
- `::test_rejection_then_acceptance_orders_by_sequence_not_existence`: 거절(seq 1) → 승인(seq 2)은 채택 가능,
  그 뒤 lead의 거절은 다시 철회 — 존재가 아니라 순서가 판정입니다.
- 음성 대조: `research.py`/`audit_gate.py`를 수정 전으로 되돌리면 위 3건이 실패함을 확인했습니다.
- `::test_replaying_an_old_acceptance_never_overturns_a_later_rejection`: PASS → REJECT → 동일 PASS 재전송은 원래 seq 1
  레코드를 그대로 돌려주고 승인은 revoked 유지; 새 영수증의 새 리뷰(seq 3)만 재승인.
- 기존 `test_research_audits.py` 69건은 그대로 통과합니다(총 73 passed).

| 항목 | 결과 |
|---|---|
| `tests/test_research_audits.py` | 73 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 920 passed, 305 skipped (164s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 철회된 binding의 재승인은 같은 decisions_pending 키가 이미 소비돼 새 리뷰 결정이 자동으로 큐잉되지 않습니다.
  새 증거로 binding이 바뀌면 새 키가 생깁니다. 같은 binding의 재심 경로는 별도 설계 대상입니다.
- 실패한 inspection **영수증**(증거)이 나중에 추가되는 경우는 판정이 아니라 증거이므로 이번에 승인을 철회하지
  않습니다. 승인에 묶인 영수증이 바뀌면 기존 `changed independent inspection` 규칙이 거부합니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

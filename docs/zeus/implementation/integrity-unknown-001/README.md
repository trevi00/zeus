# 알 수 없음은 건강이 아니다 — 유실 참조 보고와 사이드카 강등 금지

기존 FA-007 / GitHub [#8](https://github.com/trevi00/zeus/issues/8) / `ZEUS-2dd28a919f60` 개정 1의 구현입니다.
상류 Guardian `ledger_seal.verify`는 봉인 구간 개서를 TAMPER로 판정하지만, 신규 `.compacted` 사이드카가 하나
있으면 그 파일의 정당한 compaction 관계를 검증하지 않은 채 RESEAL_REQUIRED로 강등했고, CLI의 UNSEALED는 rc 0,
watchdog은 TAMPER만 소비하며 검증 예외를 무시했습니다([guardian review F05/F13](../../../full-analysis/guardian/review.md),
[observed 프로브 영수증](../../../full-analysis/guardian/observed-review-probes.receipt.json) `same_tamper_plus_new_sidecar`).
교차검토 합의는 "compaction 전후 관계 증명, unknown을 healthy로 축약하지 않음"입니다. 새 이슈나 분석 후보는
추가하지 않았습니다.

## Zeus 점검

| 무결성 경로 | 동작 | 근거 |
|---|---|---|
| SDD 이벤트 저널 `sdd.status` | 해시 체인 전수 검증, 틈·손상은 ContractError(fail closed) | `test_real_postgres_journal_tampering_is_detected` |
| 티켓 생명주기 `verify_chain` | 순서·from_sequence 불일치 거부 | `test_ticket_lifecycle` |
| Redis 스트림 `bus.compact` | pending·미전달 보호 경계 아래로만 축약, 오류는 전파 | `test_bus_compact_*` |
| 배포 건강 `deployment.py` | 관측 불가는 `unknown`, healthy로 축약하지 않음 | 코드 |
| **아티팩트 회수 `ArtifactMaintenance.collect`** | **결함**: 참조된 아티팩트 파일이 없으면 조용히 건너뛰고 결과는 정상처럼 보임 | 이번 수정 |

`collect()`는 모든 문서와 아티팩트 본문에서 `sha256:` 참조를 전이적으로 모아 보존하지만, 참조된 파일이 **이미 없으면**
`continue`만 하고 결과(`files`, `bytes`, `retained_references`)에 아무 흔적을 남기지 않았습니다. 손상된 파일은
예외로 중단하면서 유실된 파일은 "건강한 회수"로 접히는 비대칭 — 상류의 UNSEALED rc 0 / 예외 무시와 같은 형태입니다.

## 변경

- `adapters/maintenance.py`: 유실 참조를 모아 `missing_references`, `missing_reference_sample`(최대 20),
  `integrity: complete | missing_references`로 보고합니다. `apply` 시 유실 참조마다 `artifact.reference_missing`
  이벤트를 한 번만 기록합니다(내용 주소 키). 참조되지 않은 오래된 파일의 회수는 계속하고, 손상된 참조 파일은 기존대로
  삭제 전에 중단합니다.
- `docs/contracts.md`: `INV-RESOURCE-001`에 유실·손상 참조 처리와 "추가된 정상 형식 레코드는 체인 파손 판정을 완화하지
  못한다" 문장 추가.

## 재현과 검증

- `tests/test_maintenance.py::test_missing_referenced_evidence_is_reported_not_folded_into_a_healthy_result`: 참조 두
  개 중 하나의 파일을 지운 뒤 미리보기·적용 모두 `integrity=missing_references`, 유실 ref 목록, 고아만 회수, 보존
  ref 유지, 적용 시 이벤트 1건(재실행해도 1건), 참조가 없는 store는 `complete`.
- `::test_corrupted_referenced_evidence_aborts_collection_before_any_deletion`: 손상 참조는 삭제 전 중단.
- `tests/test_sdd.py::test_appended_sidecar_event_never_softens_a_journal_break`(실제 PostgreSQL): 이벤트 1을 개서한 뒤
  head 해시에 이어지는 정상 형식의 "compaction_marker" 사이드카 이벤트를 덧붙이고 head를 갱신해도 `status()`는
  `journal gap or corruption`으로 거부하고 두 레코드는 증거로 남습니다 — 상류의 TAMPER→RESEAL_REQUIRED 강등이
  Zeus에서는 일어나지 않음을 실측.
- 음성 대조: `maintenance.py`를 수정 전으로 되돌리면 유실 참조 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| `tests/test_maintenance.py` | 4 passed |
| `tests/test_sdd.py -k "sidecar or tampering"` (PG, `HARNESS_INTEGRATION=1`) | 2 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14, PG 검사 skip) | 919 passed, 306 skipped (178s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 유실 참조의 자동 복구(백업·재수집)는 없습니다. 이벤트와 결과 필드로 드러내는 것까지이며 처분은 운영자의 몫입니다.
- 모니터 화면에 `maintenance.latest.integrity`를 표시하는 것은 별도 UI 작업입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

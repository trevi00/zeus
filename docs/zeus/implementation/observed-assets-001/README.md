# Git 밖 관측 자산의 완전성 원장

기존 FA-010 / GitHub [#11](https://github.com/trevi00/zeus/issues/11) / `ZEUS-3d913005bed0` 개정 1의 구현입니다.
전체 분석은 Git 추적 2,736개 경로 외에 로컬 메타 9,420항목·추가 자산 3,434개(미커밋 노트, 플러그인, 캐시, 사적
세션, 중첩 저장소)를 캡처했지만, 이들은 추적 분모 밖이라 상태가 [local-assets-status.json](../../../full-analysis/local-assets-status.json)에
집계 숫자로만 남고 코드가 "전체 분석 완료"를 막지 못했습니다([coverage.json](../../../full-analysis/coverage.json)의
`runtime_observations_in_tracked_denominator: false`). 교차검토 합의는 "tracked/observed/캐시/사적 세션/중첩 저장소를
별도 원장으로 완전성 관리"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## 변경

- `domain/research.py`: `ObservedAsset(path, basis, state, sha256, size, evidence_refs)` 계약 추가. `basis`는
  `observed | cache | private_session | nested_repository`, `state`는 분석 원장의 상태 집합(보류 6종 / 최종 3종:
  `semantically_reviewed`, `excluded_private_session_or_credential_surface`, `generated_cache_metadata_only`).
  `semantically_reviewed`는 내용 해시와 증거 참조를 요구합니다. `parse_record`의 엄격 wire 경계(dataclass 계약 표)를
  통과합니다. `research.schema.json`은 모델 출력 스키마이고 역사 개정에 동결된 계약(`test_baseline_reconstruction_and_semantic_preservation`)이라
  건드리지 않았습니다 — 관측 자산은 운영자 매니페스트로 들어오지 모델이 출력하지 않습니다.
- `application/research.py`:
  - `observe_assets(audit_id, assets)`: 감사별 `research_observed_assets` 원장에 기록. 추적 Git 경로는 거부
    (인벤토리에 속함), 같은 레코드 재등록은 무변경, 상태 변경은 이전 레코드를 `history`에 보존, 최종 → 보류 후퇴 거부.
  - `coverage()`: `observed_assets{total, pending, pending_paths, states}`와 `whole_analysis_complete`(추적 경로·
    하위시스템·관측 자산이 모두 처분됐을 때만 True)를 추가. 추적 분모(`remaining_paths`)는 변하지 않습니다.
  - `propose()`의 adopt/adapt: 보류 관측 자산이 있으면 `Observed assets await disposition`으로 거부.
- `application/audit_gate.py`: 관측 자산 버킷을 승인 binding 증거에 포함 — 승인 뒤 새 관측 자산이 등록되면
  binding이 바뀌어 채택이 보류됩니다.
- `adapters/observed_assets.py`: JSON 매니페스트를 읽어 등록하는 CLI(`--dry-run`은 검증만).
- `docs/contracts.md`: `INV-RESEARCH-001`에 관측 자산 원장 문장 추가.

```text
uv run python -m codex_harness.adapters.observed_assets AUDIT_ID manifest.json [--dry-run]
# manifest.json: [{"path": "notes/uncommitted.md", "basis": "observed", "state": "unreviewed_observed_asset",
#                  "sha256": null, "size": 1234, "evidence_refs": []}, ...]   (path는 원시 상대 경로)
```

## 재현과 검증

- `tests/test_research_audits.py::test_observed_assets_are_a_separate_completeness_ledger`: 실제 fixture 감사에서
  관측 자산 4건(미커밋 노트·캐시 메타·사적 세션·중첩 저장소) 등록 → 추적 분모 불변, 상태 집계, 추적 경로 전부
  검토 후에도 `whole_analysis_complete` False, adopt 제안 거부; 멱등 재등록 무변경; 증거 없는 reviewed 거부;
  처분 후 완료 True와 제안 통과; 후퇴 거부와 history 보존; 추적 경로 등록 거부; basis/state/경로/해시 불량 거부;
  승인 뒤 새 관측 자산 등록 시 `adoption_eligible` False.
- `tests/test_observed_assets_cli.py`: 매니페스트 dry-run 무쓰기, 실제 등록, 잘못된 매니페스트 종료 코드.
- 기존 `test_research_audits`·`test_output_schema`(동결 스키마 불변 확인)·`test_architecture` 통과.
- 음성 대조: `application/research.py`·`audit_gate.py`를 수정 전으로 되돌리면 신규 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| `test_research_audits` + `test_observed_assets_cli` + `test_output_schema` + `test_architecture` | 111 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 919 passed, 305 skipped (167s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 분석 문서의 집계(`local-assets-status.json`)를 이 원장으로 옮기는 실제 등록은 운영자가 매니페스트로 수행합니다.
  이 PR은 원장과 게이트를 제공하며 3,434개 자산을 등록·처분하지 않았습니다.
- 관측 자산의 바이트 자체는 아티팩트로 강제 보관하지 않습니다(`sha256`·`evidence_refs`로 결속). 사적 세션·자격
  증명 표면은 내용 없이 제외 상태만 기록하는 것이 의도입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

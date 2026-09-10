# 보정 평가는 고유 실행을 세고, 승인은 정확한 한 변경을 한 번만 증명한다

기존 FA-021 / GitHub [#22](https://github.com/trevi00/zeus/issues/22) / `ZEUS-916e0f1f4333` 개정 1의 구현·검증 기록입니다.
상류 보정 원본의 격리 실측([resolution](../../../full-analysis/baldrix-calibration-001/resolution.md))에서 suggested=4인 준비
파일로 999가 적용되고, 유효값 999에도 다음 제안은 current=3이며, 손상/빈 준비 파일로 적용이 진행되고 NaN이 유효 설정으로
읽히고, 모든 매치를 제외하는 값이 precision=1과 gate accept를 얻고, 미분류 실패 10건이 success_rate=1로 계산됐습니다. 새
이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus는 이미 Git 정의 정책(`current_policy`)을 현재값 기준으로 쓰고(INV-THRESHOLD-POLICY-001), 제안은 advisory이며
  lead→conductor 순서 평가(INV-THRESHOLD-REVIEW-001)를 거칩니다. 활성 정의는 어떤 경로도 쓰지 않습니다. 남아 있던 틈은
  (1) 평가 분모가 수집 행 수였고 중복·감사 행이 실행으로 세어질 수 있었던 점, (2) 아무것도 admit하지 않는 값이 pinned
  precision 1.0으로 gate를 통과할 수 있었던 점(수집 단계 blocker만 있음), (3) "assessed" 요청과 실제 적용 사이에 정확한
  값·revision·근거·행위자·유효기간·환경을 결속하고 단일 소비를 보장하는 기록이 없었던 점입니다.
- `domain/threshold_proposals.py`: `unique_events()`가 observation id(없으면 내용 digest)로 중복을 제거하고 분모
  (`events/unique/duplicates/unidentified/unscored/invalid`)를 셉니다. `propose_threshold_changes`는 고유 이벤트로만
  평가하고 `denominator`·`evaluation_scope`(source, policy revision, 시간 범위)·`unique_corpus_hash`를 제안에 싣습니다.
  같은 id의 재수집은 첫 관측만 기록으로 남깁니다.
- `domain/threshold_replay.py`: `admitted_entries()`; `evaluate_threshold_change`는 제안값이 trailing/holdout 어느 쪽에서든
  admit 0이면 `empty_admission`으로 거절합니다(pinned precision 함수는 그대로, 한계 문구 갱신). 결과적으로 `corpus(empty)`
  케이스에서 4는 alternatives에 거절 사유와 함께 남고 2만 제안됩니다(여전히 activation-ready 아님).
- `application/threshold_approvals.py`: `ThresholdApprovals`.
  - `issue(request_id, actor='conductor', environment, ttl_seconds)`: `assessed` 요청(두 검토 모두 accepted·blocked 아님)과
    바인딩이 그대로인 제안 행, 평가 아티팩트에 아직 있는 제안, reference-accepted·유한·현재값과 다른 suggested만
    승인합니다. 바인딩(name/current/proposed/policy revision/evidence ref/corpus hash/registry hash/검토 decision id·
    generation/발행자/환경)의 digest가 id이며 같은 바인딩은 하나의 승인입니다. 만료 시각을 가집니다.
  - `consume(approval_id, applied_policy)`: `parse_applied_policy`(이전/적용 revision 40-hex, 등록된 이름의 유한 숫자만,
    소문자 환경)를 통과한 변경이 **정확히** 그 이름만, 승인된 현재값→제안값(타입까지), 평가된 이전 revision 위에서, 다른
    revision으로, 승인 환경에서, 만료 전일 때만 `issued→consumed`로 전이하고 적용 generation을 붙입니다. 어긋나면 사유를
    `threshold_approval_events`에 별도 커밋으로 남기고 거절합니다(소비 없음). 소비된 승인은 다시 증명하지 않습니다.
  - `revoke()`는 issued만, `inspect()`는 issued/consumed/revoked/expired/missing/corrupt/unreadable을 구분합니다.
  - 이 모듈은 활성 정의를 쓰지 않고 라우팅·자격·배포를 승인하지 않습니다(`authority` 필드).
- `docs/contracts.md`: `INV-THRESHOLD-APPROVAL-001` 추가.

## 재현과 검증

- `tests/test_threshold_approvals.py`(6 검사; 승인 흐름은 실제 review 체인 — `ThresholdProposals.collect` → `request` →
  Executor `decide_one`(lead, conductor) — 로 `assessed`에 도달):
  - 40개 관측 + 15개 재수집 + 같은 id의 다른 내용 1개 → unique 40, duplicates 16, 첫 관측 유지, `sample_size` 40,
    `unique_corpus_hash`가 원본 40개와 동일; 비객체/무점수 이벤트 분모 표시.
  - 모두 3점인 corpus에서 4는 `empty_admission`으로 gate 거절되고 제안값은 4가 아니며 파티션의 proposed admit > 0.
  - 발행: assessed 전 거절, conductor 외 거절, 환경/ttl 검증, 정확한 값(3→4)·revision·corpus hash·검토자·만료 바인딩,
    같은 바인딩 멱등, 다른 환경은 다른 승인.
  - 소비: 999·4.0(타입)·다른 이전값·다른 이전 revision·다른 환경·같은 revision·다른 threshold 동시 변경 7종 거절 +
    만료 거절 + NaN/bool/미등록 이름/`HEAD`/대문자 환경/문자열 값 6종 파싱 거절 → 모두 소비 없음(`issued` 유지), 이후 정확한
    변경 1회 소비(generation 1), 재소비 거절, 소비 후 철회 거절, 이벤트 순서(issued → refused×9 → consumed → refused).
  - 철회·상태: 검토자 외 철회 거절, 철회 후 소비 거절, 만료/missing/corrupt 구분.
  - **실제 PG**: 체인 산출 행을 격리 스키마에 재생한 뒤 8스레드 동시 소비 → 정확히 1건 consumed(generation 1), 7건 refused 이벤트.
- `tests/test_threshold_collection.py`의 vacuous 검사는 새 gate 동작(4 거절·2 제안·blocker 유지)에 맞춰 갱신.
- 기존 threshold 검사 5개 파일 통과(아래 표).
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`): 중복 제거를 끄면 분모 검사 실패, empty
  admission gate를 끄면 수집·제안 검사 실패, 소비의 바인딩 검사를 끄면 소비 검사 실패, 소비된 승인을 다시 소비하게 하면
  단일 소비·PG 동시성 검사 실패.

| 항목 | 결과 |
|---|---|
| `tests/test_threshold_approvals.py` + threshold 검사 5개 파일 (HARNESS_INTEGRATION=1, PG 격리 스키마) | 65 passed in 71.87s (0:01:11) |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 955 passed, 311 skipped (167s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 승인을 **소비하는 실제 적용 경로**(Git 정책 파일 변경 → 릴리스 → `current_policy` 재확인)는 Zeus에 아직 없습니다. 이
  모듈은 그 경로가 제출할 변경을 검증·증명하는 계약이며, 파일 존재·자동 생성 준비 상태를 사람 승인으로 취급하지 않습니다.
- 사용자 정의 핵심 시나리오와 실제 결과(사람 인수)를 품질 지표에 연결하는 일, Astra/Sol/Terra 자격, Windows/Linux/WSL의
  실제 설정 적용·프로세스 중단·되돌리기 실측은 하지 않았습니다. 평가 지표는 여전히 pinned replay의 점수 분포 통계입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

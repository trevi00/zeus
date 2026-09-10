# OK는 검사한 범위에 대해서만 말한다; 바이트 동일성과 검사 범위 동등성은 다른 사실이다

기존 FA-028 / GitHub [#29](https://github.com/trevi00/zeus/issues/29) / `ZEUS-79ad5a0e514a` 개정 1의 구현·검증 기록입니다.
상류 synthetic fleet의 격리 실측([resolution](../../../full-analysis/baldrix-synthetic-fleet-001/resolution.md))에서 seam 검사가
enum tag:name만 비교해 proto 금액 필드 타입·RPC 이름 변경에도 HIGH/OK를 유지하고, Dart 응답 errorCode의 String?/int?·null 직렬화
차이가 검사 범위 밖이며, 패키지·옵션·서비스·응답이 다른 proto 사본이 "동일 복사"로 서술된 것이 확인됐습니다. 이 PR은
FA-027(#59) 위에 쌓여 있습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- FA-024/027의 비교는 name/type/tag의 텍스트 일치였고, 어떤 범위를 검사했는지·스펙이 요구하는 범위가 무엇인지가 결과에 없었습니다.
- `domain/seams.py`:
  - `CHECK_SCOPES`(member_names/member_types/member_tags/envelope/rpc/response_types/error_mapping/storage/execution/
    human_scenario). 관측은 `covered_scopes`를 선언하고(`parse_observation` 검증), 선언이 없으면 `covered_scopes_of()`가 멤버가
    실제로 가진 필드(type/tag)로만 도출합니다. UNKNOWN 관측은 아무 범위도 덮지 않습니다.
  - 정책은 `required_scopes`(기본 `member_names`)를 받습니다. `scope_coverage()`는 요구 범위마다 양쪽이 덮고 정책이 비교한 것만
    `checked`, 나머지는 `unverified`로 두고 `complete`를 붙입니다. `compare()` 결과에 `scope_coverage`·`copy`(`same_blob`:
    blob 해시 동일성)·`equivalent_on_checked_scopes`를 싣습니다. verdict OK는 checked 범위에 한정됨을 명시합니다.
- `adapters/seam_extraction.py`: Python enum 추출기가 `covered_scopes = [member_names, member_types, member_tags]`를 선언합니다.
- `domain/seam_view.py`: 모든 관측이 노드가 되고 비교가 이름하지 않은 관측은 `undeclared: True`; 엣지에 `scope_coverage`·
  `copy` 포함; `live`는 두 HIGH 관측 간 OK **이면서 요구 범위가 모두 checked**일 때만; 게이트는 범위 미검증 OK를
  `OK_unverified_scopes`(undecided)로 취급; `shared_values`는 `type:tag` identity로만 묶고 "인과적 전달 아님"을 명시합니다.
- `docs/contracts.md`: `INV-SEAM-SCOPE-001` 추가.

## 재현과 검증

- `tests/test_seam_scope.py`(5 검사):
  - 정책 `required_scopes` 기본값·정렬·잘못된 4종 거절; 관측 `covered_scopes` 오류 거절; 범위 어휘 10종.
  - 같은 enum 두 개: 기본 정책은 complete OK; 스펙이 rpc/response_types까지 요구하면 verdict는 OK지만 `unverified =
    [response_types, rpc]`, `complete False`; name만 비교하는 정책은 양쪽이 type을 덮어도 member_types를 unverified로;
    UNKNOWN 상대는 checked 없음 + BLOCKED.
  - 바이트 동일성과 검사 범위 동등성: 같은 blob·같은 멤버 → 둘 다 참; 다른 blob·같은 멤버 → same_blob False/equivalent True;
    같은 blob 주장·다른 타입 → equivalent False, changed 표시.
  - VIEW: rpc를 요구하는 스펙 아래 OK 엣지는 `live False`·게이트 undecided(`OK_unverified_scopes`); 요구 범위를 모두 덮으면
    live·pass; 비교에 없는 관측은 `undeclared` 노드로 남음; HEARTBEAT 공유 값은 `str:HEARTBEAT` identity로 묶이고 note에
    "never causal".
  - 추출기: Python enum은 세 범위 선언, 미지원 스택은 `[]`.
- `tests/test_seam_view.py` + `tests/test_seam_contracts.py`와 함께 통과(아래 표).
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_seam_scope.py` + `test_seam_view.py` + `test_seam_contracts.py` (HARNESS_INTEGRATION=1) | 18 passed in 0.70s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; FA-027 `9ad77e3` 위에서) | 966 passed, 312 skipped (161s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- envelope/rpc/response_types/error_mapping/storage/execution/human_scenario 범위를 **덮는 추출기나 검사기는 아직 없습니다**.
  이 PR은 그 범위들이 스펙에 요구될 때 "미검증"으로 정직하게 남게 만드는 계약이며, proto/Dart 파서와 런타임 검사는 별도 작업입니다.
  사람이 정의한 오류/금전 시나리오의 실제 peer·저장·사용자 결과 검증과 Astra→Sol→Terra 자격은 이 결과의 소비자가 아닙니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

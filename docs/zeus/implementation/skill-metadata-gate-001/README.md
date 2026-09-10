# 스킬 메타데이터 파서와 검사 범위의 결속

기존 FA-011 / GitHub [#12](https://github.com/trevi00/zeus/issues/12) / `ZEUS-74e61b578afa` 개정 1의 구현입니다.
상류 품질 게이트는 템플릿의 `quality_axes_enforced: true   # ...`를 그대로 복사하면 값 전체를 문자열로 읽어 opt-in이
꺼졌고, 실제 CLI가 `inspected=0`인 채 PASS를 출력했습니다. 리스트 정규화(`[a, b]`, `[any]`)와 누락 절 판정도 문서와
달랐고 원본 단위 테스트 9개는 이 반례를 막지 않았습니다([common-quality 공동 검토](../../../full-analysis/cross-review-common-quality/resolution.md),
[reviewer-observations](../../../full-analysis/cross-review-common-quality/reviewer-observations.stdout.txt)). 교차검토 합의는
"명확한 입력 스키마·파서, 복사 가능한 예시 검증, 미검사와 PASS 구분"과 "검사 범위·개수·skip/not_run/fail/pass·코드/입력/정책
해시를 결속"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus에 있던 같은 결함

`adapters/skill_routing.frontmatter()`는 줄 단위 `key: value` 파서라 인라인 주석이 값에 남았습니다. 실측:
`keywords: [alpha, beta]   # 주석`은 `]`로 끝나지 않아 `['[alpha,', 'beta]', '#', '주석']`으로 쪼개져 **조용히**
매칭이 어긋났고, `min_score: 2  # note`는 `Invalid skill minimum score`로 **전체 컨텍스트 조립을 중단**시켰습니다.
라우팅 요약에는 `matched/full/pointers/legacy`만 있어 "0 매칭"이 "0개 검사"와 구분되지 않았습니다.

## 변경

- `adapters/skill_routing.frontmatter()`: 기존 `project_skills.load_yaml`(문자열 전용·태그 금지·중복 키 거부·크기/전개
  상한)로 파싱합니다. 스칼라는 문자열, 인라인 리스트는 문자열 리스트, 빈 값은 `''`, 중첩·태그·리스트 루트·문자열 아닌
  항목은 명시 거부. 닫는 fence 규칙은 그대로입니다. `native_routing_replay`도 같은 함수를 씁니다.
- `domain/skill_ranking.split_list_field()`: 이미 파싱된 리스트를 받아들이고(따옴표 제거만), 문자열이 아니면 거부.
  `skill_guidance`의 `requires`/`keywords` 소비도 이 경로입니다.
- `route_skills()` 요약에 `inspected`(메타데이터를 검사한 스킬 수) 추가. 이미 있던 `objective_hash`(입력),
  `threshold_definition`·`policy`(정책), `admission_model`(코드 버전), 매니페스트의 `revision`과 함께 검사 범위·개수·
  입력·정책·코드 식별이 한 레코드에 묶입니다. 메타데이터 오류는 skip이 아니라 명시 실패입니다(INV-SKILL-001).
- `adapters/project_skills.load_yaml(text, label)`: 오류 메시지 라벨 인자(FA-002 PR과 같은 변경).
- `docs/contracts.md`: `INV-SKILL-001`에 파서·요약 규칙 문단 추가.

## 재현과 검증

- `tests/test_skill_routing.py::test_inline_comments_never_enter_matcher_values`: 주석이 달린 템플릿 형태
  (`keywords: [alpha, "beta gamma"]   # …`, `intent: 구현해 # …`, `min_score: 2  # …`, `quality_axes_enforced: true   # …`,
  `description: "routing # not a comment"`)가 깨끗한 값으로 파싱되고 실제 `score_skill`이 `(True, 2, [intent, kw])`를
  냅니다.
- `::test_malformed_skill_metadata_fails_explicitly`(6종): 중첩 매핑, 리스트 안 리스트, 중복 키, `!!python` 태그, 리스트
  루트, 깨진 YAML 모두 ContractError.
- `::test_routing_summary_reports_inspected_count_so_zero_matches_are_not_unchecked`: 검사 2·매칭 1·레거시 1,
  매칭 0이어도 검사 2, 입력이 없으면 검사 0 — 0/2와 0/0이 구분됩니다.
- 기존 `test_skill_routing`·`test_skill_guidance`·`test_native_routing_replay`·`test_project_skills`·`test_skill_history`
  58 passed(1 skipped).
- 음성 대조: `skill_routing.py`·`skill_ranking.py`를 수정 전으로 되돌리면 신규 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| 스킬 관련 5개 모듈 | 58 passed, 1 skipped |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 925 passed, 305 skipped (164s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- Zeus에는 상류의 축별 품질 검사기(G1~G9)가 없으며 이번에 만들지 않았습니다. 이 PR은 파서와 요약 계약을 고치고, 품질 판정
  자체는 별도 설계(무엇을 검사하고 무엇을 PASS라 부르는지)로 남깁니다.
- 매니페스트 소비자(모니터·감사 CLI)가 `inspected`를 표시하는 것은 후속입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

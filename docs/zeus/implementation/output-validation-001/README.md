# 구조 검사는 지원 subset과 실행한 검사를 이름 붙이고, 소유자와 관측을 분리한다

기존 FA-023 / GitHub [#24](https://github.com/trevi00/zeus/issues/24) / `ZEUS-5f46ad3a1d56` 개정 1의 구현·검증 기록입니다.
상류 검증기의 격리 실측([resolution](../../../full-analysis/baldrix-lib-validators-001/resolution.md))에서 미검사 구조 ok,
properties 없는 additionalProperties=false 수용, NaN 수치 범위 통과, 읽기 오류와 공존하는 lexical CLEAN, 단일 중복 경로의
다중파일 의심, 무관한 두 파일의 consensus CLEAN, 스키마 소유자 오류와 에이전트 출력 결함의 동일 집계, 자기보고 tool 선언이
확인됐습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus는 `jsonschema` Draft 2020-12로 출력을 검사하므로 bool/정수 enum·`additionalProperties: false`·`required`는 이미 옳게
  동작합니다(이 PR에서 실측). 남아 있던 틈은 (1) 모르는 키워드(`requried`, `minLenght` 같은 오타)가 조용히 무시되어 "검사 없는
  ok"가 되는 것, (2) 결과에 무엇을 검사했는지 남지 않는 것, (3) 스키마 소유자 오류와 에이전트 출력 결함이 구분되지 않는 것,
  (4) 도구 사용이 관측이 아니라 자기보고로만 존재할 수 있는 것입니다. Zeus에는 어휘·파일명·boilerplate 등급이 없고 이 PR도
  추가하지 않습니다(계약에 명시).
- `adapters/output_schema.py`: `SUPPORTED_KEYWORDS`(Draft 2020-12 subset v1) 밖의 키워드는 경로와 함께
  `codex-output-schema-unsupported-keyword`로 거절합니다. `enum`도 `const`처럼 명시적 `type`을 요구하고, 닫힌 객체(`additionalProperties:
  false`)가 선언하지 않은 이름을 `required`하면 거절하며, 깊이 32·크기 256KiB 상한, 비유한 수치는 기존대로 JSON 인코딩 단계에서
  거절합니다. annotation(`examples`, `description` 등)은 스키마로 순회하지 않습니다. `preflight()`는 이제 영수증
  (`schema_hash`, `dialect`, `subset_version`, `keywords`, `checks`, `max_depth`, `bytes`)을 돌려줍니다. 기존 오류 메시지·경로·
  해시 결속은 그대로입니다.
- `adapters/execution_output.completed_output`: 결과에 `structural = {checks: {text, json, finite, schema} 각각
  checked/failed/unchecked/configuration_error, schema: preflight 영수증}`을 항상 싣습니다. 스키마가 subset을 통과하지 못하면
  `failure.owner = 'configuration'`, cause `codex-output-schema-configuration`이고 정상처럼 보이는 답도 수용하지 않습니다.
  에이전트 출력 결함은 `owner = 'agent_output'`입니다(기존 cause/`output_reason` 유지).
- `adapters/execution_output.tool_usage(result)`: transport의 `item/completed` 이벤트에서 관측한 commandExecution/
  fileChange/mcpToolCall 개수·id를 `runner_observed`로, 답의 `tool_calls`(있으면)를 `self_reported`로 나란히 기록하고
  `comparison`(`not_declared`/`consistent`/`differs`)을 붙입니다. Executor는 모든 실행 증거에 `tool_usage`를 넣습니다.
- `docs/contracts.md`: `INV-OUTPUT-001` 추가.

## 재현과 검증

- `tests/test_output_validation.py`(5 검사):
  - Zeus가 보내는 스키마 8종(VERDICT/PLAN/IMPLEMENTATION/RESEARCH/SHORTLIST/DIAGNOSIS/AdaptationProposal/IndependentReview)이
    모두 subset 안에 있고 영수증을 받음.
  - `requried`(최상위)·`minLenght`(중첩 경로) 오타 거절, type 없는 enum 거절, 미선언 required 거절, 깊이 33 거절, NaN 최소값
    거절, `examples` 안의 스키마 모양은 순회하지 않음.
  - 출력 검사: 정상 → 4개 검사 모두 checked; schema 불일치 → `owner=agent_output`, schema `failed`; `{` → json `failed`,
    finite/schema `unchecked`; 잘못된 스키마 + 정상 답 → `owner=configuration`, answer None, 실행 가능한 검사(json)는 여전히
    checked; 빈 문자열·NaN.
  - 도구 관측: completed 항목만 계수(started·agentMessage 제외, 비객체 무시), 자기보고 없음 `not_declared`, 개수 일치
    `consistent`, 빈 자기보고 `differs`.
  - Executor: 실제 프로토콜 replay 픽스처에 commandExecution 이벤트를 넣고 실행하면 증거 아티팩트의 `tool_usage`에 관측
    1건·`not_declared`.
- 기존 output/app-server/executor 검사 6개 파일과 함께 통과(아래 표). `jsonschema` 실측: `enum [1]`에 `True` 거절, `type
  integer`에 `True` 거절, properties 없는 `additionalProperties: false`도 추가 속성 거절, 모르는 키워드는 조용히 수용(이 PR이
  막는 것).
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_output_validation.py` + output/app-server/executor 5개 파일 | 118 passed, 8 skipped in 3.69s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 955 passed, 310 skipped (156s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- subset은 Zeus가 실제로 보내는 키워드 집합에 맞춘 명시적 목록이며 완전한 JSON Schema 구현이 아닙니다. 새 키워드가 필요하면
  목록에 추가하고 subset 버전을 올려야 합니다.
- 어휘 포함률·파일명·boilerplate·consensus 같은 advisory 신호는 Zeus에 없고 만들지 않았습니다. 실제 사용자 시나리오 인수와
  Astra/Sol/Terra 자격은 이 검사의 소비자가 아니며(INV-OUTPUT-001) Windows/Linux/WSL 경로·인코딩 실측도 하지 않았습니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

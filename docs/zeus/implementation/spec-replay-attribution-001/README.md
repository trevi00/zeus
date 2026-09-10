# 스펙 → 인수 초안: 문장 귀속·리터럴 임베딩·덮어쓰기 경계

기존 FA-014 / GitHub [#15](https://github.com/trevi00/zeus/issues/15) / `ZEUS-f5a496e41ac2` 개정 1의 구현입니다.
상류 usecase 템플릿과 lint는 한 줄 Given/When/Then을 허용하지만 testgen은 개행 구문을 요구했고, 생성된 pytest는
`xfail(strict=False)`+`NotImplementedError` 골격이라 행동 oracle이 없었으며, AC 귀속·120자 절단·문자열 escaping·재생성
덮어쓰기 경계가 있었습니다([판정 소비·SDD 생성 공동 검토](../../../full-analysis/harness-gate-consumer-joint/resolution.md)
"스펙→테스트" 행, [engine-extractors review](../../../full-analysis/harness-engine-extractors/review.md)). 루트 검토는 부분적
사람 인수가 이슈 개수로 전부 통과가 되면 안 된다는 점을 덧붙였습니다. 교차검토 합의는 "공통 구조화 시나리오, 안정
ID/원본 revision, 사람 oracle, 실환경 실행 receipt를 분리·연결"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus 상태와 변경

Zeus SDD는 이미 구조화 스펙(Given/When/Then은 문장 리스트, 안정 ID, 은퇴 ID 보존, 스펙 해시 결속)과 명시 selector·
oracle 바인딩이 있을 때만 Appium 초안을 생성하며, 초안은 `.py.review`로만 쓰고 골격/xfail을 만들지 않습니다. 남아 있던
틈은 **귀속**이었습니다: 생성된 단언은 어느 시나리오의 몇 번째 oracle, 어느 요구사항을 검사하는지 실행 시점에 알 수
없었고, 스펙 텍스트의 임베딩과 절단 여부는 테스트로 고정돼 있지 않았습니다.

- `adapters/sdd.replay_source`: 모듈 상수 `SPEC_HASH`, `ORACLES = {scenario_id: {requirement_ids, oracles}}`를
  생성하고, 모든 `assert_*` 바인딩을 `with self.subTest(scenario=…, oracle=i, requirement_ids=[…], expected=…)`로
  감쌉니다. 실패는 unittest가 시나리오·oracle 인덱스·요구사항 ID로 보고합니다. 액션(tap/input)은 귀속을 갖지 않습니다.
  스펙 텍스트는 전부 `repr()` 리터럴로만 들어가며 절단하지 않습니다.
- `docs/contracts.md`: `INV-SDD-001`에 GWT 리스트 규칙·초안 귀속·리터럴·무골격·덮어쓰기 금지 문장 추가.

## 재현과 검증

- `tests/test_sdd.py::test_replay_attributes_every_assertion_to_its_oracle_and_requirements_at_runtime`: 삼중 따옴표·
  역슬래시·개행·탭·따옴표가 섞인 oracle 텍스트와 값, 404자 문장으로 초안을 생성해 `ast.parse`한 뒤 `SPEC_HASH`/`ORACLES`
  상수와 각 `subTest` 인자·`exact_text` 기대값을 `ast.literal_eval`로 복원해 원문과 동일함을 확인. `xfail`/`skip(`/
  `NotImplementedError` 없음, 긴 문장 무절단, 액션 줄은 귀속 블록 밖.
- `::test_gwt_must_be_lists_never_one_line_strings`: 한 줄 문자열 `then`과 빈 문장은 스펙 검증에서 거부.
- `::test_replay_export_is_idempotent_and_never_overwrites_a_different_draft`: 같은 내용 재출력은 동일 결과, 다른 내용은
  거부하고 원본 유지, `.py.review` 확장자 강제.
- 기존 `test_sdd.py` 통과(PG 검사 제외). 음성 대조: `adapters/sdd.py`를 수정 전으로 되돌리면 귀속 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| `tests/test_sdd.py` + `test_architecture.py` | 15 passed, 6 skipped(PG) |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 920 passed, 305 skipped (192s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 초안은 여전히 **미실행 코드**이며 실기기 실행 receipt·사람 인수와 연결되지 않습니다. 실행 결과를 FA-013의 게이트 판정
  (`runner_receipt`, 문장 귀속)으로 기록하는 경로는 후속입니다.
- 다중 시나리오 replay(시나리오별 초기화 통합), web/WebView 컨텍스트, 금융 흐름은 기존대로 생성 차단입니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

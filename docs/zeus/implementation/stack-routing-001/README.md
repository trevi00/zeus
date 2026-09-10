# 기술 스택 템플릿과 라우터의 일치

기존 FA-008 / GitHub [#9](https://github.com/trevi00/zeus/issues/9) / `ZEUS-4e7e2e2b01a9` 개정 1의 구현입니다.
상류 `tech_stack._parse_yaml`은 인라인 주석을 제거하지 않아 제공 템플릿을 그대로 복사하면
`language: "java                   # java | kotlin | ..."` 같은 값이 후보 경로에 그대로 들어가고 정상 경로
`java/springboot-3.2`는 생성되지 않았습니다([격리 프로브 영수증](../../../full-analysis/baldrix-common/template-inline-comment-probe.json),
`expected_clean_path_present: false`). 루트 검토는 추가로 Flutter 예제가 `flutter/3.x`가 아닌 `dart/...`를
만들고, tree 모드가 한 단계만 순회하며, frontmatter 없는 모듈이 독립 점수 대상이 아님을 지적했습니다
([Flutter 공동 검토](../../../full-analysis/flutter-joint-001/resolution.md)). 교차검토 합의는 "엄격 파서·유효 스택
enum·상속/경로 수집 회귀; 문서만 복사하지 않음"입니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus 상태와 변경

- **인라인 주석**: Zeus는 `.harness/tech-stack.yaml`을 실제 YAML 로더(문자열 전용·태그 금지·중복 키 거부)로
  읽고 각 값을 `segment()` 정규식으로 검증하므로, 상류 템플릿과 같은 주석 달린 파일이 그대로 정상 경로로 라우팅됩니다.
  따옴표 안에 `#`나 공백이 든 값은 경로 문자열로 새지 않고 `Invalid stack path segment`로 명시 거부됩니다. 이번에
  회귀 테스트로 고정했습니다.
- **버전 계열 경로(변경)**: `18` → `18.x`만 만들던 규칙을 `3.2` → `3.x`처럼 점 버전에도 확장했습니다
  (`domain/project_skills.py::eligible_paths`). `language: flutter, version: "3.24"`는
  `flutter/flutter-3.24, flutter/flutter, flutter/3.24, flutter/3.x, flutter/lang, flutter`를 만들고 `dart/...`는
  만들지 않습니다. 언어 이름은 프로파일이 선언한 값이며 Zeus가 dart로 바꿔 쓰지 않습니다.
- **깊이 제한 수집(변경)**: 패키지 스킬 `SKILL.md`를 유효 prefix 아래 한 단계에서만 모으던 규칙을 임의 깊이로
  확장했습니다(`select_skill_paths`). 밑줄 접두 디렉터리 아래는 계속 건너뜁니다. 다른 프레임워크 트리는 여전히
  제외됩니다.
- **frontmatter 없는 모듈**: Zeus 선택은 경로 기반이라 frontmatter가 없어도 포함되며, 점수는 본문 전문/포인터 단계에만
  영향합니다(기존 `test_skill_routing`). 이번에 변경하지 않았습니다.
- `docs/contracts.md`: `INV-PROJECT-001`에 위 규칙 문장 추가.

## 재현과 검증

- `tests/test_project_skills.py::test_inline_comment_template_routes_to_clean_paths`: 상류 템플릿 형태(주석 포함)를
  파싱해 `java/springboot-3.2, java/springboot, java/3.2, java/3.x, java/lang, java`를 얻고 어떤 경로에도 `#`·공백이
  없음. 상류 프로브의 반대 결과입니다.
- `::test_flutter_stack_activates_the_flutter_tree_not_dart`: Flutter 예제의 경로 집합 고정, `dart` 접두 없음.
- `::test_comment_or_space_inside_a_quoted_value_fails_explicitly`(3종): 따옴표 안 주석/공백은 경로 대신 거부.
- `::test_packaged_skills_are_collected_at_any_depth_and_underscore_directories_are_skipped`: 2단계 깊이 수집,
  `_drafts`/`_wip` 아래 제외, 다른 프레임워크 제외, `README.md` 미포함.
- 기존 `test_project_skills`·`test_skill_routing`·`test_skill_guidance`·`test_pipeline` 통과(58 passed).
- 음성 대조: `domain/project_skills.py`를 수정 전으로 되돌리면 버전 계열·깊이 수집 검사가 실패합니다.

| 항목 | 결과 |
|---|---|
| 스킬 관련 4개 모듈 | 58 passed |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 923 passed, 305 skipped (177s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 이는 정적 라우팅 회귀이며 실제 Codex 세션에서의 스킬 활성화·본문 소비를 실측한 것은 아닙니다(기존
  `test_actual_executor_context_contains_only_eligible_pinned_skills`가 fixture 런타임으로 주입 경계를 검사).
- 상류 Baldrix 파서 자체는 고치지 않았습니다. 티켓 범위가 "새 trevi00/zeus 저장소에 한정, 기존 운영 저장소에 자동
  반영하지 않음"이고, Zeus는 상류 파서를 이식하지 않고 실제 YAML 로더로 대체했으므로 상류 수정은 이 결함의 Zeus
  해소 조건이 아닙니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따르는 별도 단계이며, 이 기록은 구현·검증 증거이지 배포 승인이 아닙니다.

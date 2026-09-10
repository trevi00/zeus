# 릴리스 검사는 실제로 실행된 트리에 결속되고, 테스트는 분모로만 통과한다

기존 FA-025 / GitHub [#26](https://github.com/trevi00/zeus/issues/26) / `ZEUS-9495da500988` 개정 1의 구현·검증 기록입니다.
상류 설치기·검사기의 격리 실측([resolution](../../../full-analysis/baldrix-scripts-root-001/resolution.md))에서 core.hooksPath를
무시한 채 설치 성공을 보고하고, linked worktree 설치가 실패하며, 생성된 pre-push가 push ref 대신 현재 작업트리를 검사하고,
JaCoCo 입력 누락이 rc0 SKIP·빈 카운터가 100%·Mermaid 검사 0건이 rc0 통과가 되는 것이 확인됐습니다. 새 이슈나 분석 후보는
추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus는 Git 훅을 설치하지 않습니다(native Codex hook은 후보 manifest 기준으로 canary를 돌리고 transport의 `hooks/list`로
  발견을 확인합니다). 릴리스 러너는 후보 revision을 checkout한 review workspace에서 검사를 실행하지만, 영수증에는 argv·exit·
  stdout·stderr만 있고 **어떤 트리에서 실행됐는지**(HEAD·clean)가 없었으며, pytest 검사는 exit 0이면 통과였습니다(모두 skip이어도).
  격리 서비스(`VerificationServices`) 진입 실패는 예외로 전파됐습니다.
- `domain/check_results.py` (stdlib만): `pytest_summary(stdout)`(마지막 요약 줄 파싱, `no tests ran` 인식, 미파싱 표시),
  `classify_test_run(returncode, stdout)`(실행된 테스트 0 → `empty_check`; 요약 없음 → `unstructured_output`; failed/errors 또는
  exit≠0 → 실패; 그 외 통과 — 분모가 exit 0보다 우선), `is_test_run(argv)`, `bind_revision(expected, observed, dirty)`.
- `adapters/deployment.py`: `_check(argv, cwd, timeout, env, expected_revision)`가 `expected_revision`을 받으면 실행 전에
  `git rev-parse HEAD`·`git status --porcelain`으로 workspace를 관측해 영수증 `binding`(cwd, expected, observed_head, dirty,
  env_keys, bound 사유)에 남깁니다. HEAD가 후보가 아니거나 dirty면 `revision_mismatch`(실행하지 않음), 관측 자체가 불가능하면
  `observation_error`. pytest 호출은 `classify_test_run`으로 `denominator`와 사유를 붙여 판정합니다. `_run`은 install·incumbent
  tests·candidate tests·docker build에 후보 revision을 넘기고, `VerificationServices` 진입 실패를 잡아 `stage: verification_isolation`
  영수증과 함께 `retry`(검사 없음, 릴리스는 `reviewed` 유지)로 끝냅니다. timeout/OSError 영수증에도 binding이 남습니다.
- `docs/contracts.md`: `INV-CHECK-001` 추가.

## 재현과 검증

- `tests/test_check_binding.py`(5 검사; 검사는 실제 자식 프로세스·실제 Git review workspace):
  - 요약 파싱 5종, 판정: 정상 통과 / **모두 skip은 exit 0이어도 `empty_check`** / no tests ran / 모두 deselected / 실패 /
    exit 0인데 요약이 failed면 실패 / 요약 없음 `unstructured_output` / xfail 허용 / 잘못된 타입 거절; `bind_revision` 4종.
  - 실제 workspace에서 `python -c` 검사: HEAD 일치·clean → executed, 영수증에 binding; 다른 expected revision →
    `revision_mismatch`(실행 안 됨, 영수증 `executed: false`); 같은 HEAD라도 dirty → `revision_mismatch`; Git이 아닌 디렉터리 →
    `observation_error`; revision 미선언은 기존 형태 유지(binding에 `bound` 없음).
  - 실제 pytest: skip 하나뿐인 커밋 → exit 0인데 `empty_check`(denominator skipped 1/passed 0); 실제 테스트 추가 커밋 →
    통과(passed 1, skipped 1); 이전 workspace를 새 후보로 검사 → `revision_mismatch`; 실패 테스트 커밋 → failed 1.
  - 격리 실패: `VerificationServices` 진입이 예외를 내면 install만 실행되고 결과 `retry`(`verification observation unavailable`),
    릴리스 `reviewed`·checks `{}` 유지, 영수증 `stage: verification_isolation`.
  - 1초 timeout: `observation_error`이고 영수증에 observed HEAD가 남음.
- 기존 릴리스 검사 5개 파일과 함께 통과(아래 표). 기존 `test_install_timeout_retains_review_and_can_retry`는 가짜 git이 HEAD를
  관측할 수 없는 경우인데, 이제 그 경우가 `observation_error`(retry)로 분류되어 그대로 통과합니다.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_check_binding.py` + 릴리스 검사 5개 파일 | 52 passed, 1 skipped in 18.08s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; origin/main `1488468` 위에서) | 955 passed, 310 skipped (178s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 실제 push ref(삭제 ref·다중 ref)·core.hooksPath·linked worktree 검증은 Zeus가 Git 훅을 쓰지 않으므로 해당 없음이며, 그 사실을
  INV-CHECK-001에 적었습니다. Linux/WSL 실측과 실제 renderer/build 산출물·사람이 검토한 SDD 시나리오는 별도입니다.
- docker build/run 검사는 여전히 exit 코드 기반이며(분모 없음) 이 PR은 pytest 검사에만 분모를 적용합니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

# 격리 실행은 끝난 단계와 산출물로 이름 붙이고, 종료 코드만으로 통과하지 않는다

기존 FA-026 / GitHub [#27](https://github.com/trevi00/zeus/issues/27) / `ZEUS-430121f4256d` 개정 1의 구현·검증 기록입니다.
상류 실행기의 격리 실측([resolution](../../../full-analysis/baldrix-test-runners-001/resolution.md))에서 빈 스크립트 rc0과
stderr FAIL 표시가 통과가 되고, pytest assertion 메시지가 의존성 부재로 오분류되며, 실패한 pytest가 더 약한 수동 main 실행으로
대체되고, 격리 재실행 예외가 원래 환경 실행으로 이어질 수 있음이 확인됐습니다. 이 PR은 FA-025(#57) 위에 쌓여 있습니다(pytest
분모 `classify_test_run` 재사용). 새 이슈나 분석 후보는 추가하지 않았습니다.

## Zeus의 현재 상태와 변경

- Zeus의 격리 실행기(`DockerSourceRunner`)는 networkless·read-only·cap-drop·tmpfs scratch·in-container timeout으로 실행하고
  원본 바이트를 manifest 해시로 검증합니다. 다만 영수증은 exit 코드와 `blocked`(124/125/126/127/137)만 있어 "격리 준비 실패"와
  "명령이 125로 종료"가 같은 모양이었고, rc0 빈 출력·stderr만 있는 출력이 구분되지 않았으며, pytest 명령의 분모도 없었습니다.
  호스트 재실행 경로는 원래 없습니다.
- `domain/check_results.py`: `classify_isolated_run(stage, exit_status, stdout, stderr, command, client_timeout, error)` —
  `materialize`/`spawn` 단계 실패 → `isolation_unavailable`(`substitute_execution: False`), client timeout → `client_timeout`,
  124/137 → `timeout`, 125/126/127 → `runner_error`, 그 외 `executed`에서 명령이 pytest면 `classify_test_run` 분모로, 아니면
  exit 0 + stdout 있음일 때만 통과(빈 출력·stderr-only는 실패 사유 명시).
- `adapters/source_execution.py`: `execute()`가 단계를 추적해(`materialize` → `spawn` → `run`) 예외를 단계별로 분류하고, docker
  client `TimeoutExpired`를 `client_timeout`으로 구분하며(컨테이너는 `docker rm -f`로 제거), 영수증 아티팩트에 `verdict`
  (category/stage/passed/output_class/denominator), `command`, `attempt`(request/owner/task/generation/release), `runner_mode`,
  stdout/stderr SHA-256을 넣습니다. `inspection_blocked`는 category가 `executed`가 아닐 때입니다. `run_one`이 큐 행의 attempt를
  넘깁니다. `ExecutionReceipt` 데이터클래스(동결된 research schema)는 바꾸지 않았습니다.
- `docs/contracts.md`: `INV-RUNNER-001` 추가.

## 재현과 검증

- `tests/test_runner_categories.py`(3 검사):
  - 분류: materialize/spawn → unavailable, client timeout, 124/137/125/126/127, rc0 빈 출력 실패, rc0 stderr-only 실패, rc0
    stdout 통과, exit 2 실패, pytest all-skip `empty_check`, **assertion 메시지가 있는 실패 pytest는 그대로 실패(의존성 부재
    아님)**, 4 passed 통과, 미지 stage 거절.
  - 실행기 영수증(가짜 docker 프로세스): ok/empty/stderr_fail/timeout(137)/runner(125)/skipped pytest 6종의 verdict·
    attempt·digest·runner_mode; empty pytest run은 blocked가 아니라 "통과 아님".
  - 격리 실패: PATH에서 docker를 제거한 **실제** spawn 실패 → `isolation_unavailable`(stage spawn, FileNotFoundError, 호스트
    재실행 없음); 바이트 해시가 어긋난 manifest → stage materialize, 컨테이너 실행 0회; client timeout → `client_timeout` +
    `docker rm -f` 호출.
- `tests/test_research_audits.py`(기존 실행기 검사 포함) + `test_check_binding.py`: 75 passed.
- 음성 대조군([target-tests.json](target-tests.json) `negative_controls`).

| 항목 | 결과 |
|---|---|
| `tests/test_runner_categories.py` + `test_research_audits.py` + `test_check_binding.py` | 78 passed in 44.87s |
| Windows 전체 `uv run python -m pytest -q` (Python 3.12, PG 검사는 skip; FA-025 `0bc83b5` 위에서) | 958 passed, 310 skipped (173s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- 실제 Docker 컨테이너 실행·Linux/WSL 프로세스 트리·scratch 권한 실측은 이번에 하지 않았습니다(실행기 검사는 기존과 같이 docker
  프로세스를 대체한 픽스처 + 실제 spawn 실패). 사람의 핵심 SDD 시나리오와 Astra→Sol→Terra 자격은 이 영수증의 소비자가 아닙니다.
- 이슈 종료는 Codex·Claude 독립 검토와 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30) 범위의 종료
  경로를 따르는 별도 단계이며, 이 기록은 검증 증거이지 배포 승인이 아닙니다.

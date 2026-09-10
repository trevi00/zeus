# 호스트별 실제 실행 증거 002 — 수정된 러너로 Windows 11·WSL Ubuntu 재실행

[environment-runs-001](../environment-runs-001/README.md)의 검토 조건(PR #69 review)을 반영한 러너
[`scripts/environment_evidence.py`](../../../../scripts/environment_evidence.py)의 출력입니다. 001의 영수증은 원본 그대로 두었고 이
디렉터리가 결속된 재실행입니다.

## 러너가 이제 보장하는 것

- **소유한 자산만 만들고 지운다**: 실행마다 고유 compose 프로젝트 이름(`harness-evidence-<label>-<8hex>`)을 만들고, 그 이름에 컨테이너·볼륨·
  네트워크가 이미 있으면 `up`도 `down`도 하지 않고 거절합니다(`claim_project`). compose 파일은 명시(`-f compose.yaml -f <override>`)하고,
  override가 PG/Redis를 **임시 loopback 포트**(`127.0.0.1::5432`, `::6379`)로 발행하므로 고정 포트 55432/56379를 쓰는 기존 서비스는 건드리지
  않습니다. 정리는 자기 프로젝트만 `down --volumes --remove-orphans` 하고 남은 컨테이너·볼륨이 없는지 확인합니다.
- **실패는 실패로 남는다**: preflight·claim·stack_up·identity_before·steps·identity_after·identity_stable·teardown 8단계가 모두 `ok`일 때만
  `passed=true`이고 그 외에는 프로세스가 1로 종료합니다. 단계 timeout·실행 오류는 `timed_out`/`error`로 기록되며, teardown 실패는 앞서 모은
  단계 증거를 지우지 않습니다.
- **시험 대상과 컨테이너의 결속**: 부모 환경의 `ZEUS_*`/`HARNESS_*`/`POSTGRES_*`/`COMPOSE_*`를 모두 버린 격리 환경에서 두 alias 계열
  (`ZEUS_DATABASE_URL`=`HARNESS_DATABASE_URL`, `*_REDIS_URL`, `*_REDIS_NAMESPACE`)을 이 실행의 스택으로 고정합니다(저장소·런타임 경로는
  테스트 자신이 정하도록 비워 둡니다 — 1차 재실행에서 이를 고정했다가 configuration/supervisor 검사 4건이 실패해 고쳤습니다). 실행 전후로 PG `system_identifier`·컨테이너 id, Redis `run_id`·컨테이너 id를 읽어 동일함을, PG `xact_commit`과 Redis
  `total_commands_processed`가 실행 중 증가했음을 확인합니다(`identity_stable`). DB URL은 비밀번호를 가린 채 기록합니다.
- **실행 소스 결속**: git head, 추적 변경·미추적 파일 목록, `git diff` digest, 러너·compose.yaml·override·uv.lock·pyproject.toml의 sha256을
  영수증에 넣습니다. 전체 스위트는 `--junitxml`로 실행해 **테스트 파일별 passed/skipped/failed** 계수(`per_file`)를 영수증에 담습니다.
- 러너 자체는 `tests/test_environment_evidence.py`가 fake shell로 검토 반례 각각(기존 프로젝트 거절, setup/identity 실패, 단계 timeout·실패,
  teardown 실패·잔여물, 비정상 종료 코드, 환경 격리·비밀 미기록)을 검사합니다.

## 결과

| 호스트 | head | 전체 스위트 (PG+Redis, 격리 환경) | 일회용 Docker 검사 | ruff | identity_stable | 영수증 |
|---|---|---|---|---|---|---|
| Windows 11 | WIN_HEAD | WIN_FULL | WIN_DOCKER | WIN_RUFF | WIN_IDENTITY | [windows-11-receipt.json](windows-11-receipt.json) |
| WSL2 Ubuntu 26.04 | WSL_HEAD | WSL_FULL | WSL_DOCKER | WSL_RUFF | WSL_IDENTITY | [wsl-ubuntu-26.04-receipt.json](wsl-ubuntu-26.04-receipt.json) |

## 이슈별 대응 (테스트 노드 / 실제 서비스 / 실패 주입 / 미실행)

요약 통과 수는 이슈의 종료 조건을 채우지 않습니다. 아래는 각 이슈의 잔여 조건 중 "호스트별 실제 환경" 부분에 이 실행이 제공하는 것과
제공하지 않는 것입니다. 파일별 계수는 영수증 `per_file`에 있습니다.

| 이슈 | 이 실행이 다루는 테스트 파일 | 실제 서비스 / 실패 주입 | 제공하지 않는 것 |
|---|---|---|---|
| #12 skill metadata gate | `test_skill_routing.py` | 파일 기반 producer→validator→reader 경로, 두 호스트의 실제 경로·인코딩 | 실제 배포 템플릿 소비자, 사람 인수 |
| #16 writeback binding | `test_git_workspace.py`, `test_release_runner.py` | 실제 Git 작업트리·격리 파일, 두 호스트의 LF/CRLF 기본값 | 실제 사용자 인수·독립 승인 영수증 |
| #17 progress event identity | `test_execution_progress.py` | 실제 PG 원장(격리 스키마)에 진행 기록, 손상 이벤트 주입 | 실제 pane 프로세스 중단·재개, QA 인수 |
| #18 host recovery | `test_host_interruption.py` (ZEUS_TEST_DOCKER=1) | **실제 PG 컨테이너 일시정지·재시작·중단** 중 원장 동작 | 이 PC의 절전·재부팅, 격리 VM 시계 변경 |
| #21 breaker admission | `test_breaker.py` | 실제 PG, 실제 자식 프로세스 동시 acquire, 만료 probe 주입 | 실제 모델 호출 중 회수, 사람 인수 |
| #23 evidence inspection | `test_evidence_inspection.py` | 실제 Python 자식 replay, 두 호스트의 경로·프로세스 트리, PG 원장 | stale authority 실측(재부팅 뒤), 실기기 인수 |
| #26 check binding | `test_check_binding.py`, `test_verification.py` (ZEUS_TEST_DOCKER=1) | 실제 Git 리비전 결속, **실제 일회용 Docker 스택 생성·정리·거부 경로** | 실제 renderer/build 산출물, 사람이 검토한 SDD 시나리오 |

## 제공하지 않는 것

- 네이티브 Linux·macOS 호스트(Linux는 GitHub Actions ubuntu-latest 결과만), 이 PC의 절전·재부팅. **재부팅 뒤 새 스택에서 스위트를 다시
  통과하는 것은 재부팅 복구 증거가 아닙니다** — 재부팅 전후의 boot identity, 재부팅 전에 만든 원장·작업 identity의 보존, 복구 불변식을
  같이 기록해야 하며 이 러너는 그것을 하지 않습니다.
- 사람의 인수, 실제 제품·기기·금전 시나리오, 실제 모델 자격 이전, 이슈 종료 판정.

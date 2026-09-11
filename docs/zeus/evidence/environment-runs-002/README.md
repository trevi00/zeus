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
- **시험 대상과 컨테이너의 결속**: 시험은 부모 환경의 `ZEUS_*`/`HARNESS_*`/`POSTGRES_*`/`COMPOSE_*`를 모두 버린 환경에서 실행되고, 스택은
  CI와 같은 방식 — 저장소 `.env`(`HARNESS_DATABASE_URL`, `HARNESS_REDIS_URL`, `ZEUS_REDIS_NAMESPACE`) — 로 고정됩니다. `settings()`는 환경에
  ZEUS_/HARNESS_ 값이 없을 때 `.env`를 읽으므로 다른 곳을 가리킬 변수가 없고, 자기 `.env`나 변수를 스스로 두는 검사(configuration,
  supervisor)는 그대로 동작합니다. 이전 `.env`는 teardown에서 복원되며 전후 digest를 기록합니다. (시행착오: 1차 재실행은 `*_REPOSITORY`/
  `*_RUNTIME_DIR`까지 환경변수로 고정해 configuration/supervisor 검사 4건이 실패했고, 2차는 DB·Redis를 환경변수로 고정해 명시 저장소의
  `.env`를 읽는 검사 1건이 실패했습니다 — 둘 다 러너가 `passed=false`·exit 1로 기록했고 `attempt-1`, `attempt-2` 디렉터리에 그대로 둡니다.)
  실행 전후로 PG `system_identifier`·컨테이너 id, Redis `run_id`·컨테이너 id를 읽어 동일함을, PG `xact_commit`과 Redis
  `total_commands_processed`가 실행 중 증가했음을 확인합니다(`identity_stable`). 실행별 임의 DB 비밀번호는 영수증에서 가려지고 로그에서도
  치환됩니다(attempt-2 로그에 한 번 노출된 값은 사후 치환했으며, 그 컨테이너는 이미 제거됐습니다).
- **실행 소스 결속**: git head, 추적 변경·미추적 파일 목록, `git diff` digest, 러너·compose.yaml·override·uv.lock·pyproject.toml의 sha256을
  영수증에 넣습니다. 전체 스위트는 `--junitxml`로 실행해 **테스트 파일별 passed/skipped/failed** 계수(`per_file`)를 영수증에 담습니다.
- 러너 자체는 `tests/test_environment_evidence.py`가 fake shell로 검토 반례 각각(기존 프로젝트 거절, setup/identity 실패, 단계 timeout·실패,
  teardown 실패·잔여물, 비정상 종료 코드, 환경 격리·비밀 미기록)을 검사합니다.

## 결과

| 호스트 | head | 전체 스위트 (PG+Redis, 격리 환경) | 일회용 Docker 검사 | ruff | identity_stable | 영수증 |
|---|---|---|---|---|---|---|
| Windows 11 | `d925e01` | **1441 passed, 14 skipped** (374s) | **17 passed** (56s) | 통과 | ok (PG xact_commit +9608, Redis commands +12650) | [windows-11-receipt.json](windows-11-receipt.json) |
| WSL2 Ubuntu 26.04 | `d925e01` | **1447 passed, 8 skipped** (124s) | **17 passed** (49s) | 통과 | ok (PG xact_commit +9427, Redis commands +12566) | [wsl-ubuntu-26.04-receipt.json](wsl-ubuntu-26.04-receipt.json) |

두 호스트 모두 `passed=true`: 8단계 전부 ok, 각 실행이 만든 프로젝트만 제거되고 잔여물 없음, `.env`는 이전 내용으로 복원, 파일별 계수는
89개 테스트 파일에 대해 기록됨. 일회용 Docker 검사 17건에는 이번에 추가한 호스트 포트 연결 대기 검사가 포함됩니다. Windows 영수증의
`tracked_changes`에는 실행 시작 시점의 작업트리 상태로 이 evidence 디렉터리 안의 attempt 파일 이동(제 정리 실수로 잠시 attempt-3 파일이
덮여 있던 상태)이 적혀 있습니다 — 실행 입력(러너·compose·override·uv.lock·pyproject)의 digest는 head와 같고, 그 상태는 커밋 전에 git으로
복원했습니다. 영수증은 사후에 고치지 않았습니다.

### 시도 기록 (모두 러너가 `passed=false`·exit 1로 기록, 디렉터리에 그대로 보존)

| 시도 | 결과 | 원인 | 조치 |
|---|---|---|---|
| attempt-1 (Windows, `7fd152a`) | 4 failed | 러너가 `*_REPOSITORY`/`*_RUNTIME_DIR`까지 환경변수로 고정해 configuration/supervisor 검사를 덮어씀 | 서비스 설정만 고정 |
| attempt-2 (Windows, `5b1379a`) | 1 failed | DB를 환경변수로 고정해 명시 저장소의 `.env`를 읽는 검사와 충돌; 로그에 실행별 비밀번호 1회 노출 | `.env`로 고정(CI 방식), 로그 치환 |
| attempt-3 (Windows, `5ed6bc8`) | 통과했으나 `per_file`이 1개 파일로 뭉침 | xunit2 junit에 `file` 속성이 없음 | classname에서 모듈 도출 |
| attempt-3 (WSL, `5ed6bc8`) | stack_up 실패 | 라벨의 `.`이 compose 프로젝트 이름에 불허 | 이름 정규화 |
| attempt-4 (WSL, `ce95566`) | Docker 검사 2 errors | `up --wait` 뒤에도 호스트 포트가 잠시 `Connection refused` | `VerificationServices`가 연결 가능할 때까지 유계 대기 (`d925e01`) |
| attempt-5 (Windows, `ce95566`) | 통과 (참고용) | 포트 대기 수정 전 Windows 실행 | 최종 실행으로 대체 |

## 이슈별 대응 (테스트 노드 / 실제 서비스 / 실패 주입 / 미실행)

요약 통과 수는 이슈의 종료 조건을 채우지 않습니다. 아래는 각 이슈의 잔여 조건 중 "호스트별 실제 환경" 부분에 이 실행이 제공하는 것과
제공하지 않는 것입니다. 파일별 계수(두 호스트 동일): skill_routing 17, git_workspace 7, release_runner 6, execution_progress 2, breaker 14,
evidence_inspection 8, check_binding 7, verification 10(+1 skip, 일회용 Docker 단계에서 실행), host_interruption 1(+5 skip, 일회용 Docker
단계에서 실행), integration 26 — 전부 passed. 전체는 영수증 `per_file`.

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

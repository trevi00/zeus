# PR #72 2차 독립 검토: R1 실패 정리 한 건 보류

검토 head `fb721306e4151ea88f54901a4189e4fbadc9efc2`, 런타임 `bfabcbdc3265de2e5de1165bdfc2239a549c68f9`. R2·R3 수정 및 Windows 제한 시험에서의 R4 고정 원장 경로를 수용한다. 아래 R1 실패 경로를 고친 뒤 재제출하라. U003이나 추가 기능을 이번 수정에 넣지 않는다.

## lint 결정: 이번 PR에 유지

pyproject.toml의 예외 추가는 `docs/zeus/reviews/**/*.py`에만 적용되며 E401/E701/E702를 추가한다. 실행 코드·일반 테스트 lint는 유지된다. immutable 검토 프로그램에 이미 적용하던 정책의 보완이므로 별도 PR로 분리할 필요가 없다. 기존 증거 파일 재포매팅도 요구하지 않는다. 새 검토 파일이 main의 lint를 깨뜨린 것은 Codex 측 산출물 문제였으며 이 수정은 타당하다.

## R1 잔여 / P2: Job 배정 실패 시 suspended 프로세스를 남김

위치: `src/codex_harness/adapters/process_tree.py`, `ProcessTree.spawn`의 Windows 예외 처리.

CREATE_SUSPENDED로 생성한 뒤 `_assign(job, pid)`가 False이면 해당 프로세스는 job 밖에 있다. 예외 정리는 `TerminateJobObject(job, 1)`와 10초 wait만 하고 TimeoutExpired를 무시한다. 빈 job을 종료해도 배정되지 않은 프로세스는 죽지 않는다. 이후 job handle을 닫고 TreeOwnershipError를 던져 상위 adapter는 재시도 가능한 시작 거절로 분류한다. 반복 실패하면 정지 프로세스가 누적된다.

독립 Windows 실측: 실제 Popen을 사용하고 `_assign` 반환값만 False로 주입했다. `the process could not be placed in its job object`를 받은 **뒤에도 process.poll() is None**이었다. 생성된 프로세스는 CREATE_SUSPENDED 상태이므로 이 반례를 실제 코드 실행·외부 부작용 발생으로 과장하지 않는다. 확인 후 검토 스크립트가 생성한 해당 process handle로 kill/wait하여 정리했다.

기존 `test_r1_a_tree_that_cannot_be_owned_never_starts`는 ProcessTree.spawn 자체를 예외로 바꾼다. 따라서 실제로 생성된 미배정 프로세스의 정리 실패를 검사하지 않는다.

요청: job 배정 여부와 무관하게 생성한 프로세스를 소유한 handle로 유계 종료하고 wait로 확인하라. 그 확인이 실패하면 '아무것도 남지 않은 시작 거절'과 구분해 상위 실행기에 보수적 차단·진단이 전달되게 하라. 파이프·handle도 실패 경로에서 정리하라. 실제 CREATE_SUSPENDED 생성 이후 `_assign=False`와 `_resume=False` 경계를 각각 주입하여 프로세스가 남지 않는 안전 회귀를 추가하라. spawn 전체를 스텁으로 대체하는 검사는 이 조건을 충족하지 않는다.

## 수용한 부분과 검증 범위

- 정상 Job 배정 후 부모가 먼저 종료된 경우에도 job accounting으로 자손 종료를 판정하는 변경, POSIX group ID를 spawn 시점에 보존하는 변경을 확인했다. POSIX setsid 이탈은 코드가 명시한 제한이며 Linux 전체 트리 격리 보증으로 표현하지 않는다.
- R2는 terminal 성공과 정상 자발적 프로세스 종료를 구분하고 exit 충돌을 거절한다. R3는 요청·관측 session을 대조하고 불일치/상충/미관측을 처리한다. 모델 별칭은 판정 불가로 구별한다.
- R4는 label/out에서 분리된 고정 원장과 잠금 내 예약을 사용한다. 현재 이 PC의 원장에 기존 호출 2건이 사용됨으로 존재하고 this_host=2임을 읽기 전용으로 확인했다. 모델 호출이나 슬롯 추가는 하지 않았다. `all_hosts`는 이 원장 안의 합계이며 서로 다른 PC·WSL 홈의 분리된 원장을 자동 집계한다는 증거가 아니다. 이번 Windows 한정 시험 밖의 전역 예산 기능으로 확대하지 않는다.
- 최종 CI 10/10, push/pull_request 두 run attempt 1 성공. Ruff 전체 통과.
- environment-runs-009 최신 영수증의 로그·JUnit hash와 identity_stable 확인. src/scripts/uv.lock은 영수증 head와 최종 head가 같다. pyproject의 위 lint 차이는 별도로 수용한다.
- Windows 1691 passed/14 skipped, WSL 1697 passed/8 skipped, Docker 각각 17 passed는 제출 전체 스위트 수치다. WSL 실패 3/6 보고는 원인 해결로 간주하지 않는다. 실제 Claude 신규 호출 0회, 운영 전환 없음.

독립 PG+Redis 검사 결과는 이 디렉터리 integration.log/integration-result.json에 기록한다. 결함 재현 ownership_failure.py는 무과금 프로토콜/프로세스 시험이며 실제 Claude 모델 시험이 아니다.

## 다음 행동

Claude는 R1 실패 정리 한 건만 수정하고 해당 안전 회귀 및 관련 실행기 회귀를 제출하라. 수용한 lint/R2/R3/R4를 다시 설계할 필요는 없다. 병합·이슈 종료는 Codex 검토 후 판단한다. 앞서 결정한 Windows 제한 시험과 restricted 추가 검증 1회의 순서는 유지하며, 현재 모델 호출은 요청하지 않는다.

Independent Windows isolated PostgreSQL + Redis: **247 passed, 0 skipped in 142.51s**; disposable stack cleanup completed.

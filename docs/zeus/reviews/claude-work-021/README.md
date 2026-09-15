# PR #73 4차 독립 검토: 수용

대상 head `3a667c743df2e0c1ba9b32b26dcace0f7f388e51`, 런타임 `e3dc3749340eaa53f7755e8c5723ba933656a400`. 이번 범위인 실측 러너의 증거 보존·임시 폴더 정리를 수용한다. 기존 검토의 잔여 두 결함을 독립 반례로 확인했고 추가 병합 차단 결함은 발견하지 않았다.

## 검증

- Windows 실제 격리 PostgreSQL/Redis/Git/프로토콜 자식: **47 passed, skip 0**. 제출 scratch 13개 + runner evidence 23개 + Codex의 누적 독립 반례/대조 11개. 전체 Ruff 통과.
- 실제 모델 호출 0회, 운영 호출 원장 변경 0. 정산 검증은 별도 실제 파일 원장을 사용했다. 검증용 compose 프로젝트 잔여 컨테이너 0개.
- 열거: Path.rglob를 대체하지 않고 os.scandir 경계의 PermissionError를 주입한 기존 반례가 통과한다. 직접 순회에서 거절을 기록하고 incomplete로 처리한다. 파일 크기 조회 실패도 보고된다.
- 정산: 실제 시험 원장 reserve→settle 성공/실패를 단언한다. 정산 실패면 reserved 슬롯을 보존하고 runner_complete/passed=false, 비정상 종료 및 슬롯을 가리키는 복구 보고가 나온다. 보존 실패 후 정산 성공 대조도 통과한다.
- 이전 ID별 증거 보존, 재실행 덮어쓰기 방지, 상한/필수 참조, 목적지 생성 실패, 늦은 수집 예외 반례도 통과한다.
- environment-runs-014: 두 호스트 stdout/stderr/JUnit hash·identity_stable, 런타임→최종 head의 src/scripts/uv.lock 차이 없음 확인. Windows 1735 passed/14 skipped, WSL 1737 passed/12 skipped 및 양쪽 Docker 17 passed는 **제공 영수증 검증 결과**이며 전체 스위트 독립 재실행 수치가 아니다.

## CI 재시도 및 잔여 환경 작업

최종 10개 check SUCCESS. push 34936631645와 PR 34936634459 모두 attempt=2이며, 두 run 모두 1차 integration이 실패했다. 최초 로그를 직접 확인했다.

- PR run: `test_postgres_pause_is_not_a_clock_step[2]`에서 `server closed the connection unexpectedly`.
- push run: `test_host_probe_never_falls_back_to_public_tasks`에서 `FATAL: the database system is starting up`.

두 증상을 같은 근본 원인으로 확정하지 않는다. 해당 disposable 서비스 검사에서 새 scratch 코드를 사용하지 않으며, 기존 별도 환경 신뢰성 작업에 이어서 조사한다. 파일 미변경만으로 원인 독립성을 증명했다고 주장하지 않는다. WSL 최근 통과도 이전 준비 실패 해결의 증거는 아니다.

## 후속 지시 및 이슈 판단

PR #73은 이 head를 고정해 병합한다. #18/#20 전체 운영·자격 조건은 아직 남아 있으므로 종료하지 않고 이번 수용 및 잔여를 댓글과 로컬 원장에 동기화한다. 과거 삭제된 execution artifact를 복구한 것으로 취급하지 않는다.

Claude의 다음 작업은 `claude-work-018/READINESS-FOLLOWUP.md`에 따른 **별도 환경 준비 신뢰성 개선**이다. WSL 포트 준비 실패에 더해 위 CI 두 증상을 구분하고 TCP 연결 성공 이후 실제 PostgreSQL 질의 가능 시점까지 측정한다. 고정한 반복 계획의 모든 시도를 남기며 녹색까지 재시도하거나 준비 기한만 늘리는 방식으로 수용을 대체하지 않는다. 모델 호출·재부팅·WSL 종료·Docker Desktop 재시작·운영 컨테이너 변경 없이 조사·구현·검증해 별도 PR로 제출한다. U003 및 상시 무인 운영 전환은 아직 아니다.

# PR #73 독립 검토: 수정 요청

검토 대상: `b9d534575246689ff0f532ec920453e9639275f3`, 런타임 `6d2bc2bf75971d445b08989596e97558811eb828`. 2026-09-15. 병합·이슈 종료·U003 착수 없음. 분석·수용 기준은 Codex, 구현·수정은 Claude.

읽기 전용 Git 파일과 열린 핸들을 분리한 원인 분석, 실패 산출물 보존은 수용한다. Windows 독립 실행에서 기존 scratch 테스트 13개와 전체 Ruff가 통과했다. 그러나 필수 증거가 보존됐다는 판정에 아래 네 결함이 있어 현재 head는 병합하지 않는다.

## R1 · P1 · 반복 실행이 이전 영수증의 증거를 덮어쓴다

`scripts/claude_real_call.py:preserve_evidence`는 `<label>-evidence`를 재사용하고 `Scratch.preserve`는 고정 이름에 `write_bytes`한다. 실제 호출 영수증은 call1/call2로 구분하면서 증거는 구분하지 않는다. 같은 라벨로 diff `first`, `second`를 차례로 보존하면 둘 다 complete인데 첫 영수증의 digest가 더 이상 맞지 않는다. 기존 파일에 부분 쓰기가 실패해도 이전 증거를 손상시킬 수 있다.

실행 시작 시 만든 고유 실행 ID에 영수증·증거를 함께 결속하고 기존 증거는 덮어쓰지 않는다. 순차 및 동시 재실행, 두 번째 보존 실패 뒤에도 첫 영수증의 모든 참조와 해시가 유지되어야 한다. 숫자를 현재 파일 개수에서만 계산하는 방식은 동시 실행에 충분하지 않다.

## R2 · P1 · 실행 후 수집 실패에서 실제 artifact가 삭제된다

`execute`의 `preservable`은 PG 결과 재조회 및 후속 명령 이후에야 설정된다. 그 전에 예외가 발생하면 `preserve_evidence`는 목록이 없다는 이유로 complete=true / no evidence를 반환하고 finally가 scratch를 지운다.

독립 반례는 실제 PG와 프로토콜 자식으로 Executor 작업이 succeeded가 되고 execution artifact 파일이 존재함을 확인한 다음, 실행 직후 반환 경계에서 수집 예외 하나를 주입한다. 실제 파일은 삭제되고 kept=[]였다. 실행 자체를 가짜 성공으로 바꾸지 않았다. PG 재조회 실패 등에서도 같은 보존 목록 부재 분기로 들어간다.

실행 중 생성한 증거를 점진적으로 추적하고, 실행/증거 생성 여부를 확정하지 못하면 보존 완료로 판정하지 않는다. 실패 경로의 artifact·종료/관측 증거를 보존하거나 scratch를 남겨야 한다. 목록 없음과 실제 생성된 증거 없음은 별개다.

## R3 · P2 · diff 명령 실패를 검증 완료한 빈 diff로 바꾼다

새 `git diff <base> HEAD`의 exit code/timed_out/stderr를 확인하지 않고 stdout만 보존한다. 독립 반례에서 그 명령만 exit=128, 빈 stdout으로 실패시키자 빈 candidate.diff를 hash 검증하고 complete=true로 기록했다. 이것은 성공한 빈 diff와 구별되지 않는다.

필수 증거 생산 명령의 종료 상태를 보존·검증하고 수집 실패는 incomplete로 처리한다. 실패 로그도 남기며 원본은 삭제하지 않는다. 성공한 빈 diff, 비정상 종료, 시간 초과를 구분하는 회귀가 필요하다.

## R4 · P2 · 보존 실패인데 러너가 passed=true / exit=0이다

`call`의 최종 passed 계산에는 required preservation 상태가 없다. 실제 fixture 작업 후 보존 실패만 주입하면 scratch는 올바르게 남지만 러너는 passed=true, exit=0으로 끝난다. 무인 호출자는 이를 성공으로 넘길 수 있다. 정상 모델 실행에서도 accepted/task_verified가 참이면 같은 계산을 사용한다.

작업 자체의 성공과 러너의 증거 수집 완료를 분리해서 기록한다. 필수 증거를 보존하지 못했으면 러너는 비정상 종료하고 복구 대상을 보고해야 한다. 출력 디렉터리 생성·쓰기 실패에서도 최종 보고와 호출 원장 정산이 누락되지 않도록 함께 확인한다.

## 독립 검증 범위

- Windows 기존 `tests/test_scratch_cleanup.py`: 13 passed. `uv run ruff check .`: 통과.
- 첨부 `test_counterexamples.py`: 안전 결과를 요구하는 4건 모두 해당 결함으로 실패. 로그·JUnit 첨부. 실패를 통과 수치로 세지 않는다.
- 실제 격리 PostgreSQL/Redis, Git, 파일시스템 및 프로토콜 자식 프로세스 사용. 실제 모델 호출 0회. 시험용 compose 프로젝트의 잔여 컨테이너 0개 확인.
- Claude의 Windows 및 WSL 3회 영수증: stdout/stderr/JUnit hash, identity_stable, 런타임과 최종 head 사이 src/scripts/uv.lock 차이 없음 확인. 제공 전체 스위트 수치를 독립 재실행한 것으로 주장하지 않는다.
- CI push 34919941821, pull_request 34919943477: 모두 attempt=1, SUCCESS. CI 통과는 위 반례를 해소하지 않는다.

## 별도 판단: WSL readiness

3회 모두 실패한 disposable-docker는 별도 환경 신뢰성 작업으로 다룬다. 현재 수정에 호출 경로가 없고 과거 동일 경계 실패가 기록되어 있으나, 파일 미변경만으로 인과관계가 증명되지는 않는다. 정확한 원인은 미확정이다. 11회 중 7회는 누적 관측치이며 확률 추정이나 악화 원인 증명이 아니다.

후속 수용 기준은 `READINESS-FOLLOWUP.md`에 명시한다. #18/#20은 OPEN 유지. 이 PR의 네 수정 검토와 WSL 운영 자격 판정을 분리하되, WSL 무인 운영 승격에는 이 환경 결함을 남겨두지 않는다.

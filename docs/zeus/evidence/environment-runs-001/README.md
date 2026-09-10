# 호스트별 실제 실행 증거 — Windows 11과 WSL Ubuntu에서 실제 PostgreSQL·Redis로 전체 검증

2026-09-11. main `e2e3235` 를 두 호스트에서 각각 체크아웃해, CI와 같은 명령을 **실제 PostgreSQL(pgvector pg17)·Redis(7.4)** 일회용
Docker 스택 위에서 실행했습니다. 지금까지 Windows 로컬 검증은 PG 검사를 skip하거나(전체 스위트) Redis가 없어 integration 검사가
실패한 상태였고(`test_integration.py` 19 failed / 19 errors), Linux 실행은 GitHub Actions 결과뿐이었습니다. 이 기록은 그 두 공백을
이 PC에서 직접 메운 것입니다. 러너는 [`scripts/environment_evidence.py`](../../../../scripts/environment_evidence.py)이며 영수증과
전체 로그를 이 디렉터리에 둡니다.

## 무엇을 실행했나

각 호스트에서 순서대로:

1. `uv run harness setup` → `docker compose -p <project> up -d --wait postgres redis` (호스트별 별도 프로젝트 이름, 55432/56379 포트를
   공유하므로 순차 실행).
2. `uv run ruff check .`
3. `HARNESS_INTEGRATION=1 uv run python -m pytest -q` — 전체 스위트, PG 격리 스키마·Redis 검사 포함.
4. `HARNESS_INTEGRATION=1 ZEUS_TEST_DOCKER=1 uv run python -m pytest -q tests/test_verification.py tests/test_host_interruption.py` —
   일회용 Docker 스택을 테스트가 직접 만들고 지우는 검사, **PG 컨테이너 일시정지·재시작·중단 중 원장 동작**
   (`test_postgres_pause_is_not_a_clock_step`, `test_postgres_restart_rolls_back_unconfirmed_failure`,
   `test_postgres_outage_cannot_extend_durable_deadline`, `test_host_probe_never_falls_back_to_public_tasks`) 포함.
5. `docker compose -p <project> down --volumes --remove-orphans` (실패 여부와 무관하게 실행, 영수증에 기록).

영수증은 platform·Python·uv·Docker·compose 버전, git head·dirty 여부, 컨테이너 이름/이미지/상태, 단계별 argv·env·exit code·소요 시간·
요약 줄·stdout/stderr sha256, 정리 결과를 담습니다.

## 결과

| 호스트 | 환경 | ruff | 전체 스위트 (PG+Redis) | 일회용 Docker 검사 | 영수증 |
|---|---|---|---|---|---|
| Windows 11 (10.0.26200) | Python 3.12.14, uv 0.12.5, Docker 29.7.2, compose 5.4.0 | 통과 | **1433 passed, 14 skipped** (441s) | **16 passed** (54s) | [windows-11-receipt.json](windows-11-receipt.json) |
| WSL2 Ubuntu 26.04 (kernel 6.18.33.2-microsoft) | Python 3.12.14, uv 0.12.12, Docker 29.7.2, compose 5.4.0 | 통과 | **1439 passed, 8 skipped** (127s) | **16 passed** (47s) | [wsl-ubuntu-26.04-receipt.json](wsl-ubuntu-26.04-receipt.json) |

두 호스트 모두 같은 1447개 검사를 수집했고, skip은 테스트 내부의 환경 판정(예: Windows 전용 PowerShell 런처 검사는 WSL에서, POSIX 전용 격리 검사는 Windows에서 skip)에 따라 Windows 14건·WSL 8건입니다. 두 호스트 모두 스택이 healthy로 올라오고 실행 뒤 컨테이너·볼륨·네트워크가 제거됐습니다(영수증 `stack`/`teardown`). 두 호스트는
같은 Docker Desktop 엔진을 쓰므로 컨테이너 런타임은 공유되고, **파이썬 프로세스·파일시스템·경로·인코딩·프로세스 트리는 각 OS의
것**입니다(Windows NTFS + CRLF 기본, WSL ext4 + LF).

## 이 기록이 채우는 잔여 조건과 채우지 않는 것

이슈 잔여 조건([ticket-closure-001](../../ticket-closure-001/README.md)) 중 "Windows/Linux/WSL의 실제 경로·프로세스·PG·재시작 환경에서
검증" 항목에 대해, **이 PC의 Windows와 WSL Ubuntu 두 호스트에서 실제 PG·Redis·프로세스로 스위트 전체가 통과했다**는 사실을 제공합니다
(#16 다중 파일 crash/lost-ack, #17 pane 로그 수집·중단·재개, #21 PG·프로세스·시계 재시험/동시성, #23 경로·프로세스 트리·PG 재시작·stale
authority, #26 훅 설치·격리 실패 경로, #12 producer→validator→reader 검사의 호스트별 실행 영수증, #18 중 "WSL/Docker 중단 복구"의
PG 컨테이너 일시정지·재시작 부분).

제공하지 않는 것:
- 네이티브 Linux 호스트(WSL2가 아닌 실제 Linux)와 macOS. Linux는 여전히 GitHub Actions(ubuntu-latest) 결과만 있습니다.
- 이 PC의 **절전·재부팅**(#18). 이 작업에서 재부팅하지 않았습니다. 세션이 끊기므로 사용자가 직접 수행해야 하는 항목입니다.
- 사람의 인수, 실제 제품·기기·금전 시나리오, 실제 모델 자격 이전(#13/#14/#15/#19/#20/#24/#25/#27/#28/#29/#31/#32/#33). 테스트 fixture는
  그 증거가 아닙니다.
- 이슈 종료 판정. 종료는 Codex의 서명 정책 경로(PR #68)로만 이루어집니다.
